import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.step_record import Step, StatePredicate, StepList

EXAMPLES = sorted((Path(__file__).parent.parent / "shared" / "examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_validate(path):
    sl = StepList.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert sl.steps and [s.order for s in sl.steps] == list(range(1, len(sl.steps) + 1))


def test_examples_exist():
    assert len(EXAMPLES) >= 3


def test_verifiable_is_derived():
    s = Step(id="a", order=1, goal="g", verifiable=True)
    assert s.verifiable is False
    s2 = Step(id="a", order=1, goal="g", expected_state=[StatePredicate(kind="mode", target="OBJECT")])
    assert s2.verifiable is True


def test_value_only_for_property_equals():
    with pytest.raises(ValidationError):
        StatePredicate(kind="mode", target="OBJECT", value="x")
    with pytest.raises(ValidationError):
        StatePredicate(kind="property_equals", target="a.b")


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        Step(id="a", order=1, goal="g", video_start_s=10, video_end_s=5)


def test_unknown_predicate_kind_rejected():
    with pytest.raises(ValidationError):
        StatePredicate(kind="vibes", target="x")


def _steps(*orders):
    return [Step(id=f"s{o}", order=o, goal="g") for o in orders]


<<<<<<< HEAD
def test_app_is_one_of_the_three_supported():
    for app in ("blender", "maya", "houdini"):
        StepList(source_type="written", app=app, steps=_steps(1))
=======
def test_app_is_blender_only():
>>>>>>> 73f5ac8 (StepList: restrict app to blender; add opt-in check_order for editors)
    with pytest.raises(ValidationError):
        StepList(source_type="written", app="unity", steps=_steps(1))


<<<<<<< HEAD
def test_craft_step_is_never_verifiable():
    p = StatePredicate(kind="mode", target="OBJECT")
    assert Step(id="a", order=1, goal="g", expected_state=[p]).verifiable
    assert not Step(id="a", order=1, goal="g", expected_state=[p], kind="craft").verifiable


=======
>>>>>>> 73f5ac8 (StepList: restrict app to blender; add opt-in check_order for editors)
@pytest.mark.parametrize("orders", [(1, 3), (2, 3), (1, 1), (2, 1)])
def test_check_order_flags_gaps_repeats_and_misordering(orders):
    sl = StepList(source_type="written", app="blender", steps=_steps(*orders))  # construction stays lenient
    assert sl.order_problems
    with pytest.raises(ValueError):
        sl.check_order()


def test_check_order_accepts_contiguous():
    sl = StepList(source_type="written", app="blender", steps=_steps(1, 2, 3))
    assert sl.order_problems == []
    sl.check_order()
