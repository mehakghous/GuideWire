"""Check the toolbar guidance, the header menus and the mode dropdown against a REAL Blender window, with ground truth that does not come from the code under test.

    python scripts/vision_live_suite.py            # starts its own Blender (about 1.5 minutes), checks, closes it
    python scripts/vision_live_suite.py --keep     # leave that Blender open afterwards

For each scenario a driver running inside that Blender (scripts/live_driver_blender.py) sets the mode, scrolls the toolbar, opens or hides the sidebar and toolbar, and makes one tool the ACTIVE tool. Blender
draws the active tool's cell in blue: so the real location of that tool's cell is known without trusting the alignment. The suite then asks the grounders for the same tool and compares: the rectangle must
sit on the blue cell. Other scenarios check what must NOT be pointed at: a tool scrolled out of the toolbar, a toolbar that is hidden, a tool that belongs to another mode.

It brings its own Blender window to the front (it must not be covered), simulates no input, and touches no other window. Run it from the project's venv, without a Qt application in the process.
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

TOOLS = {
    "loop_cut": ("builtin.loop_cut", "Loop Cut"), "rip_region": ("builtin.rip_region", "Rip Region"), "extrude_region": ("builtin.extrude_region", "Extrude Region"),
    "select_box": ("builtin.select_box", "Select Box"), "bevel": ("builtin.bevel", "Bevel"), "move": ("builtin.move", "Move"),
}


class Results:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, scenario: str, ok: bool, text: str) -> None:
        self.rows.append((scenario, "PASS" if ok else "FAIL", text))
        print(f"  {'PASS' if ok else 'FAIL'}  {text}", flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r[1] == "FAIL")


def launch(tmp: Path, size: str = "1366x700"):
    from verification.runner import find_app
    inst = find_app("blender")
    if inst is None:
        raise SystemExit("Blender is not installed (set GW_BLENDER to its executable)")
    blend = tmp / "empty.blend"
    subprocess.run([inst.exe, "-b", "--factory-startup", "--python-expr", f"import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'{blend}')"], capture_output=True, timeout=120)
    scenario, quit_flag = tmp / "scenario.json", tmp / "quit.flag"
    proc = subprocess.Popen([inst.exe, "--factory-startup", "--window-geometry", "0", "40", *size.split("x"), str(blend), "--python", str(ROOT / "scripts" / "live_driver_blender.py"), "--", str(scenario), str(quit_flag)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return proc, scenario, quit_flag


def bring_to_front(pid: int) -> None:
    import ctypes

    from vision import winplatform
    win = winplatform.find_window("Blender", ("blender",), pid)
    if win is not None:
        ctypes.windll.user32.SetForegroundWindow(win.hwnd)


def read_scenario(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def blue_cell(ctx):
    """The toolbar cell Blender draws in blue, in screen pixels (None if there is none): where the active tool REALLY is."""
    from vision.toolbar import find_cells
    ui, mp = ctx.ui, ctx.mapper
    tools, viewport = ui.region("VIEW_3D", "TOOLS"), ui.region("VIEW_3D", "WINDOW")
    if tools is None or viewport is None:
        return None
    tb = mp.to_frame(tools.rect)
    for c in find_cells(ctx.pixels, mp.to_frame(viewport.rect)):
        if c.active and tb.y - 2 <= c.rect.y and c.rect.y + c.rect.h <= tb.y + tb.h + 2:
            return ctx.frame_to_screen(c.rect)
    return None


def overlap(a, b) -> float:
    x0, y0, x1, y1 = max(a.x, b.x), max(a.y, b.y), min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(x1 - x0, 0) * max(y1 - y0, 0)
    return inter / float(a.w * a.h + b.w * b.h - inter) if inter else 0.0


def save_fixture(dest: Path, scn: dict, ctx, observed: dict) -> None:
    """Keep what the grounders saw in this scenario (the left strip of the frame as a PNG and the add-on's snapshot) so a failure can be reproduced offline, and so tests can use REAL frames."""
    import cv2
    dest.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest / f"{scn['id']}.png"), ctx.pixels[:, :220])
    keep = {k: observed[k] for k in ("mode", "active_tool", "ui", "tools", "ui_rev", "scene_rev", "snapshot_version", "blender_version") if k in observed}
    mp = ctx.mapper
    keep["capture"] = {"client": [mp.client.x, mp.client.y, mp.client.w, mp.client.h], "frame": [mp.frame.x, mp.frame.y, mp.frame.w, mp.frame.h], "image": [mp.image_w, mp.image_h]} if mp else None
    keep["scenario"] = {k: scn[k] for k in ("id", "mode", "scroll", "tool", "toolbar", "sidebar")}
    (dest / f"{scn['id']}.json").write_text(json.dumps(keep), encoding="utf-8")


