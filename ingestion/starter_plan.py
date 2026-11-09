"""A starter plan from the knowledge base: the answer to "where do I start rigging?" as a STEP LIST the overlay can follow, not only text.

No model is called and no video is needed. The plan is assembled from the researched knowledge base (ingestion/rigging_knowledge.py): for each topic of the application, in the order of the six pipeline
stages of the proposal (rig preparation, skeleton, controls and constraints, skinning), the outline items become steps, the menu path becomes the step's UI element, the entry's own notes become the how-to
and check lines, and the nodes a topic makes become the expected state (scene_chain.derive_state). Each topic is one display group (schema 0.12), so a learner sees about ten goals and can open any of them.

It is a DRAFT, and says so on every step and in the answer: source type `goal_draft`, provenance `catalog_template`, review status `drafted_automatically`, how-to lines labelled `catalog` (guidance the
knowledge base gives, not something a tutorial showed), and a caveat that it comes from GuideWire's knowledge base and not from a tutorial. Where the knowledge base has no entry (scene units, importing
the mesh: PREP-01 and PREP-02 are not written for any application) the answer says so instead of filling the gap.
"""
from __future__ import annotations

import re

from shared.answer import AnswerBundle, Explanation
from shared.step_record import Action, HowTo, Step, StepList

from .features import load_catalog
from .profiles import get_profile
from .rigging_knowledge import Entry, Knowledge
from .rigging_knowledge import load as load_knowledge
from .scene_chain import derive_state
from .validate import check_structure, sanitize_and_annotate

# Teaching order per application, as entry ids of the knowledge base. The default is the BEGINNER order: prepare the mesh, make the skeleton, bind the mesh to it (so a learner can pose and see
# it deform early), then IK, controls and constraints. The proposal's stage order puts controls and constraints BEFORE skinning (ORDER_PROPOSAL); the independent grader called that order confusing
# for a beginner in 5 of its 7 reasons on the plan replies (docs/evaluation_report_2026-11-09.md, section 3.8), so it is no longer the default.
ORDER: dict[str, list[str]] = {
    "blender": ["blender.apply_transforms", "blender.add_bones", "blender.symmetrize", "blender.bone_roll", "blender.armature_deform_parent", "blender.fk_posing", "blender.ik_constraint", "blender.copy_rotation"],
    "maya": ["maya.freeze_transformations", "maya.create_joints", "maya.name_joints", "maya.orient_joint", "maya.mirror_joint", "maya.bind_skin", "maya.paint_skin_weights", "maya.ik_handle",
             "maya.pole_vector", "maya.create_controllers", "maya.group_controls", "maya.parent_constraint"],
    "houdini": ["houdini.skeleton_sop", "houdini.rig_doctor", "houdini.orient_joints", "houdini.skeleton_mirror", "houdini.capture_weights", "houdini.ik_chains", "houdini.apex_autorig", "houdini.rig_pose"],
}
ORDER_PROPOSAL: dict[str, list[str]] = {
    "blender": ["blender.apply_transforms", "blender.add_bones", "blender.symmetrize", "blender.bone_roll", "blender.ik_constraint", "blender.copy_rotation", "blender.armature_deform_parent", "blender.fk_posing"],
    "maya": ["maya.freeze_transformations", "maya.create_joints", "maya.name_joints", "maya.orient_joint", "maya.mirror_joint", "maya.ik_handle", "maya.pole_vector", "maya.create_controllers",
             "maya.group_controls", "maya.parent_constraint", "maya.bind_skin", "maya.paint_skin_weights"],
    "houdini": ["houdini.skeleton_sop", "houdini.rig_doctor", "houdini.orient_joints", "houdini.skeleton_mirror", "houdini.ik_chains", "houdini.apex_autorig", "houdini.capture_weights", "houdini.rig_pose"],
}
# The name of each stage as the learner reads it: the application's own words and the key action, not the generic feature-catalog name (which said "clear history" for Blender, a Maya idea, and
# hid "then Joint Deform" behind "bind mesh"). Wording only: every fact stays in the knowledge base entry the stage is built from.
LABELS = {
    "blender.apply_transforms": "Apply the object's transforms (Object > Apply)", "blender.add_bones": "Add the bones in Edit Mode", "blender.symmetrize": "Mirror the bones to the other side (Symmetrize)",
    "blender.bone_roll": "Fix the bone roll", "blender.fk_posing": "Test the rig by posing the bones (Pose Mode)", "blender.armature_deform_parent": "Attach the mesh to the armature (Armature Deform with Automatic Weights)",
    "blender.ik_constraint": "Add IK to the limb (Inverse Kinematics constraint)", "blender.copy_rotation": "Drive a bone with a Copy Rotation constraint",
    "maya.freeze_transformations": "Freeze transformations on the mesh and delete its history", "maya.create_joints": "Create the joints (Skeleton > Create Joints)", "maya.name_joints": "Name the joints",
    "maya.orient_joint": "Orient the joints (Skeleton > Orient Joint)", "maya.mirror_joint": "Mirror the joints (Skeleton > Mirror Joints)", "maya.bind_skin": "Bind the mesh to the skeleton (Smooth Bind)",
    "maya.paint_skin_weights": "Paint the skin weights", "maya.ik_handle": "Add an IK handle (Skeleton > Create IK Handle)", "maya.pole_vector": "Fix the knee direction with a pole vector",
    "maya.create_controllers": "Make control curves", "maya.group_controls": "Group the controls", "maya.parent_constraint": "Constrain the joints to the controls (Constrain > Parent)",
    "houdini.skeleton_sop": "Draw the skeleton (Skeleton SOP)", "houdini.rig_doctor": "Check the skeleton (Rig Doctor)", "houdini.orient_joints": "Orient the joints (Orient Joints)",
    "houdini.skeleton_mirror": "Mirror the skeleton (Skeleton Mirror)", "houdini.capture_weights": "Bind the geometry (Joint Capture, then Joint Deform)", "houdini.ik_chains": "Add IK (IK Chains)",
    "houdini.apex_autorig": "Build the rig and its controls (APEX AutoRig)", "houdini.rig_pose": "Pose the rig (Rig Pose)",
}
PREP = {"blender": ["blender.apply_transforms"], "maya": ["maya.freeze_transformations"], "houdini": []}        # what to do BEFORE rigging, where the knowledge base has it
DONE_AFTER_SKELETON = {"blender": {"blender.apply_transforms", "blender.add_bones"}, "maya": {"maya.freeze_transformations", "maya.create_joints"},       # topics a learner who "made the skeleton" is past:
                       "houdini": {"houdini.skeleton_sop"}}                                                                                          # preparing the mesh and making the joints (naming, orienting, mirroring still come next)

