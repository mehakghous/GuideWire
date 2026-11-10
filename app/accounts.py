"""Registration, login and profile for the app. Passwords are hashed with bcrypt and never stored or logged in plain text.

Errors are raised as AccountError with a message that is safe to show the user. Login says the same thing for an unknown email and
a wrong password, so the form cannot be used to find out who has an account.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import bcrypt

from .db import Database

MIN_PASSWORD = 8
MAX_PASSWORD_BYTES = 72          # bcrypt ignores everything after 72 bytes, so longer passwords are refused instead of silently truncated
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BAD_LOGIN = "Incorrect email or password."


class AccountError(Exception):
    pass


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
    def __init__(self, db: Database):
        self.db = db

    def register(self, email: str, password: str, display_name: str = "") -> User:
        email = email.strip()
        if not _EMAIL.match(email):
            raise AccountError("Enter a valid email address.")
        _check_password_rules(password)
        try:
            uid = self.db.add_user(email, _hash(password), display_name.strip())
        except sqlite3.IntegrityError:
            raise AccountError("An account with this email already exists.") from None
        return _user(self.db.get_user(uid))

    def login(self, email: str, password: str) -> User:
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
        self.db.update_user(user_id, password_hash=_hash(new))

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
