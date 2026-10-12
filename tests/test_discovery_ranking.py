"""Ranking rules for tutorial discovery (version hints, length, level claims, tie-breaks, caption verification). Offline: caption checks use a
fake `tracks_for`; the real Data API call was verified live once, separately, and is not part of the offline suite."""
import pytest

from ingestion.tutorials import discover, level_claim_from_title, verify_captions, version_hint_from_title
from ingestion.youtube import api


def E(i, title, dur=600, tier="community", published="2024-01-01", ver=None, **kw):
    return {"id": f"{i:011d}", "url": f"https://www.youtube.com/watch?v={i:011d}", "title": title, "channel": "c", "duration_s": dur, "licence": "youtube",
            "chapters": 0, "published": published, "blender_version_hint": ver, "source_tier": tier, "keywords": [], **kw}


@pytest.mark.parametrize("title,want", [("Blender 4.2 Tutorial", "4.2"), ("Easy Low Poly Trees - Blender 3", "3.x"), ("Blender 2.8 Tutorial: Join", "2.8"),
                                        ("Blender 2026 Object Mode Explained", None), ("Learn Blender in 2024", None), ("Fix shading (3.6 LTS)", "3.6"),
                                        ("Join objects", None), ("Blender 4.5+ new features", "4.5")])
def test_version_is_read_only_from_what_the_title_states(title, want):
    assert version_hint_from_title(title) == want


def test_level_claims_are_the_titles_own_words_and_ambiguity_gives_none():
    assert level_claim_from_title("Blender for Beginners") == "beginner"
    assert level_claim_from_title("Advanced hard surface masterclass") == "advanced"
    assert level_claim_from_title("Beginner to Pro rigging") == "beginner"               # a course that STARTS at beginner level
    assert level_claim_from_title("Beginner tips and advanced tricks") is None            # claims both: no claim
    assert level_claim_from_title("Join objects") is None


def test_only_a_true_platform_flag_means_something_and_false_is_unknown():
    # TRUE = creator captions exist (verified live on a creator-captioned video); FALSE = none uploaded by the creator, says nothing about automatic ones
    yes, no = E(1, "Join objects tutorial", captions_flag=True), E(2, "Join objects tutorial copy", captions_flag=False)
    by = {r.title: r for r in discover("tutorial on join objects", [no, yes]).recommendations}
    assert by["Join objects tutorial"].caption_kind == "creator" and by["Join objects tutorial copy"].caption_kind is None
    assert by["Join objects tutorial copy"].captions_available is None and "captions" not in by["Join objects tutorial copy"].note.lower()


def test_ties_are_broken_by_stated_rules_not_by_alphabet():
    entries = [E(1, "Aaa join objects", 9000, published="2020-01-01"), E(2, "Zzz join objects", 900, published="2020-01-01"),
               E(3, "Mmm join objects", 900, tier="official", published="2020-01-01"), E(4, "Bbb join objects", 900, published="2025-01-01")]
    order = [r.title for r in discover("tutorial on join objects", entries, limit=4).recommendations]
    # same score: official first, then a 5-40 minute length, then newer, then title
    assert order == ["Mmm join objects", "Bbb join objects", "Zzz join objects", "Aaa join objects"]


def test_very_short_videos_are_penalised_unless_the_user_asked_for_short():
    entries = [E(1, "Join objects in 1 minute", 60), E(2, "How to join objects", 600)]
    assert [r.title for r in discover("tutorial on join objects", entries).recommendations][0] == "How to join objects"
    short = discover("a short tutorial on join objects", entries)
    assert "1 minute" in short.recommendations[0].title or {r.title for r in short.recommendations} == {e["title"] for e in entries}
    assert not any("too short" in r.note for r in short.recommendations)
    assert any("too short" in r.note for r in discover("tutorial on join objects", entries).recommendations if r.duration_s == 60)


