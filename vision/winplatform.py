"""Windows-only platform layer: window lookup, window rectangle, click-through overlay flags.

Everything that touches user32/dwmapi lives here and is imported lazily, so the rest of
`vision` (and CI on Linux) can import without Windows. Functions raise `PlatformUnavailable`
off Windows instead of failing at import time.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from shared.grounding import Rect

# Extended window styles (winuser.h).
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020      # mouse input falls through to the window below
WS_EX_TOOLWINDOW = 0x00000080       # no taskbar button, hidden from Alt+Tab
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000       # never takes focus from Blender
GWL_EXSTYLE = -20

CLICK_THROUGH_FLAGS = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
                       | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

DWMWA_EXTENDED_FRAME_BOUNDS = 9


class PlatformUnavailable(RuntimeError):
    """Raised when a Windows-only call is made on another platform."""


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: Rect          # visible frame in virtual-desktop physical pixels (no invisible resize border)
    minimized: bool
    pid: int = 0        # owning process
    exe: str = ""       # that process's program file name, lower case ("blender.exe"); "" when it cannot be read


def _require_windows() -> None:
    if sys.platform != "win32":
        raise PlatformUnavailable("this call needs Windows")


def apply_style_flags(current: int) -> int:
    """Pure: the extended style a click-through overlay should have, given the current one."""
    return current | CLICK_THROUGH_FLAGS


def enable_dpi_awareness() -> None:
    """Make coordinates physical pixels. Call once at startup, before any window exists."""
    _require_windows()
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def window_rect(hwnd: int) -> Rect:
    """Visible frame of a window. GetWindowRect includes an invisible ~8px border on Win10/11."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    if hr != 0:
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def client_rect(hwnd: int) -> Rect | None:
    """The drawable (client) area of a window in virtual-desktop physical pixels: where the application's own pixels start, below the title bar and inside the borders. None when it cannot be read.
    Blender's window size and region rectangles are relative to this, not to `window_rect` (measured: 1366x697 at (0, 31) inside a 1368x729 frame)."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    r, pt = wintypes.RECT(), wintypes.POINT(0, 0)
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(r)) or not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt)):
        return None
    return Rect(pt.x, pt.y, r.right - r.left, r.bottom - r.top)


def process_exe(pid: int) -> str:
    """The program file name of a process ("blender.exe"), lower case, or "" when it cannot be read (a protected process)."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value).lower() if ok else ""
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    """True while a process with this id is running. A process that cannot be opened because it is protected counts as running (it exists); one that no longer exists, or has exited, does not."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return kernel32.GetLastError() == 5                                                # access denied: it exists
    try:
        code = wintypes.DWORD(0)
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259       # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def list_windows() -> list[WindowInfo]:
    """Visible top-level windows that have a title."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(WindowInfo(int(hwnd), buf.value, window_rect(int(hwnd)), bool(user32.IsIconic(hwnd)), pid.value, process_exe(pid.value)))
        return True

    user32.EnumWindows(visit, 0)
    return found


def _own_window_covers(user32, h) -> bool:
    """Whether a window of THIS process hides pixels of the application from a capture. Our click-through overlay does not (it is transparent: its marks are drawn by us, the pixels below stay
    readable) and masking it would blank the whole window. The guide box and the main window do, unless they were excluded from capture, in which case the capture sees through them."""
    ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
    if ex & WS_EX_TRANSPARENT:
        return False
    import ctypes
    affinity = ctypes.c_uint(0)
    if user32.GetWindowDisplayAffinity(h, ctypes.byref(affinity)) and affinity.value == WDA_EXCLUDEFROMCAPTURE:
        return False
    return True


