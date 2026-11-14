"""Write Maya's real menu trees (read-only). Run in Maya's Script Editor (Python tab), interactive session:

    import sys; sys.path.append(r"<GuideWire>"); sys.path.append(r"<GuideWire>/vision/menus")
    import dump_maya; dump_maya.run(r"<GuideWire>/shared/menus/maya_menus.json")

PROTOTYPE: not yet run inside Maya 2027 (not installed on the development machine); spot-check the output.
"""
import json

from walkers import maya_groups


def run(out_path):
    import maya.mel as mel
    from maya import cmds
    data = {"app": "maya", "version": cmds.about(version=True), "groups": maya_groups(cmds, mel)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    n = sum(len(g["tree"]) for g in data["groups"])
    print("DUMP maya: %d menu sets, %d top-level menus -> %s" % (len(data["groups"]), n, out_path))
