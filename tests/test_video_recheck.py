"""The second look at the video (ingestion/video_recheck.py): when the steps cannot answer a question about the tutorial, the video model is asked about a short clip. Scripted provider, no network."""
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from ingestion.answer_model import ModelAnswerer
from ingestion.providers.base import QuotaError
from ingestion.providers.fake import ScriptedProvider
from ingestion.session import Session
from ingestion.video_recheck import apply_recheck, pick_window, video_url_of, Window
from shared.step_record import HowTo, Step, StepList


def tutorial_session(url="https://www.youtube.com/watch?v=AAAAAAAAAAA", current="s01"):
    steps = [Step(id=f"s{i:02d}", order=i, goal=g, video_start_s=t, video_end_s=t + 20, how_to=[HowTo(text=f"do {g}", support="shown", evidence="x")])
             for i, (g, t) in enumerate([("Create the hip joint", 10), ("Add a pole vector constraint to the knee", 130), ("Bind the skin", 300)], start=1)]
    sess = Session(app="maya")
    sess.load(StepList(source_type="youtube", app="maya", title="Leg rig", steps=steps, video_duration_s=400.0), tutorial={"id": "x", "title": "Leg rig", "source_type": "youtube", **({"url": url} if url else {})})
    if current:
        sess.goto(current)
    else:
        sess.current = None
    return sess


def first(**kw):
    base = {"answer": "That is not in the tutorial.", "grounding": "tutorial", "source_ids": [], "step_ids": [], "confidence": "medium", "in_tutorial": "no", "clarifying_question": None, "wants_steps": False}
    return {**base, **kw}


def test_the_moment_is_the_time_in_the_question_then_the_named_step_then_the_best_matching_step_then_the_current_step():
    s = tutorial_session()
    assert pick_window("what is he typing at 2:10", s) == Window(85, 205, "the time in the question")
    assert pick_window("why that value", s, ["s03"]) == Window(255, 375, "step s03")
    assert pick_window("what angle does the pole vector get", s).why == "step s02"
    assert pick_window("why does he pause", s, []).why == "the step the learner is on"
    assert pick_window("why", tutorial_session(current=None)) is None                                    # nothing says where: no recheck


def test_the_window_stays_inside_the_video():
    assert pick_window("what happens at 6:30", tutorial_session()) == Window(345, 400, "the time in the question")


def test_the_video_url_comes_from_the_tutorial_record():
    assert video_url_of(tutorial_session()) == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert video_url_of(tutorial_session(url=None)) is None


