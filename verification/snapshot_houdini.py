"""Run inside Houdini: hython snapshot_houdini.py request.json. Reads a .hip, writes a snapshot, changes nothing."""
import json
import sys

import hou

req = json.load(open(sys.argv[1], encoding="utf-8"))
if req.get("scene"):
    hou.hipFile.load(req["scene"], suppress_save_prompt=True, ignore_load_warnings=True)

node_types = {}
names = []


def bump(k):
    node_types[k] = node_types.get(k, 0) + 1


for n in hou.node("/").allSubChildren():
    t = n.type()
    bump(t.name())                                            # "rigdoctor"
    if t.description() != t.name():
        bump(t.description())                                 # "Rig Doctor": the label tutorials and the app profile use
    names.append(n.name())
sel = ["NODE"] * len(hou.selectedNodes())


def read(path):
    try:
        v = hou.parm(path).eval()
        return v if isinstance(v, (int, float, str)) else str(v)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


snap = {"app": "houdini", "version": hou.applicationVersionString(), "mode": None, "selection_types": sel, "node_types": node_types,
        "node_names": names, "properties": {p: read(p) for p in req.get("properties", [])}}
json.dump(snap, open(req["out"], "w", encoding="utf-8"))
