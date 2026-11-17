"""Runs INSIDE a Blender that `scripts/vision_live_suite.py --launch` started: puts the window through scenarios (mode, toolbar scroll, sidebar, hidden toolbar, active tool) and announces each one in a file, so the
suite can check what GuideWire sees against what Blender really did. It changes only the throw-away Blender it runs in, by script (no input is simulated anywhere), and it loads the GuideWire probe add-on itself.

    blender --factory-startup <empty.blend> --python scripts/live_driver_blender.py -- <scenario.json> <quit-flag-file>
"""
import importlib.util
import json
import os
import sys
import time

import bpy

OUT, QUIT = sys.argv[sys.argv.index("--") + 1], sys.argv[sys.argv.index("--") + 2]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("guidewire_probe", os.path.join(ROOT, "vision", "blender_addon", "guidewire_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
probe.register()

SETTLE = 8.0            # seconds each scenario is held (Blender scrolls smoothly: the picture lags the add-on for about a second)
SCENARIOS = [
    {"id": "edit_top", "mode": "EDIT", "scroll": 0, "tool": "builtin.loop_cut", "toolbar": True, "sidebar": False},
    {"id": "edit_scrolled_2", "mode": "EDIT", "scroll": 2, "tool": "builtin.loop_cut", "toolbar": True, "sidebar": False},
    {"id": "edit_scrolled_6_rip", "mode": "EDIT", "scroll": 6, "tool": "builtin.rip_region", "toolbar": True, "sidebar": False},
    {"id": "edit_scrolled_6_extrude", "mode": "EDIT", "scroll": 6, "tool": "builtin.extrude_region", "toolbar": True, "sidebar": False},
    {"id": "edit_top_rip_below", "mode": "EDIT", "scroll": 0, "tool": "builtin.select_box", "toolbar": True, "sidebar": False, "hold": 18},        # held longer: the suite times 10 looks here
    {"id": "edit_scrolled_6_select_above", "mode": "EDIT", "scroll": 6, "tool": "builtin.select_box", "toolbar": True, "sidebar": False},
    {"id": "edit_sidebar_open", "mode": "EDIT", "scroll": 2, "tool": "builtin.bevel", "toolbar": True, "sidebar": True},
    {"id": "edit_toolbar_hidden", "mode": "EDIT", "scroll": 0, "tool": "builtin.select_box", "toolbar": False, "sidebar": False},
    {"id": "object_mode", "mode": "OBJECT", "scroll": 0, "tool": "builtin.move", "toolbar": True, "sidebar": False},
]
state = {"i": -1, "t": 0.0}


def views():
    win = bpy.context.window_manager.windows[0]
    a3 = next(a for a in win.screen.areas if a.type == "VIEW_3D")
    return win, a3, next(r for r in a3.regions if r.type == "WINDOW"), next((r for r in a3.regions if r.type == "TOOLS"), None)


def apply(sc):
    win, a3, w3, t3 = views()
    space = a3.spaces.active
    with bpy.context.temp_override(window=win, area=a3, region=w3):
        bpy.ops.object.mode_set(mode=sc["mode"])
    space.show_region_toolbar = sc["toolbar"]
    space.show_region_ui = sc["sidebar"]
    win, a3, w3, t3 = views()
    if t3 is not None and t3.width > 1:
        with bpy.context.temp_override(window=win, area=a3, region=t3):
            for _ in range(10):
                bpy.ops.view2d.scroll_up()
            for _ in range(sc["scroll"]):
                bpy.ops.view2d.scroll_down()
    with bpy.context.temp_override(window=win, area=a3, region=w3):
        bpy.ops.wm.tool_set_by_id(name=sc["tool"])            # the cell Blender draws in blue is then this tool's: the ground truth the suite compares against


def tick():
    if os.path.exists(QUIT):
        probe.unregister()
        bpy.ops.wm.quit_blender()
        return None
    now = time.monotonic()
    if now >= state["t"]:
        state["i"] += 1
        if state["i"] >= len(SCENARIOS):
            json.dump({"id": "__end__", "seq": state["i"]}, open(OUT, "w"))
            return 1.0
        sc = SCENARIOS[state["i"]]
        try:
            apply(sc)
            err = None
        except Exception as e:
            err = repr(e)
        json.dump({**sc, "seq": state["i"], "error": err, "applied_at": time.time()}, open(OUT, "w"))
        state["t"] = now + sc.get("hold", SETTLE)
    return 0.5


bpy.app.timers.register(tick, first_interval=2.0)
