"""Preflight for the live demo: what is ready, what is missing, and the command that fixes it.

    python scripts/demo_check.py            # run it from the repo folder with the venv active, before you present
    python scripts/demo_check.py --fix      # also create the optional pre-made demo account if it is missing

Every line is [ok] (ready), [!!] (fix this before the demo) or [--] (optional, or only for one part of the demo). It calls no paid model and sends nothing anywhere.
It does not open a window: the app is built off-screen to prove it starts, then closed.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))                       # so `demo_setup` (next to this file) can be imported

DEMO_DB = ROOT / "local_data" / "demo.sqlite"
OK, BAD, INFO = "[ok]", "[!!]", "[--]"


class Report:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str]] = []

    def add(self, tag: str, what: str, fix: str = "") -> None:
        self.lines.append((tag, what, fix))

    @property
    def problems(self) -> list[tuple[str, str, str]]:
        return [x for x in self.lines if x[0] == BAD]

    def print(self) -> None:
        for tag, what, fix in self.lines:
            print(f"{tag} {what}")
            if fix and tag != OK:
                print(f"       fix: {fix}")


def check_environment(r: Report) -> None:
    v = sys.version_info
    r.add(OK if v >= (3, 11) else BAD, f"Python {v.major}.{v.minor}.{v.micro}", "use Python 3.11 (see the README)")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    r.add(OK if in_venv else BAD, "running inside the project's virtual environment" if in_venv else "NOT inside a virtual environment", r"venv\Scripts\activate  (then run this again)")
    for mod, why in (("PyQt6", "the app window"), ("bcrypt", "accounts"), ("pydantic", "the step format"), ("dotenv", "reading .env"), ("google.genai", "the Gemini model calls"), ("requests", "OpenAI calls")):
        try:
            importlib.import_module(mod)
            r.add(OK, f"package {mod} ({why})")
        except Exception:
            r.add(BAD, f"package {mod} is missing ({why})", "pip install -r requirements.txt")


def check_keys(r: Report) -> None:
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / ".env")
    has = lambda k: bool((env.get(k) or os.environ.get(k) or "").strip())          # noqa: E731  (only whether it is set; the value is never printed)
    r.add(OK if has("GEMINI_API_KEY") else INFO, "GEMINI_API_KEY is set (live questions and extraction)" if has("GEMINI_API_KEY") else "GEMINI_API_KEY is not set: only the offline parts of the demo will work", "put your key in .env (copy .env.example)")
    r.add(OK if has("YOUTUBE_API_KEY") else INFO, "YOUTUBE_API_KEY is set (Find a tutorial)" if has("YOUTUBE_API_KEY") else "YOUTUBE_API_KEY is not set: Find a tutorial falls back to the small local list", "put your key in .env")
    r.add(OK if has("OPENAI_API_KEY") else INFO, "OPENAI_API_KEY is set (optional: the independent grader)" if has("OPENAI_API_KEY") else "OPENAI_API_KEY is not set (optional)", "")


def check_database(r: Report, db_path: Path, fix: bool) -> None:
    from app.accounts import AccountError, Accounts
    from app.db import Database
    import demo_setup as setup
    if not db_path.exists() and fix:
        db = Database(db_path)
        setup.seed(db)
        db.close()
    if not db_path.exists():
        r.add(INFO, f"no pre-made demo account yet ({db_path.name}); optional: any new account can click Add demo tutorials", "python scripts/demo_setup.py")
        return
    db = Database(db_path)
    try:
        user = Accounts(db).login(setup.DEMO_EMAIL, setup.DEMO_PASSWORD)
        n = len(db.list_tutorials(user.id))
        r.add(OK if n >= 9 else BAD, f"pre-made demo account {setup.DEMO_EMAIL} can log in and has {n} tutorials", "python scripts/demo_setup.py --reset")
    except AccountError:
        r.add(BAD, "the demo account cannot log in", "python scripts/demo_setup.py --reset")
    finally:
        db.close()


def check_app_starts(r: Report, db_path: Path | None = None) -> None:
    """The journey of a BRAND-NEW account, off-screen on a throw-away database: create the account, add the demo tutorials, ask where to start, save the answer, review it and run a session."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtWidgets import QApplication

        from app.db import Database
        from app.ui.main_window import MainWindow
        qapp = QApplication.instance() or QApplication([])
        db = Database(":memory:")
        w = MainWindow(db, sync=True)
        w.login.name.setText("Preflight")
        w.login.email.setText("preflight@example.com")
        w.login.password.setText("a-long-password-1")
        w.login.do_register()
        assert w.user is not None and not w.home.empty.isHidden(), "a new account should see the welcome message"
        w.home.demo_button.click()
        assert w.home.tutorials.count() == 9, "Add demo tutorials should give 9 tutorials"
        from app.discovery import find_tutorials
        w.find_screen.finder = lambda goal, app: find_tutorials(goal, app, live=False, cache_path=None)
        w.home.find_button.click()
        w.find_screen.goal.setText("rig a leg with ik in maya")
        w.find_screen.search()
        assert w.find_screen.result is not None and (w.find_screen.result.suggestions or w.find_screen.result.message), "Find a tutorial should answer, even offline"
        w.show_home()
        w.home.ask_button.click()
        w.ask_screen.app.setCurrentText("maya")
        w.ask_screen.input.setText("where do i start rigging in maya")
        w.ask_screen.submit()
        assert w.ask_screen.last_steps is not None, "asking where to start should give steps"
        w.ask_screen.save_button.click()
        w.show_home()
        tid = w.home.selected_tutorial()
        w.open_review(tid)
        w.open_session(tid)
        w.close()
        db.close()
        del qapp
        r.add(OK, "a brand-new account works: create it, add demo tutorials, find a tutorial, ask where to start, save the steps, review, start a session (checked off-screen)")
    except Exception as e:                                                                  # report, never crash the check
        r.add(BAD, f"the app journey failed: {type(e).__name__}: {str(e)[:100]}", "pip install -r requirements.txt")


