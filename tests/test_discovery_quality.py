"""Tutorial discovery quality: recency, version signals, plain-language requests. Offline: injected search results, no network."""
from datetime import date

import pytest

from ingestion.rigging_discovery import RECENCY_LEVELS, RankingConfig, age_years, discover_rigging, parse_goal, search_queries

TODAY = date(2026, 10, 16)
CFG = RankingConfig(today=TODAY)
GOAL = "rig an ik leg in Maya"


def meta(vid, title, published, minutes=20, **kw):
    return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": title, "channel": "c", "duration_s": minutes * 60, "chapters": 0, "embeddable": True,
            "privacy": "public", "published": published, **kw}


def run(metas, goal=GOAL, config=CFG, limit=3):
    return discover_rigging(goal, limit=limit, config=config, search=lambda q, n: [{"video_id": m["id"], "title": "t", "channel": "c"} for m in metas],
                            metadata=lambda ids: list(metas))


def order(d):
    return [r.url[-3:] for r in d.recommendations]


# ------------------------------------------------------------------ recency
def test_age_comes_from_the_upload_date_and_unknown_dates_stay_unknown():
    assert age_years("2025-10-16", TODAY) == pytest.approx(1.0, abs=0.01)
    assert age_years("2024-03", TODAY) == pytest.approx(2.6, abs=0.1)
    assert age_years(None, TODAY) is None and age_years("garbage", TODAY) is None


def test_with_equal_relevance_the_newer_upload_ranks_first_and_says_what_the_date_means():
    d = run([meta("old", "Maya rigging an IK leg", "2019-05-01"), meta("new", "Maya rigging an IK leg", "2025-09-01")])
    assert order(d) == ["new", "old"]
    note = d.recommendations[0].note
    assert "uploaded 2025-09" in note.lower() and "not the date it was recorded" in note


def test_relevance_beats_recency():
    d = run([meta("rel", "Maya rigging an IK leg: joints, controls and pole vector", "2019-05-01"), meta("new", "Maya modeling a chair", "2026-09-01"),
             meta("sk", "Maya rigging skinning basics", "2026-09-01")])
    assert order(d)[0] == "rel"                                   # the unrelated recent video is not even a candidate
    assert any("chair" in x for x in d.excluded)


def test_recency_is_configurable_and_can_be_switched_off():
    metas = [meta("old", "Maya rigging an IK leg", "2018-01-01"), meta("new", "Maya rigging an IK leg", "2026-06-01")]
    off = run(metas, config=RankingConfig(recency=RECENCY_LEVELS["off"], today=TODAY))
    assert off.recommendations[0].score == off.recommendations[1].score
    hi, lo = (run(metas, config=RankingConfig(recency=w, today=TODAY)) for w in (2.0, 0.5))
    gap = lambda d: d.recommendations[0].score - d.recommendations[1].score
    assert gap(hi) > gap(lo) > 0


def test_a_missing_upload_date_is_neutral_and_said():
    d = run([meta("nod", "Maya rigging an IK leg", None), meta("dat", "Maya rigging an IK leg", "2020-01-01")])
    nod = next(r for r in d.recommendations if r.url.endswith("nod"))
    assert "upload date unknown" in nod.note.lower() and nod.published is None


def test_an_old_video_is_dropped_as_outdated_only_when_better_candidates_exist():
    good = [meta(f"g{i}", f"Maya rigging an IK leg part {i}", "2025-06-01") for i in range(3)]
    old = meta("old", "Maya rigging an IK leg", "2012-01-01")
    d = run(good + [old])
    assert "old" not in " ".join(order(d)) and any("2012" in x and "years ago" in x for x in d.excluded)
    alone = run(good[:2] + [old])                                    # fewer than `limit` alternatives: the old video stays
    assert any(r.url.endswith("old") for r in alone.recommendations)


# ------------------------------------------------------------------ version signals
def test_a_version_in_the_description_counts_and_is_attributed_to_the_description():
    goal = "rig an ik leg in Maya 2024"
    d = run([meta("des", "Maya rigging an IK leg", "2024-05-01", description_head="Recorded in Maya 2022 for beginners"),
             meta("ttl", "Maya 2024 rigging an IK leg", "2024-05-01")], goal=goal)
    by = {r.url[-3:]: r for r in d.recommendations}
    assert "description says maya 2022" in by["des"].note and by["ttl"].score > by["des"].score


def test_creator_captions_listed_add_a_little():
    d = run([meta("cap", "Maya rigging an IK leg", "2024-05-01", captions_flag=True), meta("nop", "Maya rigging an IK leg", "2024-05-01", captions_flag=False)])
    assert order(d)[0] == "cap"


# ------------------------------------------------------------------ plain-language requests (nobody says "inverse kinematics")
@pytest.mark.parametrize("text,part,area,expect_in_plan", [
    ("Help me make a character's legs move properly in Maya", "leg", "IKFK", "IKFK-02"),
    ("I want to rig my character so I can move its feet in Maya", "leg", "IKFK", "IKFK-02"),
    ("Show me how to make the arms bend naturally in Maya", "arm", "SKIN", "SKIN-01"),
    ("I want to switch between two ways of controlling a character's leg in Maya", "leg", "IKFK", "IKFK-06"),
])
def test_everyday_requests_become_the_right_narrow_task(text, part, area, expect_in_plan):
    g = parse_goal(text)
    assert g.app == "maya" and g.part == part and area in g.areas and expect_in_plan in g.plan
    assert g.clarification is None and "I read this as" in " ".join(g.notes)
    assert len(g.areas) <= 3                                          # the request was not widened into a whole-character rig
    q = search_queries(g)
    assert q and all(part in s and s.startswith("maya ") for s in q) and not any(w in " ".join(q) for w in ("properly", "naturally", "help"))


def test_narrow_requests_do_not_get_the_whole_rig_but_technical_and_broad_ones_do():
    assert set(parse_goal("rig my character so I can move its feet in Maya").areas) == {"IKFK", "CTRL"}
    assert len(parse_goal("rig a biped character in Maya with IK legs and skinning").areas) == 6
    assert len(parse_goal("rig the whole character in Maya").areas) >= 5


def test_move_is_read_as_setting_up_not_animating_and_that_is_said():
    assert "animating a walk" in " ".join(parse_goal("make the legs move in Maya").notes)


def test_technical_wording_still_works():
    g = parse_goal("ik fk switch for the arm in Houdini")
    assert g.app == "houdini" and "IKFK-06" in g.plan and g.part == "arm"


def test_a_request_that_could_mean_two_different_tutorials_asks_one_question_and_spends_nothing():
    calls = []
    def search(q, n):
        calls.append(q)
        return []
    d = discover_rigging("Teach me how to make a character ready for animation in Maya", search=search, metadata=lambda ids: [])
    assert calls == [] and d.quota_units == 0 and d.recommendations == []
    assert "Which do you want" in " ".join(d.notes) and "full rig with controls" in " ".join(d.notes)
    clear = parse_goal("get my character ready for animation with controls in Maya")
    assert clear.clarification is None                                 # the person already said which


def test_a_whole_character_goal_that_mentions_legs_keeps_its_wider_search_and_ready_for_animation_does_not_become_animation():
    g = parse_goal("rig a biped character in Maya 2024 with IK legs and skinning")
    assert not g.narrow and "rig" in " ".join(search_queries(g)) and "biped" in " ".join(search_queries(g))
    r = parse_goal("get my character ready for animation with controls in Maya")
    assert "ANIM" not in r.areas and "CURV" not in r.areas and "CTRL" in r.areas