def test_requested_level_uses_the_title_claim_and_says_so():
    entries = [E(1, "Advanced rigging masterclass", 900), E(2, "Rigging for beginners", 900)]
    d = discover("a beginner tutorial on rigging", entries)
    assert d.recommendations[0].title == "Rigging for beginners" and "author's claim" in d.recommendations[0].note
    assert d.recommendations[0].level_claim == "beginner" and d.recommendations[1].level_claim == "advanced"


def test_a_stated_version_beats_an_unknown_one_and_unknown_is_not_treated_as_a_match():
    entries = [E(1, "Join objects tutorial", ver=None), E(2, "Join objects tutorial two", ver="4.2"), E(3, "Join objects tutorial three", ver="2.80")]
    d = discover("tutorial on join objects for Blender 4.2", entries)
    assert d.recommendations[0].blender_version_hint == "4.2"
    by = {r.title: r for r in d.recommendations}
    assert "not stated" in by["Join objects tutorial"].note and "you asked for 4.2" in by["Join objects tutorial three"].note
    assert d.recommendations[-1].blender_version_hint == "2.80"


def test_major_only_hint_matches_the_requested_major():
    d = discover("tutorial on join objects for Blender 3.6", [E(1, "Join objects in Blender 3", ver=None), E(2, "Join objects in Blender 4", ver=None)])
    assert d.recommendations[0].blender_version_hint == "3.x"


def tracks(kinds):
    return lambda vid: [{"language": lang, "kind": kind} for lang, kind in kinds]


def test_verified_captions_reorder_the_shortlist_and_failures_stay_unknown():
    recs = discover("tutorial on join objects", [E(1, "Join objects one"), E(2, "Join objects two"), E(3, "Join objects three")]).recommendations
    by_vid = {"00000000001": [("en", "asr")], "00000000002": [("en", "standard")], "00000000003": None}

    def tracks_for(vid):
        if by_vid[vid] is None:
            raise RuntimeError("403")
        return [{"language": l, "kind": k} for l, k in by_vid[vid]]
    log = verify_captions(recs, tracks_for, max_checks=3)
    kinds = {r.title: r.caption_kind for r in recs}
    assert kinds == {"Join objects one": "auto", "Join objects two": "creator", "Join objects three": None}      # the failed check is unknown, never 'none'
    assert recs[0].title == "Join objects two" and any("failed" in x for x in log)


def test_captions_only_in_another_language_count_as_none_for_english_and_say_so():
    recs = discover("tutorial on join objects", [E(1, "Join objects one")]).recommendations
    verify_captions(recs, tracks([("hi", "asr")]))
    assert recs[0].caption_kind == "none" and recs[0].captions_available is False and "(hi)" in recs[0].note


def test_only_the_top_n_are_checked_to_bound_quota():
    recs = discover("tutorial on join objects", [E(i, f"Join objects {i}") for i in range(1, 6)], limit=5).recommendations
    seen = []
    verify_captions(recs, lambda v: seen.append(v) or [], max_checks=2)
    assert len(seen) == 2 and sum(r.caption_kind is not None for r in recs) == 2


def test_caption_tracks_api_parses_kinds_and_rejects_bad_ids():
    class G:
        calls = []

        def __call__(self, url, params, headers):
            G.calls.append((url, params))
            return {"items": [{"snippet": {"language": "en", "trackKind": "asr", "lastUpdated": "2019-07-16T10:00:00Z"}}]}
    t = api.caption_tracks("34FBeC9mktE", api_key="k", get=G())
    assert t == [{"language": "en", "kind": "asr", "name": None, "last_updated": "2019-07-16"}] and G.calls[0][0].endswith("/captions") and G.calls[0][1]["videoId"] == "34FBeC9mktE"
    with pytest.raises(api.YouTubeApiError):
        api.caption_tracks("bad id", api_key="k", get=G())
    assert api.QUOTA_UNITS["captions"] == 50
