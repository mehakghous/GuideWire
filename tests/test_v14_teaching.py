"""Prompt v14 (2026-11-24): steps that keep the try-see-fix thread, a why that says what is on screen, directions and conditions, Windows key names. v12 and v13 are unchanged."""
from __future__ import annotations

from ingestion import extract
from ingestion.instructions import windows_keys
from ingestion.profiles import get_profile
from shared.step_record import Action, HowTo, Step, StepList


def _prompt(version):
    return extract.build_system_prompt(get_profile("blender"), version)


def _prompt_for(app, version="v14"):
    return extract.build_system_prompt(get_profile(app), version)


def test_v14_adds_the_teaching_rules_and_v12_and_v13_do_not_have_them():
    v14 = _prompt("v14")
    for rule in ("TRY, SEE, FIX", "one to three short plain sentences", "Write directions the way the learner sees them", "never add the Mac or other-system alternative", "A deliberate try that shows a problem"):
        assert rule in v14
        assert rule not in _prompt("v12") and rule not in _prompt("v13")


def test_v14_does_not_forbid_the_demonstrations_v12_dropped():
    v12, v14 = _prompt("v12"), _prompt("v14")
    assert "looking at or checking something" in v12 and "looking at or checking something" not in v14
    assert "Do not write steps for the mistake or the undo" in v12 and "Do not write steps for the mistake or the undo" not in v14
    assert "ONE sentence" not in v14 and "why: the purpose in one sentence" not in v14


def test_every_application_uses_v14_for_videos():
    """2026-11-24: three runs on each of the six labelled videos; Maya and Houdini found more of the labelled actions by their words (about +9 and +8 points) with the same or better step support."""
    for app in ("blender", "maya", "houdini"):
        assert extract.recommended_video_prompt_version(app) == "v14"


def test_the_v14_rules_are_generic_no_name_from_one_tutorial_is_in_the_prompt():
    """Every rule must help other tutorials: the prompt may not carry the names of the leg IK video's bones or controls."""
    for app in ("blender", "maya", "houdini"):
        v14 = _prompt_for(app)
        added = v14[len(_prompt_for(app, "v12" if app != "houdini" else "v13")) - 1500:]
        for word in ("toe bone", "knee controller", "ankle controller", "pole target bone", "PctSMB"):
            assert word not in added


def test_a_setting_that_takes_two_choices_is_written_as_two_lines_in_every_application():
    for app in ("blender", "maya", "houdini"):
        assert "SETTINGS THAT TAKE TWO CHOICES" in _prompt_for(app) and "SETTINGS THAT TAKE TWO CHOICES" not in _prompt_for(app, "v12")


def test_a_mac_tutorials_command_and_option_become_ctrl_and_alt_and_the_mac_aside_is_dropped():
    st = Step(id="s01", order=1, goal="Clear the parent (or Option+P on a Mac)", actions=[Action(verb="press_keys", keys=["Option", "P"]), Action(verb="press_keys", keys=["Command", "Z"])],
              how_to=[HowTo(text="Press Alt+P (or Option+P) and select Clear Parent.", support="shown"), HowTo(text="Press Command+Z to undo.", support="shown")])
    sl = StepList(source_type="youtube", app="blender", steps=[st])
    assert windows_keys(sl) >= 3
    got = sl.steps[0]
    assert [a.keys for a in got.actions] == [["Alt", "P"], ["Ctrl", "Z"]]
    assert got.how_to[0].text == "Press Alt+P and select Clear Parent." and got.how_to[1].text == "Press Ctrl+Z to undo."
    assert got.goal == "Clear the parent"


