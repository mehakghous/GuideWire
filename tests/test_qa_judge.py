"""The independent grader (ingestion/eval/qa_judge.py), with a scripted provider: no network."""
from ingestion.eval.qa_judge import SCHEMA, compare, judge_all, judge_row, useful_rate
from ingestion.providers.fake import ScriptedProvider

ROW = {"id": "nb01", "app": "blender", "question": "how do i start rigging", "expected_behaviour": "answer", "reference": "Add an armature, build bones, parent with automatic weights.", "reply": "Add an armature."}


def test_the_grader_sends_question_reference_and_reply_and_returns_a_grade():
    p = ScriptedProvider([{"grade": "P", "reason": "misses parenting"}])
    out = judge_row(p, ROW)
    assert out == {"grade": "P", "reason": "misses parenting"} and p.calls[0]["video_url"] is None
    prompt = p.calls[0]["prompt"]
    assert "REFERENCE: Add an armature, build bones" in prompt and "REPLY:\nAdd an armature." in prompt and "how do i start rigging" in prompt
    assert set(SCHEMA["properties"]["grade"]["enum"]) == set("CPNW")


def test_an_unknown_grade_is_marked_not_guessed():
    assert judge_row(ScriptedProvider([{"grade": "A+", "reason": "x"}]), ROW)["grade"] == "?"


def test_agreement_stricter_and_more_lenient_are_counted_and_the_disagreements_listed():
    judged = {"a": {"grade": "C", "reason": "r1"}, "b": {"grade": "P", "reason": "r2"}, "c": {"grade": "C", "reason": "r3"}, "d": {"grade": "W", "reason": "r4"}}
    human = {"a": "C", "b": "C", "c": "P", "d": "P", "zz": "C"}
    r = compare(judged, human)
    assert r["questions"] == 4 and r["agree"] == 1 and r["agreement"] == 0.25
    assert r["judge_stricter"] == ["b", "d"] and r["judge_more_lenient"] == ["c"] and set(r["disagreements"]) == {"b", "c", "d"}
    assert r["disagreements"]["b"] == {"first_grader": "C", "judge": "P", "why": "r2"}


def test_useful_rate_counts_c_plus_half_p():
    assert useful_rate({"a": "C", "b": "P", "c": "N", "d": "W"}) == 0.375 and useful_rate({}) is None


def test_judge_all_grades_every_row():
    rows = [{**ROW, "id": "x1"}, {**ROW, "id": "x2"}]
    out = judge_all(ScriptedProvider([{"grade": "C", "reason": "a"}, {"grade": "N", "reason": "b"}]), rows)
    assert {k: v["grade"] for k, v in out.items()} == {"x1": "C", "x2": "N"}
