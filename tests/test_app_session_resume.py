"""Leaving a session never loses progress; Pause and Resume keep the learner's place; Start over begins a new session and keeps the old one."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.db import Database
from app.session_engine import ACTIVE, FINISHED, NOT_STARTED, PAUSED, EngineError, SessionEngine
from app.step_editor import StepEditor

SAMPLE = Path("shared/examples/blender_cube_extrude.json")      # four steps


@pytest.fixture
def env():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    yield db, uid, tid
    db.close()


# ---------------------------------------------------------------- the engine
def test_pause_keeps_the_step_and_resume_continues_there(env):
    db, uid, tid = env
    e = SessionEngine.create(db, uid, tid)
    e.start()
    e.complete()
    e.pause()
    assert e.state == PAUSED and e.position is None and e.paused_at == 2 and e.progress() == (1, 4)
    e.resume()
    assert e.state == ACTIVE and e.position == 2 and e.statuses()[0] == "done"


def test_a_paused_session_refuses_step_changes_and_resume_needs_a_pause(env):
    db, uid, tid = env
    e = SessionEngine.create(db, uid, tid)
    with pytest.raises(EngineError):
        e.pause()                                  # not started
    e.start()
    with pytest.raises(EngineError):
        e.resume()                                 # not paused
    e.pause()
    for action in (e.complete, e.skip, e.back, e.pause):
        with pytest.raises(EngineError):
            action()


def test_resume_or_create_continues_an_unfinished_session_and_starts_a_new_one_after_it_finishes(env):
    db, uid, tid = env
    first = SessionEngine.resume_or_create(db, uid, tid)
    first.start()
    first.complete()
    again = SessionEngine.resume_or_create(db, uid, tid)
    assert again.session_id == first.session_id and again.position == 2 and again.progress() == (1, 4)
    again.pause()
    assert SessionEngine.resume_or_create(db, uid, tid).session_id == first.session_id
    again.resume()
    for _ in range(3):
        again.complete()
    assert again.state == FINISHED
    fresh = SessionEngine.resume_or_create(db, uid, tid)
    assert fresh.session_id != first.session_id and fresh.state == NOT_STARTED


def test_a_pause_survives_closing_the_app(tmp_path):
    path = tmp_path / "gw.sqlite"
    db = Database(path)
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    e.complete()
    e.pause()
    db.close()
    db2 = Database(path)
    back = SessionEngine.resume_or_create(db2, uid, tid)
    assert back.state == PAUSED and back.paused_at == 2 and back.progress() == (1, 4)
    db2.close()


def test_in_progress_tutorials_are_listed_for_home(env):
    db, uid, tid = env
    assert db.open_session_tutorials(uid) == set()
    e = SessionEngine.create(db, uid, tid)
    assert db.open_session_tutorials(uid) == set()      # created but never started
    e.start()
    assert db.open_session_tutorials(uid) == {tid}
    e.pause()
    assert db.open_session_tutorials(uid) == {tid}


# ---------------------------------------------------------------- the screens
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow(Database(":memory:"))
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.name.setText("A")
    w.login.do_register()
    w.add_demo_tutorials()
    yield w
    w.close()
    w.db.close()


def _first_tutorial(win):
    return win.db.list_tutorials(win.user.id)[0]["id"]


def test_going_back_and_returning_continues_the_same_session(win):
    tid = _first_tutorial(win)
    win.open_session(tid)
    sid = win.session.engine.session_id
    win.session.start_button.click()
    win.session.done_button.click()
    win.session.back_button.click()                                     # leaves for Home
    assert win.current_screen() is win.home and win.session.engine.state == PAUSED
    win.open_session(tid)
    assert win.session.engine.session_id == sid and win.session.engine.paused_at == 2
    assert "Paused at step 2" in win.session.step_text.text() and win.session.pause_button.text() == "Resume"
    win.session.pause_button.click()
    assert win.session.engine.state == ACTIVE and win.session.engine.position == 2 and win.session.progress.text().startswith("1 of")


def test_leaving_through_the_sidebar_also_pauses(win):
    win.show()
    win.open_session(_first_tutorial(win))
    win.session.start_button.click()
    win.sidebar.buttons["history"].click()
    assert win.session.engine.state == PAUSED


def test_the_pause_button_toggles_and_start_over_keeps_the_old_session(win):
    win.open_session(_first_tutorial(win))
    s = win.session
    assert not s.pause_button.isEnabled() and not s.restart_button.isEnabled()          # not started yet
    s.start_button.click()
    s.done_button.click()
    s.pause_button.click()
    assert s.engine.state == PAUSED and not s.done_button.isEnabled() and s.pause_button.text() == "Resume"
    old = s.engine.session_id
    s.confirm_restart = lambda: False
    s.restart_button.click()
    assert s.engine.session_id == old                                   # declined
    s.confirm_restart = lambda: True
    s.restart_button.click()
    assert s.engine.session_id != old and s.engine.state == NOT_STARTED
    kept = win.db.get_session(old)
    assert kept["state"] == PAUSED and kept["current_pos"] == 2         # the old session is still there, untouched


def test_home_says_continue_for_a_tutorial_with_a_session_in_progress(win):
    tid = _first_tutorial(win)
    win.show_home()
    assert win.home.session_button.text() == "Start session"
    win.open_session(tid)
    win.session.start_button.click()
    win.session.back_button.click()
    assert win.home.session_button.text() == "Continue session"


def test_history_continues_a_session_on_double_click(win):
    tid = _first_tutorial(win)
    win.open_session(tid)
    win.session.start_button.click()
    win.session.done_button.click()
    win.session.back_button.click()
    win.open_history()
    assert "paused" in win.history.list.item(0).text()
    win.history.list.itemDoubleClicked.emit(win.history.list.item(0))
    assert win.current_screen() is win.session and win.session.engine.paused_at == 2


def test_closing_the_window_pauses_an_active_session(win):
    win.open_session(_first_tutorial(win))
    win.session.start_button.click()
    engine = win.session.engine
    win.close()
    assert engine.state == PAUSED
