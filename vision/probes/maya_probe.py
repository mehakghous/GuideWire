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


# Maya's tool-box buttons (object names) and the tool context each one selects; checked against Maya 2027.3 with cmds.setToolTo / cmds.currentCtx.
TOOLBOX_CONTEXTS = {"selectTool": "selectSuperContext", "lassoTool": "lassoSelectContext", "paintSelectTool": "artSelectContext",
                    "moveTool": "moveSuperContext", "rotateTool": "RotateSuperContext", "scaleTool": "scaleSuperContext"}
# Named containers Maya creates, and the key each is reported under.
REGIONS = {"toolbox": "ToolBox", "shelf": "Shelf", "statusline": "StatusLine", "timeslider": "TimeSlider", "rangeslider": "RangeSlider",
           "commandline": "CommandLine", "channelbox": "ChannelBoxForm"}
MENU_SET_COMBO = "menuMode"        # the "Modeling / Rigging / Animation ..." dropdown at the left of the status line


class QtApi:
    """Reads Maya's own Qt widgets. Every rectangle is in screen pixels (Qt's global coordinates times the device pixel ratio), top-left origin.
    Written against Maya 2027 (PySide6) and checked on it; PySide2 is the fallback for older versions."""

    def __init__(self) -> None:
        from maya import OpenMayaUI as omui
        try:
            from PySide6 import QtCore, QtWidgets
            from shiboken6 import wrapInstance
        except ImportError:
            from PySide2 import QtCore, QtWidgets
            from shiboken2 import wrapInstance
        self.omui, self.QtCore, self.QtWidgets, self.wrap = omui, QtCore, QtWidgets, wrapInstance
        self.main = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

    def _rect(self, w) -> dict:
        p, k = w.mapToGlobal(self.QtCore.QPoint(0, 0)), w.devicePixelRatioF()
        return {"x": round(p.x() * k), "y": round(p.y() * k), "w": round(w.width() * k), "h": round(w.height() * k)}

    def widget(self, name: str):
        ptr = self.omui.MQtUtil.findControl(name)
        return self.wrap(int(ptr), self.QtWidgets.QWidget) if ptr else None

    def main_rect(self) -> dict:
        return self._rect(self.main)

    def control_rect(self, name: str) -> dict | None:
        w = self.widget(name)
        return self._rect(w) if w is not None and w.isVisible() else None

    def toolbox(self) -> list[dict]:
        box = self.widget("ToolBox")
        out = []
        for b in (box.findChildren(self.QtWidgets.QAbstractButton) if box is not None else []):
            if b.isVisible() and b.objectName() in TOOLBOX_CONTEXTS:
                out.append({"name": b.objectName(), "tip": b.toolTip(), "rect": self._rect(b), "checked": bool(b.isChecked())})
        return out

    def menubar(self) -> list[dict]:
        bar = self.main.findChild(self.QtWidgets.QMenuBar)
        out = []
        for a in (bar.actions() if bar is not None else []):
            r = bar.actionGeometry(a)
            if r.width() > 0 and r.height() > 0 and a.text().strip():
                p, k = bar.mapToGlobal(r.topLeft()), bar.devicePixelRatioF()
                out.append({"label": a.text().replace("&", "").strip(), "rect": {"x": round(p.x() * k), "y": round(p.y() * k), "w": round(r.width() * k), "h": round(r.height() * k)}})
        return out

    def combo(self, object_name: str) -> tuple[str, dict] | None:
        for c in self.main.findChildren(self.QtWidgets.QComboBox):
            if c.objectName() == object_name and c.isVisible():
                return c.currentText(), self._rect(c)
        return None


def interface_snapshot(api, cmds) -> dict:
    """What is on screen and where, from Maya itself: the tool box (with the active tool), the current shelf and its buttons (with their tooltips), the menu bar,
    the menu-set dropdown, and the panel regions. Screen pixels. Runs on Maya's main thread only."""
    out: dict = {"v": 1, "window": api.main_rect(), "regions": {}}
    for key, name in REGIONS.items():
        r = api.control_rect(name)
        if r:
            out["regions"][key] = r
    for key, kind in (("viewport", "modelPanel"), ("outliner", "outlinerPanel")):
        for panel in cmds.getPanel(type=kind) or []:
            r = api.control_rect(panel)
            if r:
                out["regions"][key] = r
                break
    out["toolbox"] = [dict(b, context=TOOLBOX_CONTEXTS[b["name"]]) for b in api.toolbox()]
    out["menubar"] = api.menubar()
    combo = api.combo(MENU_SET_COMBO)
    if combo:
        out["menu_set"] = {"label": combo[0], "id": cmds.menuSet(q=True, currentMenuSet=True), "rect": combo[1]}
    try:
        tab = cmds.shelfTabLayout("ShelfLayout", q=True, selectTab=True)
        buttons = []
        for name in cmds.shelfLayout(tab, q=True, childArray=True) or []:
            r = api.control_rect(name)
            if r is None:
                continue
            note = cmds.shelfButton(name, q=True, annotation=True) if cmds.shelfButton(name, exists=True) else ""
            label = cmds.shelfButton(name, q=True, label=True) if cmds.shelfButton(name, exists=True) else ""
            buttons.append({"name": name, "annotation": note or "", "label": label or "", "rect": r})
        out["shelf"] = {"tab": tab, "buttons": buttons}
    except Exception:
        pass
    return out


def gather(cmds, properties=(), attributes=(), history_lines=(), api=None) -> dict:
    """The state the evaluator understands. Runs on Maya's main thread only."""
    counts = node_types(cmds)
    out: dict = {"node_counts": counts, "nodes": sorted(counts),
                 "node_names": [n for n in (cmds.ls() or [])],
                 "selection_types": selection_types(cmds), "history": history_events(list(history_lines))}
    try:
        out["active_tool"] = cmds.currentCtx()
    except Exception:
        pass
    if api is not None:
        try:
            out["interface"] = interface_snapshot(api, cmds)
        except Exception as e:                              # the interface is best effort: the rest of the state is still good
            out["interface_error"] = f"{type(e).__name__}: {e}"[:160]
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
        return gather(cmds, properties, attributes, read_tail(), QtApi())
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
