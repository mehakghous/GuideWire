"""Editing a step list: change a step's text, reorder, delete, add, then save. No Qt in here, so it is fully testable.

Rules the editor keeps (the shared step contract needs them):
  - `order` is always 1..n with no gaps, renumbered after every change;
  - step ids stay unique, and a new step never reuses a deleted id;
  - deleting a step removes it from other steps' `depends_on`, so nothing points at a step that no longer exists;
  - a step the user edited or added is marked review_status="reviewed"; untouched steps keep their status;
  - nothing is written until `save()`, and `save()` refuses an empty list or an empty goal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shared.step_record import Step, StepList

from .db import Database


class EditError(Exception):
    pass


class StepEditor:
    def __init__(self, steps: StepList, *, tutorial_id: int | None = None, title: str | None = None):
        self.steps = steps.model_copy(deep=True)
        self.tutorial_id = tutorial_id
        self.title = title or steps.title or "Untitled tutorial"
        self.dirty = False
        self._used_ids = {s.id for s in self.steps.steps}

    # ---- loading
    @classmethod
    def from_json_file(cls, path: str | Path) -> "StepEditor":
        """The fake step file used until the real pipeline output is wired in."""
        return cls(StepList.model_validate(json.loads(Path(path).read_text(encoding="utf-8"))))

    @classmethod
    def from_db(cls, db: Database, user_id: int, tutorial_id: int) -> "StepEditor":
        row = next((r for r in db.list_tutorials(user_id) if r["id"] == tutorial_id), None)
        if row is None:
            raise KeyError(f"tutorial {tutorial_id} not found for this user")
        stored = db.get_steps(tutorial_id)
        sl = StepList(source_type=row["source_type"], app=row["app"], title=row["title"], steps=[s for _, s in stored])
        return cls(sl, tutorial_id=tutorial_id, title=row["title"])

    # ---- reading
    def __len__(self) -> int:
        return len(self.steps.steps)

    def goals(self) -> list[str]:
        return [s.goal for s in self.steps.steps]

    def _index(self, step_id: str) -> int:
        for i, s in enumerate(self.steps.steps):
            if s.id == step_id:
                return i
        raise EditError(f"no step with id {step_id!r}")

    # ---- changing
    def _renumber(self) -> None:
        for i, s in enumerate(self.steps.steps, start=1):
            s.order = i
        self.dirty = True

    def edit_goal(self, step_id: str, text: str) -> None:
        text = text.strip()
        if not text:
            raise EditError("A step needs some text.")
        s = self.steps.steps[self._index(step_id)]
        if s.goal != text:
            s.goal = text
            s.review_status = "reviewed"
            self.dirty = True

    def move(self, step_id: str, delta: int) -> None:
        """Move a step up (delta < 0) or down (delta > 0); stops at the ends."""
        i = self._index(step_id)
        j = max(0, min(len(self) - 1, i + delta))
        if i != j:
            lst = self.steps.steps
            lst.insert(j, lst.pop(i))
            lst[j].review_status = "reviewed"
            self._renumber()

    def delete(self, step_id: str) -> None:
        i = self._index(step_id)
        del self.steps.steps[i]
        for s in self.steps.steps:
            if step_id in s.depends_on:
                s.depends_on = [d for d in s.depends_on if d != step_id]
        self._renumber()

    def _new_id(self) -> str:
        n = 1 + max([int(m.group(1)) for sid in self._used_ids if (m := re.fullmatch(r"s(\d+)", sid))] or [0])
        return f"s{n:02d}"

    def add(self, text: str, *, after: str | None = None) -> str:
        """Add a step after `after` (or at the end). Returns the new step id."""
        text = text.strip()
        if not text:
            raise EditError("A step needs some text.")
        sid = self._new_id()
        self._used_ids.add(sid)
        step = Step(id=sid, order=1, goal=text, review_status="reviewed", provenance="user_text", support="unknown", confidence=1.0)
        pos = len(self) if after is None else self._index(after) + 1
        self.steps.steps.insert(pos, step)
        self._renumber()
        return sid

    # ---- saving
    def save(self, db: Database, user_id: int) -> int:
        """Write the list to the database (a new tutorial, or replace the steps of the open one). Returns the tutorial id."""
        if not self.steps.steps:
            raise EditError("A tutorial needs at least one step.")
        if any(not s.goal.strip() for s in self.steps.steps):
            raise EditError("Every step needs some text.")
        self.tutorial_id = db.save_tutorial(user_id, self.title, self.steps, source_type=self.steps.source_type, tutorial_id=self.tutorial_id)
        self.dirty = False
        return self.tutorial_id
