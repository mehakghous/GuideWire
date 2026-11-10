"""The recheck evaluator (ingestion/eval/recheck_eval.py) with scripted providers: no network."""
from ingestion.eval.gold import GoldSet, GoldStep
from ingestion.eval.recheck_eval import UNANSWERABLE, build_items, judge_match, run_video, summarize
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import Step, StepList


def _sl():
    steps = [Step(id="s01", order=1, goal="Create the hip joint", video_start_s=10, video_end_s=30), Step(id="s02", order=2, goal="Bind the skin", video_start_s=200, video_end_s=230)]
    return StepList(source_type="youtube", app="maya", video_id="AAAAAAAAAAA", steps=steps, video_duration_s=300.0)


def _gold():
    acts = [("Create the hip joint", 12.0), ("Rename the knee joint to leftKnee", 100.0), ("Type 0.5 in the twist field", 150.0), ("Bind the skin", 205.0)]
    return GoldSet(duration_s=300.0, annotator="t", app="maya", steps=[GoldStep(order=i, goal=g, t_start=t) for i, (g, t) in enumerate(acts, 1)])


def test_questions_are_built_only_from_missed_actions_each_with_and_without_a_time_plus_the_unanswerable_ones():
    items = build_items(_sl(), _gold(), per_video=5)
    asked = [i for i in items if i["kind"] == "with_time"]
    assert {i["gold"] for i in asked} == {"Rename the knee joint to leftKnee", "Type 0.5 in the twist field"}                 # the two the steps do not cover
    assert [i["kind"] for i in items].count("without_time") == 2 and [i["kind"] for i in items].count("unanswerable") == 2 * len(UNANSWERABLE)
    assert "around 1:40" in next(i for i in asked if "Rename" in i["gold"])["question"]                                       # the labelled time, rounded to 10 s
    assert all("around" not in i["question"] for i in items if i["kind"] == "without_time")


def test_the_window_hit_found_and_correct_are_scored_and_an_invented_answer_is_listed():
    clip = ScriptedProvider([{"found": True, "answer": "He renames it to leftKnee."}, {"found": False, "answer": ""}, {"found": True, "answer": "He types 0.5."}, {"found": False, "answer": ""}]
                            + [{"found": False, "answer": ""}] * 5 + [{"found": True, "answer": "Jazz."}])
    judge = ScriptedProvider([{"match": "yes"}, {"match": "partly"}])
    rows = run_video(clip, _sl(), _gold(), "AAAAAAAAAAA", per_video=5, judge_provider=judge)
    s = summarize(rows)
    assert s["with_time"]["questions"] == 2 and s["with_time"]["window_contains_the_moment"] == 2 and s["with_time"]["found"] == 2
    assert s["with_time"]["correct_yes"] == 1 and s["with_time"]["correct_partly"] == 1
    assert s["without_time"]["questions"] == 2 and s["without_time"]["found"] == 0                                           # no time and no matching step: the clip is the learner's current step
    assert s["unanswerable"]["questions"] == 2 * len(UNANSWERABLE) and s["unanswerable"]["invented_an_answer"][0]["answer"] == "Jazz."


def test_judge_match_accepts_only_the_three_answers():
    assert judge_match(ScriptedProvider([{"match": "partly"}]), "a", "b") == "partly" and judge_match(ScriptedProvider([{"match": "maybe"}]), "a", "b") == "no"


def test_decoys_are_real_actions_from_another_video_that_share_no_words_with_this_one():
    from ingestion.eval.recheck_eval import pick_decoys
    other = GoldSet(duration_s=100.0, annotator="t", app="maya", steps=[GoldStep(order=1, goal="Open the Graph Editor and set the tangent type", t_start=5.0, importance="core"),
                                                                          GoldStep(order=2, goal="Create the hip joint again", t_start=9.0), GoldStep(order=3, goal="Zoom", t_start=12.0)])
    d = pick_decoys(_gold(), [other], n=3)
    assert d == ["Open the Graph Editor and set the tangent type"]                  # the one with overlapping words and the one under four words are left out
    items = build_items(_sl(), _gold(), per_video=2, decoys=d)
    assert [i["kind"] for i in items].count("decoy") == 2 and all(i["gold"] is None for i in items if i["kind"] == "decoy")
