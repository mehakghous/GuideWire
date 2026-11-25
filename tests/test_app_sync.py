"""Offline-first sync, with a fake online service that behaves like the Supabase table (server-stamped arrival times, last write wins)."""
from pathlib import Path

import pytest

from app.cloud import CloudAuthError, CloudSession, CloudUnavailable
from app.db import Database
from app.session_engine import SessionEngine
from app.step_editor import StepEditor
from app.sync import SyncService, norm

SAMPLE = Path("shared/examples/blender_cube_extrude.json")


class FakeCloud:
    configured = True

    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.clock = 0
        self.online = True
        self.expire_token = False
        self.pushes = 0

    def _check(self, session):
        if not self.online:
            raise CloudUnavailable("offline")
        if self.expire_token and session.access_token == "old":
            raise CloudAuthError("expired")

    def push_items(self, session, items):
        self._check(session)
        self.pushes += 1
        for i in items:
            self.clock += 1
            self.rows[(session.user_id, i["kind"], i["id"])] = {**i, "synced_at": f"2026-11-23T10:00:{self.clock:02d}+00:00"}

    def fetch_items(self, session, since):
        self._check(session)
        return [dict(r) for k, r in sorted(self.rows.items(), key=lambda kv: kv[1]["synced_at"]) if k[0] == session.user_id and (since is None or r["synced_at"] > since)]

    def refresh(self, session):
        return CloudSession(session.user_id, session.email, session.display_name, "new", "r")


def device(tmp_path, name):
    db = Database(tmp_path / f"{name}.sqlite")
    uid = db.add_user("a@x.com", b"h")
    return db, uid


@pytest.fixture
def cloud():
    return FakeCloud()


@pytest.fixture
def sess():
    return CloudSession("u1", "a@x.com", "A", "tok", "ref")


def titles(db, uid):
    return sorted(r["title"] for r in db.list_tutorials(uid))


# ---------------------------------------------------------------- what is noted and what is sent
def test_changes_are_noted_when_they_are_made(tmp_path):
    db, uid = device(tmp_path, "a")
    assert db.pending_changes(uid) == []
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    db.set_preferences(uid, {"theme": "dark"})
    kinds = sorted((r["kind"], r["op"]) for r in db.pending_changes(uid))
    assert kinds == [("pref", "upsert"), ("session", "upsert"), ("tutorial", "upsert")]       # one note per thing, however often it changed


def test_a_sync_sends_everything_and_clears_the_notes(tmp_path, cloud, sess):
    db, uid = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(db, uid)
    svc = SyncService(db, cloud, uid)
    assert svc.pending == 1
    report = svc.sync_once(sess)
    assert report.ok and report.pushed == 1 and svc.pending == 0
    (row,) = cloud.rows.values()
    assert row["kind"] == "tutorial" and len(row["data"]["steps"]) == 4 and row["deleted"] is False


def test_offline_keeps_every_note_and_the_next_sync_sends_it(tmp_path, cloud, sess):
    db, uid = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(db, uid)
    svc = SyncService(db, cloud, uid)
    cloud.online = False
    report = svc.sync_once(sess)
    assert report.offline and not report.ok and svc.pending == 1 and cloud.rows == {}
    cloud.online = True
    assert svc.sync_once(sess).pushed == 1 and svc.pending == 0 and len(cloud.rows) == 1


def test_a_change_made_while_a_sync_is_running_stays_queued(tmp_path, cloud, sess):
    db, uid = device(tmp_path, "a")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    svc = SyncService(db, cloud, uid)
    plan = svc.plan()
    result = svc.network(sess, plan)
    import time
    time.sleep(1.1)                                              # the notes carry whole-second times
    db.conn.execute("UPDATE tutorial SET title = 'Renamed', updated_at = ? WHERE id = ?", (norm("2030-01-01T00:00:00Z"), tid))
    db.mark_changed(uid, "tutorial", db.conn.execute("SELECT sync_id FROM tutorial").fetchone()["sync_id"])
    svc.finish(plan, result)
    assert svc.pending == 1                                      # the later edit was not sent by that sync: it is still waiting


def test_an_expired_sign_in_is_refreshed_once_and_a_dead_one_asks_to_log_in_again(tmp_path, cloud):
    db, uid = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(db, uid)
    svc = SyncService(db, cloud, uid)
    cloud.expire_token = True
    old = CloudSession("u1", "a@x.com", "A", "old", "ref")
    plan = svc.plan()
    result = svc.network(old, plan)
    assert result.ok and result.session is not None and result.session.access_token == "new"

    class Dead(FakeCloud):
        def refresh(self, session):
            raise CloudAuthError("gone")
    dead = Dead()
    dead.expire_token = True
    svc2 = SyncService(db, dead, uid)
    assert svc2.sync_once(old).signed_out


def test_a_failing_cloud_never_raises_into_the_app(tmp_path, sess):
    class Broken(FakeCloud):
        def push_items(self, session, items):
            raise RuntimeError("boom")
    db, uid = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(db, uid)
    report = SyncService(db, Broken(), uid).sync_once(sess)
    assert report.error.startswith("Sync failed") and "boom" not in report.error and SyncService(db, Broken(), uid).pending == 1


