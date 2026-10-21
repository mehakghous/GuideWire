"""Verification harness. Offline tests use hand-made snapshots; the real-application tests skip cleanly when the application is not installed."""
from pathlib import Path

import pytest

from shared.step_record import StatePredicate, Step, StepList
from verification.checker import check_predicate, check_steplist, property_paths
from verification.runner import find_app, run_script, take_snapshot

FIX = Path(__file__).parent / "fixtures" / "verification"


def P(kind, target, value=None):
    return StatePredicate(kind=kind, target=target, value=value)


def steps(app, *preds_per_step, kinds=None):
    return StepList(source_type="written", app=app, steps=[
        Step(id=f"s{i + 1:02d}", order=i + 1, goal=f"step {i + 1}", expected_state=list(ps), kind=(kinds or {}).get(i, "mechanics"))
        for i, ps in enumerate(preds_per_step)])


SNAP = {"app": "maya", "version": "x", "mode": None, "selection_types": ["JOINT"], "node_types": {"joint": 3, "ikHandle": 1},
        "node_names": [], "properties": {"body.translateX": 2.0, "body.note": "hello"}}


# ---------------------------------------------------------------- the comparison logic (no application needed)
def test_node_exists_met_and_unmet_ignoring_case_and_spacing():
    assert check_predicate(P("node_exists", "ikHandle"), SNAP).outcome == "met"
    assert check_predicate(P("node_exists", "IK handle"), {**SNAP, "node_types": {"ik_handle": 1}}).outcome == "met"
    assert check_predicate(P("node_exists", "skinCluster"), SNAP).outcome == "unmet"


def test_property_numbers_use_a_tolerance_and_text_is_compared_loosely():
    assert check_predicate(P("property_equals", "body.translateX", 2.00001), SNAP).outcome == "met"
    assert check_predicate(P("property_equals", "body.translateX", 2.5), SNAP).outcome == "unmet"
    assert check_predicate(P("property_equals", "body.note", "Hello"), SNAP).outcome == "met"


def test_unreadable_things_are_cannot_check_never_met():
    assert check_predicate(P("mode", "OBJECT"), SNAP).outcome == "cannot_check"                    # snapshot has no mode
    for kind, target in (("active_tool", "builtin.move"), ("workspace", "Layout"), ("panel_open", "Properties:Modifiers")):
        assert check_predicate(P(kind, target), SNAP).outcome == "cannot_check"
    assert check_predicate(P("property_equals", "nothing.here", 1), SNAP).outcome == "cannot_check"          # not requested
    assert check_predicate(P("property_equals", "bad.path", 1), {**SNAP, "properties": {"bad.path": {"error": "boom"}}}).outcome == "cannot_check"


def test_selection_types_and_none():
    assert check_predicate(P("selection_type", "JOINT"), SNAP).outcome == "met"
    assert check_predicate(P("selection_type", "MESH"), SNAP).outcome == "unmet"
    assert check_predicate(P("selection_type", "NONE"), {**SNAP, "selection_types": []}).outcome == "met"


def test_step_outcomes_combine_predicates_honestly():
    sl = steps("maya", [P("node_exists", "joint")], [P("node_exists", "joint"), P("node_exists", "skinCluster")],
               [P("node_exists", "joint"), P("workspace", "Layout")], [P("workspace", "Layout")], [], [P("node_exists", "joint")], kinds={5: "craft"})
    r = check_steplist(sl, SNAP)
    assert [x.outcome for x in r] == ["met", "unmet", "met", "unverifiable", "unverifiable", "unverifiable"]
    assert len(r[2].unchecked) == 1                                                          # met, but one predicate could not be read: listed, not hidden


def test_wrong_application_is_refused_and_property_paths_are_collected():
    sl = steps("blender", [P("property_equals", "objects['Body'].location.x", 2.0)])
    assert property_paths(sl) == ["objects['Body'].location.x"]
    with pytest.raises(ValueError, match="snapshot is from"):
        check_steplist(sl, SNAP)


# ---------------------------------------------------------------- real applications (skipped when not installed)
needs = {a: pytest.mark.skipif(find_app(a) is None, reason=f"{a} is not installed") for a in ("blender", "maya", "houdini")}


def _build(app, script, out):
    p = run_script(app, FIX / script, [str(out)], timeout=300)
    assert Path(out).exists(), (p.stdout + p.stderr)[-600:]


@needs["blender"]
def test_blender_real_scene(tmp_path):
    scene = tmp_path / "rig.blend"
    _build("blender", "build_blender.py", scene)
    sl = steps("blender", [P("node_exists", "ARMATURE")], [P("node_exists", "IK")], [P("node_exists", "BONE")], [P("node_exists", "SUBSURF")],
               [P("selection_type", "ARMATURE")], [P("mode", "OBJECT")], [P("property_equals", "objects['Body'].location.x", 2.0)],
               [P("property_equals", "objects['Body'].location.x", 9.0)], [P("workspace", "Layout")])
    snap = take_snapshot("blender", str(scene), property_paths(sl))
    assert snap["app"] == "blender" and snap["version"]
    got = [r.outcome for r in check_steplist(sl, snap)]
    assert got == ["met", "met", "met", "unmet", "met", "met", "met", "unmet", "unverifiable"]


@needs["blender"]
def test_blender_refuses_calls_in_a_property_path(tmp_path):
    snap = take_snapshot("blender", None, ["__import__('os').getcwd()", "objects.clear()"])
    assert all(isinstance(v, dict) and "error" in v for v in snap["properties"].values())


@needs["houdini"]
def test_houdini_real_scene(tmp_path):
    scene = tmp_path / "char.hip"
    _build("houdini", "build_houdini.py", scene)
    sl = steps("houdini", [P("node_exists", "Skeleton")], [P("node_exists", "Null")], [P("node_exists", "Rig Doctor")],
               [P("property_equals", "/obj/char/tx", 2.0)], [P("mode", "ANIMATE")])
    snap = take_snapshot("houdini", str(scene), property_paths(sl))
    assert snap["app"] == "houdini"
    assert [r.outcome for r in check_steplist(sl, snap)] == ["met", "met", "unmet", "met", "unverifiable"]


@needs["maya"]
def test_maya_real_scene(tmp_path):                      # never run: Maya is not installed on the development machine
    scene = tmp_path / "rig.ma"
    _build("maya", "build_maya.py", scene)
    sl = steps("maya", [P("node_exists", "joint")], [P("node_exists", "ikHandle")], [P("node_exists", "skinCluster")],
               [P("property_equals", "body.translateX", 2.0)])
    snap = take_snapshot("maya", str(scene), property_paths(sl))
    assert [r.outcome for r in check_steplist(sl, snap)] == ["met", "met", "unmet", "met"]
