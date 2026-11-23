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
    assert out.route == "discovery" and f"Here are {len(r.suggestions)} tutorials" in out.text and out.steps is None and r.suggestions[0].url in out.text
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
    assert 1 <= s.results.count() <= 3 and s.open_button.isEnabled() and "videos for you" in s.message.text()
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


def test_each_suggestion_shows_its_video_thumbnail_and_the_chosen_one_a_larger_picture(window):
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QColor, QImage
    img = QImage(320, 180, QImage.Format.Format_RGB32)
    img.fill(QColor("#3a6ea5"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    png = bytes(ba)
    w = window
    asked = []
    w.find_screen.thumbnail_fetcher = lambda ids: asked.append(list(ids)) or {ids[0]: png, ids[1]: b"not an image"}          # one real picture, one broken, the rest missing
    w.home.find_button.click()
    w.find_screen.app.setCurrentText("maya")
    w.find_screen.goal.setText("rig a leg with ik")
    w.find_screen.search()
    s = w.find_screen
    assert asked and len(asked[0]) == s.results.count()                                    # one request for all of them
    assert s.results.card(0).has_picture                                                  # the first has its picture
    assert not s.results.card(1).has_picture                                              # a broken one is just left out
    assert s.thumb.isVisible() is False or s.thumb.pixmap() is not None
    s.results.setCurrentRow(0)
    assert not s.thumb.isHidden() and s.thumb.pixmap().width() == 320                     # the chosen video's picture is shown larger
    s.results.setCurrentRow(1)
    assert s.thumb.isHidden()                                                             # no picture for it: nothing is shown


def test_the_thumbnail_fetch_refuses_anything_that_is_not_a_video_id(monkeypatch):
    from app import thumbnails
    called = []
    monkeypatch.setattr(thumbnails.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    assert thumbnails.fetch("../etc/passwd") is None and thumbnails.fetch("") is None and not called


# ---- Find a tutorial: persistent, with a history
def _search(w, goal="rig a leg with ik", app="maya"):
    w.open_find()
    w.find_screen.app.setCurrentText(app)
    w.find_screen.goal.setText(goal)
    w.find_screen.search()


def test_a_result_survives_leaving_the_screen_and_coming_back(window):
    w = window
    _search(w)
    s = w.find_screen
    n = s.results.count()
    assert n >= 1
    w.show_home()
    w.open_find()
    assert s.results.count() == n and s.goal.text() == "rig a leg with ik" and s.app.currentText() == "maya" and s.selected() is not None


def test_every_search_is_saved_and_shown_in_the_history_newest_first(window):
    w = window
    _search(w, "rig a leg with ik")
    _search(w, "make the legs move properly in maya", "maya")
    s = w.find_screen
    assert s.history.count() == 2 and "make the legs move" in s.history.item(0).text() and "rig a leg" in s.history.item(1).text()
    assert not s.history.isHidden() and s.history_empty.isHidden()
    _search(w, "RIG A LEG WITH IK")                                              # the same question again replaces the old entry and moves it up
    assert s.history.count() == 2 and "RIG A LEG" in s.history.item(0).text()


def test_a_history_entry_opens_again_without_a_new_search(window):
    w = window
    _search(w, "rig a leg with ik")
    first = [c.title.text() for c in w.find_screen.results.cards]
    _search(w, "make the legs move properly in maya")
    searched = []
    w.find_screen.finder = lambda goal, app: searched.append(goal)
    s = w.find_screen
    s.history.setCurrentRow(1)                                                   # the older one
    assert s.goal.text() == "rig a leg with ik" and [c.title.text() for c in s.results.cards] == first and not searched
    assert "Saved search" in s.message.text() and s.open_button.isEnabled()


def test_the_history_is_kept_after_a_restart_and_is_only_the_learners_own(window, tmp_path):
    """`window` only supplies the running application; the two windows below are the same program started twice on one database file."""
    from PyQt6.QtWidgets import QApplication

    from app.db import Database
    from app.ui.main_window import MainWindow
    path = tmp_path / "g.sqlite"
    finder = lambda goal, app: discovery.find_tutorials(goal, app, search=fake_search, metadata=fake_meta, cache_path=None)    # noqa: E731

    def start() -> tuple:
        db = Database(path)
        return db, MainWindow(db, sync=True, discover=finder)

    def stop(db, w) -> None:
        w.close()
        w.deleteLater()
        QApplication.processEvents()
        db.close()

    db, w = start()
    w.login.name.setText("T"); w.login.email.setText("t@example.com"); w.login.password.setText("a-long-password-1"); w.login.do_register()    # noqa: E702
    _search(w)
    stop(db, w)
    db2, w2 = start()
    w2.login.email.setText("t@example.com"); w2.login.password.setText("a-long-password-1"); w2.login.do_login()                         # noqa: E702
    w2.open_find()
    s = w2.find_screen
    assert s.history.count() == 1 and s.goal.text() == "rig a leg with ik" and s.results.count() >= 1      # the last search is back
    w2.on_logout()
    assert s.results.count() == 0 and s.goal.text() == ""                                                 # nothing of it is left for the next person
    w2.login.name.setText("Other"); w2.login.email.setText("o@example.com"); w2.login.password.setText("another-long-pass-2"); w2.login.do_register()    # noqa: E702
    w2.open_find()
    assert s.history.count() == 0 and s.goal.text() == "" and s.results.count() == 0
    stop(db2, w2)


def test_a_history_entry_can_be_removed_and_the_whole_history_cleared(window):
    w = window
    _search(w, "rig a leg with ik")
    _search(w, "make the legs move properly in maya")
    s = w.find_screen
    assert s.history.currentRow() == 0 and s.forget_button.isEnabled()
    s.forget_button.click()
    assert s.history.count() == 1 and "rig a leg" in s.history.item(0).text()
    s.clear_button.click()
    assert s.history.count() == 0 and not s.history_empty.isHidden() and not s.clear_button.isEnabled()


def test_a_failed_search_or_one_with_no_suggestions_is_not_added_to_the_history(window):
    w = window
    w.open_find()
    w.find_screen.goal.setText("rig something")                                  # too vague: a question comes back, nothing is found
    w.find_screen.search()
    assert w.find_screen.history.count() == 0


def test_every_suggestion_is_a_card_showing_all_its_text_in_a_list_that_scrolls(window):
    w = window
    _search(w)
    s = w.find_screen
    card = s.results.card(0)
    assert card.title.wordWrap() and card.meta.wordWrap() and card.title.text() and card.meta.text() and card.note.text()
    assert s.results.verticalScrollBarPolicy() != s.results.horizontalScrollBarPolicy()
    s.results.setCurrentRow(1) if s.results.count() > 1 else None
    assert s.results.card(s.results.currentRow()).property("selected") is True
    assert s.scroll.widgetResizable()                                              # the whole page scrolls too


def test_a_saved_search_round_trips_and_an_older_one_without_new_fields_still_opens():
    r = discovery.find_tutorials("rig a leg with ik", "maya", search=fake_search, metadata=fake_meta, cache_path=None)
    back = discovery.DiscoveryResult.from_json(r.to_json())
    assert back == r
    import json
    old = json.dumps({"suggestions": [{"title": "T", "url": "https://www.youtube.com/watch?v=abc", "extra_new_field": 1}]})
    assert discovery.DiscoveryResult.from_json(old).suggestions[0].title == "T"


# ---- plain-language wording of a suggestion
LONG_NOTE = ("Uploaded 2026-08, 0 year(s) ago (the upload date is not the date it was recorded, and the version it shows is only known if the title or description says). "
             "Judged from metadata only: what it actually shows is unknown until its steps are extracted. Checked the first 2 min of the video: "
             "This clip introduces the Blender user interface and its basic components for absolute beginners. It matches what you asked for.")


def test_a_suggestion_is_described_by_what_the_video_seems_to_cover_not_by_the_finders_bookkeeping():
    said = discovery.friendly_note(LONG_NOTE)
    assert said == "This clip introduces the Blender user interface and its basic components for absolute beginners. It matches what you asked for."
    for noise in ("Uploaded", "year(s) ago", "metadata", "Checked the first"):
        assert noise not in said


def test_without_a_look_at_the_video_the_matched_topics_of_its_title_are_said_and_a_wrong_application_is_plain():
    titled = "Uploaded 2025-03, 2 year(s) ago (x). Title/chapters touch 1 of 1 areas you need (forward and inverse kinematics). Judged from metadata only: y."
    assert discovery.friendly_note(titled) == "From its title, it looks like it covers forward and inverse kinematics."
    assert discovery.friendly_note("Title/chapters touch 0 of 1 areas you need (none). Judged from metadata only: y.") == "Picked from its title and length."
    assert discovery.friendly_note("Checked the first 2 min of the video: it shows Blender, not Maya.") == "This video seems to be about Blender, not Maya."
    assert discovery.friendly_note("") == "Picked from its title and length."


def test_only_the_notes_a_learner_needs_are_kept():
    notes = ["The request does not say which part of rigging or animation to learn.", "This matches what maya learners ask about 'ik'.", "I read this as: ik (maya). If you meant something else, say so.",
             "The live YouTube search is not available right now (RuntimeError); these come from GuideWire's small local list instead.", discovery.CAVEAT]
    assert discovery.friendly_notes(notes) == [notes[3], discovery.CAVEAT]


def test_the_find_screen_shows_the_plain_description_on_the_card_and_in_the_details(window):
    w = window
    _search(w)
    s = w.find_screen
    for c in s.results.cards:
        assert "Uploaded" not in c.note.text() and "metadata" not in c.note.text() and "year(s) ago" not in c.note.text()
    text = s.details.toPlainText()
    assert "year(s) ago" not in text and "I read this as" not in text and "This matches what" not in text and "check it fits" in text


# ---- an empty result says WHY (the user saw "nothing matches that well" on both Find and Ask)
def test_when_the_youtube_search_cannot_run_the_empty_result_says_so_and_does_not_blame_the_words(monkeypatch):
    def quota(q, n):
        raise RuntimeError("quotaExceeded: the request cannot be completed")

    def offline(q, n):
        raise OSError("network is unreachable")
    r = discovery.find_tutorials("rig a leg with ik", "blender", search=quota, metadata=fake_meta, cache_path=None)
    assert not r.suggestions and "daily search limit" in r.message and "matches that well" not in r.message
    r = discovery.find_tutorials("rig a leg with ik", "blender", search=offline, metadata=fake_meta, cache_path=None)
    assert not r.suggestions and "could not reach the YouTube search" in r.message and "OSError" in r.message and "internet connection" in r.message
    monkeypatch.setattr(discovery, "live_functions", lambda: None)
    r = discovery.find_tutorials("rig a leg with ik", "blender", cache_path=None)
    assert not r.suggestions and "No YouTube search key" in r.message and "YOUTUBE_API_KEY" in r.message


def test_nothing_matches_is_only_said_when_a_working_search_found_nothing_and_every_cause_has_its_own_words():
    r = discovery.find_tutorials("rig a leg with ik", "maya", search=lambda q, n: [], metadata=lambda ids: [], cache_path=None)
    assert r.source == "live" and not r.suggestions and r.message.startswith("I found no tutorial that matches that well")
    assert discovery.nothing_found_message().startswith("I found no tutorial that matches that well")
    assert "different application" in discovery.nothing_found_message(dropped=2) and "Try naming the application" in discovery.nothing_found_message(dropped=2)
    assert "daily search limit" in discovery.nothing_found_message(RuntimeError("HttpError 403 quotaExceeded"))


def test_ask_gives_the_same_reason_as_the_find_screen():
    def quota(q, n):
        raise RuntimeError("quotaExceeded")
    asker = Asker(discover=lambda goal, app: discovery.find_tutorials(goal, app, search=quota, metadata=fake_meta, cache_path=None))
    out = asker.ask("recommend a tutorial for rigging a leg with ik", "blender")
    assert out.route == "discovery" and "daily search limit" in out.text and "matches that well" not in out.text


def test_the_find_screen_shows_the_reason_when_nothing_is_found(window):
    w = window

    def quota(q, n):
        raise RuntimeError("quotaExceeded")
    w.find_screen.finder = lambda goal, app: discovery.find_tutorials(goal, app, search=quota, metadata=fake_meta, cache_path=None)
    _search(w, "rig a leg with ik", "blender")
    assert w.find_screen.results.count() == 0 and "daily search limit" in w.find_screen.message.text()
    assert w.find_screen.history.count() == 0                                        # nothing was found, so nothing is kept
