"""GuideWire read-only probe for Houdini (PROTOTYPE: written from the `hou` documentation, not yet run
inside Houdini 22 because it is not installed on the development machine).

In Houdini's Python Shell, with the GuideWire folder path filled in:

    import sys; sys.path.append(r"<GuideWire>/vision/probes")
    import houdini_probe; houdini_probe.register()      # houdini_probe.unregister() to stop

It only reads. Houdini is read on its main thread (hdefereval.executeInMainThreadWithResult). History
comes from Houdini's undo labels, so it lists what changed in the scene, oldest first.
"""
from __future__ import annotations

import probe_core

_server = None


def node_types(hou) -> tuple[dict, list]:
    """Node types by internal name AND UI label, and the node names (same as verification/collect_houdini.py)."""
    out: dict = {}
    names: list = []

    def bump(k):
        out[k] = out.get(k, 0) + 1

    for n in hou.node("/").allSubChildren():
        t = n.type()
        bump(t.name())
        if t.description() != t.name():
            bump(t.description())
        names.append(n.name())
    return out, names


def history_events(labels) -> list[dict]:
    """hou.undos.undoLabels() lists the newest first; events are oldest first."""
    return [{"id": str(label), "name": str(label)} for label in reversed(list(labels))]


def gather(hou, properties=(), attributes=()) -> dict:
    """The state the evaluator understands. Runs on Houdini's main thread only."""
    counts, names = node_types(hou)
    out: dict = {"node_counts": counts, "nodes": sorted(counts), "node_names": names,
                 "selection_types": ["NODE"] * len(hou.selectedNodes())}
    try:
        out["history"] = history_events(hou.undos.undoLabels())
    except Exception:
        pass
    try:
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is not None:
            out["active_tool"] = viewer.currentState()
    except Exception:
        pass
    props, attrs = {}, {}
    for p in properties:
        try:
            v = hou.parm(p).eval()
            if isinstance(v, (int, float, str)):
                props[p] = v
        except Exception:
            pass
    for a in attributes:
        try:
            node_path, _, parm = a.rpartition("/") if "/" in a else ("", "", a)
            node = hou.node(node_path)
            attrs[a] = bool(node is not None and node.parm(parm) is not None)
        except Exception:
            pass
    if props:
        out["properties"] = props
    if attrs:
        out["attributes"] = attrs
    return out


def _read(properties: list[str], attributes: list[str]) -> dict:
    import hdefereval
    import hou

    def on_main_thread():
        return gather(hou, properties, attributes)
    return hdefereval.executeInMainThreadWithResult(on_main_thread)


def register() -> None:
    global _server
    _server = probe_core.start("houdini", _read)


def unregister() -> None:
    global _server
    probe_core.stop(_server)
    _server = None
