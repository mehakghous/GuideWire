"""Prompt v13 (v12 with Houdini steps as small as the other applications') and the gap pass (a second look at stretches the first pass left without steps). Reported 2026-11-22 on the Houdini
APEX FK tutorial: 8 to 9 steps for 51 labelled actions, four parameters in one step, and the stretch 3:40 to 4:55 (F for Modify mode, moving skeleton points) left out entirely."""
import pytest

from ingestion.extract import PROMPT_VERSIONS, _schema, build_system_prompt, extract_from_video, fill_gaps, find_gaps, video_prompt
from ingestion.profiles import get_profile
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import Step, StepList


def _raw(goal, start, end, **kw):
    base = {"goal": goal, "actions": [{"verb": "other"}], "expected_state": [], "start_state": [], "video_start_s": start, "video_end_s": end, "result": "done",
            "how_to": [{"text": goal + ".", "support": "shown", "evidence": "on screen"}], "check": [], "confidence": 0.8, "kind": "mechanics", "support": "both",
            "visual_evidence": "the node is visible", "evidence": ["said"], "why": None}
    return {**base, **kw}


# ---- v13
def test_v13_is_listed_and_is_v12_for_blender_and_maya():
    assert PROMPT_VERSIONS[-2:] == ("v13", "v14")
    for app in ("blender", "maya"):
        assert build_system_prompt(get_profile(app), "v13") == build_system_prompt(get_profile(app), "v12")
    assert video_prompt("v13", 300, "T") == video_prompt("v12", 300, "T") and _schema("v13") == _schema("v12")


def test_v13_houdini_gives_parameters_and_viewport_keys_their_own_steps():
    v12, v13 = (build_system_prompt(get_profile("houdini"), v) for v in ("v12", "v13"))
    assert "A node is usually one step" in v12 and "A node is usually one step" not in v13
    assert "each parameter the instructor changes" in v13 and "different parameters are different steps" in v13
    assert "each key that starts, changes or ends a viewport state" in v13
    assert v13.split("HOUDINI NODE NETWORKS")[0] == v12.split("HOUDINI NODE NETWORKS")[0]      # everything before the Houdini block is v12's


@pytest.mark.parametrize("leak", ("Target Pattern", "Component Source", "FK Transform", "jnt_", "Control Group", "Use Color", "Shape Offset"))
def test_v13_houdini_has_no_name_a_model_could_copy(leak):
    assert leak not in build_system_prompt(get_profile("houdini"), "v13") + video_prompt("v13", 300, "A title")


# ---- the gap pass
def _first_pass(*steps):
    return extract_from_video(ScriptedProvider([{"steps": list(steps)}]), "AAAAAAAAAAA", app="houdini", duration_s=400, prompt_version="v13")


def test_gaps_are_only_the_long_uncovered_stretches_inside_the_tutorial():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Pack the skeleton", "00:40", "01:00"), _raw("Add a Merge node", "04:55", "05:10"))
    assert find_gaps(sl) == [(60.0, 295.0)]                          # 0:30 to 0:40 is short; before 0:10 and after 5:10 are intro and outro


def test_a_second_look_adds_what_it_finds_in_time_order_flagged_and_renumbered():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Add a Merge node", "04:55", "05:10"))
    clip = {"steps": [_raw("Press F to enter Modify mode", "00:05", "00:07"), _raw("Move a skeleton point", "00:10", "00:20")]}      # times from the START of the clip
    p = ScriptedProvider([clip])
    out = fill_gaps(p, sl, "AAAAAAAAAAA", app="houdini", prompt_version="v13", duration_s=400)
    assert [s.goal for s in out.steps] == ["Create the Skeleton node", "Press F to enter Modify mode", "Move a skeleton point", "Add a Merge node"]
    assert [s.id for s in out.steps] == ["s01", "s02", "s03", "s04"] and [s.order for s in out.steps] == [1, 2, 3, 4]
    clip_start = 30 - 3                                                # the stretch 0:30 to 4:55 with 3 s of context
    assert out.steps[1].video_start_s == clip_start + 5
    assert "found by a second look" in out.steps[1].flags[-1] and not any("second look" in f for f in out.steps[0].flags)
    assert len(p.calls) == 1 and p.calls[0]["video_url"].endswith(f"#t={clip_start},298")
    assert "Create the Skeleton node" in p.calls[0]["prompt"] and "Add a Merge node" in p.calls[0]["prompt"]       # it is told what comes before and after
    assert any("2 step(s) added" in w for w in out.warnings)


def test_nothing_happening_in_the_stretch_is_an_answer_not_an_error():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Add a Merge node", "04:55", "05:10"))
    p = ScriptedProvider([{"steps": []}])
    out = fill_gaps(p, sl, "AAAAAAAAAAA", app="houdini", prompt_version="v13", duration_s=400)
    assert len(out.steps) == 2 and len(p.calls) == 1                  # accepted at once: no second paid attempt
    assert any("nothing performed there" in w for w in out.warnings)


