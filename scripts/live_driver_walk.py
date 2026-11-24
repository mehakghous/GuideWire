"""Runs INSIDE a Blender that `scripts/live_guidance_walk.py` started: builds a small rig scene (a leg mesh, an armature with bones) and puts the window into each state the walk asks for (mode, which object is
active, which Properties tab is open, whether the armature exists), announcing each state in a file. It changes only the throw-away Blender it runs in, by script (no input is simulated), and loads the probe add-on.

    blender --factory-startup <empty.blend> --python scripts/live_driver_walk.py -- <states.json> <out.json> <quit-flag-file>
"""
import importlib.util
import json
import os
import sys
import time

import bpy

STATES, OUT, QUIT = sys.argv[sys.argv.index("--") + 1: sys.argv.index("--") + 4]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("guidewire_probe", os.path.join(ROOT, "vision", "blender_addon", "guidewire_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
probe.register()
SCENARIOS = json.load(open(STATES, encoding="utf-8"))
SETTLE = 6.0
state = {"i": -1, "t": 0.0}
BONES = [("hip", (0, 0, 3), (0, 0, 2), None), ("knee", (0, 0, 2), (0, 0, 1), "hip"), ("ankle", (0, 0, 1), (0, 0, 0.2), "knee"), ("toe", (0, 0, 0.2), (0, -0.4, 0.1), "ankle"),
         ("foot_ik", (0, -0.6, 0.2), (0, -0.9, 0.2), None), ("knee_pole", (0, -1, 1), (0, -1.3, 1), None)]


def views():
    win = bpy.context.window_manager.windows[0]
    a3 = next(a for a in win.screen.areas if a.type == "VIEW_3D")
    return win, a3, next(r for r in a3.regions if r.type == "WINDOW")


def to_mode(mode):
    win, a3, w3 = views()
    with bpy.context.temp_override(window=win, area=a3, region=w3):
        if bpy.context.object is not None and bpy.context.object.mode != mode:
            bpy.ops.object.mode_set(mode=mode)


def build(armature: bool, active: str):
    win, a3, w3 = views()
    with bpy.context.temp_override(window=win, area=a3, region=w3):
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        coll = bpy.context.scene.collection
        mesh = bpy.data.meshes.new("Leg")
        leg = bpy.data.objects.new("Leg", mesh)
        coll.objects.link(leg)
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.35, radius2=0.2, depth=3.0, matrix=__import__("mathutils").Matrix.Translation((0, 0, 1.5)))
        bm.to_mesh(mesh)
        bm.free()
        arm_obj = None
        if armature:
            arm = bpy.data.armatures.new("Armature")
            arm_obj = bpy.data.objects.new("Armature", arm)
            coll.objects.link(arm_obj)
            bpy.context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode="EDIT")
            for name, head, tail, parent in BONES:
                b = arm.edit_bones.new(name)
                b.head, b.tail = head, tail
                if parent:
                    b.parent = arm.edit_bones[parent]
            bpy.ops.object.mode_set(mode="OBJECT")
            arm.bones.active = arm.bones["knee"]                    # the Bone and Bone Constraint tabs exist only with an active bone
            con = arm_obj.pose.bones["knee"].constraints.new("COPY_LOCATION")      # so the steps that set a constraint's fields have one to show (Head/Tail appears once its target is a bone)
            con.target, con.subtarget = arm_obj, "ankle"
        obj = arm_obj if (active == "Armature" and arm_obj is not None) else leg
        for o in bpy.data.objects:
            o.select_set(o == obj)
        bpy.context.view_layer.objects.active = obj


def set_tab(tab: str):
    for a in bpy.context.window_manager.windows[0].screen.areas:
        if a.type == "PROPERTIES":
            try:
                a.spaces.active.context = tab
            except Exception:
                pass


def close_popups():
    """A pop-up from the state before stays open until Esc or a mouse move: send Esc to this Blender (it is the foreground window). It is sent by one tick and the next state is applied by a LATER tick, because
    Blender only reads the key between timer calls: an Esc sent inside the call that opens a pop-up would close that pop-up."""
    try:
        import ctypes
        ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
    except Exception:
        pass


def apply(sc):
    if sc.get("rebuild", True):
        build(sc["armature"], sc["active"])
    win, a3, w3 = views()
    if sc["mode"] != "OBJECT":
        with bpy.context.temp_override(window=win, area=a3, region=w3):
            if sc["mode"] == "POSE":
                bpy.ops.object.mode_set(mode="POSE")
            else:
                bpy.ops.object.mode_set(mode="EDIT")
    if sc.get("tab"):
        set_tab(sc["tab"])
    if sc.get("ran"):                                                # the operator really ran (its settings panel is then left at the bottom left of the 3D view, titled with its name)
        win, a3, w3 = views()
        arm = bpy.data.objects["Armature"].data
        with bpy.context.temp_override(window=win, area=a3, region=w3):
            for b in arm.edit_bones:
                b.select = b.name == "knee"
            bpy.ops.armature.parent_clear("EXEC_DEFAULT", type="CLEAR")
    if sc.get("popup"):                                              # the pop-up a shortcut opens (Alt+P: Clear Parent, Ctrl+P: Keep Offset, Shift+I: To Active Bone), at the mouse, over the 3D view
        mod, _, name = sc["popup"].partition(".")
        win, a3, w3 = views()
        with bpy.context.temp_override(window=win, area=a3, region=w3):
            getattr(getattr(bpy.ops, mod), name)("INVOKE_DEFAULT")


def tick():
    if os.path.exists(QUIT):
        probe.unregister()
        bpy.ops.wm.quit_blender()
        return None
    now = time.monotonic()
    if state["i"] >= 0 and now < state["t"] + 300:                  # a state is held until the walk says it has finished looking at it (the ack file holds the last finished state), never longer than 5 minutes
        try:
            if int(open(OUT + ".ack").read().strip() or -1) < state["i"]:
                return 0.5
        except (OSError, ValueError):
            return 0.5
    if state["i"] >= 0 and not state.get("closed"):
        close_popups()
        state["closed"] = True
        return 1.0                                                   # Blender reads the Esc now; the next state is applied on the next tick
    if now >= state["t"]:
        state["closed"] = False
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
        state["t"] = now
    return 0.5


bpy.app.timers.register(tick, first_interval=2.0)
