"""Tests for the deterministic coverage evaluator, using the REAL frozen reference file and SYNTHETIC
predicted steps (labelled as such; none of them is a model output)."""
import json
from pathlib import Path

import pytest

from ingestion.eval.coverage import (
    covers, demonstration_gap, evaluate_coverage, recall_in_window, recall_outside_window,
)
from ingestion.eval.gold import GoldSet
from shared.step_record import Action, StatePredicate as P, Step, StepList

REF = Path(__file__).parent.parent / "eval_data" / "gold" / "34FBeC9mktE.reference.v1.json"
GOLD = GoldSet.model_validate(json.loads(REF.read_text(encoding="utf-8")))
BY_ID = {s.id: s for s in GOLD.steps}


def sl(*steps):
    return StepList(source_type="youtube", app="blender", steps=list(steps))


def g(i, goal, s, e, keys=(), support="unknown", ui=None, expected=(), vis=None):
    return Step(id=f"g{i}", order=i, goal=goal, video_start_s=s, video_end_s=e, support=support,
                visual_evidence=vis, actions=[Action(verb="press_keys", keys=list(keys), ui_element=ui)],
                expected_state=list(expected))


# ----------------------------------------------------------------- the reference file itself
def test_reference_is_wellformed():
    ids = [s.id for s in GOLD.steps]
    assert len(set(ids)) == len(ids) == len(GOLD.steps)
    assert all(pre in ids for s in GOLD.steps for pre in s.requires)
    assert all(s.t_start <= GOLD.duration_s and (s.t_end or 0) <= GOLD.duration_s for s in GOLD.steps)
    unverified = {s.id for s in GOLD.steps if not s.is_verified}
    assert unverified == {"R05", "R14", "R20"}      # low-confidence steps are kept out of the denominators
    kinds = {s.evidence_type for s in GOLD.steps}
    assert kinds == {"demonstrated", "narrated", "both"}   # a step may be both


def test_reference_hash_is_frozen():
    import hashlib
    want = (REF.parent / "34FBeC9mktE.reference.v1.sha256").read_text().split()[0]
    assert hashlib.sha256(REF.read_bytes()).hexdigest() == want, "reference changed after freezing: make v2"


# ----------------------------------------------------------------- matching rules
def test_covers_needs_time_and_content():
    r = BY_ID["R06"]                                            # Ctrl+Z, 49-53 s
    assert covers(g(1, "Press Ctrl+Z to undo", 50, 52, keys=["Ctrl", "Z"]), r)
    assert not covers(g(1, "Press Ctrl+Z to undo", 120, 125, keys=["Ctrl", "Z"]), r)     # wrong time
    assert not covers(g(1, "Rotate the cube", 50, 52), r)                                # wrong content
    assert not covers(Step(id="x", order=1, goal="undo"), r)                             # no timestamps


def test_meaning_not_exact_wording():
    # different wording, same action: matches through annotator-defined terms
    assert covers(g(1, "Undo the last operation", 50, 52), BY_ID["R06"])
    assert covers(g(1, "Toggle back to Object Mode", 72.5, 74), BY_ID["R10"])


# ----------------------------------------------------------------- the known failure mode
def narration_only_prediction():
    """What the baseline looked like: explanations and the later steps, nothing from 38-91 s."""
    return sl(
        g(1, "Toggle between Object Mode and Edit Mode with the mode drop-down or Tab", 22, 34, keys=["Tab"]),
        g(2, "Select all objects you want to edit and go into Edit Mode", 121, 132),
        g(3, "Press Ctrl+J to join the selected objects", 162, 166, keys=["Ctrl", "J"]),
        g(4, "Mesh > Separate > Selection", 175, 184, ui="Mesh > Separate > Selection"),
    )


def test_demonstration_gap_detected_despite_narration_coverage():
    rep = evaluate_coverage(GOLD, narration_only_prediction())
    inside, outside = recall_in_window(GOLD, rep, 38, 92), recall_outside_window(GOLD, rep, 38, 92)
    assert inside == 0.0 and outside >= 0.25               # demonstration missed, rest partly covered
    assert demonstration_gap(GOLD, rep, 38, 92) is True
    assert rep.narrated_only_recall == 1.0                 # R03 and R21 are covered...
    assert rep.demonstrated_only_recall == 0.0             # ...R16 (shown, never said) is not


def test_gap_not_flagged_when_demonstration_is_covered():
    full = sl(
        g(1, "Move vertices with G", 40, 46, keys=["G"]),
        g(2, "Press Ctrl+Z twice to undo", 49, 53, keys=["Ctrl", "Z"]),
        g(3, "Press Tab to go to Object Mode", 54, 56, keys=["Tab"]),
        g(4, "Press Ctrl+Z to undo back into Edit Mode", 57, 60, keys=["Ctrl", "Z"]),
        g(5, "Select vertices and move or rotate them to reshape the cube", 62, 71),
        g(6, "Press Tab to toggle back into Object Mode", 72, 74, keys=["Tab"]),
        g(7, "Rotate the object with R", 75, 82, keys=["R"]),
        g(8, "Press Ctrl+Z repeatedly to undo", 83, 90, keys=["Ctrl", "Z"]),
        *narration_only_prediction().steps[1:],
    )
    for i, s in enumerate(full.steps, 1):
        s.id, s.order = f"g{i}", i
    rep = evaluate_coverage(GOLD, full)
    assert recall_in_window(GOLD, rep, 38, 92) == 1.0
    assert demonstration_gap(GOLD, rep, 38, 92) is False
    assert rep.prerequisite_violation_rate in (0.0, None) and rep.order_inversion_rate == 0.0


