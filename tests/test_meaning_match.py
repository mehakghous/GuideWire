"""Matching steps to the human's actions by MEANING (ingestion/eval/meaning.py), tested with a scripted provider: no model, no network."""
from ingestion.eval.gold import GoldSet, GoldStep
from ingestion.eval.meaning import MeaningJudge
from ingestion.eval.phase1 import coverage, report
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import Step, StepList


def _step(i, goal, start, end):
    return Step(id=f"s{i:02d}", order=i, goal=goal, video_start_s=start, video_end_s=end)


def _sl(steps):
    return StepList(source_type="youtube", app="blender", video_id="vid", steps=steps, video_duration_s=100.0)


def _gold(*acts):
    return GoldSet(duration_s=100.0, annotator="test", app="blender", steps=[GoldStep(order=i, goal=g, t_start=t) for i, (g, t) in enumerate(acts, 1)])


SL = _sl([_step(1, "Sign into the account", 0, 10), _step(2, "Open the add menu and pick Armature", 12, 30)])
GOLD = _gold(("log in", 2.0), ("press add", 14.0), ("select the mesh", 16.0))


def test_words_do_not_match_a_synonym_but_meaning_does():
    assert coverage(SL, GOLD)["text_recall_core"] < 1.0                                   # "log in" shares no word with "Sign into the account"
    provider = ScriptedProvider([{"matches": [{"action": "1", "steps": ["s01"]}, {"action": "ACTION 2", "steps": ["s02"]}, {"action": "3", "steps": []}]}])
    m = MeaningJudge(provider).matcher(SL, GOLD)
    assert m(SL.steps[0], GOLD.steps[0]) and m(SL.steps[1], GOLD.steps[1]) and not m(SL.steps[1], GOLD.steps[2])
    c = coverage(SL, GOLD, m)
    assert c["text_recall_core"] == round(2 / 3, 3) and c["step_support"] == 1.0


def test_one_step_can_cover_several_actions():
    gold = _gold(("log in", 2.0), ("press add", 4.0))
    sl = _sl([_step(1, "Log in and press add", 0, 10)])
    m = MeaningJudge(ScriptedProvider([{"matches": [{"action": "1", "steps": ["s01"]}, {"action": "2", "steps": ["s01"]}]}])).matcher(sl, gold)
    assert coverage(sl, gold, m)["text_recall_core"] == 1.0


def test_a_step_outside_the_time_window_or_invented_is_ignored():
    provider = ScriptedProvider([{"matches": [{"action": "1", "steps": ["s02", "s99"]}]}])         # s02 starts at 12 s: outside action 1 (2 s) plus the 5 s tolerance
    m = MeaningJudge(provider).matcher(SL, GOLD)
    assert not m(SL.steps[1], GOLD.steps[0]) and not m(SL.steps[0], GOLD.steps[0])


def test_one_model_call_per_video_and_only_candidates_are_sent():
    provider = ScriptedProvider([{"matches": []}])
    MeaningJudge(provider).judge(SL, GOLD)
    assert len(provider.calls) == 1
    prompt = provider.calls[0]["prompt"]
    assert "ACTION 1: log in" in prompt and "STEP s01" in prompt and "video" not in (provider.calls[0]["video_url"] or "")


def test_report_marks_which_matching_was_used(tmp_path):
    (tmp_path / "gold").mkdir()
    (tmp_path / "gold" / "vid.gold.json").write_text(GOLD.model_dump_json(), encoding="utf-8")
    f = tmp_path / "out.json"
    f.write_text(SL.model_dump_json(), encoding="utf-8")
    assert report([f], tmp_path / "gold")[0]["matching"] == "words"
    judge = MeaningJudge(ScriptedProvider([{"matches": [{"action": "1", "steps": ["s01"]}]}]))
    row = report([f], tmp_path / "gold", judge)[0]
    assert row["matching"] == "meaning" and row["text_recall_core"] == round(1 / 3, 3)


def test_a_model_that_echoes_the_step_line_or_writes_action_with_a_colon_is_still_read():
    provider = ScriptedProvider([{"matches": [{"action": "ACTION 1:", "steps": ["STEP s01: Sign into the account"]}, {"action": "2", "steps": ["s02: Open the add menu"]}]}])
    m = MeaningJudge(provider).matcher(SL, GOLD)
    assert m(SL.steps[0], GOLD.steps[0]) and m(SL.steps[1], GOLD.steps[1])
