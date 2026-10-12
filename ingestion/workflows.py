"""Saved, person-reviewed workflows, and normalisation of manually entered step lists.

A reviewed workflow is only ever served if (a) a named person approved it, (b) every step says review_status='reviewed', and
(c) the user's Blender version is known and inside the range the reviewer declared. The store starts EMPTY: the hand-written
example files in shared/examples are fixtures, not reviewed workflows, and are not loaded here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from shared.step_record import StepList

from .catalog import parse_version
from .profiles import BLENDER
from .validate import ValidationFailure, check_structure, sanitize_and_annotate


def op_key(op_ids: list[str]) -> str:
    return "op:" + "+".join(sorted(op_ids))


def text_key(text: str) -> str:
    norm = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
    return "text:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


class ReviewedWorkflowStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _path(self, key: str) -> Path:
        return self.dir / (re.sub(r"[^a-z0-9.+_-]+", "_", key.lower()) + ".json")

    def save(self, key: str, steplist: StepList, *, reviewed_by: str, min_version: str = "2.80", max_version: str | None = None) -> Path:
        if not reviewed_by.strip():
            raise ValueError("a reviewed workflow needs the name of the person who reviewed it")
        if not all(s.review_status == "reviewed" for s in steplist.steps):
            raise ValueError("every step must have review_status='reviewed' before it can be stored as a reviewed workflow")
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self._path(key)
        p.write_text(json.dumps({
            "key": key, "reviewed_by": reviewed_by, "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "min_version": min_version, "max_version": max_version,
            "steplist": json.loads(steplist.model_dump_json()),
        }, indent=1), encoding="utf-8")
        return p

    def find(self, key: str, version: str | None) -> StepList | None:
        p = self._path(key)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        v = parse_version(version)
        lo, hi = parse_version(d.get("min_version")), parse_version(d.get("max_version"))
        if v is None or (lo and v < lo) or (hi and v > hi):
            return None      # unknown or out-of-range version: do not claim a reviewed workflow fits
        sl = StepList.model_validate(d["steplist"])
        if not d.get("reviewed_by") or not all(s.review_status == "reviewed" for s in sl.steps):
            return None
        for s in sl.steps:
            s.provenance = "reviewed_workflow"
            s.source_refs = [*s.source_refs, f"reviewed:{key} by {d['reviewed_by']}"]
        sl.source_type = "manual" if sl.source_type == "manual" else sl.source_type
        return sl


def normalise_manual_steps(obj: str | dict, version: str | None = None) -> tuple[StepList, list[str]]:
    """Validate and annotate a manually entered step list (JSON text or dict) against the shared schema. Returns (steplist,
    notes). Raises ValidationFailure / pydantic ValidationError on malformed input; nothing is repaired silently."""
    data = json.loads(obj) if isinstance(obj, str) else obj
    sl = StepList.model_validate(data)
    sl.source_type = "manual"
    sl.app_version_tutorial = sl.app_version_tutorial or version
    for s in sl.steps:
        s.provenance = s.provenance or "user_text"
    notes: list[str] = []
    sanitize_and_annotate(sl, BLENDER, sl.video_duration_s)
    check_structure(sl, sl.video_duration_s)
    n_unv = sum(1 for s in sl.steps if not s.verifiable)
    if n_unv:
        notes.append(f"{n_unv} of {len(sl.steps)} steps have no checkable expected state and will be guided but not verified")
    return sl, notes
