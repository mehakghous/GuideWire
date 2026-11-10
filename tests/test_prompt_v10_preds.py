"""Prompt v10-preds: v10 plus the three newer kinds of expected state (name_exists, attribute_exists, node_count). Nothing else changes."""
import pytest

from ingestion.extract import PROMPT_VERSIONS, _schema, build_system_prompt, extract_from_video
from ingestion.profiles import get_profile
from ingestion.providers.fake import ScriptedProvider

APPS = ("blender", "maya", "houdini")


def _step(goal, start, end, expected):
    return {"goal": goal, "actions": [{"verb": "click", "ui_element": "Outliner"}], "expected_state": expected, "start_state": [], "video_start_s": start, "video_end_s": end,
            "result": "done", "how_to": [], "check": [], "confidence": 0.8, "kind": "mechanics"}


def test_preds_is_a_listed_version_and_is_v10_plus_one_block():
    assert "v10-preds" in PROMPT_VERSIONS
    for app in APPS:
        v10, preds = build_system_prompt(get_profile(app), "v10"), build_system_prompt(get_profile(app), "v10-preds")
        assert preds.startswith(v10) and preds != v10
        assert "name_exists" in preds and "attribute_exists" in preds and "node_count" in preds and "Use it for every rename step" in preds
        assert "name_exists" not in v10


def test_only_the_preds_version_sees_the_wider_schema():
    older = _schema()["$defs"]["DraftPredicate"]["properties"]["kind"]["enum"]
    assert len(older) == 7 and _schema("v10")["$defs"]["DraftPredicate"]["properties"]["kind"]["enum"] == older
    wider = _schema("v10-preds")["$defs"]["DraftPredicateExt"]["properties"]["kind"]["enum"]
    assert len(wider) == 10 and {"name_exists", "attribute_exists", "node_count"} <= set(wider)
    assert {"expected_state", "how_to", "check"} <= set(_schema("v10-preds")["$defs"]["DraftStepExt"]["required"])      # the same fields are REQUIRED as for the older schema


def test_unknown_suffix_is_still_refused():
    with pytest.raises(ValueError):
        build_system_prompt(get_profile("maya"), "v10-nope")


def test_new_kinds_come_back_as_checkable_state_with_their_values():
    raw = {"steps": [_step("Rename the hip joint to leftHip", "00:05", "00:12", [{"kind": "name_exists", "name": "leftHip", "expected_value": None}]),
                     _step("Add the FK_IK_Switch attribute", "00:20", "00:30", [{"kind": "attribute_exists", "name": "l_switch_GEO.FK_IK_Switch", "expected_value": None}]),
                     _step("Create nine joints", "00:40", "00:55", [{"kind": "node_count", "name": "joint", "expected_value": 9}])]}
    p = ScriptedProvider([raw])
    sl = extract_from_video(p, "AAAAAAAAAAA", app="maya", duration_s=100.0, prompt_version="v10-preds")
    kinds = [(s.expected_state[0].kind, s.expected_state[0].target, s.expected_state[0].value) for s in sl.steps]
    assert kinds == [("name_exists", "leftHip", None), ("attribute_exists", "l_switch_GEO.FK_IK_Switch", None), ("node_count", "joint", 9)]
    assert all(s.verifiable for s in sl.steps) and sl.prompt_version == "v10-preds"
    assert p.calls[0]["schema"]["$defs"]["DraftPredicateExt"]                     # the model was sent the wider schema


def test_the_older_prompts_still_reject_the_new_kinds():
    raw = {"steps": [_step("Rename the hip joint", "00:05", "00:12", [{"kind": "name_exists", "name": "leftHip", "expected_value": None}])]}
    from ingestion.extract import ExtractionError
    with pytest.raises(ExtractionError):
        extract_from_video(ScriptedProvider([raw, raw]), "AAAAAAAAAAA", app="maya", duration_s=100.0, prompt_version="v10")
