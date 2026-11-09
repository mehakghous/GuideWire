"""An independent grader for the question suite's replies (plan item B4).

The suites' replies were graded by one reader who also wrote the reference answers, so the numbers could not be called independent. This asks a DIFFERENT model family (OpenAI, by default
the stronger `gpt-5.6-terra`) to grade each reply against the reference, with the same four grades, and reports how often it agrees with the existing grades:

    python -m ingestion.eval.qa_judge runs/qa/results.json --grades tests/fixtures/qa_suite/grades_beginner_2026-11-09.json [-o runs/qa/judged.json]

C = correct and useful, P = partly right or missing something the learner needs, N = no answer (asks a question, declines, deflects), W = wrong, misleading or inventing. A model grader is NOT a
person: it is a second opinion, and where it disagrees with the first grader the pair is listed for a person to settle. Text only; every call goes through the cost guard.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SYSTEM = """You grade ONE reply from a tutoring assistant for beginners learning character rigging in Blender, Maya or Houdini.
You are given the learner's question, the behaviour expected, a REFERENCE answer (what a correct answer says, written from the application's documentation) and the assistant's REPLY.
Grades:
  C = correct and useful: it answers the question, the menu paths, tool names and order match the reference or the application's real behaviour, and a beginner could act on it.
  P = partly right: correct as far as it goes but it misses a step or detail the learner needs, is too vague to act on, answers a neighbouring question, or gives a plausible detail you cannot confirm.
  N = no answer: it asks a question back, declines, or deflects instead of answering. (When the expected behaviour allows an honest "not covered", an honest admission is C, not N.)
  W = wrong or misleading: it states something false, names a menu or node that does not exist, gives steps that would not work, or claims the tutorial said something it cannot know.
Judge the reply on its content. Be strict about invented names and wrong steps; do not reward length. Give a one-sentence reason.
Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {"grade": {"type": "string", "enum": ["C", "P", "N", "W"]}, "reason": {"type": "string"}},
    "required": ["grade", "reason"],
}


def judge_row(provider, row: dict[str, Any]) -> dict[str, str]:
    prompt = (f"APPLICATION: {row['app']}\nQUESTION: {row['question']}\nEXPECTED BEHAVIOUR: {row.get('expected_behaviour', '')}\n"
              f"REFERENCE: {row.get('reference', '')}\nREPLY:\n{(row.get('reply') or '')[:8000]}")
    out = provider.generate_json(system=SYSTEM, prompt=prompt, schema=SCHEMA)
    g = str(out.get("grade", "")).strip().upper()
    return {"grade": g if g in "CPNW" and len(g) == 1 else "?", "reason": str(out.get("reason", ""))[:300]}


def judge_all(provider, rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {r["id"]: judge_row(provider, r) for r in rows}


def compare(judged: dict[str, dict[str, str]], human: dict[str, str]) -> dict[str, Any]:
    """Agreement of the model grader with the existing grades, over the questions both graded."""
    ids = [i for i in judged if i in human]
    same = [i for i in ids if judged[i]["grade"] == human[i]]
    rank = {"W": 0, "N": 1, "P": 2, "C": 3}
    return {"questions": len(ids), "agree": len(same), "agreement": round(len(same) / len(ids), 3) if ids else None,
            "judge_stricter": [i for i in ids if judged[i]["grade"] in rank and human[i] in rank and rank[judged[i]["grade"]] < rank[human[i]]],
            "judge_more_lenient": [i for i in ids if judged[i]["grade"] in rank and human[i] in rank and rank[judged[i]["grade"]] > rank[human[i]]],
            "disagreements": {i: {"first_grader": human[i], "judge": judged[i]["grade"], "why": judged[i]["reason"]} for i in ids if i not in same}}


def useful_rate(grades: dict[str, str]) -> float | None:
    c = Counter(grades.values())
    n = sum(c[k] for k in "CPNW")
    return round((c["C"] + c["P"] / 2) / n, 3) if n else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ingestion.eval.qa_judge")
    ap.add_argument("results", type=Path, help="a results file written by ingestion.eval.qa_suite -o")
    ap.add_argument("--grades", type=Path, help="the first grader's grades file (id -> C/P/N/W under 'grades') to compare with")
    ap.add_argument("--openai-model", default=None, help="default: the strong OpenAI model (gpt-5.6-terra)")
    ap.add_argument("--max-usd", type=float, default=1.0, help="stop before a call that could pass this many dollars in this run")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    from ..budget import BudgetedProvider, Ceilings
    from ..providers.openai_provider import STRONG_MODEL, OpenAIProvider
    prov = BudgetedProvider(OpenAIProvider(model=a.openai_model or STRONG_MODEL), ceilings=Ceilings.from_env(max_usd_run=a.max_usd), label="openai")
    rows = json.loads(a.results.read_text(encoding="utf-8"))["rows"]
    judged = judge_all(prov, rows)
    res: dict[str, Any] = {"model": prov.model_id, "judge_grades": {i: j["grade"] for i, j in judged.items()}, "judge_useful_rate": useful_rate({i: j["grade"] for i, j in judged.items()}),
                           "counts": dict(Counter(j["grade"] for j in judged.values())), "reasons": {i: j["reason"] for i, j in judged.items()}}
    if a.grades:
        human = json.loads(a.grades.read_text(encoding="utf-8"))["grades"]
        res["against_first_grader"] = compare(judged, human)
        res["first_grader_useful_rate"] = useful_rate({i: human[i] for i in judged if i in human})
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("reasons", "judge_grades")}, indent=1)[:3500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
