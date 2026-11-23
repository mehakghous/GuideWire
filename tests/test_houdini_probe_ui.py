"""The Houdini probe's interface snapshot, with a fake `hou`. The numbers are the ones measured in a real Houdini 22.0.466 window (docs/houdini_grounding.md): the network editor pane at
(932, 395, 433 x 235) and packfolder1's corners at posToScreen (178, 77) and (265, 98), which put its tile at (1110, 532, 87 x 21) on screen, where the capture showed it."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROBES = Path(__file__).resolve().parents[1] / "vision" / "probes"


def _probe():
    if str(PROBES) not in sys.path:
        sys.path.insert(0, str(PROBES))
    return importlib.import_module("houdini_probe")


class V(tuple):
    def __add__(self, o):
        return V((self[0] + o[0], self[1] + o[1]))


class Geo:
    def __init__(self, x, y, w, h):
        self._r = (x, y, w, h)

    def x(self): return self._r[0]
    def y(self): return self._r[1]
    def width(self): return self._r[2]
    def height(self): return self._r[3]


class NodeType:
    def __init__(self, name, label):
        self._n, self._l = name, label

    def name(self): return self._n
    def description(self): return self._l


class Template:
    def __init__(self, label, children=None):
        self._l, self._c = label, children

    def label(self): return self._l

    def __getattr__(self, name):
        if name == "parmTemplates" and self._c is not None:
            return lambda: self._c
        raise AttributeError(name)


class Group:
    def __init__(self, entries): self._e = entries
    def entries(self): return self._e


class Node:
    def __init__(self, name, type_, label, pos, size=(87 / 77, 21 / 77), selected=False, templates=()):      # the measured tile: 87 x 21 px at 77 px per unit
        self._name, self._type, self._pos, self._size, self._sel, self._t = name, NodeType(type_, label), V(pos), V(size), selected, templates

    def name(self): return self._name
    def type(self): return self._type
    def position(self): return self._pos
    def size(self): return self._size
    def isSelected(self): return self._sel
    def path(self): return "/obj/gw_test/" + self._name
    def parmTemplateGroup(self): return Group(list(self._t))


class Net:
    def __init__(self, nodes): self._n = nodes
    def children(self): return self._n
    def path(self): return "/obj/gw_test"


class Tab:
    def __init__(self, kind, name, current=True, **kw):
        self._k, self._name, self._cur, self.kw = kind, name, current, kw

    def type(self): return f"paneTabType.{self._k}"
    def name(self): return self._name
    def isCurrentTab(self): return self._cur
    def qtScreenGeometry(self): return self.kw["geo"]
    def pwd(self): return self.kw["net"]
    def currentNode(self): return self.kw.get("node")
    def currentState(self): return self.kw["state"]

    def posToScreen(self, p):                    # the measured view: packfolder1 at (0, 1.1295) -> (178, 77); 1 unit = 77 px, x origin 178
        return (178 + (p[0] - 0.0) * 77, 77 + (p[1] - 1.1295) * 77)


class Desktop:
    def __init__(self, tabs): self._t = tabs
    def paneTabs(self): return self._t


def _hou(tabs):
    class Ui:
        def curDesktop(self): return Desktop(tabs)
    class Hou:
        ui = Ui()
    return Hou()


PACK_TEMPLATES = (Template("Parent Folder"), Template("Replace Method"), Template("Pack Output"), Template("Names", [Template("Name"), Template("Type")]))


def _world(dpr=1.0):
    pack = Node("packfolder1", "packfolder", "Pack Folder", (0.0, 1.1295), selected=True, templates=PACK_TEMPLATES)
    box = Node("box1", "box", "Box", (0.0, 0.0))
    far = Node("far1", "null", "Null", (40.0, 40.0))                       # far outside the visible part of the network
    tabs = [Tab("NetworkEditor", "panetab7", geo=Geo(932, 395, 433, 235), net=Net([pack, box, far])),
            Tab("Parm", "panetab5", node=pack),
            Tab("SceneViewer", "panetab1", state="sopview"),
            Tab("TreeView", "panetab8", current=False)]
    return _hou(tabs), {"Parm": [932, 165, 433, 201], "SceneViewer": [33, 197, 865, 433]}


def test_node_tile_is_where_the_real_capture_showed_it():
    p = _probe()
    assert p.node_rect([932, 395, 433, 235], (178.0, 77.0), (265.0, 98.0)) == [1110, 532, 87, 21]


def test_the_snapshot_has_panes_visible_nodes_the_parameter_pane_and_the_viewer():
    p = _probe()
    hou, qt = _world()
    ui = p.ui_snapshot(hou, qt, 1.0)
    assert [x["type"] for x in ui["panes"]] == ["NetworkEditor", "Parm", "SceneViewer"]          # only current tabs
    net = ui["network"]
    assert net["path"] == "/obj/gw_test" and net["rect"] == [932, 395, 433, 235]
    names = {n["name"]: n for n in net["nodes"]}
    assert set(names) == {"packfolder1", "box1"}                                                  # far1 is not in view: left out
    assert names["packfolder1"]["rect"][:2] == [1110, 532] and names["packfolder1"]["label"] == "Pack Folder" and names["packfolder1"]["selected"]
    assert ui["parm"] == {"node": "/obj/gw_test/packfolder1", "type": "packfolder", "label": "Pack Folder",
                          "labels": ["Parent Folder", "Replace Method", "Pack Output", "Names", "Name", "Type"], "rect": [932, 165, 433, 201]}
    assert ui["viewer"] == {"state": "sopview", "rect": [33, 197, 865, 433]}


def test_display_scaling_turns_logical_pixels_into_physical_ones():
    p = _probe()
    hou, qt = _world()
    ui = p.ui_snapshot(hou, qt, 1.25)
    assert ui["network"]["rect"] == [1165, 494, 541, 294] and ui["parm"]["rect"] == [1165, 206, 541, 251]


def test_without_qt_the_pane_rectangles_are_left_out_not_guessed():
    p = _probe()
    hou, _ = _world()
    ui = p.ui_snapshot(hou, {}, 1.0)
    assert "rect" not in ui["parm"] and "rect" not in ui["viewer"] and ui["network"]["rect"] == [932, 395, 433, 235]


def test_the_revision_moves_only_when_the_interface_changes():
    p = _probe()
    r = p.Revisions()
    a = r.bump("ui", {"x": 1})
    assert r.bump("ui", {"x": 1}) == a and r.bump("ui", {"x": 2}) == a + 1
