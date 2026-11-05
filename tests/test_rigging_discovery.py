import json

import pytest

from ingestion import cli
from ingestion.rigging_discovery import MAX_QUERIES, discover_rigging, parse_goal, search_queries
from ingestion.youtube import api

GOAL = "I want to rig a biped character in Maya 2024 with IK legs"

HITS = [{"video_id": v, "title": "t", "channel": "c"} for v in ("a1", "b2", "c3", "d4", "e5")]
META = [
    {"id": "a1", "url": "https://www.youtube.com/watch?v=a1", "title": "Maya 2024 Character Rigging: joints, IK legs and skinning", "channel": "Some Artist", "duration_s": 3600,
     "licence": "creativeCommon", "chapters": 5, "chapter_titles": ["Create joints", "Orient joints", "Create IK handle", "Bind skin", "Paint skin weights"],
     "embeddable": True, "privacy": "public", "published": "2024-03-01"},
    {"id": "b2", "url": "u/b2", "title": "Blender Rigify in 5 minutes", "channel": "X", "duration_s": 300, "chapters": 0, "embeddable": True, "privacy": "public"},
    {"id": "c3", "url": "u/c3", "title": "Maya modeling a chair", "channel": "Y", "duration_s": 1800, "chapters": 0, "embeddable": True, "privacy": "public"},
    {"id": "d4", "url": "u/d4", "title": "Maya 2022 rigging basics", "channel": "Autodesk", "duration_s": 1500, "chapters": 0, "embeddable": False, "privacy": "public"},
    {"id": "e5", "url": "u/e5", "title": "Maya 2019 rigging a character", "channel": "Old School", "duration_s": 2400, "chapters": 0, "embeddable": True, "privacy": "public"},
]


def fakes():
    calls = {"search": [], "meta": []}
    def search(q, n):
        calls["search"].append(q)
        return HITS
    def meta(ids):
        calls["meta"].append(ids)
        return [m for m in META if m["id"] in ids]
    return search, meta, calls


# ------------------------------------------------------------------ understanding the goal
def test_goal_gives_app_version_and_a_plan_in_teaching_order():
    g = parse_goal(GOAL)
    assert (g.app, g.version, g.needs_app) == ("maya", "2024", False)
    assert g.stages == ["rigging", "IK/FK"] and {"SKEL", "IKFK", "SKIN"} <= set(g.areas)
    assert g.plan.index("SKEL-01") < g.plan.index("ORNT-02") and "IKFK-02" in g.plan
    assert not any(f.startswith("PREP") for f in g.plan) and "PREP-05" in g.prerequisites        # set-up is assumed, not searched for


def test_a_request_without_an_application_asks_and_a_named_feature_joins_the_plan():
    g = parse_goal("teach me character rigging")
    assert g.needs_app and g.app is None
    assert "IKFK-02" in parse_goal("create an IK handle", app="maya").plan
    assert "more than one application" in " ".join(parse_goal("rig in maya or houdini").notes)
    assert parse_goal("houdini 20.5 kinefx skeleton").version == "20.5"


def test_search_queries_are_capped_and_need_an_application():
    q = search_queries(parse_goal(GOAL))
    assert 1 <= len(q) <= MAX_QUERIES and all(s.startswith("maya ") and s.endswith("tutorial") for s in q)
    assert search_queries(parse_goal("rig a character")) == []


# ------------------------------------------------------------------ discovery with fake search
def test_best_match_first_with_reasons_and_the_right_things_left_out():
    search, meta, calls = fakes()
    d = discover_rigging(GOAL, search=search, metadata=meta)
    top = d.recommendations[0]
    assert top.url.endswith("a1") and {"SKEL-01", "IKFK-02", "SKIN-01"} <= set(top.matched_terms)
    assert "areas you need" in top.note and "Judged from metadata only" in top.note
    excluded = " ".join(d.excluded)
    assert "Blender Rigify" in excluded and "chair" in excluded and "cannot be embedded" in excluded     # other app, unrelated, not embeddable
    assert [r.url[-2:] for r in d.recommendations][:2] == ["a1", "e5"]                          # 2019 comes after 2024 but is not removed
    assert "you use 2024" in d.recommendations[1].note


