"""StepEvaluator: pure comparison of a step's expected state with an observed state.

It does not observe anything. `observed` is a plain dict supplied by whoever can read the
application (read-only adapter or vision). Keys that are absent mean "not observable",
which is different from "observed and wrong".

observed = {
    "mode": "EDIT_MESH",
    "active_tool": "builtin.move",
    "workspace": "Modeling",
    "selection_types": ["MESH"],
    "open_panels": ["Properties:Modifiers"],
    "properties": {"object.location.x": 2.0},
}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shared.step_record import StatePredicate, Step

Status = Literal["met", "unmet", "unverifiable"]
_MISSING = object()
_TOL = 1e-4


@dataclass
class Verdict:
    status: Status
    met: list[StatePredicate] = field(default_factory=list)
    unmet: list[StatePredicate] = field(default_factory=list)
    unobservable: list[StatePredicate] = field(default_factory=list)


def _observe(p: StatePredicate, obs: dict[str, Any]) -> bool | object:
    """True/False if the predicate can be judged from obs, _MISSING otherwise."""
    if p.kind in ("mode", "active_tool", "workspace"):
        v = obs.get(p.kind, _MISSING)
        return _MISSING if v is _MISSING else str(v) == p.target
    if p.kind == "selection_type":
        v = obs.get("selection_types", _MISSING)
        if v is _MISSING:
            return _MISSING
        if p.target == "NONE":
            return len(v) == 0
        return p.target in v
    if p.kind == "panel_open":
        v = obs.get("open_panels", _MISSING)
        return _MISSING if v is _MISSING else p.target in v
    if p.kind == "node_exists":
        v = obs.get("nodes", _MISSING)          # node/object types present, e.g. ["joint", "ikHandle"] or ["Skeleton", "Rig Doctor"]
        return _MISSING if v is _MISSING else p.target in v
    if p.kind == "property_equals":
        props = obs.get("properties", _MISSING)
        if props is _MISSING or p.target not in props:
            return _MISSING
        actual = props[p.target]
        if isinstance(p.value, (int, float)) and isinstance(actual, (int, float)):
            return abs(float(actual) - float(p.value)) <= _TOL
        return str(actual) == str(p.value)
    return _MISSING


def evaluate_step(step: Step, observed: dict[str, Any]) -> Verdict:
    if not step.expected_state or not step.verifiable:
        return Verdict("unverifiable")
    v = Verdict("unverifiable")
    for p in step.expected_state:
        r = _observe(p, observed)
        if r is _MISSING:
            v.unobservable.append(p)
        elif r:
            v.met.append(p)
        else:
            v.unmet.append(p)
    if v.unmet:
        v.status = "unmet"
    elif v.met:
        v.status = "met"  # unobservable predicates are reported, not assumed true
    return v