def check(scn: dict, svc, res: Results, fixtures: Path | None = None) -> None:
    from shared.step_record import TargetRef
    from vision import grounders as g
    from vision.verify import gate
    sid = scn["id"]
    t0 = time.perf_counter()
    observed, ctx = svc.look()
    ms = (time.perf_counter() - t0) * 1000
    if ctx is None:
        res.add(sid, False, "the window was not visible (covered or minimized?)")
        return
    if fixtures is not None and ctx.ui is not None:
        save_fixture(fixtures, scn, ctx, observed)
    res.add(sid, ctx.ui is not None and ctx.mapper is not None, f"the add-on's snapshot fits this frame (mapping valid); the look took {ms:.0f} ms")
    if ctx.ui is None:
        return
    active_id, label = scn["tool"], next(v[1] for v in TOOLS.values() if v[0] == scn["tool"])
    ref = TargetRef(kind="tool", label=label, id=active_id, mode="EDIT_MESH")
    got = g.ground_tool(ctx, ref)
    gated = gate(got)
    truth = blue_cell(ctx) if scn["toolbar"] else None
    if scn["mode"] == "EDIT" and scn["toolbar"]:
        if truth is not None:                                               # the active tool's cell is on screen: the rectangle must be that cell
            score = overlap(gated.result.rect, truth) if (gated.ok and gated.result.rect) else 0.0
            res.add(sid, got.state == g.VISIBLE and gated.ok and score >= 0.6,
                    f"{label} is the ACTIVE tool, so its cell is blue at {truth}: grounded as {got.state}, rectangle {got.rect} overlaps the blue cell by {score:.0%}; confidence {got.confidence}; evidence: {' | '.join(got.evidence)}")
        else:                                                               # no blue cell on screen: the active tool is scrolled out, and the grounder must say so instead of pointing at some other cell
            res.add(sid, got.state == g.OFFSCREEN and gated.result.rect == got.rect and got.direction in ("up", "down"),
                    f"{label} is the ACTIVE tool but no blue cell is on screen (scrolled out): grounded as {got.state} {got.direction} ('{got.note}'); confidence {got.confidence}")
    # what must NOT be pointed at
    for tid, tlabel in (("builtin.rip_region", "Rip Region"), ("builtin.select", "Tweak"), ("builtin.loop_cut", "Loop Cut")):
        if scn["mode"] != "EDIT" or not scn["toolbar"] or tid == active_id:
            continue
        other = g.ground_tool(ctx, TargetRef(kind="tool", label=tlabel, id=tid, mode="EDIT_MESH"))
        og = gate(other)
        if other.state == g.OFFSCREEN:
            res.add(sid, og.ok and other.direction in ("up", "down") and og.result.rect is not None and "scroll the toolbar" in other.note, f"{tlabel} is scrolled out of the toolbar: '{other.note}'")
        elif other.state == g.VISIBLE:
            res.add(sid, og.ok and og.result.rect is not None, f"{tlabel} is in view: pointed at {other.rect} (confidence {other.confidence})")
    if not scn["toolbar"]:
        res.add(sid, got.state == g.HIDDEN, f"the toolbar is hidden: {got.state}: '{got.note}'")
    if scn["mode"] == "OBJECT":
        lc = g.ground_tool(ctx, TargetRef(kind="tool", label="Loop Cut", id="builtin.loop_cut", mode="EDIT_MESH"))
        res.add(sid, lc.state == g.WRONG and gate(lc).result.rect is None, f"Loop Cut in Object Mode is not pointed at: {lc.state}: '{lc.note}'")
    # the mode dropdown and the Add menu are found by text inside the headers Blender reported
    area = ctx.ui.area("VIEW_3D")
    header = ctx.mapper.to_screen(area.region("HEADER").rect) if area and area.region("HEADER") else None
    if header is not None and scn["mode"] in ("EDIT", "OBJECT"):
        md = g.ground_mode(ctx, TargetRef(kind="mode", label="Edit Mode" if scn["mode"] == "OBJECT" else "Object Mode", id="EDIT", mode="EDIT_MESH"))
        inside = md.rect is not None and header.x <= md.rect.x and md.rect.x + md.rect.w <= header.x + header.w and header.y <= md.rect.y <= header.y + header.h
        res.add(sid, md.state == g.VISIBLE and inside, f"the mode dropdown was found by the mode it shows now, inside the 3D view's header: {md.state} {md.rect} ('{md.note}')")
        add = g.ground_menu(ctx, TargetRef(kind="menu", label="Cylinder", path=["Add", "Mesh", "Cylinder"]))
        inside = add.rect is not None and header.x <= add.rect.x and add.rect.x + add.rect.w <= header.x + header.w and header.y <= add.rect.y <= header.y + header.h
        res.add(sid, add.state == g.VISIBLE and inside and add.matched == "Add", f"'Add' of Add > Mesh > Cylinder was found in the header: {add.state} {add.rect} ('{add.note}')")


