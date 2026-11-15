"""The bridge between the session and the vision part (Umaima's `vision/`). No Qt, so it is testable without a screen.

Vision OBSERVES only: it never clicks or types. Once per tick the bridge asks it two questions about the active step and does nothing else with the application:
  1. "where on screen is the thing to click?"  -> `VisionService.ground(ui_element)`: a screen rectangle the session screen can highlight;
  2. "what state is the application in?"       -> `VisionService.observe(properties, attributes)`: the dict `ingestion.evaluator` reads. It goes to `SessionEngine.auto_check`,
     which completes the step ONLY when every part of the step's expected state is seen to hold. Anything vision cannot read stays unobservable, and an unobservable step is never advanced.

Every failure is a state to show, never an exception: no vision installed, the application window not found, the screen not readable. The learner can always press Done by hand.

    bridge = VisionBridge(default_service_factory)        # in tests: a fake factory
    t = bridge.tick(engine, "blender")                    # Tick: state, message, rect to highlight, advanced
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from shared.step_record import Step

WINDOW_NAMES = {"blender": "Blender", "maya": "Maya", "houdini": "Houdini"}
INSTALL_HINT = "pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections"


@dataclass(frozen=True)
class Tick:
    state: str                                   # idle | unavailable | no_window | watching | done_seen | error
    message: str = ""                            # one line for the learner, in plain words
    target: str | None = None                    # the UI path the highlight is for
    rect: tuple[int, int, int, int] | None = None   # (x, y, w, h) in screen pixels, only when the element was found
    complete: bool = False                       # the highlighted part is the LAST part of the path (the thing to click now)
    ambiguous: bool = False                      # several equally good matches: point at none rather than guess
    verdict: str | None = None                   # met | unmet | unverifiable, for the active step
    advanced: bool = False                       # the step was completed because the application showed it done


def target_of(step: Step) -> str | None:
    """The UI path to point at for a step: the first action that names one (a menu path, a panel, a tool)."""
    for a in step.actions:
        if a.ui_element and a.ui_element.strip():
            return a.ui_element.strip()
    return None


def needs_of(step: Step) -> tuple[list[str], list[str]]:
    """(properties, attributes) the probe must read for this step: the targets of its property_equals and attribute_exists predicates."""
    props = [p.target for p in step.expected_state if p.kind == "property_equals"]
    attrs = [p.target for p in step.expected_state if p.kind == "attribute_exists"]
    return props, attrs


def app_of(engine) -> str:
    """The application of the tutorial the session runs (blender, maya or houdini)."""
    row = engine.db.conn.execute("SELECT t.app FROM tutorial t JOIN session s ON s.tutorial_id = t.id WHERE s.id = ?", (engine.session_id,)).fetchone()
    return (row["app"] if row else None) or "blender"


def default_service_factory(app: str):
    """The real vision service for an application. Imports are lazy: the app starts without OpenCV, the Windows OCR packages or Windows itself, and says what is missing instead."""
    from vision.service import VisionService
    return VisionService(app=app)


def explain(exc: BaseException) -> str:
    """Plain words for why vision cannot run here."""
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, ImportError) and ("winrt" in text or "ocr" in text.lower()):
        return f"Screen reading needs the Windows OCR packages: {INSTALL_HINT}"
    if isinstance(exc, ImportError):
        return f"The vision part is missing a package ({text[:80]})."
    if isinstance(exc, OSError) or "windows" in text.lower():
        return "Screen guidance works on Windows only."
    return f"Screen guidance is not available ({name})."


class VisionBridge:
    def __init__(self, service_factory: Callable[[str], Any] | None = None, auto_advance: bool = True):
        """`service_factory(app)` returns an object with `ground(ui_element)` and `observe(properties=, attributes=)`. None means vision is not installed on this computer."""
        self.factory = service_factory
        self.auto_advance = auto_advance
        self._services: dict[str, Any] = {}
        self._failed: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return self.factory is not None

    def _service(self, app: str):
        if app in self._failed:
            return None
        if app not in self._services:
            try:
                self._services[app] = self.factory(app)
            except Exception as e:                       # missing packages, not Windows, no display
                self._failed[app] = explain(e)
                return None
        return self._services[app]

    def reset(self) -> None:
        """Forget a failure (after the learner installed the missing package, say)."""
        self._services.clear()
        self._failed.clear()

    def tick(self, engine, app: str | None = None) -> Tick:
        """One look at the screen for the active step. Never raises."""
        step = engine.current_step()
        if step is None:
            return Tick("idle", "No step is active.")
        if self.factory is None:
            return Tick("unavailable", "Screen guidance is not set up on this computer.", target_of(step))
        app = app or app_of(engine)
        svc = self._service(app)
        if svc is None:
            return Tick("unavailable", self._failed.get(app, "Screen guidance is not available."), target_of(step))
        target = target_of(step)
        rect, complete, ambiguous = None, False, False
        try:
            if target:
                g = svc.ground(target)
                if getattr(g.grounding, "status", None) == "ok" and g.rect is not None:
                    rect = (g.rect.x, g.rect.y, g.rect.w, g.rect.h)
                complete, ambiguous = bool(g.complete), bool(g.ambiguous)
                if ambiguous:
                    rect = None                          # several equally good matches: ask, do not point at a guess
                if rect is None and getattr(g.grounding, "reason", "").startswith("no visible window"):
                    return Tick("no_window", f"Open {WINDOW_NAMES.get(app, app)} in front so GuideWire can see it.", target)
            props, attrs = needs_of(step)
            observed = svc.observe(properties=props or None, attributes=attrs or None)
            verdict = engine.check(observed)
            status = verdict.status if verdict is not None else None
            advanced = bool(self.auto_advance and engine.auto_check(observed))
        except Exception as e:                           # a vision failure must never break the session
            return Tick("error", f"Screen guidance hit a problem ({type(e).__name__}); use Done when you have finished the step.", target)
        if advanced:
            return Tick("done_seen", "GuideWire saw this step done.", target, rect, complete, ambiguous, status, True)
        if rect is None and target:
            msg = "Several places on the screen match; open the menu and it will narrow down." if ambiguous else "Looking for that on the screen."
        else:
            msg = "Watching the screen."
        return Tick("watching", msg, target, rect, complete, ambiguous, status, False)
