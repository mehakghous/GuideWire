"""30-day rule for data derived from YouTube (SRS SEC-08, CI-8): delete run logs, cached extractions and cached captions older than the limit.
Age is the file's modified time. runs/ledger*.json is NOT touched: it enforces the spend limit, and deleting it would reset the budget."""
from __future__ import annotations

import time
from pathlib import Path

TTL_DAYS = 30
# (directory, glob) pairs; relative to the repo root
TARGETS = (("runs", "*.jsonl"), ("runs/cache", "*.json"), ("runs/incomplete", "*.json"), ("local_data/captions", "*.json"))


def purge_derived(root: Path, *, days: int = TTL_DAYS, now: float | None = None, targets=TARGETS) -> list[str]:
    cutoff = (now if now is not None else time.time()) - days * 86400
    removed = []
    for d, pattern in targets:
        for f in (root / d).glob(pattern):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed.append(f.relative_to(root).as_posix())
    return removed
