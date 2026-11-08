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
from .metrics import evaluate, similarity


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


TIME_TOL_S = 5.0        # a gold action counts as inside a step when it starts within this many seconds of the step's span
TEXT_MIN = 0.5          # share of the gold action's words (3+ letters) that the step's text must contain


def _step_text(st) -> str:
    """Everything a step says about what to do: goal, result, how-to lines and the UI elements it names."""
    return " ".join([st.goal, st.result or "", *(h.text for h in st.how_to), *(a.ui_element or "" for a in st.actions)])


def covered_actions(sl: StepList, gold: GoldSet) -> list[tuple]:
    """For every gold action: (action, inside_a_step_span, inside_a_span_and_words_found). The unit the coverage numbers and the small-action report count."""
    timed = [s for s in sl.steps if s.video_start_s is not None and s.video_end_s is not None]
    out = []
    for g in gold.steps:
        inside = [s for s in timed if s.video_start_s - TIME_TOL_S <= g.t_start <= s.video_end_s + TIME_TOL_S]
        out.append((g, bool(inside), any(similarity(_step_text(s), g.goal) >= TEXT_MIN for s in inside)))
    return out


def coverage(sl: StepList, gold: GoldSet) -> dict:
    """Many-to-one scoring. A person labels small actions; a step usually covers several, so one step may cover many gold actions.
    * recall: share of CORE gold actions that lie inside some step's time span AND whose words the step's text contains (text_recall_core), or that only
      lie inside a span (time_recall_core, looser: it says the step was there, not that it said the right thing).
    * step support: share of steps that have at least one gold action inside the span whose words the step contains. A step with none is either
      invented, mistimed or about something the labeller did not list: look at it by hand before calling it wrong."""
    timed = [s for s in sl.steps if s.video_start_s is not None and s.video_end_s is not None]
    core = [(g, t, x) for g, t, x in covered_actions(sl, gold) if g.importance == "core"]
    supported = 0
    for s in timed:
        near = [g for g in gold.steps if s.video_start_s - TIME_TOL_S <= g.t_start <= s.video_end_s + TIME_TOL_S]
        supported += any(similarity(_step_text(s), g.goal) >= TEXT_MIN for g in near)
    return {"gold_actions": len(gold.steps), "gold_core": len(core),
            "text_recall_core": round(sum(x for _, _, x in core) / len(core), 3) if core else None,
            "time_recall_core": round(sum(t for _, t, _ in core) / len(core), 3) if core else None,
            "step_support": round(supported / len(timed), 3) if timed else None}


def accuracy(sl: StepList, gold: GoldSet | None) -> dict:
    """Recall, precision and timestamp accuracy against a human gold file; all None without one.
    `core_recall` and `precision` are the strict one-to-one match of ingestion/eval/metrics.py: one step can match only ONE gold action, so with
    fewer steps than gold actions they are capped by the step count. The coverage numbers are the ones to read."""
    if gold is None:
        return {"gold": False, "core_recall": None, "precision": None, "timestamp_accuracy": None, "state_recall": None,
                "text_recall_core": None, "time_recall_core": None, "step_support": None}
    r = evaluate(gold, sl)
    return {"gold": True, "core_recall": round(r.core_recall, 3), "precision": round(r.precision, 3),
            "timestamp_accuracy": None if r.timestamp_accuracy is None else round(r.timestamp_accuracy, 3),
            "state_recall": None if r.state_recall is None else round(r.state_recall, 3), **coverage(sl, gold)}


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
    keys = ("checkable_end_state", "with_how_to", "with_check", "with_time", "with_feature_id", "flags_per_step", "video_covered",
            "text_recall_core", "time_recall_core", "step_support")
    out = {}
    for app, rs in by.items():
        out[app] = {"runs": len(rs), "steps": sum(r["steps"] for r in rs)}
        for k in keys:
            v = [r[k] for r in rs if r.get(k) is not None]
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
