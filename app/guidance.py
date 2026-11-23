"""Screen guidance for a session: where to point for the active step, and whether the screen shows it is done.

Qt-free so it can be tested with a fake vision service. It uses two calls of `vision.service.VisionService` (or anything shaped like it):
    vision.observe() -> dict      the state the evaluator reads; a missing key means "not observable"
    vision.ground(ui_element) -> Guidance(grounding, rect, complete, ambiguous, matched)

Threading rule: `compute` calls only the vision service, so it may run on a worker thread. `apply` touches the session engine (SQLite, one
thread) and must run on the thread that owns it. A result is dropped when the active step has changed since it was computed.

Guidance only exists for Blender today (that is all vision supports). It observes only: it never clicks or types. When vision is unavailable
(not Windows, OCR missing, Blender not open) the session simply carries on by hand and says why.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from shared.step_record import Step

from .session_engine import ACTIVE, SessionEngine

GUIDED_APPS = frozenset({"blender"})
UNAVAILABLE = "Screen guidance is not available here ({why}). Follow the steps by hand: press Done when a step is finished."


class VisionLike(Protocol):
    def observe(self) -> dict[str, Any]: ...
    def ground(self, ui_element: str) -> Any: ...


def ui_target(step: Step) -> str | None:
    """The thing on screen to point at for a step: the first action that names a UI element, else None (a key press has nothing to highlight)."""
    for a in step.actions:
        if a.ui_element and a.ui_element.strip():
            return a.ui_element.strip()
    return None


@dataclass
class Snapshot:
    """What the vision service reported for one step. Plain data, so it can cross from the worker thread to the UI thread."""
    step_id: str
    observed: dict[str, Any] = field(default_factory=dict)
    guidance: Any = None
    error: str | None = None
    fatal: bool = False          # the service cannot work at all on this computer: stop asking


@dataclass
class Outcome:
    advanced: bool = False       # the step was completed because the screen showed its expected state
    marks: list = field(default_factory=list)   # vision.overlay.Mark objects to draw (empty = draw nothing)
    hint: str = ""               # one line for the learner
    stop: bool = False           # stop asking vision for the rest of this session


def _is_fatal(e: Exception) -> bool:
    return isinstance(e, (ImportError, NotImplementedError)) or type(e).__name__ == "PlatformUnavailable"


class GuidanceController:
    def __init__(self, engine: SessionEngine, vision: VisionLike | None):
        self.engine = engine
        self.vision = vision

    @property
    def available(self) -> bool:
        return self.vision is not None and self.engine.app in GUIDED_APPS

    def current(self) -> tuple[str, str | None] | None:
        """(step id, ui target) of the active step, or None when no step is active. Read on the UI thread, passed to `compute`."""
        step = self.engine.current_step()
        if step is None or self.engine.state != ACTIVE:
            return None
        return step.id, ui_target(step)

    def compute(self, step_id: str, target: str | None) -> Snapshot:
        """Ask vision. Safe on a worker thread: it never touches the engine."""
        if self.vision is None:
            return Snapshot(step_id, error=UNAVAILABLE.format(why="no vision service"), fatal=True)
        try:
            observed = dict(self.vision.observe() or {})
            guidance = self.vision.ground(target) if target else None
        except Exception as e:                                   # vision is best effort: it must never break a session
            return Snapshot(step_id, error=UNAVAILABLE.format(why=str(e) or type(e).__name__), fatal=_is_fatal(e))
        return Snapshot(step_id, observed, guidance)

    def apply(self, snap: Snapshot) -> Outcome:
        """Use a snapshot on the UI thread. Ignored if the active step is no longer the one it was computed for."""
        step = self.engine.current_step()
        if step is None or step.id != snap.step_id:
            return Outcome()
        if snap.error:
            return Outcome(hint=snap.error, stop=snap.fatal)
        if snap.observed and self.engine.auto_check(snap.observed):
            return Outcome(advanced=True, hint="Step completed: GuideWire saw it on screen.")
        return self._pointing(snap)

    @staticmethod
    def _pointing(snap: Snapshot) -> Outcome:
        from vision.overlay import highlight_mark
        g = snap.guidance
        if g is None:
            return Outcome()
        status = getattr(getattr(g, "grounding", None), "status", "none")
        reason = getattr(getattr(g, "grounding", None), "reason", "") or ""
        if status != "ok" or g.rect is None:
            return Outcome(hint=("Blender is not visible: bring it to the front." if "window" in reason else "Could not find that on screen yet."))
        if g.ambiguous:
            return Outcome(marks=[highlight_mark(g.rect)], hint=f"Several places match '{g.matched}': pick the one the step means.")
        return Outcome(marks=[highlight_mark(g.rect)], hint=(f"Click {g.matched}." if g.complete else f"Open {g.matched}, the next part will light up."))