# ----------------------------------------------------------------- merged / split / duplicate / broad
def test_merged_step_lenient_vs_strict():
    one_broad = sl(g(1, "Undo with Ctrl+Z, press Tab, undo again", 49, 61, keys=["Ctrl", "Z", "Tab"]))
    rep = evaluate_coverage(GOLD, one_broad)
    assert {"R06", "R07", "R08"} <= set(rep.lenient)          # lenient: one step may cover several
    assert len(rep.strict) == 1 and rep.precision_strict == 1.0   # strict: only one credited
    assert rep.broad_gen == ["g1"]                              # and it is reported as broad


def test_split_steps_each_credited():
    split = sl(g(1, "Press Ctrl+Z to undo", 49, 51, keys=["Ctrl", "Z"]),
               g(2, "Press Ctrl+Z again to undo", 51.5, 53, keys=["Ctrl", "Z"]))
    rep = evaluate_coverage(GOLD, split)
    assert rep.lenient["R06"] == ["g1", "g2"] and len(rep.strict) == 1     # R06 counts once
    assert rep.duplicate_gen == ["g2"]


def test_duplicates_do_not_inflate_recall():
    one = sl(g(1, "Press Ctrl+Z to undo", 50, 52, keys=["Ctrl", "Z"]))
    dup = sl(*[g(i, "Press Ctrl+Z to undo", 50, 52, keys=["Ctrl", "Z"]) for i in range(1, 6)])
    a, b = evaluate_coverage(GOLD, one), evaluate_coverage(GOLD, dup)
    assert a.overall_recall == b.overall_recall and a.overall_recall_strict == b.overall_recall_strict
    assert b.precision_strict == 0.2 and len(b.duplicate_gen) == 4


def test_unmatched_untimed_and_beyond_end_listed_not_scored_as_hallucination():
    rep = evaluate_coverage(GOLD, sl(
        g(1, "Explain what a mesh is", 5, 10),
        Step(id="g2", order=2, goal="Press Tab"),
        g(3, "Press Tab", 197, 203, keys=["Tab"]),
    ))
    assert rep.unmatched_gen == ["g1", "g2", "g3"] and rep.untimed_gen == ["g2"] and rep.beyond_end_gen == ["g3"]
    assert rep.precision_lenient == 0.0


# ----------------------------------------------------------------- unverifiable items, claims, state
def test_unverifiable_reference_steps_are_reported_apart_not_as_misses():
    rep = evaluate_coverage(GOLD, sl(g(1, "Add an object with Shift+A", 99, 103, keys=["Shift", "A"])))
    assert rep.n_unverified == 3 and rep.counts["verified"] == len(GOLD.steps) - 3
    assert rep.overall_recall == 0.0                        # R14 is covered but unverified: not in the numerator...
    assert rep.unverified_covered == "1/3"                  # ...and reported separately, as provisional


def test_visual_claims_must_cover_something_shown():
    rep = evaluate_coverage(GOLD, sl(
        g(1, "Press Tab", 27, 30, keys=["Tab"], support="demonstrated", vis="Tab overlay"),   # covers only R03, which is narrated-only
        g(2, "Press Tab to go to Object Mode", 54, 56, keys=["Tab"], support="both", vis="overlay Tab"),
    ))
    assert rep.false_visual_claims == ["g1"] and rep.visual_claims == ["g1", "g2"]
    assert rep.demonstrated_recall_claimed is not None and rep.demonstrated_recall_claimed > 0
    nar_claim = evaluate_coverage(GOLD, sl(g(1, "Press Ctrl+Z to undo", 50, 52, keys=["Ctrl", "Z"], support="narrated")))
    assert nar_claim.demonstrated_recall_claimed == 0.0 and nar_claim.demonstrated_recall > 0   # content vs claim


def test_state_correctness_and_ordering():
    ok = P(kind="mode", target="EDIT_MESH")
    wrong = P(kind="mode", target="OBJECT")
    rep = evaluate_coverage(GOLD, sl(g(1, "Press Ctrl+Z to undo into Edit Mode", 57, 60, keys=["Ctrl", "Z"], expected=[ok])))
    assert rep.state_recall == 1.0 and rep.state_wrong_rate == 0.0
    rep2 = evaluate_coverage(GOLD, sl(g(1, "Press Ctrl+Z to undo", 57, 60, keys=["Ctrl", "Z"], expected=[wrong])))
    assert rep2.state_recall == 0.0 and rep2.state_wrong_rate == 1.0
    # prerequisite order: R07 (Tab) must precede R08 (Ctrl+Z); reversing them is a violation
    rev = sl(g(1, "Press Ctrl+Z to undo", 57, 60, keys=["Ctrl", "Z"]), g(2, "Press Tab", 54, 56, keys=["Tab"]))
    rep3 = evaluate_coverage(GOLD, rev)
    assert rep3.prerequisite_violation_rate == 1.0 and rep3.order_inversion_rate == 1.0


def test_deterministic():
    p = narration_only_prediction()
    a, b = evaluate_coverage(GOLD, p), evaluate_coverage(GOLD, p)
    assert a == b
