"""Put the exact dropdown path into a step: not "use the Mesh menu" but `Mesh > Extrude > Extrude Faces`.

A step names what to do ("Extrude the top face"). If the application's real menus contain one clear
match (`shared/menu_paths.py`, dumped from the application itself), the step gets
  * an `open_menu` Action with the full path, so the on-screen guide can light it up, and
  * a how-to line "Menu: <path> (where; mode). Shortcut: ..." labelled `catalog`: guidance from the
    application's own menus, not something the tutorial showed.
Conservative on purpose: no confident single match, no change. Steps that already carry a full menu path
are left alone. Idempotent.
"""
from __future__ import annotations

import re

from shared.menu_paths import best_menu_path, find_menu_paths
from shared.step_record import Action, HowTo, Step, StepList

_PREFIX = "Menu: "
_DEFINITION = re.compile(r"\s*(what(?:'s|\s+is|\s+are|\s+does|\s+do)|why|who|explain|define|meaning of|difference between)", re.I)
MAX_OPTIONS = 3


def _step_mode(step: Step) -> str | None:
    for p in step.start_state:
        if p.kind == "mode":
            return p.target
    return None


def _has_full_path(step: Step) -> bool:
    return any(a.ui_element and ">" in a.ui_element for a in step.actions) or any(h.text.startswith(_PREFIX) for h in step.how_to)


def add_menu_path(step: Step, app: str) -> bool:
    """Add the exact menu path to one step. True if it changed."""
    if _has_full_path(step):
        return False
    names = [a.ui_element for a in step.actions if a.ui_element]
    hit = best_menu_path(app, " ".join([step.goal, *names]), _step_mode(step))
    if hit is None or hit.alternatives:
        return False                                   # nothing clear, or several equally good places: do not choose for the learner
    step.actions.append(Action(verb="open_menu", ui_element=hit.text))
    step.how_to.append(HowTo(text=_PREFIX + hit.describe(), support="catalog"))
    if hit.needs and hit.needs not in step.assumptions:
        step.assumptions.append(hit.needs)
    return True


def add_menu_paths(sl: StepList) -> int:
    """Add exact menu paths across a step list; returns how many steps gained one."""
    return sum(add_menu_path(st, sl.app) for st in sl.steps)


def menu_lines(app: str, question: str, mode: str | None = None) -> list[str]:
    """Lines telling a learner exactly where to click for what they asked, or [] when there is no clear answer.

    One clear match gives "Where: <menu path> (...)". Several equally good different commands (for example
    UV Sphere and Ico Sphere) are listed so the learner can choose; nothing is picked for them."""
    if _DEFINITION.match(question):
        return []                                         # "what is a vertex" asks for an explanation, not a menu
    hits = find_menu_paths(app, question, mode, limit=6)
    if not hits or hits[0].score < 0.9:
        return []
    top = hits[0]
    near = [h for h in hits if abs(h.score - top.score) <= 0.02 and (h.op or h.path[-1]) != (top.op or top.path[-1])]
    out = []
    if near:
        out.append("Where (pick the one you mean): " + "; ".join(h.describe() for h in [top, *near][:MAX_OPTIONS]))
    else:
        out.append("Where: " + top.describe())
    if top.needs and not near:
        out.append(top.needs)
    return out
