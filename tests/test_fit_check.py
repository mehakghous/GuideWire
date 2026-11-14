"""Discovery fit check (D2): clip windows, how an answer moves the ranking, failures, and the wiring in the app's finder. A fake model; no network."""
import pytest

from app import discovery
from ingestion import fit_check as fc
from shared.answer import TutorialRecommendation


def rec(title, score, vid, dur=600.0):
    return TutorialRecommendation(title=title, url=f"https://www.youtube.com/watch?v={vid}", score=score, duration_s=dur)


class FakeModel:
    """Answers from a table keyed by video id; records every call."""
    model_id = "fake"

    def __init__(self, table):
        self.table, self.calls = table, []

    def generate_json(self, *, system, prompt, schema, video_url=None):
        self.calls.append((prompt, video_url))
        vid = video_url.split("v=")[1].split("#")[0]
        out = self.table[vid]
        if isinstance(out, Exception):
            raise out
        return out


def ans(app="maya", covers="yes", level="beginner", teaches="Rigs a leg with IK.", problem=""):
    return {"app_shown": app, "covers": covers, "level": level, "teaches": teaches, "problem": problem}


def test_the_clip_is_the_start_of_the_video_and_never_longer_than_the_video():
    url, win = fc.clip_url("https://www.youtube.com/watch?v=abc", 600)
    assert url.endswith("#t=0,120") and win == (0, 120)
    url, win = fc.clip_url("https://www.youtube.com/watch?v=abc#t=5,9", 70)
    assert url.endswith("#t=0,70") and win == (0, 70)
    assert fc.clip_url("https://www.youtube.com/watch?v=abc", None)[1] == (0, 120)


def test_the_prompt_carries_the_request_the_app_and_the_level_but_nothing_else():
    m = FakeModel({"a": ans()})
    fc.check_fit(m, rec("t", 5, "a"), "rig a leg with ik", "maya", "beginner")
    prompt, url = m.calls[0]
    assert "rig a leg with ik" in prompt and "Maya" in prompt and "beginner" in prompt and url.endswith("#t=0,120")


def test_a_wrong_application_is_pushed_out_and_a_clear_match_is_lifted():
    recs = [rec("Wrong app", 9.0, "w"), rec("Other topic", 8.6, "o"), rec("Right", 8.2, "r")]
    m = FakeModel({"w": ans("blender"), "o": ans("maya", "partly"), "r": ans("maya", "yes")})
    new, fits = fc.apply_fit_checks(recs, m, "rig a leg with ik", "maya")
    assert [r.title for r in new] == ["Right", "Other topic", "Wrong app"] and len(fits) == 3 and len(m.calls) == 3
    assert "shows Blender, not Maya" in new[2].note and "matches what you asked for" in new[0].note and "only part" in new[1].note


def test_drop_wrong_app_leaves_it_out_and_unclear_or_other_is_not_a_mismatch():
    recs = [rec("Wrong app", 9.0, "w"), rec("Title card", 8.0, "t"), rec("Right", 7.5, "r")]
    m = FakeModel({"w": ans("houdini"), "t": ans("unclear", "unclear"), "r": ans("other", "yes")})
    new, _ = fc.apply_fit_checks(recs, m, "x", "maya", drop_wrong_app=True)
    assert [r.title for r in new] == ["Right", "Title card"]


def test_only_the_top_suggestions_are_checked_and_the_rest_keep_their_order():
    recs = [rec(f"v{i}", 9 - i, f"v{i}") for i in range(5)]
    m = FakeModel({f"v{i}": ans() for i in range(5)})
    new, fits = fc.apply_fit_checks(recs, m, "x", "maya", top=3)
    assert len(m.calls) == 3 and len(fits) == 3 and [r.title for r in new[3:]] == ["v3", "v4"] and all("Not checked" not in r.note for r in new[:3])


def test_a_failed_call_leaves_the_suggestion_unchanged_and_says_so():
    recs = [rec("A", 9.0, "a")]
    new, fits = fc.apply_fit_checks(recs, FakeModel({"a": RuntimeError("quota")}), "x", "maya")
    assert new[0].score == 9.0 and "Not checked against the video itself" in new[0].note and not fits[0].checked and "RuntimeError" in fits[0].reason
    assert fc.adjustment(fits[0], "maya") == 0.0


def test_a_level_mismatch_is_said_in_plain_words():
    f = fc.Fit(True, "maya", "yes", "advanced", "Builds a full rig.", "", clip=(0, 120))
    assert "advanced level; you said beginner" in fc.describe(f, "maya", "beginner")
    assert "level" not in fc.describe(f, "maya", None)


def _live(monkeypatch=None):
    vids = [{"id": f"vid{i:08d}", "url": f"https://www.youtube.com/watch?v=vid{i:08d}", "title": t, "channel": "c", "duration_s": 600, "published": "2025-03-01", "chapters": 0, "chapter_titles": [],
             "description_head": "", "licence": "youtube", "captions_flag": None, "embeddable": True, "privacy": "public"}
            for i, t in enumerate(["Rigging a Leg in Maya with IK handles", "Maya leg rig tutorial", "Maya IK leg setup guide"])]
    return (lambda q, n: [{"video_id": v["id"], "title": v["title"], "channel": "c"} for v in vids]), (lambda ids: [v for v in vids if v["id"] in ids]), vids


def test_the_app_finder_runs_the_check_on_live_results_only_and_says_what_it_did():
    search, meta, vids = _live()
    m = FakeModel({v["id"]: ans("maya", "yes") for v in vids} | {vids[0]["id"]: ans("blender")})
    r = discovery.find_tutorials("I am a beginner and want to rig a leg with ik", "maya", search=search, metadata=meta, cache_path=None, fit_provider=m)
    assert r.source == "live" and len(m.calls) == 3 and all("beginner" in c[0] for c in m.calls)
    assert all(vids[0]["id"] not in s.url for s in r.suggestions) and any("different application" in n for n in r.notes)
    assert all("Checked the first 2 min" in s.note for s in r.suggestions) and any("first two minutes" in n for n in r.notes)
    plain = discovery.find_tutorials("rig a leg with ik", "maya", search=search, metadata=meta, cache_path=None)
    assert all("Checked the first" not in s.note for s in plain.suggestions) and discovery.CAVEAT in plain.notes


def test_when_the_check_cannot_run_the_title_ranking_stays_and_the_person_is_told():
    search, meta, _ = _live()

    def no_key():
        raise RuntimeError("no Gemini key")
    r = discovery.find_tutorials("rig a leg with ik", "maya", search=search, metadata=meta, cache_path=None, fit_provider=no_key)
    assert r.source == "live" and len(r.suggestions) == 3 and any("ranked from titles only" in n for n in r.notes)


def test_the_eval_script_lists_its_calls_without_spending(capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("fit_check_eval", Path(__file__).resolve().parents[1] / "scripts" / "fit_check_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.run(True) == {} and "18 calls" in capsys.readouterr().out
    vids = mod.videos()
    for vid in mod.GOALS:
        roles = [(role, vids[r.url.split("v=")[1]]["app"]) for role, r, _ in mod.candidates(vid, vids)]
        assert roles[0][1] != mod.GOALS[vid][1] and roles[1][1] == roles[2][1] == mod.GOALS[vid][1] and roles[2][0] == "target"


@pytest.mark.parametrize("app,shown,expected", [("maya", "blender", True), ("maya", "maya", False), ("maya", "other", False), ("maya", "unclear", False), (None, "blender", False)])
def test_what_counts_as_a_wrong_application(app, shown, expected):
    assert fc.wrong_application(fc.Fit(True, shown, "yes"), app) is expected
