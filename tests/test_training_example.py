import pytest
from pydantic import ValidationError

from ingestion.training.example import Check, TrainingExample
from ingestion.training.split import find_leaks, split_examples


def ex(i, group, **kw):
    base = dict(example_id=f"e{i}", task="question_to_route", input_origin="synthetic", label_origin="human",
                review="human_verified", reviewer="r", group_key=group, input_text=f"q{i}", target_label="catalog")
    base.update(kw)
    return TrainingExample(**base)


def test_teacher_label_is_never_eval_truth_even_with_passing_checks():
    e = ex(1, "g", label_origin="teacher_model", teacher_model="m", review="none",
           checks=[Check(name="schema", passed=True)])
    assert not e.eval_eligible


def test_human_label_requires_verification_record():
    with pytest.raises(ValidationError):
        ex(1, "g", review="none")
    with pytest.raises(ValidationError):
        ex(1, "g", reviewer=None)


def test_blender_executed_needs_passing_postcondition():
    with pytest.raises(ValidationError):
        ex(1, "g", label_origin="blender_executed", review="none")
    ok = ex(1, "g", label_origin="blender_executed", review="none",
            checks=[Check(name="blender_postcondition", passed=True)])
    assert ok.eval_eligible
    real = ex(2, "g", input_origin="real", label_origin="blender_executed", review="none",
              checks=[Check(name="blender_postcondition", passed=True)])
    assert not real.eval_eligible  # real tutorial fidelity needs a person


def test_missing_target_and_clarification_rules():
    with pytest.raises(ValidationError):
        ex(1, "g", target_label=None)
    with pytest.raises(ValidationError):
        ex(1, "g", target_label=None, clarification_required=True)
    assert ex(1, "g", target_label=None, clarification_required=True, clarification_question="Which?")


def test_split_keeps_each_group_in_one_split_and_drops_ineligible_eval():
    items = [ex(i, f"vid{i % 20}") for i in range(200)]
    items += [ex(1000 + i, f"vid{i % 20}", label_origin="teacher_model", teacher_model="m", review="none")
              for i in range(100)]
    s = split_examples(items)
    assert find_leaks(s) == []
    assert all(e.eval_eligible for e in s["dev"] + s["test"])
    assert s["train"] and s["test"]
    assert split_examples(items) == s  # deterministic


def test_leak_audit_detects_group_and_text_overlap():
    a, b = ex(1, "same", input_text="Same text"), ex(2, "same", input_text="other")
    c = ex(3, "diff", input_text="same text ")
    leaks = find_leaks({"train": [a], "test": [b, c]})
    assert any("group 'same'" in p for p in leaks)
    assert any("identical input" in p for p in leaks)