def step6_engine():
    """A session on the 18-step armature tutorial, started and moved to step 6 ("Toolbar > Loop Cut", which starts in Edit Mesh and is done when Loop Cut is the active tool)."""
    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    db = Database(":memory:")
    uid = db.add_user("live@example.com", b"x")
    tid = StepEditor.from_json_file(ROOT / "demo" / "data" / "blender_armature_EBgHRd5tJfE.json").save(db, uid)
    eng = SessionEngine.create(db, uid, tid)
    eng.start()
    while eng.position < 6:
        eng.complete()
    return db, eng


def check_bridge(scn: dict, svc, res: Results, pid: int) -> None:
    """The whole path the app uses (bridge -> step state -> grounders -> gate), for step 6 of the tutorial, in this scenario."""
    from app.vision_bridge import VisionBridge
    from shared.step_record import TargetRef
    from vision import grounders as g
    from vision import winplatform
    from vision.verify import gate
    sid = scn["id"] + " / step 6 through the bridge"

    def finder(_app):
        w = winplatform.find_window("Blender", ("blender",), pid)
        return None if w is None else (w.rect.x, w.rect.y, w.rect.w, w.rect.h)
    db, eng = step6_engine()
    try:
        bridge = VisionBridge(lambda app: svc, window_finder=finder)
        observed, ctx = svc.look()
        if ctx is None or ctx.ui is None:
            res.add(sid, False, "no context")
            return
        lc = g.ground_tool(ctx, TargetRef(kind="tool", label="Loop Cut", id="builtin.loop_cut", mode="EDIT_MESH"))
        gated = gate(lc)
        look = bridge.look(eng.current_step(), "blender")
        tick = bridge.apply(eng, look)
        about = f"phase={tick.phase} state={tick.state} advanced={tick.advanced} rect={tick.rect} hint='{tick.hint}'"
        if scn["tool"] == "builtin.loop_cut" and scn["mode"] == "EDIT":
            res.add(sid, tick.advanced and tick.phase == "verified", f"Loop Cut is already the active tool: the step is seen done by the application, not before ({about})")
        elif scn["mode"] == "OBJECT":
            res.add(sid, tick.phase == "blocked" and "Edit Mode" in tick.hint, f"in Object Mode the step is blocked and says to switch mode ({about})")
        elif not scn["toolbar"]:
            res.add(sid, tick.phase == "hidden" and "toolbar is hidden" in tick.hint, f"with the toolbar hidden the step says so ({about})")
        elif lc.state == g.VISIBLE and gated.ok:
            res.add(sid, tick.phase == "visible" and tick.rect == (lc.rect.x, lc.rect.y, lc.rect.w, lc.rect.h) and not tick.advanced, f"Loop Cut is in view and not active: it is pointed at, the step is not completed ({about})")
        elif lc.state == g.OFFSCREEN:
            res.add(sid, tick.phase == "hidden" and "scroll the toolbar" in tick.hint and not tick.advanced, f"Loop Cut is scrolled out: the step says which way to scroll ({about})")
        else:
            res.add(sid, tick.phase in ("hidden", "locating") and not tick.advanced, f"not sure where Loop Cut is: no pointer is claimed ({about})")
        if scn["id"] == "edit_top_rip_below":                                           # what a still screen costs: the app looks every half second
            import statistics
            before = (bridge.stats.cache_hits, bridge.stats.looks)
            times = []
            for _ in range(10):
                t0 = time.perf_counter()
                bridge.look(eng.current_step(), "blender")
                times.append((time.perf_counter() - t0) * 1000)
                time.sleep(0.5)
            med = statistics.median(times)
            hits = bridge.stats.cache_hits - before[0]
            res.add(sid, med < 250 and hits >= 7, f"10 looks at a still screen: median {med:.0f} ms (max {max(times):.0f} ms), {hits} of 10 located-again avoided by the cache; time split per look: read {bridge.stats.ms_look / max(bridge.stats.looks, 1):.0f} ms, find {bridge.stats.ms_ground / max(bridge.stats.looks, 1):.0f} ms")
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="leave the Blender window open at the end")
    ap.add_argument("--save-fixtures", type=Path, help="keep, for every scenario, the left strip of the frame and the add-on's snapshot in this folder")
    ap.add_argument("--size", default="1366x700", help="the Blender window size: a shorter window (for example 1366x520) shows fewer tools, so more of them are out of view")
    ap.add_argument("--only", help="comma-separated scenario ids to check (the others still run in Blender but are not judged)")
    a = ap.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    from vision import winplatform
    from vision.service import VisionService
    winplatform.enable_dpi_awareness()
    res = Results()
    with tempfile.TemporaryDirectory() as d:
        proc, scenario, quit_flag = launch(Path(d), a.size)
        try:
            svc = VisionService(app="blender")
            seen = -1
            deadline = time.time() + 240
            while time.time() < deadline:
                scn = read_scenario(scenario)
                if scn is None or scn.get("seq", -1) == seen:
                    time.sleep(0.4)
                    continue
                if scn["id"] == "__end__":
                    break
                seen = scn["seq"]
                print(f"\n[{scn['id']}] mode={scn['mode']} toolbar scrolled {scn['scroll']} steps, tool {scn['tool']}, sidebar {'open' if scn['sidebar'] else 'closed'}", flush=True)
                if scn.get("error"):
                    res.add(scn["id"], False, f"the driver could not set the scenario up: {scn['error']}")
                    continue
                bring_to_front(proc.pid)
                time.sleep(3.5)                                          # Blender's smooth scrolling
                svc.look()                                               # the app looks every half second: the service learns here that the interface changed
                time.sleep(1.5)                                          # and waits until it has not moved for a while before it trusts where the cells are
                svc.reset()
                if a.only and scn["id"] not in a.only.split(","):
                    continue
                check(scn, svc, res, a.save_fixtures)
                if scn["mode"] in ("EDIT", "OBJECT"):
                    check_bridge(scn, svc, res, proc.pid)
        finally:
            if not a.keep:
                quit_flag.write_text("1")
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
    print(f"\n{len(res.rows) - res.failed} passed, {res.failed} failed")
    return 1 if res.failed else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
