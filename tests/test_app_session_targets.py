"""The session engine gives a Blender tutorial's actions their resolved targets on load, and step 9 of the armature tutorial no longer completes the moment it begins."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.session_engine import SessionEngine
from app.step_editor import StepEditor

ARMATURE = Path("demo/data/blender_armature_EBgHRd5tJfE.json")


@pytest.fixture
def eng():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(ARMATURE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    yield e
    db.close()


def test_a_loaded_session_has_resolved_targets_but_the_stored_steps_do_not(eng):
    s6 = eng.steps[5][1]
    t = s6.actions[0].target
    assert (t.kind, t.id, t.mode) == ("tool", "builtin.loop_cut", "EDIT_MESH")
    stored = eng.db.get_steps(eng.db.get_session(eng.session_id)["tutorial_id"])[5][1]
    assert stored.actions[0].target is None                                  # resolved on load, never written back
    assert [a.ui_element for a in s6.actions] == [a.ui_element for a in stored.actions]


def _go_to(eng, n):
    eng.start()
    while eng.position < n:
        eng.complete()


def test_step_9_does_not_complete_just_because_an_armature_exists(eng):
    _go_to(eng, 9)
    assert eng.current_step().id == "s09"
    seen = {"probe": True, "nodes": ["ARMATURE", "MESH"], "node_counts": {"ARMATURE": 1, "MESH": 1}, "mode": "OBJECT"}
    assert not eng.auto_check(seen) and eng.position == 9                    # was: advanced the moment the step began
    assert not eng.auto_check(seen, entry=seen) and eng.position == 9        # nothing was added since the step began
    more = {**seen, "nodes": ["ARMATURE", "MESH"], "node_counts": {"ARMATURE": 2, "MESH": 1}}
    assert eng.auto_check(more, entry=seen) and eng.position == 10          # a second armature appeared: the action happened


def test_the_subdivide_step_is_not_completed_by_the_bone_that_already_exists(eng):
    """Step 14 ("Subdivide single bone into bone chain") has `node_exists BONE` as its result and does NOT list it as a start state. The single bone from the step before made it true already, so the
    step used to complete itself the moment it began and the learner never saw it."""
    _go_to(eng, 14)
    step = eng.current_step()
    assert step.id == "s14" and "ubdivide" in step.goal
    assert [(p.kind, p.target) for p in step.expected_state] == [("node_exists", "BONE")]
    assert not [p for p in step.start_state if p.kind == "node_exists"]      # the case the old rule missed
    entry = {"probe": True, "mode": "EDIT_ARMATURE", "nodes": ["ARMATURE", "BONE", "MESH"], "node_counts": {"ARMATURE": 1, "BONE": 1, "MESH": 1}}
    assert not eng.auto_check(entry, entry=entry) and eng.position == 14    # nothing done yet: the step stays
    assert not eng.auto_check({**entry, "node_counts": {"ARMATURE": 1, "BONE": 1, "MESH": 1}}, entry=entry) and eng.position == 14
    done = {**entry, "node_counts": {"ARMATURE": 1, "BONE": 11, "MESH": 1}}
    assert eng.auto_check(done, entry=entry) and eng.position == 15         # bones were added: the action happened


def test_the_subdivide_step_waits_for_the_learner_when_only_the_screen_is_read(eng):
    """No node counts (no add-on): the step cannot be told apart from "not done", so it is left to the learner's Done rather than skipped."""
    _go_to(eng, 14)
    screen_only = {"mode": "EDIT_ARMATURE", "nodes": ["ARMATURE", "BONE", "MESH"]}
    assert not eng.auto_check(screen_only, entry=screen_only) and eng.position == 14
