"""Screen guidance in the session screen: the timer, the status line, the highlight, the "covering the application" warning. Offscreen Qt, a fake vision service and a fake overlay."""
import os
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")          # CI installs no Qt: the screen guide needs it

import vision_fakes as vf  # noqa: E402
from app import vision_bridge as vb  # noqa: E402
from app.ui.screen_guide import ScreenGuide  # noqa: E402
from shared.grounding import Rect  # noqa: E402

SAMPLE = Path("shared/examples/blender_cube_extrude.json")


FakeService = vf.FakeService                                  # tests/vision_fakes.py: look() -> (observed, context); the screen shows an Add menu in the top bar


class FakeOverlay:
    def __init__(self):
        self.covered, self.marks, self.shown, self.closed = None, [], 0, False

    def cover(self, area):
        self.covered = area

    def set_marks(self, marks):
        self.marks = list(marks)

    def show_click_through(self):
        self.shown += 1

    def hide(self):
        self.shown = 0

    def close(self):
        self.closed = True


@pytest.fixture
def env():
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    from app.ui.screens import SessionScreen
    qapp = QApplication.instance() or QApplication([])
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    engine = SessionEngine.create(db, uid, tid)
    engine.start()
    overlay = FakeOverlay()
    svc = FakeService()
    screen = SessionScreen()
    screen.sync = True
    screen.guide = ScreenGuide(lambda: overlay)
    screen.bridge = vb.VisionBridge(lambda app: svc, window_finder=lambda app: (0, 0, 1920, 1080))
    screen.set_bridge(screen.bridge)
    screen.load(engine)
    yield screen, engine, svc, overlay
    screen.timer.stop()
    db.close()
    del qapp


def test_there_is_no_screen_watching_without_a_bridge():
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ui.screens import SessionScreen
    qapp = QApplication.instance() or QApplication([])
    s = SessionScreen()
    s.set_bridge(None)
    assert s.watch_box.isHidden() and not s.watching and not s.timer.isActive()
    s.set_bridge(vb.VisionBridge(None))
    assert s.watch_box.isHidden()                                     # a bridge with no vision behind it shows no checkbox
    del qapp


def test_the_timer_runs_only_while_a_step_is_active_the_screen_is_shown_and_watching_is_on(env):
    screen, engine, _svc, _o = env
    screen.sync = False
    assert not screen.timer.isActive()                                # not visible yet
    screen.show()
    screen.refresh()
    assert screen.watching and screen.timer.isActive() and screen.timer.interval() == 500
    screen.watch_box.setChecked(False)
    assert not screen.timer.isActive() and screen.watch_label.text() == ""
    screen.watch_box.setChecked(True)
    assert screen.timer.isActive()
    screen.hide()
    assert not screen.timer.isActive()
    screen.close()


def test_a_poll_highlights_the_target_and_shows_a_plain_message(env):
    screen, engine, _svc, overlay = env
    screen.poll()
    assert screen.watch_label.text() and overlay.covered == Rect(0, 0, 1920, 1080)
    assert len(overlay.marks) == 1 and overlay.marks[0].rect == Rect(246, 16, 48, 24)        # the Add menu read at (250, 20, 40 x 16), with a little padding
    assert overlay.shown >= 1


def test_the_step_advances_in_the_window_when_the_application_shows_it_done(env):
    screen, engine, svc, overlay = env
    engine.complete()                                                 # s01 by hand; s02 expects EDIT_MESH
    screen.refresh()
    assert engine.current_step().id == "s02"
    svc.observed = {"mode": "EDIT_MESH"}
    screen.poll()
    assert engine.current_step().id == "s03" and "saw this step done" in screen.status.text() and "Step 3" in screen.step_text.text()


def test_nothing_advances_when_the_state_is_not_met_and_done_still_works_by_hand(env):
    screen, engine, svc, _o = env
    engine.complete()
    screen.refresh()
    svc.observed = {"mode": "OBJECT"}
    screen.poll()
    assert engine.current_step().id == "s02"
    screen.done_button.click()
    assert engine.current_step().id == "s03"


def test_a_missing_application_window_is_said_in_words_and_clears_the_highlight(env):
    screen, _e, svc, overlay = env
    screen.poll()
    assert overlay.shown >= 1
    svc.found = False
    screen.poll()
    assert "in front so GuideWire can see it" in screen.watch_label.text() and overlay.shown == 0


def test_missing_vision_packages_are_explained_once_in_the_window(env):
    screen, engine, _svc, _o = env

    def broken(app):
        raise ImportError("No module named 'winrt'")
    screen.bridge = vb.VisionBridge(broken)
    screen.poll()
    assert "Windows OCR packages" in screen.watch_label.text() and engine.position == 1


