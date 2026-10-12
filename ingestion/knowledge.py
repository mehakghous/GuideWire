"""Turning catalog entries into shared-schema steps, and checking their prerequisites against OBSERVED state.

Three different things are kept apart on purpose (see the plan, 'source of truth policy'):
- documented procedure: what the Blender manual says (the catalog entry);
- context-validated: checked against the Blender version and known prerequisites;
- observed state: what the running application actually reports (`observed`), which documentation cannot prove.
A step built here says which of these it rests on through `provenance`, `source_refs` and `assumptions`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.step_record import Step, StepList

from .catalog import BY_ID, Operation, Prereq, StepT, version_status
from .evaluator import _MISSING, _observe
from .profiles import BLENDER
from .validate import check_structure, sanitize_and_annotate


def ref(op: Operation) -> str:
    return f"catalog:{op.id}@main"


def make_step(i: int, tpl: StepT, op: Operation, provenance: str, *, goal: str | None = None,
              extra_refs: tuple[str, ...] = (), confidence: float = 0.8, assumptions: tuple[str, ...] = ()) -> Step:
    return Step(
        id=f"s{i:02d}", order=i, goal=goal or tpl.goal, actions=list(tpl.actions),
        start_state=list(tpl.start_state), expected_state=list(tpl.expected_state), alternatives=list(tpl.alternatives),
        confidence=confidence, support="unknown", provenance=provenance,
        source_refs=[ref(op), *extra_refs], assumptions=list(assumptions),
        evidence=[f"catalog entry {op.id}"], review_status="drafted_automatically",
    )


def link_dependencies(steps: list[Step]) -> None:
    """depends_on = the nearest earlier step whose expected_state establishes the mode this step starts from. Deterministic, additive: a step
    with no mode precondition, or whose mode was never established by an earlier step, gets no link (the missing step is NOT invented)."""
    for i, s in enumerate(steps):
        need = [p.target for p in s.start_state if p.kind == "mode"]
        if not need or s.depends_on:
            continue
        for j in range(i - 1, -1, -1):
            modes = [p.target for p in steps[j].expected_state if p.kind == "mode"]
            if modes:                      # the nearest step that sets a mode decides; if it set a DIFFERENT mode, nothing establishes ours
                if modes[0] in need:
                    s.depends_on = [steps[j].id]
                break


def finish(steps: list[Step], source_type: str, *, title: str | None = None, version: str | None = None,
           duration_s: float | None = None, profile=None) -> StepList:
    """Renumber, annotate with the deterministic validators and check structure. Raises ValidationFailure on errors."""
    for n, s in enumerate(steps, 1):
        s.id, s.order = f"s{n:02d}", n
    link_dependencies(steps)
    sl = StepList(source_type=source_type, app="blender", app_version_tutorial=version, title=title,
                  steps=steps, model_id=None, prompt_version="deterministic-v1", video_duration_s=duration_s)
    sanitize_and_annotate(sl, profile or BLENDER, duration_s)
    check_structure(sl, duration_s)
    return sl


@dataclass
class Context:
    prepend_ops: list[str] = field(default_factory=list)     # ops whose step must come first (observed state breaks a prerequisite)
    unmet: list[str] = field(default_factory=list)           # known unmet, cannot be fixed by a step
    unknown: list[str] = field(default_factory=list)         # material prerequisites we cannot tell
    questions: list[str] = field(default_factory=list)


def check_prereq(p: Prereq, observed: dict | None) -> str:
    """'met' | 'unmet' | 'unknown'. Documentation never counts as observation: with no observed state the answer is 'unknown'."""
    if observed is None:
        return "unknown"
    if p.predicate is not None:
        r = _observe(p.predicate, observed)
        if r is not _MISSING:
            return "met" if r else "unmet"
    if p.check is not None:
        r = p.check(observed)
        if r is not None:
            return "met" if r else "unmet"
    return "unknown"


def apply_context(op: Operation, observed: dict | None) -> Context:
    ctx = Context()
    for p in op.prerequisites:
        st = check_prereq(p, observed)
        if st == "unmet":
            if p.established_by:
                ctx.prepend_ops.append(p.established_by)
            else:
                ctx.unmet.append(p.text)
        elif st == "unknown" and p.material:
            ctx.unknown.append(p.text)
    if ctx.unknown:
        ctx.questions.append("Before you start, please confirm: " + " ".join(ctx.unknown))
    return ctx


def how_to_steps(op: Operation, version: str | None, observed: dict | None = None) -> tuple[list[Step], Context, list[str]]:
    """Steps for a how-to request from the op's documented procedure, plus any context step prepended because OBSERVED state
    breaks a prerequisite. Returns (steps, context, caveats)."""
    ctx = apply_context(op, observed)
    steps: list[Step] = []
    for pre in ctx.prepend_ops:
        pop = BY_ID[pre]
        steps.append(make_step(len(steps) + 1, pop.clause, pop, "catalog_context",
                               goal=f"First: {pop.clause.goal[0].lower()}{pop.clause.goal[1:]} (your application is not in the state this needs)",
                               extra_refs=(f"observed:{observed}",) if observed is not None else ()))
    st, note = version_status(op, version)
    assumptions = tuple(f"Assumes: {t}" for t in ctx.unknown)
    for tpl in op.how_to:
        steps.append(make_step(len(steps) + 1, tpl, op, "catalog_template",
                               confidence=0.8 if st == "unverified" else 0.6, assumptions=assumptions))
    caveats = list(op.caveats) + [note] + list(op.unverified)
    return steps, ctx, caveats
