"""Deterministic coverage evaluation against a frozen reference (GoldSet v2).

Definitions (all denominators are stated; nothing here calls a model):

Matching. A generated step G *covers* a reference step R when
  (1) time: G's [start, end] overlaps R's [t_start - tol, t_end + tol]  (tol = R.tol_s), and
  (2) content: one of R.match_terms (an OR of AND-groups of lowercase words, written by the annotator) is
      contained in the words of G's goal + action targets + keys. If R has no match_terms, word overlap
      with R.goal >= 0.5 is used instead.
  A G without timestamps covers nothing (it cannot be aligned) and is counted as untimed.
Lenient coverage allows one G to cover several R (a merged step) and several G to cover one R (a split).
Strict coverage is a one-to-one assignment (greedy, closest start time first, deterministic), so a broad
step cannot be credited for more than one reference step and duplicates cannot inflate coverage.

Recall denominators count only VERIFIED reference steps (verification is not 'unverified' and confidence is
medium or high). Unverified steps are reported separately, never counted as misses.
  demonstrated recall  = covered verified steps with evidence_type in {demonstrated, both} / such steps
  narrated recall      = covered verified steps with evidence_type in {narrated, both}     / such steps
  overall recall       = covered verified steps / verified steps
  (a step that is both counts in both of the first two, which is why demonstrated-only and
   narrated-only recalls are also reported)
Precision (lenient) = generated steps covering >= 1 reference step (verified or not) / generated steps.
Precision (strict)  = generated steps in the one-to-one assignment / generated steps.
An unmatched generated step is NOT automatically a hallucination: it is listed for human labelling.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from shared.step_record import Step, StepList

from .gold import GoldSet, GoldStep
from .metrics import similarity


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def step_words(s: Step) -> set[str]:
    parts = [s.goal]
    for a in s.actions:
        parts += [a.ui_element or "", " ".join(a.keys), a.value or ""]
    return _words(" ".join(parts))


def _rid(r: GoldStep) -> str:
    return r.id or f"R{r.order:02d}"


def covers(g: Step, r: GoldStep) -> bool:
    if g.video_start_s is None:
        return False
    gs = g.video_start_s
    ge = g.video_end_s if g.video_end_s is not None else gs
    rs, re_ = r.t_start - r.tol_s, (r.t_end if r.t_end is not None else r.t_start) + r.tol_s
    if not (gs <= re_ and ge >= rs):
        return False
    words = step_words(g)
    if r.match_terms:
        return any(set(grp) <= words for grp in r.match_terms)
    return similarity(g.goal, r.goal) >= 0.5


@dataclass
class CoverageReport:
    n_gen: int
    n_ref: int
    n_verified: int
    n_unverified: int
    lenient: dict[str, list[str]] = field(default_factory=dict)   # ref id -> generated ids
    strict: dict[str, str] = field(default_factory=dict)          # ref id -> generated id
    counts: dict[str, int] = field(default_factory=dict)          # denominators
    demonstrated_recall: float | None = None
    narrated_recall: float | None = None
    overall_recall: float | None = None
    demonstrated_recall_strict: float | None = None
    narrated_recall_strict: float | None = None
    overall_recall_strict: float | None = None
    demonstrated_only_recall: float | None = None
    narrated_only_recall: float | None = None
    unverified_covered: str = ""                                  # "k/n" provisional, reported apart
    precision_lenient: float | None = None
    precision_strict: float | None = None
    unmatched_gen: list[str] = field(default_factory=list)
    untimed_gen: list[str] = field(default_factory=list)
    beyond_end_gen: list[str] = field(default_factory=list)
    broad_gen: list[str] = field(default_factory=list)            # cover >= 3 reference steps
    duplicate_gen: list[str] = field(default_factory=list)        # share every covered ref with an earlier G
    temporal_within_tol: float | None = None
    temporal_median_abs_err_s: float | None = None
    state_recall: float | None = None
    state_wrong_rate: float | None = None
    order_inversion_rate: float | None = None
    prerequisite_violation_rate: float | None = None
    visual_claims: list[str] = field(default_factory=list)        # G claiming support demonstrated/both
    false_visual_claims: list[str] = field(default_factory=list)  # ... that cover only narrated-only refs, or none
    demonstrated_recall_claimed: float | None = None              # demonstrated recall counting only G that CLAIM a visual basis


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def evaluate_coverage(gold: GoldSet, pred: StepList) -> CoverageReport:
    refs = {_rid(r): r for r in gold.steps}
    verified = {i for i, r in refs.items() if r.is_verified}
    etype = {i: (r.evidence_type or ("narrated" if r.evidence_kind != "directly_evidenced" else "both"))
             for i, r in refs.items()}
    gens = {g.id: g for g in pred.steps}

    cov: dict[str, list[str]] = {i: [g.id for g in pred.steps if covers(g, r)] for i, r in refs.items()}
    gen_cov: dict[str, list[str]] = {g.id: [i for i, r in refs.items() if g.id in cov[i]] for g in pred.steps}

    # strict one-to-one: closest start time first; ties broken by reference order then generated id
    pairs = sorted(
        ((abs(gens[gid].video_start_s - refs[i].t_start), refs[i].order, gid, i)
         for i, gl in cov.items() for gid in gl)
    )
    strict: dict[str, str] = {}
    used_g: set[str] = set()
    for _, _, gid, i in pairs:
        if i not in strict and gid not in used_g:
            strict[i] = gid
            used_g.add(gid)

    rep = CoverageReport(
        n_gen=len(pred.steps), n_ref=len(refs), n_verified=len(verified),
        n_unverified=len(refs) - len(verified),
        lenient={i: v for i, v in cov.items() if v}, strict=strict,
    )
    dem = {i for i in verified if etype[i] in ("demonstrated", "both")}
    nar = {i for i in verified if etype[i] in ("narrated", "both")}
    dem_only = {i for i in verified if etype[i] == "demonstrated"}
    nar_only = {i for i in verified if etype[i] == "narrated"}
    rep.counts = {
        "verified": len(verified), "verified_demonstrated": len(dem), "verified_narrated": len(nar),
        "verified_demonstrated_only": len(dem_only), "verified_narrated_only": len(nar_only),
        "unverified": len(refs) - len(verified), "generated": len(pred.steps),
    }
    covered = {i for i, v in cov.items() if v}
    rep.demonstrated_recall = _ratio(len(dem & covered), len(dem))
    rep.narrated_recall = _ratio(len(nar & covered), len(nar))
    rep.overall_recall = _ratio(len(verified & covered), len(verified))
    sc = set(strict)
    rep.demonstrated_recall_strict = _ratio(len(dem & sc), len(dem))
    rep.narrated_recall_strict = _ratio(len(nar & sc), len(nar))
    rep.overall_recall_strict = _ratio(len(verified & sc), len(verified))
    rep.demonstrated_only_recall = _ratio(len(dem_only & covered), len(dem_only))
    rep.narrated_only_recall = _ratio(len(nar_only & covered), len(nar_only))
    unv = set(refs) - verified
    rep.unverified_covered = f"{len(unv & covered)}/{len(unv)}"

    if pred.steps:
        rep.precision_lenient = sum(1 for g in pred.steps if gen_cov[g.id]) / len(pred.steps)
        rep.precision_strict = len(used_g) / len(pred.steps)
    rep.unmatched_gen = [g.id for g in pred.steps if not gen_cov[g.id]]
    rep.untimed_gen = [g.id for g in pred.steps if g.video_start_s is None]
    dur = gold.duration_s
    rep.beyond_end_gen = [g.id for g in pred.steps
                          if any(t is not None and t > dur + 1 for t in (g.video_start_s, g.video_end_s))]
    rep.broad_gen = [gid for gid, rl in gen_cov.items() if len(rl) >= 3]
    seen: set[str] = set()
    for g in pred.steps:
        rl = set(gen_cov[g.id])
        if rl and rl <= seen:
            rep.duplicate_gen.append(g.id)
        seen |= rl

    # visual-claim honesty: a G may claim 'demonstrated'/'both' only if it covers something shown on screen
    shown = {i for i in refs if etype[i] in ("demonstrated", "both")}
    rep.visual_claims = [g.id for g in pred.steps if g.support in ("demonstrated", "both")]
    rep.false_visual_claims = [gid for gid in rep.visual_claims if not (set(gen_cov[gid]) & shown)]
    claimed_cov = {i for i in dem if any(gens[gid].support in ("demonstrated", "both") for gid in cov[i])}
    rep.demonstrated_recall_claimed = _ratio(len(claimed_cov), len(dem))

    # temporal alignment on the strict assignment (error of start time vs the reference start)
    errs = [(abs(gens[gid].video_start_s - refs[i].t_start), refs[i].tol_s) for i, gid in strict.items()]
    if errs:
        rep.temporal_within_tol = sum(e <= tol for e, tol in errs) / len(errs)
        rep.temporal_median_abs_err_s = statistics.median(e for e, _ in errs)

    # expected-state correctness on strictly matched references that define predicates
    n_pred = n_hit = n_gen_pred = n_wrong = 0
    for i, gid in strict.items():
        rp = {(p.kind, p.target) for p in refs[i].expected_state}
        gp = {(p.kind, p.target) for p in gens[gid].expected_state}
        if not rp:
            continue
        n_pred += len(rp)
        n_hit += len(rp & gp)
        kinds = {k for k, _ in rp}
        n_gen_pred += len([1 for k, t in gp if k in kinds])
        n_wrong += len([1 for k, t in gp if k in kinds and (k, t) not in rp])
    rep.state_recall = _ratio(n_hit, n_pred)
    rep.state_wrong_rate = _ratio(n_wrong, n_gen_pred)

    # ordering among strictly matched references
    ms = sorted(strict, key=lambda i: refs[i].order)
    gen_pos = {i: pred.steps.index(gens[strict[i]]) for i in ms}
    n_pairs = inv = 0
    for a in range(len(ms)):
        for b in range(a + 1, len(ms)):
            n_pairs += 1
            if gen_pos[ms[a]] > gen_pos[ms[b]]:
                inv += 1
    rep.order_inversion_rate = _ratio(inv, n_pairs)
    n_req = viol = 0
    for i, r in refs.items():
        for pre in r.requires:
            if i in strict and pre in strict:
                n_req += 1
                # violated when the generated list places the prerequisite after the step that depends on it
                if gen_pos[pre] > gen_pos[i]:
                    viol += 1
    rep.prerequisite_violation_rate = _ratio(viol, n_req)
    return rep


def recall_in_window(gold: GoldSet, rep: CoverageReport, t0: float, t1: float) -> float | None:
    """Recall over verified reference steps lying entirely inside [t0, t1]."""
    ids = [(r.id or f"R{r.order:02d}") for r in gold.steps
           if r.is_verified and r.t_start >= t0 and (r.t_end if r.t_end is not None else r.t_start) <= t1]
    return _ratio(sum(1 for i in ids if i in rep.lenient), len(ids))


def recall_outside_window(gold: GoldSet, rep: CoverageReport, t0: float, t1: float) -> float | None:
    ids = [(r.id or f"R{r.order:02d}") for r in gold.steps
           if r.is_verified and not (r.t_start >= t0 and (r.t_end if r.t_end is not None else r.t_start) <= t1)]
    return _ratio(sum(1 for i in ids if i in rep.lenient), len(ids))


def demonstration_gap(gold: GoldSet, rep: CoverageReport, t0: float, t1: float,
                      min_outside: float = 0.25, max_inside: float = 0.34) -> bool:
    """True when the output covers other parts of the video reasonably but misses most verified steps inside
    the demonstration window [t0, t1] (the failure mode seen in the baseline)."""
    inside, outside = recall_in_window(gold, rep, t0, t1), recall_outside_window(gold, rep, t0, t1)
    return inside is not None and outside is not None and outside >= min_outside and inside <= max_inside
