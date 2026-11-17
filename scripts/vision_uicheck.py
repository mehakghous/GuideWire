"""Check, on a real Blender window, that the interface rectangles the add-on reports land on the right pixels of a screen capture.

    python scripts/vision_uicheck.py --out ui_check.png        # Blender open, in front, the GuideWire probe add-on enabled

It reads the add-on's interface block (snapshot v2), maps every region onto the captured frame with `vision.uimodel.FrameMapper`, draws them on the picture (blue = areas, green = regions, red = the
toolbar's cells found from pixels) and prints the checks: does the mapping hold (the client area is the size Blender reports), and do the toolbar cells found in the pixels sit inside the
toolbar region Blender reports. Run it with the sidebar open and closed, the toolbar scrolled, and after a resize: every number must still agree.

Read-only. Use the project's venv; no Qt application is needed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="ui_check.png", help="where to write the annotated picture")
    ap.add_argument("--pid", type=int, help="the Blender process to use (default: the one the add-on reports)")
    a = ap.parse_args()

    import cv2

    from vision import uimodel, winplatform
    from vision.capture import grab, mask_occluders
    from vision.probe_client import read_probe
    from vision.toolbar import find_cells

    winplatform.enable_dpi_awareness()
    state = read_probe(app="blender")
    model = uimodel.parse(state)
    if model is None:
        print("FAIL no interface block: is the GuideWire probe add-on (version 0.2 or later) enabled in Blender?")
        return 1
    win = winplatform.find_window("Blender", ("blender",), a.pid or model.pid)
    if win is None:
        print("FAIL no visible Blender window of that process (not minimized, not on another desktop)")
        return 1
    client = winplatform.client_rect(win.hwnd)
    frame = grab(win.rect)
    pixels = mask_occluders(frame.pixels, win.rect, winplatform.windows_above(win.hwnd))
    mp = uimodel.mapper_for(model, client, win.rect, pixels.shape[1], pixels.shape[0])
    print(f"window {model.window_w}x{model.window_h} (add-on)  client {client.w}x{client.h} at ({client.x},{client.y})  frame {win.rect.w}x{win.rect.h} at ({win.rect.x},{win.rect.y})  ui_rev {model.ui_rev}")
    print("PASS mapping valid" if mp.valid else "FAIL mapping NOT valid: the add-on's window size and the capture differ (resized meanwhile? other display scaling?)")
    out = pixels.copy()
    for area in model.areas:
        r = mp.to_frame(area.rect)
        cv2.rectangle(out, (r.x, r.y), (r.x + r.w, r.y + r.h), (255, 120, 0), 2)
        for reg in area.regions:
            q = mp.to_frame(reg.rect)
            cv2.rectangle(out, (q.x, q.y), (q.x + q.w, q.y + q.h), (0, 200, 0), 1)
            cv2.putText(out, f"{area.type[:6]}.{reg.type[:6]}", (q.x + 3, q.y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 0), 1)
    ok = mp.valid
    viewport, toolbar = model.region("VIEW_3D", "WINDOW"), model.region("VIEW_3D", "TOOLS")
    if viewport is not None and toolbar is not None:
        tb = mp.to_frame(toolbar.rect)
        cells = find_cells(pixels, mp.to_frame(viewport.rect))
        inside = [c for c in cells if tb.x - 4 <= c.rect.x and c.rect.x + c.rect.w <= tb.x + tb.w + 4 and tb.y - 4 <= c.rect.y and c.rect.y + c.rect.h <= tb.y + tb.h + 4]
        for c in cells:
            cv2.rectangle(out, (c.rect.x, c.rect.y), (c.rect.x + c.rect.w, c.rect.y + c.rect.h), (0, 0, 255), 2)
        good = bool(cells) and len(inside) == len(cells)
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} toolbar: {len(cells)} cells found in the pixels, {len(inside)} inside the toolbar region the add-on reports ({tb.x},{tb.y} {tb.w}x{tb.h})")
        scroll = (toolbar.view_top, toolbar.view_bottom)
        print(f"     toolbar scroll view {scroll}, tools for mode {model.mode}: {len(model.tool_cell_ids())} cells")
    cv2.imwrite(a.out, out)
    print(f"picture written to {a.out}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
