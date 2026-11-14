"""Write Houdini's real menu data (read-only). Run in Houdini's Python Shell:

    import sys; sys.path.append(r"<GuideWire>"); sys.path.append(r"<GuideWire>/vision/menus")
    import dump_houdini; dump_houdini.run(r"<GuideWire>/shared/menus/houdini_menus.json")

Main menu: from the application's own menu XML. Tab menu: the node names Houdini lists per network type.
PROTOTYPE: not yet run inside Houdini 22 (not installed on the development machine); spot-check the output.
"""
import json

from walkers import houdini_groups


def run(out_path):
    import hou
    data = {"app": "houdini", "version": hou.applicationVersionString(), "groups": houdini_groups(hou)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    print("DUMP houdini: %d groups -> %s" % (len(data["groups"]), out_path))
