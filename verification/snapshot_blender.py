"""Run inside Blender: blender -b --factory-startup --python snapshot_blender.py -- request.json. Reads a scene, writes a snapshot, changes nothing."""
import json
import re
import sys

import bpy

req = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
if req.get("scene"):
    bpy.ops.wm.open_mainfile(filepath=req["scene"])

node_types = {}


def bump(k):
    node_types[k] = node_types.get(k, 0) + 1


for ob in bpy.data.objects:
    bump(ob.type)                                             # ARMATURE, MESH, EMPTY ...
    if ob.type == "ARMATURE":
        for _ in ob.data.bones:
            bump("BONE")
    for c in ob.constraints:
        bump(c.type)                                          # object constraints
    if ob.pose:
        for pb in ob.pose.bones:
            for c in pb.constraints:
                bump(c.type)                                  # IK, COPY_ROTATION ...
    for m in ob.modifiers:
        bump(m.type)                                          # ARMATURE, SUBSURF ...

sel = [ob.type for ob in bpy.context.view_layer.objects if ob.select_get()]
SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\[\]'\" ]*$")       # attribute/index access only: no calls, no dunder names


def read(path):
    if not SAFE.match(path) or "__" in path:
        return {"error": "path not allowed (attribute and index access only)"}
    try:
        v = eval(path, {"__builtins__": {}}, {"objects": bpy.data.objects, "scene": bpy.context.scene, "armatures": bpy.data.armatures})
        if isinstance(v, (int, float, str)):
            return v
        return float(v) if hasattr(v, "__float__") else str(v)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


snap = {"app": "blender", "version": bpy.app.version_string, "mode": bpy.context.mode, "selection_types": sel, "node_types": node_types,
        "node_names": [o.name for o in bpy.data.objects], "properties": {p: read(p) for p in req.get("properties", [])}}
json.dump(snap, open(req["out"], "w", encoding="utf-8"))
