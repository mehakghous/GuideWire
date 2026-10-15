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
from .validate import check_structure, sanitize_and_annotate


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


# ----------------------------------------------------------------------------- human review: list, edit, promote (GW-012)
DEFAULT_STORE = Path(__file__).resolve().parents[1] / "knowledge" / "reviewed"


def load_steplist(path: str | Path) -> StepList:
    """A step list from a JSON file: either the list itself or an answer bundle (`cli ask` output) that holds one."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return StepList.model_validate(d["steps"] if isinstance(d.get("steps"), dict) else d)


def edit_steps(sl: StepList, *, goals: dict[int, str] | None = None, remove: set[int] | None = None, moves: list[tuple[int, int]] | None = None) -> StepList:
    """A reviewer's edits, as a NEW step list (the input is untouched). Numbers are 1-based positions.
    `goals` and `remove` use the numbering of the list you were shown; `moves` (from, to) are applied one after another to the result.
    Step ids never change, `order` is renumbered 1..n, and a step may not end up before a step it depends on."""
    goals, remove, moves = goals or {}, remove or set(), moves or []
    n = len(sl.steps)
    for k in [*goals, *remove]:
        if not 1 <= k <= n:
            raise ValueError(f"there is no step {k}; this list has {n} steps")
    steps = [s.model_copy(deep=True) for s in sl.steps]
    for k, text in goals.items():
        if not text.strip():
            raise ValueError(f"step {k}: the new goal is empty")
        steps[k - 1].goal = text.strip()
    kept = [s for i, s in enumerate(steps, 1) if i not in remove]
    if not kept:
        raise ValueError("removing these would leave no steps")
    for a, b in moves:
        if not (1 <= a <= len(kept) and 1 <= b <= len(kept)):
            raise ValueError(f"cannot move step {a} to position {b}; the list now has {len(kept)} steps")
        kept.insert(b - 1, kept.pop(a - 1))
    ids_before = {}
    for i, s in enumerate(kept, 1):
        s.order = i
        s.depends_on = [d for d in s.depends_on if d in {x.id for x in kept}]       # a removed step is no longer a dependency
        ids_before[s.id] = i
    for s in kept:
        late = [d for d in s.depends_on if ids_before[d] >= s.order]
        if late:
            raise ValueError(f"step {s.order} ({s.id}) would come before {', '.join(late)}, which it depends on")
    out = sl.model_copy(update={"steps": kept})
    check_structure(out, out.video_duration_s)
    return out


def promote(store: ReviewedWorkflowStore, key: str, sl: StepList, *, reviewed_by: str, min_version: str = "2.80", max_version: str | None = None) -> Path:
    """Store a step list as a reviewed workflow. Marking steps 'reviewed' is the reviewer's explicit act, so it only happens here and only with a name."""
    if not reviewed_by.strip():
        raise ValueError("promoting needs the name of the person who reviewed the steps (--by)")
    check_structure(sl, sl.video_duration_s)
    done = sl.model_copy(update={"steps": [s.model_copy(update={"review_status": "reviewed"}) for s in sl.steps]})
    return store.save(key, done, reviewed_by=reviewed_by, min_version=min_version, max_version=max_version)


def entries(store: ReviewedWorkflowStore) -> list[dict]:
    """One summary row per stored reviewed workflow (newest first)."""
    rows = []
    for p in sorted(store.dir.glob("*.json")) if store.dir.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        sl = d["steplist"]
        rows.append({"key": d["key"], "app": sl.get("app"), "steps": len(sl["steps"]), "reviewed_by": d["reviewed_by"], "reviewed_at": d["reviewed_at"],
                     "min_version": d.get("min_version"), "max_version": d.get("max_version"), "title": sl.get("title")})
    return sorted(rows, key=lambda r: r["reviewed_at"], reverse=True)
