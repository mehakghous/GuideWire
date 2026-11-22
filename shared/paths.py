"""Where GuideWire reads its bundled files and where it may write. One place, so the installed app and the development checkout agree.

* Development (running from the repository): nothing changes. Everything is relative to the repository, as before.
* Installed (a PyInstaller build under Program Files): bundled data (knowledge, menus, examples) is read-only, so everything the app WRITES (the database, caches, run logs, the
  `.env` with the AI keys) lives in `%LOCALAPPDATA%\\GuideWire`. `prepare_runtime()` also makes that folder the working directory, so the many paths written relative to the
  working directory (`local_data/...`, `runs/...`) land somewhere writable.

`GUIDEWIRE_HOME` overrides the writable folder (tests, portable use).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "GuideWire"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    """The folder the bundled data sits under: PyInstaller's unpack folder when installed, the repository otherwise."""
    return Path(getattr(sys, "_MEIPASS", repo_root())) if is_frozen() else repo_root()


def writable_root() -> Path:
    env = os.environ.get("GUIDEWIRE_HOME")
    if env:
        return Path(env)
    if is_frozen():
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_FOLDER
    return repo_root()


def env_file() -> Path:
    """The `.env` that holds the AI keys: next to the repository in development, in the user's GuideWire folder when installed."""
    return writable_root() / ".env"


def load_env() -> bool:
    """Load the `.env` (keys the app needs) without overriding variables that are already set. Returns True if a file was read."""
    from dotenv import load_dotenv
    path = env_file()
    if path.is_file() and load_dotenv(path, override=False):
        return True
    return bool(load_dotenv(override=False))          # development: the usual search from the calling file upward


def prepare_runtime() -> Path | None:
    """Installed app only: create the writable folder and make it the working directory. Returns the folder (None in development)."""
    if not is_frozen():
        return None
    root = writable_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    return root
