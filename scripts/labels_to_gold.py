"""Turn the human label sheets into gold files the Phase 1 report reads.

    python scripts/labels_to_gold.py            # every sheet in eval_data/labels/<video id>.<annotator>.csv that has rows and passes the checks

Reads the manifest (title, length, application), validates each sheet with ingestion.eval.labels, and writes eval_data/gold/<video id>.gold.json.
A sheet with problems is reported and skipped, never repaired. Only sheets with the annotator named `ayesha` are used for a video's gold file
(a second annotator's sheet is for agreement, not for scoring).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.eval.labels import load_csv  # noqa: E402


def main() -> int:
    manifest = json.loads((ROOT / "eval_data" / "labels" / "manifest.json").read_text(encoding="utf-8"))
    out_dir = ROOT / "eval_data" / "gold"
    out_dir.mkdir(exist_ok=True)
    written = 0
    for v in manifest["videos"]:
        sheet = ROOT / "eval_data" / "labels" / f"{v['video_id']}.ayesha.csv"
        if not sheet.exists():
            continue
        try:
            g, pr = load_csv(sheet, duration_s=v["duration_s"], video_id=v["video_id"], title=v.get("title"), annotator="ayesha", app_version=v.get("app_version"))
        except UnicodeDecodeError:
            print(f"skip {sheet.name}: not saved as UTF-8 (in Excel: Save As, CSV UTF-8)")
            continue
        if g is None:
            if "the sheet has no rows" not in pr.errors:
                print(f"skip {sheet.name}: " + "; ".join(pr.errors[:3]))
            continue
        g.app = v.get("app", "blender")
        (out_dir / f"{v['video_id']}.gold.json").write_text(g.model_dump_json(indent=1), encoding="utf-8")
        print(f"wrote eval_data/gold/{v['video_id']}.gold.json: {len(g.steps)} actions ({g.app})")
        written += 1
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