def test_a_body_part_the_model_picked_when_the_instructor_only_points_is_flagged_for_review():
    """2026-11-24, learner report: "Parent the toe bone" where the video says "do the same thing with this bone" and the bone is the knee controller. The model's own line evidence said "Toe bone selected"."""
    from ingestion.validate import inferred_names
    st = Step(id="s29", order=29, goal="Parent the toe bone to the ankle IK controller bone with Keep Offset", video_start_s=271.0, video_end_s=278.0,
              how_to=[HowTo(text="Select the toe bone.", support="shown", evidence="Toe bone selected")],
              evidence=["We can do the same thing with this bone, press shift, select this bone, Command P, parent, keep offset."], visual_evidence="Keep Offset selected in the Make Parent menu.")
    assert "toe" in inferred_names(st)
    named = st.model_copy(update={"evidence": ["Now the toe bone: select this bone, Ctrl P"]})
    assert "toe" not in inferred_names(named)                       # the instructor said it
    plain = st.model_copy(update={"evidence": ["select the foot bone and press Ctrl P"], "goal": "Parent the foot bone", "how_to": [HowTo(text="Select the foot bone.", support="said", evidence="select the foot bone")]})
    assert inferred_names(plain) == []                              # nothing only points


def _repeat_list():
    prev = Step(id="s20", order=20, goal="Reparent the foot bone to the foot IK controller", how_to=[HowTo(text="Select the foot bone.", support="shown", evidence="foot selected")], video_start_s=261.0, video_end_s=270.0)
    st = Step(id="s21", order=21, goal="Reparent the toe bone to the foot IK controller", video_start_s=271.0, video_end_s=278.0,
              how_to=[HowTo(text="Select the toe bone (Bone.004).", support="shown", evidence="Toe bone selected"), HowTo(text="Hold Shift, select the foot IK controller bone.", support="shown", evidence="Shift held"),
                      HowTo(text="Press Ctrl+P and choose Keep Offset.", support="shown", evidence="menu")],
              check=[HowTo(text="Verify both foot and toe bones are parented to the IK controller.", support="shown")], why="To ensure the toes move with the foot.",
              actions=[Action(verb="select", ui_element="Toe Bone"), Action(verb="select", ui_element="Foot IK Controller Bone")],
              evidence=["We can do the same thing with this bone, press shift, select this bone, Command P, parent, keep offset."], visual_evidence="Keep Offset selected in the Make Parent menu.")
    return StepList(source_type="youtube", app="blender", steps=[prev, st])


def test_do_the_same_thing_with_this_bone_becomes_the_other_bone_of_the_same_kind_not_an_invented_name():
    """2026-11-24: the video (4:31) parents the OTHER controller, the knee controller; the step said "toe bone". A second look at the clip by the model was tried and also answered "toe" (and "part of the leg
    chain"), so the step says what the instructor said: the same operation on the other bone."""
    from ingestion.identify import resolve_repeats
    sl = _repeat_list()
    assert resolve_repeats(sl) == ["s21"]
    got = sl.steps[1]
    assert got.goal == "Reparent the other bone to the foot IK controller" or got.goal == "Reparent the other controller bone to the foot IK controller"
    assert got.how_to[0].text.startswith("Select the other") and "toe" not in got.how_to[0].text.lower() and "Bone.004" not in got.how_to[0].text
    assert got.how_to[1].text == "Hold Shift, select the foot IK controller bone."          # the bone it is parented to is left as written
    assert "toe" not in " ".join([got.goal, got.why or "", *(h.text for h in got.check)]).lower() and got.actions[0].ui_element.lower().startswith("other")
    assert any("do the same thing with this bone" in f and "check which bone it is in the video" in f for f in got.flags)


def test_a_step_that_names_a_bone_the_instructor_said_is_left_alone_by_the_repeat_rewrite():
    from ingestion.identify import resolve_repeats
    sl = _repeat_list()
    sl.steps[1].evidence = ["Now do the same thing with the toe bone: select it, Ctrl P, Keep Offset."]
    before = sl.steps[1].model_dump()
    assert resolve_repeats(sl) == [] and sl.steps[1].model_dump() == before
