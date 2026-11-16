from pathlib import Path

import pytest

from app.db import Database
from app.guidance import UNAVAILABLE, GuidanceController, Snapshot, ui_target
from app.session_engine import SessionEngine
from app.step_editor import StepEditor
from shared.grounding import GroundingResult, Rect
from shared.step_record import Action, Step
from vision.service import Guidance

SAMPLE = "shared/examples/blender_cube_extrude.json"      # s01 mode+selection, s02 EDIT_MESH, s03 extrude tool (Extrude Region), s04 craft
OBJECT_WITH_MESH = {"mode": "OBJECT", "selection_types": ["MESH"]}


class FakeVision:
    def __init__(self, observed=None, guidance=None, boom=None):
        self.observed, self.guidance, self.boom = observed or {}, guidance, boom
        self.asked: list[str] = []

    def observe(self):
        if self.boom:
            raise self.boom
        return self.observed

    def ground(self, ui_element):
        self.asked.append(ui_element)
        return self.guidance


def ok(rect=Rect(100, 200, 80, 20), complete=True, ambiguous=False, matched="Extrude Region"):
    return Guidance(GroundingResult("ok", 140, 210), rect, complete, ambiguous, matched)


@pytest.fixture
def engine():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    yield e
    db.close()


def test_ui_target_is_the_first_named_element():
    s = Step(id="s1", order=1, goal="g", actions=[Action(verb="press_keys", keys=["Tab"]), Action(verb="click", ui_element="  Extrude Region ")])
    assert ui_target(s) == "Extrude Region"
    assert ui_target(Step(id="s2", order=2, goal="g", actions=[Action(verb="press_keys", keys=["Tab"])])) is None
    assert ui_target(Step(id="s3", order=3, goal="g")) is None


def test_the_engine_knows_its_application(engine):
    assert engine.app == "blender"


def test_available_only_for_blender_with_a_vision_service(engine):
    assert GuidanceController(engine, FakeVision()).available
    assert not GuidanceController(engine, None).available


def test_current_is_none_unless_a_step_is_active(engine):
    c = GuidanceController(engine, FakeVision())
    assert c.current() == ("s01", "Add > Mesh > Cube")
    for _ in range(4):
        engine.complete()
    assert c.current() is None


def test_screen_state_that_matches_completes_the_step(engine):
    c = GuidanceController(engine, FakeVision(OBJECT_WITH_MESH))
    out = c.apply(c.compute("s01", "Add > Mesh > Cube"))
    assert out.advanced and engine.position == 2 and "saw it on screen" in out.hint
    assert engine.db.session_steps(engine.session_id)[0]["status_by"] == "observed"


def test_state_that_does_not_match_points_at_the_target_instead(engine):
    v = FakeVision({"mode": "EDIT_MESH"}, ok(matched="Add", complete=False))
    c = GuidanceController(engine, v)
    out = c.apply(c.compute("s01", "Add > Mesh > Cube"))
    assert not out.advanced and engine.position == 1
    assert v.asked == ["Add > Mesh > Cube"] and len(out.marks) == 1 and out.marks[0].rect.contains(140, 210)
    assert "Open Add" in out.hint


def test_final_item_says_click_it_and_ambiguity_is_said(engine):
    c = GuidanceController(engine, FakeVision({}, ok(matched="Cube")))
    assert c.apply(c.compute("s01", "Add > Mesh > Cube")).hint == "Click Cube."
    c = GuidanceController(engine, FakeVision({}, ok(ambiguous=True, matched="Cube")))
    assert "Several places match" in c.apply(c.compute("s01", "Add > Mesh > Cube")).hint


def test_nothing_found_draws_nothing_and_says_so(engine):
    c = GuidanceController(engine, FakeVision({}, Guidance(GroundingResult("none", reason="model reported no element"))))
    out = c.apply(c.compute("s01", "Add > Mesh > Cube"))
    assert out.marks == [] and "Could not find" in out.hint
    c = GuidanceController(engine, FakeVision({}, Guidance(GroundingResult("none", reason="no visible window titled 'Blender'"))))
    assert "bring it to the front" in c.apply(c.compute("s01", "Add > Mesh > Cube")).hint


def test_a_step_with_no_target_only_observes(engine):
    v = FakeVision({"mode": "OBJECT"}, ok())
    c = GuidanceController(engine, v)
    out = c.apply(c.compute("s01", None))
    assert v.asked == [] and out.marks == [] and not out.advanced


def test_a_stale_snapshot_is_ignored(engine):
    c = GuidanceController(engine, FakeVision(OBJECT_WITH_MESH))
    snap = c.compute("s01", "Add > Mesh > Cube")
    engine.complete()                                          # the learner moved on while vision was reading
    out = c.apply(snap)
    assert not out.advanced and out.marks == [] and engine.position == 2


def test_a_snapshot_never_completes_a_step_it_was_not_computed_for(engine):
    c = GuidanceController(engine, FakeVision({"mode": "EDIT_MESH"}))
    engine.complete()
    out = c.apply(Snapshot("s01", {"mode": "EDIT_MESH"}))      # s01 snapshot while s02 is active
    assert engine.position == 2 and not out.advanced


def test_a_vision_failure_never_breaks_the_session(engine):
    c = GuidanceController(engine, FakeVision(boom=RuntimeError("no OCR")))
    out = c.apply(c.compute("s01", "Add > Mesh > Cube"))
    assert "no OCR" in out.hint and not out.stop and engine.position == 1


def test_a_missing_component_stops_further_attempts(engine):
    for boom in (ImportError("winrt"), NotImplementedError("needs Windows")):
        out = GuidanceController(engine, FakeVision(boom=boom)).apply(GuidanceController(engine, FakeVision(boom=boom)).compute("s01", "x"))
        assert out.stop
    assert UNAVAILABLE.split("{")[0] in out.hint


def test_craft_steps_are_never_completed_by_the_screen(engine):
    for _ in range(3):
        engine.complete()
    c = GuidanceController(engine, FakeVision(OBJECT_WITH_MESH))
    assert engine.current_step().id == "s04"
    assert not c.apply(c.compute("s04", None)).advanced and engine.position == 4


def test_other_applications_get_no_guidance(engine):
    engine.app = "maya"
    assert not GuidanceController(engine, FakeVision()).available


def test_sample_file_exists():
    assert Path(SAMPLE).exists()
