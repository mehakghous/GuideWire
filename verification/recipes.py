"""Recipes: what a tutorial step for a rigging feature DOES, written as code that runs inside the real application.

A knowledge-base `effects` entry says "this feature makes node type X and needs node type Y". tests/test_effects_verified.py runs the recipe for that
(application, feature) in an empty scene of the real application and checks the claim: X is absent before, present after, and so is Y. A recipe is
self-sufficient (it builds what the step needs). The code strings run in the application's Python with `bpy` (Blender), `cmds` (Maya) or `hou` (Houdini)
already imported. Keep each recipe to what a learner does in the step; a feature with no checkable node type has no recipe.
"""
from __future__ import annotations

_BLENDER_RIG = """
arm = bpy.data.armatures.new('Rig'); rig = bpy.data.objects.new('Rig', arm)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig; rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
up = arm.edit_bones.new('upper.L'); up.head, up.tail = (1, 0, 0), (1, 0, 1)
lo = arm.edit_bones.new('lower.L'); lo.head, lo.tail = (1, 0, 1), (1, 0, 2); lo.parent = up
bpy.ops.object.mode_set(mode='OBJECT')
"""
_BLENDER_POSE = _BLENDER_RIG + "\nbpy.ops.object.mode_set(mode='POSE')\npb = rig.pose.bones['lower.L']\n"

BLENDER = {
    "SKEL-01": _BLENDER_RIG,
    "SKEL-04": _BLENDER_RIG + """
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.armature.select_all(action='SELECT')
bpy.ops.armature.symmetrize()
bpy.ops.object.mode_set(mode='OBJECT')
""",
    "IKFK-02": _BLENDER_POSE + "pb.constraints.new('IK').chain_count = 2\nbpy.ops.object.mode_set(mode='OBJECT')\n",
    "CNST-01": _BLENDER_POSE + "pb.constraints.new('CHILD_OF')\nbpy.ops.object.mode_set(mode='OBJECT')\n",
    "CNST-02": _BLENDER_POSE + "pb.constraints.new('COPY_ROTATION')\nbpy.ops.object.mode_set(mode='OBJECT')\n",
    "SKIN-01": _BLENDER_RIG + """
bpy.ops.mesh.primitive_cube_add()
body = bpy.context.active_object
body.select_set(True); rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
""",
}

MAYA = {
    "SKEL-01": "cmds.joint(position=(0, 0, 0)); cmds.joint(position=(0, 0, -2))",
    "IKFK-02": "a = cmds.joint(position=(0, 0, 0)); cmds.joint(position=(0, 1, -1)); c = cmds.joint(position=(0, 0, -2)); cmds.ikHandle(startJoint=a, endEffector=c)",
    "IKFK-03": "a = cmds.joint(position=(0, 0, 0)); cmds.joint(position=(0, 1, -1)); c = cmds.joint(position=(0, 0, -2)); cmds.ikHandle(startJoint=a, endEffector=c)",
    "IKFK-04": """
a = cmds.joint(position=(0, 0, 0)); cmds.joint(position=(0, 1, -1)); c = cmds.joint(position=(0, 0, -2))
h = cmds.ikHandle(startJoint=a, endEffector=c)[0]
loc = cmds.spaceLocator()[0]
cmds.poleVectorConstraint(loc, h)
""",
    "CNST-01": "a = cmds.spaceLocator()[0]; b = cmds.spaceLocator()[0]; cmds.parentConstraint(a, b)",
    "CNST-03": "a = cmds.spaceLocator()[0]; b = cmds.spaceLocator()[0]; cmds.aimConstraint(a, b)",
    "SKIN-01": """
a = cmds.joint(position=(0, 0, 0)); cmds.joint(position=(0, 2, 0))
body = cmds.polyCube(height=2)[0]
cmds.skinCluster(a, body)
""",
    "CTRL-01": "cmds.circle(normal=(0, 1, 0))",
}

HOUDINI = {
    "SKEL-01": "geo = hou.node('/obj').createNode('geo'); geo.createNode('kinefx::skeleton')",
    "SKEL-04": "geo = hou.node('/obj').createNode('geo'); s = geo.createNode('kinefx::skeleton'); geo.createNode('kinefx::skeletonmirror').setInput(0, s)",
    "ORNT-02": "geo = hou.node('/obj').createNode('geo'); s = geo.createNode('kinefx::skeleton'); geo.createNode('kinefx::orientjoints').setInput(0, s)",
    "ORNT-05": "geo = hou.node('/obj').createNode('geo'); s = geo.createNode('kinefx::skeleton'); geo.createNode('kinefx::rigdoctor').setInput(0, s)",
    "IKFK-01": "geo = hou.node('/obj').createNode('geo'); s = geo.createNode('kinefx::skeleton'); geo.createNode('kinefx::rigpose').setInput(0, s)",
    "PREP-05": "geo = hou.node('/obj').createNode('geo'); s = geo.createNode('kinefx::skeleton'); geo.createNode('kinefx::rigstashpose').setInput(0, s)",
    "IKFK-02": "geo = hou.node('/obj').createNode('geo'); s = geo.createNode('kinefx::skeleton'); geo.createNode('kinefx::ikchains').setInput(0, s)",
    "SKIN-01": """
geo = hou.node('/obj').createNode('geo')
s = geo.createNode('kinefx::skeleton'); body = geo.createNode('box')
cap = geo.createNode('kinefx::jointcapturebiharmonic'); cap.setInput(0, body); cap.setInput(1, s)
dfm = geo.createNode('kinefx::jointdeform'); dfm.setInput(0, cap)
""",
}

RECIPES = {"blender": BLENDER, "maya": MAYA, "houdini": HOUDINI}
