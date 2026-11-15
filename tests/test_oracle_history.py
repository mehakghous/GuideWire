"""Oracle scorer (units, axes, frame rate) and history-based verification. Pure: no Blender needed."""
from __future__ import annotations

from shared.step_record import Action
from verification.oracle import normalize, score, to_y_up
from vision.history import HistoryTracker, action_matches, new_events, verify_actions


def _scene(app, up, unit, loc, fps=24, end=120):
    return {"app": app, "up_axis": up, "unit_scale": unit, "fps": fps, "frames": {"start": 1, "end": end},
            "node_types": {"MESH": 2, "BONE": 3}, "node_names": ["Cube", "Rig"], "mode": "OBJECT",
            "selection_types": ["MESH"], "transforms": {"Cube": {"location": loc, "scale": [1, 2, 3]}}}


def test_axis_and_unit_normalisation_makes_apps_comparable():
    blender = _scene("blender", "Z", 1.0, [1, 2, 3])            # metres, Z up
    maya = _scene("maya", "Y", 0.01, [100, 300, -200])              # centimetres, Y up: the same point
    maya["transforms"]["Cube"]["scale"] = [1, 3, 2]             # Y-up scale of the same object
    assert to_y_up([1, 2, 3], "Z") == [1, 3, -2]
    result = score(blender, maya)
    assert result.total == 1.0 and not result.skipped


def test_frame_rate_normalisation():
    a = _scene("blender", "Z", 1.0, [0, 0, 0], fps=24, end=49)   # 2 s
    b = _scene("houdini", "Y", 1.0, [0, 0, 0], fps=30, end=61)   # 2 s
    assert score(a, b).parts["frames"] == 1.0
    assert normalize(a)["frames"]["end"] == 2.0
    c = _scene("houdini", "Y", 1.0, [0, 0, 0], fps=30, end=49)   # 1.6 s: a different length
    assert score(a, c).parts["frames"] == 0.0


def test_score_drops_missing_parts_instead_of_penalising():
    ref = {"node_types": {"MESH": 1}, "transforms": {"Cube": {"location": [0, 0, 0]}}}
    s = score(ref, {"node_types": {"MESH": 1}})
    assert s.total == 1.0 and "transforms" in s.skipped
    assert score(ref, {"node_types": {"CAMERA": 1}}).total == 0.0
    extra = score({"node_types": {"MESH": 1}}, {"node_types": {"MESH": 1, "LIGHT": 3}})
    assert 0.0 < extra.total < 1.0                                  # extras cost a little, not everything
    assert score({}, {"node_types": {"MESH": 1}}).total == 0.0


def _ev(*names):
    return [{"id": n.lower().replace(" ", "."), "name": n} for n in names]


def test_history_tracker_returns_only_new_events():
    t = HistoryTracker()
    assert t.update(_ev("Select")) == []                             # the first read is a baseline
    assert [e["name"] for e in t.update(_ev("Select", "Add Cube"))] == ["Add Cube"]
    assert [e["name"] for e in t.update(_ev("Select", "Add Cube", "Move"))] == ["Move"]
    assert t.update(_ev("Select", "Add Cube", "Move")) == []
    assert [e["name"] for e in t.update(_ev("Add Cube", "Move", "Rotate"))] == ["Rotate"]   # oldest dropped off
    assert t.update(None) == []
    assert [e["name"] for e in new_events(_ev("A"), _ev("A", "A"))] == ["A"]


def test_action_matching_and_verification():
    add_cube = Action(verb="click", ui_element="Add > Mesh > Cube")
    move = Action(verb="click", ui_element="Object > Transform > Move")
    assert action_matches(add_cube, {"id": "mesh.primitive_cube_add", "name": "Add Cube"})
    assert not action_matches(add_cube, {"id": "mesh.primitive_uv_sphere_add", "name": "Add UV Sphere"})
    assert action_matches(move, {"id": "transform.translate", "name": "Move"})
    assert not action_matches(Action(verb="press_keys", keys=["G"]), {"name": "Move"})
    events = [{"id": "mesh.primitive_cube_add", "name": "Add Cube"}]
    assert verify_actions([add_cube], events) is True
    assert verify_actions([add_cube, move], events) is False         # the move is missing
    assert verify_actions([add_cube], []) is None                    # nothing to judge
    assert verify_actions([Action(verb="press_keys", keys=["G"])], events) is None
