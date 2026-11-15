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

from app.guidance import Plan, describe, plan_for
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
    hint: str = ""                               # "Click Add, then Mesh > Cylinder": what to do next, for the highlight's label and the instruction box
    pointer: bool = False                        # rect is only WHERE to look (a region of the screen), not a found element: draw a pulsing pointer, not a box
    keys: tuple[str, ...] = ()                   # keys to press, shown as key caps
    inputs: tuple[tuple[str, str], ...] = ()     # mouse and keyboard events in order, for the animated hint


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
        w = winplatform.find_window(WINDOW_NAMES.get(app, app), profile(app).exe if app in WINDOW_NAMES else ())
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
    pointer: bool = False
    keys: tuple[str, ...] = ()
    inputs: tuple[tuple[str, str], ...] = ()
    problem: str | None = None                   # a plain-words reason nothing could be seen
    problem_state: str = "error"                 # unavailable | no_window | error


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
    """The real vision service for an application. Imports are lazy: the app starts without OpenCV, the Windows OCR packages or Windows itself, and says what is missing instead.

    It reads only what CHANGED, the way Umaima's `vision/guide.py` does. A tick grabs the window (cheap), compares a small thumbnail with the one at the last reading, and then
      * nothing changed      -> reuses the words read before (no OCR at all);
      * a small area changed -> reads only that area (a menu that just opened) and merges the words into the ones known;
      * most of the window changed, or it moved or was resized -> reads the whole window.
    VisionService on its own compares the MEAN change of the whole screen, so a menu opening (a small area) looked like "no change" and the old words stayed for up to five seconds."""
    from vision.service import VisionService

    class LiveService(VisionService):
        mode_hint: str | None = None          # the mode the step starts in: the toolbar differs per mode
        prefer_toolbar = False                # icon-only tools: look in the toolbar before the text

        def ground(self, ui_element: str):
            from shared.grounding import GroundingResult
            from vision.probe_client import read_probe
            from vision.service import Guidance, find_target, ground_located
            win, frame, pixels, words, _ = self._scene()
            if win is None:
                return Guidance(GroundingResult("none", reason=f"no visible window titled '{self.title}'"))
            mode = self.mode_hint or ((read_probe(app=self.profile.key) or {}).get("mode") if self.use_probe else None)
            found = self._tool(pixels, ui_element, mode) if self.prefer_toolbar and self.profile.toolbar else None
            if found is None:
                found = find_target(words, pixels, ui_element, mode, toolbar=self.profile.toolbar)
            return ground_located(frame.geometry, win.rect, found)

        def _tool(self, pixels, ui_element, mode):
            """A toolbar tool by name, looked up in the toolbar of the step's own mode first (a tool name exists in several modes at different places)."""
            from vision.locate import Located, parse_path
            from vision.regions import default_layout, detect_layout
            from vision.toolbar import find_cells, locate_tool, modes_matching
            layout = detect_layout(pixels)
            viewport = (layout if layout.confidence >= 0.5 else default_layout(pixels.shape[1], pixels.shape[0])).get("viewport")
            path = parse_path(ui_element)
            if viewport is None or not path:
                return None
            cells = find_cells(pixels, viewport)
            for m in modes_matching(cells, mode):
                rect = locate_tool(cells, m, path[-1])
                if rect is not None:
                    return Located(rect, path[-1], len(path) - 1, len(path), 1.0)
            return None

        def region_rect(self, name: str, anchor: str = "center"):
            """A screen rectangle in a region of the application (viewport, properties...): where to point when the thing itself has no text to find."""
            from shared.grounding import Rect
            win, frame, pixels, words, layout = self._scene()
            if win is None or layout is None or layout.get("viewport" if name == "toolbar" else name) is None:
                return None
            if name == "toolbar":                                        # the left toolbar: point at its last visible cell (a tool below it needs a scroll)
                from vision.toolbar import find_cells
                cells = find_cells(pixels, layout.get("viewport"))
                if not cells:
                    return None
                c = cells[-1].rect
                m = frame.geometry.monitor
                sx, sy = m.w / frame.geometry.image_w, m.h / frame.geometry.image_h
                return Rect(round(m.x + c.x * sx), round(m.y + c.y * sy), round(c.w * sx), round(c.h * sy))
            r = layout.get(name)
            size = max(40, min(r.w, r.h) // 6)
            if anchor == "tabs":                                         # the column of tab icons at the left edge of the Properties editor
                size = 34
                x, y = r.x + 4, r.y + int(r.h * 0.6)
            else:
                x = r.x + (r.w - size) // 2 if anchor == "center" else r.x + 12
                y = r.y + (r.h - size) // 2 if anchor == "center" else r.y + r.h - size - 12
            m = frame.geometry.monitor
            sx, sy = m.w / frame.geometry.image_w, m.h / frame.geometry.image_h
            return Rect(round(m.x + x * sx), round(m.y + y * sy), round(size * sx), round(size * sy))

        def refresh(self) -> None:
            """Forget what was read, so the next tick reads the whole window."""
            self._cache = {}

        def _scene(self):
            import cv2

            from vision.guide import FULL_READ_SHARE, THUMB, box_to_rect, changed_box, merge_words
            from vision.ocr import read_text
            from vision.regions import default_layout, detect_layout
            win, grabbed = self._frame()
            if win is None:
                self._cache = {}
                return None, None, None, [], None
            frame, pixels = grabbed
            h, w = pixels.shape[:2]
            thumb = cv2.resize(cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY), THUMB, interpolation=cv2.INTER_AREA)
            c = self._cache
            moved = not c or c.get("rect") != win.rect
            box = None if moved else changed_box(c["thumb"], thumb)
            if not moved and box is None:
                return win, frame, pixels, c["words"], c["layout"]                      # nothing changed: no OCR
            area = 1.0 if moved else (box[2] - box[0]) * (box[3] - box[1]) / (THUMB[0] * THUMB[1])
            if moved or area > FULL_READ_SHARE:
                layout = detect_layout(pixels)
                if layout.confidence < 0.5:
                    layout = default_layout(w, h)
                words, serial = read_text(pixels), (c or {}).get("serial", 0)
            else:                                                                       # a small area changed: read that area only
                from dataclasses import replace
                r = box_to_rect(box, w, h)
                serial = c.get("serial", 0) + 1
                fresh = [replace(wd, rect=type(wd.rect)(wd.rect.x + r.x, wd.rect.y + r.y, wd.rect.w, wd.rect.h), line=wd.line + serial * 100000)
                         for wd in read_text(pixels[r.y:r.y + r.h, r.x:r.x + r.w], 2.0)]
                words, layout = merge_words(c["words"], fresh, r), c["layout"]
            self._cache = {"rect": win.rect, "thumb": thumb, "words": words, "layout": layout, "serial": serial}
            return win, frame, pixels, words, layout
    return LiveService(app=app)