def test_a_look_that_finishes_after_the_learner_moved_on_is_ignored(env):
    screen, engine, svc, overlay = env
    svc.observed = {"mode": "EDIT_MESH"}
    look = screen.bridge.look(engine.current_step(), "blender")
    first = engine.current_step().id
    screen.done_button.click()                                        # the learner pressed Done while the screen was being read
    svc.observed = {"mode": "OBJECT"}                                 # and the new step (s02, Edit Mode) is not done on screen
    screen._looked(look, first)
    assert engine.current_step().id == "s02"                          # the stale look did not complete anything
    assert screen._shown_step == "s02" and svc.looks                  # a look for the NEW step was started at once, not after the next timer tick


def test_a_second_poll_while_one_is_running_is_skipped(env):
    screen, _e, _svc, _o = env
    screen._busy = True
    before = screen.watch_label.text()
    screen.poll()
    assert screen.watch_label.text() == before and not _svc.looks


def test_the_warning_appears_when_guidewire_covers_the_application_and_the_button_hands_the_screen_over_to_the_small_guide(env):
    screen, _e, _svc, _o = env
    screen.show()
    own = screen._own_rect()
    screen._warn_if_covering((own[0], own[1], own[2] + 50, own[3] + 50))
    assert not screen.cover_label.isHidden() and not screen.side_button.isHidden() and "Minimize it" in screen.cover_label.text()
    screen._warn_if_covering((own[0] + own[2] + 500, own[1], 400, 400))
    assert screen.cover_label.isHidden() and not screen.side_button.isHidden()          # the button stays while watching: it is the way to give the application the whole screen
    screen.poll()
    screen.minimize_to_guide()
    assert screen.window().isMinimized() or not screen.window().isVisible()
    assert screen.panel is not None and not screen.panel.isHidden()                       # the small guide stays on screen
    screen.close()


def test_the_small_guide_can_be_minimized_to_a_tab_and_opened_again_and_keeps_where_the_learner_put_it(env):
    screen, _e, _svc, _o = env
    screen.poll()
    p = screen.panel
    assert p is not None and p.width() <= 320 and not p.minimized
    p.set_content("GuideWire · step 3 of 18", "Go to Edit Mode", ["Press Tab"], "Click Edit Mode", ("Tab",))
    p.toggle_minimized()
    assert p.minimized and p.body.isHidden() and p.height() <= 40 and p.header.text() == "GuideWire 3/18 ▸"
    p.toggle_minimized()
    assert not p.minimized and not p.body.isHidden() and p.header.text() == "GuideWire · step 3 of 18"
    p.move(321, 123)
    p.moved_by_user = True
    p.put(5, 5)
    assert (p.x(), p.y()) == (321, 123)                       # the app no longer moves a box the learner placed
    screen.close()


def test_the_key_caps_are_shown_for_a_step_that_says_to_press_keys(env):
    screen, _e, _svc, _o = env
    p = screen._ensure_panel()
    p.set_content("GuideWire", "Delete everything", [], "Press A then Delete", ("A", "Delete"))
    caps = [lab.text() for lab in p._key_labels if lab.objectName() == "keys"]
    assert caps == ["A", "Delete"]
    p.set_content("GuideWire", "Next", [], "", ())
    assert [lab for lab in p._key_labels if lab.objectName() == "keys"] == []
    screen.close()


def test_the_overlay_is_closed_with_the_window_and_a_broken_overlay_does_not_break_the_session(env):
    screen, engine, _svc, overlay = env
    screen.poll()
    screen.guide.close()
    assert overlay.closed
    broken = ScreenGuide(lambda: (_ for _ in ()).throw(RuntimeError("no display")))
    assert broken.show((1, 2, 3, 4), (0, 0, 10, 10)) is False and broken.error and "RuntimeError" in broken.error
    screen.guide = broken
    screen.poll()                                                     # the session still works without a highlight
    assert engine.position == 1


def test_the_geometry_helpers():
    assert vb.overlaps((0, 0, 100, 100), (50, 50, 100, 100)) and not vb.overlaps((0, 0, 100, 100), (100, 0, 50, 50)) and not vb.overlaps(None, (0, 0, 1, 1))
    assert vb.side_rect((0, 0, 1920, 1080), 0.3) == (1344, 0, 576, 1080)
    assert vb.side_rect((0, 0, 1920, 1080), 0.3, right=False) == (0, 0, 576, 1080)
    assert vb.side_rect((0, 0, 800, 600), 0.1)[2] == 320                 # never narrower than a usable panel


# ---- the label, the instruction box and following the window

def test_the_hint_names_the_next_click_from_the_path_and_what_is_visible():
    assert vb.hint_for("Add > Mesh > Cylinder", "") == "Open: Add > Mesh > Cylinder"
    assert vb.hint_for("Add > Mesh > Cylinder", "Add") == "Click Add, then Mesh > Cylinder"
    assert vb.hint_for("Add > Mesh > Cylinder", "mesh") == "Click Mesh, then Cylinder"
    assert vb.hint_for("Add > Mesh > Cylinder", "Cylinder", complete=True) == "Click Cylinder"
    assert vb.hint_for(None, "x") == ""


def test_the_highlight_draws_no_text_because_text_over_the_application_is_read_back_by_the_ocr(env):
    screen, _e, _svc, overlay = env
    screen.poll()
    assert overlay.marks and overlay.marks[0].label == ""
    assert screen.panel is not None and screen.panel.hint.text().startswith(("Click", "Open"))      # the words go in the instruction box instead


