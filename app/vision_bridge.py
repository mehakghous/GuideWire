"""The bridge between the session and the vision part. No Qt, so it is testable without a screen.

Vision OBSERVES only: it never clicks or types. Once per look the bridge asks it for what the application reports and what the screen shows, finds the targets of the active step, and turns that into ONE
`StepState` (app/step_state.py): blocked / hidden / locating / visible / acting, with the words and, only when the gate (vision/verify.py) passed, the rectangle to highlight. A step advances only through
`SessionEngine.auto_check` (every part of its expected state seen to hold); anything vision cannot read stays unobservable, and an unobservable step is never advanced.

Every failure is a state to show, never an exception: no vision installed, the application window not found, the screen not readable. The learner can always press Done by hand.

Work per look is kept to what changed (the scheduler):
  * capture is cheap and runs every look; OCR runs only on what changed (vision/scene.py);
  * a located target is reused while the add-on's interface revision, its scene revision, the window and the words read from the screen are the same (`GroundCache`): a still screen costs a capture and a probe read;
  * a result that is nearly good enough earns ONE fresh read of the whole window per (step, state), then falls back to words.
`bridge.stats` counts looks, cache hits, rechecks and the time spent in each stage, for the live check script.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app import step_state
from shared import shortcuts
from shared.step_record import Step, TargetRef
from vision.grounders import ground_target, hint_for  # noqa: F401  (hint_for is re-exported: the menu wording)
from vision.verify import Gated, GroundCache, gate

WINDOW_NAMES = {"blender": "Blender", "maya": "Maya", "houdini": "Houdini"}
INSTALL_HINT = "pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections"
ENTRY_KEYS = ("node_counts", "nodes", "node_names", "mode")         # what is remembered of the state when a step begins (see SessionEngine.check)


@dataclass(frozen=True)
class Tick:
    state: str                                   # idle | unavailable | no_window | watching | done_seen | error
    message: str = ""                            # one short line for the learner (the status line)
    target: str | None = None                    # the UI path the highlight is for
    rect: tuple[int, int, int, int] | None = None   # (x, y, w, h) in screen pixels, only when the gate passed
    complete: bool = False                       # the highlighted part is the LAST part of the path (the thing to click now)
    ambiguous: bool = False                      # several equally good matches: point at none rather than guess
    verdict: str | None = None                   # met | unmet | unverifiable, for the active step
    advanced: bool = False                       # the step was completed because the application showed it done
    hint: str = ""                               # what to do next, for the guide box
    keys: tuple[str, ...] = ()                   # keys to press, said in the step's text
    phase: str = ""                              # blocked | hidden | locating | visible | acting | verified: where the learner is in the step
    shortcut: str = ""                           # a shortcut advised now ("Ctrl R"), already included in `hint`


Rect4 = tuple[int, int, int, int]               # (x, y, width, height) in physical screen pixels


def overlaps(a: Rect4 | None, b: Rect4 | None) -> bool:
    """True when two rectangles share any area (touching edges do not count)."""
    if a is None or b is None:
        return False
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def side_rect(screen: Rect4, fraction: float = 0.3, right: bool = True) -> Rect4:
    """The strip of the screen GuideWire can sit in so the application keeps the rest: `fraction` of the width, full height."""
    x, y, w, h = screen
    sw = max(320, round(w * fraction))
    return (x + w - sw if right else x, y, sw, h)


def default_window_finder(app: str) -> Rect4 | None:
    """The application's window on screen, from Umaima's Windows lookup (None when it is not visible or this is not Windows)."""
    try:
        from vision import winplatform
        from vision.apps import profile
        winplatform.enable_dpi_awareness()
        w = winplatform.find_window_cached(WINDOW_NAMES.get(app, app), profile(app).exe if app in WINDOW_NAMES else ())
    except Exception:
        return None
    return None if w is None else (w.rect.x, w.rect.y, w.rect.w, w.rect.h)


@dataclass(frozen=True)
class Look:
    """What vision saw for one step. Pure data: made on a worker thread, judged on the main thread (the database belongs to the main thread)."""
    target: str | None = None
    rect: Rect4 | None = None
    complete: bool = False
    ambiguous: bool = False
    observed: dict | None = None
    window_rect: Rect4 | None = None             # the application's window, for the overlay and the "are we covering it" check
    hint: str = ""
    keys: tuple[str, ...] = ()
    problem: str | None = None                   # a plain-words reason nothing could be seen
    problem_state: str = "error"                 # unavailable | no_window | error
    phase: str = ""
    status: str = ""
    shortcut: str = ""
    entry: dict | None = None                    # the observed state when this step began


@dataclass
class Stats:
    """What the scheduler did: for the live check script and for tests that a still screen costs nothing."""
    looks: int = 0
    cache_hits: int = 0
    rechecks: int = 0
    ms_look: float = 0.0                          # capture + OCR of what changed + probe read
    ms_ground: float = 0.0                        # locating the step's targets
    ms_total: float = 0.0


def target_of(step: Step) -> str | None:
    """The UI path to point at for a step: the first action that names one (a menu path, a panel, a tool)."""
    for a in step.actions:
        if a.ui_element and a.ui_element.strip():
            return a.ui_element.strip()
    return None


def probe_paths_of(step: Step) -> tuple[list[str], list[str]]:
    """(properties, attributes) the probe must read for this step: the targets of its property_equals and attribute_exists predicates."""
    props = [p.target for p in step.expected_state if p.kind == "property_equals"]
    attrs = [p.target for p in step.expected_state if p.kind == "attribute_exists"]
    return props, attrs


def keys_wanted(step: Step) -> list[str]:
    """Operators whose keymap entries the probe should report for this step: the ones its tools and key presses run (the learner's own keymap decides which key to show)."""
    out: list[str] = []
    for a in step.actions:
        t = a.target
        op = None if t is None else (shortcuts.tool_operator(t.id) if t.kind == "tool" and t.id else t.operator)
        if op and op not in out:
            out.append(op)
    return out


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


def _screen_checked(app: str) -> bool:
    """Whether the screen of this application is read at all (vision/apps.py `validated`)."""
    try:
        from vision.apps import profile
        return bool(profile(app).validated)
    except Exception:
        return True


class VisionBridge:
    def __init__(self, service_factory: Callable[[str], Any] | None = None, auto_advance: bool = True, window_finder: Callable[[str], Rect4 | None] | None = None):
        """`service_factory(app)` returns an object with `look(properties, attributes, keys) -> (observed, GroundContext | None)` and `reset()`. None means vision is not installed on this computer.
        `window_finder(app)` returns the application's window rectangle (default: Umaima's Windows lookup)."""
        self.factory = service_factory
        self.auto_advance = auto_advance
        self.window_finder = window_finder or default_window_finder
        self._services: dict[str, Any] = {}
        self._failed: dict[str, str] = {}
        self._cache = GroundCache()
        self._entries: dict[str, dict] = {}
        self._rechecked: set[Any] = set()
        # The first look of each VISIT to a step (session, step, engine revision): a step that is already "met" there was true when it started (after Previous, Resume, or because the
        # application was already in that state), which is not evidence the learner did it. Applies to every kind of predicate: mode, tool, selection, property, node.
        self._first_met: dict[tuple, bool] = {}
        self._seen_unmet: set[tuple] = set()
        self._visit: tuple | None = None
        self.stats = Stats()

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
        """Forget a failure (after the learner installed the missing package, say) and everything located."""
        self._services.clear()
        self._failed.clear()
        self._cache.forget()
        self._entries.clear()
        self._rechecked.clear()
        self._first_met.clear()
        self._seen_unmet.clear()
        self._visit = None

    def window_rect(self, app: str) -> Rect4 | None:
        try:
            return self.window_finder(app)
        except Exception:
            return None

    # ---- looking (vision only: safe on a worker thread, touches no database)
    def look(self, step: Step, app: str) -> Look:
        target = target_of(step)
        if self.factory is None:
            return Look(target, problem="Screen guidance is not set up on this computer.", problem_state="unavailable")
        svc = self._service(app)
        if svc is None:
            return Look(target, problem=self._failed.get(app, "Screen guidance is not available."), problem_state="unavailable")
        window = self.window_rect(app)
        t_start = time.perf_counter()
        try:
            props, attrs = probe_paths_of(step)
            wanted = keys_wanted(step)
            observed, ctx = svc.look(props or None, attrs or None, wanted or None)
            t_look = time.perf_counter()
            if ctx is None and not _screen_checked(app):         # not "open it in front": the window may well be in front; this application is not read from the screen (yet)
                return Look(target, window_rect=window, problem=f"Screen checking is available for Blender only. In {WINDOW_NAMES.get(app, app)} you follow the steps and press Done.", problem_state="unavailable", keys=step_state.keys_text(step))
            if ctx is None:
                return Look(target, window_rect=window, problem=f"Open {WINDOW_NAMES.get(app, app)} in front so GuideWire can see it.", problem_state="no_window", keys=step_state.keys_text(step))
            entry = self._entries.setdefault(step.id, {k: observed[k] for k in ENTRY_KEYS if k in observed})
            state, observed = self._assess(step, svc, observed, ctx, props, attrs, wanted, entry)
        except ImportError as e:                         # the OCR packages are missing: this fails the first time the screen is read, not when the service is made
            self._failed[app] = explain(e)
            return Look(target, window_rect=window, problem=self._failed[app], problem_state="unavailable")
        except Exception as e:                           # a vision failure must never break the session
            return Look(target, window_rect=window, problem=f"Screen guidance hit a problem ({type(e).__name__}); use Done when you have finished the step.", keys=step_state.keys_text(step))
        t_end = time.perf_counter()
        self.stats.looks += 1
        self.stats.ms_look += (t_look - t_start) * 1000
        self.stats.ms_ground += (t_end - t_look) * 1000
        self.stats.ms_total += (t_end - t_start) * 1000
        g = state.grounded
        rect = None
        if state.show_rect and g is not None and g.rect is not None:
            rect = (g.rect.x, g.rect.y, g.rect.w, g.rect.h)
        label = " > ".join(state.target.path or [state.target.label]) if state.target is not None else target
        return Look(label, rect, bool(g and g.complete and rect), bool(g and g.ambiguous), observed, window, state.hint, state.keys,
                    None, "error", state.phase, state.status, state.shortcut, entry)

    def _assess(self, step: Step, svc, observed: dict, ctx, props, attrs, wanted, entry: dict | None = None) -> tuple[step_state.StepState, dict]:
        """The step's state, locating each target through the gate and the cache. A result that is nearly good enough earns one fresh read of the whole window (per step and screen state).
        Returns the state and the observed dict that goes with the screen it was judged on (a re-read replaces it)."""
        box = {"ctx": ctx, "observed": observed}

        def ground(ref: TargetRef) -> Gated:
            key = (step.id, ref.kind, ref.id, ref.label, tuple(ref.path), ref.operator, ref.prop, ref.panel, ref.tab)
            epoch = getattr(box["ctx"], "epoch", None)
            if epoch is not None:
                hit = self._cache.lookup(key, epoch)
                if hit is not None:
                    self.stats.cache_hits += 1
                    return hit
            g = gate(ground_target(box["ctx"], ref))
            once = (step.id, epoch)
            if g.recheck and epoch is not None and once not in self._rechecked and hasattr(svc, "reset"):
                self._rechecked.add(once)
                svc.reset()                                                       # forget the words: the next look reads the whole window again
                obs2, ctx2 = svc.look(props or None, attrs or None, wanted or None)
                if ctx2 is not None:
                    self.stats.rechecks += 1
                    box["ctx"], box["observed"] = ctx2, obs2
                    g = gate(ground_target(ctx2, ref))
                    epoch = getattr(ctx2, "epoch", epoch)
            if epoch is not None:
                self._cache.put(key, epoch, g)
            return g
        state = step_state.assess(step, observed, ground, entry)
        return state, box["observed"]

    # ---- judging (touches the session: main thread)
    def apply(self, engine, look: Look) -> Tick:
        """Turn a Look into a Tick, completing the step only when the application shows it done."""
        if engine.current_step() is None:
            return Tick("idle", "No step is active.")
        if look.problem is not None:
            return Tick(look.problem_state, look.problem, look.target, keys=look.keys)
        step = engine.current_step()
        key = (engine.session_id, step.id if step is not None else "", getattr(engine, "revision", 0))
        entry = look.entry
        if key != self._visit:                           # a new visit to a step (Previous, jump, Resume, next session): what was recorded for it before is stale
            self._visit = key
            if step is not None:
                self._entries.pop(step.id, None)
            self._rechecked.clear()
            entry = None
        verdict = engine.check(look.observed or {}, entry)
        status = verdict.status if verdict is not None else None
        if status == "unmet":
            self._seen_unmet.add(key)                    # the screen has seen the step NOT done during this visit
        self._first_met.setdefault(key, status == "met")
        already = status == "met" and self._first_met[key] and key not in self._seen_unmet
        advanced = False
        if self.auto_advance and status == "met" and verdict is not None and not verdict.unobservable and not already:
            engine.complete(by="observed")               # only when the screen saw the state change, never because it was true all along
            advanced = True
        if len(self._first_met) > 500:
            self._first_met.clear()
            self._seen_unmet.clear()
        if advanced:
            self._cache.forget()
            return Tick("done_seen", "GuideWire saw this step done.", look.target, look.rect, look.complete, look.ambiguous, status, True, look.hint, look.keys, "verified", look.shortcut)
        note = "This already looks done on the screen (it was true when the step started), so press Done when you have done it." if already else None
        return Tick("watching", note or look.status or "Watching the screen.", look.target, look.rect, look.complete, look.ambiguous, status, False, look.hint, look.keys, look.phase, look.shortcut)

    def tick(self, engine, app: str | None = None) -> Tick:
        """Look and judge in one call (tests, the live check script). Never raises."""
        step = engine.current_step()
        if step is None:
            return Tick("idle", "No step is active.")
        return self.apply(engine, self.look(step, app or app_of(engine)))
