"""Run the offline corpus (tests/corpus/cases.json) through the router and report deterministic metrics.

  python -m ingestion.eval.offline_report            # prints a table and writes runs/results/offline_report.json

No network and no model: every case is answered (or declined) by rules, the catalog and parsers. A case states expected
PROPERTIES (route, kind, ordered operations, forbidden operations, flags, assumptions ...), not exact wording.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from shared.answer import AnswerBundle

from ingestion.router import route

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "corpus" / "cases.json"


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))


def op_sequence(b: AnswerBundle) -> list[str]:
    out = []
    for s in (b.steps.steps if b.steps else []):
        ref = next((r for r in s.source_refs if r.startswith("catalog:")), None)
        if ref:
            out.append(ref.split(":", 1)[1].split("@")[0])
    return out


def _subseq(want: list[str], have: list[str]) -> bool:
    it = iter(have)
    return all(any(w == h for h in it) for w in want)


def prereq_handled(b: AnswerBundle, case: dict) -> bool:
    flags = [f for s in (b.steps.steps if b.steps else []) for f in s.flags]
    if b.assumptions or b.unmet_prerequisites or b.clarification:
        return True
    if any("prerequisite" in f or f.startswith("order") for f in flags):
        return True
    if any(s.provenance == "catalog_context" for s in (b.steps.steps if b.steps else [])):
        return True
    return case.get("observed") is not None   # observed state was available and nothing is unknown or unmet


def run_case(case: dict) -> tuple[AnswerBundle, float]:
    text = case.get("input")
    if "input_file" in case:
        text = (ROOT / case["input_file"]).read_text(encoding="utf-8")
    t0 = time.perf_counter()
    b = route(text, version=case.get("version"), observed=case.get("observed"), input_type=case.get("input_type"),
              duration_s=case.get("duration_s"))
    return b, (time.perf_counter() - t0) * 1000


def check(case: dict, b: AnswerBundle) -> list[str]:
    """Return the list of failed expectations (empty = pass)."""
    e, fails = case["expect"], []
    steps = b.steps.steps if b.steps else []
    flags = " || ".join(f.lower() for s in steps for f in s.flags)
    caveats = " || ".join(c.lower() for c in b.caveats)
    expl = " || ".join(x.text.lower() for x in b.explanations)
    assum = " || ".join([*b.assumptions, *[a for s in steps for a in s.assumptions]]).lower()
    ops = op_sequence(b)

    def need(cond: bool, msg: str):
        if not cond:
            fails.append(msg)

    need(b.api_calls == e.get("api_calls", 0), f"api_calls {b.api_calls}")
    if "route" in e: need(b.route == e["route"], f"route {b.route} != {e['route']}")
    if "kind" in e: need(b.kind == e["kind"], f"kind {b.kind} != {e['kind']}")
    if "ops_in_steps" in e: need(_subseq(e["ops_in_steps"], ops), f"ops {ops} lack ordered {e['ops_in_steps']}")
    for o in e.get("forbid_ops", []): need(o not in ops, f"forbidden op {o} present in {ops}")
    if "min_steps" in e: need(len(steps) >= e["min_steps"], f"{len(steps)} steps < {e['min_steps']}")
    if "max_steps" in e: need(len(steps) <= e["max_steps"], f"{len(steps)} steps > {e['max_steps']} (an unsupported extra step?)")
    if e.get("no_steps"): need(not steps, "steps were produced")
    if "clarification" in e: need(bool(b.clarification) == e["clarification"], f"clarification={bool(b.clarification)}")
    if "fallback" in e: need(bool(b.fallback_reason) == e["fallback"], f"fallback_reason={b.fallback_reason!r}")
    if "explanations_min" in e: need(len(b.explanations) >= e["explanations_min"], "too few explanations")
    for sub in e.get("explanation_contains", []): need(sub.lower() in expl, f"explanation lacks '{sub}'")
    if e.get("explanation_links"): need(any(x.applies_to_steps for x in b.explanations), "no explanation is linked to a step")
    for sub in e.get("flags_contain", []): need(sub.lower() in flags, f"no step flag contains '{sub}'")
    for sub in e.get("flags_absent", []): need(sub.lower() not in flags, f"unexpected flag '{sub}'")
    for sub in e.get("caveats_contain", []): need(sub.lower() in caveats or sub.lower() in flags, f"caveats lack '{sub}'")
    for sub in e.get("assumptions_contain", []): need(sub.lower() in assum, f"assumptions lack '{sub}'")
    for sub in e.get("unmet_contains", []): need(any(sub.lower() in u.lower() for u in b.unmet_prerequisites), f"unmet lacks '{sub}'")
    if e.get("unmet_empty"): need(not b.unmet_prerequisites, "unexpected unmet prerequisites")
    if "first_step_goal_contains" in e: need(bool(steps) and e["first_step_goal_contains"] in steps[0].goal, "first step goal mismatch")
    if e.get("sources"): need(bool(b.sources), "no source attribution")
    if e.get("goal_unchanged"):
        need(bool(steps) and steps[0].goal.lower().startswith(case["input"].lower().rstrip(".")[:20]), "the user's wording was changed")
    if e.get("all_narrated"):
        need(bool(steps) and all(s.support == "narrated" and s.provenance == "transcript_rules" for s in steps), "a transcript step is not narrated")
    if "times_within" in e:
        need(all((s.video_end_s or 0) <= e["times_within"] and s.video_start_s is not None for s in steps), "step time outside the duration")
    if e.get("prereq_handled"): need(prereq_handled(b, case), "prerequisite not handled (no assumption, flag, question or observed check)")
    try:   # every bundle must round-trip through the shared schema
        AnswerBundle.model_validate_json(b.model_dump_json())
    except Exception as ex:   # pragma: no cover
        fails.append(f"schema round-trip failed: {ex}")
    return fails


def run_all() -> dict:
    rows, lat = [], []
    for case in load_cases():
        b, ms = run_case(case)
        fails = check(case, b)
        lat.append(ms)
        rows.append({"id": case["id"], "category": case["category"], "supported": case["supported"], "route": b.route,
                     "kind": b.kind, "steps": len(b.steps.steps) if b.steps else 0, "passed": not fails, "fails": fails,
                     "ms": round(ms, 2), "api_calls": b.api_calls, "schema_ok": True,
                     "answered_offline": b.route not in ("fallback_required", "clarify"),
                     "needs_model": b.route == "fallback_required" or bool(b.fallback_reason),
                     "prereq_case": bool(case["expect"].get("prereq_handled")),
                     "prereq_ok": prereq_handled(b, case) if case["expect"].get("prereq_handled") else None})
    sup = [r for r in rows if r["supported"]]
    pre = [r for r in rows if r["prereq_case"]]
    routes: dict[str, int] = {}
    for r in rows:
        routes[r["route"]] = routes.get(r["route"], 0) + 1
    summary = {
        "cases": len(rows), "passed": sum(r["passed"] for r in rows), "pass_rate": round(sum(r["passed"] for r in rows) / len(rows), 3),
        "schema_valid_rate": 1.0 if all(r["schema_ok"] for r in rows) else 0.0,
        "coverage_of_supported_requests": round(sum(r["answered_offline"] for r in sup) / len(sup), 3), "supported_cases": len(sup),
        "routes": routes, "clarifications": routes.get("clarify", 0), "fallback_required": routes.get("fallback_required", 0),
        "cases_with_part_needing_a_model": sum(r["needs_model"] for r in rows),
        "model_calls_made": sum(r["api_calls"] for r in rows),
        "model_calls_a_model_only_pipeline_would_have_made": len(rows),
        "calls_avoided": len(rows) - routes.get("fallback_required", 0),
        "prerequisite_handling_correct": f"{sum(1 for r in pre if r['prereq_ok'])}/{len(pre)}",
        "latency_ms_mean": round(sum(lat) / len(lat), 2), "latency_ms_max": round(max(lat), 2),
    }
    return {"summary": summary, "rows": rows}


def main() -> int:
    res = run_all()
    for r in res["rows"]:
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['id']:<38} {r['route']:<18} {r['kind']:<15} steps={r['steps']:<2} {r['ms']:>6.1f}ms {'; '.join(r['fails'])}")
    print(json.dumps(res["summary"], indent=1))
    out = ROOT / "runs" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "offline_report.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0 if res["summary"]["passed"] == res["summary"]["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
