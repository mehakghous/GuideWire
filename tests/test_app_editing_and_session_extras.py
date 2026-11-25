"""Tutorial editing (undo, rename, groups kept valid, delete from Home) and the video and questions inside a session."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.ask import AskResult
from app.db import Database
from app.step_editor import EditError, StepEditor
from app.video_link import watch_url

SAMPLE = Path("shared/examples/blender_cube_extrude.json")            # s01..s04, no groups


def grouped(layout):
    """An editor whose steps carry display groups; `layout` is one group id (or None) per step."""
    ed = StepEditor.from_json_file(SAMPLE)
    for st, gid in zip(ed.steps.steps, layout):
        st.group_id, st.group = (gid, f"Label {gid}") if gid else (None, None)
    assert ed.steps.group_problems == []
    return ed


def layout_of(ed):
    return [(s.id, s.group_id) for s in ed.steps.steps]


# ---------------------------------------------------------------- undo and rename
def test_undo_takes_back_each_kind_of_change_in_turn():
    ed = StepEditor.from_json_file(SAMPLE)
    before = ed.goals()
    ed.edit_goal("s01", "Press A to select everything in the scene")
    ed.move("s02", 1)
    ed.delete("s03")
    new = ed.add("Press N to open the side panel")
    assert ed.can_undo and new in [s.id for s in ed.steps.steps]
    for _ in range(4):
        assert ed.undo()
    assert ed.goals() == before and not ed.can_undo and not ed.undo()
    assert ed.dirty is False                                       # back at the state it was opened in


def test_undo_restores_order_numbers_and_depends_on():
    ed = StepEditor.from_json_file(SAMPLE)
    ed.steps.steps[2].depends_on = ["s02"]
    ed.delete("s02")
    assert ed.steps.steps[1].depends_on == []
    ed.undo()
    assert [s.order for s in ed.steps.steps] == [1, 2, 3, 4] and ed.steps.steps[2].depends_on == ["s02"]


def test_a_refused_change_leaves_nothing_to_undo():
    ed = StepEditor.from_json_file(SAMPLE)
    with pytest.raises(EditError):
        ed.add("   ")
    with pytest.raises(EditError):
        ed.edit_goal("s01", "")
    assert not ed.can_undo and not ed.dirty


def test_saving_clears_the_undo_history(tmp_path):
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    ed = StepEditor.from_json_file(SAMPLE)
    ed.delete("s04")
    ed.save(db, uid)
    assert not ed.can_undo and not ed.dirty
    ed.delete("s03")
    assert ed.undo() and len(ed) == 3 and ed.dirty is False


def test_rename_validates_trims_and_can_be_undone():
    ed = StepEditor.from_json_file(SAMPLE)
    old = ed.title
    ed.set_title("  My   cube \n tutorial ")
    assert ed.title == "My cube tutorial" and ed.dirty
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(EditError):
            ed.set_title(bad)
    ed.undo()
    assert ed.title == old and not ed.dirty
    ed.set_title(old)                                              # the same title is not a change
    assert not ed.can_undo


# ---------------------------------------------------------------- display groups stay valid
def test_moving_a_step_out_of_its_group_leaves_the_group_and_never_splits_it():
    ed = grouped(["g01", "g01", "g01", None])                      # s01 s02 s03 are one group
    ed.move("s02", 1)                                              # s01 s03 s02: still touching its group
    assert layout_of(ed) == [("s01", "g01"), ("s03", "g01"), ("s02", "g01"), ("s04", None)] and ed.steps.group_problems == []
    ed.move("s02", 1)                                              # s02 moves past the end of the group, next to s04
    assert layout_of(ed) == [("s01", "g01"), ("s03", "g01"), ("s04", None), ("s02", None)] and ed.steps.group_problems == []


def test_a_step_moved_into_the_middle_of_a_group_joins_it():
    ed = grouped(["g01", "g01", None, None])
    ed.move("s04", -2)                                             # s01 s04 s02 s03: s04 is between two group steps
    assert layout_of(ed) == [("s01", "g01"), ("s04", "g01"), ("s02", "g01"), ("s03", None)] and ed.steps.group_problems == []
    assert ed.steps.steps[1].group == "Label g01"


def test_a_step_added_inside_a_group_joins_it_and_one_added_after_it_does_not():
    ed = grouped(["g01", "g01", None, None])
    inside = ed.add("Press N to open the side panel", after="s01")           # between s01 and s02
    outside = ed.add("Press M to move to a collection", after="s02")         # after the last member
    by = {s.id: s.group_id for s in ed.steps.steps}
    assert by[inside] == "g01" and by[outside] is None and ed.steps.group_problems == []


def test_a_step_moved_between_two_groups_stays_where_it_belongs():
    ed = grouped(["g01", "g01", "g02", "g02"])
    ed.move("s02", 1)                                              # s01 s03 s02 s04: s02 is now inside group g02's neighbours? it sits between s03(g02) and s04(g02)
    assert ed.steps.group_problems == []
    assert {s.id: s.group_id for s in ed.steps.steps}["s02"] == "g02"


def test_deleting_steps_never_leaves_a_group_fragmented():
    ed = grouped(["g01", "g01", None, "g01"][:3] + [None])
    ed.delete("s02")
    assert ed.steps.group_problems == []
    ed2 = grouped(["g01", "g01", "g02", "g02"])
    ed2.delete("s02")
    assert ed2.steps.group_problems == [] and [s.group_id for s in ed2.steps.steps] == ["g01", "g02", "g02"]


# ---------------------------------------------------------------- video links
@pytest.mark.parametrize("url,start,expected", [
    ("https://www.youtube.com/watch?v=abcdefghijk", 90.4, "https://www.youtube.com/watch?v=abcdefghijk&t=90s"),
    ("https://youtu.be/abcdefghijk", 12, "https://www.youtube.com/watch?v=abcdefghijk&t=12s"),
    ("https://www.youtube.com/watch?list=PL1&v=abcdefghijk&t=5", None, "https://www.youtube.com/watch?v=abcdefghijk"),
    ("youtube.com/shorts/abcdefghijk", 0.5, "https://www.youtube.com/watch?v=abcdefghijk"),
    ("https://example.com/lesson.mp4", 30, "https://example.com/lesson.mp4"),
])
def test_watch_url_points_a_youtube_link_at_the_step(url, start, expected):
    assert watch_url(url, start) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "file:///C:/secret.txt", "javascript:alert(1)", "ftp://x/y", "not a link", "https://a b"])
def test_watch_url_refuses_anything_that_is_not_a_web_link(bad):
    assert watch_url(bad, 10) is None


# ---------------------------------------------------------------- the window
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow(Database(":memory:"), sync=True)
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.name.setText("A")
    w.login.do_register()
    yield w
    w.close()
    w.db.close()


def _tutorial_with_video(win):
    ed = StepEditor.from_json_file(SAMPLE)
    ed.steps.steps[1].video_start_s = 75.0
    tid = win.db.save_tutorial(win.user.id, "Cube", ed.steps, source_type="manual", source_url="https://www.youtube.com/watch?v=abcdefghijk")
    win.show_home()
    return tid


def test_the_session_offers_the_video_at_the_current_step_and_opens_only_that_link(win):
    tid = _tutorial_with_video(win)
    opened = []
    win.session.open_url = opened.append
    win.open_session(tid)
    s = win.session
    assert not s.video_button.isVisibleTo(s)                           # not started: no step yet
    s.start_button.click()
    assert s.video_button.isVisibleTo(s)
    s.video_button.click()
    s.done_button.click()                                              # now on step 2, which starts at 75 s
    s.video_button.click()
    assert opened == ["https://www.youtube.com/watch?v=abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk&t=75s"]
    s.pause_button.click()
    s.video_button.click()                                             # paused on step 2: still that step's moment
    assert opened[-1].endswith("&t=75s")


def test_a_tutorial_without_a_link_or_with_an_unsafe_one_has_no_video_button(win):
    win.add_demo_tutorials()
    ed = StepEditor.from_json_file(SAMPLE)
    local = win.db.save_tutorial(win.user.id, "Typed", ed.steps, source_type="manual")
    unsafe = win.db.save_tutorial(win.user.id, "Odd", ed.steps, source_type="manual", source_url="file:///C:/x.txt")
    for tid in (local, unsafe):
        win.open_session(tid)
        win.session.start_button.click()
        assert not win.session.video_button.isVisibleTo(win.session)
        win.session.back_button.click()


class FakeAsker:
    model_available = True

    def __init__(self):
        self.calls = []

    def ask(self, text, app, *, tutorial=None, title=None, url=None, use_model=False):
        self.calls.append(dict(text=text, app=app, title=title, url=url, use_model=use_model, steps=len(tutorial.steps) if tutorial else None))
        return AskResult("Because Edit Mode needs the mesh selected.", None, "model", use_model)


def test_a_question_in_a_session_knows_the_step_and_shows_the_answer(win):
    tid = _tutorial_with_video(win)
    asker = FakeAsker()
    win.session.asker = asker
    win.open_session(tid)
    s = win.session
    s.start_button.click()
    s.done_button.click()
    s.question.setText("why do I press Tab?")
    s.question_button.click()
    call = asker.calls[0]
    assert "step 2" in call["text"] and "why do I press Tab?" in call["text"] and call["steps"] == 4 and call["url"].startswith("https://www.youtube.com")
    assert call["use_model"] is True and s.answer.text().startswith("Because Edit Mode") and s.question.text() == "" and s.question_button.isEnabled()


def test_the_ai_choice_in_privacy_decides_whether_the_model_is_used_for_a_session_question(win):
    tid = _tutorial_with_video(win)
    asker = FakeAsker()
    win.session.asker = asker
    win.change_privacy({"ai": False})
    win.open_session(tid)
    win.session.start_button.click()
    win.session.question.setText("what next?")
    win.session.ask_question()
    assert asker.calls[0]["use_model"] is False


def test_questions_work_without_a_session_step_and_say_so_when_unavailable(win):
    tid = _tutorial_with_video(win)
    win.open_session(tid)
    s = win.session
    s.asker = None
    s.question.setText("hello")
    s.ask_question()
    assert "not available" in s.answer.text()
    s.question.setText("   ")
    s.answer.setText("")
    s.ask_question()
    assert s.answer.text() == ""                                       # an empty question does nothing


def test_a_failed_answer_is_reported_politely(win):
    tid = _tutorial_with_video(win)

    class Broken(FakeAsker):
        def ask(self, *a, **k):
            raise RuntimeError("boom secret")
    win.session.asker = Broken()
    win.open_session(tid)
    win.session.question.setText("hello")
    win.session.ask_question()
    assert "Sorry, that failed" in win.session.answer.text() and "secret" not in win.session.answer.text()


# ---------------------------------------------------------------- the review screen and Home
def test_review_has_undo_and_rename(win):
    win.import_sample()
    r = win.review
    assert not r.undo_button.isEnabled()
    r.apply_edit(r.selected_id(), "Press A to select everything")
    assert r.undo_button.isEnabled() and "Press A to select everything" in r.list.item(0).text()
    r.undo()
    assert "Press A to select everything" not in r.list.item(0).text() and not r.undo_button.isEnabled() and r.status.text() == ""
    r.apply_rename("My cube lesson")
    assert "My cube lesson" in r.title.text() and r.editor.dirty
    r.apply_rename("   ")
    assert "needs a title" in r.status.text() and "My cube lesson" in r.title.text()


def test_home_deletes_the_selected_tutorial_only_after_confirming(win):
    win.add_demo_tutorials()
    n = win.home.tutorials.count()
    first = win.home.selected_tutorial()
    win.home.confirm_delete = lambda title: False
    win.home.delete_button.click()
    assert win.home.tutorials.count() == n
    win.home.confirm_delete = lambda title: True
    win.home.delete_button.click()
    assert win.home.tutorials.count() == n - 1 and first not in [r["id"] for r in win.db.list_tutorials(win.user.id)]
    assert any(c["op"] == "delete" for c in win.db.pending_changes(win.user.id))        # the online copy will hear about it


def test_delete_is_disabled_with_no_tutorials(win):
    assert not win.home.delete_button.isEnabled()


def test_a_tutorial_that_cannot_be_loaded_for_a_question_shows_a_message_and_does_not_crash(win):
    tid = _tutorial_with_video(win)
    win.open_session(tid)
    win.session.asker = FakeAsker()
    win.session.load_tutorial = lambda _tid: (_ for _ in ()).throw(ValueError("bad steps"))
    win.session.question.setText("hello")
    win.session.ask_question()
    assert "could not be read" in win.session.answer.text() and win.session.question_button.isEnabled()
