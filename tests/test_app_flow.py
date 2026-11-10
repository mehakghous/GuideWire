"""The whole journey of a BRAND-NEW account, which is what a stranger (a professor) does: create an account, get content, ask, add a video, review, run a session. Off-screen, no network, no real model."""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import demo_content  # noqa: E402
from app.db import Database  # noqa: E402
from app.pipeline import MAX_VIDEO_S, video_steps  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from ingestion.providers.fake import ScriptedProvider  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow(Database(":memory:"), sync=True)
    yield w
    w.close()
    w.db.close()


def register(w, email="prof@example.com"):
    w.login.name.setText("Professor")
    w.login.email.setText(email)
    w.login.password.setText("a-long-password-1")
    w.login.do_register()


def test_a_new_account_sees_a_welcome_with_three_ways_in_not_a_blank_list(win):
    register(win)
    assert win.current_screen() is win.home
    assert not win.home.empty.isHidden() and win.home.tutorials.isHidden()
    text = win.home.empty.text()
    assert "Add demo tutorials" in text and "Ask GuideWire" in text and "video link" in text
    for b in (win.home.ask_button, win.home.demo_button, win.home.new_button):
        assert b.isEnabled()


def test_add_demo_tutorials_gives_any_account_nine_tutorials_once(win):
    register(win)
    win.home.demo_button.click()
    assert win.home.tutorials.count() == 9 and win.home.empty.isHidden() and not win.home.tutorials.isHidden()
    win.home.demo_button.click()
    assert win.home.tutorials.count() == 9                                                              # clicking twice adds nothing
    assert win.home.selected_tutorial() is not None                                                      # something is selected, so Review and Start session just work
    other = win.accounts.register("second@example.com", "another-long-pw-1", "Second")
    assert demo_content.add_demo_tutorials(win.db, other.id) == 9 and len(win.db.list_tutorials(other.id)) == 9


def test_the_whole_journey_ask_where_to_start_save_review_and_run_a_session(win):
    register(win)
    win.home.ask_button.click()
    assert win.current_screen() is win.ask_screen
    win.ask_screen.app.setCurrentText("maya")
    win.ask_screen.input.setText("where do i start rigging in maya")
    win.ask_screen.submit()
    assert win.ask_screen.last_steps is not None and len(win.ask_screen.last_steps.steps) == 21
    assert not win.ask_screen.save_button.isHidden() and "Save these 21 steps" in win.ask_screen.save_button.text()
    assert "/load" not in win.ask_screen.transcript.toPlainText()                                         # no terminal-only hint in the app
    win.ask_screen.save_button.click()
    assert win.ask_screen.save_button.isHidden() and "Saved as" in win.ask_screen.transcript.toPlainText()
    win.ask_screen.back_button.click()
    assert win.home.tutorials.count() == 1 and "Starter plan" in win.home.tutorials.item(0).text()
    win.home.review_button.click()
    assert win.current_screen() is win.review and win.review.list.count() == 21
    win.review.list.setCurrentRow(1)
    assert "Part of:" in win.review.detail.text()                                                         # the groups show in the app
    win.review.back_button.click()
    win.home.session_button.click()
    assert win.current_screen() is win.session
    win.session.start_button.click()
    win.session.done_button.click()
    assert "1 of 21 steps done" in win.session.progress.text()


def test_saving_the_same_answer_twice_does_not_overwrite_the_first(win):
    register(win)
    win.home.ask_button.click()
    for _ in range(2):
        win.ask_screen.app.setCurrentText("blender")
        win.ask_screen.input.setText("what should i do before rigging")
        win.ask_screen.submit()
        win.ask_screen.save_button.click()
    titles = [r["title"] for r in win.db.list_tutorials(win.user.id)]
    assert len(titles) == 2 and len(set(titles)) == 2 and any(t.endswith("(2)") for t in titles)


def test_a_question_about_a_chosen_tutorial_is_answered_from_its_steps_and_offers_no_save(win):
    register(win)
    win.home.demo_button.click()
    tid = next(r["id"] for r in win.db.list_tutorials(win.user.id) if r["title"].startswith("Blender 5.1 Basic Rigging"))
    win.home.ask_button.click()
    win.ask_screen.set_tutorials([(r["id"], r["title"]) for r in win.db.list_tutorials(win.user.id)], select=tid)
    win.ask_screen.app.setCurrentText("blender")
    win.ask_screen.input.setText("what is he doing at 1:30")
    win.ask_screen.submit()
    page = win.ask_screen.transcript.toPlainText()
    assert "s08" in page and "Object Mode" in page and win.ask_screen.save_button.isHidden()


def test_a_plain_how_to_question_without_the_ai_model_still_gets_steps_from_the_knowledge_base(win):
    register(win)
    win.home.ask_button.click()
    win.ask_screen.app.setCurrentText("maya")
    assert not win.ask_screen.use_model.isEnabled()                                                       # no AI model on this window: the checkbox says so
    win.ask_screen.input.setText("how do i bind my mesh in maya")
    win.ask_screen.submit()
    assert "Smooth Bind" in win.ask_screen.transcript.toPlainText() and win.ask_screen.last_steps is not None


