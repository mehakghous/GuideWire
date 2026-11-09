"""Live guidance through menus: show the whole path, including options that are not on screen yet.

A tutorial step says "Add > Mesh > Cube". Only "Add" exists on screen until the menu is opened, so
the overlay highlights what is visible now and writes the hidden rest beside it ("then Mesh >
Cube"). Each refresh re-reads the screen, so as the learner opens the menu the highlight moves to
the next item by itself. The overlay never clicks anything.

`guide_marks` is pure. `run_guide` is the live loop (Windows, Qt, OCR).
"""
from __future__ import annotations

from shared.grounding import Rect
from vision.locate import Located, parse_path
from vision.overlay import Mark, highlight_mark


def hint_text(path: list[str], found: Located | None) -> str:
    """What to tell the learner for the current screen."""
    if not path:
        return ""
    if found is None:
        return "Open: " + " > ".join(path)            # nothing visible: show the whole route
    rest = path[found.depth + 1:]
    if not rest:
        return f"Click {found.matched}"
    return f"Click {found.matched}, then " + " > ".join(rest)


def guide_marks(window: Rect, ui_element: str, found: Located | None) -> list[Mark]:
    """Marks (screen coordinates) for a located path. `window` is where the frame sits on screen."""
    if found is None:
        return []
    r = found.rect
    # Highlight only: no text on screen. The wording (hint_text) is for the app's own panel.
    return [highlight_mark(Rect(window.x + r.x, window.y + r.y, r.w, r.h))]


CHANGE_FRACTION = 0.004   # share of (downsampled) pixels that must differ to count as a screen change
OCR_SCALE = 1.5


def frame_changed(prev, cur, fraction: float = CHANGE_FRACTION) -> bool:
    """True when two small grayscale thumbnails differ enough to need a fresh read."""
    if prev is None or prev.shape != cur.shape:
        return True
    return float((abs(prev.astype("int16") - cur.astype("int16")) > 24).mean()) > fraction


def run_guide(ui_element: str, title: str = "Blender", seconds: float = 60, interval_ms: int = 100,
              recordable: bool = False) -> int:
    import sys
    from concurrent.futures import Future, ThreadPoolExecutor

    import cv2
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from vision import winplatform
    from vision.capture import grab, mask_occluders
    from vision.locate import locate
    from vision.ocr import read_text
    from vision.overlay import make_overlay_window

    winplatform.enable_dpi_awareness()
    win = winplatform.find_window(title)
    if win is None:
        print(f"no visible window with '{title}' in its title", file=sys.stderr)
        return 1
    app = QApplication(sys.argv[:1])
    overlay = make_overlay_window()
    overlay.hide_from_capture = not recordable
    overlay.cover(win.rect)
    overlay.show_click_through()
    pool = ThreadPoolExecutor(max_workers=1)
    pending: list[Future] = []
    state: dict = {"thumb": None, "rect": None, "dirty": True}
    last: list[str] = []

    def snapshot(w):
        """Frame of the window with anything covering it blacked out, plus a thumbnail."""
        frame = grab(w.rect)
        px = mask_occluders(frame.pixels, w.rect, winplatform.windows_above(w.hwnd))
        thumb = cv2.resize(cv2.cvtColor(px, cv2.COLOR_BGR2GRAY), (96, 54), interpolation=cv2.INTER_AREA)
        return px, thumb

    def work(px, rect: Rect):
        return rect, locate(read_text(px, OCR_SCALE), ui_element)

    def tick() -> None:
        current = winplatform.find_window(title)
        if current is None:
            return
        if pending and pending[0].done():
            rect, found = pending.pop().result()
            if rect == current.rect:                  # window moved or resized meanwhile: drop it
                overlay.set_marks(guide_marks(rect, ui_element, found))
                text = hint_text(parse_path(ui_element), found)
                if not last or last[-1] != text:
                    print(text)
                    last.append(text)
        px, thumb = snapshot(current)
        if frame_changed(state["thumb"], thumb) or state["rect"] != current.rect:
            state["dirty"] = True
        state["thumb"], state["rect"] = thumb, current.rect
        if state["dirty"] and not pending:            # read again as soon as the screen changed
            state["dirty"] = False
            pending.append(pool.submit(work, px, current.rect))

    overlay.follow(lambda: (lambda w: w.rect if w else None)(winplatform.find_window(title)))
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(interval_ms)
    QTimer.singleShot(round(seconds * 1000), app.quit)
    print(f"guiding {ui_element!r} for {seconds:g}s: open the menu in Blender and watch the highlight advance")
    code = app.exec()
    pool.shutdown(wait=False, cancel_futures=True)
    return code
