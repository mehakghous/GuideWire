"""The session screen's layout: the tutorial video and its controls on the left, the steps with their status in words and a question box on the right, under them what GuideWire does on screen."""
import os

import pytest

pytest.importorskip("PyQt6")                    # the lean CI install has no Qt

from app.ui.player import page_html, video_id_of  # noqa: E402


@pytest.fixture
def win():
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.db import Database
    from app.ui.main_window import MainWindow
    qapp = QApplication.instance() or QApplication([])
    db = Database(":memory:")
    w = MainWindow(db, sync=True)
    w.login.name.setText("T")
    w.login.email.setText("t@example.com")
    w.login.password.setText("a-long-password-1")
    w.login.do_register()
    w.add_demo_tutorials()
    yield w
    w.close()
    db.close()
    del qapp


def _video_tutorial(w):
    rows = w.db.list_tutorials(w.user.id)
    tid = next(r["id"] for r in rows if w.db.tutorial_source(r["id"]))
    w.open_session(tid)
    return w.session, tid


def test_the_video_id_is_read_from_every_youtube_link_form():
    assert video_id_of("https://www.youtube.com/watch?v=TmhC35PqZvQ") == "TmhC35PqZvQ"
    assert video_id_of("https://youtu.be/TmhC35PqZvQ?t=10") == "TmhC35PqZvQ"
    assert video_id_of("https://www.youtube.com/watch?list=x&v=TmhC35PqZvQ") == "TmhC35PqZvQ"
    assert video_id_of("https://example.com/watch?v=TmhC35PqZvQ") is None and video_id_of(None) is None and video_id_of("") is None


def test_the_player_page_holds_the_official_player_and_the_two_calls_the_window_makes():
    html = page_html("TmhC35PqZvQ", 12.5)
    assert "iframe_api" in html and "TmhC35PqZvQ" in html and "gwSeek" in html and "gwToggle" in html and "12.5" in html


def test_the_steps_list_says_each_status_in_a_word_and_marks_the_current_step(win):
    s, _tid = _video_tutorial(win)
    s.start_button.click()
    s.done_button.click()
    s.done_button.click()
    texts = [s.steps_list.item(i).text() for i in range(s.steps_list.count())]
    assert texts[0].startswith("✓ done") and texts[1].startswith("✓ done") and texts[2].startswith("► current")
    assert all("pending" in x or "craft" in x for x in texts[3:])
    assert s.steps_count.text() == f"3 of {len(texts)}" and s.steps_list.currentRow() == 2
    s.skip_button.click()
    assert s.steps_list.item(2).text().startswith("– skipped")                 # a skipped step is told apart from a done one by its word, not by colour


def test_a_step_with_video_times_shows_them_and_the_player_is_moved_to_its_start(win):
    s, _tid = _video_tutorial(win)
    moves = []
    s.player.seek = moves.append
    s.start_button.click()
    step = s.engine.current_step()
    assert step.video_start_s is not None and "Step video time" in s.time_label.text() and moves[-1] == step.video_start_s
    s.done_button.click()
    assert moves[-1] == s.engine.current_step().video_start_s                         # the video follows the step
    n = len(moves)
    s.replay_button.click()
    assert len(moves) == n + 1 and moves[-1] == s.engine.current_step().video_start_s
    s.steps_list.itemClicked.emit(s.steps_list.item(0))                               # a step clicked in the list: the video jumps there, the session stays where it is
    assert moves[-1] == s.engine.steps[0][1].video_start_s and s.engine.position == 2


def test_pause_and_play_follow_the_player_state(win):
    s, _tid = _video_tutorial(win)
    assert s.pause_button.text() == "Pause"
    s.pause_button.click()
    assert s.pause_button.text() == "Play" and s.player.paused
    s.pause_button.click()
    assert s.pause_button.text() == "Pause" and not s.player.paused


def test_without_the_web_engine_the_space_says_so_and_offers_the_browser(win):
    s, _tid = _video_tutorial(win)
    opened = []
    s.player.open_url = opened.append
    assert not s.player.available and not s.player.open_button.isHidden() and "WebEngine" in s.player.note.text()
    s.player.open_button.click()
    assert opened and opened[0].startswith("https://www.youtube.com/watch?v=")


def test_a_written_tutorial_has_no_video_and_says_so(win):
    rows = win.db.list_tutorials(win.user.id)
    tid = next(r["id"] for r in rows if not win.db.tutorial_source(r["id"]))
    win.open_session(tid)
    s = win.session
    assert "no video" in s.player.note.text() and s.player.open_button.isHidden() and s.time_label.text() == ""
    s.start_button.click()
    assert not s.replay_button.isEnabled() or s.engine.current_step().video_start_s is not None


def test_a_question_typed_beside_the_steps_opens_ask_guidewire_and_sends_it(win):
    s, tid = _video_tutorial(win)
    asked = []
    win.ask_screen.send = asked.append
    s.question.setText("what does the joint tool do")
    s.question_button.click()
    assert win.current_screen() is win.ask_screen and asked == ["what does the joint tool do"] and s.question.text() == ""
    win.open_session(tid)
    s.question_button.click()                                                         # an empty box sends nothing
    assert asked == ["what does the joint tool do"]


def test_help_still_opens_ask_guidewire_about_the_tutorial(win):
    s, tid = _video_tutorial(win)
    s.ask_button.click()
    assert win.current_screen() is win.ask_screen and win.ask_screen.tutorial.currentData() == tid


def test_the_whole_session_page_scrolls_so_nothing_is_cut_off_on_a_short_screen(win):
    s, _tid = _video_tutorial(win)
    win.resize(1100, 560)
    win.show()
    assert s.scroll.widget().minimumSizeHint().height() > 0 and s.scroll.verticalScrollBar() is not None


def test_a_webengine_of_another_qt_version_is_refused_before_any_web_view_is_made(monkeypatch):
    """Seen live: WebEngine 6.140 next to Qt 6.12 imports fine and then crashes the whole application when a web view is shown."""
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    import PyQt6.QtWebEngineCore as core

    from app.ui import player
    monkeypatch.setattr(core, "qWebEngineVersion", lambda: "6.140.0")
    problem = player.web_engine_problem()
    assert problem and "does not match" in problem and not player.web_engine_available()
    from PyQt6.QtCore import QT_VERSION_STR
    monkeypatch.setattr(core, "qWebEngineVersion", lambda: QT_VERSION_STR)
    assert player.web_engine_problem() is None
