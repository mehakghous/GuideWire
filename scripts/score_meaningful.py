"""Score extracted step lists for MEANINGFUL steps against the human labels (eval_data/gold). Offline: reads recorded runs, calls no model.

    python scripts/score_meaningful.py runs/compare/gemini-3.6-flash/v10-preds_w0 runs/compare/gemini-3.6-flash/v11_w0 ...

The labels list every small action a person saw, so a good step usually covers several of them. Per run directory, mean over its videos:
  steps              how many steps
  words_found        share of CORE labelled actions inside some step's time span whose words that step contains (phase1.coverage; longer steps find words more
                     easily, so read it with `steps` and `step_support`)
  step_support       share of steps that match at least one labelled action (a step with none is invented, mistimed or about something not labelled)
  actions_per_step   core labelled actions covered, per step: how much one step carries
  enabling_only      share of steps that only switch a mode, view or layout, select something or open something, with nothing else to do (heuristic on the goal
                     and how_to; the "micro-step" pattern)
  leaked             example names from earlier prompts found in the steps but not in the labels (copied from the prompt, not read from the video)
  with_why           share of steps that give the instructor's reason (v11 only; earlier prompts had no field for it)
  long_steps         steps spanning more than 120 s (a sign of steps merged across stages)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.eval import phase1  # noqa: E402
from shared.step_record import StepList  # noqa: E402

LEAKED = ("Target Pattern", "Component Source", "FK Transform", "jnt_L_hip", "l_switch_GEO", "FK_IK_Switch", "leftHip")
_ENABLING_GOAL = re.compile(r"^(switch|enter|go back|go to|return|change to|select|open|maximi[sz]e|expand|activate|choose the .* tool|press (tab|f|spacebar|space))\b", re.I)
_SUBSTANCE = re.compile(r"\b(add|create|extrude|rename|name|set|type|enter '|parent|connect|mirror|bind|apply|constrain|delete|duplicate|move|rotate|scale|draw|place|paint)\b", re.I)


def enabling_only(st) -> bool:
    """A step whose whole content is getting ready: a mode/view switch, a selection or opening something, with no operation that changes the result."""
    if not _ENABLING_GOAL.match(st.goal.strip()):
        return False
    rest = " ".join([st.goal.split(" to ", 1)[-1] if " to " in st.goal else "", *(h.text for h in st.how_to)])
    return not _SUBSTANCE.search(rest)


def leaked(sl: StepList, gold_text: str) -> int:
    text = " ".join([s.goal + " " + " ".join(h.text for h in s.how_to) for s in sl.steps])
    return sum(text.count(x) for x in LEAKED if x not in gold_text)


def score_file(path: Path) -> dict:
    sl = StepList.model_validate_json(path.read_text(encoding="utf-8"))
    gold = phase1.load_gold(ROOT / "eval_data" / "gold", sl.video_id)
    gold_text = (ROOT / "eval_data" / "gold" / f"{sl.video_id}.gold.json").read_text(encoding="utf-8") if gold else ""
    cov = phase1.coverage(sl, gold) if gold else {}
    core_found = round((cov.get("text_recall_core") or 0) * (cov.get("gold_core") or 0))
    n = len(sl.steps) or 1
    return {"video": f"{sl.app}_{sl.video_id}", "steps": len(sl.steps), "words_found": cov.get("text_recall_core"), "step_support": cov.get("step_support"),
            "actions_per_step": round(core_found / n, 2), "enabling_only": round(sum(enabling_only(s) for s in sl.steps) / n, 3), "leaked": leaked(sl, gold_text),
            "with_why": round(sum(bool(getattr(s, "why", None)) for s in sl.steps) / n, 3),
            "long_steps": sum(1 for s in sl.steps if s.video_start_s is not None and s.video_end_s is not None and s.video_end_s - s.video_start_s > 120)}


KEYS = ("steps", "words_found", "step_support", "actions_per_step", "enabling_only", "leaked", "with_why", "long_steps")


def main(argv: list[str]) -> int:
    verbose = "-v" in argv
    dirs = [Path(a) for a in argv if a != "-v"]
    print("run".ljust(34), *(k.rjust(16) for k in KEYS))
    for d in dirs:
        rows = [score_file(p) for p in sorted(d.glob("*.json"))]
        if not rows:
            continue
        if verbose:
            for r in rows:
                print(("  " + r["video"]).ljust(34), *(str(r[k]).rjust(16) for k in KEYS))
        mean = {k: round(sum((r[k] or 0) for r in rows) / len(rows), 3) for k in KEYS}
        print(f"{d.parent.name}/{d.name} ({len(rows)})".ljust(34), *(str(mean[k]).rjust(16) for k in KEYS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
