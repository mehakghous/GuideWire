"""Run inside Maya: mayapy snapshot_maya.py request.json.

UNTESTED: Maya is not installed on the development machine, so this was written from the maya.cmds documentation and has never run.
The matching test skips until mayapy is found (set GW_MAYAPY).
"""
import json
import sys

import maya.standalone

maya.standalone.initialize(name="python")
from maya import cmds  # noqa: E402  (importable only after initialize)

req = json.load(open(sys.argv[1], encoding="utf-8"))
if req.get("scene"):
    cmds.file(req["scene"], open=True, force=True)

node_types = {}
for n in cmds.ls(long=True) or []:
    t = cmds.nodeType(n)
    node_types[t] = node_types.get(t, 0) + 1
SEL = {"joint": "JOINT", "ikHandle": "IK_HANDLE", "camera": "CAMERA", "locator": "LOCATOR", "nurbsCurve": "CURVE", "mesh": "MESH"}
sel = []
for n in cmds.ls(selection=True, long=True) or []:
    t = cmds.nodeType(n)
    if t == "transform":
        shapes = cmds.listRelatives(n, shapes=True, fullPath=True) or []
        t = cmds.nodeType(shapes[0]) if shapes else t
    sel.append(SEL.get(t, t.upper()))


def read(path):
    try:
        v = cmds.getAttr(path)
        return v if isinstance(v, (int, float, str)) else str(v)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


snap = {"app": "maya", "version": cmds.about(version=True), "mode": None, "selection_types": sel, "node_types": node_types,
        "node_names": [n.split("|")[-1] for n in (cmds.ls(long=True) or [])], "properties": {p: read(p) for p in req.get("properties", [])}}
json.dump(snap, open(req["out"], "w", encoding="utf-8"))
maya.standalone.uninitialize()
