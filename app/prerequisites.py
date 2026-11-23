"""What a tutorial ASSUMES you already have, said before the session starts. No Qt, no database: it reads the saved steps only.

Many tutorials begin after the boring part: "How to Rig a Leg with Inverse Kinematics" starts with a leg mesh that is already modelled, and its last steps bind that mesh to the armature. Nothing in the steps
ever creates the mesh, so a learner who starts from the default scene reaches step 35 with nothing to bind. This module finds such things so the session screen can say so up front:

  * a model (mesh) that is used but never made: a step talks about binding, skinning or weight-painting a mesh, or its result is a modifier or selection of a mesh, and no step adds or imports one;
  * what a step says it assumes and the input did not establish (`Step.assumptions`). The lines the knowledge base adds ("Before this: ...") are left out: they describe a step's own context, are sometimes already
    made by the step itself, and would put noise ahead of the one thing a learner has to prepare.

Blender also starts every new file with a default cube. When no step uses it, or says to delete it or to start from an empty scene, the first item offers to remove it: the extracted steps stay exactly as the
source gave them (no renumbering, no shifted video times, no model call), and it works for every Blender tutorial, old or new.

Each item can be checked against the state the application reports (`status`): "met", "unmet" or "unknown" (the application does not say). A check never blocks anything; it only tells the learner what was not seen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from shared.step_record import Step

MESH_WORDS = {"blender": "mesh", "maya": "mesh", "houdini": "geometry"}
_USES_MESH = re.compile(r"\b(?:bind(?:ing)?\b.*\b(?:mesh|model|geometry|skin)|skin(?:ning)?|weight[- ]?paint\w*|automatic weights|parent\w*\b.*\b(?:mesh|model)|(?:mesh|model|geometry)\b.*\barmature|deform\w*)\b", re.I)
_MAKES_MESH = re.compile(r"^(?:add|create|make|model|sculpt|import|build)\b.*\b(?:mesh|cube|cylinder|sphere|plane|model|geometry|character|body)\b", re.I)
_MESH_NODES = ("MESH", "MODIFIER_ARMATURE")                 # an expected state that can only be true when a mesh was there
_STOP = {"the", "a", "an", "your", "this", "that", "bind", "select", "selected", "unselected", "armature", "bone", "mesh"}
_CUBE_HANDLED = re.compile(r"\b(?:cube|default (?:scene|objects?|cube|startup)|delete (?:all|everything)|clear (?:the )?scene|empty scene|new (?:file|scene|project)|file\s*>\s*new|factory settings)\b", re.I)
CUBE_TEXT = ("Blender's starting scene has a default cube in it, and this tutorial never uses it. You can remove it before you begin: click the cube in the 3D Viewport, press X and choose Delete "
             "(or right-click it in the Outliner and choose Delete). Skip this if you want to keep it.")
_SUBJECT_IN_GOAL = re.compile(r"\b([A-Za-z]{3,})\s+(?:mesh|model|geometry)\b", re.I)
_SUBJECT_IN_TITLE = re.compile(r"\brigg?(?:ing)?\s+(?:a|an|the|your)?\s*([A-Za-z][A-Za-z ]{1,24}?)\s*(?:with|using|in|for|\||-|:|$)", re.I)


@dataclass(frozen=True)
class Prereq:
    text: str                                  # one plain sentence for the learner
    needs: tuple[str, ...] = ()                # node types the application must show for it to be met (MESH, ARMATURE ...); empty = cannot be checked

    def status(self, observed: dict[str, Any] | None) -> str:
        nodes = (observed or {}).get("nodes")
        if not self.needs or not isinstance(nodes, (list, tuple)) or not nodes:
            return "unknown"                   # the application did not report what is in the scene (no add-on): not the same as "missing"
        return "met" if all(n in nodes for n in self.needs) else "unmet"


def _text_of(step: Step) -> str:
    return " ".join([step.goal, *(a.ui_element or "" for a in step.actions), *(h.text for h in step.how_to)])


def _makes_mesh(step: Step) -> bool:
    if _MAKES_MESH.search(step.goal):
        return True
    return any((a.ui_element or "").lower().replace(" ", "").startswith(("add>mesh", "file>import")) for a in step.actions)


def _uses_mesh(step: Step) -> bool:
    if _USES_MESH.search(step.goal) or _USES_MESH.search(" ".join(a.ui_element or "" for a in step.actions)):
        return True
    return any(p.kind in ("node_exists", "node_count", "selection_type") and p.target in _MESH_NODES for p in step.expected_state)


def _subject(steps: list[Step], title: str | None) -> str | None:
    """What the model is of ("leg"), from the step that uses it, else from the tutorial's title ("Rig a Leg with ...")."""
    for s in steps:
        if _uses_mesh(s):
            m = _SUBJECT_IN_GOAL.search(s.goal)
            if m and m.group(1).lower() not in _STOP:
                return m.group(1).lower()
    m = _SUBJECT_IN_TITLE.search(title or "")
    if m:
        words = [w for w in m.group(1).lower().split() if w not in ("a", "an", "the", "your")]
        if words and len(words) <= 3:
            return " ".join(words)
    return None


def _mentions_default_scene(steps: list[Step]) -> bool:
    return any(_CUBE_HANDLED.search(_text_of(s)) or any(_CUBE_HANDLED.search(a) for a in s.assumptions) for s in steps)


def prerequisites(steps: list[Step], app: str = "blender", title: str | None = None) -> list[Prereq]:
    """What this tutorial assumes, in the order a learner should prepare it. Empty when nothing is assumed."""
    out: list[Prereq] = []
    if app == "blender" and steps and not _mentions_default_scene(steps):
        out.append(Prereq(CUBE_TEXT))
    first_use = next((i for i, s in enumerate(steps) if _uses_mesh(s)), None)
    if first_use is not None and not any(_makes_mesh(s) for s in steps[:first_use + 1]):
        what = MESH_WORDS.get(app, "mesh")
        subject = _subject(steps, title)
        label = f"A {subject} {what}" if subject else f"A {what} (the model you want to rig)"
        out.append(Prereq(f"{label} already in the scene. This tutorial starts with it ready and never makes it: step {first_use + 1} is the first that uses it.", ("MESH",) if app == "blender" else ()))
    seen = {p.text for p in out}
    for s in steps:
        for a in s.assumptions:
            if not a.startswith("Before this:") and a not in seen:
                seen.add(a)
                out.append(Prereq(a.removeprefix("Assumes: ").strip().rstrip(".") + "."))
    return out


def check(prereqs: list[Prereq], observed: dict[str, Any] | None) -> list[Prereq]:
    """The prerequisites the application's reported state shows to be missing (those it cannot tell are not listed: silence is not a warning)."""
    return [p for p in prereqs if p.status(observed) == "unmet"]
