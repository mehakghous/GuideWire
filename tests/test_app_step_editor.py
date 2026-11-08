from pathlib import Path

import pytest

from app.db import Database
from app.step_editor import EditError, StepEditor

SAMPLE = Path("shared/examples/blender_cube_extrude.json")


@pytest.fixture
def ed():
    return StepEditor.from_json_file(SAMPLE)


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


def ids(e):
    return [s.id for s in e.steps.steps]


def orders(e):
    return [s.order for s in e.steps.steps]


def test_loads_the_sample_and_is_not_dirty(ed):
    assert len(ed) == 4 and not ed.dirty and orders(ed) == [1, 2, 3, 4]


def test_edit_text_marks_the_step_reviewed(ed):
    ed.steps.steps[1].review_status = "drafted_automatically"
    ed.edit_goal("s02", "  Press Tab to enter Edit Mode ")
    assert ed.steps.steps[1].goal == "Press Tab to enter Edit Mode"
    assert ed.steps.steps[1].review_status == "reviewed" and ed.dirty


def test_unchanged_text_is_not_a_change(ed):
    ed.edit_goal("s01", ed.steps.steps[0].goal)
    assert not ed.dirty


def test_empty_text_is_refused(ed):
    with pytest.raises(EditError):
        ed.edit_goal("s01", "   ")
    with pytest.raises(EditError):
        ed.add("")
    assert ed.steps.steps[0].goal == "Add a cube to the scene"


def test_move_renumbers_and_stops_at_the_ends(ed):
    ed.move("s03", -1)
    assert ids(ed) == ["s01", "s03", "s02", "s04"] and orders(ed) == [1, 2, 3, 4]
    ed.move("s01", -1)
    assert ids(ed)[0] == "s01"
    ed.move("s04", 5)
    assert ids(ed)[-1] == "s04"


def test_delete_renumbers_and_cleans_depends_on(ed):
    ed.steps.steps[2].depends_on = ["s02", "s01"]
    ed.delete("s02")
    assert ids(ed) == ["s01", "s03", "s04"] and orders(ed) == [1, 2, 3]
    assert ed.steps.steps[1].depends_on == ["s01"]


def test_add_after_a_step_and_at_the_end(ed):
    a = ed.add("Rotate the cube", after="s01")
    b = ed.add("Save the file")
    assert ids(ed) == ["s01", a, "s02", "s03", "s04", b] and orders(ed) == [1, 2, 3, 4, 5, 6]
    assert ed.steps.steps[1].review_status == "reviewed" and ed.steps.steps[1].provenance == "user_text"


def test_new_ids_are_never_reused_after_a_delete(ed):
    ed.delete("s04")
    assert ed.add("Another step") == "s05"


def test_unknown_step_id_is_an_error(ed):
    with pytest.raises(EditError):
        ed.move("nope", 1)


def test_save_creates_then_updates_the_same_tutorial(ed, db):
    uid = db.add_user("a@x.com", b"h")
    tid = ed.save(db, uid)
    assert not ed.dirty and len(db.get_steps(tid)) == 4
    ed.delete("s04")
    ed.add("Save the file")
    assert ed.save(db, uid) == tid
    assert [s.goal for _, s in db.get_steps(tid)][-1] == "Save the file" and len(db.list_tutorials(uid)) == 1


def test_open_from_the_database_roundtrips(ed, db):
    uid = db.add_user("a@x.com", b"h")
    tid = ed.save(db, uid)
    again = StepEditor.from_db(db, uid, tid)
    assert again.goals() == ed.goals() and again.tutorial_id == tid


def test_cannot_open_someone_elses_tutorial(ed, db):
    a, b = db.add_user("a@x.com", b"h"), db.add_user("b@x.com", b"h")
    tid = ed.save(db, a)
    with pytest.raises(KeyError):
        StepEditor.from_db(db, b, tid)


def test_empty_list_cannot_be_saved(ed, db):
    uid = db.add_user("a@x.com", b"h")
    for sid in ids(ed):
        ed.delete(sid)
    with pytest.raises(EditError, match="at least one"):
        ed.save(db, uid)


def test_the_loaded_list_is_a_copy(ed):
    original = StepEditor.from_json_file(SAMPLE)
    ed.delete("s01")
    assert len(original) == 4
