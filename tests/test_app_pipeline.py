import json
from pathlib import Path


from app.pipeline import YOUTUBE_MESSAGE, request_steps

SRT = "1\n00:00:01,000 --> 00:00:04,000\nPress Tab to enter Edit Mode\n\n2\n00:00:05,000 --> 00:00:08,000\nNow press G to move it\n"


def test_written_blender_steps_become_a_step_list_offline():
    r = request_steps("Press Tab to enter Edit Mode\nSelect the cube\nMove it with G")
    assert r.steps is not None and len(r.steps.steps) >= 2 and r.steps.app == "blender"
    assert r.api_calls == 0 and r.network_calls == 0


def test_maya_steps_use_the_rigging_route():
    r = request_steps("Create joints down the arm\nCreate an IK handle on the leg", "maya")
    assert r.steps is not None and r.steps.app == "maya" and r.route == "rigging_text" and r.api_calls == 0


def test_a_question_gives_a_message_and_no_steps():
    r = request_steps("what is a vertex group?")
    assert r.steps is None and r.message


def test_empty_text_is_refused():
    assert request_steps("   ").steps is None and "Paste" in request_steps("").message


def test_unknown_app_is_refused():
    r = request_steps("Press Tab", "unity")
    assert r.steps is None and "Unknown application" in r.message


def test_youtube_link_is_not_sent_anywhere():
    r = request_steps("https://www.youtube.com/watch?v=abc123 please", "blender")
    assert r.steps is None and r.message == YOUTUBE_MESSAGE and r.network_calls == 0
    assert request_steps("see https://youtu.be/abc123", "maya").message == YOUTUBE_MESSAGE


def test_timed_transcript_is_parsed():
    r = request_steps(SRT)
    assert r.steps is not None and r.steps.steps and r.api_calls == 0


def test_hand_made_json_step_list_is_accepted():
    d = json.loads(Path("shared/examples/blender_cube_extrude.json").read_text(encoding="utf-8"))
    r = request_steps(json.dumps(d))
    assert r.steps is not None and len(r.steps.steps) == 4


def test_bad_json_is_a_message_not_a_crash():
    r = request_steps('{"steps": [oops')
    assert r.steps is None and r.message
