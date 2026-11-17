"""Time each stage of the screen-reading pipeline against a real Blender window, and check how the window can be captured.

    python scripts/vision_bench.py                 # 8 runs of every stage, medians in milliseconds
    python scripts/vision_bench.py --runs 20 --json out.json
    python scripts/vision_bench.py --diag          # also: PrintWindow vs screen grab, and why hiding a window from capture is refused

Read-only: it captures the screen and reads the probe; it sends no input. Blender must be open and in front (nothing over it).
It is the single harness for "before / after" numbers (docs/vision-research.md): run it before a change and after, same machine, same layout.
Run it in the project's venv, without a Qt application in the same process (the Windows OCR hangs next to one).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def timed(fn, runs: int):
    """(median ms, last result) of calling fn() `runs` times."""
    out, last = [], None
    for _ in range(runs):
        t = time.perf_counter()
        last = fn()
        out.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(out), 1), last


def bench(runs: int, title: str, exe: tuple[str, ...]) -> dict:
    from vision import winplatform
    from vision.capture import grab, mask_occluders
    from vision.ocr import read_text
    from vision.probe_client import read_probe
    from vision.regions import default_layout, detect_layout
    from vision.toolbar import find_cells

    winplatform.enable_dpi_awareness()
    res: dict = {"runs": runs, "stages_ms": {}}
    ms, win = timed(lambda: winplatform.find_window(title, exe), runs)
    if win is None:
        raise SystemExit(f"no visible window with '{title}' in its title (open Blender in front)")
    res["stages_ms"]["find_window"] = ms
    res["window"] = [win.rect.x, win.rect.y, win.rect.w, win.rect.h]
    ms, above = timed(lambda: winplatform.windows_above(win.hwnd), runs)
    res["stages_ms"]["windows_above"] = ms
    ms, frame = timed(lambda: grab(win.rect), runs)
    res["stages_ms"]["grab"] = ms
    ms, pixels = timed(lambda: mask_occluders(frame.pixels, win.rect, above), runs)
    res["stages_ms"]["mask"] = ms
    res["covered_share"] = round(float((pixels.max(axis=2) == 0).mean()), 3)           # near 1.0: something covers Blender, the numbers below mean nothing
    ms, layout = timed(lambda: detect_layout(pixels), runs)
    res["stages_ms"]["detect_layout"] = ms
    res["layout_confidence"] = layout.confidence
    view = (layout if layout.confidence >= 0.5 else default_layout(pixels.shape[1], pixels.shape[0])).get("viewport")
    if view is not None:
        ms, cells = timed(lambda: find_cells(pixels, view), runs)
        res["stages_ms"]["find_cells"] = ms
        res["toolbar_cells"] = len(cells)
    ms, words = timed(lambda: read_text(pixels), max(2, runs // 2))
    res["stages_ms"]["ocr_full_frame"] = ms
    res["words"] = len(words)
    h, w = pixels.shape[:2]
    ms, _ = timed(lambda: read_text(pixels[h // 4:h // 4 + 400, w // 4:w // 4 + 500], 2.0), runs)
    res["stages_ms"]["ocr_changed_area_500x400"] = ms
    ms, probe = timed(lambda: read_probe(app="blender"), runs)
    res["stages_ms"]["probe_read"] = ms
    res["probe_running"] = probe is not None
    return res


def diag(title: str, exe: tuple[str, ...]) -> dict:
    """How the window can be captured, and whether a window of ours can be kept out of a capture."""
    import ctypes
    from ctypes import wintypes

    import mss
    import numpy as np

    from vision import winplatform

    winplatform.enable_dpi_awareness()
    win = winplatform.find_window(title, exe)
    if win is None:
        raise SystemExit(f"no visible window with '{title}' in its title")
    out: dict = {}
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    # 1. PrintWindow of the window itself (works while it is covered) vs the screen grab
    r = wintypes.RECT()
    user32.GetClientRect(win.hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    ok = user32.PrintWindow(win.hwnd, mem, 0x3)          # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    buf = ctypes.create_string_buffer(w * h * 4)

    class BMI(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("w", wintypes.LONG), ("h", wintypes.LONG), ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("comp", wintypes.DWORD), ("img", wintypes.DWORD),
                    ("xp", wintypes.LONG), ("yp", wintypes.LONG), ("used", wintypes.DWORD), ("imp", wintypes.DWORD)]
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(BMI(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
    pw = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3]
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(win.hwnd, ctypes.byref(pt))
    with mss.mss() as sct:
        shot = sct.grab({"left": pt.x, "top": pt.y, "width": w, "height": h})
    sg = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(h, w, 4)[:, :, :3]
    out["client_size"] = [w, h]
    out["client_origin_on_screen"] = [pt.x, pt.y]
    out["window_rect_used_by_vision"] = [win.rect.x, win.rect.y, win.rect.w, win.rect.h]
    out["printwindow_ok"] = bool(ok)
    out["printwindow_black_share"] = round(float((pw.max(axis=2) == 0).mean()), 3)
    out["printwindow_vs_screen_mean_abs_diff"] = round(float(np.abs(pw.astype("int16") - sg.astype("int16")).mean()), 2)
    # 2. why hiding our own window from capture is refused: try on a plain window of this process
    from PyQt6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication(sys.argv[:1])
    probe = QWidget()
    probe.show()
    hwnd = int(probe.winId())
    for name, flag in (("WDA_EXCLUDEFROMCAPTURE", 0x11), ("WDA_MONITOR", 0x1)):
        ctypes.windll.kernel32.SetLastError(0)
        res = user32.SetWindowDisplayAffinity(hwnd, flag)
        out[f"display_affinity_{name}"] = {"ok": bool(res), "last_error": ctypes.windll.kernel32.GetLastError()}
    probe.close()
    del app
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--title", default="Blender")
    ap.add_argument("--diag", action="store_true", help="also check PrintWindow capture and the capture-exclusion flag (loads Qt: run it after the timings)")
    ap.add_argument("--front", action="store_true", help="bring Blender to the front first (only for a Blender you started for the test: it covers whatever is on screen)")
    ap.add_argument("--json", help="write the result to this file")
    a = ap.parse_args()
    if a.front:
        from vision import winplatform
        win = winplatform.find_window(a.title, ("blender",))
        if win is not None:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(win.hwnd)
            time.sleep(1.0)
    result = bench(a.runs, a.title, ('blender',))
    if a.diag:
        result["diag"] = diag(a.title, ('blender',))
    text = json.dumps(result, indent=1)
    print(text)
    if a.json:
        Path(a.json).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
