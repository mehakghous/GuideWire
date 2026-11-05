"""Small structured session state for tutorial follow-ups. No history is kept beyond a few compact turn summaries.

What it holds, and why each piece is needed to resolve "Why?", "Continue" or "that didn't work":
  - the procedure (StepList) and where it came from (tutorial metadata), so a follow-up never attaches to the wrong source;
  - per-step status (pending / done / skipped / failed) AND who said so (user report vs observed state);
  - the current step pointer;
  - the user's Blender version and the last observed application state (if any adapter supplies it);
  - `active`: False after the user changes task, so later short messages are not pinned on an abandoned tutorial.
Rules that tests pin: asking about a step never completes it; loading a new procedure resets everything; observed state is stored as a
verification on the step but only the user (or an explicit confirmation) marks a step done.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from shared.answer import AnswerBundle
from shared.step_record import Step, StepList, StepVerification

from .evaluator import evaluate_step
from .features import APPS

Status = str   # "pending" | "done" | "skipped" | "failed"
MAX_TURNS = 6


def human_state(kind: str, target: str) -> str:
    if kind == "mode":
        return {"OBJECT": "Object Mode", "EDIT_MESH": "Edit Mode"}.get(target, target.replace("_", " ").title())
    return f"{kind}={target}"


@dataclass
class TurnNote:
    user: str
    intent: str
    route: str
    step: str | None = None


@dataclass
class Session:
    version: str | None = None
    app: str = "blender"                    # blender | maya | houdini: which application the user is working in
    observed: dict | None = None
    tutorial: dict | None = None            # id, title, url, version_hint, source_type: carried from the selected tutorial
    steps: StepList | None = None
    status: dict[str, Status] = field(default_factory=dict)
    status_by: dict[str, str] = field(default_factory=dict)   # step id -> "user" | "observed"
    current: str | None = None
    active: bool = False
    task: str | None = None
    turns: deque = field(default_factory=lambda: deque(maxlen=MAX_TURNS))
    corrections: list[str] = field(default_factory=list)

    # ---- loading / switching: always a clean slate, so two tutorials never mix
    def load(self, steps: StepList | AnswerBundle, *, tutorial: dict | None = None, version: str | None = None, task: str | None = None) -> "Session":
        sl = steps.steps if isinstance(steps, AnswerBundle) else steps
        if sl is None or not sl.steps:
            raise ValueError("nothing to follow: the procedure has no steps")
        if tutorial is None and isinstance(steps, AnswerBundle) and sl.source_type in ("transcript", "youtube"):
            # only a procedure BUILT FROM a tutorial is "the tutorial". Catalog and written procedures also cite a tutorial video (as documentation
            # that confirms a behaviour) and a manual page; neither makes pasted instructions "that tutorial"
            s0 = next((x for x in steps.sources if x.kind == "tutorial_video"), None)
            if s0 is not None:
                tutorial = {"title": s0.title, "url": s0.url, "version_hint": s0.version, "source_type": sl.source_type}
        self.steps = sl.model_copy(deep=True)
        self.app = sl.app
        # NOT sl.app_version_tutorial: for pasted instructions that field holds the USER's own version, which would turn into
        # "the tutorial was recorded for Blender <your version>". A recorded version only ever comes from a tutorial source.
        self.tutorial = tutorial or {"title": sl.title, "source_type": sl.source_type, "version_hint": None}
        self.status = {s.id: "pending" for s in self.steps.steps}
        self.status_by, self.turns, self.corrections = {}, deque(maxlen=MAX_TURNS), []
        self.current = self.steps.steps[0].id
        self.active, self.task = True, task
        if version:
            self.version = version
        return self

    # ---- queries
    def step(self, sid: str | None) -> Step | None:
        return next((s for s in (self.steps.steps if self.steps else []) if s.id == sid), None)

    @property
    def current_step(self) -> Step | None:
        return self.step(self.current)

    def index(self, sid: str) -> int:
        return next(i for i, s in enumerate(self.steps.steps) if s.id == sid)

    def previous_step(self) -> Step | None:
        if not self.steps or self.current is None:
            return None
        i = self.index(self.current)
        return self.steps.steps[i - 1] if i > 0 else None

    def pending_from_current(self) -> list[Step]:
        if not self.steps or self.current is None:
            return []
        return [s for s in self.steps.steps[self.index(self.current):] if self.status[s.id] in ("pending", "failed")]

    # ---- changes (each one is a deliberate user action, never a side effect of a question)
    def _advance(self) -> None:
        i = self.index(self.current)
        nxt = next((s for s in self.steps.steps[i + 1:] if self.status[s.id] in ("pending", "failed")), None)
        self.current = nxt.id if nxt else self.current

    def mark(self, sid: str, status: Status, by: str = "user") -> None:
        if sid not in self.status:
            raise KeyError(sid)
        self.status[sid], self.status_by[sid] = status, by

    def complete(self, sid: str | None = None, by: str = "user") -> None:
        sid = sid or self.current
        self.mark(sid, "done", by)
        if sid == self.current:
            self._advance()

    def skip(self) -> None:
        self.mark(self.current, "skipped", "user")
        self._advance()

    def goto(self, sid: str) -> None:
        if sid not in self.status:
            raise KeyError(sid)
        self.current = sid

    def pause(self) -> None:
        self.active = False

    def resume(self) -> None:
        if self.steps:
            self.active = True

    def observe(self, state: dict | None) -> None:
        self.observed = state

    def verify(self, step: Step) -> StepVerification | None:
        """Compare the step's expected state with the last observed state and STORE the result on the step. Does not change its status."""
        if self.observed is None:
            return None
        v = evaluate_step(step, self.observed)
        step.verification = StepVerification(
            outcome=v.status, observed_source="addon", checked_at=datetime.now(timezone.utc),
            unmet=[human_state(p.kind, p.target) for p in v.unmet],
            detail=("not observable: " + ", ".join(human_state(p.kind, p.target) for p in v.unobservable)) if v.unobservable else None)
        return step.verification

    def note(self, user: str, intent: str, route: str, step: str | None) -> None:
        self.turns.append(TurnNote(user[:120], intent, route, step))


# ---- persistence: a session is plain JSON, so a conversation survives a restart and the UI can read it
def to_dict(s: Session) -> dict:
    return {"format": 1, "version": s.version, "app": s.app, "observed": s.observed, "tutorial": s.tutorial, "task": s.task, "active": s.active, "current": s.current,
            "status": s.status, "status_by": s.status_by, "corrections": s.corrections, "turns": [asdict(t) for t in s.turns],
            "steps": s.steps.model_dump(mode="json") if s.steps else None}


def from_dict(d: dict) -> Session:
    if d.get("format") != 1:
        raise ValueError(f"unknown session format: {d.get('format')!r}")
    if d.get("app", "blender") not in APPS:
        raise ValueError(f"session file names an unknown application: {d.get('app')!r}")
    s = Session(version=d.get("version"), app=d.get("app", "blender"), observed=d.get("observed"), tutorial=d.get("tutorial"), task=d.get("task"), active=bool(d.get("active")),
                current=d.get("current"), status=dict(d.get("status") or {}), status_by=dict(d.get("status_by") or {}), corrections=list(d.get("corrections") or []))
    s.steps = StepList.model_validate(d["steps"]) if d.get("steps") else None
    s.turns.extend(TurnNote(**t) for t in d.get("turns", []))
    if s.steps and (s.current not in {x.id for x in s.steps.steps} or set(s.status) != {x.id for x in s.steps.steps}):
        raise ValueError("session file is inconsistent: statuses or the current step do not match the steps")
    return s