def test_quota_is_counted_and_duplicates_across_searches_are_looked_up_once():
    search, meta, calls = fakes()
    d = discover_rigging(GOAL, search=search, metadata=meta)
    assert d.quota_units == 100 * len(d.queries) + 1 and len(calls["meta"]) == 1 and len(calls["meta"][0]) == len(HITS)


def test_no_live_search_means_no_calls_and_an_honest_empty_result():
    search, meta, calls = fakes()
    d = discover_rigging(GOAL)
    assert d.recommendations == [] and d.quota_units == 0 and "live search was not requested" in " ".join(d.notes)
    asked = discover_rigging("teach me rigging", search=search, metadata=meta)
    assert asked.recommendations == [] and "Which application" in " ".join(asked.notes) and calls["search"] == []     # nothing is spent before the app is known


# ------------------------------------------------------------------ the CLI
def test_cli_find_offline_prints_the_plan_and_spends_nothing(capsys):
    assert cli.main(["find", GOAL]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["goal"]["app"] == "maya" and out["quota_units_used"] == 0 and out["results"] == [] and out["queries"] == []


def test_cli_find_live_uses_the_youtube_api_and_reports_the_cost(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "DISCOVERY_CACHE", tmp_path)
    search, meta, calls = fakes()
    monkeypatch.setattr(api, "search_videos", lambda q, max_results=10, **kw: search(q, max_results))
    monkeypatch.setattr(api, "videos_metadata", meta)
    assert cli.main(["find", "--live", GOAL]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["results"][0]["url"].endswith("a1") and out["quota_units_used"] == 100 * len(out["queries"]) + 1


def test_cli_find_live_api_errors_are_one_line(monkeypatch, capsys):
    def boom(*a, **k):
        raise api.YouTubeApiError("HTTP 403: quota")
    monkeypatch.setattr(api, "search_videos", boom)
    assert cli.main(["find", "--live", GOAL]) == 1
    assert capsys.readouterr().err.startswith("error: HTTP 403")


def test_blender_modelling_requests_still_use_the_old_index(capsys):
    assert cli.main(["find", "edit mode basics"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "constraints" in out and "goal" not in out


@pytest.mark.parametrize("text", ["rig a character", "animate a walk cycle in houdini"])
def test_rigging_goals_without_an_application_or_with_houdini_take_the_new_path(text, capsys):
    cli.main(["find", text])
    assert "goal" in json.loads(capsys.readouterr().out)


# ------------------------------------------------------------------ length is judged against the goal (no fixed 8 to 90 minute rule)
def _entry(title, minutes, **kw):
    return {"id": "x", "url": f"https://www.youtube.com/watch?v={title[:2]}{minutes}", "title": title, "channel": "c", "duration_s": minutes * 60, "chapters": 0,
            "embeddable": True, "privacy": "public", **kw}


def test_expected_length_grows_with_the_goal_and_a_stated_limit_wins():
    from ingestion.rigging_discovery import expected_length
    one = expected_length(parse_goal("create an IK handle in maya"))
    many = expected_length(parse_goal("rig a character in maya with ik, skinning, controls and constraints"))
    full = expected_length(parse_goal("complete character rigging in maya from start to finish"))
    assert one[0] < many[0] and one[1] < 3600 and many[1] is None and full[1] is None and full[0] >= 45 * 60        # a whole rig has no upper bound
    assert expected_length(parse_goal("rig a biped in maya under 20 minutes")) == (0, 1200, "you asked for under 20 minutes")


def test_a_long_tutorial_is_not_penalised_for_a_big_goal_and_a_short_one_is_for_a_whole_rig():
    search = lambda q, n: [{"video_id": v, "title": "t", "channel": "c"} for v in ("l", "s")]
    metas = [_entry("Maya complete character rigging course: joints, IK, skinning, controls", 300), _entry("Maya complete character rigging: joints, IK, skinning, controls", 10)]
    d = discover_rigging("complete character rigging in Maya", search=search, metadata=lambda ids: metas)
    long_, short_ = d.recommendations
    assert long_.duration_s == 300 * 60 and "long for this goal" not in long_.note                                  # five hours for a whole rig is expected
    assert short_.duration_s == 600 and "too short to teach it step by step" in short_.note and long_.score > short_.score


def test_only_a_stated_limit_excludes_by_length():
    search = lambda q, n: [{"video_id": v, "title": "t", "channel": "c"} for v in ("l",)]
    metas = [_entry("Maya rigging an IK leg", 40)]
    kept = discover_rigging("rig an ik leg in maya", search=search, metadata=lambda ids: metas)
    assert len(kept.recommendations) == 1
    cut = discover_rigging("rig an ik leg in maya under 15 minutes", search=search, metadata=lambda ids: metas)
    assert cut.recommendations == [] and "longer than the 15 you asked for" in " ".join(cut.excluded)


# ------------------------------------------------------------------ lessons from the first real search (2026-10-15)
def _discover(*metas, goal="rig a biped character in Maya with IK legs and skinning"):
    return discover_rigging(goal, search=lambda q, n: [{"video_id": m["id"], "title": "t", "channel": "c"} for m in metas], metadata=lambda ids: list(metas))


def test_query_has_no_filler_words():
    assert not any(" and " in f" {q} " for q in search_queries(parse_goal("rig a biped character in Maya with IK legs and skinning")))


def test_an_automatic_rigging_tool_ranks_below_a_manual_tutorial_unless_you_asked_for_it():
    manual = {**_entry("Maya character rigging: joints, IK legs and skinning", 30), "id": "m"}
    auto = {**_entry("Maya Quick Rig a character: fast auto rig tutorial for beginners", 30), "id": "q"}
    d = _discover(auto, manual)
    assert d.recommendations[0].title.startswith("Maya character rigging") and "automatic rigging tool" in d.recommendations[1].note
    wanted = _discover(auto, goal="quick rig a character in Maya")
    assert "automatic rigging tool" not in wanted.recommendations[0].note


def test_series_parts_are_named_as_such_and_titles_naming_the_stage_get_credit():
    d = _discover({**_entry("Maya Character Rigging - Part 10. leg IK controls", 20), "id": "p"})
    assert "part 10 of a series" in d.recommendations[0].note.lower()
    generic = _discover({**_entry("Character rigging for beginners in Maya 2024", 20), "id": "g"}, goal="rig a character in Maya 2024")
    assert generic.recommendations[0].score >= 3.0 + 1.0 + 1.0 - 0.01                       # app named 3, same year 1, stage named 1


def test_area_wording_counts_where_no_catalog_feature_matches():
    from ingestion.rigging_discovery import touched_areas
    g = parse_goal("rig an ik leg in maya")
    assert "IKFK" in touched_areas(_entry("Rigging for Beginners: IK Legs in Maya", 17), g)


def test_a_live_run_can_be_saved_and_replayed_with_no_quota(monkeypatch, capsys, tmp_path):
    search, meta, calls = fakes()
    monkeypatch.setattr(cli, "DISCOVERY_CACHE", tmp_path)
    monkeypatch.setattr(api, "search_videos", lambda q, max_results=10, **kw: search(q, max_results))
    monkeypatch.setattr(api, "videos_metadata", meta)
    assert cli.main(["find", "--live", GOAL]) == 0
    live = json.loads(capsys.readouterr().out)
    [saved] = list(tmp_path.glob("discovery_*.json"))
    calls["search"].clear()
    assert cli.main(["find", "--replay", str(saved), GOAL]) == 0
    again = json.loads(capsys.readouterr().out)
    assert [r["url"] for r in again["results"]] == [r["url"] for r in live["results"]] and calls["search"] == []
