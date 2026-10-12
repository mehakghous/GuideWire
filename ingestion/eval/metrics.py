"""Offline evaluation metrics: compare a predicted StepList with a human GoldSet.

Matching is automatic only as a first pass (time window + goal/UI-name token overlap). A human
may override via `manual_matches` {pred_step_id: gold_order or None}. Judgements that cannot be
automated (is a step unsupported by the video?) come from `manual_labels` {pred_step_id: label}.
Nothing here calls a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared.step_record import StatePredicate, StepList

from .gold import GoldSet

SIM_TIME_MATCH = 0.34   # token similarity needed when the time window also agrees
SIM_ACTION_ONLY = 0.6   # similarity needed to call it the same action with a wrong timestamp


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _desc(goal: str, actions) -> str:
    return goal + " " + " ".join((a.ui_element or "") + " " + " ".join(a.keys) for a in actions)


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


@dataclass
class Match:
    pred_id: str
    gold_order: int
    sim: float
    dt: float | None
    time_ok: bool


@dataclass
class Report:
    n_pred: int
    n_gold: int
    n_gold_core: int
    matches: list[Match] = field(default_factory=list)
    precision: float = 0.0
    core_recall: float = 0.0
    timestamp_accuracy: float | None = None
    timestamps_beyond_end: int = 0
    coverage_core: float | None = None         # share of core gold steps inside some predicted time span
    verifiable_rate: float = 0.0
    state_precision: float | None = None       # predicates on matched steps that are also in gold
    state_recall: float | None = None          # gold predicates on matched steps that were predicted
    duplicate_rate: float = 0.0
    order_inversion_rate: float | None = None
    unsupported_rate: float | None = None      # needs manual_labels
    correct_usable_steps: int = 0
    cost_per_correct_usable_step: float | None = None


def _pkey(p: StatePredicate):
    return (p.kind, p.target, p.value)


def match_steps(
    gold: GoldSet, pred: StepList, manual_matches: dict[str, int | None] | None = None
) -> list[Match]:
    manual_matches = manual_matches or {}
    used_gold: set[int] = set()
    out: list[Match] = []
    gmap = {g.order: g for g in gold.steps}
    pmap = {s.id: s for s in pred.steps}
    for pid, g_order in manual_matches.items():
        if g_order is not None and g_order in gmap and pid in pmap:
            ps, g = pmap[pid], gmap[g_order]
            dt = None if ps.video_start_s is None else ps.video_start_s - g.t_start
            out.append(Match(pid, g_order, 1.0, dt, dt is not None and abs(dt) <= g.tol_s))
            used_gold.add(g_order)
    done = set(manual_matches)
    cands = []
    for ps in pred.steps:
        if ps.id in done:
            continue
        for g in gold.steps:
            sim = similarity(_desc(ps.goal, ps.actions), _desc(g.goal, g.actions))
            dt = None if ps.video_start_s is None else ps.video_start_s - g.t_start
            time_ok = dt is not None and abs(dt) <= g.tol_s
            if (time_ok and sim >= SIM_TIME_MATCH) or sim >= SIM_ACTION_ONLY:
                cands.append((time_ok, sim, -abs(dt) if dt is not None else -1e9, ps.id, g.order, dt))
    for time_ok, sim, _, pid, go, dt in sorted(cands, reverse=True):
        if pid in done or go in used_gold:
            continue
        out.append(Match(pid, go, sim, dt, time_ok))
        done.add(pid)
        used_gold.add(go)
    return out


def evaluate(
    gold: GoldSet, pred: StepList, *, cost_usd: float | None = None,
    manual_matches: dict[str, int | None] | None = None,
    manual_labels: dict[str, str] | None = None,
) -> Report:
    """manual_labels values: 'supported' | 'unsupported' | 'wrong'. A step counts as 'correct and
    usable' if it is matched, its start is within tolerance, and it is not labelled unsupported/wrong."""
    core = [g for g in gold.steps if g.importance == "core"]
    ms = match_steps(gold, pred, manual_matches)
    gmap = {g.order: g for g in gold.steps}
    pmap = {s.id: s for s in pred.steps}
    r = Report(n_pred=len(pred.steps), n_gold=len(gold.steps), n_gold_core=len(core), matches=ms)
    if pred.steps:
        r.precision = len(ms) / len(pred.steps)
        r.verifiable_rate = sum(s.verifiable for s in pred.steps) / len(pred.steps)
    core_orders = {g.order for g in core}
    r.core_recall = (len({m.gold_order for m in ms} & core_orders) / len(core)) if core else 0.0
    timed = [m for m in ms if m.dt is not None]
    if timed:
        r.timestamp_accuracy = sum(m.time_ok for m in timed) / len(timed)
    dur = gold.duration_s
    r.timestamps_beyond_end = sum(
        1 for s in pred.steps for t in (s.video_start_s, s.video_end_s) if t is not None and t > dur + 1
    )
    spans = [(s.video_start_s, s.video_end_s) for s in pred.steps
             if s.video_start_s is not None and s.video_end_s is not None]
    if core:
        r.coverage_core = sum(any(a - 1 <= g.t_start <= b + 1 for a, b in spans) for g in core) / len(core)
    n_pred_p = n_gold_p = hit = 0
    for m in ms:
        pk = {_pkey(p) for p in pmap[m.pred_id].expected_state}
        gk = {_pkey(p) for p in gmap[m.gold_order].expected_state}
        n_pred_p += len(pk)
        n_gold_p += len(gk)
        hit += len(pk & gk)
    r.state_precision = hit / n_pred_p if n_pred_p else None
    r.state_recall = hit / n_gold_p if n_gold_p else None
    dups, seen = 0, []
    for s in pred.steps:
        d = _desc(s.goal, s.actions)
        if any(similarity(d, x) >= 0.9 and abs((s.video_start_s or 0) - (t or 0)) <= 10 for x, t in seen):
            dups += 1
        seen.append((d, s.video_start_s))
    r.duplicate_rate = dups / len(pred.steps) if pred.steps else 0.0
    order_p = {s.id: s.order for s in pred.steps}
    pairs = [(order_p[m.pred_id], m.gold_order) for m in ms]
    if len(pairs) >= 2:
        inv = sum(1 for i in range(len(pairs)) for j in range(i + 1, len(pairs))
                  if (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1]) < 0)
        r.order_inversion_rate = inv / (len(pairs) * (len(pairs) - 1) / 2)
    labels = manual_labels or {}
    if labels:
        r.unsupported_rate = sum(v in ("unsupported", "wrong") for v in labels.values()) / len(labels)
    good = [m for m in ms if m.time_ok and labels.get(m.pred_id, "supported") == "supported"]
    r.correct_usable_steps = len(good)
    if cost_usd is not None:
        r.cost_per_correct_usable_step = cost_usd / len(good) if good else None
    return r
