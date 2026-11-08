import json
import sqlite3
from pathlib import Path

import pytest

from app.db import Database
from shared.step_record import StepList

EXAMPLE = Path("shared/examples/blender_cube_extrude.json")


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


def _steps() -> StepList:
    return StepList.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))


def test_user_roundtrip_and_default_preferences(db):
    uid = db.add_user("A@x.com", b"hash", "Ayesha")
    assert db.get_user_by_email("a@x.com")["id"] == uid          # email is case-insensitive
    assert db.get_user(uid)["password_hash"] == b"hash"
    assert db.get_preferences(uid) == {}


def test_duplicate_email_is_rejected(db):
    db.add_user("a@x.com", b"h")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_user("A@X.COM", b"h2")
    assert db.conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1


def test_preferences_roundtrip(db):
    uid = db.add_user("a@x.com", b"h")
    db.set_preferences(uid, {"theme": "dark"})
    db.set_preferences(uid, {"theme": "light", "overlay": True})
    assert db.get_preferences(uid) == {"theme": "light", "overlay": True}


def test_tutorial_steps_roundtrip_in_order(db):
    uid = db.add_user("a@x.com", b"h")
    sl = _steps()
    tid = db.save_tutorial(uid, "Cube", sl)
    got = [s for _, s in db.get_steps(tid)]
    assert [s.model_dump(mode="json") for s in got] == [s.model_dump(mode="json") for s in sl.steps]


def test_saving_again_replaces_steps_and_keeps_the_tutorial(db):
    uid = db.add_user("a@x.com", b"h")
    sl = _steps()
    tid = db.save_tutorial(uid, "Cube", sl)
    sl.steps = sl.steps[:1]
    assert db.save_tutorial(uid, "Cube v2", sl, tutorial_id=tid) == tid
    assert len(db.get_steps(tid)) == 1
    assert db.list_tutorials(uid)[0]["title"] == "Cube v2"


def test_users_cannot_touch_each_others_tutorials(db):
    a, b = db.add_user("a@x.com", b"h"), db.add_user("b@x.com", b"h")
    tid = db.save_tutorial(a, "Cube", _steps())
    assert db.list_tutorials(b) == []
    assert db.delete_tutorial(b, tid) is False
    with pytest.raises(KeyError):
        db.save_tutorial(b, "x", _steps(), tutorial_id=tid)
    with pytest.raises(KeyError):
        db.start_session(b, tid)


def test_session_tracks_a_row_per_step(db):
    uid = db.add_user("a@x.com", b"h")
    tid = db.save_tutorial(uid, "Cube", _steps())
    sid = db.start_session(uid, tid)
    rows = db.session_steps(sid)
    assert len(rows) == len(db.get_steps(tid)) and {r["status"] for r in rows} == {"pending"}
    db.set_step_status(sid, rows[0]["step_id"], "done")
    assert db.session_steps(sid)[0]["status"] == "done"
    assert db.get_session(sid)["state"] == "not_started"


def test_deleting_a_tutorial_removes_its_steps_and_sessions(db):
    uid = db.add_user("a@x.com", b"h")
    tid = db.save_tutorial(uid, "Cube", _steps())
    sid = db.start_session(uid, tid)
    assert db.delete_tutorial(uid, tid)
    assert db.get_steps(tid) == [] and db.get_session(sid) is None


def test_failed_transaction_rolls_back(db):
    uid = db.add_user("a@x.com", b"h")
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            c.execute("INSERT INTO tutorial (user_id, title, created_at, updated_at) VALUES (?, 't', 'x', 'x')", (uid,))
            c.execute("INSERT INTO user (email, password_hash, created_at) VALUES ('a@x.com', x'00', 'x')")
    assert db.list_tutorials(uid) == []


def test_database_persists_to_a_file(tmp_path):
    p = tmp_path / "sub" / "g.sqlite"
    d = Database(p)
    uid = d.add_user("a@x.com", b"h")
    d.close()
    assert Database(p).get_user(uid)["email"] == "a@x.com"


def test_session_history_newest_first_with_progress(db):
    uid = db.add_user("a@x.com", b"h")
    other = db.add_user("b@x.com", b"h")
    tid = db.save_tutorial(uid, "Cube", _steps())
    s1 = db.start_session(uid, tid)
    s2 = db.start_session(uid, tid)
    db.set_step_status(s1, db.session_steps(s1)[0]["step_id"], "done")
    db.set_step_status(s1, db.session_steps(s1)[1]["step_id"], "skipped")
    rows = db.session_history(uid)
    assert [r["id"] for r in rows] == [s2, s1]
    assert rows[1]["dealt"] == 2 and rows[1]["total"] == 4 and rows[1]["title"] == "Cube" and rows[0]["dealt"] == 0
    assert db.session_history(other) == []
