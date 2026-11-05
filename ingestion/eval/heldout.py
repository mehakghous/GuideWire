"""Held-out evaluation over human-labelled tutorials: recall per evidence type, precision, a pipeline FUNNEL and a CATEGORY for every missed action.

    python -m ingestion.eval.heldout --manifest eval_data/labels/manifest.json

Why a funnel and categories: one recall number cannot say what to fix. For each reference action the human says is narrated ("said" or "both"):
  stage 1  in_captions   some caption near that time shares the action's words   (if not: nothing in the transcript to extract)
  stage 2  recognised    the offline rules identified an operation in a transcript unit at that time   (if not: a pattern/catalog gap)
  stage 3  emitted       a final step covers it (right content AND time)          (if recognised but not emitted: lost by merging/filtering)
Each action that never reaches stage 3 gets exactly ONE category, checked in this order:
  demonstrated_only   the human marked it "shown": a transcript cannot contain it (reported apart, not counted against the transcript route)
  not_in_captions     stage 1 failed
  outside_catalog     the action maps to none of the catalog operations or key patterns, so the rules cannot represent it
  looks_equivalent    a step overlaps the action in time with similar wording, but the scorer's match test did not credit it (scorer strictness, or a
                      step that merged several actions into one wording)
  timing_miss         a step with similar content exists elsewhere in the video but not within the tolerance of this action
  recognition_miss    the operation is in the catalog and narrated, but no rule fired in the window
  lost_after_recognition   a rule fired but no final step covers it (merged into a neighbour, or filtered)
  other
Limits: word-overlap tests are crude; the categories tell you where to look, they are not a proof of cause. Pooled numbers add counts across
videos (a long video weighs more); per-video numbers are reported too. Nothing here tunes anything: it only reads labels and runs the pipeline.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from ..catalog import match_aliases
from ..transcript_ingest import _choose, clean_cues, group_units, ingest_transcript, parse_timed_text
from .coverage import evaluate_coverage, similarity
from .gold import GoldSet, GoldStep
from .labels import agreement, load_csv

ROOT = Path(__file__).resolve().parents[2]
_STOP = frozenset("the a an and or to of in on at it is this that then now you your we with for from by as be are so just".split())
CATEGORIES = ["demonstrated_only", "not_in_captions", "outside_catalog", "looks_equivalent", "timing_miss", "recognition_miss", "lost_after_recognition", "other"]


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def _rid(r: GoldStep) -> str:
    return r.id or f"R{r.order:02d}"


def _ref_words(r: GoldStep) -> set[str]:
    return _content_words(r.goal + " " + " ".join(k for a in r.actions for k in a.keys) + " " + " ".join(a.ui_element or "" for a in r.actions))


def evaluate_video(gold: GoldSet, transcript: str, *, version: str | None = None) -> dict:
    cues, _ = clean_cues(parse_timed_text(transcript, gold.duration_s))
    units = group_units(cues)
    res = ingest_transcript(transcript, duration_s=gold.duration_s, version=version, video_id=gold.video_id)
    sl = res.steplist
    rep = evaluate_coverage(gold, sl) if sl else None
    covered_len = set(rep.lenient) if rep else set()
    covered_strict = set(rep.strict) if rep else set()
    narr = [r for r in gold.steps if r.evidence_type in ("narrated", "both")]
    cats: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    funnel = Counter()
    for r in gold.steps:
        rid = _rid(r)
        if r.evidence_type == "demonstrated":
            cats["demonstrated_only"].append(rid)
            continue
        lo, hi = r.t_start - r.tol_s, (r.t_end if r.t_end is not None else r.t_start) + r.tol_s + 2
        win_cues = [c for c in cues if c.end_s >= lo and c.start_s <= hi]
        rw = _ref_words(r)
        in_cap = bool(rw) and len(rw & _content_words(" ".join(c.text for c in win_cues))) / len(rw) >= 0.3
        win_units = [u for u in units if u.end >= lo and u.start <= hi]
        recognised = any(_choose(u.text) for u in win_units)
        emitted = rid in covered_len
        funnel["narrated_refs"] += 1
        funnel["in_captions"] += in_cap
        funnel["recognised"] += recognised
        funnel["emitted"] += emitted
        if emitted:
            continue
        in_catalog = bool(match_aliases(r.goal + " " + " ".join(k for a in r.actions for k in a.keys))) or bool(_choose(r.goal))
        steps = sl.steps if sl else []
        similar = [g for g in steps if similarity(g.goal, r.goal) >= 0.3]
        overlapping = [g for g in similar if g.video_start_s is not None and g.video_start_s <= hi and (g.video_end_s or g.video_start_s) >= lo]
        cats["not_in_captions" if not in_cap else "outside_catalog" if not in_catalog else "looks_equivalent" if overlapping else "timing_miss" if similar else
             "recognition_miss" if not recognised else "lost_after_recognition"].append(rid)
    n_miss = sum(len(v) for k, v in cats.items() if k != "demonstrated_only")
    return {
        "video_id": gold.video_id, "annotator": gold.annotator, "n_reference": len(gold.steps), "n_narrated_or_both": len(narr), "n_generated": len(sl.steps) if sl else 0,
        "narrated_covered_lenient": len([r for r in narr if _rid(r) in covered_len]), "narrated_covered_strict": len([r for r in narr if _rid(r) in covered_strict]),
        "precision_lenient": rep.precision_lenient if rep else None, "precision_strict": rep.precision_strict if rep else None,
        "unmatched_generated": rep.unmatched_gen if rep else [], "false_visual_claims": rep.false_visual_claims if rep else [],
        "temporal_within_tol": rep.temporal_within_tol if rep else None, "funnel": dict(funnel), "categories": cats,
        "missed_narrated": n_miss, "accounted": n_miss == len(narr) - len([r for r in narr if _rid(r) in covered_len]),
    }


def pool(rows: list[dict]) -> dict:
    n = sum(r["n_narrated_or_both"] for r in rows)
    f = Counter()
    cats = Counter()
    for r in rows:
        f.update(r["funnel"])
        cats.update({k: len(v) for k, v in r["categories"].items()})
    cl, cs = sum(r["narrated_covered_lenient"] for r in rows), sum(r["narrated_covered_strict"] for r in rows)
    gen = sum(r["n_generated"] for r in rows)
    return {"videos": len(rows), "reference_steps": sum(r["n_reference"] for r in rows), "narrated_or_both": n, "generated": gen,
            "narrated_recall_lenient": round(cl / n, 3) if n else None, "narrated_recall_strict": round(cs / n, 3) if n else None,
            "per_video_recall_lenient": [round(r["narrated_covered_lenient"] / r["n_narrated_or_both"], 2) if r["n_narrated_or_both"] else None for r in rows],
            "funnel": dict(f), "funnel_rates": {k: round(f[k] / f["narrated_refs"], 3) for k in ("in_captions", "recognised", "emitted")} if f["narrated_refs"] else {},
            "missed_by_category": {k: v for k, v in cats.items() if v}, "demonstrated_only_not_counted_against_transcripts": cats["demonstrated_only"]}


def run_manifest(manifest_path: Path) -> dict:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    tdir = ROOT / m.get("transcripts_dir", "local_data/labelling")
    rows, problems, agree = [], {}, {}
    for v in m["videos"]:
        vid = v["video_id"]
        sheets = {a: base / f"{vid}.{a}.csv" for a in v["annotators"]}
        golds = {}
        for a, p in sheets.items():
            if not p.exists():
                problems[f"{vid}.{a}"] = ["sheet not found (not labelled yet)"]
                continue
            g, pr = load_csv(p, duration_s=v["duration_s"], video_id=vid, title=v.get("title"), annotator=a, app_version=v.get("app_version"))
            if pr.errors or g is None:
                problems[f"{vid}.{a}"] = pr.errors
                continue
            if pr.warnings:
                problems[f"{vid}.{a}"] = [f"warning: {w}" for w in pr.warnings]
            golds[a] = g
        tp = tdir / f"{vid}.transcript.txt"
        prim = v["annotators"][0]
        if prim not in golds or not tp.exists():
            if not tp.exists():
                problems[vid] = problems.get(vid, []) + ["transcript missing"]
            continue
        rows.append(evaluate_video(golds[prim], tp.read_text(encoding="utf-8"), version=v.get("app_version")))
        if len(golds) > 1:
            other = [a for a in golds if a != prim][0]
            ag = agreement(golds[prim], golds[other])
            agree[vid] = {"annotators": [prim, other], "dice": ag.dice, "matched": ag.matched, "n": [ag.n_a, ag.n_b], "evidence_agreement": ag.evidence_agreement,
                          "importance_agreement": ag.importance_agreement, "median_start_diff_s": ag.median_start_diff_s}
    return {"manifest": str(manifest_path.name), "labelled_videos": len(rows), "per_video": rows, "pooled": pool(rows) if rows else None, "agreement": agree,
            "mean_agreement_dice": round(sum(a["dice"] for a in agree.values()) / len(agree), 3) if agree else None, "problems": problems}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "eval_data" / "labels" / "manifest.json"))
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = run_manifest(Path(a.manifest))
    summary = {k: v for k, v in res.items() if k != "per_video"}
    print(json.dumps(summary, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
