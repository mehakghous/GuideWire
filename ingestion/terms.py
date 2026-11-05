"""Cross-application vocabulary (SRS XAPP-06) and a cautious feature suggester.

CONCEPTS maps the words the three applications use for the same thing onto one canonical word, so a Blender "bone", a Maya "joint" and a Houdini
"joint" match the same feature. `suggest_feature` offers a catalog feature for a step's wording; it returns None when unsure, because a wrong
feature id sends the learner to the wrong guidance. A model (part 5) or a person can set the id too; this is only the rule-based fallback.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .features import APPS, Feature, load_catalog

# canonical word -> what each application calls it (as written in the feature matrix)
CONCEPTS: dict[str, dict[str, str]] = {
    "joint": {"blender": "bone", "maya": "joint", "houdini": "joint"},
    "skeleton": {"blender": "armature", "maya": "skeleton", "houdini": "skeleton"},
    "bind": {"blender": "parent with automatic weights", "maya": "bind skin", "houdini": "bone capture"},
    "weights": {"blender": "vertex groups", "maya": "skin weights", "houdini": "capture attributes"},
    "ik": {"blender": "ik constraint", "maya": "ik handle", "houdini": "ik chains"},
    "keyframe": {"blender": "keyframe", "maya": "key", "houdini": "key"},
    "blend shape": {"blender": "shape key", "maya": "blend shape", "houdini": "blendshape"},
    "layers": {"blender": "nla tracks", "maya": "animation layers", "houdini": "override layers"},
    "constraint": {"blender": "constraint", "maya": "constraint", "houdini": "constraint component"},
}
_SYNONYMS = {"bone": "joint", "bones": "joint", "joints": "joint", "armature": "skeleton", "skeletons": "skeleton", "keys": "keyframe",
             "keyframes": "keyframe", "keying": "keyframe", "shape key": "blend shape", "shape keys": "blend shape", "blendshape": "blend shape",
             "vertex groups": "weights", "weight": "weights", "constraints": "constraint", "controls": "control", "controllers": "control", "rename": "name", "renaming": "name", "renamed": "name"}
_STOP = frozenset("a an the of to and or in on for with from by at as is it this that then up your".split())          # create, add, make, set stay: "Create Joints" is two words, not one
USE_KNOWLEDGE = True            # False = catalog wording only (the baseline in measurements)
MIN_SCORE = 0.6
MIN_MARGIN = 0.12
SINGLE_WORD = 0.55              # a one-word reference ("joint", "parent") matches any sentence that mentions it, so it can never be enough on its own (MIN_SCORE is 0.6)


def term(concept: str, app: str) -> str:
    """The word `app` uses for a canonical concept, e.g. term("joint", "blender") -> "bone"."""
    return CONCEPTS[concept][app]


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w       # arcs -> arc, joints -> joint


_KEYBOARD = re.compile(r"\b(?:control|ctrl|shift|alt|command)(?: and (?:control|ctrl|shift|alt))? keys?\b")


@lru_cache(maxsize=4096)
def _tokens(text: str) -> frozenset[str]:
    t = re.sub(r"\bconstraints?\s+(orient|point|scale|aim|parent)\b", r"\1 constraint", text.lower())
    t = re.sub(r"[^a-z0-9]+", " ", _KEYBOARD.sub(" ", t)).strip()           # "press the control and shift key" is the keyboard, not rig controls
    for src, dst in sorted(_SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{re.escape(src)}\b", dst, t)
    return frozenset(_stem(w) for w in t.split() if w not in _STOP and not w.isdigit())


def _score(goal: frozenset[str], feature: Feature, app: str) -> float:
    phrase = re.sub(r"\([^)]*\)", "", feature.support[app].split("–", 1)[-1]).split(";")[0].split(",")[0]     # first tool phrase for this app, no parentheses
    # (reference words, weight): the feature's name, the whole menu path (its menu words also occur in speech about OTHER tools: "go to skeleton and orient joint"),
    # and the tool itself (last menu item), which is the strongest evidence
    refs = ((_tokens(feature.name), 1.0), (_tokens(phrase), 0.9), (_tokens(phrase.split(">")[-1]), 1.1))
    return max((len(goal & r) / len(r) * w * (1.0 if len(r) > 1 else SINGLE_WORD) for r, w in refs if r), default=0.0)


def suggest_feature(text: str, app: str) -> str | None:
    """The catalog feature id whose name or tool phrase best matches `text`, or None when no feature is clearly the best match."""
    if app not in APPS:
        raise ValueError(f"unknown app {app!r}")
    from .rigging_knowledge import load as knowledge
    kb_entry = knowledge().match_phrase(text, app, min_cover=0.75) if USE_KNOWLEDGE else None               # what people actually say, researched (knowledge/rigging_knowledge.json)
    if kb_entry is not None:
        feats = [f for f in kb_entry.features if load_catalog().get(f).support_code(app) != "U"]
        if feats:
            return feats[0]                                                       # the entry lists its primary feature first
    goal = _tokens(text)
    ranked = sorted(((_score(goal, f, app), f.id) for f in load_catalog().features if f.support_code(app) != "U"), reverse=True)
    best, runner = ranked[0], ranked[1]
    if best[0] < MIN_SCORE or best[0] - runner[0] < MIN_MARGIN:
        return None
    return best[1]
