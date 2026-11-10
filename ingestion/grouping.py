"""Display groups for a step list (schema 0.12: Step.group_id and Step.group).

Extraction writes ATOMIC steps (one small operation each): that is what the overlay points at and what completion detection checks. A beginner does not want 60 lines, so the steps are also
given DISPLAY groups: runs of consecutive steps that serve one goal ("Rename the leg joints"). The steps themselves are never changed, merged or reordered; a group is only a label and an id.

One text-only model call per step list (no video is sent). The answer is checked by code before it is used: every step in exactly one group, in order, each group one run of consecutive steps,
a short label. If the answer breaks a rule the model is asked once more with the problem; if it still does, the list is returned UNGROUPED with a warning, never with a guess.

    grouped = group_steps(step_list, provider)     # provider: any LLMProvider, normally the cost-guarded one (ingestion/budget.py)
"""
from __future__ import annotations

from typing import Any

from shared.step_record import Step, StepList

MAX_GROUP_STEPS = 12     # a group bigger than this is no longer something a beginner can take in at a glance
MAX_LABEL = 80

SYSTEM = """You prepare a tutorial's step list for a beginner. The steps are small, single operations. Put CONSECUTIVE steps that serve one goal into display groups, so the learner sees a short list of goals and can open a group to see its small steps.

Rules:
- Keep the given order. Every step is in exactly one group. A group is a run of consecutive steps: never skip a step and come back to it.
- A group is one learner goal, for example "Create the leg joints", "Rename the leg joints", "Add the IK handle", "Switch to Pose Mode and select the bones". Aim for 2 to 8 steps in a group. A step that is a goal by itself is a group of one.
- Start a new group when the goal changes, when the tutorial moves to a different part of the rig (the other leg, the next controller, a different tool), or when there is a long pause in the times.
- The label is a short imperative phrase of at most 8 words, in the tutorial's own words (the object and tool names it uses). Never invent an operation that is not in the steps.
- Do not rewrite, merge or reorder the steps. You only decide where the groups start and end, and name them.
Return JSON only: {"groups": [{"label": "...", "step_ids": ["s01", "s02"]}]}"""

SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "step_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["label", "step_ids"]}}},
    "required": ["groups"],
}


def _mmss(t: float | None) -> str:
    if t is None:
        return "?"
    t = int(round(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def _prompt(sl: StepList) -> str:
    lines = [f"Application: {sl.app}. Tutorial: {sl.title or 'untitled'}. {len(sl.steps)} steps:"]
    lines += [f"{s.id} [{_mmss(s.video_start_s)}-{_mmss(s.video_end_s)}] {s.goal}" for s in sl.steps]
    return "\n".join(lines)


def check_groups(sl: StepList, raw: dict[str, Any]) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """(groups as (label, step ids), problems). Problems are empty only when the answer obeys every rule."""
    problems: list[str] = []
    ids = [s.id for s in sl.steps]
    groups: list[tuple[str, list[str]]] = []
    for g in raw.get("groups", []) if isinstance(raw, dict) else []:
        label = " ".join(str(g.get("label", "")).split())
        members = [str(x).strip() for x in g.get("step_ids", [])]
        if not label:
            problems.append("a group has no label")
        if len(label) > MAX_LABEL:
            problems.append(f"label too long ({len(label)} characters): {label[:40]}...")
        if not members:
            problems.append(f"group '{label}' has no steps")
        if len(members) > MAX_GROUP_STEPS:
            problems.append(f"group '{label}' has {len(members)} steps, the most allowed is {MAX_GROUP_STEPS}")
        groups.append((label, members))
    flat = [m for _, ms in groups for m in ms]
    unknown = [m for m in flat if m not in ids]
    if unknown:
        problems.append(f"unknown step ids: {unknown[:5]}")
    if not unknown and flat != ids:
        missing = [i for i in ids if i not in flat]
        dup = sorted({m for m in flat if flat.count(m) > 1})
        problems.append("the groups must list every step exactly once, in order" + (f"; missing {missing[:5]}" if missing else "") + (f"; repeated {dup[:5]}" if dup else "") + ("" if missing or dup else "; the order differs"))
    return groups, problems


def apply_groups(sl: StepList, groups: list[tuple[str, list[str]]]) -> StepList:
    by_id: dict[str, tuple[str, str]] = {}
    for n, (label, members) in enumerate(groups, start=1):
        for m in members:
            by_id[m] = (f"g{n:02d}", label)
    steps: list[Step] = [s.model_copy(update={"group_id": by_id[s.id][0], "group": by_id[s.id][1]}) for s in sl.steps]
    return sl.model_copy(update={"steps": steps, "warnings": [*sl.warnings, f"steps grouped for display into {len(groups)} groups ({len(steps)} steps)"]})


def group_steps(sl: StepList, provider, max_attempts: int = 2) -> StepList:
    """Return the step list with display groups, or UNGROUPED with a warning if the model could not give a valid grouping. The steps themselves are never touched."""
    if not sl.steps:
        return sl
    prompt, last = _prompt(sl), []
    for attempt in range(max_attempts):
        ask = prompt if not last else prompt + "\n\nYour previous answer broke these rules, fix them:\n- " + "\n- ".join(last[:5])
        try:
            raw = provider.generate_json(system=SYSTEM, prompt=ask, schema=SCHEMA)
        except Exception as e:                                         # an outage or a budget stop must not lose the steps
            return sl.model_copy(update={"warnings": [*sl.warnings, f"grouping skipped: {type(e).__name__}"]})
        groups, last = check_groups(sl, raw)
        if not last:
            return apply_groups(sl, groups)
    return sl.model_copy(update={"warnings": [*sl.warnings, "grouping skipped: the model's groups broke the rules (" + "; ".join(last[:2]) + ")"]})
