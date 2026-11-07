"""Run inside Blender: blender -b --factory-startup --python snapshot_blender.py -- request.json. Reads a scene, writes a snapshot, changes nothing."""
import json
import os
import re
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_blender  # noqa: E402

req = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
if req.get("scene"):
    bpy.ops.wm.open_mainfile(filepath=req["scene"])

node_types = collect_blender.node_types(bpy)

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


def has_attr(path):
    try:
        name, _, attr = path.partition(".")
        ob = bpy.data.objects.get(name)
        if ob is not None:
            return bool(attr and (attr in ob.keys() or hasattr(ob, attr)))
        for o in bpy.data.objects:
            pb = o.pose.bones.get(name) if o.pose else None
            if pb is not None:
                return bool(attr and (attr in pb.keys() or hasattr(pb, attr)))
        return False
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


snap = {"app": "blender", "version": bpy.app.version_string, "mode": bpy.context.mode, "selection_types": sel, "node_types": node_types,
        "node_names": [o.name for o in bpy.data.objects] + [b.name for a in bpy.data.armatures for b in a.bones],
        "attributes": {p: has_attr(p) for p in req.get("attributes", [])}, "properties": {p: read(p) for p in req.get("properties", [])}}
json.dump(snap, open(req["out"], "w", encoding="utf-8"))
