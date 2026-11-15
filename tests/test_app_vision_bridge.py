"""The bridge between the session and vision: a fake vision service, a real session engine on an in-memory database. No screen, no Windows, no OCR."""
from dataclasses import dataclass
from pathlib import Path

import pytest

from app import vision_bridge as vb
from app.db import Database
from app.session_engine import SessionEngine
from app.step_editor import StepEditor
from shared.grounding import GroundingResult, Rect

SAMPLE = Path("shared/examples/blender_cube_extrude.json")      # s01 mode+selection, s02 EDIT_MESH, s03 extrude tool, s04 craft


@dataclass
class G:
    grounding: GroundingResult
    rect: Rect | None = None
    complete: bool = False
    ambiguous: bool = False


def found(x=100, y=50, w=80, h=20, complete=False):
    return G(GroundingResult("ok", x + w // 2, y + h // 2), Rect(x, y, w, h), complete)


class FakeService:
    def __init__(self, ground=None, observed=None, boom=None):
        self._ground, self._observed, self.boom = ground or found(), observed or {}, boom
        self.ground_calls, self.observe_calls = [], []

    def ground(self, ui_element):
        self.ground_calls.append(ui_element)
        if self.boom:
            raise self.boom
        return self._ground

    def observe(self, properties=None, attributes=None):
        self.observe_calls.append((properties, attributes))
        if self.boom:
            raise self.boom
        return dict(self._observed)


@pytest.fixture
def eng():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    yield e
    db.close()


def bridge_with(svc, **kw):
    return vb.VisionBridge(lambda app: svc, **kw)


def test_the_target_and_the_probe_paths_come_from_the_step(eng):
    from shared.step_record import Action, StatePredicate, Step
    step = Step(id="s9", order=9, goal="Rename the cube", actions=[Action(verb="open_menu", ui_element="  Add > Mesh > Cube  ")],
                expected_state=[StatePredicate(kind="property_equals", target="Cube.location.x", value=2.0), StatePredicate(kind="attribute_exists", target="Cube.my_prop"),
                                StatePredicate(kind="mode", target="EDIT_MESH")])
    assert vb.target_of(step) == "Add > Mesh > Cube"
    assert vb.needs_of(step) == (["Cube.location.x"], ["Cube.my_prop"])


def test_the_application_comes_from_the_tutorial(eng):
    assert vb.app_of(eng) == "blender"


def test_no_vision_installed_is_a_state_not_a_crash(eng):
    t = vb.VisionBridge(None).tick(eng)
    assert t.state == "unavailable" and "not set up" in t.message and not t.advanced
    assert not vb.VisionBridge(None).available


def test_a_factory_that_fails_says_why_once_and_does_not_retry(eng):
    calls = []

    def factory(app):
        calls.append(app)
        raise ImportError("No module named 'winrt'")
    b = vb.VisionBridge(factory)
    t = b.tick(eng)
    assert t.state == "unavailable" and "Windows OCR packages" in t.message and "pip install" in t.message
    b.tick(eng)
    assert calls == ["blender"]                                   # not retried every tick
    b.reset()
    b.tick(eng)
    assert calls == ["blender", "blender"]


def test_a_found_target_gives_a_rectangle_and_nothing_advances_when_the_state_is_not_met(eng):
    svc = FakeService(found(10, 20, 30, 40, complete=True), observed={"mode": "OBJECT", "selection_types": []})
    t = bridge_with(svc).tick(eng)
    assert t.state == "watching" and not t.advanced
    assert svc.observe_calls and eng.position == 1                 # observed, but the step did not move


def test_the_step_is_completed_only_when_the_application_shows_it_done(eng):
    eng.complete()                                                  # s01 done by hand; s02 expects EDIT_MESH
    assert eng.current_step().id == "s02"
    svc = FakeService(observed={"mode": "OBJECT_MODE_NOT_EDIT"})
    b = bridge_with(svc)
    assert not b.tick(eng).advanced and eng.current_step().id == "s02"
    svc._observed = {"mode": "EDIT_MESH"}
    t = b.tick(eng)
    assert t.advanced and t.state == "done_seen" and t.verdict == "met" and eng.current_step().id == "s03"
    assert eng.statuses()[1] == "done"


def test_auto_advance_can_be_switched_off_and_the_verdict_is_still_reported(eng):
    eng.complete()
    svc = FakeService(observed={"mode": "EDIT_MESH"})
    t = bridge_with(svc, auto_advance=False).tick(eng)
    assert not t.advanced and t.verdict == "met" and eng.current_step().id == "s02"


def test_an_unobservable_step_is_never_advanced(eng):
    eng.complete()
    t = bridge_with(FakeService(observed={})).tick(eng)            # vision could read nothing
    assert not t.advanced and eng.current_step().id == "s02"


def test_an_ambiguous_match_points_at_nothing(eng):
    g = found()
    g.ambiguous = True
    t = bridge_with(FakeService(g)).tick(eng)
    assert t.rect is None and t.ambiguous and "narrow down" in t.message


def test_a_missing_window_asks_the_learner_to_bring_the_application_forward(eng):
    g = G(GroundingResult("none", reason="no visible window titled 'Blender'"))
    t = bridge_with(FakeService(g)).tick(eng)
    assert t.state == "no_window" and "Open Blender in front" in t.message and not t.advanced


def test_a_vision_failure_during_a_tick_is_reported_and_the_session_is_untouched(eng):
    t = bridge_with(FakeService(boom=RuntimeError("capture failed"))).tick(eng)
    assert t.state == "error" and "RuntimeError" in t.message and "Done" in t.message and eng.position == 1


def test_no_active_step_is_idle(eng):
    while eng.current_step() is not None:
        eng.complete()
    t = bridge_with(FakeService()).tick(eng)
    assert t.state == "idle"


def test_the_real_service_factory_fails_with_words_when_vision_cannot_load(monkeypatch):
    import builtins
    real = builtins.__import__

    def deny(name, *a, **k):
        if name.startswith("vision"):
            raise ImportError("No module named 'winrt.windows.media.ocr'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", deny)
    with pytest.raises(ImportError):
        vb.default_service_factory("blender")
    assert "Windows OCR packages" in vb.explain(ImportError("No module named 'winrt'"))
    assert "Windows only" in vb.explain(OSError("not windows"))
