"""The review sheet for a person (scripts/review_sheet.py): written without any grade of the person's, and compared once filled in."""
import csv
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("review_sheet", Path(__file__).resolve().parents[1] / "scripts" / "review_sheet.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)


def _inputs(tmp_path):
    results = tmp_path / "r.json"
    results.write_text(json.dumps({"rows": [{"id": "a1", "app": "maya", "question": "how do i bind", "reply": "Skin > Bind Skin", "reference": "ref a"},
                                            {"id": "a2", "app": "maya", "question": "what is ik", "reply": "Inverse kinematics", "reference": "ref b"}]}), encoding="utf-8")
    judged = tmp_path / "j.json"
    judged.write_text(json.dumps({"judge_grades": {"a1": "C", "a2": "P"}, "reasons": {"a1": "good", "a2": "thin"}}), encoding="utf-8")
    return results, judged


def test_the_sheet_has_empty_person_columns_and_the_model_graders_columns_last(tmp_path):
    results, judged = _inputs(tmp_path)
    out = tmp_path / "s.csv"
    assert rs.make(results, judged, out) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig", newline="")))
    assert [r["id"] for r in rows] == ["a1", "a2"] and all(r["human_grade"] == "" and r["human_note"] == "" for r in rows)
    assert rows[0]["model_grader_grade"] == "C" and rows[1]["model_grader_reason"] == "thin"
    assert rs.COLS.index("human_grade") < rs.COLS.index("model_grader_grade")


def test_an_unfilled_sheet_reports_nothing_graded_and_a_filled_one_reports_agreement(tmp_path):
    results, judged = _inputs(tmp_path)
    out = tmp_path / "s.csv"
    rs.make(results, judged, out)
    assert rs.check(out) == {"rows": 2, "graded_by_person": 0}
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig", newline="")))
    rows[0]["human_grade"], rows[1]["human_grade"] = "c", "C"                                               # lower case is accepted
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rs.COLS)
        w.writeheader()
        w.writerows(rows)
    res = rs.check(out)
    assert res["person_vs_model_grader"] == {"agree": 1, "of": 2, "agreement": 0.5, "disagreements": {"a2": {"person": "C", "model_grader": "P"}}}
    assert res["person_useful_rate"] == 1.0 and res["model_grader_useful_rate_on_same_questions"] == 0.75
