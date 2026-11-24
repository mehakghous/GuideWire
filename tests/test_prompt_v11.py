"""Prompt v11: meaningful steps built from the screen (what, where, values) and the narration (why). Each test pins a failure found in the recorded v10 runs
(docs/extraction_v11_report_2026-11-22.md), so the fix cannot quietly come undone."""
import json

import pytest

from ingestion.extract import PROMPT_VERSIONS, _schema, build_system_prompt, extract_from_video, video_prompt
from ingestion.profiles import get_profile
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import SCHEMA_VERSION, Step

APPS = ("blender", "maya", "houdini")

# Names that appeared in v10 steps only because the prompt's own examples contained them ("Target Pattern": 0 times without the Houdini rules, 19 to 46 times with them; the
# instructor never shows it). No v11 prompt may contain a real-looking example a model could copy.
LEAKED_EXAMPLES = ("Target Pattern", "Component Source", "FK Transform", "jnt_*", "leftToe", "jnt_L_hip", "l_switch_GEO", "FK_IK_Switch", "leftHip", "Skeleton > Orient Joint")


def _step(goal, start, end, **kw):
    base = {"goal": goal, "actions": [{"verb": "click", "ui_element": "Skeleton > Mirror Joints"}], "expected_state": [], "start_state": [], "video_start_s": start,
            "video_end_s": end, "result": "done", "how_to": [{"text": "Click Mirror.", "support": "shown", "evidence": "Mirror button clicked"}], "check": [],
            "confidence": 0.8, "kind": "mechanics", "support": "both", "visual_evidence": "the dialog is open", "evidence": ["mirror it"], "why": None}
    return {**base, **kw}


def test_v11_is_listed_and_the_schema_version_moved():
    assert PROMPT_VERSIONS[-4:] == ("v11", "v12", "v13", "v14")
    assert SCHEMA_VERSION == "0.16"


@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("version", ("v11", "v12"))
def test_no_example_a_model_could_copy(app, version):
    p = build_system_prompt(get_profile(app), version) + video_prompt(version, 300, "A title")
    leaked = [x for x in LEAKED_EXAMPLES if x in p]
    assert not leaked, f"real-looking example names in the v11 prompt: {leaked}"


@pytest.mark.parametrize("app", APPS)
def test_v11_asks_for_meaningful_steps_not_atomic_ones_or_filler(app):
    p = build_system_prompt(get_profile(app), "v11")
    assert "ATOMIC STEPS" not in p and "COVERAGE." not in p and "many dozens" not in p              # the v8 and v9 rules that made every click a step and pushed the model to fill gaps
    assert "Fold small enabling actions into the step they serve" in p                              # mode switches and selections live inside the step
    assert "Never split a step only to have more steps" in p
    assert "NARRATION tells you WHY" in p and "SCREEN tells you WHAT" in p                           # both sources, each for what it is good at
    assert "common_mistakes" in p and "undoes or corrects it" in p                                   # an on-screen mistake becomes a warning, not steps


def test_houdini_rules_only_for_houdini_and_without_example_names():
    assert "HOUDINI NODE NETWORKS" in build_system_prompt(get_profile("houdini"), "v11")
    assert "HOUDINI NODE NETWORKS" not in build_system_prompt(get_profile("maya"), "v11")


def test_why_is_required_for_v11_only_and_older_schemas_are_unchanged():
    req = _schema("v11")["$defs"]["DraftStepV11"]["required"]
    assert "why" in req and {"how_to", "check", "expected_state"} <= set(req)
    for v in ("v10", "v10-preds", "v10-hou", "v7"):
        assert "why" not in json.dumps(_schema(v)), v                                                # their requests and cache keys stay as recorded


def test_v11_does_not_change_older_prompts():
    for v in ("v10", "v10-preds", "v10-hou"):
        assert "WHAT ONE STEP IS" not in build_system_prompt(get_profile("houdini"), v)


