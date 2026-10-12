"""Offline tests for transcript/subtitle ingestion. The full first-video transcript is a LOCAL fixture (local_data/, git-ignored:
it is YouTube caption text supplied by the user); those tests skip when it is absent. The version-controlled corpus uses a
short synthetic VTT written for this repository."""
from pathlib import Path

import pytest

from ingestion.eval.transcript_eval import evaluate_transcript
from ingestion.transcript import parse_cues
from ingestion.transcript_ingest import (
    choose_ops, clean_cues, group_units, ingest_transcript, parse_timed_text,
)
from ingestion.validate import ValidationFailure

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "local_data" / "34FBeC9mktE.transcript.txt"
REF1 = ROOT / "eval_data" / "gold" / "34FBeC9mktE.reference.v1.json"
SYN = (ROOT / "tests" / "corpus" / "transcript_synthetic.vtt").read_text(encoding="utf-8")


# ---------------------------------------------------------------- formats
def test_parses_srt_vtt_plain_markdown_and_seconds_formats():
    srt = "1\n00:00:05,000 --> 00:00:09,000\nPress Tab\n\n2\n00:00:10,000 --> 00:00:12,000\nthen go on\n"
    assert [c.start_s for c in parse_timed_text(srt)] == [5.0, 10.0]
    plain = "00:00:05.500 press tab\n00:00:08.000 then go on"
    c = parse_timed_text(plain, duration_s=20)
    assert (c[0].start_s, c[0].end_s, c[1].end_s) == (5.5, 8.0, 20)
    md = "* `00:00:01.140`[object mode is the default](https://x.example/run)\n* `00:00:03.000`[mode of blender](https://x.example/run)"
    assert parse_timed_text(md)[0].text == "object mode is the default"
    assert parse_timed_text("[12s] hello there\n[15s] more words")[0].start_s == 12.0
    assert parse_timed_text("1:23 minute text\n2:05 later text")[1].start_s == 125.0
    with pytest.raises(ValueError):
        parse_timed_text("no timestamps here at all")


def test_cleaning_drops_empty_duplicate_and_rolling_overlap():
    from ingestion.transcript import Cue
    cues = [Cue(0, 2, "press tab to enter"), Cue(2, 4, "press tab to enter"), Cue(4, 6, "  "),
            Cue(6, 8, "tab to enter edit mode now"), Cue(8, 10, "go on")]
    out, st = clean_cues(cues)
    assert st["duplicate"] == 1 and st["empty"] == 1 and st["overlap_trimmed"] == 1
    assert [c.text for c in out] == ["press tab to enter", "edit mode now", "go on"]


# ---------------------------------------------------------------- what a transcript can and cannot say
def synth():
    return ingest_transcript(SYN, duration_s=100, version="2.80", video_id="synthetic")


def test_steps_are_narrated_never_demonstrated():
    r = synth()
    assert r.steplist.source_type == "transcript"
    for s in r.steplist.steps:
        assert s.support == "narrated" and s.provenance == "transcript_rules"
        assert s.visual_evidence is None and s.evidence and s.source_refs[-1].startswith("transcript:")
        assert any("Narrated only" in a for a in s.assumptions)
        assert any("expected state comes from the catalog" in a for a in s.assumptions)
    assert any("demonstrated-only actions are not produced" in lim for lim in r.limitations)


def test_operations_in_order_and_concept_chatter_is_not_a_step():
    r = synth()
    ops = [s.source_refs[0].split(":")[1].split("@")[0] for s in r.steplist.steps]
    assert ops == ["mode.enter_edit", "select.elements", "mode.enter_object", "history.undo", "select.object", "mode.enter_edit",
                   "object.join", "mode.enter_edit", "select.elements", "mesh.separate"]
    text = " ".join(s.evidence[0] for s in r.steplist.steps).lower()
    assert "fun fact" not in text and "welcome" not in text and "cannot connect" not in text   # chatter produced no step
    assert r.stats["duplicate"] == 1 and r.stats["cues_in"] == 13   # the duplicate cue was dropped; the blank cue never reached the cleaner (parse_cues skips empty bodies)


