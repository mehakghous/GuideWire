"""What the app can really check for a step, in words a learner understands.

`OBSERVABLE_KINDS` are the predicate kinds that `ingestion/evaluator.py` can judge from an observed application state. The kinds added in
schema 0.11 (name_exists, attribute_exists, node_count) are checked by Ayesha's verification harness against saved scenes, but the app's
evaluator does not read them yet, so for the app they are "not checkable" until a source of that state exists.
tests/test_app_step_checks.py keeps this list in step with the evaluator.

The text never shows an internal kind name to the learner: `KIND_PHRASES` says what each unreadable kind means in plain words.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.step_record import Step

OBSERVABLE_KINDS = frozenset({"mode", "active_tool", "workspace", "selection_type", "panel_open", "node_exists", "property_equals"})

KIND_PHRASES = {
    "name_exists": "that a node has the name you gave it",
    "attribute_exists": "that an attribute was added",
    "node_count": "how many nodes of a type exist",
}

Level = Literal["checkable", "partial", "manual"]

BADGES = {"checkable": "Checkable", "partial": "Partly checkable", "manual": "You confirm"}
NOTHING_TEXT = "There is nothing GuideWire can check for this step."
CRAFT_TEXT = "It is judged by eye, so GuideWire does not grade it."
CHECKABLE_TEXT = "GuideWire can check this step once it can read the application state."


@dataclass(frozen=True)
class Checkability:
    level: Level
    text: str

    @property
    def badge(self) -> str:
        return BADGES[self.level]

    @property
    def full(self) -> str:
        """Badge and explanation as one sentence, for places with no room for a heading."""
        return f"{self.badge}: {self.text}"


def _phrase(kinds: list[str]) -> str:
    parts = [KIND_PHRASES.get(k, k.replace("_", " ")) for k in kinds]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def checkability(step: Step) -> Checkability:
    """Manual (nothing to check, or a craft step), partial (some of its expected state cannot be read by the app) or checkable."""
    if step.kind == "craft":
        return Checkability("manual", CRAFT_TEXT)
    if not step.verifiable:
        return Checkability("manual", NOTHING_TEXT)
    unreadable = sorted({p.kind for p in step.expected_state if p.kind not in OBSERVABLE_KINDS})
    if not unreadable:
        return Checkability("checkable", CHECKABLE_TEXT)
    if all(p.kind not in OBSERVABLE_KINDS for p in step.expected_state):
        return Checkability("manual", f"GuideWire cannot yet see {_phrase(unreadable)}.")
    return Checkability("partial", f"It cannot yet see {_phrase(unreadable)}, so you confirm that part.")
