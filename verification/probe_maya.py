"""Run inside Maya: mayapy probe_maya.py request.json
For each {feature: code} in the request: new scene, count node types, run the code, count again."""
import json
import os
import sys
import traceback

import maya.standalone

maya.standalone.initialize(name="python")
from maya import cmds  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_maya  # noqa: E402

req = json.load(open(sys.argv[1], encoding="utf-8"))
out = {}
for feature, code in req["recipes"].items():
    cmds.file(new=True, force=True)
    before = collect_maya.node_types(cmds)
    try:
        exec(code, {"cmds": cmds})
        out[feature] = {"before": before, "after": collect_maya.node_types(cmds)}
    except Exception:
        out[feature] = {"error": traceback.format_exc()[-400:]}
json.dump({"app": "maya", "version": cmds.about(version=True), "results": out}, open(req["out"], "w", encoding="utf-8"))
maya.standalone.uninitialize()
