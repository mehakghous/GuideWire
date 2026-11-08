import pytest

from app.step_editor import EditError, StepEditor
from app.step_validation import MULTI_FLAG, UNRECOGNISED_FLAG, TextRefused, analyse, check_text

SAMPLE = "shared/examples/blender_cube_extrude.json"


@pytest.mark.parametrize("text", ["ss", "ok", "...", "123 456 789", "asdf", "", "   ", "x" * 301])
def test_junk_is_refused(text):
    with pytest.raises(TextRefused):
        check_text(text)


@pytest.mark.parametrize("text", ["Undo", "Press Tab to enter Edit Mode", "Add a cube", "  Rotate   the cube  "])
def test_real_steps_are_accepted_and_whitespace_is_cleaned(text):
    assert check_text(text) == " ".join(text.split())


def test_nonsense_with_two_words_is_accepted_but_not_recognised():
    assert check_text("asdf qwer") == "asdf qwer"
    a = analyse("asdf qwer")
    assert not a.recognised and a.flags == [UNRECOGNISED_FLAG]


def test_duplicates_are_refused_ignoring_case_and_punctuation():
    with pytest.raises(TextRefused, match="already in the list"):
        check_text("add a CUBE.", ["Add a cube"])


def test_recognised_instruction_carries_its_expected_state():
    a = analyse("Press Tab to enter Edit Mode")
    assert a.recognised and [(p.kind, p.target) for p in a.step.expected_state] == [("mode", "EDIT_MESH")]


def test_several_instructions_in_one_step_are_flagged():
    assert MULTI_FLAG in analyse("Move the cube and then rotate it").flags


def test_other_applications_are_manual_without_a_recognition_check():
    a = analyse("Press Tab to enter Edit Mode", "maya")
    assert not a.recognised and "only exists for Blender" in a.flags[0]


def test_editor_adds_a_recognised_step_with_its_checks():
    ed = StepEditor.from_json_file(SAMPLE)
    sid = ed.add("Press Tab to enter Edit Mode")
    step = ed.steps.steps[-1]
    assert step.id == sid and step.verifiable and step.expected_state and step.provenance == "user_text" and step.review_status == "reviewed"
    assert step.goal == "Press Tab to enter Edit Mode"


def test_editor_adds_an_unrecognised_step_as_manual_with_a_flag():
    ed = StepEditor.from_json_file(SAMPLE)
    ed.add("Save the file")
    step = ed.steps.steps[-1]
    assert not step.verifiable and UNRECOGNISED_FLAG in step.flags


def test_editor_refuses_junk_and_changes_nothing():
    ed = StepEditor.from_json_file(SAMPLE)
    with pytest.raises(EditError, match="too short"):
        ed.add("ss")
    with pytest.raises(EditError, match="already in the list"):
        ed.add("Enter Edit Mode")
    with pytest.raises(EditError):
        ed.edit_goal("s01", "ok")
    assert len(ed) == 4 and not ed.dirty
