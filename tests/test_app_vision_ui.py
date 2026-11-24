"""Screen guidance in the session screen: the timer, the status line, the highlight, the "covering the application" warning. Offscreen Qt, a fake vision service and a fake overlay."""
import os
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")          # CI installs no Qt: the screen guide needs it

import vision_fakes as vf  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
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
    assert screen.watching and screen.timer.isActive() and screen.timer.interval() == screen.LOOK_ACTIVE_MS
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
    svc.observed = {"mode": "OBJECT"}
    screen.poll()
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


def test_the_keys_of_a_step_are_said_in_words_in_the_guide(env):
    screen, _e, _svc, _o = env
    p = screen._ensure_panel()
    p.set_content("GuideWire", "Delete everything", [], "", ("A", "Delete"))
    assert p.hint.text() == "Press A then Delete." and not p.hint.isHidden()
    p.set_content("GuideWire", "Delete everything", [], "Press A then Delete", ("A", "Delete"))
    assert p.hint.text() == "Press A then Delete"                 # already said: not said twice
    p.set_content("GuideWire", "Next", [], "", ())
    assert p.hint.isHidden()
    assert not hasattr(p, "input_hint") and not hasattr(p, "_key_labels")        # no mouse or key animation
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


def test_the_guide_is_words_only_in_the_apps_colours_and_has_a_back_button(env):
    from app.ui.style import current_palette
    screen, engine, _svc, _o = env
    p = screen._ensure_panel()
    p.set_content("GuideWire · step 1 of 2", "Delete everything", [], "Press A then Delete", ("A", "Delete"))
    assert p.goal.text() == "Delete everything"
    assert current_palette()["tile_hi"] in p.styleSheet() and current_palette()["accent"] in p.styleSheet()        # the same palette as every screen
    assert p.done_button.objectName() == "primary"
    engine.complete()
    screen.refresh()
    p.back_button.click()
    assert engine.position == 1
    screen.close()


def test_the_screen_is_looked_at_often_while_the_learner_works_and_rarely_while_they_read(env, monkeypatch):
    from vision import winplatform
    screen, _engine, _svc, _o = env
    screen.sync = False
    screen.show()
    screen.refresh()
    idle = {"s": 0.5}
    monkeypatch.setattr(winplatform, "idle_seconds", lambda: idle["s"])
    screen._pace()
    assert screen.timer.interval() == screen.LOOK_ACTIVE_MS
    idle["s"] = 30.0
    screen._pace()
    assert screen.timer.interval() == screen.LOOK_IDLE_MS and screen.LOOK_IDLE_MS > 3 * screen.LOOK_ACTIVE_MS // 2
    monkeypatch.setattr(winplatform, "idle_seconds", lambda: None)             # cannot be read: the pace stays as it was
    screen._pace()
    assert screen.timer.interval() == screen.LOOK_IDLE_MS
    screen.close()


def test_the_window_lookup_walks_every_window_only_now_and_then(monkeypatch):
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows only")
    from vision import winplatform
    calls = []
    real = winplatform.WindowInfo
    fake = real(hwnd=0, title="Blender", rect=winplatform.Rect(0, 0, 10, 10), minimized=False, pid=1, exe="blender.exe")
    monkeypatch.setattr(winplatform, "find_window", lambda *a, **k: calls.append(1) or fake)
    winplatform._FOUND.clear()
    assert winplatform.find_window_cached("Blender", ("blender",)) is fake
    winplatform.find_window_cached("Blender", ("blender",))               # hwnd 0 is not a real window, so this one walks again: the walk is only skipped for a window that is still there
    assert len(calls) >= 1
    winplatform._FOUND.clear()


# ---- pause, going back, the list of all steps, prerequisites
def _at_s02_in_edit_mode(env):
    """s02 ("Enter Edit Mode") ends in EDIT_MESH; the fake application is already there."""
    screen, engine, svc, overlay = env
    engine.complete()
    screen.refresh()
    svc.observed = {"mode": "OBJECT"}
    screen.poll()                                                     # the learner is seen NOT done first ...
    svc.observed = {"mode": "EDIT_MESH"}                              # ... then does it
    return screen, engine, svc, overlay


def test_pause_holds_the_step_even_when_the_application_shows_it_done(env):
    screen, engine, svc, overlay = _at_s02_in_edit_mode(env)
    screen.pause_button.click()
    assert screen.paused and screen.pause_button.text() == "Resume" and "Paused" in screen.watch_label.text()
    screen.poll()
    assert engine.current_step().id == "s02" and overlay.shown == 0 and not screen.looking       # nothing was looked at, drawn or completed
    screen.pause_button.click()
    assert not screen.paused and screen.pause_button.text() == "Pause"
    screen.poll()
    assert engine.current_step().id == "s03"                                                    # watching again: the step it saw done completes


