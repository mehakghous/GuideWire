"""Run inside Maya: mayapy snapshot_maya.py request.json.

Verified once against Maya 2027 (tests/test_verification.py::test_maya_real_scene). The test skips when mayapy is not found (set GW_MAYAPY).
"""
import json
import os
import sys

import maya.standalone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

maya.standalone.initialize(name="python")
from maya import cmds  # noqa: E402  (importable only after initialize)

import collect_maya  # noqa: E402

req = json.load(open(sys.argv[1], encoding="utf-8"))
if req.get("scene"):
    cmds.file(req["scene"], open=True, force=True)

node_types = collect_maya.node_types(cmds)
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


def has_attr(path):
    try:
        obj, _, attr = path.partition(".")
        return bool(cmds.objExists(obj) and attr and cmds.attributeQuery(attr.split(".")[0], node=obj, exists=True))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


snap = {"app": "maya", "version": cmds.about(version=True), "mode": None, "selection_types": sel, "node_types": node_types,
        "node_names": [n.split("|")[-1] for n in (cmds.ls(long=True) or [])], "attributes": {p: has_attr(p) for p in req.get("attributes", [])},
        "properties": {p: read(p) for p in req.get("properties", [])}}
json.dump(snap, open(req["out"], "w", encoding="utf-8"))
maya.standalone.uninitialize()
