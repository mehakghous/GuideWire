"""SQLite data layer for the app (User, Tutorial, Step, Session, SessionStep, Preferences).

Plain `sqlite3`, no ORM. Foreign keys are on. A step is stored as the shared Step record (shared/step_record.py) serialised as JSON
in `step.record`, plus its position, so the step contract stays the single source of truth and a schema bump never needs a table change.
Times are UTC ISO-8601 strings. The database file lives in local_data/ (git-ignored); never commit it.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from shared.step_record import Step, StepList

DEFAULT_PATH = Path(os.environ.get("GUIDEWIRE_DB", "local_data/guidewire.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL DEFAULT '',
    password_hash BLOB NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    user_id INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
    data    TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tutorial (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    app         TEXT NOT NULL DEFAULT 'blender',
    source_type TEXT NOT NULL DEFAULT 'manual',
    source_url  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS step (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tutorial_id INTEGER NOT NULL REFERENCES tutorial(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    record      TEXT NOT NULL,
    UNIQUE (tutorial_id, position)
);
CREATE TABLE IF NOT EXISTS session (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    tutorial_id INTEGER NOT NULL REFERENCES tutorial(id) ON DELETE CASCADE,
    state       TEXT NOT NULL DEFAULT 'not_started',
    current_pos INTEGER,
    started_at  TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS session_step (
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    step_id    INTEGER NOT NULL REFERENCES step(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'pending',
    status_by  TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, step_id)
);
CREATE INDEX IF NOT EXISTS idx_tutorial_user ON tutorial(user_id);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---- users (password hashing lives in app/accounts.py; this layer only stores the hash)
    def add_user(self, email: str, password_hash: bytes, display_name: str = "") -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO user (email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                            (email.strip(), display_name, password_hash, now()))
            c.execute("INSERT INTO preferences (user_id) VALUES (?)", (cur.lastrowid,))
            return int(cur.lastrowid)

    def get_user_by_email(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM user WHERE email = ?", (email.strip(),)).fetchone()

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()

    def update_user(self, user_id: int, *, display_name: str | None = None, password_hash: bytes | None = None) -> None:
        with self.tx() as c:
            if display_name is not None:
                c.execute("UPDATE user SET display_name = ? WHERE id = ?", (display_name, user_id))
            if password_hash is not None:
                c.execute("UPDATE user SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    # ---- preferences
    def get_preferences(self, user_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT data FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row["data"]) if row else {}

    def set_preferences(self, user_id: int, data: dict[str, Any]) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO preferences (user_id, data) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
                      (user_id, json.dumps(data, sort_keys=True)))

    # ---- tutorials and steps
    def save_tutorial(self, user_id: int, title: str, steps: StepList, *, source_type: str = "manual", source_url: str | None = None,
                      tutorial_id: int | None = None) -> int:
        """Create a tutorial, or replace the steps of an existing one (`tutorial_id`), in one transaction."""
        with self.tx() as c:
            if tutorial_id is None:
                cur = c.execute("INSERT INTO tutorial (user_id, title, app, source_type, source_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (user_id, title, steps.app, source_type, source_url, now(), now()))
                tutorial_id = int(cur.lastrowid)
            else:
                if not c.execute("SELECT 1 FROM tutorial WHERE id = ? AND user_id = ?", (tutorial_id, user_id)).fetchone():
                    raise KeyError(f"tutorial {tutorial_id} not found for this user")
                c.execute("UPDATE tutorial SET title = ?, app = ?, updated_at = ? WHERE id = ?", (title, steps.app, now(), tutorial_id))
                c.execute("DELETE FROM step WHERE tutorial_id = ?", (tutorial_id,))
            for pos, step in enumerate(steps.steps, start=1):
                c.execute("INSERT INTO step (tutorial_id, position, record) VALUES (?, ?, ?)", (tutorial_id, pos, step.model_dump_json()))
            return tutorial_id

    def list_tutorials(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM tutorial WHERE user_id = ? ORDER BY updated_at DESC, id DESC", (user_id,)).fetchall()

    def get_steps(self, tutorial_id: int) -> list[tuple[int, Step]]:
        """(step row id, Step) in order."""
        rows = self.conn.execute("SELECT id, record FROM step WHERE tutorial_id = ? ORDER BY position", (tutorial_id,)).fetchall()
        return [(r["id"], Step.model_validate_json(r["record"])) for r in rows]

    def delete_tutorial(self, user_id: int, tutorial_id: int) -> bool:
        with self.tx() as c:
            return c.execute("DELETE FROM tutorial WHERE id = ? AND user_id = ?", (tutorial_id, user_id)).rowcount > 0

    # ---- sessions
    def start_session(self, user_id: int, tutorial_id: int) -> int:
        with self.tx() as c:
            if not c.execute("SELECT 1 FROM tutorial WHERE id = ? AND user_id = ?", (tutorial_id, user_id)).fetchone():
                raise KeyError(f"tutorial {tutorial_id} not found for this user")
            cur = c.execute("INSERT INTO session (user_id, tutorial_id) VALUES (?, ?)", (user_id, tutorial_id))
            sid = int(cur.lastrowid)
            for r in c.execute("SELECT id FROM step WHERE tutorial_id = ?", (tutorial_id,)).fetchall():
                c.execute("INSERT INTO session_step (session_id, step_id, updated_at) VALUES (?, ?, ?)", (sid, r["id"], now()))
            return sid

    def get_session(self, session_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()

    def update_session(self, session_id: int, *, state: str, current_pos: int | None, started_at: str | None = None, finished_at: str | None = None) -> None:
        with self.tx() as c:
            c.execute("UPDATE session SET state = ?, current_pos = ?, started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at) WHERE id = ?",
                      (state, current_pos, started_at, finished_at, session_id))

    def set_step_status(self, session_id: int, step_id: int, status: str, by: str = "user") -> None:
        with self.tx() as c:
            c.execute("UPDATE session_step SET status = ?, status_by = ?, updated_at = ? WHERE session_id = ? AND step_id = ?",
                      (status, by, now(), session_id, step_id))

    def session_steps(self, session_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT ss.*, s.position FROM session_step ss JOIN step s ON s.id = ss.step_id WHERE ss.session_id = ? ORDER BY s.position",
                                 (session_id,)).fetchall()

    def list_sessions(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM session WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
