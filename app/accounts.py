"""Registration, login and profile for the app. Passwords are hashed with bcrypt and never stored or logged in plain text.

Errors are raised as AccountError with a message that is safe to show the user. Login says the same thing for an unknown email and
a wrong password, so the form cannot be used to find out who has an account.

With the online service configured (app/cloud.py, Supabase) the ONLINE account is the real one: sign up and log in go there, and a copy of the account
(email, name and a bcrypt hash of the password) is kept on this computer so the learner can still log in with no connection. Without it every account is
local, as before. Password reset sends a one-time code by email and needs the connection.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import bcrypt

from .cloud import Cloud, CloudAuthError, CloudSession, CloudUnavailable, NullCloud
from .db import Database

MIN_PASSWORD = 8
MAX_PASSWORD_BYTES = 72          # bcrypt ignores everything after 72 bytes, so longer passwords are refused instead of silently truncated
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BAD_LOGIN = "Incorrect email or password."


class AccountError(Exception):
    pass


class AccountNotice(AccountError):
    """Not a failure: something the learner must do next (confirm the email address). Shown as a message."""


@dataclass(frozen=True)
class User:
    id: int
    email: str
    display_name: str


def _hash(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def _check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AccountError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")


def _user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], display_name=row["display_name"])


class Accounts:
    def __init__(self, db: Database, cloud: Cloud | None = None):
        self.db = db
        self.cloud: Cloud = cloud or NullCloud()
        self.cloud_session: CloudSession | None = None       # set by an online sign up / login; used by the sync
        self.offline_login = False                           # the last login used the copy on this computer because there was no connection

    @property
    def online_enabled(self) -> bool:
        return bool(self.cloud.configured)

    def _mirror(self, cs: CloudSession, password: str) -> User:
        """Keep the copy of an online account on this computer: created at first login, refreshed when the password changed elsewhere."""
        row = self.db.get_user_by_email(cs.email)
        if row is None:
            uid = self.db.add_user(cs.email, _hash(password), cs.display_name)
        else:
            uid = row["id"]
            self.db.update_user(uid, password_hash=_hash(password), display_name=row["display_name"] or cs.display_name)
        self.db.set_remote_id(uid, cs.user_id)
        self.cloud_session = cs
        self.offline_login = False
        return _user(self.db.get_user(uid))

    def register(self, email: str, password: str, display_name: str = "") -> User:
        email = email.strip()
        if not _EMAIL.match(email):
            raise AccountError("Enter a valid email address.")
        _check_password_rules(password)
        if self.online_enabled:
            try:
                cs = self.cloud.sign_up(email, password, display_name.strip())
            except CloudUnavailable:
                raise AccountError("Creating an account needs an internet connection. Try again when you are online.") from None
            except CloudAuthError as e:
                raise AccountError(str(e)) from None
            if cs is None:
                raise AccountNotice("Check your email: open the link we sent to confirm your address, then log in.")
            return self._mirror(cs, password)
        try:
            uid = self.db.add_user(email, _hash(password), display_name.strip())
        except sqlite3.IntegrityError:
            raise AccountError("An account with this email already exists.") from None
        return _user(self.db.get_user(uid))

    def login(self, email: str, password: str) -> User:
        self.offline_login = False
        if self.online_enabled and _EMAIL.match(email.strip()):
            try:
                return self._mirror(self.cloud.sign_in(email.strip(), password), password)
            except CloudAuthError as e:
                raise AccountError(str(e) if "Confirm your email" in str(e) or "Too many" in str(e) else BAD_LOGIN) from None
            except CloudUnavailable:
                if self.db.get_user_by_email(email) is None:
                    raise AccountError("You are offline and this account is not on this computer yet. Connect to the internet and log in once.") from None
                self.cloud_session = None
                user = self._login_local(email, password)
                self.offline_login = True                    # works on the local copy; the sync waits for the connection
                return user
        return self._login_local(email, password)

    def _login_local(self, email: str, password: str) -> User:
        row = self.db.get_user_by_email(email)
        if row is None:
            bcrypt.checkpw(b"x", _DUMMY_HASH)          # spend the same time as a real check, so timing does not reveal unknown emails
            raise AccountError(BAD_LOGIN)
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), bytes(row["password_hash"]))
        except ValueError:
            ok = False
        if not ok:
            raise AccountError(BAD_LOGIN)
        return _user(row)

    def change_password(self, user_id: int, old: str, new: str) -> None:
        row = self.db.get_user(user_id)
        if row is None or not bcrypt.checkpw(old.encode("utf-8"), bytes(row["password_hash"])):
            raise AccountError("Current password is incorrect.")
        _check_password_rules(new)
        if self.online_enabled and row["remote_id"]:
            if self.cloud_session is None:
                raise AccountError("Changing your password needs an internet connection. Log in while online, then change it.")
            try:
                self.cloud.change_password(self.cloud_session, new)
            except CloudUnavailable:
                raise AccountError("Changing your password needs an internet connection. Try again when you are online.") from None
            except CloudAuthError as e:
                raise AccountError(str(e)) from None
        self.db.update_user(user_id, password_hash=_hash(new))

    # ---- forgotten password: an emailed one-time code, then a new password
    def request_password_reset(self, email: str) -> None:
        email = email.strip()
        if not _EMAIL.match(email):
            raise AccountError("Enter the email address of your account.")
        if not self.online_enabled:
            raise AccountError("Resetting a password needs the online service, which is not set up on this computer.")
        try:
            self.cloud.request_reset(email)
        except CloudUnavailable:
            raise AccountError("Resetting a password needs an internet connection. Try again when you are online.") from None
        except CloudAuthError as e:
            raise AccountError(str(e)) from None

    def finish_password_reset(self, email: str, code: str, new_password: str) -> User:
        """Check the emailed code, set the new password online and here, and sign the learner in."""
        email = email.strip()
        if not code.strip():
            raise AccountError("Enter the code from the email.")
        _check_password_rules(new_password)
        if not self.online_enabled:
            raise AccountError("Resetting a password needs the online service, which is not set up on this computer.")
        try:
            cs = self.cloud.finish_reset(email, code, new_password)
        except CloudUnavailable:
            raise AccountError("Resetting a password needs an internet connection. Try again when you are online.") from None
        except CloudAuthError as e:
            raise AccountError(str(e)) from None
        return self._mirror(cs, new_password)

    def sign_out(self) -> None:
        self.cloud_session = None
        self.offline_login = False

    def update_profile(self, user_id: int, display_name: str) -> User:
        self.db.update_user(user_id, display_name=display_name.strip())
        return _user(self.db.get_user(user_id))

    def preferences(self, user_id: int) -> dict[str, Any]:
        return self.db.get_preferences(user_id)

    def set_preferences(self, user_id: int, **values: Any) -> dict[str, Any]:
        prefs = {**self.db.get_preferences(user_id), **values}
        self.db.set_preferences(user_id, prefs)
        return prefs


_DUMMY_HASH = bcrypt.hashpw(b"unused", bcrypt.gensalt())