def test_a_v11_answer_keeps_why_and_mistakes():
    raw = {"steps": [_step("Set up joint name replacement and mirror the leg joints", "03:07", "04:04", why="So the copied joints are named for the right side.",
                           common_mistakes=["The joints are mirrored across the wrong plane if Mirror across is left on its default; the instructor undid it and chose YZ."])]}
    sl = extract_from_video(ScriptedProvider([raw]), "AAAAAAAAAAA", app="maya", duration_s=400, prompt_version="v11")
    s = sl.steps[0]
    assert isinstance(s, Step) and s.why == "So the copied joints are named for the right side."
    assert "wrong plane" in s.common_mistakes[0]
    assert sl.prompt_version == "v11"


def test_a_documented_pitfall_lands_only_on_a_step_it_concerns():
    from ingestion.instructions import concerns_step
    from shared.step_record import HowTo
    node = Step(id="s03", order=3, goal="Create APEX AutoRig Component for FK configuration", how_to=[HowTo(text="Open the Component drop-down menu and select 'FK'.", support="shown", evidence="x")])
    assert not concerns_step("Writing #tag in the Multi IK Segments field: it expects the plain tag names.", node)        # attached to this step by its feature tag in the real v11 run
    orient = Step(id="s04", order=4, goal="Orient the leg joints", how_to=[HowTo(text="Skeleton > Orient Joint, set Secondary Axis World Orientation to +Z.", support="shown", evidence="x")])
    assert concerns_step("Letting Maya orient automatically on a curved chain can flip axes; choose a Secondary Axis World Orientation to fix the up direction.", orient)


def test_a_line_that_changes_a_setting_without_its_value_is_flagged_for_review():
    from ingestion.validate import vague_lines
    from shared.step_record import HowTo

    def lines(*texts):
        return Step(id="s01", order=1, goal="g", how_to=[HowTo(text=t, support="shown", evidence="x") for t in texts])
    assert vague_lines(lines("Adjust shape scale/offset to enlarge control shapes around joints.", "Open the color palette and set a custom control color.")) == [
        "Adjust shape scale/offset to enlarge control shapes around joints.", "Open the color palette and set a custom control color."]      # both from the real v11 Houdini run
    assert vague_lines(lines("Adjust the Shape Offset Scale to 4.1.", "Set Shape Override to Box.", "Set Roll to 90.", "Set Type to 'skel'.")) == []


def test_null_why_is_kept_as_none_never_filled_in():
    sl = extract_from_video(ScriptedProvider([{"steps": [_step("Create the leg joint chain", "00:52", "01:34")]}]), "AAAAAAAAAAA", app="maya", duration_s=400, prompt_version="v11")
    assert sl.steps[0].why is None


# ---- v12: v11 with smaller steps (2026-11-22: "each step is so many mini steps")
@pytest.mark.parametrize("app", APPS)
def test_v12_is_v11_with_only_the_step_size_rules_changed(app):
    v11, v12 = build_system_prompt(get_profile(app), "v11"), build_system_prompt(get_profile(app), "v12")
    assert "ONE operation with ONE result the learner can see" in v12 and "1 to 3 short how_to lines" in v12
    assert "A switch of mode" in v12 and "naming five joints is five steps" in v12               # the earlier division the learner preferred
    assert "Fold small enabling actions" not in v12 and "Fold small enabling actions" in v11
    assert v12.split("STAY TRUE TO THE TUTORIAL.")[1].replace("1 to 3 short", "ordered, short") == v11.split("STAY TRUE TO THE TUTORIAL.")[1]   # the accuracy rules and fields are v11's
    assert v12.split("WHAT ONE STEP IS.")[0] == v11.split("WHAT ONE STEP IS.")[0]                  # and so is the part about the two sources


def test_v12_returns_why_like_v11():
    assert "why" in _schema("v12")["$defs"]["DraftStepV11"]["required"]