_APP = {"blender": re.compile(r"\bblender\b", re.I), "maya": re.compile(r"\bmaya\b", re.I), "houdini": re.compile(r"\b(?:houdini|kinefx|apex)\b", re.I)}
_START = re.compile(r"\bfrom scratch\b|\bteach me\b[^?]*\b(?:rig|rigging)\b|\b(?:where|how)\b[^?]*\b(?:start|begin|get started|getting started)\b|\bgetting started\b|\bfirst steps?\b|\bnew to\b[^?]*\b(?:rig|rigging)\b|\bbeginner\b[^?]*\b(?:rig|rigging)\b", re.I)
_BEFORE = re.compile(r"\bbefore\b[^?]*\b(?:rig|rigging)\b", re.I)
# An explicit request for STEPS ("give me the steps to ...", "step by step", "walk me through"). A plain "how do i ..." is not one: it keeps its text answer.
_STEPS = re.compile(r"\b(?:give|show|tell|list|need|want|get|write)\b[^?]{0,25}\b(?:steps|a plan|a walk-?through|instructions)\b|\bstep[- ]by[- ]step\b|\bwalk me through\b|\bguide me (?:through|to)\b|\bsteps (?:to|for|of)\b", re.I)
_WHOLE_RIG = re.compile(r"\b(?:rig|rigging|rigged)\b[^?]*\b(?:character|biped|human|body|model)\b|\b(?:whole|entire|full|complete)\s+rig(?:ging)?\b", re.I)
_AFTER = re.compile(r"\b(?:made|created|finished|done|built|have|did|completed)\b[^?]*\b(?:skeleton|joints?|bones?|armature)\b[^?]*\b(?:next|now what|then what)\b", re.I)


def plan_request(text: str) -> str | None:
    """"start", "before" (what to do before rigging) or "after_skeleton" when the text asks for a starter plan, else None."""
    if _AFTER.search(text):
        return "after_skeleton"
    if _BEFORE.search(text):
        return "before"
    if _START.search(text):
        return "start"
    return None


def steps_request(text: str) -> bool:
    return bool(_STEPS.search(text))


def app_in(text: str, default: str | None = None) -> str | None:
    found = [a for a, rx in _APP.items() if rx.search(text)]
    return found[0] if len(found) == 1 else default


def _first_sentence(text: str, limit: int = 180) -> str:
    s = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0].rstrip(".")
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "..."


