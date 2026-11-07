"""Build a tiny scene in Houdini and save it: hython build_houdini.py OUT.hip
/obj/char (a geo object, tx = 2) containing a Skeleton SOP and a Null SOP."""
import sys

import hou

geo = hou.node("/obj").createNode("geo", "char")
geo.createNode("skeleton")
geo.createNode("null")
geo.parm("tx").set(2.0)
hou.hipFile.save(sys.argv[1])
