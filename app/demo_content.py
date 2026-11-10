"""Starter content for an account: the six real tutorials in demo/data and one starter plan per application (built from the knowledge base).

One click on Home ("Add demo tutorials") gives ANY account, a brand-new one included, something to review, run a session on and ask about. Nothing is sent anywhere.
Tutorials the account already has (same title) are skipped, so clicking twice adds nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

from ingestion.starter_plan import starter_plan

from .db import Database
from .step_loader import load_steps

DATA = Path(__file__).resolve().parents[1] / "demo" / "data"
APPS = ("blender", "maya", "houdini")


def manifest() -> list[dict]:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def starter_title(app: str) -> str:
    return f"Starter plan: rigging a character in {app.capitalize()} (from the knowledge base)"


def add_demo_tutorials(db: Database, user_id: int) -> int:
    """Add the demo tutorials this account does not have yet. Returns how many were added."""
    have = {r["title"] for r in db.list_tutorials(user_id)}
    added = 0
    for m in manifest():
        if m["title"] in have:
            continue
        steps = load_steps(json.loads((DATA / m["file"]).read_text(encoding="utf-8")))
        db.save_tutorial(user_id, m["title"], steps, source_type="youtube", source_url=m["url"])
        added += 1
    for app in APPS:
        if starter_title(app) in have:
            continue
        db.save_tutorial(user_id, starter_title(app), starter_plan(app), source_type="manual")
        added += 1
    return added
