import json
from pathlib import Path

from app.step_loader import NOT_CHECKABLE_FLAG, load_steps
from ingestion.evaluator import evaluate_step
from shared.step_record import StepList

EXAMPLE = Path("shared/examples/blender_cube_extrude.json")


def _data():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_known_files_load_unchanged():
    d = _data()
    assert load_steps(d).model_dump(mode="json") == StepList.model_validate(d).model_dump(mode="json")


def test_unknown_kind_does_not_fail_and_step_is_not_checkable():
    d = _data()
    d["steps"][0]["expected_state"].append({"kind": "future_kind", "target": "joint", "value": 9})
    sl = load_steps(d)
    s = sl.steps[0]
    assert not s.verifiable
    assert NOT_CHECKABLE_FLAG in s.flags
    assert evaluate_step(s, {"mode": "OBJECT"}).status == "unverifiable"


def test_other_steps_are_untouched():
    d = _data()
    before = load_steps(_data())
    d["steps"][0]["expected_state"].append({"kind": "future_kind_b", "target": "x"})
    after = load_steps(d)
    assert [s.model_dump() for s in after.steps[1:]] == [s.model_dump() for s in before.steps[1:]]


def test_input_is_not_mutated():
    d = _data()
    d["steps"][0]["expected_state"].append({"kind": "future_kind_c", "target": "a.b"})
    snap = json.dumps(d, sort_keys=True)
    load_steps(d)
    assert json.dumps(d, sort_keys=True) == snap
