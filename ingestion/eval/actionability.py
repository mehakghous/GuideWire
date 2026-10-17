"""A repeatable rubric for "can a beginner follow these steps?". Deterministic: no model, no network, no human in the loop at scoring time.

Every criterion scores 0, 1 or 2 per step; the report gives each criterion as a percentage of the maximum, plus list-level completeness and ordering.
What it measures is STRUCTURE: whether the information a learner needs is present, specific and tied to evidence. It cannot tell whether the information is TRUE
(a model can state a wrong menu path with evidence attached) and it cannot judge whether a feature tag is semantically right. A person checking against the video is still required for that,
and nothing here claims a step works in the application.

Per step (0-2)
  actionability   2 = two or more how-to lines or actions that name a UI target or a value; 1 = something to do but no target or value; 0 = only the goal
  ui_specificity  2 = an action with a UI target AND a value or a menu path; 1 = a UI target; 0 = none
  verification    2 = a check line the source showed or said; 1 = only catalog guidance or an expected state; 0 = none
  grounding       2 = step has evidence and every shown/said line carries its own; 1 = step has evidence; 0 = none
  timestamps      2 = start and end; 1 = one of them; 0 = none (the player cannot seek)
  feature_tag     2 = a feature id that exists in the catalog; 0 = none or unknown (whether it is the RIGHT feature is not judged)
List level (0-2)
  completeness    2 x the share of the reference checklist items found anywhere in the steps' text
  ordering        2 = no step comes before a prerequisite that this list also teaches; 1 = one; 0 = more
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from shared.step_record import Step, StepList

from ..features import load_catalog

CRITERIA = ("actionability", "ui_specificity", "verification", "grounding", "timestamps", "feature_tag")


def _has_target_or_value(h_text: str) -> bool:
    return bool(re.search(r">|:|\bto [\w.\-]+|\b\d+\b", h_text)) or any(c.isupper() for c in h_text[1:])


def score_step(st: Step) -> dict[str, int]:
    lines = [h for h in st.how_to if not h.text.startswith("In the video:")]
    targets = sum(1 for a in st.actions if a.ui_element) + sum(_has_target_or_value(h.text) for h in lines)
    doing = len(lines) + len(st.actions)
    s = {}
    s["actionability"] = 2 if doing >= 2 and targets >= 2 else (1 if doing >= 1 else 0)
    s["ui_specificity"] = 2 if any(a.ui_element and (a.value or ">" in a.ui_element) for a in st.actions) else (1 if any(a.ui_element for a in st.actions) else 0)
    real_checks = [h for h in st.check if h.support in ("shown", "said")]
    s["verification"] = 2 if real_checks else (1 if (st.check or st.expected_state) else 0)
    claimed = [h for h in (*st.how_to, *st.check) if h.support in ("shown", "said")]
    s["grounding"] = 2 if st.evidence and all((h.evidence or "").strip() for h in claimed) else (1 if st.evidence else 0)
    s["timestamps"] = (st.video_start_s is not None) + (st.video_end_s is not None)
    s["feature_tag"] = 2 if st.feature_id and st.feature_id in load_catalog() else 0
    return s


def _text(sl: StepList) -> str:
    parts = []
    for st in sl.steps:
        parts += [st.goal, st.result or "", st.visual_evidence or "", *st.evidence, *(h.text for h in st.how_to), *(h.text for h in st.check)]
        parts += [f"{a.ui_element or ''} {a.value or ''}" for a in st.actions]
    return " ".join(parts).lower()


def _found(items: list[dict], text: str) -> list[str]:
    stem = lambda w: w[:-1] if len(w) > 3 and w.endswith("s") else w                    # weight / weights, joint / joints
    words = {stem(w) for w in re.findall(r"[a-z0-9]+", text)}
    return [i["name"] for i in items if any(all(stem(w) in words for w in g) for g in i["any_of"])]


def ordering_violations(sl: StepList) -> list[str]:
    cat = load_catalog()
    pos = {}
    for i, st in enumerate(sl.steps):
        if st.feature_id in cat:
            pos.setdefault(st.feature_id, i)
    out = []
    for fid, i in pos.items():
        for pre in cat.prerequisites(fid):
            if pre.id in pos and pos[pre.id] > i:
                out.append(f"possible order issue: {fid} (step {i + 1}) comes before {pre.id} (step {pos[pre.id] + 1}), which the catalog lists as its prerequisite; the tutorial may not need it")
    return out


@dataclass
class Report:
    steps: int
    per_criterion: dict[str, float]                   # percent of the maximum
    completeness: float                               # percent of checklist items found
    ordering: int                                     # 0-2
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reference_found: list[str] = field(default_factory=list)
    reference_missing: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    weakest_steps: list[tuple[int, str, int]] = field(default_factory=list)       # (order, goal, total 0-12)

    @property
    def overall(self) -> float:
        """Mean of the six per-step criteria, completeness and ordering, as a percent. A single headline number; read the parts."""
        vals = [*self.per_criterion.values(), self.completeness, self.ordering * 50.0]
        return round(sum(vals) / len(vals), 1)

    def render(self) -> str:
        rows = [f"steps: {self.steps}   overall: {self.overall}%"]
        rows += [f"  {k:<15}{v:>5.0f}%" for k, v in self.per_criterion.items()]
        rows += [f"  {'completeness':<15}{self.completeness:>5.0f}%   ({len(self.found)}/{len(self.found) + len(self.missing)} reference items; missing: {', '.join(self.missing) or 'none'})",
                 f"  {'ordering':<15}{self.ordering * 50:>5.0f}%   {'; '.join(self.violations) or 'no prerequisite comes after the step that needs it'}"]
        if self.reference_missing or self.reference_found:
            rows.append(f"  quality reference (not counted): found {len(self.reference_found)} of {len(self.reference_found) + len(self.reference_missing)}; missing: {', '.join(self.reference_missing) or 'none'}")
        return "\n".join(rows)


def load_rubric(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def score(sl: StepList, rubric: dict | None = None) -> Report:
    per = [score_step(st) for st in sl.steps]
    pct = {c: round(100.0 * sum(p[c] for p in per) / (2 * len(per)), 1) if per else 0.0 for c in CRITERIA}
    text = _text(sl)
    rub = rubric or {"items": [], "reference_only": []}
    found = _found(rub["items"], text)
    missing = [i["name"] for i in rub["items"] if i["name"] not in found]
    ref_found = _found(rub.get("reference_only", []), text)
    viol = ordering_violations(sl)
    weakest = sorted(((st.order, st.goal[:60], sum(p.values())) for st, p in zip(sl.steps, per)), key=lambda t: t[2])[:3]
    return Report(steps=len(sl.steps), per_criterion=pct, completeness=round(100.0 * len(found) / len(rub["items"]), 1) if rub["items"] else 0.0,
                  ordering=2 if not viol else (1 if len(viol) == 1 else 0), found=found, missing=missing, reference_found=ref_found,
                  reference_missing=[i["name"] for i in rub.get("reference_only", []) if i["name"] not in ref_found], violations=viol, weakest_steps=weakest)
