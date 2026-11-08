"""Run inside Houdini: hython vocab_houdini.py request.json. Writes the REAL node types (internal name and the label the UI shows) of this install."""
import glob
import json
import os
import sys

import hou

req = json.load(open(sys.argv[1], encoding="utf-8"))
KEEP = ("Sop", "Object", "Dop", "Chop", "Lop", "Vop", "Driver", "Cop2")
types = {}
for cname, cat in hou.nodeTypeCategories().items():
    if cname in KEEP:
        types[cname] = sorted([t.name(), t.description()] for t in cat.nodeTypes().values())


def parm_labels(node):
    """Every label a user can see on a node's parameter pane: parameter, folder and menu-choice labels."""
    out = set()

    def walk(templates):
        for t in templates:
            if t.label():
                out.add(t.label())
            if t.type() == hou.parmTemplateType.Folder or t.type() == hou.parmTemplateType.FolderSet:
                walk(t.parmTemplates())
            try:
                out.update(x for x in t.menuLabels() if x)
            except Exception:
                pass

    walk(node.parmTemplateGroup().entries())
    return sorted(out)


parms = {}
hou.hipFile.clear(suppress_save_prompt=True)
geo = hou.node("/obj").createNode("geo")
for name, desc in types.get("Sop", []):
    if name.startswith(("kinefx::", "apex::")) or name in ("blendshapes", "bonedeform", "captureproximity", "capturelayerpaint", "capturemirror", "deltamush", "packfolder"):
        try:
            n = geo.createNode(name)
            parms[desc.strip()] = parm_labels(n)
            n.destroy()
        except Exception:
            pass
desktops = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(hou.getenv("HFS"), "houdini", "desktop", "*.desk")))
data = {"app": "houdini", "version": hou.applicationVersionString(), "node_types_by_category": types, "desktops": desktops, "sop_parm_labels": parms}
json.dump(data, open(req["out"], "w", encoding="utf-8"), indent=0)
