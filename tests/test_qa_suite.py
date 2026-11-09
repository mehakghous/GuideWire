"""The realistic question suite: well formed, tied to saved fixtures, and the replies that were correct on 2026-11-09 stay correct. Offline, no model."""
import json
from pathlib import Path

import pytest

from ingestion.eval import qa_suite

FIX = Path(__file__).parent / "fixtures" / "qa_suite"
SUITE = json.loads((FIX / "questions.json").read_text(encoding="utf-8"))["questions"]
GRADES = json.loads((FIX / "grades_2026-11-09.json").read_text(encoding="utf-8"))["grades"]


def test_suite_is_well_formed():
    ids = [q["id"] for q in SUITE]
    assert len(ids) == len(set(ids)) == 48 and set(GRADES) == set(ids)
    for q in SUITE:
        assert q["behaviour"] in qa_suite.ACCEPTED and q["scenario"] in ("no_video", "video_context") and q["reference"] and q["question"].strip()
        assert q["app"] in ("blender", "maya", "houdini")
        if q["scenario"] == "video_context":
            assert (FIX / f"steps_{q['video']}.json").exists()
    assert {g["g"] for g in GRADES.values()} <= {"C", "P", "N", "W"}
    for app in ("blender", "maya", "houdini"):
        assert sum(q["app"] == app for q in SUITE) == 16
    assert sum(q["scenario"] == "no_video" for q in SUITE) == 30


@pytest.fixture(scope="module")
def rows():
    return {r["id"]: r for r in qa_suite.run()}


def test_replies_graded_correct_still_pass(rows):
    for qid, g in GRADES.items():
        if g["g"] == "C":
            assert rows[qid]["auto_pass"], (qid, rows[qid]["reply"][:200])


def test_no_reply_contains_a_forbidden_claim(rows):
    assert all(r["checks"]["must_not_ok"] for r in rows.values())


def test_summary_counts_add_up(rows):
    s = qa_suite.summary(list(rows.values()))
    assert s["all"]["questions"] == 48 and s["all"]["answered"] + s["all"]["clarified"] + s["all"]["declined"] == 48


def test_the_beginner_suite_is_well_formed():
    import collections
    d = json.loads((FIX / "questions_beginner.json").read_text(encoding="utf-8"))["questions"]
    ids = [q["id"] for q in d]
    assert len(d) == 36 and len(set(ids)) == 36
    assert collections.Counter(q["app"] for q in d) == {"blender": 12, "maya": 12, "houdini": 12}
    assert all(q["scenario"] == "no_video" and q["reference"] and q["behaviour"] in ("answer", "answer_or_admit", "clarify_or_admit", "admit") for q in d)
    grades = json.loads((FIX / "grades_beginner_2026-11-09.json").read_text(encoding="utf-8"))["grades"]
    assert set(grades) == set(ids) and set(grades.values()) <= {"C", "P", "N", "W"}
