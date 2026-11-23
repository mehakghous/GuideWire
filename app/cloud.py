"""The app's door to Supabase: accounts (sign up, sign in, password reset by emailed code) and the sync table. No Qt in here.

Only Supabase's public REST endpoints are used, through `httpx`:
  * Auth ("GoTrue"):  /auth/v1/signup, /auth/v1/token, /auth/v1/recover, /auth/v1/verify, /auth/v1/user
  * Data (PostgREST): /rest/v1/sync_item   (one row per tutorial, session or preference; see docs/supabase.md for the SQL and the row level security)

Rules:
  * Only the project URL and the ANON (public) key are ever used here, read from SUPABASE_URL and SUPABASE_ANON_KEY (a `.env` file, never committed).
    The service_role key must never be put in the app: it would bypass the row level security that keeps each user's data private.
  * Passwords and tokens are never logged and never put in an error message.
  * Errors are CloudError with a message that is safe to show the learner; CloudUnavailable means "no connection or the service is down", which the app treats as OFFLINE
    (work continues locally and is synced later), and CloudAuthError means the service answered "no" (wrong password, unknown code ...).
  * `Cloud` is the small interface the rest of the app uses; tests and offline runs use `NullCloud`, tests of the logic use a fake.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class CloudError(Exception):
    """A message that is safe to show the learner."""


class CloudUnavailable(CloudError):
    """No connection, or the service did not answer in time. The app goes on offline."""


class CloudAuthError(CloudError):
    """The service refused: wrong password, unknown email, a wrong or expired code."""


@dataclass
class CloudSession:
    user_id: str            # the account's id in Supabase (a uuid)
    email: str
    display_name: str
    access_token: str
    refresh_token: str


class Cloud(Protocol):
    configured: bool

    def sign_up(self, email: str, password: str, display_name: str) -> CloudSession | None: ...
    def sign_in(self, email: str, password: str) -> CloudSession: ...
    def request_reset(self, email: str) -> None: ...
    def finish_reset(self, email: str, code: str, new_password: str) -> CloudSession: ...
    def change_password(self, session: CloudSession, new_password: str) -> None: ...
    def refresh(self, session: CloudSession) -> CloudSession: ...
    def push_items(self, session: CloudSession, items: list[dict[str, Any]]) -> None: ...
    def fetch_items(self, session: CloudSession, since: str | None) -> list[dict[str, Any]]: ...   # items carry synced_at (the server's arrival time): the next `since`


class NullCloud:
    """No cloud on this computer (no project configured): accounts and data stay local, exactly as before."""
    configured = False

    def _no(self, *_a, **_k):
        raise CloudUnavailable("The online service is not set up on this computer.")

    sign_up = sign_in = request_reset = finish_reset = change_password = refresh = push_items = fetch_items = _no


def _message(resp: httpx.Response) -> str:
    """Supabase's own error text, trimmed, never the request (which holds the password)."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        for key in ("msg", "error_description", "message", "error"):
            if isinstance(body.get(key), str):
                return body[key][:200]
    return ""