def test_ask_about_this_tutorial_from_a_session_opens_the_ask_screen_on_that_tutorial(win):
    register(win)
    win.home.demo_button.click()
    win.home.session_button.click()
    tid = win.session.tutorial_id
    win.session.ask_button.click()
    assert win.current_screen() is win.ask_screen and win.ask_screen.tutorial.currentData() == tid


# ------------------------------------------------------------------ a video link
def _meta(duration=300.0, privacy="public", title="A rigging video"):
    return lambda vid: SimpleNamespace(duration_s=duration, privacy_status=privacy, title=title)


def _step(goal, start, end):
    return {"goal": goal, "actions": [{"verb": "click", "ui_element": "Skeleton > Create Joints"}], "expected_state": [], "start_state": [], "video_start_s": start, "video_end_s": end,
            "result": "done", "how_to": [], "check": [], "confidence": 0.8, "kind": "mechanics"}


def _good_provider():
    return ScriptedProvider([{"steps": [_step("Create the hip joint", "00:05", "00:15"), _step("Create the knee joint", "00:20", "00:30")]},
                             {"groups": [{"label": "Create the leg joints", "step_ids": ["s01", "s02"]}]}])


def test_a_video_link_becomes_grouped_steps_and_opens_in_the_editor(win):
    register(win)
    from app.pipeline import video_steps as vs
    win.new_tutorial.video_runner = lambda url, app, status: vs(url, app, provider_factory=_good_provider_once(), fetch_meta=_meta(), on_status=status)
    win.home.new_button.click()
    win.new_tutorial.app.setCurrentText("maya")
    win.new_tutorial.text.setPlainText("please use https://www.youtube.com/watch?v=AAAAAAAAAAA thanks")
    win.new_tutorial.create_button.click()
    assert win.current_screen() is win.review and win.review.list.count() == 2
    assert win.review.title.text().count("A rigging video") == 1                                           # the video's own title
    win.review.list.setCurrentRow(0)
    assert "Part of: Create the leg joints" in win.review.detail.text()
    win.review.save_button.click()
    assert len(win.db.list_tutorials(win.user.id)) == 1


def _good_provider_once():
    p = _good_provider()
    return lambda: p


def test_video_steps_reports_each_failure_in_plain_words_and_never_raises():
    link = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    r = video_steps(link, "maya")                                                                          # no AI model configured
    assert r.steps is None and "AI gateway" in r.message
    r = video_steps("this is not a link", "maya", provider_factory=_good_provider_once(), fetch_meta=_meta())
    assert r.steps is None and "does not look like a YouTube link" in r.message
    r = video_steps(link, "maya", provider_factory=_good_provider_once(), fetch_meta=_meta(privacy="private"))
    assert r.steps is None and "'private'" in r.message
    r = video_steps(link, "maya", provider_factory=_good_provider_once(), fetch_meta=_meta(duration=MAX_VIDEO_S + 60))
    assert r.steps is None and "minutes long" in r.message
    r = video_steps(link, "nuke", provider_factory=_good_provider_once(), fetch_meta=_meta())
    assert r.steps is None and "Unknown application" in r.message

    def no_key():
        raise RuntimeError("The AI model is not set up on this computer: put GEMINI_API_KEY in the .env file.")
    r = video_steps(link, "maya", provider_factory=no_key, fetch_meta=_meta())
    assert r.steps is None and "GEMINI_API_KEY" in r.message
    r = video_steps(link, "maya", provider_factory=lambda: ScriptedProvider([RuntimeError("down")]), fetch_meta=_meta())
    assert r.steps is None and "could not be read right now" in r.message


def test_video_steps_still_works_without_the_youtube_key_and_keeps_the_steps_if_grouping_fails():
    def no_meta(vid):
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    p = ScriptedProvider([{"steps": [_step("Create the hip joint", "00:05", "00:15"), _step("Create the knee joint", "00:20", "00:30")]}, RuntimeError("grouping down")])
    r = video_steps("https://youtu.be/AAAAAAAAAAA", "maya", provider_factory=lambda: p, fetch_meta=no_meta)
    assert r.steps is not None and len(r.steps.steps) == 2 and any("could not be grouped" in n for n in r.notes)
    assert r.steps.source_type == "youtube" and "Drafted automatically" in r.notes[0]


def test_the_default_video_model_says_plainly_when_no_key_is_set(monkeypatch):
    import dotenv

    from app.pipeline import default_video_provider
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        default_video_provider()


def test_without_any_model_a_pasted_link_still_gets_the_old_message(win):
    register(win)
    win.home.new_button.click()
    win.new_tutorial.text.setPlainText("https://youtu.be/abc123")
    win.new_tutorial.create_button.click()
    assert win.current_screen() is win.new_tutorial and "AI gateway" in win.new_tutorial.message.text()