def test_a_failed_second_look_keeps_the_first_pass():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Add a Merge node", "04:55", "05:10"))
    out = fill_gaps(ScriptedProvider([RuntimeError("quota")]), sl, "AAAAAAAAAAA", app="houdini", prompt_version="v13", duration_s=400)
    assert [s.goal for s in out.steps] == ["Create the Skeleton node", "Add a Merge node"] and any("could not be made" in w for w in out.warnings)


def test_a_step_that_repeats_one_already_there_is_dropped():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Add a Merge node", "04:55", "05:10"))
    clip = {"steps": [_raw("Create the Skeleton node", "00:01", "00:03"), _raw("Press F to enter Modify mode", "01:00", "01:02")]}
    out = fill_gaps(ScriptedProvider([clip]), sl, "AAAAAAAAAAA", app="houdini", prompt_version="v13", duration_s=400)
    assert [s.goal for s in out.steps] == ["Create the Skeleton node", "Press F to enter Modify mode", "Add a Merge node"]


def test_no_gap_no_call():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Pack it", "00:35", "00:50"))
    p = ScriptedProvider([])
    assert fill_gaps(p, sl, "AAAAAAAAAAA", app="houdini", prompt_version="v13", duration_s=400) is sl and p.calls == []


def test_earlier_steps_keep_pointing_at_the_right_step_after_renumbering():
    sl = _first_pass(_raw("Create the Skeleton node", "00:10", "00:30"), _raw("Add a Merge node", "04:55", "05:10"))
    sl.steps[1].depends_on = ["s01"]
    out = fill_gaps(ScriptedProvider([{"steps": [_raw("Press F to enter Modify mode", "00:05", "00:07")]}]), sl, "AAAAAAAAAAA", app="houdini", prompt_version="v13", duration_s=400)
    merge = next(s for s in out.steps if s.goal == "Add a Merge node")
    assert merge.id == "s03" and merge.depends_on == ["s01"]
    assert isinstance(out, StepList) and all(isinstance(s, Step) for s in out.steps)


# ---- parameter labels checked against Houdini's own list (knowledge/app_vocab/houdini.json, Houdini 22.0.466)
from ingestion import houdini_parms as hp  # noqa: E402
from shared.step_record import HowTo  # noqa: E402

needs_vocab = pytest.mark.skipif(not hp.version(), reason="knowledge/app_vocab/houdini.json is missing")


def _h(goal, *lines):
    return Step(id="s01", order=1, goal=goal, how_to=[HowTo(text=t, support="shown", evidence="x") for t in lines])


@needs_vocab
def test_a_label_the_node_does_not_have_is_reported_and_the_real_one_is_not():
    bad = _h("Configure control shapes", "In configurecontrols1 parameters, set Target Pattern to 'jnt_*'.")      # every v13 run of the APEX FK tutorial wrote this
    assert [lab for lab, _ in hp.unknown_labels(bad)] == ["Target Pattern"] and hp.label_of(hp.unknown_labels(bad)[0][1][0]) == "APEX Configure Controls"
    assert hp.unknown_labels(_h("Configure control shapes", "In configurecontrols1 parameters, set Control Group to 'jnt_*'.")) == []


@needs_vocab
def test_short_labels_and_numbered_repeats_are_accepted():
    assert hp.unknown_labels(_h("Set the control shape on APEX Configure Controls", "Set Shape to box.")) == []                    # the start of "Shape Override"
    assert hp.unknown_labels(_h("Pack the skeleton with Pack Folder", "Set Use Input 2 to on.")) == []                              # "Use Input #"


@needs_vocab
def test_nodes_the_list_cannot_judge_are_never_judged():
    assert hp.unknown_labels(_h("Rename the joints with an Attribute Wrangle after the Skeleton", "Set Run Over to Points.")) == []           # Attribute Wrangle is not in the list
    assert hp.unknown_labels(_h("Set up FK on the APEX AutoRig Component", "Set Promote Transforms to point*.")) == []                        # its parameters come from the chosen component
    assert hp.unknown_labels(_h("Draw the chain", "Click three times in the viewport.")) == []                                                 # no node named, nothing to check


@needs_vocab
def test_the_validator_flags_it_for_houdini_only():
    from ingestion.profiles import get_profile
    from ingestion.validate import sanitize_and_annotate
    raw = _raw("Configure control shapes on APEX Configure Controls", "00:10", "00:20", how_to=[{"text": "Set Target Pattern to point*.", "support": "shown", "evidence": "x"}])
    hou = extract_from_video(ScriptedProvider([{"steps": [raw]}]), "AAAAAAAAAAA", app="houdini", duration_s=400, prompt_version="v13")
    assert any("'Target Pattern' is not a parameter of APEX Configure Controls in Houdini 22.0" in f for f in hou.steps[0].flags)
    maya = extract_from_video(ScriptedProvider([{"steps": [raw]}]), "AAAAAAAAAAA", app="maya", duration_s=400, prompt_version="v13")
    assert not any("is not a parameter of" in f for f in maya.steps[0].flags)
    assert sanitize_and_annotate is not None and get_profile("houdini").name == "houdini"
