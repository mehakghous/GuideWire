"""Run the realistic question suite (tests/fixtures/qa_suite/questions.json) through the answering layer and sort every reply.

    python -m ingestion.eval.qa_suite [--suite FILE] [-o runs/qa/results.json]

Each question is asked through ingestion.service.Service, the same path a person reaches (router, knowledge base, rigging knowledge, follow-up resolution). Nothing is
mocked and no model is called: the answering layer is rule-based. A `video_context` question first loads the saved step list named in the suite.

Automated sorting only (it cannot judge truth): the reply is ANSWERED, CLARIFIED (a question back) or DECLINED (an honest "not available / needs a model"); an answered reply is
checked against the question's must_any / must_not words and, for follow-ups, against the step it should name. A person reads every answered reply for correctness.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from shared.step_record import StepList

from .. import session as S
from ..service import Service

SUITE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "qa_suite" / "questions.json"
FIXTURES = SUITE.parent
ADMITS = re.compile(r"not in the tutorial|isn'?t in the tutorial|not (?:shown|covered|mentioned|stated) in|does(?:n'?t| not) (?:say|state|mention|show|cover|include)|not stated|"
                    r"no (?:information|mention)|can(?:'?t|not) tell|not sure|do(?:n'?t| not) know|don'?t have", re.I)
ACCEPTED = {"answer": {"answered"}, "answer_or_admit": {"answered", "declined"}, "clarify_or_admit": {"clarified", "declined"}, "admit": {"declined", "clarified"}}


class Paced:
    """Wraps a ModelAnswerer for a batch run: at least `gap_s` between calls, and a rate-limit (HTTP 429) answer waits and retries, so a free-tier limit does not turn answers into fallbacks."""

    def __init__(self, inner, gap_s: float = 4.5, retries: int = 3, wait_s: float = 30.0):
        self.inner, self.gap_s, self.retries, self.wait_s, self._last = inner, gap_s, retries, wait_s, 0.0

    def __call__(self, *a, **kw):
        from ..providers.base import QuotaError
        for attempt in range(self.retries + 1):
            time.sleep(max(0.0, self._last + self.gap_s - time.time()))
            self._last = time.time()
            try:
                return self.inner(*a, **kw)
            except QuotaError:
                if attempt == self.retries:
                    raise
                time.sleep(self.wait_s)


def classify(result: dict) -> str:
    kind = result.get("kind")
    if kind in ("clarification", "needs_state"):
        return "clarified"
    if kind in ("unsupported", "needs_model", "decline"):
        return "declined"
    return "answered"


def _step_at(sl: StepList, t: float):
    timed = [s for s in sl.steps if s.video_start_s is not None]
    inside = [s for s in timed if s.video_start_s <= t <= (s.video_end_s if s.video_end_s is not None else s.video_start_s)]
    return (inside or sorted(timed, key=lambda s: abs(s.video_start_s - t)))[0] if timed else None


def _names(step) -> tuple[str, str]:
    return step.id.lower(), " ".join(step.goal.lower().split()[:3])


def run_one(q: dict, kb, tutorials, answerer=None) -> dict:
    svc = Service(S.Session(), None, kb, tutorials, None, answerer=answerer)
    svc.session.app = q["app"]
    svc.app_known = True                              # the suite states the application, as a UI that knows it would
    sl = None
    if q["scenario"] == "video_context":
        sl = StepList.model_validate_json((FIXTURES / f"steps_{q['video']}.json").read_text(encoding="utf-8"))
        svc.session.load(sl, tutorial={"id": q["video"], "title": f"saved extraction of {q['video']}", "source_type": "youtube"})
    for p in q.get("prior", []):
        svc.message(p)
    r = svc.message(q["question"])
    text = r["text"]
    low = text.lower()
    got = classify(r)
    admits = bool(ADMITS.search(text))
    checks = {"behaviour_ok": got in ACCEPTED[q["behaviour"]] or (answerer is not None and q["behaviour"] in ("admit", "answer_or_admit", "clarify_or_admit") and admits)}
    if got == "answered":
        checks["must_any_ok"] = all(any(w.lower() in low for w in grp) for grp in q.get("must_any", []))
    checks["must_not_ok"] = not any(w.lower() in low for w in q.get("must_not", []))
    target = None
    if sl is not None and q.get("expect_step_at") is not None:
        target = _step_at(sl, q["expect_step_at"])
    elif sl is not None and q.get("expect_step_id"):
        target = next((s for s in sl.steps if s.id == q["expect_step_id"]), None)
    elif sl is not None and q.get("expect_next_step"):
        target = sl.steps[1]
    if target is not None:
        ids, words = _names(target)
        checks["names_expected_step"] = ids in low or words in low
    ok = all(checks.values())
    return {"id": q["id"], "app": q["app"], "scenario": q["scenario"], "tags": q.get("tags", []), "question": q["question"], "expected_behaviour": q["behaviour"], "got": got,
            "route": r["route"], "kind": r["kind"], "admits": admits, "checks": checks, "auto_pass": ok, "reply": text, "reference": q["reference"]}


def run(suite_path: Path = SUITE, answerer=None) -> list[dict]:
    from ..service import _default_kb
    kb, tutorials = _default_kb()
    return [run_one(q, kb, tutorials, answerer) for q in json.loads(suite_path.read_text(encoding="utf-8"))["questions"]]


def summary(rows: list[dict]) -> dict:
    def block(rs):
        n = len(rs)
        return {"questions": n, "auto_pass": sum(r["auto_pass"] for r in rs), "answered": sum(r["got"] == "answered" for r in rs),
                "clarified": sum(r["got"] == "clarified" for r in rs), "declined": sum(r["got"] == "declined" for r in rs)}
    out = {"all": block(rows), "by_scenario": {}, "by_app": {}, "by_tag": {}}
    for key, field in (("by_scenario", "scenario"), ("by_app", "app")):
        groups = defaultdict(list)
        for r in rows:
            groups[r[field]].append(r)
        out[key] = {k: block(v) for k, v in groups.items()}
    tags = defaultdict(list)
    for r in rows:
        for t in r["tags"]:
            tags[t].append(r)
    out["by_tag"] = {k: block(v) for k, v in sorted(tags.items())}
    out["routes"] = dict(Counter(r["route"] for r in rows))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ingestion.eval.qa_suite")
    ap.add_argument("--suite", type=Path, default=SUITE)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--model-tier", choices=["iterate", "report"], help="answer with a model (grounded on the knowledge base) through the cost guard; omit for the rule-based layer only")
    ap.add_argument("--provider", choices=["gemini", "openai"], default="gemini", help="which model family answers (openai: text only, so it cannot recheck a video)")
    ap.add_argument("--openai-model", default=None, help="with --provider openai: the model id (default gpt-5.6-luna)")
    ap.add_argument("--max-usd", type=float, default=2.0, help="stop before a call that could pass this many dollars in this run")
    ap.add_argument("--recheck", action="store_true", help="with --model-tier: look at the video clip when the steps cannot answer a question about the tutorial (one extra call)")
    a = ap.parse_args(argv)
    answerer = None
    if a.model_tier or a.provider == "openai":
        from dotenv import load_dotenv
        load_dotenv()
        from ..answer_model import ModelAnswerer
        from ..budget import TIERS, BudgetedProvider, Ceilings, api_key_for
        from ..service import _default_kb
        kb, _ = _default_kb()
        if a.provider == "openai":
            from ..providers.openai_provider import CHEAP_MODEL, OpenAIProvider
            prov = BudgetedProvider(OpenAIProvider(model=a.openai_model or CHEAP_MODEL), ceilings=Ceilings.from_env(max_usd_run=a.max_usd), label="openai")
        else:
            from ..providers.gemini import GeminiProvider
            prov = BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model=TIERS[a.model_tier]), label="default")
        answerer = Paced(ModelAnswerer(prov, manual=kb, recheck=a.recheck, recheck_sweep=3 if a.recheck else 0))
    rows = run(a.suite, answerer)
    res = {"summary": summary(rows), "rows": rows}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
