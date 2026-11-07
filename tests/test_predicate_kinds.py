"""Schema 0.11 predicate kinds name_exists, attribute_exists, node_count: the contract rules, the checker (offline) and the three real applications."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.step_record import SCHEMA_VERSION, StatePredicate
from verification.checker import attribute_paths, check_predicate, check_steplist
from verification.runner import find_app, run_script, take_snapshot

from test_verification import FIX, P, steps

needs = {a: pytest.mark.skipif(find_app(a) is None, reason=f"{a} is not installed") for a in ("blender", "maya", "houdini")}
SNAP = {"app": "maya", "node_types": {"joint": 3}, "node_names": ["hip_jnt", "knee_jnt"], "attributes": {"body.FK_IK_Switch": True, "body.nope": False}}


def test_schema_version_and_value_rules():
    assert SCHEMA_VERSION == "0.11"
    StatePredicate(kind="name_exists", target="left_hip_IK_jnt")
    StatePredicate(kind="attribute_exists", target="l_switch_GEO.FK_IK_Switch")
    assert StatePredicate(kind="node_count", target="joint", value=9).value == 9
    for bad in ({"kind": "name_exists", "target": "x", "value": 1}, {"kind": "attribute_exists", "target": "a.b", "value": "x"},
                {"kind": "node_count", "target": "joint"}, {"kind": "node_count", "target": "joint", "value": 0},
                {"kind": "node_count", "target": "joint", "value": 2.5}, {"kind": "node_count", "target": "joint", "value": "many"}):
        with pytest.raises(ValidationError):
            StatePredicate(**bad)
    with pytest.raises(ValidationError):
        StatePredicate(kind="property_equals", target="a.b")           # unchanged rule


def test_model_is_still_offered_only_the_seven_older_kinds():
    from ingestion.extract import DraftPredicate
    kinds = DraftPredicate.model_json_schema()["properties"]["kind"]["enum"]
    assert len(kinds) == 7 and not {"name_exists", "attribute_exists", "node_count"} & set(kinds)


def test_node_count_means_at_least():
    assert check_predicate(P("node_count", "joint", 3), SNAP).outcome == "met"
    assert check_predicate(P("node_count", "joint", 2), SNAP).outcome == "met"
    assert check_predicate(P("node_count", "joint", 4), SNAP).outcome == "unmet"
    assert check_predicate(P("node_count", "ikHandle", 1), SNAP).outcome == "unmet"


def test_name_is_matched_exactly_as_the_outliner_shows_it():
    assert check_predicate(P("name_exists", "knee_jnt"), SNAP).outcome == "met"
    assert check_predicate(P("name_exists", "Knee_Jnt"), SNAP).outcome == "unmet"          # the learner's own name: case matters
    assert check_predicate(P("name_exists", "knee_jnt"), {"app": "maya"}).outcome == "cannot_check"


def test_attribute_met_unmet_and_not_requested():
    assert check_predicate(P("attribute_exists", "body.FK_IK_Switch"), SNAP).outcome == "met"
    assert check_predicate(P("attribute_exists", "body.nope"), SNAP).outcome == "unmet"
    assert check_predicate(P("attribute_exists", "other.attr"), SNAP).outcome == "cannot_check"
    assert check_predicate(P("attribute_exists", "x.y"), {**SNAP, "attributes": {"x.y": {"error": "boom"}}}).outcome == "cannot_check"
    sl = steps("maya", [P("attribute_exists", "body.FK_IK_Switch")], [P("attribute_exists", "a.b"), P("node_exists", "joint")])
    assert attribute_paths(sl) == ["a.b", "body.FK_IK_Switch"]
    assert [r.outcome for r in check_steplist(sl, SNAP)] == ["met", "met"]    # a.b was not tested, joint is met: met, with one predicate unchecked


def _build(app, script, out):
    run_script(app, FIX / script, [str(out)], timeout=300)
    assert Path(out).exists()


def _check(app, scene, *preds):
    sl = steps(app, *[[p] for p in preds])
    snap = take_snapshot(app, str(scene), attribute_paths=attribute_paths(sl))
    return [r.outcome for r in check_steplist(sl, snap)]


@needs["maya"]
def test_maya_real_scene_new_kinds(tmp_path):
    _build("maya", "build_maya.py", tmp_path / "rig.ma")
    assert _check("maya", tmp_path / "rig.ma", P("name_exists", "knee_jnt"), P("name_exists", "left_knee"), P("node_count", "joint", 3), P("node_count", "joint", 4),
                  P("attribute_exists", "body.FK_IK_Switch"), P("attribute_exists", "body.nothing")) == ["met", "unmet", "met", "unmet", "met", "unmet"]


@needs["blender"]
def test_blender_real_scene_new_kinds(tmp_path):
    _build("blender", "build_blender.py", tmp_path / "rig.blend")
    assert _check("blender", tmp_path / "rig.blend", P("name_exists", "lower"), P("name_exists", "Body"), P("name_exists", "upper_L"), P("node_count", "BONE", 2),
                  P("node_count", "BONE", 3), P("attribute_exists", "Rig.FK_IK_Switch"), P("attribute_exists", "Rig.nothing")) == ["met", "met", "unmet", "met", "unmet", "met", "unmet"]


@needs["houdini"]
def test_houdini_real_scene_new_kinds(tmp_path):
    _build("houdini", "build_houdini.py", tmp_path / "char.hip")
    assert _check("houdini", tmp_path / "char.hip", P("name_exists", "char"), P("name_exists", "left_arm"), P("node_count", "Null", 1), P("node_count", "Skeleton", 2),
                  P("attribute_exists", "/obj/char/tx"), P("attribute_exists", "/obj/char/nothing")) == ["met", "unmet", "met", "unmet", "met", "unmet"]
