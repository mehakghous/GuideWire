"""A review sheet for a PERSON to grade the question suite's replies (plan item B4, step 4), and the comparison once it is filled in.

    python scripts/review_sheet.py make  runs/qa/results.json runs/qa/judged.json -o eval_data/review/beginner_review.csv
    python scripts/review_sheet.py check eval_data/review/beginner_review.csv [--grades tests/fixtures/qa_suite/grades_beginner_2026-11-09.json]

`make` writes one row per question with the question, the reference answer, the reply and the model grader's grade and reason, and EMPTY columns `human_grade` and `human_note`. Fill `human_grade`
with C, P, N or W (C correct and useful, P partly, N no answer, W wrong or misleading) WITHOUT looking at the grader's column first if you can (it is the last columns for that reason).
`check` reads the filled sheet and reports how often the person agrees with the model grader (and with the first grader, when a grades file is given), and lists the disagreements.
The first grader's grades were written for EARLIER replies, so they are only compared where the reply did not change.
Open the CSV in Excel or Google Sheets (UTF-8).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

COLS = ["id", "app", "question", "expected_behaviour", "reference", "reply", "human_grade", "human_note", "model_grader_grade", "model_grader_reason"]


def make(results: Path, judged: Path, out: Path) -> int:
    rows = json.loads(results.read_text(encoding="utf-8"))["rows"]
    j = json.loads(judged.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({"id": r["id"], "app": r["app"], "question": r["question"], "expected_behaviour": r.get("expected_behaviour", ""), "reference": r.get("reference", ""),
                        "reply": r.get("reply", ""), "human_grade": "", "human_note": "", "model_grader_grade": j["judge_grades"].get(r["id"], ""), "model_grader_reason": j["reasons"].get(r["id"], "")})
    print(f"wrote {len(rows)} rows to {out}: fill human_grade (C, P, N or W) for each")
    return 0


def check(sheet: Path, grades: Path | None = None) -> dict:
    with sheet.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    done = [r for r in rows if (r.get("human_grade") or "").strip().upper() in ("C", "P", "N", "W")]
    res: dict = {"rows": len(rows), "graded_by_person": len(done)}
    if not done:
        return res
    h = {r["id"]: r["human_grade"].strip().upper() for r in done}
    m = {r["id"]: r["model_grader_grade"] for r in done}
    same = [i for i in h if h[i] == m[i]]
    res["person_vs_model_grader"] = {"agree": len(same), "of": len(h), "agreement": round(len(same) / len(h), 3), "disagreements": {i: {"person": h[i], "model_grader": m[i]} for i in h if h[i] != m[i]}}
    c = Counter(h.values())
    res["person_useful_rate"] = round((c["C"] + c["P"] / 2) / len(h), 3)
    c2 = Counter(m[i] for i in h)
    res["model_grader_useful_rate_on_same_questions"] = round((c2["C"] + c2["P"] / 2) / len(h), 3)
    if grades:
        first = json.loads(grades.read_text(encoding="utf-8"))["grades"]
        both = [i for i in h if i in first]
        res["person_vs_first_grader"] = {"agree": sum(1 for i in both if h[i] == first[i]), "of": len(both), "note": "the first grader graded earlier replies; unchanged replies only match"}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("make")
    a.add_argument("results", type=Path)
    a.add_argument("judged", type=Path)
    a.add_argument("-o", "--out", type=Path, required=True)
    b = sub.add_parser("check")
    b.add_argument("sheet", type=Path)
    b.add_argument("--grades", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "make":
        return make(args.results, args.judged, args.out)
    print(json.dumps(check(args.sheet, args.grades), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
