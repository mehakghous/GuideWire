"""Phase 1 report: how good is step extraction, per application.

Two kinds of number, never mixed:
* STRUCTURE (needs no human): measured on the model output alone. Share of steps with a checkable end state, with how-to and check lines, with a time,
  with a feature id; flags per step; share of the video the steps span; steps that run past the end of the video.
* ACCURACY (needs a human gold file in eval_data/gold/<video id>.gold.json): step recall and precision, timestamp accuracy, state recall. Without a gold
  file these are reported as None. A gold file must be written by a person watching the video (docs/labelling_guide.md); nothing here writes one.

    python -m ingestion.eval.phase1 runs/phase1/*.json [--gold-dir eval_data/gold]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from shared.step_record import StepList

from .gold import GoldSet
from .metrics import evaluate


def structure(sl: StepList) -> dict:
    """Numbers from the model output alone. Rates are over MECHANICS steps where noted (craft steps are never graded)."""
    steps = sl.steps
    n = len(steps)
    mech = [s for s in steps if s.kind == "mechanics"]
    dur = sl.video_duration_s
    spans = [(s.video_start_s, s.video_end_s) for s in steps if s.video_start_s is not None and s.video_end_s is not None]
    covered = sum(max(0.0, b - a) for a, b in spans)

    def rate(k: int, d: int) -> float | None:
        return round(k / d, 3) if d else None

    return {
        "steps": n,
        "mechanics_steps": len(mech),
        "checkable_end_state": rate(sum(1 for s in mech if s.expected_state), len(mech)),
        "with_how_to": rate(sum(1 for s in steps if s.how_to), n),
        "with_check": rate(sum(1 for s in steps if s.check), n),
        "with_time": rate(sum(1 for s in steps if s.video_start_s is not None), n),
        "with_feature_id": rate(sum(1 for s in steps if s.feature_id), n),
        "flags_per_step": round(sum(len(s.flags) for s in steps) / n, 2) if n else None,
        "order_flags": sum(1 for s in steps for f in s.flags if f.startswith("order:")),
        "video_covered": rate(round(covered), round(dur)) if dur else None,
        "past_end": sum(1 for s in steps for t in (s.video_start_s, s.video_end_s) if t is not None and dur and t > dur + 1),
        "warnings": len(sl.warnings),
    }


def accuracy(sl: StepList, gold: GoldSet | None) -> dict:
    """Recall, precision and timestamp accuracy against a human gold file; all None without one."""
    if gold is None:
        return {"gold": False, "core_recall": None, "precision": None, "timestamp_accuracy": None, "state_recall": None}
    r = evaluate(gold, sl)
    return {"gold": True, "core_recall": round(r.core_recall, 3), "precision": round(r.precision, 3),
            "timestamp_accuracy": None if r.timestamp_accuracy is None else round(r.timestamp_accuracy, 3),
            "state_recall": None if r.state_recall is None else round(r.state_recall, 3)}


def load_gold(gold_dir: Path, video_id: str | None) -> GoldSet | None:
    """eval_data/gold/<video id>.gold.json. The DRAFT, reference and posthoc files are not final human gold and are ignored."""
    if not video_id:
        return None
    p = gold_dir / f"{video_id}.gold.json"
    return GoldSet.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def report(paths: list[Path], gold_dir: Path) -> list[dict]:
    rows = []
    for p in paths:
        sl = StepList.model_validate_json(p.read_text(encoding="utf-8"))
        rows.append({"file": p.name, "app": sl.app, "video_id": sl.video_id, "model": sl.model_id, "prompt": sl.prompt_version,
                     **structure(sl), **accuracy(sl, load_gold(gold_dir, sl.video_id))})
    return rows


def per_app(rows: list[dict]) -> dict[str, dict]:
    """Average each structure rate over the runs of an application (a run with None for a rate is left out of that rate)."""
    by = defaultdict(list)
    for r in rows:
        by[r["app"]].append(r)
    keys = ("checkable_end_state", "with_how_to", "with_check", "with_time", "with_feature_id", "flags_per_step", "video_covered")
    out = {}
    for app, rs in by.items():
        out[app] = {"runs": len(rs), "steps": sum(r["steps"] for r in rs)}
        for k in keys:
            v = [r[k] for r in rs if r[k] is not None]
            out[app][k] = round(sum(v) / len(v), 3) if v else None
        out[app]["runs_with_gold"] = sum(1 for r in rs if r["gold"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ingestion.eval.phase1")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--gold-dir", type=Path, default=Path("eval_data") / "gold")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = report(a.files, a.gold_dir)
    out = {"runs": rows, "per_application": per_app(rows),
           "note": "accuracy fields are None until a human gold file exists for the video; structure fields are measured on model output only"}
    print(json.dumps(out, indent=1) if a.json else json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
