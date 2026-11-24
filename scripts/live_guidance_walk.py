"""Walk a tutorial's steps through a REAL Blender and record what the app's own guidance does at each one: the same resolver, step state, grounders and gate the session uses, on a real screen.

    python scripts/live_guidance_walk.py                      # the default comparison on the Blender leg IK video (PctSMB-RGsM)
    python scripts/live_guidance_walk.py --only v10,v12split  # some of the step lists

For every step the walk sets Blender up the way the step needs it to start (mode, whether the armature exists, which object is active) and looks twice: with the Properties editor on its default tab (what a learner
sees at the start of the step) and with the tab the step names already open (after the learner opened it). Each look is the bridge's own (`VisionBridge.look`), so a rectangle is drawn only when the gate allows it.
It brings its own Blender to the front, simulates no input and touches no other window. Run it from the project's venv, without a Qt application in the process. Takes several minutes.
Results: a table on screen and `runs/results/live_walk_<stamp>.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUNS = ROOT / "runs" / "compare" / "gemini-3.6-flash"
VIDEO = "PctSMB-RGsM"
GUIDED = ("tool", "menu", "mode", "property", "sidebar", "operator_panel", "context_menu")


def step_lists(only: set[str] | None):
    from ingestion.split import split_steps
    from shared.step_record import StepList
    v10 = StepList.model_validate_json((RUNS / "v10-preds_w0" / f"blender_{VIDEO}.json").read_text(encoding="utf-8"))
    v12 = StepList.model_validate_json((RUNS / "v12_w0" / f"blender_{VIDEO}.json").read_text(encoding="utf-8"))
    out = {"v10": v10, "v12": v12, "v12split": split_steps(v12)}
    v14_file = RUNS.parent / "gemini-3.6-flash" / "v14_w0" / f"blender_{VIDEO}.json"
    if v14_file.exists():
        from ingestion.identify import resolve_repeats
        from ingestion.instructions import windows_keys
        v14 = StepList.model_validate_json(v14_file.read_text(encoding="utf-8"))
        windows_keys(v14)                                                     # the app does this to every v14 extraction
        resolve_repeats(v14)
        out["v14"], out["v14split"] = v14, split_steps(v14)
    saved = _saved_tutorial()
    if saved is not None:
        out["saved"] = saved
    return {k: v for k, v in out.items() if not only or k in only}


def _saved_tutorial():
    """The tutorial the learner made from this video in the app (local_data/guidewire.sqlite, tutorial 41), read-only; None when it is not there. Set GW_SAVED_TUTORIAL to another id."""
    import sqlite3

    from shared.step_record import Step, StepList
    db = ROOT / "local_data" / "guidewire.sqlite"
    if not db.exists():
        return None
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute("select record from step where tutorial_id=? order by position", (int(os.environ.get("GW_SAVED_TUTORIAL", "41")),)).fetchall()
    c.close()
    if not rows:
        return None
    return StepList(source_type="youtube", app="blender", video_id=VIDEO, steps=[Step.model_validate_json(r[0]) for r in rows])


def _save_shot(folder: Path, name: str, rect, hint: str) -> None:
    """The screen with the rectangle the guide would draw, so what it points at can be LOOKED at (set GW_SHOTS=saved to keep these for that list)."""
    import cv2
    import mss
    import numpy as np
    folder.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        shot = np.array(sct.grab(sct.monitors[0]))[:, :, :3].copy()
        left, top = sct.monitors[0]["left"], sct.monitors[0]["top"]
    if rect is not None:
        x, y, w, h = (int(v) for v in rect)
        cv2.rectangle(shot, (x - left - 3, y - top - 3), (x - left + w + 3, y - top + h + 3), (0, 0, 255), 3)
    cv2.putText(shot, hint[:110], (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.imwrite(str(folder / f"{name}.png"), shot)


def plan(resolved):
    """Per step: (mode, armature exists, active object, the Properties tab the step names or None). The mode is the step's own, else the one before."""
    rows, carried, armature = [], "OBJECT", False
    for st in resolved:
        text = " ".join([st.goal, *(h.text for h in st.how_to), *(a.ui_element or "" for a in st.actions)]).lower()
        made_here = "single bone" in text or "add > armature" in text or "armature > single bone" in text or "add an armature" in text or "create an armature" in text
        own = next((p.target for p in st.start_state if p.kind == "mode"), None)
        mode = (own or carried).split("_")[0]
        mode = mode if mode in ("OBJECT", "EDIT", "POSE") else "OBJECT"
        end = next((p.target for p in st.expected_state if p.kind == "mode"), None)
        if end:
            carried = end
        elif own:
            carried = own
        if mode != "OBJECT":
            armature = True
        tab = next((a.target.tab for a in st.actions if a.target is not None and a.target.kind == "property" and a.target.tab), None)
        popup = next((a.target.operator for a in st.actions if a.target is not None and a.target.kind == "operator_panel" and a.target.id and a.target.operator), None)
        rows.append((mode, armature, "Armature" if armature else "Leg", tab, popup))
        if made_here:
            armature = True
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated: v10, v12, v12split, v14, v14split, saved")
    ap.add_argument("--size", default="1366x700")
    a = ap.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    import ctypes

    from app.step_state import needs_of
    from app.vision_bridge import VisionBridge
    if os.environ.get("GW_OLD_TARGETS"):                          # compare with an earlier resolver: a copy of ingestion/targets.py from before a change
        import importlib.util
        spec = importlib.util.spec_from_file_location("targets_old", os.environ["GW_OLD_TARGETS"])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["targets_old"] = mod
        spec.loader.exec_module(mod)
        resolve_steps = mod.resolve_steps
    else:
        from ingestion.targets import resolve_steps
    from verification.runner import find_app
    from vision import winplatform
    from vision.service import VisionService
    winplatform.enable_dpi_awareness()
    lists = step_lists(set(a.only.split(",")) if a.only else None)
    jobs = []                                                     # (list name, step index, state key, which: "start" | "ready")
    states: dict[tuple, int] = {}
    if os.environ.get("GW_PLAN_TARGETS"):                          # the resolver that decides which screens to set up (a copy of the current ingestion/targets.py when the code under test is an older checkout)
        import importlib.util
        spec2 = importlib.util.spec_from_file_location("targets_plan", os.environ["GW_PLAN_TARGETS"])
        mod2 = importlib.util.module_from_spec(spec2)
        sys.modules["targets_plan"] = mod2
        spec2.loader.exec_module(mod2)
        current_resolve_steps = mod2.resolve_steps
    else:
        from ingestion.targets import resolve_steps as current_resolve_steps
    resolved = {k: resolve_steps(sl.steps) for k, sl in lists.items()}                 # what the guide is given (an older resolver when GW_OLD_TARGETS is set)
    for k, sl in lists.items():
        for i, (mode, arm, active, tab, popup) in enumerate(plan(current_resolve_steps(sl.steps))):      # the screens to set up are always the ones the CURRENT resolver says each step needs, so an older resolver is judged on the same screens
            for which, t, pop in (("start", "OBJECT", None), ("ready", tab or "OBJECT", None), ("popup", "OBJECT", popup), ("ran", "OBJECT", popup)):
                if (which == "ready" and tab is None) or (which in ("popup", "ran") and popup is None) or (which == "ran" and popup != "armature.parent_clear"):
                    continue
                m_pop = {"armature": "EDIT", "pose": "POSE", "object": "OBJECT"}.get((pop or "").split(".")[0], mode) if pop else mode      # the pop-up belongs to the mode its operator works in
                key = (m_pop, arm, active, t, pop, which == "ran")
                states.setdefault(key, len(states))
                jobs.append((k, i, key, which))
    order = sorted(states, key=lambda s: states[s])
    scenarios = [{"id": f"s{n}", "mode": m, "armature": arm, "active": act, "tab": tab, "popup": None if ran else pop, "popup_key": pop, "ran": ran, "rebuild": True} for n, (m, arm, act, tab, pop, ran) in enumerate(order)]
    print(f"{sum(len(s.steps) for s in lists.values())} steps in {len(lists)} lists need {len(scenarios)} Blender states", flush=True)
    inst = find_app("blender")
    if inst is None:
        raise SystemExit("Blender is not installed (set GW_BLENDER)")
    results = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        blend = tmp / "empty.blend"
        subprocess.run([inst.exe, "-b", "--factory-startup", "--python-expr", f"import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'{blend}')"], capture_output=True, timeout=120)
        states_file, out_file, quit_flag = tmp / "states.json", tmp / "out.json", tmp / "quit.flag"
        states_file.write_text(json.dumps(scenarios), encoding="utf-8")
        proc = subprocess.Popen([inst.exe, "--factory-startup", "--window-geometry", "0", "40", *a.size.split("x"), str(blend), "--python", str(ROOT / "scripts" / "live_driver_walk.py"), "--", str(states_file), str(out_file), str(quit_flag)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            svc = VisionService(app="blender")

            def finder(_app):
                w = winplatform.find_window("Blender", ("blender",), proc.pid)
                return None if w is None else (w.rect.x, w.rect.y, w.rect.w, w.rect.h)
            bridge = VisionBridge(lambda app: svc, window_finder=finder)
            seen, deadline = -1, time.time() + 120 + 90 * len(scenarios)
            while time.time() < deadline:
                try:
                    scn = json.loads(out_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    scn = None
                if scn is None or scn.get("seq", -1) == seen:
                    time.sleep(0.4)
                    continue
                if scn["id"] == "__end__":
                    break
                seen = scn["seq"]
                key = (scn["mode"], scn["armature"], scn["active"], scn["tab"], scn.get("popup_key"), bool(scn.get("ran")))
                print(f"[{scn['id']}] mode={key[0]} armature={key[1]} active={key[2]} tab={key[3]} popup={key[4]}{' (ran)' if key[5] else ''}" + (f"  ERROR {scn['error']}" if scn.get("error") else ""), flush=True)
                w = winplatform.find_window("Blender", ("blender",), proc.pid)
                if w is not None:
                    ctypes.windll.user32.SetForegroundWindow(w.hwnd)
                if w is not None:                                          # a pop-up opens where the mouse is: keep it over Blender's 3D view (the mouse is only moved, never clicked)
                    ctypes.windll.user32.SetCursorPos(int(w.rect.x + w.rect.w * 0.45), int(w.rect.y + w.rect.h * 0.45))
                time.sleep(3.5)
                svc.look()
                time.sleep(1.5)
                svc.reset()
                if os.environ.get("GW_DEBUG_WORDS") and key[4] and not key[5]:
                    from vision.locate import find_phrase
                    _o, c0 = svc.look()
                    print("   words near the pop-up:", [(w.text, round(w.rect.x), round(w.rect.y), round(w.rect.w)) for w in (c0.words if c0 else []) if 150 < w.rect.x < 900 and 150 < w.rect.y < 600][:40], flush=True)
                    print("   hits for 'Clear Parent':", [(round(r.x), round(r.y), round(r.w), round(r.h), round(sc, 2)) for r, sc in find_phrase(c0.words, "Clear Parent", None, 0.9)] if c0 else None, flush=True)
                for k, i, jk, which in jobs:
                    if jk != key:
                        continue
                    step = resolved[k][i]
                    bridge.reset()
                    look = bridge.look(step, "blender")
                    needs = [n for n in needs_of(step) if n.kind in GUIDED]
                    results.append({"list": k, "step": i + 1, "goal": step.goal[:70], "when": which, "needs": [f"{n.kind}:{' > '.join(n.path or [n.label])}" for n in needs],
                                    "rect": look.rect, "phase": look.phase, "target": look.target, "hint": (look.hint or "")[:140]})
                    if look.rect and os.environ.get("GW_SHOTS") and k in os.environ["GW_SHOTS"].split(","):
                        _save_shot(ROOT / "runs" / "results" / "live_walk_images", f"{k}_step{i + 1:02d}_{which}", look.rect, look.hint)
                    print(f"   {k:9} step {i + 1:2} {which:5} rect={'YES' if look.rect else 'no '} {look.phase or '':9} -> {look.target or ''}   [Blender mode {(look.observed or {}).get('mode')}]", flush=True)
                (tmp / "out.json.ack").write_text(str(scn["seq"]), encoding="utf-8")
        finally:
            quit_flag.write_text("1")
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = ROOT / "runs" / "results"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"live_walk_{stamp}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nsaved runs/results/live_walk_{stamp}.json")
    for k in lists:
        rs = [r for r in results if r["list"] == k]
        steps_with_need = {r["step"] for r in rs if r["needs"]}
        got = {r["step"] for r in rs if r["rect"]}
        print(f"{k:9} {len(lists[k].steps)} steps; {len(steps_with_need)} have something the guide can find; a rectangle was drawn at {len(got & steps_with_need)} of them (either look)")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
