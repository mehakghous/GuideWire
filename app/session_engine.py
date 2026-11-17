"""Session engine: a small state machine that walks one user through one saved tutorial and stores progress in the database.

States:   not_started  ->  active (step N)  ->  finished
Per step: pending | done | skipped      (and who said so: "user" or "observed")

Rules:
  - only the owner of the tutorial can run a session on it;
  - `complete`, `skip` and `back` are only valid while a session is active; everything else raises EngineError;
  - a step is marked done by the user, or by `auto_check` when the observed application state satisfies its expected state;
    a step that cannot be checked (no expected state, craft step, or an unknown predicate kind) is never completed automatically;
  - progress is written to the database after every change, so a session survives closing the app (`SessionEngine.load`).
"""
from __future__ import annotations

from typing import Any

from ingestion.evaluator import Verdict, evaluate_step
from shared.step_record import Step

from .db import Database, now

NOT_STARTED, ACTIVE, FINISHED = "not_started", "active", "finished"
PENDING, DONE, SKIPPED = "pending", "done", "skipped"


class EngineError(Exception):
    pass


class SessionEngine:
    def __init__(self, db: Database, user_id: int, session_id: int):
        row = db.get_session(session_id)
        if row is None or row["user_id"] != user_id:
            raise EngineError("session not found")
        self.db, self.user_id, self.session_id = db, user_id, session_id
        self.steps: list[tuple[int, Step]] = db.get_steps(row["tutorial_id"])     # (step row id, Step), in order
        self.app: str = db.tutorial_app(row["tutorial_id"]) or "blender"          # which application this tutorial is for

    # ---- creating / resuming
    @classmethod
    def create(cls, db: Database, user_id: int, tutorial_id: int) -> "SessionEngine":
        try:
            sid = db.start_session(user_id, tutorial_id)
        except KeyError as e:
            raise EngineError(str(e)) from None
        return cls(db, user_id, sid)

    @classmethod
    def load(cls, db: Database, user_id: int, session_id: int) -> "SessionEngine":
        return cls(db, user_id, session_id)

    # ---- reading
    @property
    def _row(self):
        return self.db.get_session(self.session_id)

    @property
    def state(self) -> str:
        return self._row["state"]

    @property
    def position(self) -> int | None:
        """1-based number of the active step, or None when not active."""
        return self._row["current_pos"] if self.state == ACTIVE else None

    def current_step(self) -> Step | None:
        p = self.position
        return None if p is None else self.steps[p - 1][1]

    def statuses(self) -> list[str]:
        by_id = {r["step_id"]: r["status"] for r in self.db.session_steps(self.session_id)}
        return [by_id[sid] for sid, _ in self.steps]

    def progress(self) -> tuple[int, int]:
        """(steps finished with, total): done and skipped both count as dealt with."""
        st = self.statuses()
        return sum(1 for s in st if s != PENDING), len(st)

    # ---- transitions
    def _need_active(self) -> int:
        if self.state != ACTIVE:
            raise EngineError(f"session is {self.state}, not active")
        return int(self._row["current_pos"])

    def start(self) -> None:
        if self.state != NOT_STARTED:
            raise EngineError(f"session is already {self.state}")
        if not self.steps:
            raise EngineError("this tutorial has no steps")
        self.db.update_session(self.session_id, state=ACTIVE, current_pos=1, started_at=now())

    def _close_current(self, status: str, by: str) -> None:
        pos = self._need_active()
        self.db.set_step_status(self.session_id, self.steps[pos - 1][0], status, by)
        if pos >= len(self.steps):
            self.db.update_session(self.session_id, state=FINISHED, current_pos=pos, finished_at=now())
        else:
            self.db.update_session(self.session_id, state=ACTIVE, current_pos=pos + 1)

    def complete(self, by: str = "user") -> None:
        self._close_current(DONE, by)

    def skip(self) -> None:
        self._close_current(SKIPPED, "user")

    def back(self) -> None:
        """Return to the previous step to redo it (it becomes pending again)."""
        pos = self._need_active()
        if pos <= 1:
            raise EngineError("already at the first step")
        self.db.set_step_status(self.session_id, self.steps[pos - 2][0], PENDING, "user")
        self.db.update_session(self.session_id, state=ACTIVE, current_pos=pos - 1)

    # ---- checking against what the application shows
    def check(self, observed: dict[str, Any]) -> Verdict | None:
        """Compare the active step with an observed application state. Changes nothing."""
        step = self.current_step()
        return None if step is None else evaluate_step(step, observed)

    def auto_check(self, observed: dict[str, Any]) -> bool:
        """Complete the active step if (and only if) every part of its expected state is observed to hold. Returns True if it advanced."""
        v = self.check(observed)
        if v is None or v.status != "met" or v.unobservable:
            return False
        self.complete(by="observed")
        return True
