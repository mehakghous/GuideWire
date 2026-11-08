"""Tolerant loading of step files for the app.

Contract rule (agreed with ingestion): the app never fails on a predicate kind it does not recognise. A newer schema may add kinds
(e.g. name_exists, attribute_exists, node_count). Such a predicate is dropped from the step's expected_state and the step is kept,
marked as not checkable: the learner still sees the instruction and the readable check and continues by hand.
"""
from __future__ import annotations

import copy
from typing import Any, get_args

from shared.step_record import PredicateKind, StepList

KNOWN_KINDS = frozenset(get_args(PredicateKind))
NOT_CHECKABLE_FLAG = "not checkable: uses a check this version of the app does not know"


def load_steps(data: dict[str, Any]) -> StepList:
    """Validate a step-list dict, tolerating unknown predicate kinds. Everything else is still validated strictly."""
    data = copy.deepcopy(data)
    for step in data.get("steps", []):
        for key in ("start_state", "expected_state"):
            preds = step.get(key) or []
            kept = [p for p in preds if p.get("kind") in KNOWN_KINDS]
            if len(kept) != len(preds):
                step[key] = kept
                if key == "expected_state":
                    step["kind"] = step.get("kind", "mechanics")
                    flags = list(step.get("flags") or [])
                    if NOT_CHECKABLE_FLAG not in flags:
                        flags.append(NOT_CHECKABLE_FLAG)
                    step["flags"] = flags
                    # a step whose check cannot be read fully is not graded: drop the partial check so it is never marked met by accident
                    step["expected_state"] = []
    return StepList.model_validate(data)