class SupabaseCloud:
    configured = True

    def __init__(self, url: str, anon_key: str, client: httpx.Client | None = None, timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.key = anon_key
        self.http = client or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls) -> "Cloud":
        """The real service when SUPABASE_URL and SUPABASE_ANON_KEY are set (in the environment or a .env file); otherwise `NullCloud`."""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        url, key = os.environ.get("SUPABASE_URL", "").strip(), os.environ.get("SUPABASE_ANON_KEY", "").strip()
        return cls(url, key) if url and key else NullCloud()

    # ---- plumbing
    def _headers(self, session: CloudSession | None = None) -> dict[str, str]:
        """The `apikey` header always carries the project's public key. `Authorization` carries the learner's token once logged in; before that it carries the key only when it is
        a JWT (the older "anon" key). A newer "publishable" key (sb_publishable_...) is not a JWT and must go in `apikey` alone."""
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if session is not None:
            headers["Authorization"] = f"Bearer {session.access_token}"
        elif self.key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    def _send(self, method: str, path: str, *, session: CloudSession | None = None, json: Any = None, params: dict | None = None, extra: dict | None = None) -> httpx.Response:
        try:
            resp = self.http.request(method, self.url + path, headers={**self._headers(session), **(extra or {})}, json=json, params=params)
        except (httpx.TransportError, httpx.TimeoutException):
            raise CloudUnavailable("No connection to the online service.") from None
        if resp.status_code >= 500:
            raise CloudUnavailable("The online service is not answering right now.")
        return resp

    @staticmethod
    def _session(body: dict, fallback_email: str = "", fallback_name: str = "") -> CloudSession:
        user = body.get("user") or {}
        meta = user.get("user_metadata") or {}
        return CloudSession(user_id=str(user.get("id", "")), email=str(user.get("email") or fallback_email), display_name=str(meta.get("display_name") or fallback_name),
                            access_token=str(body["access_token"]), refresh_token=str(body.get("refresh_token", "")))

    # ---- accounts
    def sign_up(self, email: str, password: str, display_name: str) -> CloudSession | None:
        """Create the account. Returns the signed-in session, or None when the project asks the learner to confirm their email first."""
        r = self._send("POST", "/auth/v1/signup", json={"email": email, "password": password, "data": {"display_name": display_name}})
        if r.status_code in (400, 409, 422):
            text = _message(r).lower()
            if "already" in text or "registered" in text:
                raise CloudAuthError("An account with this email already exists.")
            if "password" in text:
                raise CloudAuthError("That password is not accepted. Use a longer one.")
            raise CloudAuthError("The account could not be created. Check the email address.")
        if r.status_code == 429:
            raise CloudAuthError("Too many attempts. Wait a minute and try again.")
        r.raise_for_status()
        body = r.json()
        if "access_token" not in body:
            return None
        return self._session(body, email, display_name)

    def sign_in(self, email: str, password: str) -> CloudSession:
        r = self._send("POST", "/auth/v1/token", params={"grant_type": "password"}, json={"email": email, "password": password})
        if r.status_code in (400, 401, 422):
            text = _message(r).lower()
            if "confirm" in text:
                raise CloudAuthError("Confirm your email address first: open the link in the email we sent you.")
            raise CloudAuthError("Incorrect email or password.")
        if r.status_code == 429:
            raise CloudAuthError("Too many attempts. Wait a minute and try again.")
        r.raise_for_status()
        return self._session(r.json(), email)

    def request_reset(self, email: str) -> None:
        """Email a one-time code (the project's recovery template must contain {{ .Token }}). Always looks the same, so it cannot be used to find who has an account."""
        r = self._send("POST", "/auth/v1/recover", json={"email": email})
        if r.status_code == 429:
            raise CloudAuthError("Too many attempts. Wait a minute and try again.")

    def finish_reset(self, email: str, code: str, new_password: str) -> CloudSession:
        r = self._send("POST", "/auth/v1/verify", json={"type": "recovery", "email": email, "token": code.strip()})
        if r.status_code >= 400:
            raise CloudAuthError("That code is wrong or has expired. Ask for a new one.")
        session = self._session(r.json(), email)
        self.change_password(session, new_password)
        return session

    def change_password(self, session: CloudSession, new_password: str) -> None:
        r = self._send("PUT", "/auth/v1/user", session=session, json={"password": new_password})
        if r.status_code >= 400:
            raise CloudAuthError("The new password was not accepted." if r.status_code in (400, 422) else "Please log in again, then change the password.")

    def refresh(self, session: CloudSession) -> CloudSession:
        r = self._send("POST", "/auth/v1/token", params={"grant_type": "refresh_token"}, json={"refresh_token": session.refresh_token})
        if r.status_code >= 400:
            raise CloudAuthError("Your online sign-in has expired. Log in again.")
        return self._session(r.json(), session.email, session.display_name)

    # ---- data: one generic table, see docs/supabase.md
    def push_items(self, session: CloudSession, items: list[dict[str, Any]]) -> None:
        """Insert or update items: dicts with kind, id, data (a dict), updated_at, deleted. The user id comes from the token (row level security), never from the app."""
        if not items:
            return
        rows = [{"user_id": session.user_id, "kind": i["kind"], "id": i["id"], "data": i.get("data") or {}, "updated_at": i["updated_at"], "deleted": bool(i.get("deleted"))} for i in items]
        r = self._send("POST", "/rest/v1/sync_item", session=session, json=rows, params={"on_conflict": "user_id,kind,id"}, extra={"Prefer": "resolution=merge-duplicates,return=minimal"})
        if r.status_code in (401, 403):
            raise CloudAuthError("Your online sign-in has expired. Log in again.")
        r.raise_for_status()

    def fetch_items(self, session: CloudSession, since: str | None) -> list[dict[str, Any]]:
        # the cursor is `synced_at`, stamped by the SERVER when a row arrives, so a device whose clock is wrong cannot hide its changes from the others
        params = {"select": "kind,id,data,updated_at,deleted,synced_at", "order": "synced_at.asc", "limit": "1000"}
        if since:
            params["synced_at"] = f"gt.{since}"
        r = self._send("GET", "/rest/v1/sync_item", session=session, params=params)
        if r.status_code in (401, 403):
            raise CloudAuthError("Your online sign-in has expired. Log in again.")
        r.raise_for_status()
        return list(r.json())
