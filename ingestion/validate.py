"""Deterministic validation and annotation of extracted step lists. No LLM involved.

Policy (deliberate):
- Structural errors (bad order, timestamps outside the video, ...) are reported as Issues and
  make the list unusable. They are NEVER silently repaired or clamped.
- Semantic findings (state already true before the step, duplicates, coverage gaps, unknown UI
  names, claimed support without evidence) are warnings: they are written to `step.flags` /
  `StepList.warnings`, lower the heuristic confidence, and never rewrite the model's content.
- The only content change made here is restricting predicates to the closed vocabulary
  (each removal is flagged) and canonicalising spelling of vocabulary entries.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Literal

from shared.step_record import StatePredicate, Step, StepList

from .features import load_catalog
from .profiles import AppProfile, norm

TS_TOLERANCE_S = 1.0          # allowed rounding past the stated video duration
MIN_GAP_S = 30.0              # a gap between steps shorter than this is never flagged
GAP_FRACTION = 0.15           # ... nor shorter than this fraction of the video
LOW_COVERAGE = 0.5            # flag if steps cover less than this share of the video
DUP_GOAL_RATIO = 0.9

# Heuristic prior on how much to trust a step given how directly the source supports it.
# These numbers are NOT calibrated; experiment E1 measures whether the composite predicts errors.
SUPPORT_CAP = {"demonstrated": 0.9, "both": 0.9, "narrated": 0.8, "unknown": 0.7, "inferred": 0.5}
PENALTY = {
    "unknown_ui": 0.85,
    "dropped_predicate": 0.9,
    "uninformative_state": 0.85,
    "no_evidence": 0.8,
    "no_visual_evidence": 0.8,
    "duplicate_goal": 0.7,
    "missing_time": 0.9,
    "overlap": 0.9,
    "feature_needs_extra": 0.9,
}


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Literal["error", "warning"]
    message: str
    step_id: str | None = None

    def __str__(self) -> str:
        where = f"{self.step_id}: " if self.step_id else ""
        return f"[{self.code}] {where}{self.message}"


class ValidationFailure(ValueError):
    """Structural problems that make a StepList unusable (triggers a retry upstream)."""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues[:8]) + (" ..." if len(issues) > 8 else ""))


# ----------------------------------------------------------------- structural errors


def find_errors(sl: StepList, video_duration_s: float | None = None) -> list[Issue]:
    out: list[Issue] = []
    if not sl.steps:
        return [Issue("NO_STEPS", "error", "no steps extracted")]
    orders = [s.order for s in sl.steps]
    if orders != list(range(1, len(orders) + 1)):
        out.append(Issue("BAD_ORDER", "error", f"step order must be 1..n consecutive, got {orders}"))
    if len({s.id for s in sl.steps}) != len(sl.steps):
        out.append(Issue("DUP_ID", "error", "duplicate step ids"))
    last_start = None
    for s in sl.steps:
        if not s.actions and not s.goal.strip():
            out.append(Issue("EMPTY_STEP", "error", "neither goal nor actions", s.id))
        if video_duration_s is not None:
            for name, t in (("start", s.video_start_s), ("end", s.video_end_s)):
                if t is not None and t > video_duration_s + TS_TOLERANCE_S:
                    out.append(Issue(
                        "TS_BEYOND_END", "error",
                        f"{name} {t:g}s is beyond the video duration {video_duration_s:g}s", s.id,
                    ))
        if s.feature_id and s.feature_id not in load_catalog():
            out.append(Issue("UNKNOWN_FEATURE", "error", f"feature_id {s.feature_id!r} is not in the rigging feature catalog", s.id))
        if s.video_start_s is not None:
            if last_start is not None and s.video_start_s + TS_TOLERANCE_S < last_start:
                out.append(Issue(
                    "TS_NOT_MONOTONIC", "error",
                    f"starts at {s.video_start_s:g}s, before the previous step ({last_start:g}s)", s.id,
                ))
            last_start = s.video_start_s
    return out


def check_structure(sl: StepList, video_duration_s: float | None = None) -> None:
    """Raise ValidationFailure listing ALL structural errors."""
    errors = find_errors(sl, video_duration_s)
    if errors:
        raise ValidationFailure(errors)


# ----------------------------------------------------------------- vocabulary


def _canonical_target(p: StatePredicate, profile: AppProfile) -> str | None:
    """Return the canonical vocabulary entry for p, or None if outside the vocabulary."""
    if p.kind == "mode":
        t = p.target.strip().upper().replace(" ", "_")
        t = profile.mode_aliases.get(t, t)
        return t if t in profile.modes else None
    if p.kind == "selection_type":
        t = p.target.strip().upper()
        return t if t in profile.selection_types else None
    pools = {"active_tool": profile.tools, "workspace": profile.workspaces, "panel_open": profile.panels, "node_exists": profile.nodes}
    if p.kind in pools:
        t = p.target.strip().lower()
        for cand in pools[p.kind]:
            if cand.lower() == t:
                return cand
        return None
    return p.target.strip()  # property_equals: open-ended property path, kept as-is


def _ui_name_known(label: str, profile: AppProfile) -> bool:
    segments = [s for s in label.replace("->", ">").split(">") if s.strip()] or [label]
    for seg in segments:
        n = norm(seg)
        if not n or n in profile.ui_names:
            continue
        if difflib.get_close_matches(n, profile.ui_names, n=1, cutoff=0.85):
            continue
        return False
    return True


# ----------------------------------------------------------------- semantic annotation


def _key(p: StatePredicate) -> tuple:
    return (p.kind, p.target, p.value)


def _covered_seconds(steps: list[Step]) -> float:
    spans = sorted(
        (s.video_start_s, s.video_end_s)
        for s in steps
        if s.video_start_s is not None and s.video_end_s is not None
    )
    total, cur_end = 0.0, None
    cur_start = None
    for a, b in spans:
        if cur_end is None or a > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = a, b
        else:
            cur_end = max(cur_end, b)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def sanitize_and_annotate(
    sl: StepList, profile: AppProfile, video_duration_s: float | None = None
) -> StepList:
    """Restrict predicates to the closed vocabulary, add semantic flags, recompute
    `verifiable` and the heuristic `confidence`. Mutates and returns sl. Idempotent only
    on fresh extractor output (flags are appended)."""
    sl.video_duration_s = video_duration_s if video_duration_s is not None else sl.video_duration_s
    dur = sl.video_duration_s
    pen: dict[str, list[float]] = {s.id: [] for s in sl.steps}

    def flag(step: Step, code: str, msg: str) -> None:
        step.flags.append(msg)
        pen[step.id].append(PENALTY[code])

    seen_sigs: dict[tuple, Step] = {}
    prev: Step | None = None
    for step in sl.steps:
        for which in ("expected_state", "start_state"):
            kept = []
            for p in getattr(step, which):
                canon = _canonical_target(p, profile)
                if canon is None:
                    flag(step, "dropped_predicate",
                         f"removed {which} '{p.kind}={p.target}': not in {profile.name} vocabulary")
                else:
                    kept.append(p.model_copy(update={"target": canon}))
            setattr(step, which, kept)

        # Is the expected state actually informative, i.e. not already true by the step's own start_state?
        start_keys = {_key(p) for p in step.start_state}
        informative = [p for p in step.expected_state if _key(p) not in start_keys]
        if step.expected_state and not informative:
            flag(step, "uninformative_state",
                 "expected state already holds before this step, so completing it cannot be verified")
        step.verifiable = bool(informative) and step.kind == "mechanics"

        for a in step.actions:
            if a.ui_element and not _ui_name_known(a.ui_element, profile):
                flag(step, "unknown_ui",
                     f"UI name '{a.ui_element}' is not in the {profile.name} vocabulary (it may be real "
                     "but missing from the list): please check")

        if step.feature_id and step.feature_id in load_catalog():
            f = load_catalog().get(step.feature_id)
            code = f.support_code(sl.app)
            if code in ("U", "C"):
                what = "has no tool" if code == "U" else "needs an add-on or a script"
                flag(step, "feature_needs_extra", f"{f.id} ({f.name}) {what} in {sl.app}: the tutorial is using something outside the application")

        if step.support in ("demonstrated", "narrated", "both") and not step.evidence:
            flag(step, "no_evidence", f"claims support='{step.support}' but gives no evidence")
        if step.support in ("demonstrated", "both") and not (step.visual_evidence or "").strip():
            flag(step, "no_visual_evidence",
                 f"claims support='{step.support}' (visible on screen) but describes nothing visible")

        if sl.source_type == "youtube" and (step.video_start_s is None or step.video_end_s is None):
            flag(step, "missing_time", "no video time range: cannot seek the player to this step")

        if prev is not None:
            if difflib.SequenceMatcher(None, norm(prev.goal), norm(step.goal)).ratio() >= DUP_GOAL_RATIO:
                flag(step, "duplicate_goal", f"goal is almost identical to step {prev.order}")
            if (
                step.video_start_s is not None and prev.video_end_s is not None
                and step.video_start_s < prev.video_end_s - 2 * TS_TOLERANCE_S
            ):
                flag(step, "overlap",
                     f"starts at {step.video_start_s:g}s, before step {prev.order} ends ({prev.video_end_s:g}s)")
        sig = (frozenset(start_keys), frozenset(_key(p) for p in step.expected_state))
        if step.expected_state and sig in seen_sigs:
            step.flags.append(
                f"same start and expected state as step {seen_sigs[sig].order}: the two cannot be told apart by state"
            )
        seen_sigs.setdefault(sig, step)
        prev = step

    # list-level coverage findings (information for the reviewer, not a rejection)
    sl.warnings = []
    timed = [s for s in sl.steps if s.video_start_s is not None and s.video_end_s is not None]
    if dur and timed:
        min_gap = max(MIN_GAP_S, GAP_FRACTION * dur)
        edges = [(0.0, "start")] + [(s.video_end_s, s.order) for s in timed]
        starts = [s.video_start_s for s in timed] + [dur]
        for (end, after), nxt in zip(edges, starts):
            if nxt - end > min_gap:
                where = "video start" if after == "start" else f"step {after}"
                sl.warnings.append(
                    f"uncovered {nxt - end:.0f}s after {where} ({end:g}s to {nxt:g}s): steps may be missing "
                    "(or this is intro/outro/talk)"
                )
        cov = _covered_seconds(timed) / dur
        if cov < LOW_COVERAGE:
            sl.warnings.append(f"steps cover only {cov:.0%} of the {dur:g}s video: extraction may be incomplete")

    for step in sl.steps:
        base = step.model_confidence if step.model_confidence is not None else step.confidence
        conf = min(base, SUPPORT_CAP[step.support])
        for f in pen[step.id]:
            conf *= f
        step.confidence = round(max(0.0, min(1.0, conf)), 3)
    return sl