def test_time_spans_come_from_the_cues_and_are_validated_not_clamped():
    r = synth()
    assert r.steplist.steps[0].video_start_s == 14.0
    with pytest.raises(ValidationFailure) as ei:
        ingest_transcript(SYN, duration_s=60)           # the transcript runs past 60 s: refuse, do not clamp
    assert "TS_BEYOND_END" in str(ei.value)


def test_a_unit_that_mentions_an_operation_without_an_action_becomes_an_explanation():
    text = "00:00:01.000 once again edit multiple mesh objects at once is a feature\n00:00:09.000 and that is all\n"
    r = ingest_transcript(text, duration_s=20)
    assert r.steplist is None and r.explanations and r.explanations[0].start_s == 1.0


def test_descriptions_are_not_mistaken_for_instructions():
    # 'separate objects' and 'join two vertices' are descriptions, not the Separate / Join operations
    for txt in ("because these two vertices belong to separate objects blender restricts me",
                "normally you can press f as in fill to join two vertices with an edge"):
        assert [o.id for o, _ in choose_ops(txt)] == []
    assert [o.id for o, _ in choose_ops("go to the object menu and select join")] == ["object.join"]


def test_matched_wording_is_kept_on_the_step():
    r = ingest_transcript("00:00:01.000 to do this simply select all the objects you would like to edit and go into edit mode\n"
                          "00:00:09.000 done", duration_s=30)
    first = r.steplist.steps[0]
    assert first.actions[0].value and "select all the objects" in first.actions[0].value


def test_empty_or_unparseable_input_fails_loudly():
    with pytest.raises(ValueError):
        ingest_transcript("just prose with no times")
    assert ingest_transcript("00:00:01.000 hello\n00:00:03.000 world\n00:00:05.000 again", duration_s=10).steplist is None


# ---------------------------------------------------------------- the real first-video transcript (local fixture)
needs_local = pytest.mark.skipif(not LOCAL.exists(), reason="local transcript fixture not present (git-ignored)")


@needs_local
def test_first_video_transcript_invariants_and_regression_floors():
    r = evaluate_transcript(LOCAL.read_text(encoding="utf-8"), REF1, 188.0)
    # invariants a transcript can guarantee
    assert r["demonstrated_visual_claims"] == 0 and r["demonstrated_recall_claimed"] == 0.0     # never claims visual evidence
    assert r["unsupported_evidence_quotes"] == 0 and r["false_visual_claims"] == []
    assert r["timestamps_beyond_end"] == [] and r["untimed"] == []
    assert "R16" in r["not_applicable_demonstrated_only_reference_steps"]                      # shown-only step: not scorable, not a miss
    assert r["prerequisite_violation_rate"] in (0.0, None) and (r["order_inversion_rate"] or 0) <= 0.1
    assert r["state_wrong_rate_vs_reference"] in (0.0, None)
    # regression floors measured on 2026-10-11 (narrated recall 0.55 / strict 0.50; precision 0.88 / 0.69). They are floors, not targets,
    # and the transcript is the development video the rules were tuned on, so they are optimistic.
    assert r["narrated_recall_lenient"] >= 0.50 and r["narrated_recall_strict"] >= 0.45
    assert r["precision_lenient"] >= 0.80 and r["precision_strict"] >= 0.60
    assert r["temporal_within_tol"] >= 0.5 and r["temporal_median_abs_err_s"] <= 4


@needs_local
def test_first_video_transcript_misses_the_visual_only_content_by_design():
    r = evaluate_transcript(LOCAL.read_text(encoding="utf-8"), REF1, 188.0)
    # reference steps that are only visible (nobody says them) cannot appear: the undo/Tab/undo demonstration at 49-61 s
    assert not ({"R06", "R07", "R08"} & set(r["covered_reference_ids"]))
    assert r["narrated_recall_lenient"] < 0.9          # a transcript alone is not a substitute for watching the video
