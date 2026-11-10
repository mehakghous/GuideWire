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
    win.open_review(1)
    assert win.current_screen() is win.login
    win.open_session(1)
    assert win.current_screen() is win.login
    win.show_home()
    assert win.current_screen() is win.login


# ---------------------------------------------------------------- step review editor
def _open_sample(w):
    _login(w)
    w.import_sample()
    return w.review


def test_import_sample_opens_the_editor_with_the_steps(win):
    r = _open_sample(win)
    assert win.current_screen() is win.review and r.list.count() == 4


def test_edit_move_delete_add_through_the_screen(win):
    r = _open_sample(win)
    r.list.setCurrentRow(1)
    r.apply_edit("s02", "Press Tab")
    assert r.list.item(1).text() == "2. Press Tab" and "Unsaved" in r.status.text()
    r.list.setCurrentRow(1)
    r.up_button.click()
    assert r.list.item(0).text() == "1. Press Tab" and r.list.currentRow() == 0
    r.delete_button.click()
    assert r.list.count() == 3
    r.list.setCurrentRow(0)
    r.apply_add("Save the file")
    assert r.list.count() == 4 and r.list.item(1).text().startswith("2. Save the file")


def test_empty_text_shows_a_message_and_changes_nothing(win):
    r = _open_sample(win)
    r.apply_edit("s01", "  ")
    assert "needs some text" in r.status.text() and r.list.item(0).text().endswith("Add a cube to the scene")


def test_save_returns_home_and_the_tutorial_is_listed(win):
    r = _open_sample(win)
    r.save_button.click()
    assert win.current_screen() is win.home and win.home.tutorials.count() == 1


def test_reopen_a_saved_tutorial_and_see_the_edit(win):
    r = _open_sample(win)
    r.apply_edit("s01", "Add a cube")
    r.save_button.click()
    win.home.tutorials.setCurrentRow(0)
    win.home.review_button.click()
    assert win.review.list.item(0).text() == "1. Add a cube"


def test_unsaved_edits_are_not_stored(win):
    r = _open_sample(win)
    r.apply_edit("s01", "Never saved")
    r.back_button.click()
    assert win.home.tutorials.count() == 0


def test_import_needs_a_login(win):
    win.import_sample()
    assert win.current_screen() is win.login


# ---------------------------------------------------------------- session screen
def _session(w):
    r = _open_sample(w)
    r.save_button.click()
    w.home.tutorials.setCurrentRow(0)
    w.home.session_button.click()
    return w.session


def test_session_starts_not_started_with_only_start_enabled(win):
    s = _session(win)
    assert win.current_screen() is win.session
    assert s.start_button.isEnabled() and not s.done_button.isEnabled() and not s.skip_button.isEnabled()
    assert "0 of 4" in s.progress.text()


def test_session_walks_through_to_finished(win):
    s = _session(win)
    s.start_button.click()
    assert "Step 1" in s.step_text.text() and not s.prev_button.isEnabled()
    s.done_button.click()
    assert "Step 2" in s.step_text.text() and s.prev_button.isEnabled()
    s.prev_button.click()
    assert "Step 1" in s.step_text.text()
    s.skip_button.click()
    s.done_button.click()
    s.done_button.click()
    s.done_button.click()
    assert "finished" in s.step_text.text() and "4 of 4" in s.progress.text()
    assert not s.done_button.isEnabled() and not s.start_button.isEnabled()


def test_craft_step_tells_the_user_it_is_manual(win):
    s = _session(win)
    s.start_button.click()
    for _ in range(3):
        s.done_button.click()
    assert "Manual step" in s.detail.text() and "Tell it when you are done" in s.detail.text()


def test_each_open_creates_its_own_session_and_back_goes_home(win):
    s = _session(win)
    first = s.engine.session_id
    s.back_button.click()
    win.home.tutorials.setCurrentRow(0)
    win.home.session_button.click()
    assert win.session.engine.session_id != first and win.current_screen() is win.session


# ---------------------------------------------------------------- history and profile
def test_history_is_empty_then_lists_sessions(win):
    _login(win)
    win.home.history_button.click()
    assert win.current_screen() is win.history and win.history.list.count() == 0
    assert "No sessions yet" in win.history.empty.text()
    win.history.back_button.click()
    s = _session(win)
    s.start_button.click()
    s.done_button.click()
    s.back_button.click()
    win.home.history_button.click()
    assert win.history.list.count() == 1
    text = win.history.list.item(0).text()
    assert "in progress" in text and "1/4 steps" in text


def test_history_shows_only_own_sessions(win):
    s = _session(win)
    s.back_button.click()
    win.on_logout()
    win.login.email.setText("b@x.com")
    win.login.password.setText("another pass1")
    win.login.do_register()
    win.home.history_button.click()
    assert win.history.list.count() == 0


