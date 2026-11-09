"""Outline hints (ingestion/outline_check.py): the knowledge base's typical order of operations used AFTER extraction, as questions for a reviewer. Uses the real Maya IK handle outline."""
from ingestion.outline_check import outline_hints
from shared.step_record import Step, StepList


def _sl(*goals, app="maya"):
    return StepList(source_type="youtube", app=app, steps=[Step(id=f"s{i:02d}", order=i, goal=g) for i, g in enumerate(goals, 1)])


CHOOSE = "Choose the IK Handle tool from Skeleton, Create IK Handle"
CLICK = "Click the start joint, the hip, then the end joint, the ankle"
MOVE = "Move the handle to check that the limb bends to follow it"


def test_a_missing_outline_step_is_a_hint_not_a_change():
    sl = _sl(CHOOSE, CLICK)
    hints = outline_hints(sl)
    assert [h.kind for h in hints] == ["missing"] and "Move the handle" in hints[0].detail and hints[0].after_step == "s02"
    assert [s.goal for s in sl.steps] == [CHOOSE, CLICK]                        # the step list is untouched


def test_a_complete_sequence_gives_no_hint():
    assert outline_hints(_sl(CHOOSE, CLICK, MOVE)) == []


def test_steps_in_the_wrong_order_are_an_order_hint():
    hints = outline_hints(_sl(CLICK, CHOOSE, MOVE))
    assert [h.kind for h in hints] == ["order"] and "usually done before" in hints[0].detail


def test_an_unrelated_tutorial_is_not_asked_about_a_topic_it_does_not_cover():
    assert outline_hints(_sl("Add a cube", "Scale the cube", "Press Tab")) == []
    assert outline_hints(_sl(CHOOSE, CLICK, app="blender")) == []               # the Maya outline is not applied to a Blender tutorial
