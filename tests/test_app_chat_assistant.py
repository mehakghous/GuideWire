"""Ask GuideWire as an assistant that remembers the conversation: tutorials discovered in the chat (the count asked for, relevance, no duplicates), turning one into steps without leaving the chat
(the same `video_steps` pipeline, saved as a normal tutorial), context across messages, general and tutorial-specific questions, failures and retry, and the chat's cards. Fake YouTube and a fake
pipeline: nothing here touches the network or a model."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import discovery  # noqa: E402
from app.ask import Asker  # noqa: E402
from app.chat_context import ChatContext, Video, describe_step, has_topic, requested_count, resolve_video, tutorial_specific, wants_steps_from_video  # noqa: E402
from app.pipeline import PipelineResult  # noqa: E402
from shared.step_record import HowTo, Step, StepList  # noqa: E402

RELEVANT = [
    ("Rigging a Leg in Maya with IK handles", "Rig School", 12 * 60),
    ("Maya leg rig tutorial for beginners", "Anim Lab", 18 * 60),
    ("Leg IK FK switch setup in Maya", "Rig School", 25 * 60),
    ("Maya reverse foot rig for a character leg", "Foot Works", 15 * 60),
    ("Beginner: rig a leg with IK in Maya", "Newbie Rigs", 9 * 60),
    ("Advanced leg rigging with pole vectors in Maya", "Pro Rigs", 40 * 60),
    ("Maya leg skeleton and IK handle explained", "Joint Lab", 14 * 60),
    ("Quick leg IK in Maya", "Fast Rigs", 7 * 60),
    ("Rig a cartoon leg in Maya step by step", "Toon Rigs", 22 * 60),
    ("Maya IK spline leg tutorial", "Spline Lab", 19 * 60),
    ("Leg rigging basics for Maya", "Rig Basics", 16 * 60),
    ("Maya leg joints and IK, the whole workflow", "Joint Lab", 31 * 60),
]
UNRELATED = [("Modeling a wooden chair in Maya", "Chair Co", 20 * 60), ("Maya render settings for beginners", "Render Co", 11 * 60), ("Best pizza recipes of the year", "Cook Co", 10 * 60)]


def make_videos(rows, offset=0):
    return [{"id": f"vid{offset + i:08d}", "url": f"https://www.youtube.com/watch?v=vid{offset + i:08d}", "title": t, "channel": ch, "duration_s": d, "published": f"2025-0{1 + i % 9}-01",
             "chapters": 0, "chapter_titles": [], "description_head": "", "licence": "youtube", "captions_flag": None, "embeddable": True, "privacy": "public"} for i, (t, ch, d) in enumerate(rows)]


def fake_discover(rows, calls=None):
    vids = make_videos(rows)

    def search(q, n):
        return [{"video_id": v["id"], "title": v["title"], "channel": v["channel"]} for v in vids]

    def meta(ids):
        return [v for v in vids if v["id"] in ids]

    def discover(goal, app, limit=3, exclude=(), check=True):
        if calls is not None:
            calls.append({"goal": goal, "app": app, "limit": limit, "exclude": list(exclude), "check": check})
        return discovery.find_tutorials(goal, app, limit=limit, exclude=exclude, search=search, metadata=meta, cache_path=None)
    return discover


def make_steps(n=6, title="Rig a leg with IK"):
    steps = [Step(id=f"s{i:02d}", order=i, goal=f"Do thing number {i}", video_start_s=60 * i, how_to=[HowTo(text=f"Click the thing {i}", support="said")], check=[HowTo(text=f"You see thing {i}", support="said")]) for i in range(1, n + 1)]
    return StepList(source_type="youtube", app="maya", title=title, steps=steps)


class Runner:
    """A fake `video_steps`: records every call; `outcomes` is a list of PipelineResults or exceptions used in turn (the last repeats)."""

    def __init__(self, *outcomes, delay=0.0):
        self.calls, self.outcomes, self.delay = [], list(outcomes) or [PipelineResult(make_steps(), "6 steps found.", ["Drafted automatically; review the steps."], "youtube_video")], delay

    def __call__(self, url, app, status):
        self.calls.append((url, app))
        status("The AI is watching the video...")
        if self.delay:
            time.sleep(self.delay)
        out = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(out, Exception):
            raise out
        return out


def asker(rows=RELEVANT, runner=None, calls=None, **kw):
    return Asker(discover=fake_discover(rows, calls), video_runner=runner if runner is not None else Runner(), **kw)


def find(a, text="give me 5 tutorials for rigging a leg with IK in maya", app="maya"):
    return a.ask(text, app)


# ---------------------------------------------------------------- reading what was asked
@pytest.mark.parametrize("text,want", [("give me 10 tutorials", 10), ("give me ten videos for leg rigging", 10), ("show 3 beginner tutorials", 3), ("top 5 maya rigging videos", 5),
                                       ("I want 7 good leg IK tutorials", 7), ("recommend a tutorial", None), ("a 10 minute tutorial on IK", None), ("a tutorial under 20 minutes", None)])
def test_how_many_tutorials_were_asked_for(text, want):
    assert requested_count(text)[0] == want


def test_a_count_above_what_one_request_can_give_is_capped_and_says_so():
    assert requested_count("give me 50 tutorials") == (20, True)


def test_a_request_with_no_topic_is_told_from_one_with_a_topic():
    assert not has_topic("give me 10 tutorials") and not has_topic("10 more videos please") and not has_topic("show me five tutorials in maya")
    assert has_topic("give me 10 tutorials for leg rigging") and has_topic("find a video on skinning")


@pytest.mark.parametrize("text", ["turn the first one into steps", "make steps for this tutorial", "turn this video into a guide", "can't I just turn into steps here", "convert it to steps",
                                  "make a step by step guide from the second video"])
def test_asks_to_turn_a_video_into_steps(text):
    assert wants_steps_from_video(text, ChatContext(videos=[Video("a", "https://www.youtube.com/watch?v=aaaaaaaaaaa")]))


@pytest.mark.parametrize("text", ["give me the steps to bind the mesh", "what is IK", "how do i make steps in the stairs of my building", "explain step 4", "where do i start rigging in maya", "give me the steps for it", "give me the steps for rigging a leg"])
def test_ordinary_questions_are_not_a_request_to_turn_a_video_into_steps(text):
    assert not wants_steps_from_video(text, ChatContext())


def test_which_questions_are_about_the_tutorial():
    for t in ["what does the instructor do in step 3", "what is he doing at 1:30", "what should i click next", "why did he change the solver", "explain step 4"]:
        assert tutorial_specific(t), t
    for t in ["what is IK", "how do i make an IK handle in maya", "why does my IK knee bend wrong"]:
        assert not tutorial_specific(t), t


# ---------------------------------------------------------------- finding tutorials: the count, relevance, no duplicates
@pytest.mark.parametrize("n", [3, 5, 10])
def test_the_number_of_tutorials_asked_for_is_what_comes_back(n):
    calls = []
    a = asker(calls=calls)
    out = find(a, f"give me {n} tutorials for rigging a leg with IK in maya")
    assert out.route == "discovery" and len(out.videos) == n and calls[0]["limit"] == n
    assert len({v.url for v in out.videos}) == n and len(a.context.videos) == n and len(a.context.shown) == n
    for v in out.videos:
        assert v.title in out.text and v.url in out.text


def test_with_no_number_the_usual_three_come_back():
    assert len(find(asker(), "recommend a tutorial for rigging a leg with IK").videos) == 3


def test_fewer_come_back_when_fewer_are_relevant_and_nothing_unrelated_fills_the_list():
    a = asker(RELEVANT[:4] + UNRELATED)
    out = find(a, "give me 10 tutorials for rigging a leg with IK in maya")
    assert len(out.videos) <= 4 and out.videos
    assert all("leg" in v.title.lower() for v in out.videos)
    assert not any(t in out.text for t, _c, _d in UNRELATED)
    assert f"You asked for 10, but only {len(out.videos)}" in out.headline and "did not add unrelated" in out.headline


def test_each_recommendation_shows_title_creator_length_publication_and_link_and_says_when_one_is_missing():
    rows = make_videos(RELEVANT[:3])
    rows[0]["channel"], rows[0]["published"], rows[0]["duration_s"] = "", "", None
    vids = {v["id"]: v for v in rows}
    d = lambda goal, app, limit=3, exclude=(): discovery.find_tutorials(goal, app, limit=limit, search=lambda q, n: [{"video_id": i, "title": v["title"], "channel": v["channel"]} for i, v in vids.items()],  # noqa: E731
                                                                         metadata=lambda ids: [vids[i] for i in ids], cache_path=None)
    out = Asker(discover=d).ask("give me 3 tutorials for rigging a leg with IK", "maya")
    full = out.text
    assert "Creator: Anim Lab" in full and "Length: 18 min" in full and "Published: 2025-" in full and "https://www.youtube.com/watch?v=" in full
    gone = next(v for v in out.videos if v.title == RELEVANT[0][0])
    assert gone.details() == "Creator: not available | Length: not available | Published: not available" and gone.details() in full


def test_the_same_video_is_never_listed_twice():
    rows = make_videos(RELEVANT[:5])
    again = [{**rows[0], "id": "otherid0001", "url": rows[0]["url"]}]                       # the same link under a second search hit
    pool = rows + again
    d = lambda goal, app, limit=3, exclude=(): discovery.find_tutorials(goal, app, limit=limit, search=lambda q, n: [{"video_id": v["id"], "title": v["title"], "channel": v["channel"]} for v in pool],  # noqa: E731
                                                                         metadata=lambda ids: [v for v in pool if v["id"] in ids], cache_path=None)
    r = d("rig a leg with ik", "maya", limit=10)
    urls = [s.url for s in r.suggestions]
    assert len(urls) == len(set(urls)) == 5


def test_more_tutorials_means_more_of_the_same_goal_and_never_the_ones_already_shown():
    calls = []
    a = asker(calls=calls)
    first = find(a, "give me 5 tutorials for rigging a leg with IK in maya")
    more = a.ask("give me 5 more tutorials", "maya")
    assert calls[1]["goal"] == calls[0]["goal"] and calls[1]["exclude"], "the second request keeps the first one's goal"
    assert {v.url for v in first.videos}.isdisjoint({v.url for v in more.videos}) and len(more.videos) == 5
    assert len(a.context.videos) == 10 and a.context.shown == list(range(5, 10))


def test_a_bare_count_after_a_search_keeps_the_goal_so_the_second_ten_is_still_about_the_leg():
    a = asker()
    find(a, "give me 3 tutorials for rigging a leg with IK in maya")
    out = a.ask("give me 10 tutorials", "maya")
    assert len(out.videos) == 10 and all("leg" in v.title.lower() for v in out.videos)


def test_a_bare_count_with_nothing_to_go_on_asks_what_to_learn_instead_of_searching():
    calls = []
    out = asker(calls=calls).ask("give me 10 tutorials", "maya")
    assert calls == [] and out.videos == [] and "What do you want to learn in Maya" in out.text and "10" in out.text


def test_a_search_that_finds_nothing_says_so_and_a_broken_one_says_it_could_not_search():
    out = asker(UNRELATED).ask("give me 5 tutorials for rigging a leg with IK in maya", "maya")
    assert out.videos == [] and out.text
    broken = Asker(discover=lambda goal, app, limit=3, exclude=(): (_ for _ in ()).throw(RuntimeError("x")))
    assert "could not search" in broken.ask("give me 5 tutorials for rigging a leg", "maya").text


def test_a_discovery_function_that_takes_only_goal_and_app_still_works():
    r = discovery.find_tutorials("rig a leg with ik", "maya", search=lambda q, n: [{"video_id": v["id"], "title": v["title"], "channel": v["channel"]} for v in make_videos(RELEVANT)],
                                 metadata=lambda ids: [v for v in make_videos(RELEVANT) if v["id"] in ids], cache_path=None, limit=10)
    out = Asker(discover=lambda goal, app: r).ask("give me 10 tutorials for rigging a leg", "maya")
    assert len(out.videos) == len(r.suggestions) > 3


def test_a_beginner_goal_ranks_a_title_that_says_beginner_above_one_that_says_advanced():
    r = discovery.find_tutorials("I am a beginner and want to rig a leg with ik", "maya", limit=12, cache_path=None,
                                 search=lambda q, n: [{"video_id": v["id"], "title": v["title"], "channel": v["channel"]} for v in make_videos(RELEVANT)],
                                 metadata=lambda ids: [v for v in make_videos(RELEVANT) if v["id"] in ids])
    by_title = {s.title: s for s in r.suggestions}
    beginner, advanced = by_title["Beginner: rig a leg with IK in Maya"], by_title["Advanced leg rigging with pole vectors in Maya"]
    assert "its title says it is for beginners" in beginner.note.lower() and "its title says advanced, and you said you are new" in advanced.note.lower()
    assert beginner.score > advanced.score
    plain = discovery.find_tutorials("rig a leg with ik", "maya", limit=12, cache_path=None, search=lambda q, n: [{"video_id": v["id"], "title": v["title"], "channel": v["channel"]} for v in make_videos(RELEVANT)],
                                     metadata=lambda ids: [v for v in make_videos(RELEVANT) if v["id"] in ids])
    assert "its title says" not in " ".join(x.note for x in plain.suggestions).lower()                    # no level said, no level scored


# ---------------------------------------------------------------- a request to learn a whole application: an ordered path, not a one-topic search
PATH_POOL = [("Blender interface and navigation basics for beginners", "Nav School", 12 * 60), ("Blender 3D viewport navigation tutorial", "Nav School", 9 * 60),
             ("Blender modeling basics for beginners", "Model Lab", 30 * 60), ("Blender modeling a simple object tutorial", "Model Lab", 25 * 60), ("Blender hard surface modeling tutorial", "Model Lab", 35 * 60),
             ("Blender materials and shading basics for beginners", "Shade Co", 20 * 60), ("Blender shader nodes and materials explained", "Shade Co", 15 * 60),
             ("Blender lighting and rendering basics for beginners", "Light Co", 18 * 60), ("Blender render settings and lighting explained", "Light Co", 16 * 60),
             ("Blender animation basics for beginners", "Anim Co", 22 * 60), ("Blender keyframe animation tutorial", "Anim Co", 20 * 60),
             ("Blender complete beginner project start to finish", "Proj Co", 60 * 60), ("Blender make a donut, a complete beginner project", "Proj Co", 50 * 60)]
BIG_ASK = "can you give 10 tutorials for blender after which i can make whatever i want"


def test_which_requests_are_for_a_whole_application_and_which_name_a_technique():
    from app.chat_context import goal_label, is_broad_goal, path_quota
    assert is_broad_goal(BIG_ASK) and is_broad_goal("learn blender from scratch") and is_broad_goal("give me 5 beginner tutorials for maya")
    assert not is_broad_goal("give me 10 tutorials") and not is_broad_goal("10 tutorials for rigging a leg") and not is_broad_goal("find a video on skinning")
    assert path_quota(10) == [2, 2, 2, 2, 1, 1] and path_quota(3) == [1, 1, 1, 0, 0, 0] and sum(path_quota(7)) == 7
    assert goal_label("can you give 10 tutorials for rigging a leg in maya?") == "rigging a leg in maya" and goal_label("recommend a tutorial for rigging a leg with ik") == "rigging a leg with ik"


def test_ten_tutorials_after_which_i_can_make_whatever_i_want_is_an_ordered_path_of_ten_not_one_video():
    calls = []
    a = asker(PATH_POOL, calls=calls)
    out = a.ask(BIG_ASK, "blender")
    assert out.route == "discovery" and len(out.videos) == 10 and len({v.url for v in out.videos}) == 10
    stages = [v.stage for v in out.videos]
    assert stages[0] == "Interface and navigation" and stages[-1] == "A whole project" and len(set(stages)) == 6
    order = ["Interface and navigation", "Modeling", "Materials and shading", "Lighting and rendering", "Animation", "A whole project"]
    assert [order.index(s) for s in stages] == sorted(order.index(s) for s in stages), "the stages come in teaching order"
    assert "path from the basics" in out.headline and "Watch them in this order" in out.headline and "not watched" in out.headline
    assert all(f"[{v.stage}] {v.title}" in out.text for v in out.videos)
    assert all(c["app"] == "blender" and "beginner" in c["goal"] for c in calls) and len(calls) == 6 and all(c["check"] is False for c in calls), "one search per stage, no per-video clip check, none of them the user's whole sentence"
    assert not any("whatever" in c["goal"] for c in calls)


def test_a_path_stage_with_no_relevant_video_is_left_out_and_nothing_unrelated_fills_it():
    a = asker([r for r in PATH_POOL if "animation" not in r[0].lower() and "keyframe" not in r[0].lower()] + UNRELATED)
    out = a.ask(BIG_ASK, "blender")
    assert out.videos and "Animation" not in {v.stage for v in out.videos} and not any(t in out.text for t, _c, _d in UNRELATED)
    assert f"You asked for 10, but only {len(out.videos)}" in out.headline or len(out.videos) == 10


def test_more_after_a_path_continues_the_path_without_repeating_a_video():
    a = asker(PATH_POOL)
    first = a.ask("give me 6 tutorials to learn blender from scratch", "blender")
    more = a.ask("give me 5 more tutorials", "blender")
    assert len(first.videos) == 6 and more.videos and {v.url for v in first.videos}.isdisjoint({v.url for v in more.videos}) and all(v.stage for v in more.videos)


def test_a_path_video_can_be_turned_into_steps_like_any_other():
    runner = Runner()
    a = asker(PATH_POOL, runner=runner)
    out = a.ask(BIG_ASK, "blender")
    assert a.ask("turn the third one into steps", "blender").guide is not None and runner.calls[0][0] == out.videos[2].url


def test_conversational_words_do_not_decide_which_videos_are_relevant():
    out = asker().ask("can you give me 5 tutorials for rigging a leg with IK in maya after which i can make whatever i want", "maya")
    assert len(out.videos) == 5 and all("leg" in v.title.lower() for v in out.videos)
    assert "can you give" not in out.headline.lower()                                 # the reply says what the tutorials are for, not the whole sentence back


# ---------------------------------------------------------------- selecting and context across messages
def test_the_first_second_and_a_named_tutorial_can_be_picked_from_the_chat():
    a = asker()
    out = find(a, "give me 5 tutorials for rigging a leg with IK in maya")
    v = out.videos
    assert a.ask("pick the second one", "maya").text.startswith(f"Picked \"{v[1].title}\"") and a.context.focus_video is v[1]
    assert a.ask("let's go with the first", "maya").text.startswith(f"Picked \"{v[0].title}\"") and a.context.focus_video is v[0]
    named = a.ask("use the reverse foot one", "maya")
    assert named.text.startswith("Picked") and "reverse foot" in a.context.focus_video.title.lower()
    assert "only 5 tutorials" in a.ask("pick the 8th one", "maya").text


def test_which_one_is_best_for_beginners_is_answered_from_the_last_results_and_labelled_as_title_based():
    a = asker()
    out = find(a, "give me 5 tutorials for rigging a leg with IK in maya")
    ans = a.ask("which one is best for beginners?", "maya")
    assert ans.route == "context" and any(v.title in ans.text for v in out.videos) and "beginner" in ans.text.lower() and "has not watched" in ans.text
    assert "Advanced" not in ans.text.split("\"")[1]
    assert "shortest" in a.ask("which one is the shortest", "maya").text.lower()
    assert "I have not shown you any tutorials" in Asker(discover=fake_discover(RELEVANT)).ask("which one is best for beginners", "maya").text


def test_tell_me_about_the_second_one_gives_its_details_from_the_chat():
    a = asker()
    out = find(a)
    ans = a.ask("tell me more about the second one", "maya")
    assert out.videos[1].title in ans.text and out.videos[1].url in ans.text and "not watched" in ans.text and a.context.focus_video is out.videos[1]


# ---------------------------------------------------------------- turning a chat-discovered video into steps
def test_turn_the_first_one_into_steps_runs_the_pipeline_on_that_video_without_loading_anything_by_hand():
    runner = Runner()
    a = asker(runner=runner)
    out = find(a)
    res = a.ask("turn the first one into steps", "maya", on_status=lambda m: None)
    assert runner.calls == [(out.videos[0].url, "maya")]
    assert res.route == "video_steps" and res.guide is not None and len(res.guide.steps) == 6 and res.guide_video is out.videos[0]
    assert "I made 6 steps" in res.text and "Do thing number 1" in res.text and "Drafted automatically" in res.text
    assert out.videos[0].status == "done" and a.context.guide_steps is res.guide and a.context.guide_video == 0


@pytest.mark.parametrize("text", ["make steps for this tutorial", "turn this video into a guide", "can't I just turn into steps here", "turn it into steps"])
def test_the_picked_video_is_what_this_and_it_mean(text):
    runner = Runner()
    a = asker(runner=runner)
    out = find(a)
    a.ask("pick the third one", "maya")
    assert a.ask(text, "maya").guide is not None and runner.calls == [(out.videos[2].url, "maya")]


def test_this_means_the_only_video_when_only_one_was_recommended():
    runner = Runner()
    a = asker(runner=runner)
    out = find(a, "give me 1 tutorials for rigging a leg with IK in maya")
    assert len(out.videos) == 1 and a.ask("turn this video into a guide", "maya").guide is not None and runner.calls[0][0] == out.videos[0].url


def test_a_named_video_is_found_by_its_title():
    runner = Runner()
    a = asker(runner=runner)
    find(a, "give me 8 tutorials for rigging a leg with IK in maya")
    a.ask("make steps for the reverse foot one", "maya")
    assert "reverse-foot" not in runner.calls[0][0] and len(runner.calls) == 1
    assert "reverse foot" in a.context.focus_video.title.lower()


def test_the_previous_video_means_the_one_just_talked_about():
    runner = Runner()
    a = asker(runner=runner)
    out = find(a)
    a.ask("tell me about the third one", "maya")
    a.ask("turn the previous video into steps", "maya")
    assert runner.calls == [(out.videos[2].url, "maya")]


def test_asking_for_steps_when_nothing_was_discovered_says_so_and_runs_nothing():
    runner = Runner()
    a = asker(runner=runner)
    out = a.ask("turn the first one into steps", "maya")
    assert runner.calls == [] and out.guide is None and "no video to turn into steps" in out.text and "YouTube link" in out.text
    assert "no video to turn into steps" in a.ask("can't I just turn into steps here", "maya").text


def test_an_ambiguous_reference_gets_one_short_question_and_the_answer_completes_it():
    runner = Runner()
    a = asker(runner=runner)
    out = find(a)
    q = a.ask("turn this into steps", "maya")
    assert runner.calls == [] and q.route == "clarify" and "Which one" in q.text and all(v.title in q.text for v in out.videos)
    done = a.ask("2", "maya")
    assert runner.calls == [(out.videos[1].url, "maya")] and done.guide is not None


def test_a_number_that_is_not_in_the_list_is_said_plainly():
    a = asker()
    find(a)
    assert "only 5 tutorials" in a.ask("turn the 9th one into steps", "maya").text


def test_a_youtube_link_in_the_message_is_turned_into_steps_too():
    runner = Runner()
    a = asker(runner=runner)
    out = a.ask("turn https://youtu.be/abcdefghijk into steps", "maya")
    assert runner.calls == [("https://youtu.be/abcdefghijk", "maya")] and out.guide is not None
    assert a.context.videos[0].key == "abcdefghijk"


def test_a_video_already_made_in_the_chat_is_not_read_again():
    runner = Runner()
    a = asker(runner=runner)
    find(a)
    a.ask("turn the first one into steps", "maya")
    again = a.ask("turn the first one into steps", "maya")
    assert len(runner.calls) == 1 and "already made" in again.text and again.guide is None


def test_a_video_already_saved_as_a_tutorial_is_reused_instead_of_read_again():
    runner = Runner()
    a = asker(runner=runner)
    out = find(a)
    a.saved_tutorials = {out.videos[0].key: (make_steps(title="Saved earlier"), "Saved earlier", 7)}
    res = a.ask("turn the first one into steps", "maya")
    assert runner.calls == [] and res.reused_tutorial_id == 7 and res.guide is not None and "already had these steps saved" in res.text
    assert a.context.guide_tutorial_id == 7 and out.videos[0].tutorial_id == 7


# ---------------------------------------------------------------- failures and retry
def test_a_failed_pipeline_says_why_never_claims_it_worked_and_retry_runs_it_again():
    runner = Runner(PipelineResult(None, "The video is 'private': GuideWire can only read public videos."), make_ok())
    a = asker(runner=runner)
    out = find(a)
    bad = a.ask("turn the first one into steps", "maya")
    v = out.videos[0]
    assert bad.guide is None and bad.failed_video is v and v.status == "failed" and "private" in v.error and "I made" not in bad.text and "Nothing was saved" in bad.text
    ok = a.ask("try again", "maya")
    assert len(runner.calls) == 2 and runner.calls[0] == runner.calls[1] and ok.guide is not None and v.status == "done" and v.error == ""


def make_ok():
    return PipelineResult(make_steps(), "6 steps found.", [], "youtube_video")


def test_an_exception_a_missing_model_and_an_invalid_link_are_each_a_plain_message():
    a = asker(runner=Runner(ConnectionError("down"), make_ok()))
    out = find(a)
    bad = a.ask("turn the first one into steps", "maya")
    assert "could not turn" in bad.text and "ConnectionError" in bad.text and bad.guide is None and out.videos[0].status == "failed"
    none = Asker(discover=fake_discover(RELEVANT))
    find(none)
    assert "not set up" in none.ask("turn the first one into steps", "maya").text and none.context.videos[0].status == "failed"
    bad_link = Asker(video_runner=lambda url, app, status: PipelineResult(None, "That does not look like a YouTube link. Paste the full address of the video."))
    assert "does not look like a YouTube link" in bad_link.ask("turn https://youtu.be/abcdefghijk into steps", "maya").text


def test_a_video_that_takes_too_long_is_given_up_on_and_can_be_retried():
    slow = Runner(make_ok(), delay=0.5)
    a = asker(runner=slow, video_timeout_s=0.05)
    out = find(a)
    res = a.ask("turn the first one into steps", "maya")
    assert res.guide is None and "too long" in res.text and out.videos[0].status == "failed" and "try again" in res.text.lower()


def test_retry_with_nothing_to_retry_says_so():
    assert "nothing to retry" in asker().ask("try again", "maya").text


# ---------------------------------------------------------------- the generated guide, questions about it, and general questions
def made(runner=None):
    a = asker(runner=runner)
    find(a)
    a.ask("turn the first one into steps", "maya")
    return a


def test_explain_step_four_is_answered_from_the_generated_guide_only():
    a = made()
    ans = a.ask("explain step 4", "maya")
    assert ans.route == "tutorial_step" and "Step 4 of 6: Do thing number 4" in ans.text and "Click the thing 4" in ans.text and "You see thing 4" in ans.text and "4:00" in ans.text
    assert "no step 9" in a.ask("explain step 9", "maya").text


def test_a_step_with_nothing_but_its_goal_does_not_get_invented_detail():
    sl = StepList(source_type="youtube", app="maya", steps=[Step(id="s01", order=1, goal="Create a joint")])
    assert describe_step(sl, 1) == "Step 1 of 1: Create a joint\nThe guide holds nothing more about this step than that line."


def test_a_question_about_the_tutorial_with_no_tutorial_says_there_is_none_instead_of_inventing():
    a = asker()
    out = a.ask("what does the instructor do in step 3", "maya")
    assert out.route == "context" and "no tutorial in this chat" in out.text and "did not load" not in out.text
    find(a)
    again = a.ask("what is he doing at 1:30", "maya")
    assert "no tutorial has been turned into steps" in again.text and "turn the first one into steps" in again.text


def test_a_tutorial_question_after_the_guide_exists_goes_to_the_guide_not_a_refusal():
    a = made()
    out = a.ask("what is he doing at 1:00", "maya")
    assert out.route != "context" and "no tutorial" not in out.text.lower()
    assert a._svc is not None and a._key[1] == "Rig a leg with IK"


def test_a_general_question_needs_no_tutorial_and_is_not_answered_with_workflow_rules():
    a = asker()
    for q in ["what is IK", "how do I make an IK handle in Maya", "why does my IK knee bend wrong"]:
        out = a.ask(q, "maya")
        assert out.route != "context" and out.text.strip() and "did not load" not in out.text and "turn the first" not in out.text, (q, out.text)


def test_a_general_question_while_a_guide_exists_is_answered_as_general_and_labelled():
    a = made()
    out = a.ask("how do I make an IK handle in Maya", "maya")
    assert "general answer about the software, not something from the tutorial" in out.text
    assert a._key[1] is None, "the general question was answered without the tutorial loaded"


def test_context_holds_across_several_messages():
    runner = Runner()
    a = asker(runner=runner)
    out = find(a, "give me 5 tutorials for rigging a leg with IK in maya")
    best = a.ask("which one is best for beginners", "maya")
    assert best.route == "context"
    a.ask("tell me about the second one", "maya")
    a.ask("pick the third one", "maya")
    steps = a.ask("turn it into steps", "maya")
    assert runner.calls == [(out.videos[2].url, "maya")] and steps.guide is not None
    assert "Step 2 of 6" in a.ask("explain step 2", "maya").text
    assert "Step 5 of 6" in a.ask("what does step 5 do", "maya").text
    more = a.ask("give me 3 more tutorials", "maya")
    assert len(more.videos) == 3 and a.context.guide_steps is steps.guide, "a new search does not lose the guide"


# ---------------------------------------------------------------- what a chat remembers, kept and restored
def test_a_chats_memory_round_trips_through_json_and_a_run_that_was_in_progress_is_not_left_running():
    a = made()
    a.context.videos[1].status = "processing"
    d = a.context.to_dict()
    back = ChatContext.from_dict(d)
    assert [v.title for v in back.videos] == [v.title for v in a.context.videos] and back.shown == a.context.shown and back.last_goal == a.context.last_goal
    assert back.videos[0].status == "done" and back.videos[1].status == "new" and back.guide_steps is None and back.guide_video == 0
    assert ChatContext.from_dict(None).videos == [] and ChatContext.from_dict({"videos": [{"nonsense": 1}], "focus": 99}).focus is None


def test_resolving_a_reference_never_guesses_between_several_videos():
    ctx = ChatContext()
    ctx.add_videos([Video("Leg IK in Maya", "https://www.youtube.com/watch?v=aaaaaaaaaaa"), Video("Arm IK in Maya", "https://www.youtube.com/watch?v=bbbbbbbbbbb")])
    assert resolve_video("this one", ctx).ambiguous and resolve_video("turn it into steps", ctx).ambiguous
    assert resolve_video("the arm one", ctx).video.title == "Arm IK in Maya" and resolve_video("the second", ctx).video.title == "Arm IK in Maya"
    assert resolve_video("use the IK", ctx, strict=True).video is None


# ---------------------------------------------------------------- the chat screen: cards, status, saving, retry, reopening
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    from app.db import Database
    from app.ui.main_window import MainWindow
    w = MainWindow(Database(":memory:"), sync=True, discover=fake_discover(RELEVANT))
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.do_register()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()                                       # the window is gone before the next test starts (a live widget under a later test corrupts the heap)
    w.db.close()


def chat(win, runner=None):
    win.ask_screen.asker.video_runner = runner or Runner()
    win.sidebar.buttons["ask"].click()
    win.ask_screen.app.setCurrentText("maya")
    return win.ask_screen


def say(a, text):
    a.composer.setPlainText(text)
    a.submit()


def test_recommended_tutorials_are_cards_with_a_link_and_their_own_turn_into_steps_button(win):
    a = chat(win)
    say(a, "give me 5 tutorials for rigging a leg with IK in maya")
    assert len(a._video_cards) == 5
    card = next(iter(a._video_cards.values()))
    assert "<a href=" in card.title.text() and card.video.title in card.title.text() and card.video.url in card.link.text()
    assert "Creator:" in card.meta.text() and "Length:" in card.meta.text() and "Published:" in card.meta.text()
    assert not card.steps_button.isHidden() and card.retry_button.isHidden() and card.review_button.isHidden()
    from PyQt6.QtWidgets import QPushButton
    from app.ui.ask_screen import VideoCard
    say(a, "what is IK")
    buttons = [b for b in a.findChildren(QPushButton) if b.text() == "Turn into steps"]
    assert len(a._video_cards) == 5 and len(buttons) == 5 and all(isinstance(b.parent(), VideoCard) for b in buttons)      # one per recommended tutorial, none on the other messages


def test_turn_into_steps_on_a_card_saves_a_normal_tutorial_and_the_chat_goes_on_about_it(win):
    runner = Runner()
    a = chat(win, runner)
    say(a, "give me 5 tutorials for rigging a leg with IK in maya")
    key = list(a._video_cards)[1]
    card = a._video_cards[key]
    card.steps_button.click()
    assert runner.calls == [(card.video.url, "maya")]
    rows = win.db.list_tutorials(win.user.id)
    assert len(rows) == 1 and rows[0]["source_url"] == card.video.url and rows[0]["source_type"] == "youtube" and rows[0]["app"] == "maya"
    assert len(win.db.get_steps(rows[0]["id"])) == 6                                                            # the same tutorials and steps Home lists
    assert card.video.status == "done" and not card.review_button.isHidden() and not card.session_button.isHidden() and card.steps_button.isHidden()
    assert a.tutorial.currentData() == rows[0]["id"] and a.asker.context.guide_tutorial_id == rows[0]["id"]
    assert a.conversation_id is not None and win.db.get_conversation(win.user.id, a.conversation_id)["tutorial_id"] == rows[0]["id"]
    assert "I made 6 steps" in a.transcript_text()
    say(a, "explain step 3")
    assert "Step 3 of 6: Do thing number 3" in a.transcript_text()
    say(a, "what is IK")                                                                                       # and the conversation continues
    assert a.asker.context.guide_steps is not None and a.conversation_id is not None
    guide_cards = [c for c, _m, _q in a._cards if c.tutorial_id == rows[0]["id"]]
    assert guide_cards and not guide_cards[0].map_buttons and not guide_cards[0].review_button.isHidden()


def test_the_guide_can_be_reviewed_or_started_from_the_chat_without_losing_it(win):
    a = chat(win)
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    card = a._video_cards[list(a._video_cards)[0]]
    card.steps_button.click()
    tid = card.tutorial_id
    opened = []
    a.review_tutorial.connect(opened.append)
    a.start_session.connect(opened.append)
    card.review_button.click()
    card.session_button.click()
    assert opened == [tid, tid]
    assert a.chat_list.count() == 1 and a.conversation_id is not None                                          # the chat is still there to come back to


def test_a_failed_card_shows_why_and_retry_succeeds(win):
    runner = Runner(PipelineResult(None, "The video is 'private': GuideWire can only read public videos."), make_ok())
    a = chat(win, runner)
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    card = a._video_cards[list(a._video_cards)[0]]
    card.steps_button.click()
    assert card.video.status == "failed" and not card.retry_button.isHidden() and card.steps_button.isHidden() and "private" in card.status.text()
    assert win.db.list_tutorials(win.user.id) == [] and "I made" not in a.transcript_text()                   # nothing claimed, nothing saved
    card.retry_button.click()
    assert len(runner.calls) == 2 and card.video.status == "done" and len(win.db.list_tutorials(win.user.id)) == 1 and card.retry_button.isHidden()


def test_a_second_turn_of_the_same_video_does_not_save_a_second_tutorial(win):
    a = chat(win)
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    say(a, "turn the first one into steps")
    say(a, "turn the first one into steps")
    assert len(win.db.list_tutorials(win.user.id)) == 1


def test_a_video_saved_in_an_earlier_chat_is_reused_not_read_again(win):
    runner = Runner()
    a = chat(win, runner)
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    say(a, "turn the first one into steps")
    a.new_chat()
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    say(a, "turn the first one into steps")
    assert len(runner.calls) == 1 and "already had these steps saved" in a.transcript_text() and len(win.db.list_tutorials(win.user.id)) == 1


def test_reopening_a_chat_brings_back_its_cards_and_what_it_remembered(win):
    a = chat(win)
    say(a, "give me 4 tutorials for rigging a leg with IK in maya")
    say(a, "turn the second one into steps")
    cid = a.conversation_id
    tid = a.asker.context.guide_tutorial_id
    a.new_chat()
    assert a.asker.context.videos == [] and not a._video_cards
    a.open_chat(cid)
    assert len(a._video_cards) == 4 and a.asker.context.guide_tutorial_id == tid and a.asker.context.guide_steps is not None
    done = [c for c in a._video_cards.values() if c.video.status == "done"]
    assert len(done) == 1 and not done[0].review_button.isHidden()
    say(a, "explain step 2")
    assert "Step 2 of 6: Do thing number 2" in a.transcript_text()
    say(a, "turn the third one into steps")                                                                   # the list survived too: "the third one" is still the third
    assert win.db.list_tutorials(win.user.id)[0]["source_url"] == list(a._video_cards.values())[2].video.url


def test_pick_on_a_card_marks_it_and_the_next_request_means_it(win):
    runner = Runner()
    a = chat(win, runner)
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    cards = list(a._video_cards.values())
    cards[2].pick_button.click()
    assert cards[2].property("selected") is True and cards[2].pick_button.isHidden() and not cards[0].pick_button.isHidden()
    say(a, "make steps for this tutorial")
    assert runner.calls == [(cards[2].video.url, "maya")]


def test_the_application_named_in_the_message_wins_over_the_toggle(win):
    calls = []
    win.ask_screen.asker.discover = fake_discover(RELEVANT, calls)
    a = chat(win)
    a.app.setCurrentText("blender")
    say(a, "give me 3 tutorials for rigging a leg with IK in maya")
    assert calls[0]["app"] == "maya" and len(a._video_cards) == 3


def test_asking_for_steps_in_an_empty_chat_is_answered_in_the_chat(win):
    a = chat(win)
    say(a, "can't I just turn into steps here")
    assert "no video to turn into steps" in a.transcript_text() and not a._video_cards and win.db.list_tutorials(win.user.id) == []
