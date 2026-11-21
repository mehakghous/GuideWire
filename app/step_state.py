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
from shared.step_record import Action, Step, TargetRef
from vision.grounders import HIDDEN, NOT_OPEN, OFFSCREEN, VISIBLE, WORDS, WRONG, Grounded, mode_label
from vision.verify import Gated

GROUNDED_KINDS = ("tool", "menu", "mode", "property", "sidebar", "operator_panel", "context_menu")      # kinds a grounder can locate on screen


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


def text_target(a: Action) -> TargetRef | None:
    """A target for an action the resolver could not resolve: its words as a menu path to look for on screen (the old behaviour, now explicit and only for what is unresolved)."""
    ui = (a.ui_element or "").strip()
    if not ui or a.target is not None:
        return None
    path = [p.strip() for p in ui.replace("›", ">").replace("→", ">").split(">") if p.strip()]
    if not path or (len(path) == 1 and a.verb != "open_menu"):          # one unresolved word that is not a menu ("Bone", "Z Move Handle") is something in the 3D view: words only, never searched for as text
        return None
    return TargetRef(kind="menu", label=path[-1], path=path, confidence=0.3)


def needs_of(step: Step) -> list[TargetRef]:
    """What the step needs found on screen, in the order the actions come: resolved targets of a kind a grounder can locate, and the words of anything the resolver could not resolve."""
    out: list[TargetRef] = []
    for a in step.actions:
        t = a.target if a.target is not None and a.target.kind in GROUNDED_KINDS else text_target(a)
        if t is not None:
            out.append(t)
    return out


def _done(step: Step, ref: TargetRef, observed: dict, prog: Progress) -> bool:
    """The action this target stands for was already seen performed: the tool is the active one, Blender is already in that mode."""
    if ref.kind == "tool" and ref.id:
        return any(p.kind == "active_tool" and p.target == ref.id for p in prog.done)
    if ref.kind == "mode":
        now = observed.get("mode")
        return bool(now and ((ref.mode and now == ref.mode) or (ref.id and (now == ref.id or now.startswith(ref.id + "_")))))
    return False


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


def assess(step: Step, observed: dict, ground: Callable[[TargetRef], Gated]) -> StepState:
    """The learner's position in the step. `observed` is what the application reports (the add-on's state merged with what the screen showed); `ground(ref)` locates and GATES one target."""
    prog = progress(step, observed)
    keys = keys_text(step)

    fix = _unmet_mode_ref(prog)
    if fix is not None:
        g = ground(fix)
        gr = g.result
        label = fix.label
        return StepState("blocked", f"This step starts in {label}", f"Switch to {label} first. {gr.note}".strip(), fix, gr, g.ok, prog, "", ())

    pending = [r for r in needs_of(step) if not _done(step, r, observed, prog)]
    if not pending:
        what = "Do this in the 3D view" if (keys or any(a.target is not None and a.target.kind == "viewport" for a in step.actions)) else "Do the step as described"
        done = bool(prog.done)
        return StepState("acting", "Keep going" if done else what, _how(step, keys), None, None, False, prog, "", keys)

    ref = pending[0]
    g = ground(ref)
    gr = g.result
    sc = _advice(step, ref, gr, observed)
    tail = f" Or press {sc} with the mouse over the 3D view." if sc else ""
    if g.ok and gr.state == VISIBLE and gr.rect is not None:
        return StepState("visible", f"Found {gr.label or ref.label}", (gr.note or f"Click {ref.label}.") + tail, ref, gr, True, prog, sc, keys)
    if gr.state in (HIDDEN, OFFSCREEN, WRONG):
        return StepState("hidden", f"Cannot reach {ref.label} yet", gr.note + tail, ref, gr, g.ok, prog, sc, keys)
    if gr.state == WORDS:
        return StepState("acting", "Do this in the 3D view", _how(step, keys), ref, gr, False, prog, "", keys)
    why = "Several places match" if gr.ambiguous else ("Open it first" if gr.state == NOT_OPEN else "Looking for it")
    return StepState("locating", f"{why}: {ref.label}", gr.note or f"Open: {' > '.join(ref.path or [ref.label])}", ref, gr, False, prog, sc, keys)


def _how(step: Step, keys: tuple[str, ...]) -> str:
    if keys:
        return "Press " + " then ".join(keys) + " with the mouse over the 3D view."
    if step.how_to:
        return step.how_to[0].text.rstrip(".")
    return step.goal

