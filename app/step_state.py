"""Where is the learner in THIS step, and what is the one next thing to tell them? No screen, no Qt: it takes the observed state and a function that grounds a target, so it is tested with fakes.

The step is not "show instruction N". Five things are kept apart because they are different facts:
  * the instruction being shown                (the step's own words),
  * the target located on screen               (`Grounded.state`: found, hidden, scrolled out, wrong mode ...),
  * the target visible AND verified            (the gate passed: a pointer may be drawn),
  * the action performed                       (`Progress.done`: the tool is now active, the operator ran),
  * the action verified complete               (the step's expected state, checked by `SessionEngine.auto_check`, which this module never calls).

Phases (`StepState.phase`), in the order they are decided:
  blocked   a precondition is seen unmet (the step starts in Edit Mode, Blender is in Object Mode): the next move is to fix that, with its own target;
  hidden    the next target exists but cannot be reached now (scrolled out of the toolbar, toolbar hidden, wrong Properties tab, the tool belongs to another mode);
  locating  the target should be on screen and is not found yet / not open yet / ambiguous;
  visible   the target was found and passed the gate: point at it;
  acting    nothing on screen to find for the rest of the step (keys, a thing in the 3D view): do it, the words say how;
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ingestion.evaluator import Progress, progress
from shared import shortcuts
from app import key_alternatives
from shared.step_record import Action, Step, TargetRef
from vision.grounders import HIDDEN, NOT_OPEN, OFFSCREEN, VISIBLE, WORDS, WRONG, Grounded, mode_label
from vision.verify import Gated

GROUNDED_KINDS = ("tool", "menu", "mode", "property", "sidebar", "operator_panel", "context_menu", "node", "parm", "pane")      # node, parm, pane: Houdini      # kinds a grounder can locate on screen


@dataclass(frozen=True)
class StepState:
    phase: str                                   # blocked | hidden | locating | visible | acting
    status: str                                  # one short line for the status label
    hint: str                                    # what to do next, for the guide box
    target: TargetRef | None = None              # the thing the phase is about
    grounded: Grounded | None = None             # what may be shown for it (rect is None unless the gate passed)
    show_rect: bool = False                      # the gate passed: a rectangle for `grounded` may be drawn
    progress: Progress = field(default_factory=Progress)
    shortcut: str = ""                           # "Ctrl R" when a shortcut is advised now
    keys: tuple[str, ...] = ()                   # keys the step says to press (as key caps)
    alternative: str = ""                        # the other way to do the keyed part: "Without the keyboard: use the Add menu in the 3D view header." (already part of `hint`)


def text_target(a: Action) -> TargetRef | None:
    """A target for an action the resolver could not resolve: its words as a menu path to look for on screen (the old behaviour, now explicit and only for what is unresolved)."""
    ui = (a.ui_element or "").strip()
    if not ui or a.target is not None:
        return None
    path = [p.strip() for p in ui.replace("›", ">").replace("→", ">").split(">") if p.strip()]
    if not path or (len(path) == 1 and a.verb != "open_menu"):          # one unresolved word that is not a menu ("Bone", "Z Move Handle") is something in the 3D view: words only, never searched for as text
        return None
    return TargetRef(kind="menu", label=path[-1], path=path, confidence=0.3)


_MODE_OPERATORS = ("object.mode_set", "object.editmode_toggle", "object.posemode_toggle")


def _mode_from_keys(step: Step, a: Action) -> TargetRef | None:
    """A key that switches mode ("Tab" -> object.mode_set) leaves nothing to point at as a key, but its result is a mode the header shows: when the step's expected state names that mode, the
    mode is the thing to guide to. Without this a step "add an armature, press Tab, ..." never says "go to Edit Mode"."""
    t = a.target
    if t is None or t.kind != "keys" or t.operator not in _MODE_OPERATORS:
        return None
    want = next((p.target for p in step.expected_state if p.kind == "mode"), None)
    if not want:
        return None
    return TargetRef(kind="mode", label=mode_label(want), id=want.split("_")[0], mode=want, keys=list(t.keys))


def needs_of(step: Step) -> list[TargetRef]:
    """What the step needs found on screen, in the order the actions come: resolved targets of a kind a grounder can locate, a mode a key switches to, and the words of anything the resolver
    could not resolve."""
    out: list[TargetRef] = []
    for a in step.actions:
        t = a.target if a.target is not None and a.target.kind in GROUNDED_KINDS else (_mode_from_keys(step, a) or text_target(a))
        if t is not None and not any(t.kind == "mode" and o.kind == "mode" and o.mode == t.mode for o in out):
            out.append(t)
    return out


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _created(step: Step, ref: TargetRef, observed: dict, entry: dict | None) -> bool:
    """A menu that ADDS something ("Add > Armature > Single Bone") is done once a thing of a type the step expects to exist is there and was not there when the step began. A menu leaves no
    mark of its own, so without this the guide pointed at Add > Armature for the rest of the step, however many armatures were added."""
    if ref.kind == "pane" and ref.id == "NetworkEditor" and ref.keys:     # Houdini: "press Tab in the network editor" is done once the node the step creates is there
        path = ["add"]
    elif ref.kind != "menu":
        return False
    else:
        path = [_norm(p) for p in (ref.path or [ref.label])]
    counts = {_norm(k): v for k, v in (observed.get("node_counts") or {}).items()}
    before = {_norm(k): v for k, v in ((entry or {}).get("node_counts") or {}).items()}
    for p in step.expected_state:
        if p.kind not in ("node_exists", "node_count"):
            continue
        kind = _norm(p.target)
        names_it = path[:1] == ["add"] or any(kind and (kind in part or part in kind) for part in path if len(part) > 3)
        if names_it and counts.get(kind, 0) > before.get(kind, 0):
            return True
    return False


def _done(step: Step, ref: TargetRef, observed: dict, prog: Progress, entry: dict | None = None) -> bool:
    """The action this target stands for was already seen performed: the tool is the active one, Blender is already in that mode, the thing an Add menu creates now exists."""
    if ref.kind == "tool" and ref.id:
        return any(p.kind == "active_tool" and p.target == ref.id for p in prog.done)
    if ref.kind == "mode":
        now = observed.get("mode")
        return bool(now and ((ref.mode and now == ref.mode) or (ref.id and (now == ref.id or now.startswith(ref.id + "_")))))
    if ref.kind == "node":                                                  # Houdini: "select this node" is done once the probe reports it selected
        return _houdini_selected(ref, observed)
    return _created(step, ref, observed, entry)


def _houdini_selected(ref: TargetRef, observed: dict) -> bool:
    nodes = (((observed.get("ui") or {}).get("network") or {}).get("nodes")) or []
    key = (lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum()).removeprefix("apex"))      # noqa: E731
    for n in nodes:
        if not n.get("selected"):
            continue
        if (ref.path and n.get("name") == ref.path[0]) or (not ref.path and key(n.get("label")) == key(ref.label)):
            return True
    return False


def pending_needs(step: Step, observed: dict, prog: Progress, entry: dict | None = None) -> tuple[list[TargetRef], bool]:
    """The targets still to do, in order, and whether any part of the step has been seen done. A target BEFORE one that is done counts as done too: the learner has moved past it (they are in
    Edit Mode, so the armature they had to add first was added), and the guide must never send them back to an earlier part of the same step."""
    needs = needs_of(step)
    done = [_done(step, r, observed, prog, entry) for r in needs]
    last = max((i for i, d in enumerate(done) if d), default=-1)
    return [r for i, r in enumerate(needs) if i > last and not done[i]], last >= 0


def _unmet_mode_ref(prog: Progress) -> TargetRef | None:
    for p in prog.preconditions_unmet:
        if p.kind == "mode":
            return TargetRef(kind="mode", label=mode_label(p.target), id=p.target.split("_")[0], mode=p.target)
    return None


def _advice(step: Step, ref: TargetRef, g: Grounded, observed: dict) -> str:
    """The shortcut worth showing for this target now, as "Ctrl R", or "" (see shared.shortcuts.advise)."""
    if ref.kind != "tool" or not ref.id:
        return ""
    op = shortcuts.tool_operator(ref.id)
    expects = next((p.target for p in step.expected_state if p.kind == "active_tool"), None)
    uses = any(a.target is not None and a.target.kind == "keys" and a.target.operator == op for a in step.actions) if op else False
    vis = {OFFSCREEN: "offscreen", HIDDEN: "container_hidden", VISIBLE: "visible"}.get(g.state, "unknown")
    adv = shortcuts.advise(tool_id=ref.id, operator=op, mode=observed.get("mode"), visibility=vis, tutorial_uses_keys=uses, expects_tool=expects,
                           user_keys=(observed.get("keys") or {}).get(op) if op else None, app_version=observed.get("blender_version"))
    return adv.shortcut.display if adv.show and adv.shortcut else ""


def keys_text(step: Step) -> tuple[str, ...]:
    from app.hands import keys_of
    return keys_of(step)


def assess(step: Step, observed: dict, ground: Callable[[TargetRef], Gated], entry: dict | None = None) -> StepState:
    """The learner's position in the step. `observed` is what the application reports (the add-on's state merged with what the screen showed); `ground(ref)` locates and GATES one target.
    `entry` is the state observed when the step began (what was already there is not progress)."""
    prog = progress(step, observed)
    keys = keys_text(step)
    pending, started = pending_needs(step, observed, prog, entry)

    fix = None if started else _unmet_mode_ref(prog)          # the mode a step STARTS in is checked before it is under way; once part of it is done (it switched to Edit Mode itself), never send the learner back
    if fix is not None:
        g = ground(fix)
        gr = g.result
        label = fix.label
        return StepState("blocked", f"This step starts in {label}", f"Switch to {label} first. {gr.note}".strip(), fix, gr, g.ok, prog, "", ())

    here = observed.get("mode")
    alts = [a for a in key_alternatives.alternatives_of(step, here) if not (a.target.kind == "mode" and a.target.mode == here)]
    other_way = key_alternatives.sentence(alts)

    if not pending:
        what = "Do this in the 3D view" if (keys or any(a.target is not None and a.target.kind == "viewport" for a in step.actions)) else "Do the step as described"
        done = bool(prog.done)
        how = (_how(step, keys) + " " + other_way).strip()
        if len(alts) == 1 and not done:                           # one key, one other way: point at it (the same gate as any target: no rectangle unless the screen shows it with confidence)
            g = ground(alts[0].target)
            if g.ok and g.result.rect is not None:
                return StepState("acting", what, how, alts[0].target, g.result, True, prog, "", keys, other_way)
        return StepState("acting", "Keep going" if done else what, how, None, None, False, prog, "", keys, other_way)

    ref = pending[0]
    g = ground(ref)
    gr = g.result
    sc = _advice(step, ref, gr, observed)
    tail = f" Or press {sc} with the mouse over the 3D view." if sc else ""
    if not tail and ref.kind == "menu":                           # the step's own target is a menu and a key of the step opens it: say the key too
        k = key_alternatives.key_for_menu(step, ref.path or [ref.label], here)
        tail = f" Or press {k} with the mouse over the 3D view." if k else ""
    if g.ok and gr.state == VISIBLE and gr.rect is not None:
        return StepState("visible", f"Found {gr.label or ref.label}", (gr.note or f"Click {ref.label}.") + tail, ref, gr, True, prog, sc, keys)
    if gr.state in (HIDDEN, OFFSCREEN, WRONG):
        return StepState("hidden", f"Cannot reach {ref.label} yet", gr.note + tail, ref, gr, g.ok, prog, sc, keys)
    if gr.state == WORDS:
        return StepState("acting", "Do this in the 3D view", (_how(step, keys) + " " + other_way).strip(), ref, gr, False, prog, "", keys, other_way)
    why = "Several places match" if gr.ambiguous else ("Open it first" if gr.state == NOT_OPEN else "Looking for it")
    return StepState("locating", f"{why}: {ref.label}", (gr.note or f"Open: {' > '.join(ref.path or [ref.label])}") + tail, ref, gr, False, prog, sc, keys)


def _how(step: Step, keys: tuple[str, ...]) -> str:
    if keys:
        return "Press " + " then ".join(keys) + " with the mouse over the 3D view."
    if step.how_to:
        return step.how_to[0].text.rstrip(".")
    return step.goal

