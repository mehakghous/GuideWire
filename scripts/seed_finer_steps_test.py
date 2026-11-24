"""Seed a separate test database for trying the finer steps in the app. Offline; touches no existing database.

    python scripts/seed_finer_steps_test.py
    $env:GUIDEWIRE_DB = "local_data/finer_steps_test.sqlite"; python -m app.ui.main_window

Each saved video run is added twice: as extracted ("(before)") and split into finer steps ("(finer steps)"), so the two can be compared in the same session screen.
The test account's email and password are written to local_data/finer_steps_test_login.txt (git-ignored).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.accounts import Accounts, AccountError  # noqa: E402
from app.db import Database  # noqa: E402
from ingestion.identify import resolve_repeats  # noqa: E402
from ingestion.instructions import windows_keys  # noqa: E402
from ingestion.split import split_steps  # noqa: E402
from shared.step_record import StepList  # noqa: E402

DB = ROOT / "local_data" / "finer_steps_test.sqlite"
LOGIN = ROOT / "local_data" / "finer_steps_test_login.txt"
EMAIL, PASSWORD = "finer.steps.test@example.com", "finer-steps-test-1"
RUNS = ROOT / "runs" / "compare" / "gemini-3.6-flash"
SOURCES = [("Blender armature", RUNS / "v12_w0" / "blender_EBgHRd5tJfE.json"),
           ("Blender leg IK", RUNS / "v12_w0" / "blender_PctSMB-RGsM.json"),
           ("Maya quick rig", RUNS / "v12_w0" / "maya_8RqfDcoP0jI.json"),
           ("Houdini APEX FK", RUNS / "v13_w0_g" / "houdini_xWnI7is6e7Q.json"),
           ("Blender leg IK v14", RUNS / "v14_w0" / "blender_PctSMB-RGsM.json"),
           ("Blender armature v14", RUNS / "v14_w0" / "blender_EBgHRd5tJfE.json"),
           ("Maya leg IK v14", RUNS / "v14_w0" / "maya_TmhC35PqZvQ.json"),
           ("Houdini APEX FK v14", RUNS / "v14_w0" / "houdini_xWnI7is6e7Q.json")]


def main() -> None:
    db = Database(DB)
    acc = Accounts(db)
    try:
        user = acc.register(EMAIL, PASSWORD, "Finer steps test")
    except AccountError:
        user = acc.login(EMAIL, PASSWORD)
    have = {r["title"] for r in db.list_tutorials(user.id)}
    for name, path in SOURCES:
        sl = StepList.model_validate_json(path.read_text(encoding="utf-8"))
        if "v14" in path.parent.name:
            windows_keys(sl)                                                  # the app does this to every v14 extraction
            resolve_repeats(sl)
        url = f"https://www.youtube.com/watch?v={sl.video_id}" if sl.video_id else None
        for title, steps in ((f"{name} (finer steps)", split_steps(sl)), (f"{name} (before)", sl)):
            if title not in have:
                db.save_tutorial(user.id, title, steps, source_type="youtube", source_url=url)
                print(f"added: {title}: {len(steps.steps)} steps")
    LOGIN.write_text(f"email: {EMAIL}\npassword: {PASSWORD}\n", encoding="utf-8")
    print("database:", DB)


if __name__ == "__main__":
    main()
