"""Probe state (node counts, names, requested paths), the three extra evaluator kinds, and the shared read."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ingestion.evaluator import evaluate_step
from shared.step_record import StatePredicate as P
from shared.step_record import Step

ADDON = Path(__file__).parents[1] / "vision" / "blender_addon" / "guidewire_probe.py"


def _addon():
    spec = importlib.util.spec_from_file_location("guidewire_probe", ADDON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _step(*preds):
    return Step(id="s01", order=1, goal="g", expected_state=list(preds), confidence=1.0, verifiable=True)


def test_evaluator_node_count_name_exists_attribute_exists():
    counts = {"probe": True, "node_counts": {"BONE": 9, "ARMATURE": 1}, "node_names": ["Cube", "Armature"], "attributes": {"Cube.my_prop": True, "Cube.nope": False}}
    assert evaluate_step(_step(P(kind="node_count", target="bone", value=9)), counts).status == "met"
    assert evaluate_step(_step(P(kind="node_count", target="BONE", value=10)), counts).status == "unmet"
    assert evaluate_step(_step(P(kind="node_count", target="BONE", value=1)), {}).status == "unverifiable"
    no_probe = {k: v for k, v in counts.items() if k != "probe"}                  # same data, probe not running
    assert evaluate_step(_step(P(kind="name_exists", target="Cube")), no_probe).status == "unverifiable"
    assert evaluate_step(_step(P(kind="name_exists", target="Cube")), counts).status == "met"
    assert evaluate_step(_step(P(kind="name_exists", target="cube")), counts).status == "unmet"   # exact, as the Outliner shows
    assert evaluate_step(_step(P(kind="attribute_exists", target="Cube.my_prop")), counts).status == "met"
    assert evaluate_step(_step(P(kind="attribute_exists", target="Cube.nope")), counts).status == "unmet"
    assert evaluate_step(_step(P(kind="attribute_exists", target="Cube.other")), counts).status == "unverifiable"   # never tested


def test_addon_gather_with_fake_blender():
    probe = _addon()
    cube = NS(type="MESH", name="Cube", constraints=[], pose=None, modifiers=[NS(type="SUBSURF")], location=[1.5, 0, 0],
              keys=lambda: ["my_prop"], select_get=lambda: True)
    arm = NS(type="ARMATURE", name="Rig", constraints=[], pose=NS(bones=[NS(constraints=[NS(type="IK")])]), modifiers=[],
             data=NS(bones=[NS(name="b1"), NS(name="b2")]), keys=lambda: [])

    class Objs(dict):
        def __iter__(self):
            return iter(self.values())

    objs = Objs(Cube=cube, Rig=arm)
    objs.get = lambda n, d=None: dict.get(objs, n, d)
    bpy = NS(data=NS(objects=objs, armatures=[arm.data]),
             context=NS(mode="OBJECT", workspace=NS(name="Layout", tools=NS(from_space_view3d_mode=lambda *a, **k: None)),
                        selected_objects=[cube], active_object=cube, scene=NS()))
    state = probe.gather(bpy, ["objects['Cube'].location[0]", "objects['Cube'].__class__", "os.system('x')"], ["Cube.my_prop", "Cube.zzz"])
    assert state["nodes"] == ["ARMATURE", "BONE", "CONSTRAINT_IK", "MESH", "MODIFIER_SUBSURF"]
    assert state["node_counts"]["BONE"] == 2 and state["node_names"] == ["Cube", "Rig", "b1", "b2"]
    assert state["properties"] == {"objects['Cube'].location[0]": 1.5}        # dunder and calls refused
    assert state["attributes"] == {"Cube.my_prop": True, "Cube.zzz": False}
    assert state["selection_types"] == ["MESH"]


def test_probe_records_requested_paths_and_client_sends_them(tmp_path):
    from vision.probe_client import read_probe
    probe = _addon()
    probe._state.clear()
    probe._state.update({"mode": "OBJECT"})
    probe._wanted["properties"].clear()
    server = HTTPServer(("127.0.0.1", 0), probe._make_handler("tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info = tmp_path / "probe.json"
    info.write_text(json.dumps({"v": 1, "port": server.server_address[1], "token": "tok"}))
    state = read_probe(info_path=str(info), properties=["objects['Cube'].location[0]"], attributes=["Cube.my_prop"])
    server.shutdown()
    assert state == {"mode": "OBJECT"}                                         # not read yet: main thread does that
    assert probe._wanted["properties"] == {"objects['Cube'].location[0]"} and probe._wanted["attributes"] == {"Cube.my_prop"}


def test_service_shares_one_read_between_ground_and_observe(monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from shared.grounding import CaptureGeometry, Rect
    from vision import ocr, service
    reads = []
    monkeypatch.setattr(ocr, "read_text", lambda px, scale=2.0: reads.append(1) or [])
    svc = service.VisionService(use_probe=False)
    win = NS(rect=Rect(0, 0, 400, 300))
    px = np.full((300, 400, 3), 40, np.uint8)
    frame = NS(pixels=px, geometry=CaptureGeometry(win.rect, 400, 300))
    monkeypatch.setattr(svc, "_frame", lambda: (win, (frame, px)))
    svc.ground("File")
    svc.observe()
    assert len(reads) == 1                                                     # the second call reused the read
    px2 = px.copy()
    px2[50:250, 50:350] = 220                                                  # the screen changed
    monkeypatch.setattr(svc, "_frame", lambda: (win, (NS(pixels=px2, geometry=frame.geometry), px2)))
    svc.observe()
    assert len(reads) == 2
