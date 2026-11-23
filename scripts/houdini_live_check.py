"""Live check of Houdini guidance against a real Houdini window (the Houdini counterpart of scripts/vision_live_suite.py).

    python scripts/houdini_live_check.py OUT_DIR

Needs Houdini open with the GuideWire probe running (in Houdini's Python Shell: import sys; sys.path.append(r"<GuideWire>/vision/probes"); import houdini_probe; houdini_probe.register())
and a network with a Pack Folder (packfolder1) selected so the parameter pane shows it. It takes ONE look through the real vision service (window lookup by program name, probe, screen
reading), grounds each target below through the real gate, prints what it decided, and, only when no window of another program covers Houdini, saves the capture with every box drawn
(OUT_DIR/houdini_live.png) for a person to check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.step_record import TargetRef  # noqa: E402

TARGETS = [
    ("the selected Pack Folder node", TargetRef(kind="node", label="Pack Folder", id="packfolder", path=["packfolder1"])),
    ("a Skeleton node by its type", TargetRef(kind="node", label="Skeleton", id="kinefx::skeleton")),
    ("Tab in the network editor", TargetRef(kind="pane", label="network editor", id="NetworkEditor", keys=["Tab"])),
    ("F in the viewport", TargetRef(kind="pane", label="viewport", id="SceneViewer", keys=["F"])),
    ("parameter Replace Method", TargetRef(kind="parm", label="Replace Method", prop="Replace Method", id="packfolder", panel="Pack Folder")),
    ("parameter Pack Output", TargetRef(kind="parm", label="Pack Output", prop="Pack Output", id="packfolder", panel="Pack Folder")),
    ("parameter Reload Names", TargetRef(kind="parm", label="Reload Names", prop="Reload Names", id="packfolder", panel="Pack Folder")),
    ("a label Pack Folder does not have", TargetRef(kind="parm", label="Target Pattern", prop="Target Pattern", id="packfolder", panel="Pack Folder")),
    ("a parameter of another node", TargetRef(kind="parm", label="Control Group", prop="Control Group", panel="APEX Configure Controls")),
]


def covered(win) -> bool:
    from vision import winplatform
    r = win.rect
    above = [a for a in winplatform.windows_above(win.hwnd) if a.x < r.x + r.w and r.x < a.x + a.w and a.y < r.y + r.h and r.y < a.y + a.h]
    own = [x for x in winplatform.list_windows() if not x.minimized and x.pid == win.pid and any(x.rect == a for a in above)]
    return len(own) < len(above)


def main(out_dir: str) -> int:
    import cv2

    from vision import winplatform
    from vision.grounders import ground_target
    from vision.service import VisionService
    from vision.verify import gate
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    winplatform.enable_dpi_awareness()
    svc = VisionService(app="houdini")
    observed, ctx = svc.look()
    if ctx is None:
        print("no Houdini window found (it must belong to houdini.exe and be visible)")
        return 1
    if not ctx.houdini:
        print("Houdini is visible but the probe sent no interface snapshot: start the probe in Houdini (see the top of this file)")
        return 1
    print("probe:", {k: observed.get(k) for k in ("ui_rev", "scene_rev")}, "network", ctx.houdini.get("network", {}).get("path"), "parameter pane shows", ctx.houdini.get("parm", {}).get("node"),
          "words read", len(ctx.words))
    results = []
    for what, ref in TARGETS:
        g = gate(ground_target(ctx, ref))
        r = g.result
        results.append({"target": what, "state": r.state, "box": g.ok and r.rect is not None, "rect": None if r.rect is None else [r.rect.x, r.rect.y, r.rect.w, r.rect.h],
                        "confidence": r.confidence, "note": r.note, "why": g.reason})
        print(f"  {what:38} {r.state:16} box={'yes' if g.ok and r.rect else 'no ':3}  {r.note}")
    (out / "houdini_live.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    win = winplatform.find_window("Houdini", ("houdini", "happrentice", "hindie"))
    if win is None or covered(win):
        print("capture not saved: a window of another program covers Houdini")
        return 0
    from vision.capture import grab
    img = grab(win.rect).pixels.copy()
    colours = {"node": (0, 0, 255), "pane": (255, 128, 0), "parm": (0, 200, 0)}
    for (what, ref), res in zip(TARGETS, results):
        if res["box"]:
            x, y, w, h = res["rect"]
            cv2.rectangle(img, (x - win.rect.x, y - win.rect.y), (x - win.rect.x + w, y - win.rect.y + h), colours[ref.kind], 2)
    cv2.imwrite(str(out / "houdini_live.png"), img)
    print("saved", out / "houdini_live.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "runs/houdini_live"))
