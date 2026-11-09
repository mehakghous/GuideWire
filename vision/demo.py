"""Manual check on a real machine: find Blender, report its areas, draw a highlight on each.

    python -m vision.demo            # window title containing "Blender"
    python -m vision.demo --save frame.png --delay 5
    python -m vision.demo --follow --seconds 30   # drag/resize Blender and watch the boxes follow

Needs Windows, PyQt6, mss, opencv-python and a running Blender at the default layout.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from shared.grounding import Rect
from vision import winplatform
from vision.capture import grab
from vision.overlay import highlight_mark, make_overlay_window
from vision.regions import default_layout, detect_layout


def save_annotated(pixels, layout, frame_path: str) -> str:
    """Write <frame>_annotated.png with each detected area outlined and named."""
    import cv2
    img = pixels.copy()
    for r in layout.regions:
        x, y, w, h = r.rect.x, r.rect.y, r.rect.w, r.rect.h
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 190, 255), 3)
        cv2.putText(img, r.name, (x + 8, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 190, 255), 2)
    out = frame_path.rsplit(".", 1)[0] + "_annotated.png"
    cv2.imwrite(out, img)
    return out


def region_marks(window: Rect, layout) -> list:
    """One labelled highlight per detected area, in screen coordinates."""
    return [highlight_mark(Rect(window.x + r.rect.x, window.y + r.rect.y, r.rect.w, r.rect.h), r.name)
            for r in layout.regions]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Blender")
    ap.add_argument("--save", help="write the captured frame to this PNG")
    ap.add_argument("--delay", type=float, default=0, help="seconds to wait before capturing, to switch to Blender")
    ap.add_argument("--follow", action="store_true", help="keep the boxes on Blender as it is moved or resized")
    ap.add_argument("--seconds", type=float, default=6, help="how long to keep the overlay up")
    ap.add_argument("--locate", help='UI path to find and highlight, e.g. "Add > Mesh > Cube"')
    ap.add_argument("--guide", help='live guidance through a menu path, e.g. "File > Save As"')
    args = ap.parse_args()

    if args.delay > 0:
        print(f"capturing in {args.delay:g}s: switch to Blender now")
        time.sleep(args.delay)
    if args.guide:
        from vision.guide import run_guide
        return run_guide(args.guide, args.title, args.seconds)
    winplatform.enable_dpi_awareness()
    win = winplatform.find_window(args.title)
    if win is None:
        print(f"no visible window with '{args.title}' in its title", file=sys.stderr)
        return 1
    frame = grab(win.rect)
    print(f"window: {win.title!r} {win.rect}  frame: {frame.pixels.shape[1]}x{frame.pixels.shape[0]}")
    if args.save:
        import cv2
        cv2.imwrite(args.save, frame.pixels)

    layout = detect_layout(frame.pixels)
    if layout.confidence < 0.5:
        print(f"low confidence ({layout.confidence:.2f}); using default-layout fractions")
        layout = default_layout(frame.pixels.shape[1], frame.pixels.shape[0])
    for r in layout.regions:
        print(f"  {r.name:<10} {r.rect}")
    if args.save:
        annotated = save_annotated(frame.pixels, layout, args.save)
        print(f"saved {os.path.abspath(args.save)}")
        print(f"saved {os.path.abspath(annotated)} (the same frame with the detected areas drawn on it)")
        os.startfile(os.path.abspath(annotated))  # opens in the default image viewer

    marks = region_marks(win.rect, layout)
    if args.locate:
        from vision.locate import locate
        from vision.observe import observe_blender
        from vision.ocr import read_text
        words = read_text(frame.pixels)
        print("observed:", observe_blender(words, frame.pixels, layout))
        found = locate(words, args.locate)
        if found is None:
            print(f"locate {args.locate!r}: not visible (icon-only or the menu is closed)")
        else:
            note = "" if found.complete else f"  (path not fully open yet: showing step {found.depth + 1} of {found.total})"
            print(f"locate {args.locate!r}: {found.matched!r} at {found.rect}, alternatives={found.alternatives}{note}")
            r = found.rect
            marks = [highlight_mark(Rect(win.rect.x + r.x, win.rect.y + r.y, r.w, r.h), found.matched)]

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    overlay = make_overlay_window()
    overlay.cover(win.rect)
    overlay.set_marks(marks)
    overlay.show_click_through()

    if args.follow:
        def current_rect():
            w = winplatform.find_window(args.title)
            return w.rect if w else None

        def reground():
            rect = current_rect()
            if rect is None:
                return
            lay = detect_layout(grab(rect).pixels)
            print(f"resized to {rect.w}x{rect.h}: confidence {lay.confidence:.2f}")
            overlay.set_marks(region_marks(rect, lay))

        overlay.follow(current_rect, on_resized=reground)
        print(f"following the window for {args.seconds:g}s: move or resize Blender")
    QTimer.singleShot(round(args.seconds * 1000), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