def check_ingestion(r: Report) -> None:
    """The offline answering path: a starter plan for a question, no model and no network."""
    try:
        from ingestion.service import Service
        from ingestion.session import Session
        svc = Service(Session(), None, None, None, None)
        svc.command("/app maya")
        out = svc.message("where do i start rigging in maya")
        ok = out["route"] == "rigging_knowledge" and svc.last_bundle is not None and len(svc.last_bundle.steps.steps) >= 10
        r.add(OK if ok else BAD, "ingestion answers 'where do I start' with a step list, offline (no model call)", "python -m pytest tests/test_starter_plan.py -q")
    except Exception as e:
        r.add(BAD, f"ingestion check failed: {type(e).__name__}: {str(e)[:100]}", "python -m pytest tests/test_starter_plan.py -q")


def check_applications(r: Report) -> None:
    try:
        from verification.runner import detect_apps
        for app, inst in detect_apps().items():
            r.add(OK if inst else INFO, f"{app} is installed" if inst else f"{app} not found", "")
    except Exception as e:
        r.add(INFO, f"could not look for installed applications: {type(e).__name__}", "")


def check_vision(r: Report) -> None:
    here = (ROOT / "vision" / "guide.py").exists()
    r.add(OK if here else INFO, "Umaima's live guide (vision/guide.py) is in this folder" if here else "Umaima's live guide is not in this folder: it is on her branch, see docs/demo_guide.md part 5", "")
    try:
        from vision import winplatform
        win = winplatform.find_window("Blender")
        r.add(OK if win else INFO, "a Blender window is open" if win else "no Blender window is open (open Blender 5.2 with the default layout before the vision part)", "")
    except Exception as e:
        r.add(INFO, f"vision window lookup unavailable here: {type(e).__name__}", "")
    for mod, why in (("cv2", "screen analysis"), ("mss", "screen capture"), ("winrt.windows.media.ocr", "Windows text reading for the live guide")):
        try:
            importlib.import_module(mod)
            r.add(OK, f"package {mod} ({why})")
        except Exception:
            r.add(INFO, f"package {mod} is missing ({why}; only needed for the vision part)", "pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections" if "winrt" in mod else "pip install -r requirements.txt")


def run(db_path: Path = DEMO_DB, fix: bool = False) -> Report:
    r = Report()
    check_environment(r)
    check_keys(r)
    check_database(r, db_path, fix)
    check_app_starts(r)
    check_ingestion(r)
    check_applications(r)
    check_vision(r)
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEMO_DB)
    ap.add_argument("--fix", action="store_true", help="create the demo database if it is missing")
    a = ap.parse_args(argv)
    r = run(a.db, a.fix)
    r.print()
    bad = r.problems
    print()
    print("READY for the demo (the [--] lines are optional)." if not bad else f"NOT READY: fix the {len(bad)} line(s) marked [!!] first.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
