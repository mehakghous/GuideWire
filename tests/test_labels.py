"""GW-041: labelling sheets, annotator agreement, held-out evaluation with funnel and miss categories, video selection. Offline, no local data needed."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ingestion.eval.gold import GoldSet
from ingestion.eval.heldout import CATEGORIES, evaluate_video, pool, run_manifest
from ingestion.eval.labels import agreement, load_csv, parse_time, to_csv

ROOT = Path(__file__).resolve().parent.parent
HEADER = "start,end,action,evidence,importance,keys_or_menu,notes\n"


def sheet(*rows):
    return HEADER + "\n".join(rows) + "\n"


def load(text, dur=60, annotator="a"):
    return load_csv(text, duration_s=dur, video_id="VID", title="t", annotator=annotator)


# ============================================================ parsing and validation
@pytest.mark.parametrize("v,want", [("0:21", 21), ("1:05", 65), ("1:02:03", 3723), ("83", 83), ("12.5", 12.5), ("0:21.5", 21.5)])
def test_times_are_read_in_every_common_form(v, want):
    assert parse_time(v) == want


@pytest.mark.parametrize("v", ["", "abc", "1:99", "1:2:3:4", "-5"])
def test_unreadable_times_are_rejected(v):
    with pytest.raises(ValueError):
        parse_time(v)


def test_a_valid_sheet_becomes_a_reference():
    g, pr = load(sheet("0:05,0:08,Press Tab to enter Edit Mode,both,core,Tab,", "0:20,,Select a vertex,said,optional,,heard only"))
    assert not pr.errors and len(g.steps) == 2
    a, b = g.steps
    assert (a.t_start, a.t_end, a.evidence_type, a.importance, a.actions[0].keys) == (5, 8, "both", "core", ["Tab"])
    assert b.evidence_type == "narrated" and b.note == "heard only" and a.verification == "human" and a.is_verified


def test_every_problem_is_reported_with_its_row_number_and_nothing_is_repaired():
    g, pr = load(sheet("0:05,,Press Tab,both,core,,", "bad,,Select,said,core,,", "0:10,,,said,core,,", "0:12,,Move,maybe,core,,", "0:14,,Scale,said,huge,,", "1:30,,Late,said,core,,", "0:30,0:20,Reverse,said,core,,"))
    assert g is None
    text = " | ".join(pr.errors)
    for needle in ("row 3: cannot read time", "row 4: the action is empty", "row 5: evidence must be", "row 6: importance must be", "row 7: time is past the end", "row 8: end is before start"):
        assert needle in text, needle


def test_warnings_for_order_and_duplicates_do_not_block_the_sheet():
    g, pr = load(sheet("0:20,,Press Tab to enter Edit Mode,both,core,,", "0:10,,Select a vertex,said,core,,", "0:20,,Press Tab to enter Edit Mode,both,core,,"))
    assert g is not None and len(g.steps) == 3
    assert any("before the previous row" in w for w in pr.warnings) and any("duplicate" in w for w in pr.warnings)


def test_blank_and_malformed_sheets_say_so_instead_of_crashing():
    assert "no rows" in load(HEADER)[1].errors[0]
    assert "missing column" in load("start,action\n0:01,x\n")[1].errors[0]
    assert load(sheet(",,,,,,"))[1].errors


def test_the_existing_reference_survives_a_round_trip_through_the_sheet_format():
    g = GoldSet.model_validate(json.loads((ROOT / "eval_data" / "gold" / "34FBeC9mktE.reference.v1.json").read_text(encoding="utf-8")))
    g2, pr = load_csv(to_csv(g), duration_s=g.duration_s, video_id=g.video_id, title=g.title, annotator="x")
    assert not pr.errors and len(g2.steps) == len(g.steps)
    assert [s.evidence_type for s in g2.steps] == [s.evidence_type for s in g.steps] and [s.importance for s in g2.steps] == [s.importance for s in g.steps]
    assert all(abs(a.t_start - b.t_start) < 0.11 for a, b in zip(g.steps, g2.steps))


# ============================================================ agreement
def G(*rows, a="a"):
    return load(sheet(*rows), annotator=a)[0]


def test_agreement_of_identical_sheets_is_perfect_and_disagreement_is_listed():
    rows = ["0:05,,Press Tab to enter Edit Mode,both,core,,", "0:20,,Select two vertices,said,core,,", "0:40,,Press G to move them,shown,optional,,"]
    assert agreement(G(*rows), G(*rows, a="b")).dice == 1.0
    b = G(rows[0], "0:21,,Select two vertices,both,core,,", "0:50,,Add a cube from the Add menu,shown,core,,", a="b")
    ag = agreement(G(*rows), b)
    assert (ag.n_a, ag.n_b, ag.matched) == (3, 3, 2) and ag.dice == pytest.approx(2 / 3, abs=0.01)
    assert ag.only_a == ["Press G to move them"] and ag.only_b == ["Add a cube from the Add menu"]
    assert ag.evidence_agreement == 0.5 and ag.importance_agreement == 1.0 and ag.median_start_diff_s in (0, 1)


def test_agreement_is_one_to_one():
    a = G("0:05,,Press Tab,both,core,,")
    b = G("0:05,,Press Tab,both,core,,", "0:06,,Press Tab again,both,core,,", a="b")
    assert agreement(a, b).matched == 1


# ============================================================ the evaluation: funnel and categories
VTT = "\n".join(["WEBVTT", "", "00:00:05.000 --> 00:00:09.000", "first press tab to enter edit mode", "",
                 "00:00:20.000 --> 00:00:25.000", "now bevel the edges with control b", "",
                 "00:00:50.000 --> 00:00:54.000", "and that is how it works", ""])
LABELS = sheet("0:05,0:08,Press Tab to enter Edit Mode,both,core,Tab,",                 # said and recognised -> credited
               "0:20,0:24,Bevel the edges with Ctrl + B,said,core,Ctrl + B,",             # said, but the rules have no bevel -> outside_catalog
               "0:35,,Rotate the camera around the cube,shown,core,,",                    # shown only -> demonstrated_only
               "0:45,,Select two vertices,said,core,,")                                   # labelled as said but nothing near it in the captions -> not_in_captions


def test_every_action_is_credited_or_given_exactly_one_reason():
    r = evaluate_video(load(LABELS)[0], VTT, version="2.80")
    cats = {k: v for k, v in r["categories"].items() if v}
    assert cats == {"outside_catalog": ["H02"], "demonstrated_only": ["H03"], "not_in_captions": ["H04"]}
    assert r["accounted"] and r["n_narrated_or_both"] == 3 and r["narrated_covered_lenient"] == 1
    assert r["funnel"] == {"narrated_refs": 3, "in_captions": 2, "recognised": 1, "emitted": 1}
    flat = [x for v in r["categories"].values() for x in v]
    assert len(flat) == len(set(flat)) and set(r["categories"]) == set(CATEGORIES)


def test_demonstrated_only_actions_are_not_counted_against_the_transcript_route():
    r = evaluate_video(load(LABELS)[0], VTT)
    p = pool([r])
    assert p["narrated_or_both"] == 3 and p["demonstrated_only_not_counted_against_transcripts"] == 1
    assert p["narrated_recall_lenient"] == pytest.approx(1 / 3, abs=0.01) and p["funnel_rates"]["emitted"] == pytest.approx(1 / 3, abs=0.01)


def test_a_video_with_no_recognised_steps_is_scored_not_crashed():
    r = evaluate_video(load(LABELS)[0], "WEBVTT\n\n00:00:05.000 --> 00:00:09.000\nwelcome everybody\n\n00:00:30.000 --> 00:00:33.000\nthanks for watching\n")
    assert r["n_generated"] == 0 and r["narrated_covered_lenient"] == 0 and r["accounted"]


def test_manifest_run_pools_videos_reports_agreement_and_names_what_is_missing(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "VID.transcript.txt").write_text(VTT, encoding="utf-8")
    (tmp_path / "VID.ayesha.csv").write_text(LABELS, encoding="utf-8")
    (tmp_path / "VID.second.csv").write_text(sheet("0:05,,Press Tab to enter Edit Mode,both,core,,", "0:21,,Bevel the edges,said,core,,"), encoding="utf-8")
    (tmp_path / "NOPE.ayesha.csv").write_text(HEADER, encoding="utf-8")
    man = {"transcripts_dir": str(tmp_path / "t"), "videos": [
        {"video_id": "VID", "title": "x", "duration_s": 60, "annotators": ["ayesha", "second"]},
        {"video_id": "NOPE", "title": "y", "duration_s": 60, "annotators": ["ayesha"]},
        {"video_id": "UNLABELLED", "title": "z", "duration_s": 60, "annotators": ["ayesha"]}]}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(man), encoding="utf-8")
    res = run_manifest(mp)
    assert res["labelled_videos"] == 1 and res["pooled"]["videos"] == 1
    assert res["agreement"]["VID"]["matched"] == 2 and res["agreement"]["VID"]["dice"] == pytest.approx(2 * 2 / (4 + 2), abs=0.01)
    assert "no rows" in res["problems"]["NOPE.ayesha"][0] and "not labelled yet" in res["problems"]["UNLABELLED.ayesha"][0]


# ============================================================ video selection
def _script():
    spec = importlib.util.spec_from_file_location("prepare_labelling", ROOT / "scripts" / "prepare_labelling.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prepare_labelling"] = mod
    spec.loader.exec_module(mod)
    return mod


def cands():
    return [{"id": f"{i:011d}", "channel": f"ch{i % 7}", "duration_s": d, "found_by": [f"topic{i % 3}"], "title": f"t{i}"} for i, d in
            enumerate([300, 400, 100, 5000, 600, 700, 800, 900, 500, 450, 350, 650, 750, 280, 320], start=1)]


def test_selection_is_deterministic_and_respects_its_constraints():
    pl = _script()
    reviewed = {"00000000002"}
    a, b = pl.choose(cands(), reviewed, 5), pl.choose(cands(), reviewed, 5)
    assert [e["id"] for e in a] == [e["id"] for e in b] and len(a) == 5
    assert len({e["channel"] for e in a}) == 5 and all(240 <= e["duration_s"] <= 900 for e in a) and "00000000002" not in {e["id"] for e in a}
    assert len({e["topic"] for e in a}) == 3                                         # topics are spread, not exhausted one by one


def test_selection_skips_videos_that_cannot_be_used_and_never_repeats_a_channel():
    pl = _script()
    refuse = {c["id"] for c in cands()[:6]}
    got = pl.choose(cands(), set(), 6, accept=lambda e: e["id"] not in refuse)
    assert refuse.isdisjoint({e["id"] for e in got}) and len({e["channel"] for e in got}) == len(got)


def test_the_prepared_manifest_in_the_repo_is_consistent():
    man = json.loads((ROOT / "eval_data" / "labels" / "manifest.json").read_text(encoding="utf-8"))
    ids = [v["video_id"] for v in man["videos"]]
    assert len(ids) == len(set(ids)) >= 10 and len({v["channel"] for v in man["videos"]}) == len(ids)
    assert sum(len(v["annotators"]) > 1 for v in man["videos"]) >= 3
    reviewed = {e["id"] for e in json.loads((ROOT / "knowledge" / "tutorial_index.json").read_text(encoding="utf-8"))["entries"]}
    assert reviewed.isdisjoint(ids)                                                   # none of the rule-tuning videos
    for v in man["videos"]:
        for a in v["annotators"]:
            assert (ROOT / "eval_data" / "labels" / f"{v['video_id']}.{a}.csv").exists()
