"""Run inside Houdini: hython snapshot_houdini.py request.json. Reads a .hip, writes a snapshot, changes nothing."""
import json
import os
import sys

import hou

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_houdini  # noqa: E402

req = json.load(open(sys.argv[1], encoding="utf-8"))
if req.get("scene"):
    hou.hipFile.load(req["scene"], suppress_save_prompt=True, ignore_load_warnings=True)

node_types, names = collect_houdini.node_types(hou)
sel = ["NODE"] * len(hou.selectedNodes())


def read(path):
    try:
        v = hou.parm(path).eval()
        return v if isinstance(v, (int, float, str)) else str(v)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def has_attr(path):
    try:
        node_path, _, parm = path.rpartition("/") if "/" in path else ("", "", path)
        n = hou.node(node_path)
        return bool(n is not None and n.parm(parm) is not None)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


snap = {"app": "houdini", "version": hou.applicationVersionString(), "mode": None, "selection_types": sel, "node_types": node_types,
        "node_names": names, "attributes": {p: has_attr(p) for p in req.get("attributes", [])},
        "properties": {p: read(p) for p in req.get("properties", [])}}
json.dump(snap, open(req["out"], "w", encoding="utf-8"))
