import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.db import Database  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from shared.step_record import StepList  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow(Database(":memory:"))
    yield w
    w.close()
    w.db.close()


def _login(w, email="a@x.com", pw="correct horse"):
    w.login.email.setText(email)
    w.login.password.setText(pw)
    w.login.do_register()


def test_starts_on_login(win):
    assert win.current_screen() is win.login


def test_register_goes_home_and_clears_the_password(win):
    win.login.name.setText("Mehak")
    _login(win)
    assert win.current_screen() is win.home
    assert "Mehak" in win.home.greeting.text()
    assert win.login.password.text() == ""


def test_wrong_password_stays_on_login_with_a_message(win):
    _login(win)
    win.on_logout()
    win.login.email.setText("a@x.com")
    win.login.password.setText("nope nope")
    win.login.do_login()
    assert win.current_screen() is win.login
    assert "Incorrect email or password" in win.login.message.text()


def test_duplicate_email_shows_a_message(win):
    _login(win)
    win.on_logout()
    _login(win)
    assert win.current_screen() is win.login
    assert "already exists" in win.login.message.text()


def test_logout_returns_to_login_and_forgets_the_user(win):
    _login(win)
    win.home.logout.emit()
    assert win.current_screen() is win.login and win.user is None


def test_home_lists_only_own_tutorials_and_opens_the_placeholders(win):
    _login(win)
    steps = StepList.model_validate(json.loads(Path("shared/examples/blender_cube_extrude.json").read_text(encoding="utf-8")))
    tid = win.db.save_tutorial(win.user.id, "Cube", steps)
    other = win.db.add_user("b@x.com", b"h")
    win.db.save_tutorial(other, "Not mine", steps)
    win.show_home()
    assert win.home.tutorials.count() == 1
    win.home.tutorials.setCurrentRow(0)
    win.home.review_button.click()
    assert win.current_screen() is win.review and win.review.tutorial_id == tid
    win.review.back_button.click()
    win.home.tutorials.setCurrentRow(0)
    win.home.session_button.click()
    assert win.current_screen() is win.session and win.session.tutorial_id == tid
    win.session.back_button.click()
    assert win.current_screen() is win.home


def test_buttons_do_nothing_without_a_selection(win):
    _login(win)
    win.home.review_button.click()
    assert win.current_screen() is win.home


def test_screens_never_open_without_a_login(win):
    win.go(win.review, 1)
    assert win.current_screen() is win.login
    win.show_home()
    assert win.current_screen() is win.login