def test_profile_saves_name_and_preferences(win):
    _login(win)
    win.home.profile_button.click()
    p = win.profile
    assert win.current_screen() is p and p.email.text() == "a@x.com" and p.theme.currentText() == "light" and p.overlay.isChecked()
    p.name.setText("Mehak")
    p.theme.setCurrentText("dark")
    p.overlay.setChecked(False)
    p.save_button.click()
    assert p.message.text() == "Saved" and win.user.display_name == "Mehak"
    win.on_logout()
    win.login.email.setText("a@x.com")
    win.login.password.setText("correct horse")
    win.login.do_login()
    win.home.profile_button.click()
    assert p.name.text() == "Mehak" and p.theme.currentText() == "dark" and not p.overlay.isChecked()


def test_profile_change_password(win):
    _login(win)
    win.home.profile_button.click()
    p = win.profile
    p.old_password.setText("wrong one")
    p.new_password.setText("new password1")
    p.password_button.click()
    assert "Current password is incorrect" in p.message.text()
    p.old_password.setText("correct horse")
    p.password_button.click()
    assert p.message.text() == "Password changed" and p.old_password.text() == ""
    win.on_logout()
    win.login.email.setText("a@x.com")
    win.login.password.setText("new password1")
    win.login.do_login()
    assert win.current_screen() is win.home


def test_history_and_profile_need_a_login(win):
    win.open_history()
    assert win.current_screen() is win.login
    win.open_profile()
    assert win.current_screen() is win.login


# ---------------------------------------------------------------- new tutorial from text
def _new(w):
    _login(w)
    w.home.new_button.click()
    return w.new_tutorial


def test_new_from_text_opens_the_editor_and_saves_nothing_until_saved(win):
    n = _new(win)
    assert win.current_screen() is n
    n.title.setText("My cube")
    n.text.setPlainText("Press Tab to enter Edit Mode\nSelect the cube\nMove it with G")
    n.create_button.click()
    assert win.current_screen() is win.review and win.review.list.count() >= 2 and "My cube" in win.review.title.text()
    win.review.back_button.click()
    assert win.home.tutorials.count() == 0
    win.home.new_button.click()
    n.text.setPlainText("Press Tab to enter Edit Mode")
    n.create_button.click()
    win.review.save_button.click()
    assert win.home.tutorials.count() == 1 and win.home.tutorials.item(0).text() == "Untitled tutorial"


def test_new_from_text_shows_a_message_when_no_steps(win):
    n = _new(win)
    n.text.setPlainText("what is a vertex group?")
    n.create_button.click()
    assert win.current_screen() is n and n.message.text()


def test_youtube_link_shows_the_gateway_message(win):
    n = _new(win)
    n.text.setPlainText("https://youtu.be/abc123")
    n.create_button.click()
    assert win.current_screen() is n and "AI gateway" in n.message.text()


def test_new_tutorial_needs_a_login_and_reset_clears_the_form(win):
    win.open_new_tutorial()
    assert win.current_screen() is win.login
    n = _new(win)
    n.text.setPlainText("junk")
    n.back_button.click()
    win.home.new_button.click()
    assert n.text.toPlainText() == "" and n.message.text() == ""


def test_junk_step_is_refused_and_a_manual_step_is_marked(win):
    r = _open_sample(win)
    r.apply_add("ss")
    assert "too short" in r.status.text() and r.list.count() == 4
    r.list.setCurrentRow(0)
    r.apply_add("Save the file")
    assert r.list.currentItem().text().endswith("[manual]")
    assert "Manual step" in r.detail.text() and "not recognised" in r.detail.text()


def test_recognised_step_is_checkable_and_not_marked_manual(win):
    r = _open_sample(win)
    r.list.setCurrentRow(0)
    r.apply_add("Press Tab to enter Edit Mode")
    assert "[manual]" not in r.list.currentItem().text() and "Checkable step" in r.detail.text()


def test_duplicate_step_is_refused_on_add_and_on_edit(win):
    r = _open_sample(win)
    r.apply_add("add a cube to the scene.")
    assert "already in the list" in r.status.text() and r.list.count() == 4
    r.apply_edit("s02", "Add a cube to the scene")
    assert "already in the list" in r.status.text()


def test_step_with_unreadable_checks_is_marked_in_the_list_and_explained(win):
    from shared.step_record import StatePredicate
    r = _open_sample(win)
    steps = r.editor.steps.steps
    steps[0].expected_state = [StatePredicate(kind="mode", target="OBJECT"), StatePredicate(kind="attribute_exists", target="a.b")]
    steps[1].expected_state = [StatePredicate(kind="node_count", target="joint", value=3)]
    r.refresh()
    assert r.list.item(0).text().endswith("[partly checkable]")
    assert r.list.item(1).text().endswith("[manual]")
    r.list.setCurrentRow(0)
    assert "Partly checkable" in r.detail.text() and "attribute_exists" in r.detail.text()
    r.list.setCurrentRow(1)
    assert "node_count" in r.detail.text() and "confirm it yourself" in r.detail.text()
