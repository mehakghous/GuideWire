"""Run inside Houdini: hython probe_houdini.py request.json
For each {feature: code} in the request: empty scene, count node types, run the code, count again."""
import json
import os
import sys
import traceback

import hou

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_houdini  # noqa: E402

req = json.load(open(sys.argv[1], encoding="utf-8"))
out = {}
for feature, code in req["recipes"].items():
    hou.hipFile.clear(suppress_save_prompt=True)
    before = collect_houdini.node_types(hou)[0]
    try:
        exec(code, {"hou": hou})
        out[feature] = {"before": before, "after": collect_houdini.node_types(hou)[0]}
    except Exception:
        out[feature] = {"error": traceback.format_exc()[-400:]}
json.dump({"app": "houdini", "version": hou.applicationVersionString(), "results": out}, open(req["out"], "w", encoding="utf-8"))
