"""Build a tiny rig in Blender and save it: blender -b --factory-startup --python build_blender.py -- OUT.blend
Two bones (upper, lower), an IK constraint on lower, a mesh object at x=2, the armature selected."""
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]
arm = bpy.data.armatures.new("Rig")
rig = bpy.data.objects.new("Rig", arm)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
upper = arm.edit_bones.new("upper")
upper.head, upper.tail = (0, 0, 0), (0, 0, 1)
lower = arm.edit_bones.new("lower")
lower.head, lower.tail = (0, 0, 1), (0, 0, 2)
lower.parent = upper
bpy.ops.object.mode_set(mode="POSE")
rig.pose.bones["lower"].constraints.new("IK").chain_count = 2
bpy.ops.object.mode_set(mode="OBJECT")
body = bpy.data.objects.new("Body", bpy.data.meshes.new("BodyMesh"))
bpy.context.scene.collection.objects.link(body)
body.location.x = 2.0
rig.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=out)
