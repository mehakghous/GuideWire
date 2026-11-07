"""Run inside Maya: mayapy vocab_maya.py request.json. Writes the REAL node types of this install (nothing is changed).
mayapy has no menus, so UI labels cannot be dumped headlessly; only node types and runtime-command names are."""
import json
import sys

import maya.standalone

maya.standalone.initialize(name="python")
from maya import cmds  # noqa: E402

req = json.load(open(sys.argv[1], encoding="utf-8"))
runtime = []
try:
    runtime = sorted(cmds.runTimeCommand(q=True, uiArray=True) or [])
except Exception:
    pass
# the labels a user sees in the Attribute Editor / Channel Box for the rigging node types, plus the choices of their enum attributes
ATTR_NODES = ("joint", "ikHandle", "ikEffector", "skinCluster", "aimConstraint", "parentConstraint", "pointConstraint", "orientConstraint", "scaleConstraint",
              "poleVectorConstraint", "blendShape", "animLayer", "locator", "reverse", "multiplyDivide", "plusMinusAverage", "condition")
attr_labels = {}
for t in ATTR_NODES:
    labels = set()
    try:
        node = cmds.createNode(t)
        for a in cmds.listAttr(node) or []:
            try:
                labels.add(cmds.attributeQuery(a, node=node, niceName=True))
                for group in cmds.attributeQuery(a, node=node, listEnum=True) or []:
                    labels.update(x.split("=")[0] for x in group.split(":") if x)
            except Exception:
                pass
        cmds.delete(node)
    except Exception:
        pass
    attr_labels[t] = sorted(labels)
data = {"app": "maya", "version": cmds.about(version=True), "node_types": sorted(cmds.allNodeTypes()), "runtime_commands": runtime, "attr_labels": attr_labels}
json.dump(data, open(req["out"], "w", encoding="utf-8"), indent=0)
maya.standalone.uninitialize()
