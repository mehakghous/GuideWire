"""Build a tiny rig in Maya and save it: mayapy build_maya.py OUT.ma. UNTESTED: Maya is not installed on the development machine.
Three joints in a chain, an IK handle on them, a cube at translateX = 2."""
import sys

import maya.standalone

maya.standalone.initialize(name="python")
from maya import cmds  # noqa: E402

j1 = cmds.joint(position=(0, 0, 0), name="hip_jnt")
j2 = cmds.joint(position=(0, 0, -2), name="knee_jnt")
j3 = cmds.joint(position=(0, 0, -4), name="ankle_jnt")
cmds.ikHandle(startJoint=j1, endEffector=j3, name="leg_ik")
cmds.polyCube(name="body")
cmds.setAttr("body.translateX", 2.0)
cmds.file(rename=sys.argv[1])
cmds.file(save=True, type="mayaAscii")
maya.standalone.uninitialize()
