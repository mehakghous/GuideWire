"""Runs inside Blender (imported by snapshot_blender.py and probe_blender.py): count the node types a scene holds.

Names: an object is its Blender type (ARMATURE, MESH), a bone is BONE, a constraint is CONSTRAINT_<type> (CONSTRAINT_IK) and a modifier is MODIFIER_<type>
(MODIFIER_ARMATURE). The prefixes are needed because Blender uses the same word for different things (ARMATURE is an object type, a constraint and a modifier)."""


def node_types(bpy) -> dict:
    out = {}

    def bump(k):
        out[k] = out.get(k, 0) + 1

    for ob in bpy.data.objects:
        bump(ob.type)                                         # ARMATURE, MESH, EMPTY ...
        if ob.type == "ARMATURE":
            for _ in ob.data.bones:
                bump("BONE")
        for c in ob.constraints:
            bump("CONSTRAINT_" + c.type)                     # object constraints
        if ob.pose:
            for pb in ob.pose.bones:
                for c in pb.constraints:
                    bump("CONSTRAINT_" + c.type)              # CONSTRAINT_IK, CONSTRAINT_COPY_ROTATION ...
        for m in ob.modifiers:
            bump("MODIFIER_" + m.type)                       # MODIFIER_ARMATURE, MODIFIER_SUBSURF ...
    return out