def test_a_look_that_was_in_flight_when_the_learner_paused_completes_nothing(env):
    screen, engine, svc, _o = _at_s02_in_edit_mode(env)
    step = engine.current_step()
    look = screen.bridge.look(step, "blender")                                                  # the screen was read ...
    screen.toggle_pause()                                                                       # ... and then the learner paused
    screen._busy = True
    screen._looked(look, step.id)
    assert engine.current_step().id == "s02" and not screen._busy


def test_previous_step_holds_there_instead_of_being_completed_again_at_once(env):
    screen, engine, svc, _o = _at_s02_in_edit_mode(env)
    screen.poll()
    assert engine.current_step().id == "s03"
    svc.observed = {"mode": "EDIT_MESH"}                                                        # still in Edit Mode: s02's own result holds right now
    screen.prev_button.click()
    assert engine.current_step().id == "s02" and screen.paused and "paused" in screen.status.text().lower()
    for _ in range(3):
        screen.poll()
    assert engine.current_step().id == "s02"                                                    # the learner can look at it as long as they like
    assert "Step 2" in screen.step_text.text() and "(paused)" in screen.step_pill.text()
    screen.pause_button.click()
    screen.poll()
    assert engine.current_step().id == "s02" and "already looks done" in screen.watch_label.text()   # Resume: true before the visit began is not evidence (audit S-1)


def test_done_and_skip_end_a_pause_because_the_learner_is_moving_on(env):
    screen, engine, svc, _o = _at_s02_in_edit_mode(env)
    screen.toggle_pause()
    screen.done_button.click()
    assert not screen.paused and engine.current_step().id == "s03"
    screen.toggle_pause()
    screen.skip_button.click()
    assert not screen.paused


def test_the_small_guide_has_a_pause_button_that_does_the_same(env):
    screen, engine, svc, _o = _at_s02_in_edit_mode(env)
    svc.observed = {"mode": "OBJECT"}
    screen.poll()
    p = screen.panel
    assert p is not None and p.pause_button.text() == "Pause"
    p.pause_button.click()
    assert screen.paused and screen.panel.pause_button.text() == "Resume" and "Paused" in screen.panel.hint.text()
    p.toggle_minimized()
    assert p.pause_button.isHidden()                                                            # the minimized tab stays small
    p.toggle_minimized()
    p.pause_button.click()
    assert not screen.paused


def test_the_list_shows_every_step_and_picks_out_the_one_you_are_on(env):
    screen, engine, svc, _o = env
    rows = screen.steps_list.rows
    assert len(rows) == len(engine.steps) and all(r.text.text().startswith(f"{i}. ") for i, r in enumerate(rows, start=1))
    assert screen.steps_list.states()[0] == "current" and set(screen.steps_list.states()[1:]) == {"pending"}
    screen.done_button.click()
    screen.skip_button.click()
    st = screen.steps_list.states()
    assert st[:3] == ["done", "skipped", "current"] and rows[0].word.text() == "Done" and rows[1].word.text() == "Skipped" and rows[2].word.text() == "Now"      # a word as well as a colour
    screen.prev_button.click()
    assert screen.steps_list.states()[2] == "pending" and screen.steps_list.states()[1] == "current"


def test_clicking_a_step_only_looks_at_it_and_go_to_moves_the_session(env):
    screen, engine, svc, _o = env
    for _ in range(3):
        engine.complete()
    screen.refresh()
    assert engine.position == 4
    screen.steps_list.rows[0].clicked.emit(1)                                                    # what a click on the row does
    assert engine.position == 4 and screen.viewing == 1
    assert "Step 1" in screen.step_text.text() and "not your current step" in screen.step_pill.text() and "marked this step done" in screen.detail.text()
    assert not screen.goto_button.isHidden() and not screen.unview_button.isHidden() and screen.steps_list.rows[0].property("viewing") is True
    screen.unview_button.click()
    assert screen.viewing is None and "Step 4" in screen.step_text.text()
    screen._view(2)
    screen.goto_button.click()
    assert engine.position == 2 and screen.viewing is None and screen.paused                    # going back holds there, like Previous step
    assert engine.statuses()[1:4] == ["pending", "pending", "pending"] and engine.statuses()[0] == "done"


