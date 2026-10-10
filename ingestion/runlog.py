"""Opt-in JSONL run log: one line per extraction attempt, raw model response included.

Usage:  log = RunLog("runs/2026-10-10.jsonl");  extract_from_video(..., on_attempt=log)
Raw responses contain tutorial-derived content but no secrets. Keep the directory out of git
(`runs/` is git-ignored) and delete derived YouTube data within 30 days (Proposal §4.f).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RunLog:
    def __init__(self, path: str | Path, **context: Any):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.context = context  # e.g. run_id, arm, video_id

    def __call__(self, rec: dict[str, Any]) -> None:
        line = {"ts": time.time(), **self.context, **rec}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
