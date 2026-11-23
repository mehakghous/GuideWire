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
    "node_counts": {"ARMATURE": 1, "BONE": 9},   # node_exists reads "nodes" (the types present); node_count reads this
    "node_names": ["Cube", "Armature"],           # name_exists
    "attributes": {"Cube.my_prop": True},         # attribute_exists, only for paths that were tested
    "probe": True,                                # node_count, name_exists, attribute_exists, operator_ran are judged only when set
    "history": [{"id": "mesh.loopcut_slide", "name": "Loop Cut and Slide"}],   # operator_ran: the application's own operator list (what the learner just did)
}
"""
from __future__ import annotations

import re
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


def _norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


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
    if p.kind in ("node_count", "name_exists", "attribute_exists", "operator_ran") and not obs.get("probe"):
        return _MISSING        # the screen cannot see these: only an application probe can (it sets obs["probe"])
    if p.kind == "operator_ran":
        hist = obs.get("history", _MISSING)             # only operators the application records (those that can be undone or repeated) appear: absence is "not seen", never proof it was not done
        if hist is _MISSING:
            return _MISSING
        return any(h.get("id") == p.target for h in hist)
    if p.kind == "node_count":
        counts = obs.get("node_counts", _MISSING)       # {"ARMATURE": 1, "BONE": 9}: how many of each node type
        if counts is _MISSING or p.value is None:
            return _MISSING
        have = {_norm(k): v for k, v in counts.items()}
        return float(have.get(_norm(p.target), 0)) >= float(p.value)
    if p.kind == "name_exists":
        names = obs.get("node_names", _MISSING)         # exact names, as the Outliner shows them
        return _MISSING if names is _MISSING else p.target.strip() in set(names)
    if p.kind == "attribute_exists":
        attrs = obs.get("attributes", _MISSING)         # {"object.attribute": True/False}, only for paths that were tested
        if attrs is _MISSING or p.target not in attrs:
            return _MISSING
        return bool(attrs[p.target])
    return _MISSING


def _same(a: StatePredicate, b: StatePredicate) -> bool:
    return (a.kind, a.target, a.value) == (b.kind, b.target, b.value)


def _shows_change(p: StatePredicate, obs: dict[str, Any], entry: dict[str, Any] | None) -> bool | object:
    """For an existence or count predicate that was ALREADY true when the step started (the same one is in start_state), whether the observed state shows the step's action changed anything. Being true now is no evidence:
    step 9 ("Add > Armature") lists `node_exists ARMATURE` as both its start and its result, and used to count as done the moment it began. A count that went UP since the step began is evidence; anything
    else cannot be told, so it is unobservable (the learner says Done). `entry` is the observed state taken when the step started."""
    if p.kind in ("node_exists", "node_count") and entry is not None and obs.get("node_counts") is not None and entry.get("node_counts") is not None:
        have, before = {_norm(k): v for k, v in obs["node_counts"].items()}, {_norm(k): v for k, v in entry["node_counts"].items()}
        return have.get(_norm(p.target), 0) > before.get(_norm(p.target), 0)
    return _MISSING


def _held_at_entry(p: StatePredicate, entry: dict[str, Any] | None) -> bool:
    """Whether an existence or count predicate was already true in the state observed when the step began. This is read from what was SEEN, not from the step's own `start_state`: a model that
    writes `node_exists BONE` as the result of "Subdivide" does not list it as a start state, yet the single bone from the step before is already there (the step completed itself before the learner did anything)."""
    if not entry:
        return False
    if p.kind == "node_exists":
        return p.target in (entry.get("nodes") or []) or any(_norm(k) == _norm(p.target) and n > 0 for k, n in (entry.get("node_counts") or {}).items())
    if p.kind == "node_count" and p.value is not None:
        return any(_norm(k) == _norm(p.target) and float(n) >= float(p.value) for k, n in (entry.get("node_counts") or {}).items())
    return False


def evaluate_step(step: Step, observed: dict[str, Any], entry: dict[str, Any] | None = None) -> Verdict:
    if not step.expected_state or not step.verifiable:
        return Verdict("unverifiable")
    v = Verdict("unverifiable")
    for p in step.expected_state:
        r = _observe(p, observed)
        if r is True and p.kind in ("node_exists", "node_count") and (any(_same(p, q) for q in step.start_state) or _held_at_entry(p, entry)):
            r = _shows_change(p, observed, entry)             # true before the step began (declared, or seen at entry): not evidence that the step did anything
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


# ---- state-aware guidance: where is the learner relative to this step? (read-only; none of this completes a step)
@dataclass
class Progress:
    """The learner's position in one step, from the observed state. `preconditions_*`: what the step needs to be true BEFORE it makes sense (the mode it starts in), seen unmet or not readable;
    `done`: parts of the action that were seen (implied by the resolved targets: the tool is active, the operator ran); `pending`: implied parts not seen yet; `unobservable`: cannot be read from this state."""
    preconditions_unmet: list[StatePredicate] = field(default_factory=list)
    preconditions_unobservable: list[StatePredicate] = field(default_factory=list)
    done: list[StatePredicate] = field(default_factory=list)
    pending: list[StatePredicate] = field(default_factory=list)
    unobservable: list[StatePredicate] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True when nothing known contradicts starting the step: no precondition is seen unmet."""
        return not self.preconditions_unmet


def implied_state(step: Step) -> list[StatePredicate]:
    """What the step's resolved targets imply was DONE, as predicates: a toolbar tool target implies that tool is active; a key or context-menu target that names an operator implies it ran; a mode target
    that knows its mode implies it. Only what the application can say exactly; nothing for a menu path (a menu leaves no mark) or a viewport item. These are evidence of progress, never a reason to
    complete the step: step 5 selects Scale AND drags a handle."""
    out: list[StatePredicate] = []
    for a in step.actions:
        t = a.target
        if t is None:
            continue
        if t.kind == "tool" and t.id and t.confidence >= 0.8:
            out.append(StatePredicate(kind="active_tool", target=t.id))
        elif t.kind in ("keys", "context_menu") and t.operator and t.confidence >= 0.8 and not t.candidates:
            out.append(StatePredicate(kind="operator_ran", target=t.operator))
        elif t.kind == "mode" and t.mode:
            out.append(StatePredicate(kind="mode", target=t.mode))
    seen: list[StatePredicate] = []
    for p in out:
        if not any(_same(p, q) for q in seen):
            seen.append(p)
    return seen


def progress(step: Step, observed: dict[str, Any]) -> Progress:
    """Preconditions (`start_state`) and implied progress of a step against an observed state. Distinguishes "not true" from "cannot tell": an absent key is unobservable, never unmet."""
    out = Progress()
    for p in step.start_state:
        r = _observe(p, observed)
        if r is _MISSING:
            out.preconditions_unobservable.append(p)
        elif not r:
            out.preconditions_unmet.append(p)
    for p in implied_state(step):
        r = _observe(p, observed)
        if r is _MISSING:
            out.unobservable.append(p)
        elif r:
            out.done.append(p)
        else:
            out.pending.append(p)
    return out
