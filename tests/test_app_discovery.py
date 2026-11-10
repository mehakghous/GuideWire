"""Tutorial discovery in the app: the wrapper (fake YouTube, no network), the Find screen, and tutorial requests typed into Ask."""
import os

import pytest

from app import discovery
from app.ask import Asker, asks_for_a_tutorial

VIDEOS = [
    {"id": f"vid{i:08d}", "url": f"https://www.youtube.com/watch?v=vid{i:08d}", "title": t, "channel": ch, "duration_s": d, "published": "2025-03-01", "chapters": 0, "chapter_titles": [],
     "description_head": "", "licence": "youtube", "captions_flag": None, "embeddable": True, "privacy": "public"}
    for i, (t, ch, d) in enumerate([
        ("Rigging a Leg in Maya with IK handles", "Rig School", 12 * 60),
        ("Maya leg rig tutorial for beginners", "Anim Lab", 18 * 60),
        ("Auto rig your character in Maya", "Quick Tools", 9 * 60),
    ])
]


def fake_search(query, n):
    return [{"video_id": v["id"], "title": v["title"], "channel": v["channel"]} for v in VIDEOS]


def fake_meta(ids):
    return [v for v in VIDEOS if v["id"] in ids]


def test_a_rigging_goal_gives_ranked_suggestions_and_is_remembered_for_a_day(tmp_path):
    calls = []

    def search(q, n):
        calls.append(q)
        return fake_search(q, n)
    cache = tmp_path / "c.json"
    r = discovery.find_tutorials("I am a beginner and want to rig a leg with ik", "maya", search=search, metadata=fake_meta, cache_path=cache, now=lambda: 1000.0)
    assert r.source == "live" and 1 <= len(r.suggestions) <= 3 and all(s.url.startswith("https://www.youtube.com/watch?v=") for s in r.suggestions)
    assert discovery.CAVEAT in r.notes and calls
    n = len(calls)
    again = discovery.find_tutorials("I am a beginner and want to rig a leg with ik", "maya", search=search, metadata=fake_meta, cache_path=cache, now=lambda: 2000.0)
    assert again.source == "saved" and len(calls) == n and [s.url for s in again.suggestions] == [s.url for s in r.suggestions]
    later = discovery.find_tutorials("I am a beginner and want to rig a leg with ik", "maya", search=search, metadata=fake_meta, cache_path=cache, now=lambda: 1000.0 + discovery.CACHE_TTL_S + 5)
    assert later.source == "live" and len(calls) > n


def test_a_vague_request_asks_a_question_instead_of_searching(tmp_path):
    def boom(*_a):
        raise AssertionError("must not search")
    r = discovery.find_tutorials("rig something", None, search=boom, metadata=boom, cache_path=None)
    assert not r.suggestions and "Blender, Maya or Houdini" in r.message
    assert "Describe" in discovery.find_tutorials("  ", None, cache_path=None).message


def test_a_failed_live_search_falls_back_to_the_local_list_and_says_so():
    def down(q, n):
        raise RuntimeError("quota")
    r = discovery.find_tutorials("rig a leg with ik", "maya", search=down, metadata=fake_meta, cache_path=None)
    assert r.source == "local" and any("not available" in n for n in r.notes)


def test_no_youtube_key_says_so(monkeypatch):
    monkeypatch.setattr(discovery, "live_functions", lambda: None)
    r = discovery.find_tutorials("rig a leg with ik", "maya", cache_path=None)
    assert r.source == "local" and any("YOUTUBE_API_KEY" in n for n in r.notes)


def test_which_messages_are_requests_for_a_tutorial():
    assert asks_for_a_tutorial("recommend a tutorial for rigging a leg in maya")
    assert asks_for_a_tutorial("find me a video on skinning")
    assert not asks_for_a_tutorial("give me the steps to bind the mesh")
    assert not asks_for_a_tutorial("what is he doing in the video at 1:30")
    assert not asks_for_a_tutorial("where do i start rigging in maya")


def test_ask_sends_a_tutorial_request_to_discovery_only_when_it_is_connected_and_no_tutorial_is_chosen():
    r = discovery.find_tutorials("rig a leg with ik", "maya", search=fake_search, metadata=fake_meta, cache_path=None)
    asker = Asker(discover=lambda goal, app: r)
    out = asker.ask("recommend a tutorial for rigging a leg with ik", "maya")
    assert out.route == "discovery" and "Here are some tutorials" in out.text and out.steps is None and r.suggestions[0].url in out.text
    assert Asker().ask("recommend a tutorial for rigging a leg", "maya").route != "discovery"
    broken = Asker(discover=lambda g, a: (_ for _ in ()).throw(RuntimeError("x")))
    assert "could not search" in broken.ask("recommend a video on ik", "maya").text


@pytest.fixture
def window():
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.db import Database
    from app.ui.main_window import MainWindow
    qapp = QApplication.instance() or QApplication([])
    db = Database(":memory:")
    w = MainWindow(db, sync=True, discover=lambda goal, app: discovery.find_tutorials(goal, app, search=fake_search, metadata=fake_meta, cache_path=None))
    w.login.name.setText("T")
    w.login.email.setText("t@example.com")
    w.login.password.setText("a-long-password-1")
    w.login.do_register()
    yield w
    w.close()
    db.close()
    del qapp


def test_find_screen_search_open_and_turn_into_steps(window):
    w = window
    opened = []
    w.find_screen.open_url = opened.append
    w.home.find_button.click()
    assert w.current_screen() is w.find_screen and not w.find_screen.open_button.isEnabled()
    w.find_screen.app.setCurrentText("maya")
    w.find_screen.goal.setText("rig a leg with ik")
    w.find_screen.search()
    s = w.find_screen
    assert 1 <= s.results.count() <= 3 and s.open_button.isEnabled() and "Live YouTube results" in s.message.text()
    assert "has not watched it" in s.details.toPlainText()
    s.open_button.click()
    assert opened and opened[0].startswith("https://www.youtube.com/watch?v=")
    s.steps_button.click()
    assert w.current_screen() is w.new_tutorial and w.new_tutorial.text.toPlainText() == opened[0] and w.new_tutorial.app.currentText() == "maya"


def test_find_screen_shows_the_question_for_a_vague_request_and_is_off_without_a_finder(window):
    w = window
    w.open_find()
    w.find_screen.goal.setText("rig something")
    w.find_screen.search()
    assert w.find_screen.results.count() == 0 and "Blender, Maya or Houdini" in w.find_screen.message.text()
    w.find_screen.finder = None
    w.find_screen.reset()
    assert "not available" in w.find_screen.message.text()