def test_a_step_shows_how_to_do_it_and_how_to_tell_it_worked_but_not_the_editors_notes(env):
    from shared.step_record import HowTo
    screen, engine, svc, _o = env
    step = engine.steps[0][1].model_copy(update={"how_to": [HowTo(text="Open the Add menu", support="said")], "check": [HowTo(text="A cube is in the scene", support="shown")],
                                                 "flags": ["expected/start state (ARMATURE) derived from the knowledge base (blender.add_bones), not read from the tutorial"]})
    text = screen._detail_for(step)
    assert "How to do it" in text and "Open the Add menu" in text and "How you can tell it worked" in text and "A cube is in the scene" in text
    assert "Notes" not in text and "knowledge base" not in text and "vocabulary" not in text


def test_a_long_video_title_wraps_and_cannot_make_the_page_wider(env):
    screen, engine, svc, _o = env
    short = screen.scroll.widget().minimumSizeHint().width()
    screen.title.setText("Session: " + "How to Rig a Leg with Inverse Kinematics in Blender " * 6)
    assert screen.title.wordWrap() and screen.title.minimumSizeHint().width() < 300
    assert screen.scroll.widget().minimumSizeHint().width() == short                            # the page needs exactly what it needed with a short title


def test_a_page_wider_than_the_window_can_still_be_scrolled_sideways(env):
    screen, engine, svc, _o = env
    assert screen.scroll.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_the_list_of_steps_sits_beside_the_tiles_on_a_wide_window_and_below_them_on_a_narrow_one(env):
    screen, engine, svc, _o = env
    screen.resize(1200, 700)
    screen.show()
    assert not screen._narrow and screen._grid.getItemPosition(screen._grid.indexOf(screen._steps_tile))[1] == 2
    screen.resize(700, 700)
    assert screen._narrow and screen._grid.getItemPosition(screen._grid.indexOf(screen._steps_tile))[:2] == (5, 0)
    screen.resize(1200, 700)
    assert not screen._narrow
    screen.close()


@pytest.fixture
def leg_session():
    """The real leg-rigging tutorial: it starts with a leg mesh that is already modelled."""
    import json

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_loader import load_steps
    from app.ui.screens import SessionScreen
    qapp = QApplication.instance() or QApplication([])
    db = Database(":memory:")
    uid = db.add_user("p@x.com", b"h")
    steps = load_steps(json.loads(Path("demo/data/blender_leg_ik_PctSMB-RGsM.json").read_text(encoding="utf-8")))
    tid = db.save_tutorial(uid, steps.title or "Leg", steps, source_type="youtube")
    engine = SessionEngine.create(db, uid, tid)
    svc = FakeService()
    screen = SessionScreen()
    screen.sync = True
    screen.guide = ScreenGuide(lambda: FakeOverlay())
    screen.set_bridge(vb.VisionBridge(lambda app: svc, window_finder=lambda app: (0, 0, 1920, 1080)))
    screen.load(engine)
    yield screen, engine, svc
    screen.timer.stop()
    db.close()
    del qapp


def test_the_session_says_what_the_tutorial_assumes_before_it_starts(leg_session):
    screen, engine, _svc = leg_session
    assert engine.state == "not_started" and any("leg mesh" in p.text for p in screen.prereqs)
    assert screen.prereq_tile.isVisibleTo(screen) and "leg mesh" in screen.prereq_label.text() and "assumes" in screen.step_text.text()
    assert "Session: " in screen.title.text()
    screen.start_button.click()
    assert not screen.prereq_tile.isVisibleTo(screen) and screen.prereq_button.isVisibleTo(screen)      # out of the way once started, one click to read it again
    screen.prereq_button.click()
    assert screen.prereq_tile.isVisibleTo(screen)


def test_a_scene_without_a_mesh_is_said_when_the_application_reports_one(leg_session):
    screen, engine, svc = leg_session
    screen.start_button.click()
    svc.observed = {"mode": "OBJECT", "nodes": ["ARMATURE"]}                                      # the application lists what is in the scene: no mesh
    screen.poll()
    assert screen.prereq_missing and screen.prereq_tile.isVisibleTo(screen) and "did not see" in screen.prereq_label.text()
    assert engine.state == "active"                                                              # said, never enforced


def test_a_scene_with_a_mesh_or_one_that_cannot_be_read_gives_no_warning(leg_session):
    screen, engine, svc = leg_session
    screen.start_button.click()
    svc.observed = {"mode": "OBJECT"}                                                            # no list of nodes (no add-on): silence is not a warning
    screen.poll()
    assert not screen.prereq_missing and not screen._prereq_checked
    svc.observed = {"mode": "OBJECT", "nodes": ["MESH", "ARMATURE"]}
    screen.poll()
    assert screen._prereq_checked and not screen.prereq_missing


