"""Offline-first sync: the app always works on the local database; changes are sent to the online copy (Supabase) when there is a connection, and other devices' changes are brought in.

No Qt in here. The database is touched only on the caller's (the window's) thread; only `network` talks to the internet, so the window can run it on a worker:

    plan = sync.plan()                      # window thread: what to send, and where to continue fetching from
    result = sync.network(session, plan)    # worker thread: the internet only; never raises
    report = sync.finish(plan, result)      # window thread: forget what was sent, apply what came in

`sync_once(session)` does the three in a row (tests, and a run without threads).

What is synced: tutorials (with their steps), sessions (with the status of every step) and the preferences, as one row each (kind, id, data JSON, updated_at, deleted).
Rules:
  * a change is noted in the `outbox` table at the moment it is made (app/db.py), so nothing is lost while offline or when the app is closed;
  * when two devices changed the same thing, the newest `updated_at` wins; a delete wins over an older edit;
  * a tutorial is identified by a random `sync_id`, not by the local row id, so two computers never clash;
  * tutorials are applied before sessions, so a session finds its tutorial; a session whose tutorial no longer exists online is skipped;
  * a failure (offline, signed out) keeps every note, so the next attempt sends it all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shared.step_record import Step

from .cloud import Cloud, CloudAuthError, CloudSession, CloudUnavailable
from .db import Database, now

KIND_ORDER = {"tutorial": 0, "session": 1, "pref": 2}        # apply in this order: sessions need their tutorial


def norm(ts: str | None) -> str:
    """Any ISO timestamp as UTC `YYYY-MM-DDTHH:MM:SS+00:00`, so strings compare in time order (the server may answer `...Z` or with microseconds)."""
    if not ts:
        return ""
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Plan:
    items: list[dict[str, Any]]                  # what to send
    sent_keys: list[tuple[str, str, str]]        # (kind, id, queued_at) of each, to clear afterwards
    since: str | None                            # fetch what the server received after this


@dataclass
class Result:
    ok: bool = False
    offline: bool = False
    signed_out: bool = False                     # the online sign-in expired: the learner must log in again
    error: str = ""
    incoming: list[dict[str, Any]] = field(default_factory=list)
    session: CloudSession | None = None          # a refreshed sign-in, if the old one had expired


@dataclass
class Report:
    pushed: int = 0
    pulled: int = 0
    offline: bool = False
    signed_out: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not (self.offline or self.signed_out or self.error)


class SyncService:
    def __init__(self, db: Database, cloud: Cloud, user_id: int):
        self.db, self.cloud, self.user_id = db, cloud, user_id

    # ---- state
    @property
    def pending(self) -> int:
        return len(self.db.pending_changes(self.user_id))

    # ---- window thread
    def plan(self) -> Plan:
        items, keys = [], []
        for row in self.db.pending_changes(self.user_id):
            item = self.export_item(row["kind"], row["item_id"], row["op"], row["queued_at"])
            if item is not None:
                items.append(item)
            keys.append((row["kind"], row["item_id"], row["queued_at"]))           # a note whose thing no longer exists is simply cleared
        return Plan(items=items, sent_keys=keys, since=self.db.sync_cursor(self.user_id))

    def finish(self, plan: Plan, result: Result) -> Report:
        if result.offline or result.signed_out or not result.ok:
            return Report(offline=result.offline, signed_out=result.signed_out, error=result.error)
        self.db.clear_changes(self.user_id, plan.sent_keys)
        pulled = self.apply(result.incoming)
        return Report(pushed=len(plan.items), pulled=pulled)

    # ---- worker thread: the internet only
    def network(self, session: CloudSession, plan: Plan) -> Result:
        result = Result()
        try:
            try:
                result.incoming = self._exchange(session, plan)
            except CloudAuthError:
                session = self.cloud.refresh(session)               # the access token may just have expired: refresh it once
                result.session = session
                result.incoming = self._exchange(session, plan)
            result.ok = True
        except CloudUnavailable:
            result.offline = True
        except CloudAuthError:
            result.signed_out = True
        except Exception as e:                                       # a bug or a bad answer must never close the app
            result.error = f"Sync failed ({type(e).__name__})."
        return result

    def _exchange(self, session: CloudSession, plan: Plan) -> list[dict[str, Any]]:
        self.cloud.push_items(session, plan.items)
        return self.cloud.fetch_items(session, plan.since)

    def sync_once(self, session: CloudSession) -> Report:
        plan = self.plan()
        return self.finish(plan, self.network(session, plan))

    # ---- turning rows into items and back
    def export_item(self, kind: str, item_id: str, op: str = "upsert", queued_at: str = "") -> dict[str, Any] | None:
        c = self.db.conn
        if op == "delete":
            return {"kind": kind, "id": item_id, "data": {}, "updated_at": norm(queued_at) or now(), "deleted": True}
        if kind == "tutorial":
            t = c.execute("SELECT * FROM tutorial WHERE sync_id = ? AND user_id = ?", (item_id, self.user_id)).fetchone()
            if t is None:
                return None
            steps = [r["record"] for r in c.execute("SELECT record FROM step WHERE tutorial_id = ? ORDER BY position", (t["id"],)).fetchall()]
            data = {"title": t["title"], "app": t["app"], "source_type": t["source_type"], "source_url": t["source_url"], "created_at": t["created_at"], "steps": steps}
            return {"kind": kind, "id": item_id, "data": data, "updated_at": norm(t["updated_at"]), "deleted": False}
        if kind == "session":
            s = c.execute("SELECT s.*, t.sync_id AS tsync FROM session s JOIN tutorial t ON t.id = s.tutorial_id WHERE s.sync_id = ? AND s.user_id = ?", (item_id, self.user_id)).fetchone()
            if s is None:
                return None
            steps = [{"position": r["position"], "status": r["status"], "by": r["status_by"], "at": r["updated_at"]} for r in self.db.session_steps(s["id"])]
            data = {"tutorial": s["tsync"], "state": s["state"], "current_pos": s["current_pos"], "started_at": s["started_at"], "finished_at": s["finished_at"], "steps": steps}
            return {"kind": kind, "id": item_id, "data": data, "updated_at": norm(s["updated_at"]), "deleted": False}
        if kind == "pref":
            row = c.execute("SELECT * FROM preferences WHERE user_id = ?", (self.user_id,)).fetchone()
            if row is None:
                return None
            return {"kind": kind, "id": item_id, "data": json.loads(row["data"]), "updated_at": norm(row["updated_at"]) or now(), "deleted": False}
        return None

    def apply(self, items: list[dict[str, Any]]) -> int:
        """Bring other devices' changes in. Never marks them as changes to send back. Returns how many changed something here."""
        changed, newest = 0, self.db.sync_cursor(self.user_id)
        for item in sorted(items, key=lambda i: (KIND_ORDER.get(i.get("kind"), 9), norm(i.get("updated_at")))):
            try:
                with self.db.tx():
                    changed += 1 if self._apply_one(item) else 0
            except (ValueError, KeyError, TypeError):
                continue                                              # one bad row must not stop the rest
            if item.get("synced_at") and (newest is None or item["synced_at"] > newest):
                newest = item["synced_at"]
        if newest is not None:
            self.db.set_sync_cursor(self.user_id, newest)
        return changed

    def _apply_one(self, item: dict[str, Any]) -> bool:
        kind, iid, deleted = item["kind"], str(item["id"]), bool(item.get("deleted"))
        remote_at, data, c, uid = norm(item.get("updated_at")), item.get("data") or {}, self.db.conn, self.user_id
        if kind == "tutorial":
            t = c.execute("SELECT * FROM tutorial WHERE sync_id = ? AND user_id = ?", (iid, uid)).fetchone()
            if deleted:
                if t is None:
                    return False
                c.execute("DELETE FROM tutorial WHERE id = ?", (t["id"],))
                return True
            steps = [Step.model_validate_json(r) for r in data["steps"]]            # a row with a bad step is skipped, never half-applied
            if t is None:
                cur = c.execute("INSERT INTO tutorial (user_id, title, app, source_type, source_url, created_at, updated_at, sync_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (uid, data["title"], data["app"], data.get("source_type", "manual"), data.get("source_url"), data.get("created_at") or remote_at, remote_at, iid))
                tid = int(cur.lastrowid)
            elif norm(t["updated_at"]) >= remote_at:
                return False                                                     # ours is as new or newer
            else:
                tid = t["id"]
                c.execute("UPDATE tutorial SET title = ?, app = ?, source_type = ?, source_url = ?, updated_at = ? WHERE id = ?",
                          (data["title"], data["app"], data.get("source_type", "manual"), data.get("source_url"), remote_at, tid))
                c.execute("DELETE FROM step WHERE tutorial_id = ?", (tid,))
            for pos, step in enumerate(steps, start=1):
                c.execute("INSERT INTO step (tutorial_id, position, record) VALUES (?, ?, ?)", (tid, pos, step.model_dump_json()))
            return True
        if kind == "session":
            s = c.execute("SELECT * FROM session WHERE sync_id = ? AND user_id = ?", (iid, uid)).fetchone()
            if deleted:
                if s is None:
                    return False
                c.execute("DELETE FROM session WHERE id = ?", (s["id"],))
                return True
            t = c.execute("SELECT id FROM tutorial WHERE sync_id = ? AND user_id = ?", (data["tutorial"], uid)).fetchone()
            if t is None:
                raise KeyError("its tutorial is gone")                              # skipped (apply() catches it)
            if s is not None and norm(s["updated_at"]) >= remote_at:
                return False
            if s is None:
                cur = c.execute("INSERT INTO session (user_id, tutorial_id, state, current_pos, started_at, finished_at, sync_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (uid, t["id"], data["state"], data.get("current_pos"), data.get("started_at"), data.get("finished_at"), iid, remote_at))
                sid = int(cur.lastrowid)
                for r in c.execute("SELECT id FROM step WHERE tutorial_id = ?", (t["id"],)).fetchall():
                    c.execute("INSERT INTO session_step (session_id, step_id, updated_at) VALUES (?, ?, ?)", (sid, r["id"], remote_at))
            else:
                sid = s["id"]
                c.execute("UPDATE session SET state = ?, current_pos = ?, started_at = ?, finished_at = ?, updated_at = ? WHERE id = ?",
                          (data["state"], data.get("current_pos"), data.get("started_at"), data.get("finished_at"), remote_at, sid))
            for st in data.get("steps", []):
                c.execute("UPDATE session_step SET status = ?, status_by = ?, updated_at = ? WHERE session_id = ? AND step_id = "
                          "(SELECT id FROM step WHERE tutorial_id = ? AND position = ?)", (st["status"], st.get("by"), st.get("at") or remote_at, sid, t["id"], st["position"]))
            return True
        if kind == "pref":
            row = c.execute("SELECT * FROM preferences WHERE user_id = ?", (uid,)).fetchone()
            if row is not None and norm(row["updated_at"]) >= remote_at:
                return False
            c.execute("INSERT INTO preferences (user_id, data, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                      (uid, json.dumps(data, sort_keys=True), remote_at))
            return True
        return False
