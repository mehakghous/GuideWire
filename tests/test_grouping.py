"""Display groups (schema 0.12, ingestion/grouping.py): the contract helpers and the rules the model's grouping must obey. No model, no network."""
import pytest
from pydantic import ValidationError

from ingestion.grouping import MAX_GROUP_STEPS, apply_groups, check_groups, group_steps
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import Step, StepList


def _sl(n=6):
    steps = [Step(id=f"s{i:02d}", order=i, goal=f"do thing {i}", video_start_s=i * 5.0, video_end_s=i * 5.0 + 4) for i in range(1, n + 1)]
    return StepList(source_type="youtube", app="maya", video_id="vid", steps=steps, video_duration_s=100.0)


GOOD = {"groups": [{"label": "Create the leg joints", "step_ids": ["s01", "s02", "s03"]}, {"label": "Rename the joints", "step_ids": ["s04", "s05"]}, {"label": "Add the IK handle", "step_ids": ["s06"]}]}


def test_the_contract_fields_are_optional_and_validated():
    assert Step(id="s01", order=1, goal="x").group_id is None
    with pytest.raises(ValidationError):
        Step(id="s01", order=1, goal="x", group_id="3")                    # not like g03
    with pytest.raises(ValidationError):
        Step(id="s01", order=1, goal="x", group="")


def test_groups_walks_every_step_and_ungrouped_steps_are_their_own_group():
    sl = apply_groups(_sl(), [("A", ["s01", "s02"]), ("B", ["s03", "s04", "s05", "s06"])])
    assert [(gid, label, [s.id for s in steps]) for gid, label, steps in sl.groups] == [("g01", "A", ["s01", "s02"]), ("g02", "B", ["s03", "s04", "s05", "s06"])]
    assert sl.group_problems == []
    plain = _sl(2)
    assert [(gid, label, len(steps)) for gid, label, steps in plain.groups] == [("", "do thing 1", 1), ("", "do thing 2", 1)]


def test_group_problems_finds_a_split_group_two_labels_and_half_set_fields():
    sl = _sl(4)
    for s, (gid, label) in zip(sl.steps, [("g01", "A"), ("g02", "B"), ("g01", "A"), ("g03", None)]):
        s.group_id, s.group = gid, label
    text = " | ".join(sl.group_problems)
    assert "not one run of consecutive steps" in text and "must be set together" in text
    sl2 = _sl(2)
    sl2.steps[0].group_id, sl2.steps[0].group = "g01", "A"
    sl2.steps[1].group_id, sl2.steps[1].group = "g01", "B"
    assert "two labels" in " ".join(sl2.group_problems)


def test_a_valid_answer_groups_the_steps_and_leaves_them_unchanged():
    sl = _sl()
    p = ScriptedProvider([GOOD])
    out = group_steps(sl, p)
    assert [s.group_id for s in out.steps] == ["g01", "g01", "g01", "g02", "g02", "g03"] and out.group_problems == []
    assert [(s.id, s.goal, s.video_start_s) for s in out.steps] == [(s.id, s.goal, s.video_start_s) for s in sl.steps]       # nothing else touched
    assert sl.steps[0].group_id is None                                       # the input is not modified
    assert len(p.calls) == 1 and "s01 [00:05-00:09] do thing 1" in p.calls[0]["prompt"] and "video_url" in p.calls[0] and p.calls[0]["video_url"] is None
    assert "grouped for display into 3 groups" in out.warnings[-1]


@pytest.mark.parametrize("bad, fragment", [
    ({"groups": [{"label": "A", "step_ids": ["s01", "s02"]}]}, "missing"),                                                        # steps left out
    ({"groups": [{"label": "A", "step_ids": ["s01", "s02", "s03", "s04", "s05", "s06", "s06"]}]}, "repeated"),
    ({"groups": [{"label": "A", "step_ids": ["s02", "s01", "s03", "s04", "s05", "s06"]}]}, "order differs"),                     # reordered
    ({"groups": [{"label": "A", "step_ids": ["s01", "s02", "s03"]}, {"label": "B", "step_ids": ["s04", "s05", "s99"]}]}, "unknown step ids"),
    ({"groups": [{"label": "", "step_ids": ["s01", "s02", "s03", "s04", "s05", "s06"]}]}, "no label"),
    ({"groups": [{"label": "x" * 90, "step_ids": ["s01", "s02", "s03", "s04", "s05", "s06"]}]}, "too long"),
])
def test_rule_breaking_answers_are_found(bad, fragment):
    _, problems = check_groups(_sl(), bad)
    assert fragment in " ".join(problems)


def test_a_group_bigger_than_the_limit_is_refused():
    sl = _sl(MAX_GROUP_STEPS + 1)
    _, problems = check_groups(sl, {"groups": [{"label": "All", "step_ids": [s.id for s in sl.steps]}]})
    assert "the most allowed" in " ".join(problems)


def test_a_bad_first_answer_is_retried_with_the_problem_then_used():
    bad = {"groups": [{"label": "A", "step_ids": ["s01"]}]}
    p = ScriptedProvider([bad, GOOD])
    out = group_steps(_sl(), p)
    assert out.steps[0].group == "Create the leg joints" and len(p.calls) == 2
    assert "broke these rules" in p.calls[1]["prompt"] and "missing" in p.calls[1]["prompt"]


def test_two_bad_answers_leave_the_list_ungrouped_with_a_warning_not_a_guess():
    bad = {"groups": [{"label": "A", "step_ids": ["s01"]}]}
    out = group_steps(_sl(), ScriptedProvider([bad, bad]))
    assert all(s.group_id is None for s in out.steps) and "grouping skipped" in out.warnings[-1]


def test_a_provider_failure_keeps_the_steps_and_says_so():
    out = group_steps(_sl(), ScriptedProvider([RuntimeError("down")]))
    assert all(s.group_id is None for s in out.steps) and "grouping skipped: RuntimeError" in out.warnings[-1]
