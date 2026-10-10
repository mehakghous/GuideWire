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