def test_a_found_answer_replaces_the_not_in_the_tutorial_reply_and_carries_its_time():
    p = ScriptedProvider([first(), {"found": True, "answer": "He types 0.5 in the Twist field."}])
    b = ModelAnswerer(p, recheck=True)("what value does he type for twist at 2:10", tutorial_session())
    assert b.explanations[0].text == "He types 0.5 in the Twist field. (the video shows this somewhere in 1:25 to 3:25)" and b.api_calls == 2
    assert p.calls[1]["video_url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA#t=85,205" and "twist" in p.calls[1]["prompt"] and "SHOWN" in p.calls[1]["system"]
    assert p.calls[0]["video_url"] is None and any("Checked the video around 1:25 to 3:25" in c for c in b.caveats)


def test_not_found_keeps_the_first_answer_and_says_the_clip_was_checked():
    p = ScriptedProvider([first(), {"found": False, "answer": ""}])
    b = ModelAnswerer(p, recheck=True)("what render settings at 2:10", tutorial_session())
    assert b.explanations[0].text == "That is not in the tutorial. I also checked the video around 1:25 to 3:25 and it is not shown there." and b.api_calls == 2


def test_a_found_answer_with_no_text_counts_as_not_found():
    text, note = apply_recheck("first", Window(0, 60, "x"), {"found": True, "answer": "  "})
    assert "not shown there" in text and "not shown" in note


@pytest.mark.parametrize("err", [QuotaError("429"), RuntimeError("down")])
def test_a_provider_failure_keeps_the_first_answer_untouched(err):
    p = ScriptedProvider([first(), err])
    b = ModelAnswerer(p, recheck=True)("what value at 2:10", tutorial_session())
    assert b.explanations[0].text == "That is not in the tutorial." and b.api_calls == 1


def test_it_runs_only_when_asked_for_and_only_for_questions_the_steps_could_not_answer():
    off = ScriptedProvider([first()])
    ModelAnswerer(off)("what value at 2:10", tutorial_session())
    assert len(off.calls) == 1                                                                              # not enabled
    yes = ScriptedProvider([first(in_tutorial="yes", answer="Step 2 creates the pole vector.")])
    ModelAnswerer(yes, recheck=True)("what is step 2", tutorial_session())
    assert len(yes.calls) == 1                                                                              # the steps answered it
    none = ScriptedProvider([first(in_tutorial="not_applicable", answer="An IK handle bends a limb.")])
    ModelAnswerer(none, recheck=True)("what is an ik handle", tutorial_session())
    assert len(none.calls) == 1                                                                             # not about the tutorial
    novideo = ScriptedProvider([first()])
    b = ModelAnswerer(novideo, recheck=True)("what value at 2:10", tutorial_session(url=None))
    assert len(novideo.calls) == 1 and b.api_calls == 1                                                     # no video to look at


def test_the_gateway_sends_the_clip_question_only_when_the_client_gives_the_video_url():
    prov = ScriptedProvider([first(), {"found": True, "answer": "He types 0.5."}])
    c = TestClient(create_app(provider_factory=lambda: prov, tokens={"t1": "u1"}))
    tut = {"title": "Leg rig", "current": "s01", "video_url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
           "steps": [{"id": "s01", "goal": "Create the hip joint", "start_s": 10, "how_to": []}, {"id": "s02", "goal": "Add the pole vector", "start_s": 130, "how_to": []}]}
    r = c.post("/v1/answer", json={"question": "what value does he type for the twist", "app": "maya", "model": True, "tutorial": tut}, headers={"Authorization": "Bearer t1"})
    assert r.status_code == 200 and "0.5" in r.json()["explanations"][0]["text"] and r.json()["api_calls"] == 2
    assert prov.calls[1]["video_url"].endswith("#t=0,85")                                                    # nothing in the question names a moment: the step the learner is on
    prov2 = ScriptedProvider([first()])
    c2 = TestClient(create_app(provider_factory=lambda: prov2, tokens={"t1": "u1"}))
    tut.pop("video_url")
    r2 = c2.post("/v1/answer", json={"question": "what value does he type for the twist", "app": "maya", "model": True, "tutorial": tut}, headers={"Authorization": "Bearer t1"})
    assert r2.status_code == 200 and r2.json()["api_calls"] == 1 and len(prov2.calls) == 1


def test_the_sweep_tries_other_parts_of_the_video_nearest_first_and_never_repeats_a_clip():
    from ingestion.video_recheck import windows_to_try
    s = tutorial_session()                                                              # a 400 s video; "why that value" is anchored on the step the learner is on (s01 at 10 s)
    one = windows_to_try("why that value", s, [])
    assert one == [Window(0, 85, "the step the learner is on")]
    wins = windows_to_try("why that value", s, [], extra=2)
    assert wins[0] == one[0] and len(wins) == 3 and all(w.why == "a sweep of the video" for w in wins[1:])
    assert wins[1].start_s < wins[2].start_s and wins[1].start_s >= 85 - 60                 # the nearest part comes first
    spans = [(w.start_s, w.end_s) for w in wins]
    assert all(min(a[1], b[1]) - max(a[0], b[0]) < 60 for i, a in enumerate(spans) for b in spans[i + 1:])


def test_a_sweep_stops_at_the_first_clip_that_shows_it_and_a_miss_everywhere_says_how_many_parts_were_checked():
    from ingestion.video_recheck import apply_recheck, recheck
    p = ScriptedProvider([{"found": False, "answer": ""}, {"found": True, "answer": "He types 0.5."}])
    win, res = recheck(p, "why that value", tutorial_session(), [], extra_windows=3)
    assert res["found"] and len(p.calls) == 2 and len(res["tried"]) == 2 and win.start_s == res["tried"][1][0]                  # stopped at the second clip
    p2 = ScriptedProvider([{"found": False, "answer": ""}] * 3)
    win2, res2 = recheck(p2, "why that value", tutorial_session(), [], extra_windows=2)
    text, note = apply_recheck("That is not in the tutorial.", win2, res2)
    assert len(p2.calls) == 3 and "I also checked 3 parts of the video" in text and "not shown in any of them" in text and "3 parts" in note


def test_a_failure_part_way_through_a_sweep_keeps_what_was_asked():
    from ingestion.video_recheck import recheck
    p = ScriptedProvider([{"found": False, "answer": ""}, QuotaError("429")])
    win, res = recheck(p, "why that value", tutorial_session(), [], extra_windows=3)
    assert not res["found"] and len(res["tried"]) == 1
    assert recheck(ScriptedProvider([QuotaError("429")]), "why", tutorial_session(), [], extra_windows=2) is None