# ---------------------------------------------------------------- two devices
def test_a_second_device_receives_tutorials_sessions_and_preferences(tmp_path, cloud, sess):
    a, ua = device(tmp_path, "a")
    tid = StepEditor.from_json_file(SAMPLE).save(a, ua)
    e = SessionEngine.create(a, ua, tid)
    e.start()
    e.complete()
    e.pause()
    a.set_preferences(ua, {"theme": "dark"})
    SyncService(a, cloud, ua).sync_once(sess)

    b, ub = device(tmp_path, "b")
    rep = SyncService(b, cloud, ub).sync_once(sess)
    assert rep.pulled == 3 and titles(b, ub) == titles(a, ua)
    mine = SessionEngine.resume_or_create(b, ub, b.list_tutorials(ub)[0]["id"])
    assert mine.paused_at == 2 and mine.progress() == (1, 4) and mine.statuses()[0] == "done"
    assert b.get_preferences(ub) == {"theme": "dark"}
    assert SyncService(b, cloud, ub).pending == 0                 # what came in is not sent back as if it were new


def test_the_newest_edit_wins_and_an_older_one_does_not_overwrite(tmp_path, cloud, sess):
    a, ua = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(a, ua)
    SyncService(a, cloud, ua).sync_once(sess)
    b, ub = device(tmp_path, "b")
    SyncService(b, cloud, ub).sync_once(sess)
    bt = b.list_tutorials(ub)[0]
    b.conn.execute("UPDATE tutorial SET title = 'Edited on B', updated_at = ? WHERE id = ?", (norm("2031-01-01T00:00:00Z"), bt["id"]))
    b.mark_changed(ub, "tutorial", bt["sync_id"])
    SyncService(b, cloud, ub).sync_once(sess)
    SyncService(a, cloud, ua).sync_once(sess)
    assert titles(a, ua) == ["Edited on B"]

    at = a.list_tutorials(ua)[0]                                  # now A makes an OLDER edit (clock behind): it must not win
    a.conn.execute("UPDATE tutorial SET title = 'Old edit on A', updated_at = ? WHERE id = ?", (norm("2020-01-01T00:00:00Z"), at["id"]))
    a.mark_changed(ua, "tutorial", at["sync_id"])
    SyncService(a, cloud, ua).sync_once(sess)
    SyncService(b, cloud, ub).sync_once(sess)
    assert titles(b, ub) == ["Edited on B"]


def test_a_delete_travels_and_removes_the_tutorial_and_its_sessions_elsewhere(tmp_path, cloud, sess):
    a, ua = device(tmp_path, "a")
    tid = StepEditor.from_json_file(SAMPLE).save(a, ua)
    SessionEngine.create(a, ua, tid).start()
    SyncService(a, cloud, ua).sync_once(sess)
    b, ub = device(tmp_path, "b")
    SyncService(b, cloud, ub).sync_once(sess)
    assert titles(b, ub) and b.list_sessions(ub)
    a.delete_tutorial(ua, tid)
    SyncService(a, cloud, ua).sync_once(sess)
    SyncService(b, cloud, ub).sync_once(sess)
    assert titles(b, ub) == [] and b.list_sessions(ub) == []


def test_one_bad_row_does_not_stop_the_rest(tmp_path, cloud, sess):
    a, ua = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(a, ua)
    SyncService(a, cloud, ua).sync_once(sess)
    cloud.rows[("u1", "tutorial", "bad")] = {"kind": "tutorial", "id": "bad", "data": {"title": "x", "app": "blender", "steps": ["not json"]}, "updated_at": "2026-11-23T10:00:00+00:00",
                                             "deleted": False, "synced_at": "2026-11-23T10:00:30+00:00"}
    b, ub = device(tmp_path, "b")
    rep = SyncService(b, cloud, ub).sync_once(sess)
    assert rep.ok and rep.pulled == 1 and len(titles(b, ub)) == 1


def test_the_cursor_moves_on_so_the_next_sync_fetches_only_news(tmp_path, cloud, sess):
    a, ua = device(tmp_path, "a")
    StepEditor.from_json_file(SAMPLE).save(a, ua)
    svc = SyncService(a, cloud, ua)
    svc.sync_once(sess)
    cursor = a.sync_cursor(ua)
    assert cursor
    assert svc.sync_once(sess).pulled == 0 and a.sync_cursor(ua) == cursor


# ---------------------------------------------------------------- databases made by an earlier version
def test_an_old_database_gets_the_new_columns_and_keeps_its_data(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE user (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '', password_hash BLOB NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE preferences (user_id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE tutorial (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL, app TEXT NOT NULL DEFAULT 'blender', source_type TEXT NOT NULL DEFAULT 'manual', source_url TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE step (id INTEGER PRIMARY KEY AUTOINCREMENT, tutorial_id INTEGER NOT NULL, position INTEGER NOT NULL, record TEXT NOT NULL, UNIQUE (tutorial_id, position));
        CREATE TABLE session (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, tutorial_id INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'not_started', current_pos INTEGER, started_at TEXT, finished_at TEXT);
        CREATE TABLE session_step (session_id INTEGER NOT NULL, step_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', status_by TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (session_id, step_id));
        INSERT INTO user (email, password_hash, created_at) VALUES ('a@x.com', x'00', '2026-01-01');
        INSERT INTO tutorial (user_id, title, created_at, updated_at) VALUES (1, 'Old one', '2026-01-01', '2026-01-02');
        INSERT INTO session (user_id, tutorial_id, state, started_at) VALUES (1, 1, 'active', '2026-01-03T10:00:00+00:00');
    """)
    c.commit()
    c.close()
    db = Database(path)
    assert [r["title"] for r in db.list_tutorials(1)] == ["Old one"]
    assert db.list_tutorials(1)[0]["sync_id"] and db.list_sessions(1)[0]["sync_id"] and db.list_sessions(1)[0]["updated_at"]
    Database(path).close()                                          # opening it twice is fine