def test_the_small_guide_opens_the_details_by_default_and_does_not_say_a_one_line_step_twice():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ui.screen_guide import InstructionPanel
    qapp = QApplication.instance() or QApplication([])
    p = InstructionPanel()
    p.set_content("GuideWire · step 2 of 5", "Add a bone", ["Click Add.", "Choose Armature > Single Bone."], "")
    assert p.lines.isHidden() is False and "Armature > Single Bone" in p.lines.text() and p.more_button.text() == "Details ▴"
    p.set_content("GuideWire · step 3 of 5", "Select Armature > Single Bone.", ["Select Armature > Single Bone"], "")
    assert p.lines.text() == "" and p.more_button.isHidden()
    p.set_content("GuideWire · step 4 of 5", "Add a bone", ["Click Add.", "Choose it."], "")
    p._toggle_details()
    p.set_content("GuideWire · step 4 of 5", "Add a bone", ["Click Add.", "Choose it."], "a new hint")
    assert p.lines.isHidden()                                       # folding them is remembered when the hint changes
    del qapp


def test_a_different_phase_must_be_seen_twice_before_the_text_under_the_heading_changes(env):
    """2026-11-23: on a step like "Switch to Pose Mode" the message flipped between "Click the mode dropdown...", "Open it first" and "Looking for it" as single looks missed a word, too fast to read."""
    from types import SimpleNamespace as NS
    screen = env[0]

    def view(phase, message, rect=None, advanced=False, problem=None):
        return screen._steady_view(NS(message=message, hint=message, keys=(), rect=rect, advanced=advanced), NS(phase=phase, problem=problem))
    assert view("visible", "Click Pose Mode", (1, 2, 3, 4))[0] == "Click Pose Mode"               # the first look is shown at once
    assert view("visible", "Click Pose Mode now", (5, 6, 3, 4))[0] == "Click Pose Mode now"        # the same phase updates at once: the box follows a moving window
    assert view("locating", "Looking for it", None) == ("Click Pose Mode now", "Click Pose Mode now", (), (5, 6, 3, 4))   # one look of another phase: what was shown stays, box included
    assert view("locating", "Looking for it", None)[0] == "Looking for it"                         # the second look in a row: it replaces it
    assert view("visible", "Click Pose Mode", (1, 2, 3, 4))[0] == "Looking for it"
    assert view("visible", "Done", None, advanced=True)[0] == "Done"                               # a finished step is shown at once
    assert view("", "Open Blender", None, problem="no window")[0] == "Open Blender"                # no window to look at: said at once


def test_the_small_guide_writes_where_and_what_to_do_now_and_keeps_how_you_can_tell_it_worked_closed_until_opened():
    """2026-11-24, learner request: the text under the heading flipped between variants. The route ("Add > Armature") is written once and stays; the line under it says what to do now. The check lines are
    there but closed, and opening them is remembered."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ui.screen_guide import InstructionPanel
    qapp = QApplication.instance() or QApplication([])
    p = InstructionPanel()
    check = ["The foot does not move: that is expected.", "The Armature object now shows in the Outliner."]
    p.set_content("GuideWire · step 1 of 5", "Add a bone", ["Click Add.", "Choose Armature."], "Click Add, then Armature", route="Add > Armature", check=check)
    assert p.route.text() == "Where: Add > Armature" and not p.route.isHidden() and "Click Add" in p.hint.text()
    p.set_content("GuideWire · step 1 of 5", "Add a bone", ["Click Add.", "Choose Armature."], "Click Armature", route="Add > Armature", check=check)
    assert p.route.text() == "Where: Add > Armature" and p.hint.text() == "Click Armature"      # the route did not change while the step went on
    assert not p.check_button.isHidden() and p.check_lines.isHidden() and "▾" in p.check_button.text() and "expected" in p.check_lines.text()
    p._toggle_check()
    assert not p.check_lines.isHidden() and "▴" in p.check_button.text()
    p.set_content("GuideWire · step 1 of 5", "Add a bone", ["Click Add."], "Click Armature", route="Add > Armature", check=check)
    assert not p.check_lines.isHidden()                                                         # opened once, stays open
    p.set_content("GuideWire · step 2 of 5", "Switch to Edit Mode", [], "", route="Switch to Edit Mode", check=[])
    assert p.route.isHidden() and p.check_button.isHidden()                                     # nothing to say twice, nothing to check
    del qapp
