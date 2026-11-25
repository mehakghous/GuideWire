"""Editing a step list: change a step's text, reorder, delete, add, then save. No Qt in here, so it is fully testable.

Rules the editor keeps (the shared step contract needs them):
  - `order` is always 1..n with no gaps, renumbered after every change;
  - step ids stay unique, and a new step never reuses a deleted id;
  - deleting a step removes it from other steps' `depends_on`, so nothing points at a step that no longer exists;
  - a step the user edited or added is marked review_status="reviewed"; untouched steps keep their status;
  - display groups (schema 0.12: consecutive steps share one group_id and one label) stay valid: a step moved INTO the middle of a group, or added there, joins that group;
    a step moved away from its group leaves it (it never splits a group in two); deleting steps never leaves a group fragmented;
  - every change can be undone (`undo`), back to the moment the tutorial was opened or last saved; the title can be changed (`set_title`);
  - nothing is written until `save()`, and `save()` refuses an empty list or an empty goal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shared.step_record import Step, StepList

from .db import Database
from .step_validation import TextRefused, analyse, check_text


class EditError(Exception):
    pass


class StepEditor:
    def __init__(self, steps: StepList, *, tutorial_id: int | None = None, title: str | None = None):
        self.steps = steps.model_copy(deep=True)
        self.tutorial_id = tutorial_id
        self.title = title or steps.title or "Untitled tutorial"
        self.dirty = False
        self._used_ids = {s.id for s in self.steps.steps}
        self._history: list[tuple[StepList, str, bool]] = []          # (steps, title, dirty) before each change, newest last

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

    # ---- undo
    MAX_UNDO = 50

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    def _remember(self) -> None:
        """Called before a change is made: the state to come back to."""
        self._history.append((self.steps.model_copy(deep=True), self.title, self.dirty))
        del self._history[:-self.MAX_UNDO]

    def undo(self) -> bool:
        """Take back the last change. Returns False when there is nothing to undo."""
        if not self._history:
            return False
        self.steps, self.title, self.dirty = self._history.pop()
        return True

    def set_title(self, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            raise EditError("The tutorial needs a title.")
        if len(text) > 120:
            raise EditError("Keep the title under 120 characters.")
        if text != self.title:
            self._remember()
            self.title = text
            self.dirty = True

    # ---- changing
    def _renumber(self, changed: Step | None = None) -> None:
        """`changed` is the step that was moved or added: it is the only step whose group can change."""
        for i, s in enumerate(self.steps.steps, start=1):
            s.order = i
        self._settle_groups(changed)
        self.dirty = True

    def _settle_groups(self, changed: Step | None) -> None:
        """Keep every display group ONE run of consecutive steps (see StepList.group_problems).

        The step that was moved or added joins a group when it now sits inside one (between two steps of the same group) and leaves its own group when it
        no longer touches it. Nothing else changes group. If anything is still fragmented (it should not be), the longest run of a group stays and the others are let go."""
        lst = self.steps.steps
        if changed is not None:
            i = next(k for k, x in enumerate(lst) if x is changed)
            before, after = (lst[i - 1] if i > 0 else None), (lst[i + 1] if i + 1 < len(lst) else None)
            if before and after and before.group_id and before.group_id == after.group_id:
                changed.group_id, changed.group = before.group_id, before.group
            elif changed.group_id and not ((before and before.group_id == changed.group_id) or (after and after.group_id == changed.group_id)):
                changed.group_id = changed.group = None
        runs: dict[str, list[tuple[int, int]]] = {}
        i = 0
        while i < len(lst):
            gid = lst[i].group_id
            j = i
            while gid and j + 1 < len(lst) and lst[j + 1].group_id == gid:
                j += 1
            if gid:
                runs.setdefault(gid, []).append((i, j))
            i = j + 1
        for spans in runs.values():
            keep = max(spans, key=lambda ab: (ab[1] - ab[0], -ab[0]))
            for a_, b_ in spans:
                if (a_, b_) != keep:
                    for st in lst[a_:b_ + 1]:
                        st.group_id = st.group = None

    def edit_goal(self, step_id: str, text: str) -> None:
        s = self.steps.steps[self._index(step_id)]
        try:
            text = check_text(text, [x.goal for x in self.steps.steps if x.id != step_id])
        except TextRefused as e:
            raise EditError(str(e)) from None
        if s.goal != text:
            self._remember()
            s.goal = text
            s.review_status = "reviewed"
            self.dirty = True

    def move(self, step_id: str, delta: int) -> None:
        """Move a step up (delta < 0) or down (delta > 0); stops at the ends."""
        i = self._index(step_id)
        j = max(0, min(len(self) - 1, i + delta))
        if i != j:
            self._remember()
            lst = self.steps.steps
            lst.insert(j, lst.pop(i))
            lst[j].review_status = "reviewed"
            self._renumber(lst[j])

    def delete(self, step_id: str) -> None:
        i = self._index(step_id)
        self._remember()
        del self.steps.steps[i]
        for s in self.steps.steps:
            if step_id in s.depends_on:
                s.depends_on = [d for d in s.depends_on if d != step_id]
        self._renumber()

    def _new_id(self) -> str:
        n = 1 + max([int(m.group(1)) for sid in self._used_ids if (m := re.fullmatch(r"s(\d+)", sid))] or [0])
        return f"s{n:02d}"

    def add(self, text: str, *, after: str | None = None) -> str:
        """Add a step after `after` (or at the end). Returns the new step id.

        The text must pass the hard rules (see app/step_validation.py). If the catalog parser recognises the instruction, the new step gets
        its actions and expected state, so the session engine can check it; otherwise it is a manual step carrying a flag that says so."""
        try:
            text = check_text(text, self.goals())
        except TextRefused as e:
            raise EditError(str(e)) from None
        pos = len(self) if after is None else self._index(after) + 1
        self._remember()
        sid = self._new_id()
        self._used_ids.add(sid)
        a = analyse(text, self.steps.app)
        base = a.step.model_dump() if a.recognised and a.step is not None else {}
        data = {**base, "id": sid, "order": 1, "goal": text, "review_status": "reviewed", "provenance": "user_text", "flags": a.flags,
                "confidence": base.get("confidence", 1.0) if base else 1.0}
        new_step = Step.model_validate(data)
        self.steps.steps.insert(pos, new_step)
        self._renumber(new_step)
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
        self._history.clear()                                       # what is saved is saved: undo goes back to here, not past it
        return self.tutorial_id
