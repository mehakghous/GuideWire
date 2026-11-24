"""Follow the guide's own highlights, inside menus and panels, in a REAL Blender: look, click the middle of the rectangle the guide drew (what a learner would do), look again, until the guide points at the last
element of the step or stops pointing at anything.

    python scripts/live_follow_walk.py                    # steps 1, 3, 5, 13, 21, 22, 24 of the learner's saved tutorial for the Blender leg IK video
    python scripts/live_follow_walk.py --steps 3,13       # some of them
    GW_SHOTS=1 python scripts/live_follow_walk.py         # keep a screenshot with the rectangle at every look (runs/results/live_follow_images)

This is the one check that SENDS INPUT: it moves the mouse and clicks, only on the throw-away Blender it starts (a scene it builds itself), only where the guide's rectangle is. Do not touch the mouse while it runs.
It does not click the LAST element of a step (that would do the step); it records that the guide got there. Run it from the project venv without a Qt application in the process. Windows only.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("live_guidance_walk", ROOT / "scripts" / "live_guidance_walk.py")
walk = importlib.util.module_from_spec(_spec)
sys.modules["live_guidance_walk"] = walk
_spec.loader.exec_module(walk)

MAX_CLICKS = 8


def click(x: int, y: int) -> None:
    u = ctypes.windll.user32
    u.SetCursorPos(x, y)
    time.sleep(0.4)
    u.mouse_event(0x0002, 0, 0, 0, 0)       # left down
    time.sleep(0.08)
    u.mouse_event(0x0004, 0, 0, 0, 0)       # left up


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", default="1,3,5,13,21,22,24")
    ap.add_argument("--size", default="1366x700")
    a = ap.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    from app.vision_bridge import VisionBridge
    from ingestion.targets import resolve_steps
    from verification.runner import find_app
    from vision import winplatform
    from vision.service import VisionService
    winplatform.enable_dpi_awareness()
    saved = walk._saved_tutorial()
    if saved is None:
        raise SystemExit("the saved tutorial is not in local_data/guidewire.sqlite (GW_SAVED_TUTORIAL=<id>)")
    resolved = resolve_steps(saved.steps)
    rows = walk.plan(resolved)
    wanted = [int(s) for s in a.steps.split(",")]
    scenarios = []
    for n in wanted:
        mode, arm, active, _tab, _popup = rows[n - 1]
        scenarios.append({"id": f"step{n}", "step": n, "mode": mode, "armature": arm, "active": active, "tab": "OBJECT", "popup": None, "rebuild": True})
    inst = find_app("blender")
    if inst is None:
        raise SystemExit("Blender is not installed (set GW_BLENDER)")
    report = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        blend = tmp / "empty.blend"
        subprocess.run([inst.exe, "-b", "--factory-startup", "--python-expr", f"import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'{blend}')"], capture_output=True, timeout=120)
        states, out, quit_flag = tmp / "states.json", tmp / "out.json", tmp / "quit.flag"
        states.write_text(json.dumps(scenarios), encoding="utf-8")
        proc = subprocess.Popen([inst.exe, "--factory-startup", "--window-geometry", "0", "40", *a.size.split("x"), str(blend), "--python", str(ROOT / "scripts" / "live_driver_walk.py"), "--", str(states), str(out), str(quit_flag)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            svc = VisionService(app="blender")

            def finder(_app):
                w = winplatform.find_window("Blender", ("blender",), proc.pid)
                return None if w is None else (w.rect.x, w.rect.y, w.rect.w, w.rect.h)
            bridge = VisionBridge(lambda app: svc, window_finder=finder)
            seen, deadline = -1, time.time() + 120 + 120 * len(scenarios)
            while time.time() < deadline:
                try:
                    scn = json.loads(out.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    scn = None
                if scn is None or scn.get("seq", -1) == seen:
                    time.sleep(0.4)
                    continue
                if scn["id"] == "__end__":
                    break
                seen = scn["seq"]
                n = scn["step"]
                step = resolved[n - 1]
                w = winplatform.find_window("Blender", ("blender",), proc.pid)
                if w is not None:
                    ctypes.windll.user32.SetForegroundWindow(w.hwnd)
                    ctypes.windll.user32.SetCursorPos(int(w.rect.x + w.rect.w * 0.45), int(w.rect.y + w.rect.h * 0.55))
                time.sleep(3.5)
                svc.look()
                time.sleep(1.5)
                svc.reset()
                print(f"\n[step {n}] {step.goal[:70]}", flush=True)
                trail = []
                last = None
                for i in range(MAX_CLICKS + 1):
                    bridge.reset()
                    svc.reset()
                    look = bridge.look(step, "blender")
                    mark = (look.target, look.rect)
                    trail.append({"look": i, "target": look.target, "rect": look.rect, "complete": look.complete, "phase": look.phase, "hint": (look.hint or "")[:120]})
                    print(f"   look {i}: {'RECT' if look.rect else 'none'} {look.phase or '':9} -> {look.target or ''} | {(look.hint or '')[:90]}", flush=True)
                    if os.environ.get("GW_SHOTS"):
                        walk._save_shot(ROOT / "runs" / "results" / "live_follow_images", f"step{n:02d}_look{i}", look.rect, look.hint or "")
                    if not look.rect or look.complete or mark == last or i == MAX_CLICKS:
                        break
                    last = mark
                    x, y, rw, rh = look.rect
                    if (look.hint or "").startswith(("Scroll down", "Viewport Display is open. Scroll", "Display is open")) or "Scroll down in the Properties" in (look.hint or ""):
                        if w is not None:                                       # the guide says to scroll the Properties editor: scroll it (the mouse wheel over that editor), as a learner would
                            ctypes.windll.user32.SetCursorPos(int(w.rect.x + w.rect.w * 0.92), int(w.rect.y + w.rect.h * 0.62))
                            time.sleep(0.4)
                            ctypes.windll.user32.mouse_event(0x0800, 0, 0, ctypes.c_ulong(-360 & 0xFFFFFFFF).value, 0)
                        time.sleep(1.6)
                        continue
                    click(int(x + rw / 2), int(y + rh / 2))
                    time.sleep(1.6)
                report.append({"step": n, "goal": step.goal[:70], "trail": trail, "reached_last": bool(trail and trail[-1]["complete"])})
                (tmp / "out.json.ack").write_text(str(scn["seq"]), encoding="utf-8")
        finally:
            quit_flag.write_text("1")
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    dest = ROOT / "runs" / "results"
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (dest / f"live_follow_{stamp}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("\nsummary")
    for r in report:
        print(f"  step {r['step']:2}: {len(r['trail'])} looks, {'reached the last element' if r['reached_last'] else 'did NOT reach the last element'}: {r['goal']}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
