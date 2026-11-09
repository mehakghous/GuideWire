"""Live guidance through menus: highlight the next thing to click, following the learner's progress.

A tutorial step says "Add > Mesh > Cube". Only "Add" exists on screen until the menu is opened, so
the overlay highlights what is visible now; as the learner opens the menu the highlight moves to
the next item by itself. The overlay never clicks anything and draws no text.

To stay responsive the loop watches a small grayscale thumbnail of the window and, when something
changes, reads only the changed area (a menu opening) and merges it into the words already known.

`guide_marks` and the change helpers are pure. `run_guide` is the live loop (Windows, Qt, OCR).
"""
from __future__ import annotations

from shared.grounding import Rect
from vision.locate import Located, parse_path
from vision.overlay import Mark, highlight_mark

THUMB = (192, 108)        # (w, h) of the grayscale thumbnail used to spot screen changes
PIXEL_DELTA = 24          # grey-level difference that counts as a changed pixel
MIN_CHANGED_CELLS = 3     # ignore isolated flicker
PAD = 48                  # frame pixels added around a changed area before reading it
FULL_READ_SHARE = 0.4     # if more than this share of the window changed, read the whole frame
OCR_SCALE = 1.5


def hint_text(path: list[str], found: Located | None) -> str:
    """What to tell the learner for the current screen (for the app's own panel / the terminal)."""
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
    # Highlight only: no text on screen.
    return [highlight_mark(Rect(window.x + r.x, window.y + r.y, r.w, r.h))]


def click_hits(mark_rect: Rect, point: tuple[int, int] | None) -> bool:
    """True if a click at `point` (screen pixels) landed on the highlighted target."""
    if point is None:
        return False
    x, y = point
    return mark_rect.x <= x < mark_rect.x + mark_rect.w and mark_rect.y <= y < mark_rect.y + mark_rect.h


def changed_box(prev, cur):
    """Bounding box (x0, y0, x1, y1) in thumbnail cells of what changed, or None if nothing did."""
    if prev is None or prev.shape != cur.shape:
        return (0, 0, cur.shape[1], cur.shape[0])
    diff = abs(prev.astype("int16") - cur.astype("int16")) > PIXEL_DELTA
    if int(diff.sum()) < MIN_CHANGED_CELLS:
        return None
    ys, xs = diff.nonzero()
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def union_box(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def box_to_rect(box, frame_w: int, frame_h: int, pad: int = PAD) -> Rect:
    """Thumbnail-cell box -> frame-pixel rect, padded and clipped to the frame."""
    sx, sy = frame_w / THUMB[0], frame_h / THUMB[1]
    x0, y0 = max(int(box[0] * sx) - pad, 0), max(int(box[1] * sy) - pad, 0)
    x1, y1 = min(int(box[2] * sx) + pad, frame_w), min(int(box[3] * sy) + pad, frame_h)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def merge_words(old: list, new: list, region: Rect) -> list:
    """Words known before, minus those inside the re-read region, plus the freshly read ones."""
    def inside(w) -> bool:
        cx, cy = w.rect.x + w.rect.w // 2, w.rect.y + w.rect.h // 2
        return region.x <= cx < region.x + region.w and region.y <= cy < region.y + region.h
    return [w for w in old if not inside(w)] + new


def run_guide(ui_element: str, title: str = "Blender", seconds: float = 60, interval_ms: int = 80,
              recordable: bool = False) -> int:
    import sys
    from concurrent.futures import Future, ThreadPoolExecutor
    from dataclasses import replace

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
    state: dict = {"thumb": None, "rect": None, "box": None}
    cache: dict = {"words": [], "serial": 0}       # touched only by the worker thread
    last: list[str] = []
    target: list[Rect] = []                        # screen rect of the final item while it is highlighted
    result = {"done": False}

    def snapshot(w):
        """Frame of the window with anything covering it blacked out, plus a thumbnail."""
        frame = grab(w.rect)
        px = mask_occluders(frame.pixels, w.rect, winplatform.windows_above(w.hwnd))
        if float((px.max(axis=2) == 0).mean()) > 0.5 and not state.get("warned"):
            state["warned"] = True
            print("Blender is mostly covered by another window: click on Blender to bring it to the front")
        thumb = cv2.resize(cv2.cvtColor(px, cv2.COLOR_BGR2GRAY), THUMB, interpolation=cv2.INTER_AREA)
        return px, thumb

    def work(px, rect: Rect, box, full: bool):
        h, w = px.shape[:2]
        if full or box is None:
            cache["words"] = read_text(px, OCR_SCALE)
        else:
            r = box_to_rect(box, w, h)
            crop = px[r.y:r.y + r.h, r.x:r.x + r.w]
            cache["serial"] += 1
            base = cache["serial"] * 100000          # keep line ids of this read distinct
            fresh = [replace(wd, rect=Rect(wd.rect.x + r.x, wd.rect.y + r.y, wd.rect.w, wd.rect.h),
                             line=wd.line + base) for wd in read_text(crop, 2.0)]
            cache["words"] = merge_words(cache["words"], fresh, r)
        return rect, locate(cache["words"], ui_element)

    def tick() -> None:
        current = winplatform.find_window(title)
        if current is None:
            return
        if pending and pending[0].done():
            rect, found = pending.pop().result()
            if rect == current.rect:                  # window moved or resized meanwhile: drop it
                marks = guide_marks(rect, ui_element, found)
                overlay.set_marks(marks)
                target[:] = [marks[0].rect] if marks and found.complete else []
                text = hint_text(parse_path(ui_element), found)
                if not last or last[-1] != text:
                    print(text)
                    last.append(text)
        if target and click_hits(target[0], winplatform.left_click_position()):
            result["done"] = True                     # the learner clicked the destination
            overlay.set_marks([])
            overlay.hide()
            print(f"Done: clicked {parse_path(ui_element)[-1]}")
            app.quit()
            return
        px, thumb = snapshot(current)
        moved = state["rect"] != current.rect
        state["box"] = union_box(state["box"], changed_box(None if moved else state["thumb"], thumb))
        state["thumb"], state["rect"] = thumb, current.rect
        if state["box"] is not None and not pending:  # read again as soon as the screen changed
            box, state["box"] = state["box"], None
            area = (box[2] - box[0]) * (box[3] - box[1]) / (THUMB[0] * THUMB[1])
            full = moved or area > FULL_READ_SHARE or not cache["words"]
            pending.append(pool.submit(work, px, current.rect, box, full))

    overlay.follow(lambda: (lambda w: w.rect if w else None)(winplatform.find_window(title)))
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(interval_ms)
    QTimer.singleShot(round(seconds * 1000), app.quit)
    print(f"guiding {ui_element!r} for {seconds:g}s: open the menu in Blender and watch the highlight advance")
    code = app.exec()
    if not result["done"]:
        print("Stopped: time ran out before the target was clicked")
    pool.shutdown(wait=False, cancel_futures=True)
    return code
