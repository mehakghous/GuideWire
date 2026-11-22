"""The other way to do what a step does with the keyboard: "Press Shift+A" -> "use the Add menu in the 3D view header". No Qt, no screen.

A tutorial that says a shortcut leaves the learner with one way in. Blender nearly always has a second, a menu or the mode dropdown, and a learner who has not learned the keys, or whose keymap
differs, needs it. The route comes from what Blender itself reports (shared/menu_routes.py) for the key's own operator in the learner's mode; nothing is guessed, and a key with no menu
equivalent (a typed value, a modal key) gets no alternative and nothing is said about it.

`alternatives_of(step, mode)` gives one `KeyAlt` per distinct route: the keys as written, the route, a sentence to show, and a `TargetRef` the guide can look for on screen like any other target.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared import menu_routes
from shared.step_record import Step, TargetRef
from vision.grounders import mode_label

MODE_OPERATORS = ("object.mode_set", "object.mode_set_with_submode", "object.editmode_toggle", "object.posemode_toggle")
MODE_SELECTOR = "Mode selector"
MAX_IN_HINT = 2                  # the one-line hint names at most this many; the step details list them all


@dataclass(frozen=True)
class KeyAlt:
    keys: str                       # as the step writes them: "Shift+A"
    route: tuple[str, ...]          # the labels to click: ("Add",), ("Object", "Parent", "Clear Parent"), ("Mode selector", "Edit Mode")
    text: str                       # "use the Add menu in the 3D view header"
    target: TargetRef               # what the guide looks for on screen: a menu path, or the mode


def phrase(route: tuple[str, ...]) -> str:
    """The route as a sentence fragment."""
    if route[0] == MODE_SELECTOR and len(route) == 2:
        return f"choose {route[1]} in the mode dropdown at the top left of the 3D view"
    if len(route) == 1:
        return f"use the {route[0]} menu in the 3D view header"
    return f"use {' > '.join(route)} in the 3D view header"


def start_mode(step: Step) -> str | None:
    return next((p.target for p in step.start_state if p.kind == "mode"), None)


def mode_for(steps: list[Step], index: int) -> str | None:
    """The mode the learner is in when step `index` (0-based) begins: its own start state, else the mode the closest earlier step ends in, else unknown."""
    own = start_mode(steps[index])
    if own:
        return own
    for s in reversed(steps[:index]):
        m = next((p.target for p in s.expected_state if p.kind == "mode"), None)
        if m:
            return m
    return None


def alternatives_of(step: Step, mode: str | None = None) -> list[KeyAlt]:
    """The menu or dropdown route for each key press of the step that has one. `mode` is where the learner is now (observed, or carried over from the earlier steps); without it the step's own start
    state is used, and without that every mode Blender's header menus were dumped for is tried in turn, which is right whenever the key's operator belongs to one mode only."""
    mode = mode or start_mode(step)
    out: list[KeyAlt] = []
    seen: set[tuple[str, ...]] = set()
    for a in step.actions:
        t = a.target
        if a.verb != "press_keys" or not a.keys or t is None or t.kind != "keys" or not t.operator:
            continue
        keys = "+".join(k if len(k) > 1 else k.upper() for k in a.keys)
        if t.operator in MODE_OPERATORS:
            want = next((p.target for p in step.expected_state if p.kind == "mode"), None)
            if not want or want == mode:                       # no mode to choose, or already in it
                continue
            label = mode_label(want)
            route = (MODE_SELECTOR, label)
            target = TargetRef(kind="mode", label=label, id=want.split("_")[0], mode=want, keys=list(a.keys), confidence=0.9)
        else:
            found = menu_routes.alternative_for_keys(a.keys, t.operator, mode)
            if found is None:
                continue
            route = found[1]
            target = TargetRef(kind="menu", label=route[-1], path=list(route), keys=list(a.keys), confidence=0.7)
        if route not in seen:
            seen.add(route)
            out.append(KeyAlt(keys, route, phrase(route), target))
    return out


def sentence(alts: list[KeyAlt]) -> str:
    """One line for the guide: "Without the keyboard: use the Add menu in the 3D view header." With several, each is tied to its key."""
    if not alts:
        return ""
    if len(alts) == 1:
        return f"Without the keyboard: {alts[0].text}."
    shown = alts[:MAX_IN_HINT]
    more = "; the others are in the step details" if len(alts) > len(shown) else ""
    return "Without the keyboard: " + "; ".join(f"for {a.keys}, {a.text}" for a in shown) + more + "."


def key_for_menu(step: Step, path: list[str], mode: str | None = None) -> str:
    """The other direction: when the step's own target is a menu ("Add > Armature > Single Bone") and a key of the step opens that same menu, those keys ("Shift+A"), else ""."""
    if not path:
        return ""
    for alt in alternatives_of(step, mode):
        if alt.target.kind == "menu" and alt.route[0] == path[0]:
            return alt.keys
    return ""