def test_the_instruction_box_shows_the_goal_how_to_and_hint_outside_the_window_when_there_is_room(env):
    screen, engine, _svc, _o = env
    screen.poll()
    p = screen.panel
    assert p is not None and not p.isHidden()
    assert engine.current_step().goal in p.goal.text() and "step 1 of 4" in p.header.text() and p.hint.text()
    from app.ui.screen_guide import panel_position
    assert panel_position((0, 0, 1366, 728), (0, 0, 1920, 1080), (420, 200))[2] == "below"
    assert panel_position((0, 0, 1366, 1000), (0, 0, 1920, 1080), (420, 200))[2] == "beside"
    assert panel_position((0, 0, 1920, 1080), (0, 0, 1920, 1080), (420, 200))[2] == "inside"
    assert panel_position(None, (0, 0, 1920, 1080), (420, 200))[2] == "corner"
    x, y, where = panel_position((100, 50, 1366, 728), (0, 0, 1920, 1080), (420, 200), scale=1.5)       # physical window, logical screen
    assert where == "below" and y == round(50 / 1.5) + round(728 / 1.5) + 8


def test_closing_the_box_hides_it_for_that_step_and_the_next_step_shows_it_again(env):
    screen, engine, _svc, _o = env
    screen.poll()
    screen.panel.close_button.click()
    assert screen.panel.isHidden() and screen._dismissed_step == "s01"
    screen.poll()
    assert screen.panel.isHidden()                                     # still closed for this step
    engine.complete()
    screen.refresh()
    screen.poll()
    assert not screen.panel.isHidden() and "step 2" in screen.panel.header.text()


def test_the_box_can_be_turned_off_and_back_on_and_its_buttons_drive_the_session(env):
    screen, engine, _svc, _o = env
    screen.poll()
    screen.panel_box.setChecked(False)
    assert screen.panel.isHidden()
    screen.panel_box.setChecked(True)
    assert not screen.panel.isHidden()
    screen.panel.done_button.click()
    assert engine.current_step().id == "s02"
    screen.panel.skip_button.click()
    assert engine.current_step().id == "s03"


def test_the_highlight_follows_a_moved_window_and_is_cleared_by_a_resized_one(env):
    screen, _e, _svc, overlay = env
    screen.poll()
    g = screen.guide
    assert g.follow_window((0, 0, 1920, 1080)) == "same"
    first = overlay.marks[0].rect
    assert g.follow_window((30, 40, 1920, 1080)) == "moved"
    moved = overlay.marks[0].rect
    assert (moved.x - first.x, moved.y - first.y) == (30, 40) and overlay.covered == Rect(30, 40, 1920, 1080)
    assert g.follow_window((30, 40, 1000, 700)) == "resized" and overlay.marks == [] and overlay.covered == Rect(30, 40, 1000, 700)
    assert g.follow_window(None) == "lost" and g.follow_window((0, 0, 10, 10)) == "found"


def test_the_fast_timer_asks_for_a_new_look_when_the_window_is_resized(env):
    screen, _e, _svc, _o = env
    sizes = [(0, 0, 1920, 1080), (0, 0, 1000, 700)]
    screen.bridge.window_finder = lambda app: sizes[0]
    screen.poll()
    looks = []
    real = screen.poll
    screen.poll = lambda: looks.append(1) or real()
    screen._track()
    assert looks == []                                                 # nothing changed
    screen.bridge.window_finder = lambda app: sizes[1]
    screen._track()
    assert looks == [1]                                                # resized: look again at once


def test_closing_the_window_closes_the_overlay_and_the_box(env):
    screen, _e, _svc, overlay = env
    screen.poll()
    box = screen.panel
    screen.close_guides()
    assert overlay.closed and screen.panel is None and box.isHidden()


def test_the_guide_animates_the_mouse_and_keys_of_the_step_and_has_a_back_button(env):
    screen, engine, _svc, _o = env
    p = screen._ensure_panel()
    p.set_content("GuideWire · step 1 of 2", "Delete everything", [], "Press A then Delete", ("A", "Delete"), (("click", "right"), ("keys", "Ctrl+P"), ("drag", "left")))
    h = p.input_hint
    assert not h.isHidden() and h.label() == "Right click"
    for _ in range(h.HOLD_TICKS):
        h.advance()
    assert h.label() == "Press Ctrl + P"
    for _ in range(h.HOLD_TICKS):
        h.advance()
    assert h.label() == "Hold the left button and drag"
    for _ in range(h.HOLD_TICKS):
        h.advance()
    assert h.label() == "Right click"                          # it loops
    h.grab()                                                   # painting every kind of event does not raise
    for i in range(3):
        h.index = i
        h.grab()
    p.set_content("GuideWire", "x", [], "", (), ())
    assert h.isHidden() and not h.timer.isActive()
    engine.complete()
    screen.refresh()
    p.back_button.click()
    assert engine.position == 1
    screen.close()
