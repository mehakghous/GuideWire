"""Zero-cost evaluation of transcript-only extraction against a frozen reference.

  python -m ingestion.eval.transcript_eval --transcript local_data/34FBeC9mktE.transcript.txt \
      --reference eval_data/gold/34FBeC9mktE.reference.v1.json --duration 188

What a transcript can and cannot establish is built into the report:
- narrated recall: verified reference steps with evidence_type narrated or both (the transcript can evidence the SAID part);
- demonstrated recall is reported two ways and never conflated:
    * content coverage: does some step cover the reference step by time and meaning (narration may describe a demonstration);
    * visual claim: would a step claim the action was seen on screen? Always 0 here by construction;
- reference steps that are demonstrated-only (nothing said) are NOT scorable from a transcript and are reported as
  'not applicable', never as misses.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ingestion.experiment import _frozen_ok
from ingestion.transcript import check_evidence

from .coverage import evaluate_coverage
from .gold import GoldSet


def evaluate_transcript(text: str, reference: Path, duration_s: float | None, version: str | None = "2.80") -> dict:
    from ingestion.transcript_ingest import ingest_transcript, parse_timed_text, clean_cues

    sha = _frozen_ok(reference)
    gold = GoldSet.model_validate(json.loads(reference.read_text(encoding="utf-8")))
    res = ingest_transcript(text, duration_s=duration_s or gold.duration_s, version=version, video_id=gold.video_id)
    sl = res.steplist
    out: dict = {"reference": reference.name, "reference_sha256": sha[:12], "stats": res.stats, "limitations": res.limitations}
    if sl is None:
        return {**out, "steps": 0}
    rep = evaluate_coverage(gold, sl)
    cues, _ = clean_cues(parse_timed_text(text, duration_s))
    check_evidence(sl, cues)
    unsupported_quotes = sum(1 for s in sl.steps if any("evidence quote" in f for f in s.flags))
    n_not_applicable = [r.id for r in gold.steps if r.is_verified and (r.evidence_type == "demonstrated")]
    out.update({
        "steps": len(sl.steps),
        "narrated_recall_lenient": rep.narrated_recall, "narrated_recall_strict": rep.narrated_recall_strict,
        "narrated_only_recall": rep.narrated_only_recall,
        "overall_recall_lenient": rep.overall_recall,
        "demonstrated_content_coverage_lenient": rep.demonstrated_recall,
        "demonstrated_visual_claims": len(rep.visual_claims),
        "demonstrated_recall_claimed": rep.demonstrated_recall_claimed,
        "not_applicable_demonstrated_only_reference_steps": n_not_applicable,
        "precision_lenient": rep.precision_lenient, "precision_strict": rep.precision_strict,
        "unmatched_generated": rep.unmatched_gen, "broad_generated": rep.broad_gen, "duplicate_generated": rep.duplicate_gen,
        "unsupported_evidence_quotes": unsupported_quotes, "false_visual_claims": rep.false_visual_claims,
        "timestamps_beyond_end": rep.beyond_end_gen, "untimed": rep.untimed_gen,
        "temporal_within_tol": rep.temporal_within_tol, "temporal_median_abs_err_s": rep.temporal_median_abs_err_s,
        "state_recall_vs_reference": rep.state_recall, "state_wrong_rate_vs_reference": rep.state_wrong_rate,
        "order_inversion_rate": rep.order_inversion_rate, "prerequisite_violation_rate": rep.prerequisite_violation_rate,
        "counts": rep.counts, "covered_reference_ids": sorted(rep.lenient),
        "strict_pairs": rep.strict,
        "steps_detail": [{"id": s.id, "t": [s.video_start_s, s.video_end_s], "op": s.source_refs[0], "support": s.support,
                          "provenance": s.provenance} for s in sl.steps],
    })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    r = evaluate_transcript(Path(a.transcript).read_text(encoding="utf-8"), Path(a.reference), a.duration)
    txt = json.dumps(r, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
