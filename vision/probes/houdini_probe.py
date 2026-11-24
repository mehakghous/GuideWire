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


# ---- the interface, for highlighting (measured in Houdini 22.0.466: docs/houdini_grounding.md)
QT_PANES = {"parmdialog": "Parm", "DM_ViewLayout": "SceneViewer"}      # Houdini's Qt window titles for the pane CONTENTS: their rectangles on screen
MAX_NODES = 200


class Revisions:
    """A counter per part of the state that goes up only when that part's content changes (as in the Blender add-on): a reader that sees the same number has nothing new to look at."""

    def __init__(self) -> None:
        self._last: dict = {}
        self._n: dict = {}

    def bump(self, name: str, content) -> int:
        import json
        h = json.dumps(content, sort_keys=True, default=str)
        if self._last.get(name) != h:
            self._last[name] = h
            self._n[name] = self._n.get(name, 0) + 1
        return self._n.get(name, 0)


_revs = Revisions()


def node_rect(pane: list[float], lo, hi, dpr: float = 1.0) -> list[int]:
    """A node's tile on screen, from the network editor's pane rectangle (x, y, w, h; screen, top-left origin) and `posToScreen` of the node's lower-left and upper-right corners. Those are pane
    pixels with the origin at the BOTTOM-left of the pane's drawable area, which is the bottom of the pane: x = pane.x + lo.x, y = pane.y + pane.h - hi.y. Checked against a capture of a real
    Houdini 22 window: the rectangle sits on the node tile. `dpr` turns Qt's logical pixels into the screen's physical ones."""
    x, y, w, h = pane
    return [round((x + lo[0]) * dpr), round((y + h - hi[1]) * dpr), round((hi[0] - lo[0]) * dpr), round((hi[1] - lo[1]) * dpr)]


def overlaps(a: list[int], b: list[int]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def parm_labels(group) -> list[str]:
    """The labels of a node's parameters in the order the parameter pane shows them, folders included (a folder's label, then its parameters)."""
    out: list[str] = []

    def walk(entries):
        for e in entries:
            try:
                label = e.label()
            except Exception:
                label = ""
            if label and label.strip() and label not in out:
                out.append(label)
            if hasattr(e, "parmTemplates"):
                try:
                    walk(e.parmTemplates())
                except Exception:
                    pass
    walk(group.entries())
    return out


def _type_name(tab) -> str:
    return str(tab.type()).rsplit(".", 1)[-1]


def _qt_pane_rects(hou) -> tuple[dict, float]:
    """{"Parm": [x, y, w, h], "SceneViewer": [...]} from Houdini's Qt windows (logical pixels), and the device pixel ratio. Empty when Qt is not reachable (hython, tests)."""
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        try:
            from PySide2 import QtCore, QtWidgets
        except ImportError:
            return {}, 1.0
    try:
        mw = hou.qt.mainWindow()
        dpr = float(mw.devicePixelRatioF())
    except Exception:
        return {}, 1.0
    out: dict = {}
    for w in mw.findChildren(QtWidgets.QWidget):
        try:
            kind = QT_PANES.get(w.windowTitle())
            if kind and w.isVisible() and kind not in out:
                p = w.mapToGlobal(QtCore.QPoint(0, 0))
                out[kind] = [p.x(), p.y(), w.width(), w.height()]
        except Exception:
            continue
    return out, dpr


def ui_snapshot(hou, qt_rects: dict | None = None, dpr: float | None = None) -> dict:
    """What is on screen: the current pane tabs, the network the network editor shows with each visible node's tile (screen pixels), the node the parameter pane shows with its labels in order,
    and the viewport state. All rectangles are (x, y, w, h) in physical screen pixels, top-left origin. Parts that cannot be read are left out, never guessed."""
    if qt_rects is None or dpr is None:
        qr, d = _qt_pane_rects(hou)
        qt_rects = qr if qt_rects is None else qt_rects
        dpr = d if dpr is None else dpr

    def scaled(r):
        return [round(v * dpr) for v in r]
    out: dict = {"v": 1, "dpr": dpr, "panes": []}
    try:
        tabs = list(hou.ui.curDesktop().paneTabs())
    except Exception:
        return out
    for t in tabs:
        try:
            if not t.isCurrentTab():
                continue
            kind = _type_name(t)
            pane: dict = {"type": kind, "name": t.name()}
            if kind == "NetworkEditor":
                g = t.qtScreenGeometry()
                geom = [g.x(), g.y(), g.width(), g.height()]
                pane["rect"] = scaled(geom)
                if "network" not in out:
                    pwd = t.pwd()
                    nodes = []
                    for n in pwd.children():
                        r = node_rect(geom, t.posToScreen(n.position()), t.posToScreen(n.position() + n.size()), dpr)
                        if overlaps(r, pane["rect"]):
                            nodes.append({"name": n.name(), "type": n.type().name(), "label": n.type().description(), "rect": r, "selected": bool(n.isSelected())})
                        if len(nodes) >= MAX_NODES:
                            break
                    out["network"] = {"path": pwd.path(), "rect": pane["rect"], "nodes": nodes}
            elif kind == "Parm":
                node = t.currentNode()
                if qt_rects.get("Parm"):
                    pane["rect"] = scaled(qt_rects["Parm"])
                if node is not None and "parm" not in out:
                    out["parm"] = {"node": node.path(), "type": node.type().name(), "label": node.type().description(), "labels": parm_labels(node.parmTemplateGroup()),
                                   **({"rect": pane["rect"]} if "rect" in pane else {})}
            elif kind == "SceneViewer":
                if qt_rects.get("SceneViewer"):
                    pane["rect"] = scaled(qt_rects["SceneViewer"])
                state = t.currentState()
                pane["state"] = state
                out.setdefault("viewer", {"state": state, **({"rect": pane["rect"]} if "rect" in pane else {})})
            out["panes"].append(pane)
        except Exception:
            continue
    return out


def gather(hou, properties=(), attributes=()) -> dict:
    """The state the evaluator understands, and the interface for highlighting. Runs on Houdini's main thread only."""
    counts, names = node_types(hou)
    out: dict = {"node_counts": counts, "nodes": sorted(counts), "node_names": names,
                 "selection_types": ["NODE"] * len(hou.selectedNodes())}
    try:
        if hou.isUIAvailable():
            out["ui"] = ui_snapshot(hou)
    except Exception:
        pass
    out["ui_rev"] = _revs.bump("ui", out.get("ui"))
    out["scene_rev"] = _revs.bump("scene", {"counts": counts, "names": names})
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
