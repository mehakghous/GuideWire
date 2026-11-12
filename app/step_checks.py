"""What the app can really check for a step, in words a learner understands.

`OBSERVABLE_KINDS` are the predicate kinds that `ingestion/evaluator.py` can judge from an observed application state. The kinds added in
schema 0.11 (name_exists, attribute_exists, node_count) are checked by Ayesha's verification harness against saved scenes, but the app's
evaluator does not read them yet, so for the app they are "not checkable" until a source of that state exists.
tests/test_app_step_checks.py keeps this list in step with the evaluator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.step_record import Step

OBSERVABLE_KINDS = frozenset({"mode", "active_tool", "workspace", "selection_type", "panel_open", "node_exists", "property_equals"})

Level = Literal["checkable", "partial", "manual"]

MANUAL_TEXT = "Manual step: GuideWire cannot check it, you confirm it yourself."
CHECKABLE_TEXT = "Checkable step: GuideWire can verify it from the application state once it can read that state; until then you confirm it."


@dataclass(frozen=True)
class Checkability:
    level: Level
    text: str


def checkability(step: Step) -> Checkability:
    """Manual (nothing to check, or a craft step), partial (some of its expected state cannot be read by the app) or checkable."""
    if not step.verifiable:
        return Checkability("manual", MANUAL_TEXT)
    unreadable = sorted({p.kind for p in step.expected_state if p.kind not in OBSERVABLE_KINDS})
    if not unreadable:
        return Checkability("checkable", CHECKABLE_TEXT)
    if all(p.kind not in OBSERVABLE_KINDS for p in step.expected_state):
        return Checkability("manual", f"Manual step: its check ({', '.join(unreadable)}) is not something the app can read yet, so you confirm it yourself.")
    return Checkability("partial", f"Partly checkable: GuideWire can verify part of it, but not {', '.join(unreadable)}, so you confirm the rest yourself.")
