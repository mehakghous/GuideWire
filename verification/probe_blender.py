"""Run inside Blender: blender -b --factory-startup --python probe_blender.py -- request.json
For each {feature: code} in the request: empty scene, count node types, run the code, count again."""
import json
import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_blender  # noqa: E402

req = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
out = {}
for feature, code in req["recipes"].items():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = collect_blender.node_types(bpy)
    try:
        exec(code, {"bpy": bpy})
        out[feature] = {"before": before, "after": collect_blender.node_types(bpy)}
    except Exception:
        out[feature] = {"error": traceback.format_exc()[-400:]}
json.dump({"app": "blender", "version": bpy.app.version_string, "results": out}, open(req["out"], "w", encoding="utf-8"))
