"""Try the label repair (ingestion/label_repair.py) on recorded Houdini runs and print every decision, for judging against the human labels.

    python scripts/repair_labels_eval.py runs/compare/gemini-3.6-flash/v13_w0 ... [--dry-run]

For each run directory, every houdini_*.json is loaded, the steps with a parameter label Houdini does not have on that node get one second look each (through the cost guard), and the repaired
copy is written to <run dir>_fix/ (the recorded run is never changed). --dry-run only counts the flagged labels and calls nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion import houdini_parms as hp  # noqa: E402
from ingestion.label_repair import repair_labels  # noqa: E402
from shared.step_record import StepList  # noqa: E402


def provider():
    from dotenv import load_dotenv

    from ingestion.budget import BudgetedProvider, api_key_for
    from ingestion.providers.gemini import GeminiProvider
    load_dotenv()
    return BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model="gemini-3.6-flash"), label="default")


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    dirs = [Path(a) for a in argv if not a.startswith("--")]
    p = None if dry else provider()
    total = 0
    for d in dirs:
        for f in sorted(d.glob("houdini_*.json")):
            sl = StepList.model_validate_json(f.read_text(encoding="utf-8"))
            flagged = [(s.order, lab) for s in sl.steps for lab, _ in hp.unknown_labels(s)]
            total += len(flagged)
            if dry:
                print(f"{d.name}/{f.name}: {flagged}")
                continue
            for r in repair_labels(p, sl, sl.video_id or "", sl.video_duration_s):
                print(f"{d.name:14} {sl.video_id} {r.step_id}  '{r.wrong}' on {r.node} -> {r.label or '(kept: ' + r.reason + ')'}   | {r.evidence[:90]}")
            out = d.parent / (d.name + "_fix")
            out.mkdir(exist_ok=True)
            (out / f.name).write_text(sl.model_dump_json(indent=1), encoding="utf-8")
    print(f"{total} flagged labels" + ("" if dry else f"; {p.calls} paid call(s), {p.hits} cache hit(s), about ${p.run_usd:.4f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
