from pathlib import Path

import pytest

from app.db import Database
from app.session_engine import ACTIVE, FINISHED, NOT_STARTED, EngineError, SessionEngine
from app.step_editor import StepEditor

SAMPLE = Path("shared/examples/blender_cube_extrude.json")   # s01 mode+selection, s02 EDIT_MESH, s03 extrude tool, s04 craft


@pytest.fixture
def env():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    yield db, uid, tid
    db.close()


@pytest.fixture
def eng(env):
    db, uid, tid = env
    return SessionEngine.create(db, uid, tid)


def test_new_session_is_not_started(eng):
    assert eng.state == NOT_STARTED and eng.position is None and eng.current_step() is None
    assert eng.progress() == (0, 4)


def test_start_activates_the_first_step(eng):
    eng.start()
    assert eng.state == ACTIVE and eng.position == 1 and eng.current_step().id == "s01"
    with pytest.raises(EngineError):
        eng.start()


def test_complete_walks_through_and_finishes(eng):
    eng.start()
    for expected in (2, 3, 4):
        eng.complete()
        assert eng.position == expected
    eng.complete()
    assert eng.state == FINISHED and eng.position is None
    assert eng.statuses() == ["done"] * 4 and eng.progress() == (4, 4)
    assert eng.db.get_session(eng.session_id)["finished_at"]


def test_skip_counts_as_dealt_with(eng):
    eng.start()
    eng.skip()
    assert eng.statuses()[0] == "skipped" and eng.position == 2 and eng.progress() == (1, 4)


def test_back_redoes_the_previous_step(eng):
    eng.start()
    eng.complete()
    eng.back()
    assert eng.position == 1 and eng.statuses()[0] == "pending"
    with pytest.raises(EngineError, match="first step"):
        eng.back()


def test_actions_are_refused_in_the_wrong_state(eng):
    for action in (eng.complete, eng.skip, eng.back):
        with pytest.raises(EngineError, match="not_started"):
            action()
    eng.start()
    for _ in range(4):
        eng.complete()
    for action in (eng.complete, eng.skip, eng.back, eng.start):
        with pytest.raises(EngineError):
            action()


def test_progress_survives_closing_the_app(env):
    db, uid, tid = env
    e = SessionEngine.create(db, uid, tid)
    e.start()
    e.complete()
    again = SessionEngine.load(db, uid, e.session_id)
    assert again.state == ACTIVE and again.position == 2 and again.statuses()[:2] == ["done", "pending"]


def test_other_users_cannot_run_or_load_the_session(env):
    db, uid, tid = env
    other = db.add_user("b@x.com", b"h")
    with pytest.raises(EngineError):
        SessionEngine.create(db, other, tid)
    sid = SessionEngine.create(db, uid, tid).session_id
    with pytest.raises(EngineError):
        SessionEngine.load(db, other, sid)


def test_a_tutorial_without_steps_cannot_start(env):
    db, uid, _ = env
    tid = db.save_tutorial(uid, "Empty", StepEditor.from_json_file(SAMPLE).steps.model_copy(update={"steps": []}))
    e = SessionEngine.create(db, uid, tid)
    with pytest.raises(EngineError, match="no steps"):
        e.start()


def test_auto_check_completes_only_when_the_state_is_observed(eng):
    eng.start()
    assert not eng.auto_check({})                                   # nothing observed
    assert not eng.auto_check({"mode": "OBJECT"})                   # s01 also needs a MESH selected
    assert eng.position == 1
    assert eng.auto_check({"mode": "OBJECT", "selection_types": ["MESH"]})
    assert eng.position == 2 and eng.db.session_steps(eng.session_id)[0]["status_by"] == "observed"


def test_auto_check_never_completes_craft_or_uncheckable_steps(eng):
    eng.start()
    for _ in range(3):
        eng.complete()
    assert eng.current_step().id == "s04"
    assert not eng.auto_check({"mode": "OBJECT", "selection_types": ["MESH"]}) and eng.position == 4


def test_unknown_predicate_kind_is_not_auto_completed(env):
    from app.step_loader import load_steps
    db, uid, _ = env
    import json
    d = json.loads(SAMPLE.read_text(encoding="utf-8"))
    d["steps"][0]["expected_state"].append({"kind": "future_kind", "target": "joint", "value": 9})
    tid = db.save_tutorial(uid, "Future", load_steps(d))
    e = SessionEngine.create(db, uid, tid)
    e.start()
    assert not e.auto_check({"mode": "OBJECT", "selection_types": ["MESH"], "nodes": ["joint"] * 9})
    assert e.position == 1
