"""What to SHOW for a step, from the step itself (no screen, no vision, no Qt: pure and testable).

A tutorial step is not always "click this menu item". Looking at an 18-step Blender tutorial, a step needs one of four kinds of help:
  * a UI path to point at          ("Add > Mesh > Cylinder", "Mode selector > Edit Mode", "Toolbar > Loop Cut"): found on screen by text, or in the toolbar by name for the current mode;
  * keys to press                  ("Press A, then Delete"): nothing to point at, so the keys are shown as key caps and the pointer goes where the mouse must be (the 3D viewport);
  * something in the 3D viewport   ("Z Scale Handle", "Bone Tip Joint", "Cylinder Mesh"): the screen does not name it, so the pointer goes to the viewport and the words say what to do there;
  * a panel that exists only after an action ("Loop Cut and Slide > Number of Cuts", "Subdivide > Number of Cuts"): the pointer goes where Blender puts it (the bottom-left of the viewport).
`plan_for` sorts a step's actions and how-to lines into those, and `describe` turns what vision found into the words for the learner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from shared.step_record import Step

from .session_engine import ACTIVE, SessionEngine

# words that name something in the 3D viewport, not a menu or panel (they are never found as text)
SCENE_WORDS = ("handle", "joint", "gizmo", "viewport mesh", "cylinder mesh", "armature object", "bone", "object")
KEY_WORDS = {"delete", "tab", "enter", "return", "esc", "escape", "space", "backspace", "home", "end", "ctrl", "shift", "alt", "x", "z"}
_KEY = re.compile(r"\bpress(?:ing)?\s+((?:(?:ctrl|shift|alt)\s*\+\s*)*[a-z0-9]+)", re.I)
# panels Blender opens at the bottom-left of the 3D viewport after an operation (the "redo" panel)
TOOL_KEYS = {"scale": "S", "move": "G", "rotate": "R", "loop cut": "Ctrl+R"}      # the keyboard way to the same tool, when it is not visible in a short toolbar
REDO_PANELS = ("loop cut and slide", "subdivide", "add cylinder", "extrude")


@dataclass(frozen=True)
class Target:
    kind: str            # path | mode | tool | context
    path: str            # what to look for on screen
    shown: str = ""      # the words for the learner ("Mode selector > Edit Mode" reads better than the internal path)


@dataclass(frozen=True)
class Plan:
    targets: tuple[Target, ...] = ()
    keys: tuple[str, ...] = ()                 # in order: ("A", "Delete")
    region: str | None = None                  # viewport | properties | outliner | timeline | None
    anchor: str = "center"                     # where in the region the pointer goes: center | bottom-left
    mode_hint: str | None = None               # the mode the step starts in (the toolbar differs per mode)
    scene_items: tuple[str, ...] = ()          # things in the 3D viewport the step names
    inputs: tuple[tuple[str, str], ...] = ()   # the mouse and keyboard events in order, for the animated hint


def keys_of(step: Step) -> tuple[str, ...]:
    """The keys the step says to press, in order, as written on a keyboard ("A", "Delete", "Ctrl+P")."""
    out: list[str] = []
    for a in getattr(step, "actions", []) or []:                       # the step's own key actions say it exactly (["Ctrl", "P"] = Ctrl+P)
        if a.verb == "press_keys" and a.keys:
            out.append("+".join(k if len(k) > 1 else k.upper() for k in a.keys))
    if out:
        return tuple(out)
    for h in step.how_to:
        for m in _KEY.finditer(h.text):
            parts = [p.strip() for p in m.group(1).split("+") if p.strip()]
            if not parts or not all(len(p) == 1 or p.lower() in KEY_WORDS or re.fullmatch(r"f\d{1,2}", p.lower()) for p in parts):
                continue
            out.append("+".join(p.upper() if len(p) == 1 else p.capitalize() for p in parts))
    return tuple(out)


def inputs_for(step: Step) -> tuple[tuple[str, str], ...]:
    """The mouse and keyboard events of a step in order, for the animated hint: ("click", "left" | "right" | "hover"), ("drag", "left"), ("keys", "Ctrl+P"), ("type", "10"). At most six."""
    out: list[tuple[str, str]] = []
    for a in step.actions:
        ui = (a.ui_element or "").lower()
        if a.verb == "press_keys":
            if a.keys:
                out.append(("keys", "+".join(k if len(k) > 1 else k.upper() for k in a.keys)))
        elif a.verb == "drag":
            out.append(("drag", "left"))
        elif a.verb == "open_menu" and ui.startswith("viewport context menu"):
            out += [("click", "right"), ("click", "left")]
        elif a.verb == "open_menu":
            out += [("click", "left"), ("click", "hover"), ("click", "left")] if ui.count(">") >= 2 else [("click", "left")]
        elif a.verb == "set_value":
            out.append(("type", a.value or ""))
        elif ui:
            out.append(("click", "left"))
        elif a.verb in ("click", "select"):
            out.append(("click", "left"))
    return tuple(out[:6])


def _is_scene_item(ui: str) -> bool:
    low = ui.lower()
    return ">" not in ui and any(w in low for w in SCENE_WORDS)


def plan_for(step: Step) -> Plan:
    targets: list[Target] = []
    scene: list[str] = []
    region, anchor = None, "center"
    for a in step.actions:
        ui = (a.ui_element or "").strip()
        if not ui:
            continue
        low = ui.lower()
        if low.startswith("mode selector"):
            targets.append(Target("mode", ui, ui.replace("Mode selector", "the mode dropdown")))
        elif low.startswith("toolbar"):
            targets.append(Target("tool", ui, ui))
            region = region or "toolbar"
        elif low.startswith("viewport context menu"):
            item = ui.split(">", 1)[1].strip() if ">" in ui else ui
            targets.append(Target("context", item, f"right-click, then {item}"))
            region = "viewport"
        elif _is_scene_item(ui):
            scene.append(ui)
        else:
            targets.append(Target("path", ui, ui))
            if any(low.startswith(p) for p in REDO_PANELS):
                region, anchor = "viewport", "bottom-left"
            elif low.startswith("properties"):
                region, anchor = "properties", "tabs"
            elif low.startswith("outliner"):
                region = "outliner"
    keys = keys_of(step)
    if region == "toolbar" and (scene or keys):
        region = "toolbar"
    elif region is None and (scene or keys or any("viewport" in (h.text or "").lower() for h in step.how_to)):
        region = "viewport"
    mode = next((p.target for p in step.start_state if p.kind == "mode"), None)
    return Plan(tuple(targets), keys, region, anchor, mode, tuple(scene), inputs_for(step))


def describe(plan: Plan, found: Target | None, matched: str = "", complete: bool = False, step: Step | None = None) -> str:
    """The sentence for the learner: what to click next if something was found, else the keys, else what to do in the viewport."""
    if found is not None:
        path = found.path
        if found.kind == "mode":
            item = path.split(">", 1)[1].strip() if ">" in path else path
            return f"Click the mode dropdown (top left), then {item}" if not complete else f"Click {item}"
        if found.kind == "context":
            return f"Right-click in the viewport, then click {found.path}"
        parts = [p.strip() for p in path.split(">") if p.strip()]
        low = [p.lower() for p in parts]
        if found.kind == "tool":
            then = (" Then in the 3D viewport: " + ", ".join(plan.scene_items) + ".") if plan.scene_items else ""
            return f"Click {parts[-1]} in the toolbar (left side)." + then
        note = " (Blender 5.2 adds a single bone directly; older versions: Armature > Single Bone)" if low[-1:] == ["armature"] and low[:1] == ["add"] else ""
        i = max((n for n, p in enumerate(low) if p == (matched or "").strip().lower()), default=None)
        if i is None:
            return "Open: " + " > ".join(parts)
        rest = parts[i + 1:]
        return (f"Click {parts[i]}" if complete or not rest else f"Click {parts[i]}, then " + " > ".join(rest)) + (note if complete else "")
    if plan.targets and plan.targets[0].kind == "tool":
        name = plan.targets[0].path.split(">")[-1].strip()
        key = TOOL_KEYS.get(name.lower())
        tip = f" or press {key} with the mouse over the 3D viewport" if key else ""
        return f"Pick {name} in the toolbar (left side; scroll it or make the window taller if you cannot see it){tip}." + ((" Then in the 3D viewport: " + ", ".join(plan.scene_items) + ".") if plan.scene_items else "")
    if plan.anchor == "bottom-left" and plan.targets and step is not None and step.how_to:
        return step.how_to[0].text.rstrip(".") + f", then use {plan.targets[0].path} in the panel at the bottom-left of the 3D viewport."
    if plan.region == "properties" and plan.targets:
        parts = [p.strip() for p in plan.targets[0].path.split(">") if p.strip()][1:]
        tab = parts[0] if parts else "the tab"
        tab = "Object Data (the green icon)" if tab.lower() == "data" else tab
        return f"In the Properties panel (right side) open the {tab} tab in the column of icons, then " + " > ".join(parts[1:]) if len(parts) > 1 else f"Open the {tab} tab in the Properties panel (right side)"
    if plan.keys:
        where = " with the mouse over the 3D viewport" if plan.region == "viewport" else ""
        after = f", then choose {plan.targets[0].path}" if plan.targets else ""
        return "Press " + " then ".join(plan.keys) + where + after
    if step is not None and step.how_to:
        return step.how_to[0].text.rstrip(".")
    return step.goal if step is not None else ""


# ======================================================================================== the first guidance controller (kept)
# What follows is the controller for a vision service with observe() and ground(). The session screen now uses the vision bridge (app/vision_bridge.py) instead; this stays for its callers and its tests.
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
