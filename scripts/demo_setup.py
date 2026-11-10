"""OPTIONAL shortcut for the supervisor demo: a local demo database with a ready-made demo account and real content.

You do not need this to demo the app: any new account can click "Add demo tutorials" on Home and gets the same content. This script is for a pre-made account.

    python scripts/demo_setup.py [--db local_data/demo.sqlite] [--reset]

Creates (or refreshes) the demo account and fills it with:
  * the six real tutorials in demo/data (steps extracted from real YouTube videos, grouped for display; Blender, Maya and Houdini),
  * three starter plans built from the knowledge base ("where do I start rigging"), one per application.
Then start the app on that database:

    $env:GUIDEWIRE_DB = "local_data/demo.sqlite"      # PowerShell
    python -m app.ui.main_window

The demo account is local to this file: nothing is sent anywhere. The database lives in local_data/ (git-ignored).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.accounts import AccountError, Accounts  # noqa: E402
from app.db import Database  # noqa: E402
from app import demo_content  # noqa: E402

DATA = demo_content.DATA
DEMO_EMAIL = "demo@guidewire.test"
DEMO_PASSWORD = "guidewire-demo-2026"
DEMO_NAME = "Demo Learner"


def manifest() -> list[dict]:
    return demo_content.manifest()


def seed(db: Database) -> dict:
    """Register (or log in) the demo account and add the demo tutorials it does not have yet. Returns what is there."""
    acc = Accounts(db)
    try:
        user = acc.register(DEMO_EMAIL, DEMO_PASSWORD, DEMO_NAME)
    except AccountError:
        user = acc.login(DEMO_EMAIL, DEMO_PASSWORD)
    added = demo_content.add_demo_tutorials(db, user.id)
    return {"user": user.email, "tutorials": len(db.list_tutorials(user.id)), "added": added}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "local_data" / "demo.sqlite")
    ap.add_argument("--reset", action="store_true", help="delete the demo database first and start clean")
    a = ap.parse_args(argv)
    a.db.parent.mkdir(parents=True, exist_ok=True)
    if a.reset and a.db.exists():
        a.db.unlink()
    db = Database(a.db)
    try:
        res = seed(db)
    finally:
        db.close()
    print(f"Demo database: {a.db}")
    print(f"  account : {DEMO_EMAIL}   password: {DEMO_PASSWORD}")
    print(f"  content : {res['tutorials']} tutorials ({res['added']} added now)")
    print("Start the app on it (PowerShell):")
    print(f'  $env:GUIDEWIRE_DB = "{a.db}"')
    print("  python -m app.ui.main_window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
