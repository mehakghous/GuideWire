"""Runs inside Houdini (imported by snapshot_houdini.py and probe_houdini.py): count the node types a scene holds, by internal name AND by UI label."""


def node_types(hou) -> tuple[dict, list]:
    out, names = {}, []

    def bump(k):
        out[k] = out.get(k, 0) + 1

    for n in hou.node("/").allSubChildren():
        t = n.type()
        bump(t.name())                                        # "kinefx::rigdoctor"
        if t.description() != t.name():
            bump(t.description())                             # "Rig Doctor": the label tutorials and the app profile use
        names.append(n.name())
    return out, names
