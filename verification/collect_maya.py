"""Runs inside Maya (imported by snapshot_maya.py and probe_maya.py): count the node types a scene holds."""


def node_types(cmds) -> dict:
    out = {}
    for n in cmds.ls(long=True) or []:
        t = cmds.nodeType(n)
        out[t] = out.get(t, 0) + 1
    return out
