"""Regression tests for the four input flows, written after probing the real router (Part XI of the technical plan).
Each test names the defect it pins. Offline: no network, no key, no model."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingestion.handoff import (
    IngestionPlan, Section, classify_url, find_urls, locate_topic, parse_section, plan_ingestion, read_cached_captions, slice_timed_text,
)
from ingestion.kb.index import KnowledgeBase
from ingestion.router import route
from ingestion.text_steps import parse_written
from ingestion.tutorials import discover, load_index, parse_request
from ingestion.youtube.captions import CaptionResult, CaptionsBlocked, CaptionsUnavailable
from tests.test_kb import FIX, SITE, TUT

ROOT = Path(__file__).resolve().parent.parent
VTT = (ROOT / "tests" / "corpus" / "transcript_synthetic.vtt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    return KnowledgeBase.build({"main": FIX}, db_path=tmp_path_factory.mktemp("kb2") / "kb.sqlite", site_titles=SITE)


def ask(kb, text, **kw):
    return route(text, kb=kb, tutorials=kw.pop("tutorials", TUT), **kw)


# ------------------------------------------------------------------------- B. written instructions
def test_one_clause_is_one_step_when_a_key_is_named_with_a_different_purpose():
    # defect: "Press Ctrl+Z to enter edit mode" produced an undo step AND an enter-edit-mode step with the same wording
    r = parse_written("1. Press Ctrl+Z to enter edit mode\n2. Select the cube\n3. Join them with Ctrl+J")
    assert [s.goal for s in r.steps] == ["Press Ctrl+Z to enter edit mode", "Select the cube", "Join them with Ctrl+J"]
    assert any("you wrote 'ctrl+z'" in f for f in r.steps[0].flags)           # the wrong key is reported, the wording is kept
    assert any("prerequisite not met" in f for f in r.steps[2].flags)         # the contradiction is still found


def test_modelling_verbs_start_a_new_clause():
    # defect: "press Tab, extrude it" stayed one step, so "extrude it" vanished into the Tab step
    r = parse_written("Select the cube, press Tab, extrude it and then bevel the edges.")
    assert [s.goal for s in r.steps] == ["Select the cube", "Press Tab", "Extrude it", "Bevel the edges"]
    assert r.unmatched == ["extrude it", "bevel the edges"]                  # outside the catalog: kept, flagged, not guessed
    assert all("not in the Blender catalog" in " ".join(s.flags) for s in r.steps[2:])


def test_sequencing_words_are_not_part_of_the_instruction_but_order_is_kept():
    r = parse_written("Select both objects. Press Ctrl+J to join. Then press P to separate them.")
    assert [s.goal for s in r.steps][-1] == "Press P to separate them"
    assert any("needs Edit Mode" in f for f in r.steps[-1].flags)            # separating right after joining is flagged, not rewritten


def test_original_text_is_preserved_as_evidence():
    r = parse_written("Press Tab to enter Edit Mode. Select two vertices.")
    assert [s.evidence for s in r.steps] == [["Press Tab to enter Edit Mode"], ["Select two vertices"]]
    assert all(s.provenance == "user_text" and s.source_refs for s in r.steps)


# ------------------------------------------------------------------------- C. questions
@pytest.mark.parametrize("q", ["Why didn't that action work?", "I'm following these instructions, but my screen looks different.",
                               "Continue from where I left off.", "What's the next step?"])
def test_follow_ups_get_a_question_not_a_page_pointer_or_a_decline(kb, q):
    # defect: these returned outside_index (irrelevant manual pointers) or decline
    b = ask(kb, q)
    assert (b.kind, b.route) == ("clarification", "clarify") and b.clarification and not b.pointers and not b.steps
    assert "session_context" in b.needs and b.api_calls == 0


def test_follow_up_mentions_observed_mode_when_known(kb):
    b = ask(kb, "Continue from where I left off.", observed={"mode": "EDIT_MESH"})
    assert "EDIT_MESH" in b.clarification


def test_does_nothing_is_treated_as_a_state_question(kb):
    # defect: "tab does nothing in blender" got the canned "which operation?" question
    b = ask(kb, "tab does nothing in blender")
    assert b.kind == "needs_state" and b.questions


def test_version_in_the_request_text_is_used():
    b = route("How do I join two objects in Blender 4.2?")
    assert any("4.2 taken from the request" in r for r in b.reasons)
    assert not any("taken from the request" in r for r in route("How do I join two objects in Blender 4.2?", version="2.80").reasons)  # the app wins
    assert not any("taken from the request" in r for r in route("How do I join two objects?", version="2.80").reasons)


# ------------------------------------------------------------------------- A. URLs
def test_non_youtube_links_are_refused_explicitly_not_searched_as_tutorials(kb):
    # defect: a Vimeo link + "turn this into steps" was routed to tutorial discovery
    b = ask(kb, "https://vimeo.com/12345 turn this tutorial into steps")
    assert b.kind == "unsupported" and b.route == "tutorial_import" and "vimeo.com" in b.fallback_reason and not b.recommendations
    p = ask(kb, "https://www.youtube.com/playlist?list=PLabcdefghijk turn this into steps")           # playlists are expanded via the official API, on request
    assert p.kind == "tutorial_recommendation" and p.route == "tutorial_import" and "network" in p.needs and not p.recommendations and p.network_calls == 0
    ch = ask(kb, "https://www.youtube.com/@Blender turn this into steps")
    assert ch.kind == "unsupported" and "not a single video" in ch.fallback_reason


@pytest.mark.parametrize("url,kind,vid,start", [
    ("https://www.youtube.com/watch?v=34FBeC9mktE", "youtube_video", "34FBeC9mktE", None),
    ("https://youtu.be/34FBeC9mktE?t=90", "youtube_video", "34FBeC9mktE", 90.0),
    ("https://www.youtube.com/watch?v=34FBeC9mktE&t=1m30s", "youtube_video", "34FBeC9mktE", 90.0),
    ("https://m.youtube.com/shorts/34FBeC9mktE", "youtube_video", "34FBeC9mktE", None),
    ("https://www.youtube.com/@Blender", "youtube_other", None, None),
    ("https://example.com/x", "other", None, None)])
def test_classify_url(url, kind, vid, start):
    i = classify_url(url)
    assert (i.kind, i.video_id, i.start_s) == (kind, vid, start)


def test_section_requests_are_understood_and_reported(kb):
    assert parse_section("from 1:20 to 2:40") == Section(80.0, 160.0, [], "time range in the request")
    assert parse_section("only the first 2 minutes").end_s == 120.0
    assert parse_section("after 0:49").start_s == 49.0
    assert parse_section("just the part about undo").topic == ["undo"]
    assert parse_section("whole thing", url_start_s=60.0).start_s == 60.0 and parse_section("whole thing").is_empty
    b = ask(kb, "https://youtu.be/34FBeC9mktE?t=60 only the part about edit mode")
    assert any("Section requested" in c for c in b.caveats) and b.steps is None


# ------------------------------------------------------------------------- D. discovery
def test_request_constraints_are_parsed():
    w = parse_request("Find a beginner tutorial on selecting objects under 15 minutes for Blender 4.2")
    assert (w.version, w.major, w.minor, w.level, w.max_duration_s) == ("4.2", 4, 2, "beginner", 900)
    assert parse_request("a tutorial for Blender 4.x").minor is None and parse_request("a tutorial for Blender 4.x").major == 4
    s = parse_request("a short tutorial on bevel")
    assert (s.max_duration_s, s.duration_assumed) == (600, True)
    assert parse_request("tutorial", version="2.80").version_from == "argument"


def test_discovery_without_a_topic_asks_what_to_learn(kb):
    # defect: "Find a tutorial compatible with Blender 4.x" returned "nothing matches" instead of asking
    for q in ["Find a tutorial compatible with Blender 4.x.", "Compare a few tutorials and recommend the best one for my skill level."]:
        b = ask(kb, q)
        assert b.kind == "clarification" and "learn" in b.clarification and not b.recommendations


def test_requested_version_is_used_and_mismatch_is_stated():
    # defect: "for Blender 4.2" was ignored and a 2.80 video was recommended with only "tell me your version"
    d = discover("Find a tutorial on select and transform for Blender 4.2", TUT)
    assert d.recommendations and "you asked for 4.2" in d.recommendations[0].note and "tell me your version" not in d.recommendations[0].note
    assert any("None of these was recorded for Blender 4.2" in n for n in d.notes)


def test_duration_limit_excludes_and_says_so():
    d = discover("Find a tutorial on select and transform under 5 minutes", TUT)
    assert d.recommendations == [] and d.excluded and "Left out because longer than 5 min" in d.notes[0]


def test_level_is_never_claimed_without_data():
    d = discover("Find a beginner tutorial on select and transform", TUT)
    # (wording changed on purpose: the title's own claim is now used, and labelled as the author's claim, not as a verified level)
    assert d.recommendations and any("not recorded for any tutorial" in n and "author's claim" in n for n in d.notes)


def test_comparison_uses_metadata_only_and_says_so():
    both = TUT + [{**TUT[0], "id": "CCCCCCCCCCC", "url": "https://www.youtube.com/watch?v=CCCCCCCCCCC", "title": "Move and Select Basics", "duration_s": 300,
                   "channel": "x", "source_tier": "community", "keywords": ["select", "move"]}]
    d = discover("Compare tutorials on select and move", both)
    assert len(d.comparison) >= 2 and any("metadata only" in n for n in d.notes)


def test_discovery_never_returns_an_entry_outside_the_index():
    urls = {e["url"] for e in TUT}
    for q in ["tutorial on select", "tutorial on cake", "tutorial on rigging", "tutorial on nothing"]:
        assert {r.url for r in discover(q, TUT).recommendations} <= urls


def test_the_platform_captions_flag_is_not_used_and_unknown_is_said():
    # changed on purpose (owner's decision, evidence: the flag was false for 62 of 67 live candidates and for a video with an automatic track)
    d = discover("tutorial on edit mode", [{**TUT[0], "captions_flag": False, "title": "Edit Mode", "keywords": ["edit mode"]}])
    r = d.recommendations[0]
    assert r.captions_available is None and r.caption_kind is None and "captions" not in r.note.lower()
    assert any("has not been checked" in n for n in d.notes)


# ------------------------------------------------------------------------- A/D. handoff
def _cache(tmp_path, vid="AAAAAAAAAAA", source="auto", text_vtt=None):
    snippets = [{"start": s, "duration": 3, "text": t} for s, t in
                [(0, "Welcome to this video."), (5, "Press Tab to go into edit mode."), (12, "Then select the vertices."),
                 (60, "Now select both objects and press control J to join them.")]]
    (tmp_path / f"{vid}.json").write_text(json.dumps({"video_id": vid, "fetched_at": datetime.now(timezone.utc).isoformat(), "source": source,
                                                      "language": "en", "tracks": [["en", True]], "snippets": snippets}), encoding="utf-8")


def test_handoff_without_any_transcript_reports_what_is_missing_and_infers_nothing(tmp_path):
    p = plan_ingestion("https://www.youtube.com/watch?v=AAAAAAAAAAA", entry=TUT[0], cache_dir=tmp_path)
    assert p.status == "needs_transcript" and p.bundle is None and len(p.options) == 3
    assert any("nothing was inferred" in r for r in p.reasons)


def test_handoff_from_user_transcript_keeps_provenance():
    p = plan_ingestion("AAAAAAAAAAA", entry=TUT[0], transcript_text=VTT, version="2.80", duration_s=100)
    assert p.status == "ready" and p.source == "user_transcript" and p.bundle.steps
    st = p.bundle.steps.steps[0]
    assert st.support == "narrated" and st.provenance == "transcript_rules" and st.evidence and st.video_start_s is not None
    assert p.bundle.sources[0].kind == "tutorial_video" and p.bundle.sources[0].url.endswith("AAAAAAAAAAA")
    assert p.bundle.api_calls == 0 and p.bundle.network_calls == 0


def test_handoff_uses_cached_captions_and_flags_auto_captions(tmp_path):
    _cache(tmp_path)
    p = plan_ingestion("AAAAAAAAAAA", entry=TUT[0], cache_dir=tmp_path, version="4.2")
    assert p.status == "ready" and p.source == "cached_captions" and p.caption_kind == "auto"
    c = " ".join(p.bundle.caveats)
    assert "automatic captions" in c and "recorded for Blender 2.80; you use 4.2" in c


def test_handoff_expired_cache_is_not_used(tmp_path):
    _cache(tmp_path)
    f = tmp_path / "AAAAAAAAAAA.json"
    d = json.loads(f.read_text())
    d["fetched_at"] = "2020-01-01T00:00:00+00:00"
    f.write_text(json.dumps(d))
    assert read_cached_captions("AAAAAAAAAAA", tmp_path) is None and not f.exists()


@pytest.mark.parametrize("exc", [CaptionsUnavailable("no track"), CaptionsBlocked("blocked")])
def test_handoff_retrieval_failure_is_a_stated_reason_not_a_crash(tmp_path, exc):
    def boom(_vid):
        raise exc
    p = plan_ingestion("AAAAAAAAAAA", cache_dir=tmp_path, fetch=boom)
    assert p.status == "needs_transcript" and any("caption retrieval failed" in r for r in p.reasons) and p.options


def test_handoff_fetch_is_injected_never_implicit(tmp_path):
    calls = []
    def fake(vid):
        calls.append(vid)
        return CaptionResult(vid, "00:00:05.000 Press Tab to go into edit mode.\n00:00:12.000 Then select the vertices.", "creator", "en", "now", False)
    assert plan_ingestion("AAAAAAAAAAA", cache_dir=tmp_path).status == "needs_transcript" and calls == []
    p = plan_ingestion("AAAAAAAAAAA", cache_dir=tmp_path, fetch=fake)
    assert calls == ["AAAAAAAAAAA"] and p.source == "fetched_captions" and p.caption_kind == "creator"


def test_handoff_invalid_source_and_unreadable_transcript(tmp_path):
    assert plan_ingestion("https://vimeo.com/1", cache_dir=tmp_path).status == "invalid_source"
    p = plan_ingestion("AAAAAAAAAAA", transcript_text="this is not a transcript", cache_dir=tmp_path)
    assert p.status == "needs_transcript" and any("could not be read" in r for r in p.reasons)


def test_section_slicing_keeps_absolute_times(tmp_path):
    _cache(tmp_path)
    p = plan_ingestion("AAAAAAAAAAA", cache_dir=tmp_path, section=Section(start_s=50.0))
    assert p.status == "ready"
    times = [s.video_start_s for s in p.bundle.steps.steps]
    assert times and all(t >= 50 for t in times) and any("Only the section 50s" in c for c in p.bundle.caveats)
    cut = slice_timed_text("00:00:05.000 a b c\n00:01:00.000 d e f", 30, None)
    assert cut.startswith("00:01:00.000")


def test_topic_section_is_located_as_a_candidate_to_confirm(tmp_path):
    _cache(tmp_path)
    p = plan_ingestion("AAAAAAAAAAA", cache_dir=tmp_path, section=Section(topic=["join"]))
    assert p.status == "ready" and any("please confirm" in r for r in p.reasons) and p.section.start_s >= 40
    miss = plan_ingestion("AAAAAAAAAAA", cache_dir=tmp_path, section=Section(topic=["sculpt"]))
    assert miss.status == "needs_transcript" and any("nothing in the transcript mentions" in r for r in miss.reasons)


def test_chapters_beat_caption_clusters():
    w = locate_topic("00:00:05.000 join join\n00:02:00.000 other", ["join"], chapters=[(0.0, "Intro"), (90.0, "Joining objects"), (200.0, "End")])
    assert w[0][:2] == (90.0, 200.0) and "chapter" in w[0][2]


def test_handoff_module_never_imports_the_caption_library_or_a_model():
    import ingestion.handoff  # noqa: F401
    assert "youtube_transcript_api" not in sys.modules and "google.genai" not in sys.modules


def test_find_urls_trims_punctuation():
    assert find_urls("see https://youtu.be/34FBeC9mktE, thanks.") == ["https://youtu.be/34FBeC9mktE"]
