"""Collect public quality signals for tutorial videos: counters, and the text of top comments, into runs/signals/ (git-ignored).

    python scripts/youtube_signals.py VIDEO_ID [VIDEO_ID ...]

Quota: 1 unit for all counters plus 1 unit per video for comments. The comment text is YouTube-derived data written by strangers: it stays under runs/ (the 30-day purge
covers it), carries no author or id, and only counts and themes go into documents. Nothing in a comment is ever treated as an instruction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.youtube import api  # noqa: E402


def main(ids: list[str]) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    stats = api.video_statistics(ids)
    out_dir = ROOT / "runs" / "signals"
    out_dir.mkdir(parents=True, exist_ok=True)
    for vid in ids:
        rec = {"video_id": vid, "statistics": stats.get(vid), "comments": api.top_comments(vid, max_results=100)}
        (out_dir / f"{vid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        n = rec["comments"]
        print(vid, rec["statistics"], "comments saved:", "disabled" if n is None else len(n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else 2)
