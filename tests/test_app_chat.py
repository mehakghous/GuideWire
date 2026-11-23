"""Ask GuideWire as a chat: saved conversations, the pickers below the text box, the greeting and its suggestions, steps cards (save, save and start, map onto another application), reusing history,
the Home page that scrolls, and the pages that are still being built. Offscreen Qt; no network (the knowledge base answers)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.db import Database  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow(Database(":memory:"), sync=True)
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.do_register()
    yield w
    w.close()
    w.db.close()


def chat(win):
    win.sidebar.buttons["ask"].click()
    return win.ask_screen


def say(a, text):
    a.composer.setPlainText(text)
    a.submit()


# ---------------------------------------------------------------- the database
def test_conversations_and_messages_are_stored_per_user_and_listed_newest_first():
    db = Database(":memory:")
    u1, u2 = db.add_user("a@x.com", b"h"), db.add_user("b@x.com", b"h")
    first, second = db.new_conversation(u1, "one", "maya"), db.new_conversation(u1, "two")
    db.add_chat_message(first, "user", "hi")
    db.add_chat_message(first, "bot", "hello", '{"x": 1}', {"who": "GuideWire"})
    assert [c["title"] for c in db.list_conversations(u1)] == ["one", "two"]          # the one just written to comes first
    assert db.list_conversations(u2) == [] and db.get_conversation(u2, first) is None
    msgs = db.chat_messages(first)
    assert [m["role"] for m in msgs] == ["user", "bot"] and msgs[1]["meta"] == {"who": "GuideWire"} and msgs[1]["steps_json"] == '{"x": 1}'
    assert db.delete_conversation(u2, first) is False and db.delete_conversation(u1, first) is True
    assert db.chat_messages(first) == [] and [c["title"] for c in db.list_conversations(u1)] == ["two"]       # deleting a chat deletes its messages
    assert second


def test_progress_summary_counts_what_the_user_did():
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file("shared/examples/blender_cube_extrude.json").save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    e.complete()
    e.skip()
    db.new_conversation(uid, "c")
    assert db.progress_summary(uid) == {"tutorials": 1, "sessions": 1, "finished": 0, "steps_done": 1, "chats": 1}


# ---------------------------------------------------------------- the empty chat and its pickers
def test_an_empty_chat_greets_and_offers_things_to_try_and_sending_one_starts_the_conversation(win):
    a = chat(win)
    assert not a.welcome.isHidden() and len(a.suggest_buttons) == 4 and "Blender" in a.suggest_buttons[0].text()
    a.suggest_buttons[3].click()                                                          # "What should I do before rigging?"
    assert a.welcome.isHidden() and a.conversation_id is not None
    assert "What should I do before rigging?" in a.transcript_text() and a.chat_list.count() == 1


def test_the_suggestions_follow_the_application_picker(win):
    a = chat(win)
    a.app_actions["houdini"].trigger()
    assert a.app.currentText() == "houdini" and "Houdini" in a.suggest_buttons[0].text() and a.app_button.text().startswith("Houdini")


def test_the_pickers_sit_below_the_text_box_like_a_model_picker(win):
    a = chat(win)
    win.show()
    QApplication.processEvents()
    assert a.composer.mapTo(a, a.composer.rect().topLeft()).y() < a.app_button.mapTo(a, a.app_button.rect().topLeft()).y()
    assert a.composer.mapTo(a, a.composer.rect().topLeft()).y() < a.about_button.mapTo(a, a.about_button.rect().topLeft()).y()
    assert {act.text() for act in a.app_menu.actions()} == {"Blender", "Maya", "Houdini"}
    assert a.about_button.text().startswith("About: General question")


def test_the_about_picker_lists_the_users_tutorials_and_choosing_one_changes_what_the_chat_is_about(win):
    win.home.demo_button.click()
    a = chat(win)
    names = [act.text() for act in a.about_menu.actions()]
    assert names[0] == "General question" and len(names) == 10
    a.about_menu.actions()[1].trigger()
    assert a.tutorial.currentData() is not None and a.about_button.text().startswith("About: ")
    assert "General" not in a.about_button.text()


def test_enter_sends_and_shift_enter_adds_a_line(win, qapp):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    a = chat(win)
    a.composer.setPlainText("what should i do before rigging")
    qapp.sendEvent(a.composer, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier))
    assert a.conversation_id is None                                                      # Shift+Enter did not send
    qapp.sendEvent(a.composer, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert a.conversation_id is not None and a.composer.toPlainText() == ""


# ---------------------------------------------------------------- history: going back to a chat
def test_a_chat_can_be_left_and_come_back_to_with_its_messages_and_its_steps_card(win):
    a = chat(win)
    a.app.setCurrentText("maya")
    say(a, "where do i start rigging in maya")
    first = a.conversation_id
    a.new_chat()
    assert a.conversation_id is None and not a.welcome.isHidden() and a.transcript_text() == ""
    say(a, "what should i do before rigging")
    assert a.chat_list.count() == 2 and a.conversation_id != first
    item = next(a.chat_list.item(i) for i in range(2) if a.chat_list.item(i).data(0x0100) == first)
    a._open_item(item)
    assert a.conversation_id == first and a.app.currentText() == "maya"
    assert "where do i start rigging in maya" in a.transcript_text() and "Starter plan" in a.transcript_text()
    assert len(a._cards) == 1 and "21 steps" in a._cards[0][0].findChildren(type(a._cards[0][0].saved_label))[0].text()
    assert a.title.text() == "where do i start rigging in maya"


def test_deleting_a_chat_removes_it_from_the_list_and_the_database(win):
    a = chat(win)
    say(a, "what should i do before rigging")
    cid = a.conversation_id
    a.delete_chat()
    assert a.chat_list.count() == 0 and a.conversation_id is None and win.db.get_conversation(win.user.id, cid) is None


def test_chats_belong_to_the_signed_in_user(win):
    a = chat(win)
    say(a, "what should i do before rigging")
    win.on_logout()
    win.login.email.setText("b@x.com")
    win.login.password.setText("correct horse")
    win.login.do_register()
    assert chat(win).chat_list.count() == 0


# ---------------------------------------------------------------- steps: save, start, map onto another application
def test_save_and_start_session_saves_the_steps_and_opens_a_session_on_them(win):
    a = chat(win)
    a.app.setCurrentText("maya")
    say(a, "where do i start rigging in maya")
    card = a._cards[-1][0]
    card.start_button.click()
    assert win.current_screen() is win.session and win.session.engine.app == "maya"
    assert [r["title"] for r in win.db.list_tutorials(win.user.id)] == [win.session.engine.db.get_session(win.session.engine.session_id) and win.db.list_tutorials(win.user.id)[0]["title"]]
    assert "21 steps" in win.session.progress.text() or "0 of 21" in win.session.progress.text()


def test_a_saved_card_offers_start_session_and_keeps_that_after_coming_back(win):
    a = chat(win)
    say(a, "what should i do before rigging")
    card = a._cards[-1][0]
    card.save_button.click()
    assert card.save_button.isHidden() and not card.open_button.isHidden()
    cid = a.conversation_id
    a.new_chat()
    a.open_chat(cid)
    back = a._cards[-1][0]
    assert back.save_button.isHidden() and not back.open_button.isHidden() and back.tutorial_id is not None
    back.open_button.click()
    assert win.current_screen() is win.session


def test_the_same_question_can_be_mapped_onto_another_application(win):
    a = chat(win)
    a.app.setCurrentText("maya")
    say(a, "where do i start rigging in maya")
    first = a._cards[-1][0]
    assert set(first.map_buttons) == {"blender", "houdini"}
    first.map_buttons["blender"].click()
    assert a.app.currentText() == "blender" and len(a._cards) == 2
    assert "Blender" in a.app_button.text() and "where do i start rigging in Blender" in a.transcript_text()          # the question is rewritten for the new application
    assert set(a._cards[-1][0].map_buttons) == {"maya", "houdini"}                         # and it can go on to the next
    assert len(a._cards[-1][0].steps.steps) > 0 and a._cards[-1][0].steps.app == "blender"


# ---------------------------------------------------------------- history: use a session again
def finish_one_session(win):
    win.home.demo_button.click()
    win.home.session_button.click()
    s = win.session
    s.start_button.click()
    s.done_button.click()
    return s.engine.session_id, s.tutorial_id


def test_history_can_start_the_same_tutorial_again_review_it_or_continue_where_it_was_left(win):
    sid, tid = finish_one_session(win)
    win.sidebar.buttons["history"].click()
    h = win.history
    assert h.list.count() == 1 and h.again_button.isEnabled() and h.resume_button.isEnabled() and h.review_button.isEnabled()
    h.resume_button.click()
    assert win.current_screen() is win.session and win.session.engine.session_id == sid and win.session.engine.position == 2     # where it was left
    win.sidebar.buttons["history"].click()
    h.again_button.click()
    assert win.current_screen() is win.session and win.session.engine.session_id != sid and win.session.tutorial_id == tid and win.session.engine.state == "not_started"
    win.sidebar.buttons["history"].click()
    assert h.list.count() == 2
    h.review_button.click()
    assert win.current_screen() is win.review


def test_continue_is_only_offered_for_a_session_that_is_not_finished(win):
    win.home.demo_button.click()
    win.home.session_button.click()
    s = win.session
    s.start_button.click()
    while s.engine.state == "active":
        s.done_button.click()
    win.sidebar.buttons["history"].click()
    assert win.history.again_button.isEnabled() and not win.history.resume_button.isEnabled()


# ---------------------------------------------------------------- Home scrolls
def test_the_home_page_scrolls_and_the_tutorials_list_keeps_its_room_on_a_short_window(win, qapp):
    win.home.demo_button.click()
    win.resize(1100, 560)
    win.show()
    win.show_home()
    qapp.processEvents()
    scroll = win.home.scroll
    assert scroll.widget().height() > scroll.viewport().height()                          # more page than window: it scrolls
    assert win.home.tutorials.parentWidget().minimumHeight() >= 330 and scroll.verticalScrollBar().maximum() > 0
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    assert win.home.tutorials.height() >= 150                                             # at the bottom the list has room for several rows


# ---------------------------------------------------------------- pages still being built
def test_progress_learning_paths_and_achievements_are_in_the_sidebar_and_say_work_in_progress(win):
    for key, page in (("progress", win.progress_page), ("paths", win.paths_page), ("badges", win.badges_page)):
        win.sidebar.buttons[key].click()
        assert win.current_screen() is page and win.sidebar.buttons[key].property("on") is True
        assert "being built" in page.hero_title.text() or key == "progress"
        page.back_button.click()
        assert win.current_screen() is win.home


def test_the_progress_page_shows_the_real_numbers(win):
    finish_one_session(win)
    win.sidebar.buttons["progress"].click()
    text = win.progress_page.numbers.text()
    assert "<b>1</b> steps done" in text and "<b>0</b> sessions finished of <b>1</b> started" in text and "<b>9</b> tutorials" in text


def test_a_question_is_rewritten_for_the_application_it_is_mapped_onto():
    from app.ui.ask_screen import retarget
    assert retarget("where do i start rigging in maya", "blender") == "where do i start rigging in Blender"
    assert retarget("Give me the steps to bind the mesh", "houdini") == "Give me the steps to bind the mesh in Houdini"
    assert retarget("how do I bind in Maya and Houdini?", "blender") == "how do I bind in Blender and Blender?"