def _clean_path(path: str) -> str:
    """The UI element the overlay should look for: the menu path without notes in brackets ("(options box)", "(Shift-N)", "(Shift-A in Edit Mode)")."""
    return re.sub(r"\s*\([^)]*\)", "", path).strip() or path


def _entry_steps(e: Entry, app: str, start_order: int, group_no: int, feature_names: dict[str, str]) -> list[Step]:
    fid = next((f for f in e.features if f in feature_names), None)
    label = LABELS.get(e.id) or (feature_names.get(fid) if fid else None) or e.id.split(".", 1)[-1].replace("_", " ").capitalize()
    path = next((u["path"] for u in e.ui), None)
    items = [(_first_sentence(s.text), s) for s in e.outline] or [(label + (f": {path}" if path else ""), None)]
    steps: list[Step] = []
    for i, (goal, stmt) in enumerate(items):
        order = start_order + i
        how = [HowTo(text=stmt.text, support="catalog", evidence=f"knowledge base {e.id} ({stmt.tier})")] if stmt else []
        if i == 0 and e.prerequisites:
            how = [HowTo(text=e.prerequisites[0], support="catalog", evidence=f"knowledge base {e.id}"), *how]
        check = [HowTo(text=v.text, support="catalog", evidence=f"knowledge base {e.id} ({v.tier})") for v in e.verify[:1]] if i == len(items) - 1 else []
        steps.append(Step(
            id=f"s{order:02d}", order=order, goal=goal, feature_id=fid, kind="mechanics", support="unknown", provenance="catalog_template", review_status="drafted_automatically",
            source_refs=[f"kb:{e.id}"], how_to=how, check=check, group_id=f"g{group_no:02d}", group=label,
            actions=[Action(verb="open_menu", ui_element=_clean_path(path))] if (i == 0 and path) else []))
    return steps


def starter_plan(app: str, mode: str = "start", kb: Knowledge | None = None, order: dict[str, list[str]] | None = None) -> StepList | None:
    """The starter step list for `app`, or None when the knowledge base has nothing for that mode (for example "before rigging" in Houdini)."""
    kb = kb or load_knowledge()
    by_id = {e.id: e for e in kb.entries}
    ids = PREP[app] if mode == "before" else (order or ORDER)[app]
    entries = [by_id[i] for i in ids if i in by_id]
    if mode == "after_skeleton":
        entries = [e for e in entries if e.id not in DONE_AFTER_SKELETON[app]]
    if not entries:
        return None
    names = {f.id: f.name for f in load_catalog().features}
    steps: list[Step] = []
    for n, e in enumerate(entries, start=1):
        steps += _entry_steps(e, app, len(steps) + 1, n, names)
    title = {"start": f"Starter plan for rigging a character in {app.capitalize()}", "before": f"Before you rig in {app.capitalize()}",
             "after_skeleton": f"After the skeleton in {app.capitalize()}"}[mode]
    return _finish(app, title, steps)


def _finish(app: str, title: str, steps: list[Step]) -> StepList:
    sl = StepList(source_type="goal_draft", app=app, title=title, steps=steps, prompt_version="starter-plan-v1")
    derive_state(sl)
    sanitize_and_annotate(sl, get_profile(app))
    check_structure(sl)
    return sl


def plan_from_entries(app: str, entries: list[Entry], title: str | None = None) -> StepList | None:
    """A step list for just these knowledge-base topics (the ones a question matched), in the teaching order of `app`. None when none of them has anything to build steps from."""
    order = {i: n for n, i in enumerate(ORDER[app])}
    entries = sorted([e for e in entries if app in e.apps], key=lambda e: order.get(e.id, len(order)))
    if not entries:
        return None
    names = {f.id: f.name for f in load_catalog().features}
    steps: list[Step] = []
    for n, e in enumerate(entries, start=1):
        steps += _entry_steps(e, app, len(steps) + 1, n, names)
    return _finish(app, title or "Steps for " + " and ".join(g for g in dict.fromkeys(s.group for s in steps) if g).lower(), steps)


_NOT_TOPIC = frozenset({"give", "show", "tell", "list", "need", "want", "get", "write", "step", "plan", "instruction", "implement", "walk", "through", "guide", "please", "me", "how", "do",
                        "blender", "maya", "houdini", "make", "making", "create", "creating", "set", "setup"})


