"""Which bone does "do the same thing with this bone" mean?

In the Blender leg IK tutorial (PctSMB-RGsM, 4:31) the instructor parents the foot to the ankle controller, then says "we can do the same thing with this bone", selects the OTHER controller (the knee
controller, the free bone at the left of the leg) and parents it to the ankle controller too. The written step said "toe bone": the model invented a name from the layout of the rig, and the learner parented
the wrong bone.

A second look at the video does not fix this. It was tried (a clip of the step, with the list of bones already made, asked which bone is selected): the answers were "the toe bone" (confidently, with a
plausible description) and "part of the leg chain" (describing another minute of the video). The selected bone is a few orange pixels in a low-resolution screen recording. So the step is not made more specific
than the instructor was. When all he says is "do the same thing with this bone" and the step names a body part he never said, the step is rewritten as what he said: the same operation on the OTHER bone of
the same kind, the one not used in the previous step. A note says what was changed, where in the video to look, and what the model had written.
"""
from __future__ import annotations

import re

from shared.step_record import Step, StepList

from .validate import inferred_names

_ROLE_WORDS = ("toe", "hip", "knee", "ankle", "foot", "thigh", "shin", "heel", "pelvis", "spine", "wrist", "elbow", "shoulder")
_BONE_ID = re.compile(r"\s*\((?:Bone|Armature)\.\d+\)", re.I)       # "(Bone.004)": the number the model read or made up for the bone it named
_KIND = re.compile(r"controller|control bone|control\b|pole target|ik target|handle", re.I)


def _kind_of(previous: Step) -> str:
    """The word for the other bone: "controller bone" when the previous step worked on a controller, else just "bone"."""
    text = " ".join([previous.goal, *(h.text for h in previous.how_to)])
    return "controller bone" if _KIND.search(text) else "bone"


def _replace(text: str, word: str, new: str) -> str:
    def sub(m: re.Match) -> str:
        article = m.group(1) or ""
        plural = (m.group(2) or "").strip().lower() == "bones"
        phrase = new + ("s" if plural else "")
        return article + (phrase if article or not m.group(0)[:1].isupper() else phrase[:1].upper() + phrase[1:])
    return re.sub(r"\b(the\s+)?" + re.escape(word) + r"(\s+bones?)?\b", sub, text, count=0, flags=re.I)


def _first_word(step: Step, words: list[str]) -> str | None:
    """The invented word in the line that SELECTS the pointed-at bone ("Select the toe bone"): the first how-to line that starts with select, click, pick or choose and has one. A word in a later line
    ("Hold Shift, select the foot IK controller bone") names the bone it is parented to, which the instructor does not point at, so it is left alone."""
    for line in (h.text for h in step.how_to):
        if not re.match(r"\s*(select|click|pick|choose)\b", line, re.I):
            continue
        hits = [(m.start(), w) for w in words for m in [re.search(r"\b" + w + r"\b", line, re.I)] if m]
        if hits:
            return min(hits)[1]
    return None


def resolve_repeats(sl: StepList) -> list[str]:
    """Rewrite every step that is a "same thing with this bone" repeat and names a body part nobody said. Returns the ids changed. Mutates the step list (fresh model output only)."""
    from .extract import _mmss
    changed: list[str] = []
    for i, step in enumerate(sl.steps):
        words = inferred_names(step)
        if not words or i == 0:
            continue
        word = _first_word(step, words)
        if word is None:
            continue
        new = f"other {_kind_of(sl.steps[i - 1])}"
        first = True
        for h in step.how_to:
            if re.search(r"\b" + word + r"\b", h.text, re.I):
                h.text = _BONE_ID.sub("", _replace(h.text, word, new + (" (the one you did not use in the previous step)" if first else "")))
                first = False
        for h in step.check:
            if re.search(r"\b" + word + r"\b", h.text, re.I):
                h.text = _BONE_ID.sub("", _replace(h.text, word, new))
        for act in step.actions:
            if act.ui_element and re.search(r"\b" + word + r"\b", act.ui_element, re.I):
                act.ui_element = _replace(act.ui_element, word, new).title()
        step.goal = _BONE_ID.sub("", _replace(step.goal, word, new))
        step.why = f"The same operation as in the previous step, done for the other {new.split(' ', 1)[1]}."          # the model's reason was about the bone it invented
        at = _mmss(step.video_start_s or 0.0)
        for f in [f for f in step.flags if f.startswith("the instructor only says")]:
            step.flags.remove(f)
        step.flags.append(f'at {at} the instructor says "do the same thing with this bone", which is the other {new.split(" ", 1)[1]} (the one not used in the previous step); the model had called it "the {word} bone", '
                          "which he never says: check which bone it is in the video")
        changed.append(step.id)
    return changed
