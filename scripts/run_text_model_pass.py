"""ONE text-only model call on a LOCAL transcript, scored against the frozen reference with the same scorer as the rule-based route.

    python scripts/run_text_model_pass.py --transcript local_data/34FBeC9mktE.transcript.txt --reference eval_data/gold/34FBeC9mktE.reference.v1.json --duration 188

Authorised by the project owner (2026-10-11) with: a cost cap, NO retries. Therefore: exactly one HTTP attempt (provider max_attempts=1) and one
validation attempt (extract max_attempts=1); any failure is recorded and the script stops. Nothing is cached or re-run.
The video itself is never sent, only the caption text. The result is a single run on the DEVELOPMENT video (the rules were tuned on it), so it
is a data point for the plan, not a held-out comparison. Output: eval_data/results/<video>.text-model-pass.<UTC date>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from ingestion.eval.coverage import evaluate_coverage  # noqa: E402
from ingestion.eval.gold import GoldSet  # noqa: E402
from ingestion.experiment import _frozen_ok  # noqa: E402
from ingestion.extract import ExtractionError, _run  # noqa: E402
from ingestion.providers.gemini import GeminiProvider, ProviderError  # noqa: E402
from ingestion.transcript import check_evidence  # noqa: E402
from ingestion.transcript_ingest import clean_cues, parse_timed_text  # noqa: E402

INSTRUCTION = (
    "Below is the timestamped caption transcript of a Blender tutorial video. The video itself is NOT provided. Produce step records for the "
    "actions the speaker tells the viewer to perform.\n"
    "Rules: use ONLY what the narration says; do not add steps and do not describe what might be shown on screen; set support to \"narrated\" for "
    "every step; video_start_s and video_end_s are the start of the first and the end of the last caption line that contain the instruction "
    "(seconds); evidence must be verbatim quotes from the transcript; skip explanations, jokes, asides, and anything the speaker says NOT to do or "
    "only hypothetically.\n\n--- TRANSCRIPT ---\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--prompt-version", default="v3")
    a = ap.parse_args(argv)
    load_dotenv()
    text = Path(a.transcript).read_text(encoding="utf-8")
    ref = Path(a.reference)
    sha = _frozen_ok(ref)
    gold = GoldSet.model_validate(json.loads(ref.read_text(encoding="utf-8")))
    cues, _ = clean_cues(parse_timed_text(text, a.duration))
    lines = "\n".join(f"[{c.start_s:.1f}-{c.end_s:.1f}s] {c.text}" for c in cues)
    prompt = INSTRUCTION + lines
    provider = GeminiProvider(max_attempts=1)
    attempts: list[dict] = []
    t0 = time.time()
    out: dict = {"label": "text-only model pass, single run, DEVELOPMENT video (not held out)", "model_id": provider.model_id, "prompt_version": a.prompt_version,
                 "reference": ref.name, "reference_sha256": sha[:12], "prompt_chars": len(prompt), "cues": len(cues), "retries_allowed": 0,
                 "run_utc": datetime.now(timezone.utc).isoformat()}
    try:
        sl = _run(provider, prompt=prompt, video_url=None, source_type="youtube", app="blender", video_id=gold.video_id, video_duration_s=a.duration,
                  prompt_version=a.prompt_version, max_attempts=1, on_attempt=attempts.append)
        out["latency_s"] = round(time.time() - t0, 1)
        check_evidence(sl, cues)
        rep = evaluate_coverage(gold, sl)
        unsupported = sum(1 for s in sl.steps if any("evidence quote" in f for f in s.flags))
        out.update({"status": "accepted", "steps": len(sl.steps), "narrated_recall_lenient": rep.narrated_recall, "narrated_recall_strict": rep.narrated_recall_strict,
                    "narrated_only_recall": rep.narrated_only_recall, "precision_lenient": rep.precision_lenient, "precision_strict": rep.precision_strict,
                    "unsupported_evidence_quotes": unsupported, "false_visual_claims": rep.false_visual_claims, "timestamps_beyond_end": rep.beyond_end_gen,
                    "untimed": rep.untimed_gen, "temporal_within_tol": rep.temporal_within_tol, "temporal_median_abs_err_s": rep.temporal_median_abs_err_s,
                    "state_wrong_rate_vs_reference": rep.state_wrong_rate, "order_inversion_rate": rep.order_inversion_rate,
                    "prerequisite_violation_rate": rep.prerequisite_violation_rate, "unmatched_generated": rep.unmatched_gen,
                    "duplicate_generated": rep.duplicate_gen, "steps_detail": [{"id": s.id, "goal": s.goal, "t": [s.video_start_s, s.video_end_s], "support": s.support,
                                                                               "flags": s.flags[:3]} for s in sl.steps]})
    except (ExtractionError, ProviderError) as e:
        out.update({"status": "failed (no retry made)", "error": str(e)[:600], "latency_s": round(time.time() - t0, 1)})
    except Exception as e:                                   # QuotaError and anything else: record and stop, never retry
        out.update({"status": f"failed (no retry made): {type(e).__name__}", "error": str(e)[:600], "latency_s": round(time.time() - t0, 1)})
    out["usage"] = getattr(provider, "usage", [])
    out["http_events"] = [{k: v for k, v in e.items() if k != "error"} for e in getattr(provider, "events", [])]
    out["attempt_records"] = [{k: v for k, v in r.items() if k in ("attempt", "accepted", "error", "issues", "usage")} for r in attempts]
    dest = ROOT / "eval_data" / "results" / f"{gold.video_id}.text-model-pass.{datetime.now(timezone.utc):%Y%m%d}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("steps_detail", "attempt_records", "http_events")}, indent=1))
    print("wrote", dest)
    return 0 if out.get("status") == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