MODE_LABELS = {"OBJECT": "Object Mode", "EDIT_MESH": "Edit Mode", "EDIT_ARMATURE": "Edit Mode", "EDIT_CURVE": "Edit Mode", "POSE": "Pose Mode", "SCULPT": "Sculpt Mode",
               "PAINT_WEIGHT": "Weight Paint", "PAINT_VERTEX": "Vertex Paint", "PAINT_TEXTURE": "Texture Paint"}


def _as_dropdown(g):
    """The guidance of the mode dropdown itself (found by the name of the mode it shows now): not 'the last part of the path'."""
    from dataclasses import replace
    return replace(g, complete=False)


def hint_for(target: str | None, matched: str, complete: bool = False) -> str:
    """Words for the learner about the next click, from the step's UI path and the part of it that was found on screen:
    "Click Add, then Mesh > Cylinder"; "Open: Add > Mesh > Cylinder" when nothing of the path is visible yet."""
    parts = [p.strip() for p in (target or "").split(">") if p.strip()]
    if not parts:
        return ""
    low = [p.lower() for p in parts]
    i = max((n for n, p in enumerate(low) if p == (matched or "").strip().lower()), default=None)
    if i is None:
        return "Open: " + " > ".join(parts)
    rest = parts[i + 1:]
    return f"Click {parts[i]}" if complete or not rest else f"Click {parts[i]}, then " + " > ".join(rest)


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
    def __init__(self, service_factory: Callable[[str], Any] | None = None, auto_advance: bool = True, window_finder: Callable[[str], Rect4 | None] | None = None):
        """`service_factory(app)` returns an object with `ground(ui_element)` and `observe(properties=, attributes=)`. None means vision is not installed on this computer.
        `window_finder(app)` returns the application's window rectangle (default: Umaima's Windows lookup)."""
        self.factory = service_factory
        self.auto_advance = auto_advance
        self.window_finder = window_finder or default_window_finder
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

    def window_rect(self, app: str) -> Rect4 | None:
        try:
            return self.window_finder(app)
        except Exception:
            return None

    # ---- looking (vision only: safe on a worker thread, touches no database)
    def _find(self, svc, plan: Plan):
        """The first target of the plan that is on screen right now: (target, guidance), or (None, the guidance worth reporting)."""
        last, saw = None, None
        for t in plan.targets:
            if hasattr(svc, "prefer_toolbar"):
                svc.prefer_toolbar = t.kind == "tool"
            names = [t.path]
            if t.kind == "mode":                           # the item once the dropdown is open, else the dropdown itself (it shows the current mode)
                names = [t.path.split(">", 1)[-1].strip(), MODE_LABELS.get(plan.mode_hint or "", "Object Mode")]
            for i, name in enumerate(names):
                g = svc.ground(name)
                last = last or g
                if getattr(g.grounding, "status", None) == "ok" and g.rect is not None and not g.ambiguous:
                    if t.kind == "mode" and i == 1:
                        g = _as_dropdown(g)
                    return t, g
                if g.ambiguous and saw is None:
                    saw = g
        return None, saw or last

    def look(self, step: Step, app: str) -> Look:
        plan = plan_for(step)
        target = target_of(step)
        keys = plan.keys
        if self.factory is None:
            return Look(target, problem="Screen guidance is not set up on this computer.", problem_state="unavailable")
        svc = self._service(app)
        if svc is None:
            return Look(target, problem=self._failed.get(app, "Screen guidance is not available."), problem_state="unavailable")
        window = self.window_rect(app)
        rect, complete, ambiguous, matched, pointer, found = None, False, False, "", False, None
        try:
            if hasattr(svc, "mode_hint"):
                svc.mode_hint = plan.mode_hint
            if plan.targets:
                found, g = self._find(svc, plan)
                if g is not None:
                    matched = getattr(g, "matched", "") or ""
                    if found is not None and g.rect is not None:
                        rect = (g.rect.x, g.rect.y, g.rect.w, g.rect.h)
                    complete, ambiguous = bool(g.complete), bool(g.ambiguous and found is None)
                    if found is None and getattr(g.grounding, "reason", "").startswith("no visible window"):
                        return Look(target, window_rect=window, problem=f"Open {WINDOW_NAMES.get(app, app)} in front so GuideWire can see it.", problem_state="no_window", keys=keys)
            if rect is None and not ambiguous and plan.region and hasattr(svc, "region_rect"):
                r = svc.region_rect(plan.region, plan.anchor)        # nothing to find by text: point at where it happens
                if r is not None:
                    rect, pointer = (r.x, r.y, r.w, r.h), True
            props, attrs = needs_of(step)
            observed = svc.observe(properties=props or None, attributes=attrs or None)
        except ImportError as e:                         # the OCR packages are missing: this fails the first time the screen is read, not when the service is made
            self._failed[app] = explain(e)
            return Look(target, window_rect=window, problem=self._failed[app], problem_state="unavailable")
        except Exception as e:                           # a vision failure must never break the session
            return Look(target, window_rect=window, problem=f"Screen guidance hit a problem ({type(e).__name__}); use Done when you have finished the step.", keys=keys)
        hint = describe(plan, found, matched, complete, step)
        return Look(target, rect, complete, ambiguous, observed, window, hint=hint, pointer=pointer, keys=keys, inputs=plan.inputs)

    # ---- judging (touches the session: main thread)
    def apply(self, engine, look: Look) -> Tick:
        """Turn a Look into a Tick, completing the step only when the application shows it done."""
        if engine.current_step() is None:
            return Tick("idle", "No step is active.")
        if look.problem is not None:
            return Tick(look.problem_state, look.problem, look.target, keys=look.keys, inputs=look.inputs)
        verdict = engine.check(look.observed or {})
        status = verdict.status if verdict is not None else None
        advanced = bool(self.auto_advance and engine.auto_check(look.observed or {}))
        if advanced:
            return Tick("done_seen", "GuideWire saw this step done.", look.target, look.rect, look.complete, look.ambiguous, status, True, look.hint, look.pointer, look.keys, look.inputs)
        if look.rect is None and look.target and not look.keys:
            msg = "Several places on the screen match; open the menu and it will narrow down." if look.ambiguous else "Looking for that on the screen."
        else:
            msg = "Watching the screen."
        return Tick("watching", msg, look.target, look.rect, look.complete, look.ambiguous, status, False, look.hint, look.pointer, look.keys, look.inputs)

    def tick(self, engine, app: str | None = None) -> Tick:
        """Look and judge in one call (tests, the live check script). Never raises."""
        step = engine.current_step()
        if step is None:
            return Tick("idle", "No step is active.")
        return self.apply(engine, self.look(step, app or app_of(engine)))