def _topic_score(e: Entry, q: frozenset[str], rank: int) -> tuple[float, int, int]:
    """How well a topic's own names (everyday phrases, menu paths, id words) cover the words of the question: (coverage, shorter name first, teaching order first). Facts and outlines are not
    used here: they mention "ik" or "x" in passing and made unrelated topics tie."""
    from .rigging_knowledge import _tokens
    names = [*e.phrases, *(u["path"] for u in e.ui), e.id.split(".", 1)[-1].replace("_", " ")]
    best = (0.0, 0)
    for n in names:
        w = _tokens(n)
        if w and q:
            best = max(best, (len(q & w) / len(q), -len(w)))
    return best[0], best[1], -rank


def topic_bundle(text: str, app: str, kb: Knowledge | None = None) -> AnswerBundle | None:
    """"Give me the steps to add IK": the knowledge-base topics whose names match the question, as a step list. None when nothing matches (then the model answers in text)."""
    from .rigging_knowledge import _tokens
    kb = kb or load_knowledge()
    q = _tokens(text) - _NOT_TOPIC                                       # the words that ask for steps, and the application's name, say nothing about the topic
    order = {i: n for n, i in enumerate(ORDER[app])}
    scored = sorted(((_topic_score(e, q, order.get(e.id, len(order))), e) for e in kb.entries if app in e.apps and (e.outline or e.ui)), key=lambda t: t[0], reverse=True)
    best = scored[0][0][0] if scored else 0.0
    entries = [e for sc, e in scored[:2] if best >= 0.5 and sc[0] == best]      # the best matches only, at most two
    sl = plan_from_entries(app, entries)
    if sl is None:
        return None
    return _bundle(sl, "Here are the steps for what you asked, from GuideWire's knowledge base: " + ", then ".join(g.lower() for _, g, _ in sl.groups) + ".")


def starter_bundle(text: str, app: str | None, kb: Knowledge | None = None) -> AnswerBundle | None:
    """The answer to a "where do I start" question, or None when `text` is not one (or the knowledge base has nothing for it). Asks which application when it is not known."""
    mode = plan_request(text)
    asks_steps = steps_request(text)
    if mode is None and asks_steps and _WHOLE_RIG.search(text):
        mode = "start"
    if mode is None and not asks_steps:
        return None
    app = app_in(text, app)
    if app not in ORDER:
        return AnswerBundle(kind="clarification", route="clarify", clarification="Which application do you use: Blender, Maya or Houdini? The first steps differ completely between them.",
                            reasons=["starter plan: application unknown"])
    if mode is None:                                                    # steps asked for a topic, not for the whole rig
        return topic_bundle(text, app, kb)
    sl = starter_plan(app, mode, kb)
    if sl is None:
        return None
    groups = sl.groups
    intro = {"start": f"Starter plan for rigging a character in {app.capitalize()}: {len(groups)} stages in the usual order, {len(sl.steps)} small steps in all.",
             "before": f"Before you rig in {app.capitalize()}, do this first:",
             "after_skeleton": f"With the skeleton done, the usual next stages in {app.capitalize()} are these {len(groups)}, {len(sl.steps)} small steps in all."}[mode]
    return _bundle(sl, intro, f"starter plan ({mode})", gap=True)


# What the knowledge base cannot source yet, said in the answer. Checked 2026-11-09: the Blender manual page "Adding Bones" covers adding bones in Edit Mode but not creating the armature object, and no
# official page for that was found; the Rigging menu set (F3) is named by two official Maya help pages already in the knowledge base (mirror joints, go to the bind pose).
APP_NOTES = {
    "blender": "Before the first step, an armature object has to exist in the scene (the steps add bones to it in Edit Mode); the knowledge base has no sourced step for creating that object yet.",
    "maya": "In Maya the Skeleton, Skin and Constrain menus used here are in the Rigging menu set (F3), as the official help pages for mirroring joints and going to the bind pose show.",
    "houdini": "Work at SOP level, in a geometry network: the KineFX nodes used here are SOPs.",
}


def _bundle(sl: StepList, intro: str, why: str = "topic steps", gap: bool = False) -> AnswerBundle:
    caveats = ["Drafted from GuideWire's knowledge base, not from a tutorial: it is the usual order, and a tutorial may do it differently."]
    if gap:
        caveats.append(APP_NOTES[sl.app])
        caveats.append("The knowledge base does not yet cover scene units and importing or creating the mesh; make sure your character mesh is ready before you start.")
    return AnswerBundle(kind="procedure", route="rigging_knowledge", steps=sl, trust="catalog", explanations=[Explanation(text=intro, provenance="catalog_template")], caveats=caveats,
                        assumptions=["You already have a finished character mesh."] if gap else [], reasons=[f"{why} built from {len(sl.groups)} knowledge base topics, no model called"])
