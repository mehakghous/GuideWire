"""Does each step's start state follow from what the earlier steps made? Replays a step list on a simulated scene (a set of node types), offline.

`derive_state` fills a missing start/expected `node_exists` from the knowledge base (`effects` per feature), labelled as derived and never read from the
tutorial. `chain_report` then walks the steps in order: a step that needs a node only a LATER step makes is an order error; a node nothing makes is
assumed to be in the starting scene (said, not an error). Node TYPES only: two joint chains are one "joint", so a duplicate step cannot be told
apart by state (the validator already flags that). It reads step lists; it never touches Maya, Blender or Houdini.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.step_record import StatePredicate, StepList

from .rigging_knowledge import load


def _nodes(preds) -> list[str]:
    return [p.target for p in preds if p.kind == "node_exists"]


def derive_state(sl: StepList) -> int:
    """Add the nodes a step's feature makes/needs when the step names none. Returns how many steps changed. Idempotent; craft steps are left alone."""
    kb, changed = load(), 0
    for st in sl.steps:
        if st.kind != "mechanics" or not st.feature_id:
            continue
        hits = [(e, e.effects[st.feature_id]) for e in kb.for_feature(st.feature_id, sl.app) if st.feature_id in e.effects]
        if not hits:
            continue
        entry, eff = hits[0]
        makes = [] if _nodes(st.expected_state) else [n for n in eff["makes"]]
        needs = [n for n in eff.get("needs", ()) if n not in _nodes(st.start_state) and n not in makes]
        if not (makes or needs):
            continue
        st.expected_state += [StatePredicate(kind="node_exists", target=n) for n in makes]
        st.start_state += [StatePredicate(kind="node_exists", target=n) for n in needs]
        st.flags.append(f"expected/start state ({', '.join(makes + needs)}) derived from the knowledge base ({entry.id}), not read from the tutorial")
        start = {(p.kind, p.target) for p in st.start_state}
        st.verifiable = any((p.kind, p.target) not in start for p in st.expected_state)
        changed += 1
    return changed


@dataclass
class ChainReport:
    total: int = 0                                          # mechanics steps
    verifiable: int = 0                                     # of those, with an expected state that is not already true at the start
    order_errors: list[str] = field(default_factory=list)   # "s03 needs joint, but only step s09 makes it"
    order_steps: dict[str, list[str]] = field(default_factory=dict)   # step id -> its order error, so the step itself can carry the warning
    assumed: dict[str, str] = field(default_factory=dict)   # node type -> first step that needs it with no step making it
    uncheckable: list[str] = field(default_factory=list)    # mechanics step ids with nothing a program could verify

    def render(self) -> str:
        pct = f"{100 * self.verifiable / self.total:.0f}%" if self.total else "n/a"
        out = [f"steps with a verifiable end state: {self.verifiable}/{self.total} ({pct})"]
        out += [f"  ORDER: {e}" for e in self.order_errors]
        out += [f"  assumed already in the scene: {n} (first needed by {s})" for n, s in self.assumed.items()]
        if self.uncheckable:
            out.append("  nothing to verify for: " + ", ".join(self.uncheckable))
        return "\n".join(out)


def chain_report(sl: StepList) -> ChainReport:
    r = ChainReport()
    made = [{p.target for p in st.expected_state if p.kind == "node_exists"} - set(_nodes(st.start_state)) for st in sl.steps]
    scene: set[str] = set()
    for i, st in enumerate(sl.steps):
        for n in _nodes(st.start_state):
            if n in scene:
                continue
            later = next((sl.steps[j].id for j in range(i + 1, len(sl.steps)) if n in made[j]), None)
            if later:
                r.order_errors.append(f"{st.id} needs {n}, but only step {later} makes it")
                r.order_steps.setdefault(st.id, []).append(f"needs {n}, but only step {later} makes it")
            else:
                r.assumed.setdefault(n, st.id)
            scene.add(n)                                    # reported once
        scene |= made[i]
        if st.kind == "mechanics":
            r.total += 1
            r.verifiable += st.verifiable
            if not st.verifiable:
                r.uncheckable.append(st.id)
    return r


def flag_order_errors(sl: StepList) -> ChainReport:
    """Put each order error on the step that has it, once, and return the report. Run after validation so a re-run adds nothing."""
    r = chain_report(sl)
    for st in sl.steps:
        if st.id in r.order_steps:
            flag = f"order: this step {'; '.join(r.order_steps[st.id])}; the tutorial may be out of order or a step is missing before it"
            if flag not in st.flags:
                st.flags.append(flag)
    return r
