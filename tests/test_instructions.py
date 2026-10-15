"""Actionable steps: the real Maya Part 9 response (tests/fixtures/real_runs/R5) as the 'before', the composer and prompt v5 as the 'after'. No network, no model."""
import json
from pathlib import Path

import pytest

from ingestion.extract import DraftStepList, _to_steplist, build_system_prompt, extract_from_text
from ingestion.instructions import compose_instructions
from ingestion.profiles import get_profile
from ingestion.providers.fake import ScriptedProvider
from ingestion.validate import sanitize_and_annotate
from shared.step_record import Step

R5 = json.loads((Path(__file__).parent / "fixtures" / "real_runs" / "R5_maya_part9_v4_raw.json").read_text(encoding="utf-8"))


def before():
    return _to_steplist(DraftStepList.model_validate(R5["raw_response"]), source_type="youtube", app="maya", video_id="dc3iRo0hb3g", model_id="m", prompt_version="v4")


def after():
    sl = before()
    compose_instructions(sl)
    return sanitize_and_annotate(sl, get_profile("maya"), 1151)


def test_before_the_real_response_had_nothing_a_learner_could_act_on():
    sl = before()
    assert all(not s.actions and not s.how_to and not s.check for s in sl.steps)          # the diagnosis: details sat in evidence text only


def test_menu_paths_settings_and_values_from_the_steps_own_evidence_become_actions_and_lines():
    sl = after()
    orient, constrain, attr = sl.steps[3], sl.steps[5], sl.steps[7]
    assert [h.text for h in orient.how_to][:3] == ["Open Skeleton > Orient Joint.", "Set Primary Axis to X.", "Set Secondary Axis to Y."]
    assert [(a.ui_element, a.value) for a in constrain.actions] == [("Constrain > Parent", None), ("Maintain Offset", "on")]
    assert [(a.ui_element, a.value) for a in attr.actions][1:] == [("Attribute Name", "FK_IK_Switch"), ("Minimum", "0"), ("Maximum", "1")]
    assert all(h.support == "shown" and h.evidence for st in sl.steps for h in st.how_to)             # every line says where it came from


def test_nothing_is_added_that_the_evidence_does_not_contain():
    sl = after()
    for st in sl.steps:
        quoted = " ".join(st.evidence + [st.visual_evidence or ""]).lower()
        for a in st.actions:
            assert (a.ui_element or "").split(" > ")[-1].lower().rstrip(".") in quoted or (a.ui_element or "").lower() in quoted
            assert a.value is None or a.value.lower() in quoted or a.value == "on"
    assert after().steps[0].actions == []                                                              # "Skeleton menu / Create Joints" is no menu path: nothing invented


def test_checks_are_labelled_as_catalog_guidance_not_as_shown():
    sl = after()
    chk = [h for st in sl.steps for h in st.check]
    assert chk and all(h.support == "catalog" for h in chk)
    assert "Check that the joints form one chain" in sl.steps[0].check[0].text
    assert not any("1e-4" in h.text or "within" in h.text for h in chk)                                # the matrix's test tolerances are not shown to learners


def test_menu_names_the_vocabulary_knows_are_not_flagged_unknown():
    flags = " ".join(f for s in after().steps for f in s.flags)
    assert "not in the maya vocabulary" not in flags


def test_composer_is_idempotent_and_leaves_model_written_lines_alone():
    sl = after()
    first = sl.model_dump_json()
    compose_instructions(sl)
    assert sl.model_dump_json() == first
    st = Step(id="s1", order=1, goal="g", evidence=["Constrain > Parent"], how_to=[{"text": "Do the thing", "support": "said", "evidence": "he says so"}])
    from shared.step_record import StepList
    sl2 = StepList(source_type="written", app="maya", steps=[st])
    compose_instructions(sl2)
    assert [h.text for h in sl2.steps[0].how_to] == ["Do the thing"]


def test_a_shown_or_said_line_without_evidence_is_flagged():
    st = Step(id="s1", order=1, goal="Orient the joints", how_to=[{"text": "Open Skeleton > Orient Joint.", "support": "shown"}])
    from shared.step_record import StepList
    sl = sanitize_and_annotate(StepList(source_type="written", app="maya", steps=[st]), get_profile("maya"))
    assert any("give no evidence" in f for f in sl.steps[0].flags)


def test_prompt_v5_demands_actionable_steps_and_older_prompts_are_untouched():
    p5 = build_system_prompt(get_profile("maya"), "v5")
    assert "ACTIONABLE STEPS" in p5 and "NEVER write a menu location" in p5 and "feature_id" in p5 and "node_exists" in p5
    assert "ACTIONABLE STEPS" not in build_system_prompt(get_profile("maya"), "v4")
    assert "ACTIONABLE" not in build_system_prompt(get_profile("blender"), "v2")


def test_model_written_how_to_lines_pass_through_extraction():
    resp = {"steps": [{"goal": "Orient the joints", "confidence": 0.9, "support": "both", "visual_evidence": "Orient Joint Options window is open.", "evidence": ["Skeleton > Orient Joint"],
                       "result": "Every joint's X axis points down its bone.",
                       "how_to": [{"text": "Select the root joint.", "support": "shown", "evidence": "root joint highlighted in the Outliner"},
                                  {"text": "Open Skeleton > Orient Joint.", "support": "said", "evidence": "'go to skeleton and orient joint'"}],
                       "check": [{"text": "The axes line up along each bone.", "support": "shown", "evidence": "axes displayed after applying"}]}]}
    sl = extract_from_text(ScriptedProvider([resp]), "orient the joints", app="maya", prompt_version="v5")
    st = sl.steps[0]
    assert [h.text for h in st.how_to] == ["Select the root joint.", "Open Skeleton > Orient Joint."] and st.result.startswith("Every joint's")
    assert st.check[0].support == "shown" and not any("give no evidence" in f for f in st.flags)


@pytest.mark.parametrize("bad", [{"text": "x", "support": "catalog"}, {"text": "x", "support": "invented"}])
def test_the_model_cannot_claim_catalog_support(bad):
    with pytest.raises(Exception):
        DraftStepList.model_validate({"steps": [{"goal": "g", "confidence": 0.5, "how_to": [bad]}]})
