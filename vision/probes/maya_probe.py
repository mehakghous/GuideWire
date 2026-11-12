"""GuideWire read-only probe for Maya (PROTOTYPE: written from the maya.cmds documentation, not yet run
inside Maya 2027 because it is not installed on the development machine).

In Maya's Script Editor (Python tab), with the GuideWire folder path filled in:

    import sys; sys.path.append(r"<GuideWire>/vision/probes"); sys.path.append(r"<GuideWire>")
    import maya_probe; maya_probe.register()      # maya_probe.unregister() to stop

It only reads. Maya is read on its main thread (maya.utils.executeInMainThreadWithResult). The history
comes from the Script Editor echo: register() points Maya's history log at a temp file and switches
the log off again in unregister().
"""
from __future__ import annotations

import os
import tempfile

import probe_core

HISTORY_FILE = os.path.join(tempfile.gettempdir(), "guidewire_maya_history.txt")
HISTORY_LINES = 40
SEL = {"joint": "JOINT", "ikHandle": "IK_HANDLE", "camera": "CAMERA", "locator": "LOCATOR",
       "nurbsCurve": "CURVE", "mesh": "MESH"}           # same names as verification/snapshot_maya.py
_server = None


def node_types(cmds) -> dict:
    out: dict = {}
    for n in cmds.ls(long=True) or []:
        t = cmds.nodeType(n)
        out[t] = out.get(t, 0) + 1
    return out


def selection_types(cmds) -> list[str]:
    sel = []
    for n in cmds.ls(selection=True, long=True) or []:
        t = cmds.nodeType(n)
        if t == "transform":
            shapes = cmds.listRelatives(n, shapes=True, fullPath=True) or []
            t = cmds.nodeType(shapes[0]) if shapes else t
        sel.append(SEL.get(t, t.upper()))
    return sel


def history_events(lines: list[str]) -> list[dict]:
    """Script Editor echo lines -> operator events: `polyCube -w 1;` and `cmds.polyCube(w=1)` give polyCube."""
    out = []
    for line in lines:
        line = line.strip().rstrip(";")
        if not line or line.startswith(("//", "#")):            # results and comments are not commands
            continue
        head = line.split("(")[0].split()[0] if line else ""
        head = head.split(".")[-1]                                # cmds.polyCube -> polyCube
        if head:
            out.append({"id": head, "name": head})
    return out[-HISTORY_LINES:]


def read_tail(path: str = HISTORY_FILE) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-HISTORY_LINES * 3:]
    except OSError:
        return []


def gather(cmds, properties=(), attributes=(), history_lines=()) -> dict:
    """The state the evaluator understands. Runs on Maya's main thread only."""
    counts = node_types(cmds)
    out: dict = {"node_counts": counts, "nodes": sorted(counts),
                 "node_names": [n for n in (cmds.ls() or [])],
                 "selection_types": selection_types(cmds), "history": history_events(list(history_lines))}
    try:
        out["active_tool"] = cmds.currentCtx()
    except Exception:
        pass
    props, attrs = {}, {}
    for p in properties:
        try:
            v = cmds.getAttr(p)
            if isinstance(v, (int, float, str)):
                props[p] = v
        except Exception:
            pass
    for a in attributes:
        try:
            attrs[a] = bool(cmds.objExists(a))
        except Exception:
            pass
    if props:
        out["properties"] = props
    if attrs:
        out["attributes"] = attrs
    return out


def _read(properties: list[str], attributes: list[str]) -> dict:
    import maya.utils
    from maya import cmds

    def on_main_thread():
        return gather(cmds, properties, attributes, read_tail())
    return maya.utils.executeInMainThreadWithResult(on_main_thread)


def register() -> None:
    global _server
    from maya import cmds
    cmds.scriptEditorInfo(historyFilename=HISTORY_FILE, writeHistory=True)
    _server = probe_core.start("maya", _read)


def unregister() -> None:
    global _server
    from maya import cmds
    cmds.scriptEditorInfo(writeHistory=False)
    probe_core.stop(_server)
    _server = None