def windows_above(hwnd: int) -> list[Rect]:
    """Screen rects of visible windows stacked above `hwnd` that hide part of it from a capture: other applications' windows, and our own guide box and main window (not the click-through overlay)."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    out: list[Rect] = []
    state = {"seen": False}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(h, _lparam):
        if int(h) == hwnd:
            state["seen"] = True
            return False                      # EnumWindows runs top of the stack first
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        own = pid.value == os.getpid()
        if own and not _own_window_covers(user32, h):
            return True
        if user32.IsWindowVisible(h) and not user32.IsIconic(h) and (own or user32.GetWindowTextLengthW(h) > 0):       # our own boxes may have no title; other processes' untitled windows are helpers
            cloaked = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(h), 14, ctypes.byref(cloaked), 4)
            if not cloaked.value:
                out.append(window_rect(int(h)))
        return True

    user32.EnumWindows(visit, 0)
    return out if state["seen"] else []


def pick_window(windows: list[WindowInfo], title_contains: str = "Blender", exe: tuple[str, ...] = (), pid: int | None = None) -> WindowInfo | None:
    """The application's main window among `windows`. Pure.

    A title alone is not enough: a browser tab called "Get Involved - Blender" matched "Blender" and could win by size. So when `pid` or `exe` is given the window must belong to that process (`exe` is a list of
    substrings of the program file name, such as ("blender",)); the title is then only a tie-break filter. With neither, the old rule applies (title text only), for applications whose program name is not checked yet.
    The largest non-minimized match wins."""
    needle = title_contains.lower()
    hits = [w for w in windows if needle in w.title.lower() and not w.minimized]
    if pid is not None:
        hits = [w for w in hits if w.pid == pid]
    if exe:
        hits = [w for w in hits if any(e.lower() in w.exe for e in exe)]
    return max(hits, key=lambda w: w.rect.w * w.rect.h, default=None)


def find_window(title_contains: str = "Blender", exe: tuple[str, ...] = (), pid: int | None = None) -> WindowInfo | None:
    """Largest non-minimized visible window of the application (see `pick_window`)."""
    return pick_window(list_windows(), title_contains, exe, pid)


def idle_seconds() -> float | None:
    """Seconds since the learner last moved the mouse or pressed a key anywhere on the computer (one cheap call), or None when it cannot be read. GuideWire looks often while the learner is
    working and rarely while they are reading or away."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def set_background_priority(on: bool) -> bool:
    """Run GuideWire below normal priority while it watches another application, so that application's own work (Blender redrawing, Maya, Houdini) always comes first on a busy computer."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    return bool(kernel32.SetPriorityClass(ctypes.c_void_p(kernel32.GetCurrentProcess()), 0x4000 if on else 0x20))      # BELOW_NORMAL / NORMAL


_FOUND: dict[tuple, tuple[float, WindowInfo]] = {}
FIND_AGAIN_SECONDS = 2.0


def find_window_cached(title_contains: str = "Blender", exe: tuple[str, ...] = (), pid: int | None = None) -> WindowInfo | None:
    """`find_window`, but the full list of windows (every window and its program file: about 10 ms) is only walked every couple of seconds. In between, the window found last time is checked
    (still there, visible, not minimized) and only its rectangle is read again (a move or a resize shows at once). The guide asks several times a second, so this is most of its saved time."""
    import time
    key = (title_contains, tuple(exe), pid)
    now = time.monotonic()
    hit = _FOUND.get(key)
    if hit is not None and now - hit[0] < FIND_AGAIN_SECONDS:
        w = hit[1]
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if user32.IsWindow(w.hwnd) and user32.IsWindowVisible(w.hwnd) and not user32.IsIconic(w.hwnd):
                return WindowInfo(w.hwnd, w.title, window_rect(w.hwnd), False, w.pid, w.exe)
        except Exception:
            pass
    found = find_window(title_contains, exe, pid)
    if found is None:
        _FOUND.pop(key, None)
    else:
        _FOUND[key] = (now, found)
    return found


def make_click_through(hwnd: int, hide_from_capture: bool = True) -> None:
    """Apply click-through, always-on-top, no-focus, no-taskbar flags to an overlay window."""
    _require_windows()
    import ctypes
    user32 = ctypes.windll.user32
    get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_ = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    set_(hwnd, GWL_EXSTYLE, apply_style_flags(get(hwnd, GWL_EXSTYLE)))
    if hide_from_capture:
        exclude_from_capture(hwnd)


WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_from_capture(hwnd: int) -> bool:
    """Keep the overlay out of screen captures, so our own labels are never read back by OCR.

    Needs Windows 10 2004 or later; returns False (and the overlay still works) if refused."""
    _require_windows()
    import ctypes
    return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


def left_click_position() -> tuple[int, int] | None:
    """Screen position of the cursor while the left mouse button is held, else None.

    Passive polling of the button state; nothing is sent to any window."""
    _require_windows()
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    if not user32.GetAsyncKeyState(0x01) & 0x8000:      # VK_LBUTTON
        return None
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y
