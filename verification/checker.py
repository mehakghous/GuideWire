"""Compare a StepList's expected states with a scene snapshot. Pure Python, no application needed.

Snapshot (JSON, written by snapshot_<app>.py):
  {"app": "blender", "version": "5.2.2", "mode": "OBJECT" | null, "selection_types": ["MESH"], "node_types": {"ARMATURE": 1, "IK": 2},
   "node_names": ["Armature"], "attributes": {"<object.attribute>": true}, "properties": {"<path>": 1.0 | "text" | {"error": "..."}}}
`node_types` keys are whatever the application calls a node/object/constraint type; Houdini adds the type's label ("Rig Doctor") as well as its name.

Limit (v1): every step is compared with the ONE scene given, so this checks the state at the END of a procedure. A step whose state a later step changes
(a mode switch, a rename) can be reported unmet although it was done. Replaying step by step needs a session in the application, which is not built.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from shared.step_record import StatePredicate, Step, StepList

Outcome = Literal["met", "unmet", "cannot_check"]
TOL = 1e-4


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


@dataclass
class PredicateResult:
    predicate: str
    outcome: Outcome
    detail: str = ""


@dataclass
class StepResult:
    step_id: str
    outcome: Literal["met", "unmet", "unverifiable"]       # same words as shared.step_record.StepVerification
    predicates: list[PredicateResult] = field(default_factory=list)

    @property
    def unchecked(self) -> list[PredicateResult]:
        return [p for p in self.predicates if p.outcome == "cannot_check"]


def property_paths(sl: StepList) -> list[str]:
    """The property paths a snapshot must read for this step list (property_equals targets)."""
    return sorted({p.target for st in sl.steps for p in st.expected_state if p.kind == "property_equals"})


def attribute_paths(sl: StepList) -> list[str]:
    """The "object.attribute" paths a snapshot must test for existence (attribute_exists targets)."""
    return sorted({p.target for st in sl.steps for p in st.expected_state if p.kind == "attribute_exists"})


def _label(p: StatePredicate) -> str:
    return f"{p.kind}:{p.target}" + (f"={p.value}" if p.value is not None else "")


def check_predicate(p: StatePredicate, snap: dict) -> PredicateResult:
    lab = _label(p)
    if p.kind == "node_exists":
        want = _norm(p.target)
        have = {_norm(k): v for k, v in snap.get("node_types", {}).items()}
        n = have.get(want, 0)
        return PredicateResult(lab, "met" if n >= 1 else "unmet", f"{n} of this type in the scene" if n else "no node of this type in the scene")
    if p.kind == "node_count":
        want = _norm(p.target)
        have = {_norm(k): v for k, v in snap.get("node_types", {}).items()}
        n = have.get(want, 0)
        return PredicateResult(lab, "met" if n >= float(p.value) else "unmet", f"{n} of this type in the scene (at least {int(float(p.value))} wanted)")
    if p.kind == "name_exists":
        names = snap.get("node_names")
        if names is None:
            return PredicateResult(lab, "cannot_check", "names were not recorded")
        ok = p.target.strip() in set(names)                  # the learner's own name: exact, as the Outliner shows it
        return PredicateResult(lab, "met" if ok else "unmet", "a node with this name exists" if ok else "no node with this exact name")
    if p.kind == "attribute_exists":
        got = (snap.get("attributes") or {}).get(p.target)
        if got is None:
            return PredicateResult(lab, "cannot_check", "attribute was not tested (not in the snapshot request)")
        if isinstance(got, dict):
            return PredicateResult(lab, "cannot_check", f"attribute could not be tested: {got.get('error', 'unknown error')}")
        return PredicateResult(lab, "met" if got else "unmet", "the attribute exists" if got else "no such attribute on that object")
    if p.kind == "mode":
        if snap.get("mode") is None:
            return PredicateResult(lab, "cannot_check", f"{snap.get('app')} reports no interaction mode headlessly")
        ok = _norm(snap["mode"]) == _norm(p.target)
        return PredicateResult(lab, "met" if ok else "unmet", f"scene mode is {snap['mode']}")
    if p.kind == "selection_type":
        sel = snap.get("selection_types")
        if sel is None:
            return PredicateResult(lab, "cannot_check", "selection was not recorded")
        want = _norm(p.target)
        ok = (want == "none" and not sel) or want in {_norm(s) for s in sel}
        return PredicateResult(lab, "met" if ok else "unmet", f"selected: {sel or 'nothing'}")
    if p.kind == "property_equals":
        got = snap.get("properties", {}).get(p.target)
        if got is None:
            return PredicateResult(lab, "cannot_check", "property was not read (not in the snapshot request)")
        if isinstance(got, dict):
            return PredicateResult(lab, "cannot_check", f"property could not be read: {got.get('error', 'unknown error')}")
        try:
            ok = abs(float(got) - float(p.value)) <= TOL
        except (TypeError, ValueError):
            ok = _norm(got) == _norm(p.value)
        return PredicateResult(lab, "met" if ok else "unmet", f"scene value is {got!r}")
    return PredicateResult(lab, "cannot_check", f"{p.kind} needs the screen or a running session, not a saved scene")      # active_tool, workspace, panel_open


def check_step(st: Step, snap: dict) -> StepResult:
    res = [check_predicate(p, snap) for p in st.expected_state]
    if st.kind == "craft" or not res:
        return StepResult(st.id, "unverifiable", res)
    if any(r.outcome == "unmet" for r in res):
        return StepResult(st.id, "unmet", res)
    if any(r.outcome == "met" for r in res):
        return StepResult(st.id, "met", res)               # every predicate that could be read holds; `unchecked` lists the rest
    return StepResult(st.id, "unverifiable", res)


def check_steplist(sl: StepList, snap: dict) -> list[StepResult]:
    if snap.get("app") != sl.app:
        raise ValueError(f"snapshot is from {snap.get('app')!r} but the step list is for {sl.app!r}")
    return [check_step(st, snap) for st in sl.steps]


def render(results: list[StepResult], sl: StepList) -> str:
    goals = {s.id: s.goal for s in sl.steps}
    out = []
    for r in results:
        out.append(f"{r.step_id} [{r.outcome}] {goals.get(r.step_id, '')}")
        out += [f"    {p.outcome:12} {p.predicate}  ({p.detail})" for p in r.predicates]
    n = {k: sum(r.outcome == k for r in results) for k in ("met", "unmet", "unverifiable")}
    out.append(f"{n['met']} met, {n['unmet']} unmet, {n['unverifiable']} nothing checkable, of {len(results)} steps")
    return "\n".join(out)
