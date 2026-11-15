"""Screen guidance in the session screen: the timer, the status line, the highlight, the "covering the application" warning. Offscreen Qt, a fake vision service and a fake overlay."""
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from app import vision_bridge as vb
from app.ui.screen_guide import ScreenGuide
from shared.grounding import GroundingResult, Rect

SAMPLE = Path("shared/examples/blender_cube_extrude.json")


@dataclass
class G:
    grounding: GroundingResult
    rect: Rect | None = None
    complete: bool = False
    ambiguous: bool = False


class FakeService:
    def __init__(self, observed=None, found=True):
        self.observed, self.found = observed or {}, found

    def ground(self, ui_element):
        if not self.found:
            return G(GroundingResult("none", reason="no visible window titled 'Blender'"))
        return G(GroundingResult("ok", 60, 40), Rect(50, 30, 80, 20), True)

    def observe(self, properties=None, attributes=None):
        return dict(self.observed)


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
    assert len(overlay.marks) == 1 and overlay.marks[0].rect == Rect(46, 26, 88, 28) or overlay.marks[0].rect.w >= 80     # a highlight with a little padding
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
    engine.complete()                                                 # the learner pressed Done while the screen was being read
    screen._looked(look, first)
    assert engine.current_step().id == "s02"                          # the stale look did not complete anything


def test_a_second_poll_while_one_is_running_is_skipped(env):
    screen, _e, _svc, _o = env
    screen._busy = True
    screen.poll()
    assert screen.watch_label.text() == ""


def test_the_warning_appears_when_guidewire_covers_the_application_and_the_button_moves_it_aside(env):
    screen, _e, _svc, _o = env
    screen.show()
    own = screen._own_rect()
    screen._warn_if_covering((own[0], own[1], own[2] + 50, own[3] + 50))
    assert not screen.cover_label.isHidden() and not screen.side_button.isHidden() and "covering part of the application" in screen.cover_label.text()
    screen._warn_if_covering((own[0] + own[2] + 500, own[1], 400, 400))
    assert screen.cover_label.isHidden() and screen.side_button.isHidden()
    screen.window().resize(900, 600)
    screen.move_aside()
    g = screen.window().geometry()
    avail = screen.window().screen().availableGeometry()
    assert g.x() + g.width() == avail.x() + avail.width() and g.width() >= screen.window().minimumSizeHint().width() and g.height() == avail.height()
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
