"""Checks for a step the user types in.

Two layers:
  1. HARD rules (`check_text`): the text is refused with a message. They only catch input that is clearly not a step ("ss", "...", "ok").
  2. SOFT check (`analyse`): Ayesha's written-step parser (`ingestion.text_steps.parse_written`, Blender catalog only) tries to recognise the
     instruction. A recognised step gets its actions and expected state filled in, so the session engine can check it. An unrecognised one is
     still accepted but flagged: it is a manual step GuideWire cannot check. Nothing is rejected only because the catalog does not know it.

Limits, on purpose: two words of nonsense ("asdf qwer") pass the hard rules and are flagged as unrecognised, not blocked; the parser only
knows the operations in the catalog and only for Blender, so Maya and Houdini steps are accepted as manual steps without a recognition check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.text_steps import parse_written
from shared.step_record import Step

MAX_LENGTH = 300
MIN_LETTERS = 4
HINT = "Describe the step in a few words, for example 'Press Tab to enter Edit Mode'."
UNRECOGNISED_FLAG = "not recognised as a Blender action in the catalog: this is a manual step, GuideWire cannot check it automatically"
MULTI_FLAG = "this looks like several instructions in one step: adding them one at a time lets GuideWire check each of them"


class TextRefused(ValueError):
    """The text is not acceptable as a step; the message is safe to show the user."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _recognised_alone(text: str) -> bool:
    """A single word is only accepted if the catalog knows it (for example 'Undo')."""
    try:
        r = parse_written(text)
    except Exception:
        return False
    return bool(r.steps) and not r.unmatched


def check_text(text: str, existing: list[str] | None = None) -> str:
    """Return the cleaned text, or raise TextRefused. `existing` are the goals already in the list (duplicates are refused)."""
    text = " ".join(text.split())
    if not text:
        raise TextRefused("A step needs some text.")
    if len(text) > MAX_LENGTH:
        raise TextRefused(f"A step can be at most {MAX_LENGTH} characters.")
    letters = sum(c.isalpha() for c in text)
    if letters < MIN_LETTERS and not _recognised_alone(text):
        raise TextRefused(f"That is too short to be a step. {HINT}")
    if letters < len(text.replace(" ", "")) / 2:
        raise TextRefused(f"That does not look like a sentence. {HINT}")
    if len(text.split()) == 1 and not _recognised_alone(text):
        raise TextRefused(f"One unrecognised word is not enough. {HINT}")
    if _norm(text) in {_norm(e) for e in existing or []}:
        raise TextRefused("This step is already in the list.")
    return text


@dataclass
class Analysis:
    recognised: bool
    step: Step | None = None                     # the parsed step (actions, expected state, flags) when recognised
    flags: list[str] = field(default_factory=list)


def analyse(text: str, app: str = "blender") -> Analysis:
    """Soft check. Never raises for unrecognised text."""
    if app != "blender":
        return Analysis(False, None, [f"not checked: instruction recognition only exists for Blender, so this is a manual {app} step"])
    try:
        r = parse_written(text)
    except Exception:
        return Analysis(False, None, [UNRECOGNISED_FLAG])
    if not r.steps or r.unmatched:
        return Analysis(False, None, [UNRECOGNISED_FLAG])
    if len(r.steps) > 1:
        return Analysis(True, r.steps[0], list(r.steps[0].flags) + [MULTI_FLAG])
    return Analysis(True, r.steps[0], list(r.steps[0].flags))
