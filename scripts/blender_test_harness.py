"""Live-check harness: run INSIDE Blender (blender --factory-startup --python scripts/blender_test_harness.py). Loads the GuideWire probe and runs any python file
dropped in %TEMP%/blenderrun/ on Blender's main thread, so a test can make the "learner's" changes (delete the cube, enter Edit Mode, choose a tool).
Use a NEW file name each time: the harness cannot rename onto an old one."""
import os, sys, traceback
import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(os.environ["TEMP"], "blenderrun")
sys.path.insert(0, os.path.join(REPO, "vision", "blender_addon"))
import guidewire_probe
guidewire_probe.register()


def view3d_override():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                return dict(window=win, area=area, region=region)
    return None


def poll():
    try:
        for f in sorted(os.listdir(RUN)):
            if f.endswith(".py"):
                path = os.path.join(RUN, f)
                os.rename(path, path + ".running")
                out = ""
                try:
                    exec(compile(open(path + ".running", encoding="utf-8").read(), f, "exec"), {"bpy": bpy, "view3d_override": view3d_override})
                except Exception:
                    out = traceback.format_exc()
                open(path + ".out", "w", encoding="utf-8").write(out or "ok")
    except Exception:
        pass
    return 0.5


bpy.app.timers.register(poll, first_interval=2.0, persistent=True)
