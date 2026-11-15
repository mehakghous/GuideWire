"""Maya and Houdini probes (against fake `maya.cmds` / `hou` objects: neither application is installed here),
the shared probe server, app profiles and history matching with Maya-style command names."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from shared.step_record import Action
from vision.apps import PROFILES, profile
from vision.history import action_matches
from vision.probe_client import read_probe

PROBES = Path(__file__).parents[1] / "vision" / "probes"


def _load(name):
    sys.path.insert(0, str(PROBES))
    try:
        spec = importlib.util.spec_from_file_location(name, PROBES / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(PROBES))


def test_profiles():
    assert set(PROFILES) == {"blender", "maya", "houdini"}
    assert profile("Maya").title == "Maya" and profile("blender").validated and not profile("houdini").validated
    assert profile("blender").toolbar and not profile("maya").toolbar
    with pytest.raises(ValueError):
        profile("zbrush")


def _fake_cmds():
    nodes = {"|persp": "transform", "|pCube1": "transform", "|pCube1|pCubeShape1": "mesh", "|j1": "joint"}
    attrs = {"pCube1.translateX": 2.5, "pCube1.visibility": True}
    return NS(
        ls=lambda *a, long=False, selection=False, **k: (["|pCube1"] if selection else
                                                          list(nodes) if long else ["persp", "pCube1", "j1"]),
        nodeType=lambda n: nodes[n], listRelatives=lambda n, **k: ["|pCube1|pCubeShape1"] if n == "|pCube1" else [],
        getAttr=lambda p: attrs[p], objExists=lambda a: a in attrs, currentCtx=lambda: "moveSuperContext")


def test_maya_probe_gather_with_fake_cmds():
    maya = _load("maya_probe")
    state = maya.gather(_fake_cmds(), ["pCube1.translateX", "pCube1.nope"], ["pCube1.visibility", "pCube1.zzz"],
                        ["polyCube -w 1 -h 1;", "// Result: pCube1 //", "cmds.move(2, 0, 0)", "# comment"])
    assert state["node_counts"] == {"transform": 2, "mesh": 1, "joint": 1}
    assert "joint" in state["nodes"] and state["selection_types"] == ["MESH"]
    assert state["properties"] == {"pCube1.translateX": 2.5}               # an unreadable path is left out
    assert state["attributes"] == {"pCube1.visibility": True, "pCube1.zzz": False}
    assert state["active_tool"] == "moveSuperContext"
    assert [e["id"] for e in state["history"]] == ["polyCube", "move"]       # results and comments are not commands


def test_houdini_probe_gather_with_fake_hou():
    houdini = _load("houdini_probe")

    class N:
        def __init__(self, name, type_name, desc, parms=()):
            self._n, self._t, self._d, self._p = name, type_name, desc, parms

        def name(self):
            return self._n

        def type(self):
            return NS(name=lambda: self._t, description=lambda: self._d)

        def parm(self, p):
            return NS() if p in self._p else None

    geo = N("geo1", "geo", "Geometry")
    rig = N("rigdoctor1", "kinefx::rigdoctor", "Rig Doctor", parms=("tx",))
    root = NS(allSubChildren=lambda: [geo, rig])
    hou = NS(node=lambda p: root if p == "/" else (rig if p == "/obj/rigdoctor1" else None),
             selectedNodes=lambda: [geo],
             parm=lambda p: NS(eval=lambda: 4.0) if p == "/obj/geo1/tx" else (_ for _ in ()).throw(KeyError(p)),
             undos=NS(undoLabels=lambda: ["Set Parameter", "Create Node"]),            # newest first
             ui=NS(paneTabOfType=lambda t: NS(currentState=lambda: "select")), paneTabType=NS(SceneViewer=1))
    state = houdini.gather(hou, ["/obj/geo1/tx", "/obj/none/ty"], ["/obj/rigdoctor1/tx", "/obj/rigdoctor1/zz"])
    assert state["node_counts"]["Rig Doctor"] == 1 and state["node_counts"]["kinefx::rigdoctor"] == 1
    assert state["node_names"] == ["geo1", "rigdoctor1"] and state["selection_types"] == ["NODE"]
    assert state["properties"] == {"/obj/geo1/tx": 4.0}
    assert state["attributes"] == {"/obj/rigdoctor1/tx": True, "/obj/rigdoctor1/zz": False}
    assert [e["name"] for e in state["history"]] == ["Create Node", "Set Parameter"]     # oldest first
    assert state["active_tool"] == "select"


def test_probe_core_serves_token_protected_state_and_client_filters_by_app(tmp_path, monkeypatch):
    core = _load("probe_core")
    seen = []

    def read(props, attrs):
        seen.append((props, attrs))
        return {"nodes": ["joint"]}
    server = HTTPServer(("127.0.0.1", 0), core.make_handler("tok", read))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info = tmp_path / "probe.json"
    info.write_text(json.dumps({"v": 1, "app": "maya", "port": server.server_address[1], "token": "tok"}))
    assert read_probe(info_path=str(info), app="maya", properties=["a.b"], attributes=["c.d", "e.f"]) == {"nodes": ["joint"]}
    assert seen == [(["a.b"], ["c.d", "e.f"])]
    assert read_probe(info_path=str(info), app="houdini") is None             # another app's probe is running
    info.write_text(json.dumps({"v": 1, "app": "maya", "port": server.server_address[1], "token": "bad"}))
    assert read_probe(info_path=str(info), app="maya") is None                # wrong token is refused
    server.shutdown()
    assert core.split_paths({"properties": ["a, b ,", "x" * 500]}, "properties") == ["a", "b"]


def test_history_matches_maya_and_houdini_style_names():
    create = Action(verb="click", ui_element="Create > Polygon Primitives > Cube")
    assert action_matches(create, {"id": "polyCube", "name": "polyCube"})
    assert not action_matches(create, {"id": "polySphere", "name": "polySphere"})
    assert action_matches(Action(verb="click", ui_element="Add > Mesh > Cube"), {"id": "x", "name": "Add Cube"})
    assert action_matches(Action(verb="click", ui_element="Edit > Delete"), {"id": "delete", "name": "delete"})
