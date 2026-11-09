"""Windows-only platform layer: window lookup, window rectangle, click-through overlay flags.

Everything that touches user32/dwmapi lives here and is imported lazily, so the rest of
`vision` (and CI on Linux) can import without Windows. Functions raise `PlatformUnavailable`
off Windows instead of failing at import time.
"""
from __future__ import annotations

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
        found.append(WindowInfo(int(hwnd), buf.value, window_rect(int(hwnd)),
                                bool(user32.IsIconic(hwnd))))
        return True

    user32.EnumWindows(visit, 0)
    return found


def find_window(title_contains: str = "Blender") -> WindowInfo | None:
    """Largest non-minimized visible window whose title contains the text (case-insensitive)."""
    needle = title_contains.lower()
    hits = [w for w in list_windows() if needle in w.title.lower() and not w.minimized]
    return max(hits, key=lambda w: w.rect.w * w.rect.h, default=None)


def make_click_through(hwnd: int) -> None:
    """Apply click-through, always-on-top, no-focus, no-taskbar flags to an overlay window."""
    _require_windows()
    import ctypes
    user32 = ctypes.windll.user32
    get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_ = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    set_(hwnd, GWL_EXSTYLE, apply_style_flags(get(hwnd, GWL_EXSTYLE)))
    exclude_from_capture(hwnd)


WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_from_capture(hwnd: int) -> bool:
    """Keep the overlay out of screen captures, so our own labels are never read back by OCR.

    Needs Windows 10 2004 or later; returns False (and the overlay still works) if refused."""
    _require_windows()
    import ctypes
    return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
