"""Score the router + knowledge base on a labelled question set (classes and gold pages), deterministically and offline.

  python -m ingestion.eval.kb_eval --set tests/corpus/heldout_questions.json --label A-dev
  python -m ingestion.eval.kb_eval --set tests/corpus/heldout_B_questions.json --label B-heldout

Predicted class of a bundle: answer_local (documentation or catalog answer), ask_state, find_tutorial, import_tutorial, outside_index,
clarify, decline (or 'fallback' for the old catalog-only fallback). Metrics: class accuracy, retrieval hit@1/@3 of the gold manual page,
false confidence (answered locally when the label says it should not be), unnecessary escalation (not answered although it could be),
attribution checks, tutorial-recommendation correctness, model/network calls made, latency.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import time
from pathlib import Path

from shared.answer import AnswerBundle

from ingestion.kb.index import KnowledgeBase
from ingestion.router import route
from ingestion.tutorials import load_index

ROOT = Path(__file__).resolve().parents[2]


def predicted_class(b: AnswerBundle) -> str:
    if b.route == "clarify":
        return "clarify"
    if b.route == "decline":
        return "decline"
    if b.route == "outside_index":
        return "outside_index"
    if b.route in ("tutorial_index",):
        return "find_tutorial"
    if b.route == "tutorial_import":
        return "import_tutorial"
    if b.kind in ("needs_state", "troubleshooting"):
        return "ask_state"
    if b.route == "fallback_required":
        return "fallback"
    return "answer_local"


def cited_pages(b: AnswerBundle) -> list[str]:
    """Manual page paths the bundle cites, in order (sources, then step refs)."""
    out: list[str] = []
    for s in [*b.sources, *[x for e in b.explanations for x in e.sources], *b.pointers]:
        m = re.search(r"/manual/en/[^/]+/(.+?)\.html", s.url or "")
        if m and m.group(1) not in out:
            out.append(m.group(1))
    for st in (b.steps.steps if b.steps else []):
        for r in st.source_refs:
            m = re.match(r"doc:(.+?)@", r)
            if m and m.group(1) not in out:
                out.append(m.group(1))
    return out


def attribution_ok(b: AnswerBundle) -> bool:
    """Every excerpt names a manual source with URL, date and licence; doc-extracted steps cite their page; trust matches content."""
    for e in b.explanations:
        if e.is_excerpt and not (e.sources and all(s.url and s.licence and s.verified_on for s in e.sources)):
            return False
    if b.steps and any(s.provenance == "doc_reference" for s in b.steps.steps):
        if b.trust != "doc_extracted" or not all(any(r.startswith("doc:") for r in s.source_refs) for s in b.steps.steps if s.provenance == "doc_reference"):
            return False
    if any(e.is_excerpt for e in b.explanations) and not b.steps and b.trust not in ("doc_passage", "catalog", "doc_extracted"):
        return False
    return True


def evaluate_set(path: Path, kb: KnowledgeBase, tutorials: list[dict], label: str) -> dict:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    rows, lat = [], []
    for c in cases:
        t0 = time.perf_counter()
        b = route(c["q"], version=c.get("version"), kb=kb, tutorials=tutorials)
        lat.append((time.perf_counter() - t0) * 1000)
        pred = predicted_class(b)
        gold_pages = c.get("pages", [])
        cited = cited_pages(b)
        retr = kb.search(c["q"]) if gold_pages else None
        top3 = [h.path for h in retr.hits[:3]] if retr else []
        try:
            AnswerBundle.model_validate_json(b.model_dump_json())
            schema_ok = True
        except Exception:
            schema_ok = False
        rows.append({
            "id": c["id"], "q": c["q"], "gold": c["class"], "pred": pred, "route": b.route, "kind": b.kind, "trust": b.trust,
            "correct_class": pred == c["class"], "cited": cited[:3],
            "retrieval_hit1": (top3[:1] and top3[0] in gold_pages) if gold_pages else None,
            "retrieval_hit3": any(p in gold_pages for p in top3) if gold_pages else None,
            "answer_cites_gold": any(p in gold_pages for p in cited) if gold_pages and pred in ("answer_local", "ask_state") else None,
            "steps": len(b.steps.steps) if b.steps else 0, "recs": len(b.recommendations), "pointers": len(b.pointers),
            "attribution_ok": attribution_ok(b), "schema_ok": schema_ok, "api_calls": b.api_calls, "network_calls": b.network_calls,
            "version_caveat": bool(b.version_note or any("version" in x.lower() for x in b.caveats)) if c.get("expect_version_caveat") else None,
            "recs_correct": (bool(b.recommendations) == c["expect_recs"]) if "expect_recs" in c else None,
        })
    gold_cls = collections.Counter(r["gold"] for r in rows)
    per_class = {k: round(sum(r["correct_class"] for r in rows if r["gold"] == k) / n, 3) for k, n in gold_cls.items()}
    al = [r for r in rows if r["gold"] == "answer_local"]
    paged = [r for r in rows if r["retrieval_hit1"] is not None]
    wrong_conf = [r["id"] for r in rows if r["gold"] != "answer_local" and r["pred"] == "answer_local"]
    escal = [r["id"] for r in al if r["pred"] != "answer_local"]
    confusion: dict[str, dict[str, int]] = {}
    for r in rows:
        confusion.setdefault(r["gold"], {}).setdefault(r["pred"], 0)
        confusion[r["gold"]][r["pred"]] += 1
    summary = {
        "label": label, "cases": len(rows), "class_accuracy": round(sum(r["correct_class"] for r in rows) / len(rows), 3), "per_class_accuracy": per_class,
        "answer_local_answered": f"{sum(r['pred'] == 'answer_local' for r in al)}/{len(al)}",
        "answer_local_cites_gold_page": f"{sum(bool(r['answer_cites_gold']) for r in al)}/{len(al)}",
        "retrieval_hit@1": f"{sum(bool(r['retrieval_hit1']) for r in paged)}/{len(paged)}",
        "retrieval_hit@3": f"{sum(bool(r['retrieval_hit3']) for r in paged)}/{len(paged)}",
        "false_confidence": {"n": len(wrong_conf), "ids": wrong_conf}, "unnecessary_escalation": {"n": len(escal), "ids": escal},
        "attribution_ok": f"{sum(r['attribution_ok'] for r in rows)}/{len(rows)}", "schema_valid": f"{sum(r['schema_ok'] for r in rows)}/{len(rows)}",
        "model_calls": sum(r["api_calls"] for r in rows), "network_calls": sum(r["network_calls"] for r in rows),
        "tutorial_recs_correct": f"{sum(bool(r['recs_correct']) for r in rows if r['recs_correct'] is not None)}/{sum(r['recs_correct'] is not None for r in rows)}",
        "version_caveat_present": [r["version_caveat"] for r in rows if r["version_caveat"] is not None],
        "latency_ms_mean": round(sum(lat) / len(lat), 2), "latency_ms_max": round(max(lat), 2), "confusion": confusion,
    }
    return {"summary": summary, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--db", default=str(ROOT / "knowledge" / "kb.sqlite"))
    a = ap.parse_args(argv)
    kb = KnowledgeBase(a.db)
    res = evaluate_set(Path(a.set), kb, load_index(), a.label)
    print(json.dumps(res["summary"], indent=1))
    for r in res["rows"]:
        if not r["correct_class"]:
            print(f"  MISS {r['id']:<5} gold={r['gold']:<15} pred={r['pred']:<15} {r['q'][:70]}")
    out = ROOT / "runs" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"kb_eval_{a.label}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
