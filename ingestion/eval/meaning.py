"""Matching by MEANING for the span-and-words scores (ingestion/eval/phase1.py).

The default matcher counts shared words ("log in" does not match "sign into the account"). `MeaningJudge` asks a model instead, once per video and in text only (no video is sent):
for every gold action it lists the steps whose time span contains the action (the same time rule as before) and the model says which of those steps DO that action, whatever words
they use. A step that covers several actions is credited for each of them, as before. Only candidates are accepted, so the model cannot match a step outside the time window.

    judge = MeaningJudge(provider)            # provider: any LLMProvider, normally a cost-guarded one (ingestion/budget.py), so a repeated run is a cache hit
    matcher = judge.matcher(step_list, gold)  # matcher(step, gold_step) -> bool

Strict one-to-one recall and precision (metrics.py) still use words; only the coverage numbers can use this matcher.
"""
from __future__ import annotations

import re
from typing import Callable

from shared.step_record import Step, StepList

from .gold import GoldSet, GoldStep

SYSTEM = """You compare the steps a program extracted from a tutorial video with a list of actions a person wrote down while watching the same video.

For each ACTION you are given the candidate STEPS (the steps whose time range contains the action). Say which candidates DO that action, judged by meaning, not by wording:
"sign into the account" and "log in" are the same; "select the bone" and "click the bone in the outliner" are the same; a step that says "create the joint chain and name it" covers both "create the joint chain" and "name the chain".
Be strict about the operation: a step that only mentions the same object, the same menu, or the same topic without doing the action does NOT cover it. If none of the candidates does the action, return an empty list.
In "action" write only the number of the action (for example "12"); in "steps" write only the step ids (for example ["s03", "s04"]), never the step text.
Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {"matches": {"type": "array", "items": {
        "type": "object",
        "properties": {"action": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}}},
        "required": ["action", "steps"]}}},
    "required": ["matches"],
}

MAX_CANDIDATES = 8      # nearest candidates per action sent to the model; keeps the request small


def _step_text(st: Step) -> str:
    return " ".join([st.goal, st.result or "", *(h.text for h in st.how_to), *(a.ui_element or "" for a in st.actions)]).strip()


def candidates(sl: StepList, g: GoldStep, tol_s: float) -> list[Step]:
    near = [s for s in sl.steps if s.video_start_s is not None and s.video_end_s is not None and s.video_start_s - tol_s <= g.t_start <= s.video_end_s + tol_s]
    near.sort(key=lambda s: abs((s.video_start_s + s.video_end_s) / 2 - g.t_start))
    return near[:MAX_CANDIDATES]


class MeaningJudge:
    def __init__(self, provider, tol_s: float = 5.0):
        self.provider = provider
        self.tol_s = tol_s

    def judge(self, sl: StepList, gold: GoldSet) -> dict[tuple[str, int], bool]:
        """{(step id, gold order): True} for every accepted pair. One model call for the whole video."""
        cands = {g.order: candidates(sl, g, self.tol_s) for g in gold.steps}
        asked = [g for g in gold.steps if cands[g.order]]
        if not asked:
            return {}
        lines = []
        for g in asked:
            lines.append(f'ACTION {g.order}: {g.goal}')
            lines += [f'   STEP {s.id}: {_step_text(s)[:300]}' for s in cands[g.order]]
        out = self.provider.generate_json(system=SYSTEM, prompt="\n".join(lines), schema=SCHEMA)
        allowed = {(g.order, s.id) for g in asked for s in cands[g.order]}
        pairs: dict[tuple[str, int], bool] = {}
        for m in out.get("matches", []):
            num = re.search(r"\d+", str(m.get("action", "")))
            if not num:
                continue
            order = int(num.group())
            for raw in m.get("steps", []):
                sid = re.match(r"\s*(?:STEP\s+)?([^\s:,;]+)", str(raw), re.I)       # the model sometimes echoes "STEP s03: text" instead of "s03"
                if sid and (order, sid.group(1)) in allowed:               # a step the model invented or that is outside the time window is ignored
                    pairs[(sid.group(1), order)] = True
        return pairs

    def matcher(self, sl: StepList, gold: GoldSet) -> Callable[[Step, GoldStep], bool]:
        pairs = self.judge(sl, gold)
        return lambda step, g: pairs.get((step.id, g.order), False)
