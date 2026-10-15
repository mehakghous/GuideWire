"""What does the person actually want to achieve? Most learners do not know the words "inverse kinematics", "skinning" or "joint orientation".
They say "make the legs move properly" or "switch between two ways of controlling a leg". This module reads such sentences as OUTCOMES and maps each to the rigging
areas it needs (the feature catalog's categories), the body part involved, and plain search words for finding a tutorial. It keeps the request narrow: "move its feet"
is a leg-control question, not "teach me the whole rig". A request that could mean substantially different tutorials gets ONE short question instead of a guess.

Rule-based and deliberately small: a phrase table, easy to read and extend. Anything it does not recognise falls through to the keyword stages in rigging_discovery.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Interpretation:
    label: str = ""                                    # what we think they want, in plain words ("control the legs with IK/FK")
    areas: tuple[str, ...] = ()                        # feature-catalog category codes the outcome needs
    features: tuple[str, ...] = ()                     # specific catalog features it clearly needs
    words: tuple[str, ...] = ()                        # plain search words (what tutorial titles actually say)
    part: str | None = None                            # leg | arm | hand | spine | neck | head | tail
    narrow: bool = False                               # a part or a single outcome was named, so do not expand to a whole-character rig
    clarify: str | None = None                         # one short question, when the answer changes which tutorial is right
    notes: list[str] = field(default_factory=list)     # how we read the request, shown to the person so a wrong reading is easy to correct


_PARTS = [
    ("leg", re.compile(r"\b(?:legs?|feet|foot|knees?|ankles?|thighs?|toes?)\b", re.I)),
    ("arm", re.compile(r"\b(?:arms?|elbows?|wrists?|shoulders?)\b", re.I)),
    ("hand", re.compile(r"\b(?:hands?|fingers?|thumbs?)\b", re.I)),
    ("spine", re.compile(r"\b(?:spine|back|torso|hips?)\b", re.I)),
    ("neck", re.compile(r"\b(?:neck|head)\b", re.I)),
    ("tail", re.compile(r"\btails?\b", re.I)),
]
_WHOLE = re.compile(r"\b(?:biped|humanoid|whole|entire|full|complete|full.?body|from scratch)\b", re.I)

# (pattern, label, areas, features, search words). Checked in order; every matching row contributes.
_OUTCOMES: list[tuple[re.Pattern, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    (re.compile(r"\b(?:switch|toggle|swap|change|flip)\w*\b.{0,40}\b(?:two|2|both|different|between)\b.{0,25}\b(?:ways?|modes?|methods?|types?)\b|\bik\s*/?\s*fk\b|\bfk\s*/?\s*ik\b", re.I),
     "switch a limb between two ways of controlling it (IK/FK)", ("IKFK", "CTRL"), ("IKFK-06",), ("ik", "fk", "switch")),
    (re.compile(r"\b(?:move|moving|position|place|plant|control|pose|posing)\b.{0,30}\b(?:feet|foot|legs?)\b|\b(?:feet|foot|legs?)\b.{0,25}\b(?:move|moving|walk|work|follow)\w*", re.I),
     "control the legs/feet so they can be posed", ("IKFK", "CTRL"), ("IKFK-02",), ("ik", "leg", "rig")),
    (re.compile(r"\b(?:arms?|elbows?|knees?|legs?|shoulders?)\b.{0,30}\b(?:bend|bending|twist|deform|stretch|collapse|crease|pinch)\w*|\bbend\w*.{0,25}\b(?:naturally|properly|smoothly|correctly)\b", re.I),
     "make the limb bend without the mesh breaking (skinning)", ("SKIN",), ("SKIN-01", "SKIN-03"), ("skinning", "weight", "paint")),
    (re.compile(r"\b(?:ready|set up|setup|prepare|prep|get)\b.{0,30}\banimat\w*|animation.?ready|rigged? (?:and )?ready", re.I),
     "get the character ready for animation", ("SKEL", "ORNT", "IKFK", "CTRL", "SKIN"), (), ("character", "rigging")),
]
_BROAD_ASK = ("'Ready for animation' can mean two different things: a complete rig with controls an animator can grab, or just the skeleton and skinning so the mesh moves. "
              "Which do you want: (1) a full rig with controls, or (2) skeleton and skinning only?")


def interpret(query: str) -> Interpretation:
    q = query or ""
    out = Interpretation()
    for name, rx in _PARTS:
        if rx.search(q):
            out.part = name
            break
    areas, feats, words, labels = [], [], [], []
    for rx, label, ar, ft, wd in _OUTCOMES:
        if rx.search(q):
            labels.append(label)
            areas += [a for a in ar if a not in areas]
            feats += [f for f in ft if f not in feats]
            words += [w for w in wd if w not in words]
    out.areas, out.features, out.words, out.label = tuple(areas), tuple(feats), tuple(words), "; ".join(labels)
    ready = any("ready for animation" in lb for lb in labels)
    if ready and not out.part and not _WHOLE.search(q) and not re.search(r"\b(?:controls?|skinning|skin|skeleton|ik|fk)\b", q, re.I):
        out.clarify = _BROAD_ASK
    out.narrow = bool(labels) and out.part is not None and not _WHOLE.search(q) and not ready
    if labels:
        out.notes.append(f"I read this as: {out.label}" + (f" (the {out.part})" if out.part else "") + ". If you meant something else, say so.")
        if re.search(r"\bmove\b", q, re.I) and not re.search(r"\b(?:rig|rigging|controls?|animat\w*)\b", q, re.I):
            out.notes.append("'Move' can also mean animating a walk; I assumed you want the limb set up so it can be posed, which is the step before animating.")
    return out
