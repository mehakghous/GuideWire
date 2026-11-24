"""`GuideWire.exe --selftest [--selftest-out report.json]`: check that this copy of the app can actually work, without a window the user sees.

It exists because a frozen (installed) build fails in ways the source tree never does: a missing library, a data file that was not bundled, a folder that is not writable, an OCR engine
that did not load. Every check runs on its own, so one failure does not hide the others. Exit code 0 = all passed. Nothing here touches the user's real data or keys.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path


def _check_imports() -> str:
    names = ["PyQt6.QtWidgets", "cv2", "numpy", "mss", "bcrypt", "pydantic", "dotenv", "httpx", "google.genai", "youtube_transcript_api"]
    missing = []
    for n in names:
        try:
            __import__(n)
        except Exception as e:
            missing.append(f"{n} ({type(e).__name__})")
    if missing:
        raise RuntimeError("cannot import: " + ", ".join(missing))
    return f"{len(names)} libraries import"


def _check_writable() -> str:
    from shared import paths
    root = paths.writable_root()
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".selftest-write"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return f"writable folder {root}"


def _check_data() -> str:
    import importlib.util

    from shared import paths
    res = paths.resource_root()
    need = ["knowledge/rigging_knowledge.json", "knowledge/app_vocab/blender.json", "shared/examples/blender_cube_extrude.json", "vision/toolbars.json"]
    has_menus = importlib.util.find_spec("shared.menu_paths") is not None            # the exact-menu-path feature, once it is part of this build
    if has_menus:
        need += ["shared/menus/blender_menus.json", "shared/menus/maya_menus.json"]
    absent = [n for n in need if not (res / n).is_file()]
    if absent:
        raise RuntimeError("bundled files missing: " + ", ".join(absent))
    if has_menus:
        from shared.menu_paths import best_menu_path
        hit = best_menu_path("blender", "add a cube")
        if hit is None or hit.text != "Add > Mesh > Cube":
            raise RuntimeError("the Blender menu data did not resolve 'add a cube'")
    from vision.toolbar import tool_groups
    if len(tool_groups("OBJECT")) != 10:
        raise RuntimeError("the toolbar data is wrong")
    return f"{len(need)} bundled data files found" + ("; menu data resolves" if has_menus else "")


def _check_knowledge() -> str:
    from ingestion.profiles import PROFILES
    from ingestion.rigging_knowledge import load
    kb = load() if callable(load) else None
    return f"{len(PROFILES)} application profiles, rigging knowledge {'loaded' if kb is not None else 'present'}"


def _check_database() -> str:
    from app.accounts import Accounts
    from app.db import Database
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "t.sqlite"))
        Accounts(db).register("selftest@example.invalid", "a long enough password", "Selftest")
        db.close()
    return "database and password hashing work"


def _check_logging() -> str:
    from shared import diagnostics
    with tempfile.TemporaryDirectory() as d:
        diagnostics.setup_logging(d)
        diagnostics.get_logger("selftest").info("hello")
        ok = (Path(d) / diagnostics.LOG_FILE).is_file()
        import logging
        for h in list(logging.getLogger(diagnostics.LOGGER_NAME).handlers):
            logging.getLogger(diagnostics.LOGGER_NAME).removeHandler(h)
            h.close()
    if not ok:
        raise RuntimeError("no log file was written")
    return "log file written"


def _check_ocr() -> str:
    """Draw some text, read it back with the Windows OCR engine: proves the winrt packages and the language pack work in this build."""
    import cv2
    import numpy as np
    img = np.full((120, 560, 3), 255, np.uint8)
    cv2.putText(img, "GuideWire Select Edit", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    from vision.ocr import read_text
    words = " ".join(w.text for w in read_text(img, 1.5)).lower()
    if "guidewire" not in words and "select" not in words:
        raise RuntimeError(f"OCR read {words!r}")
    return "Windows OCR reads text"


def _check_window() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from app.db import Database
    from app.ui.main_window import MainWindow
    qapp = QApplication.instance() or QApplication([])
    w = MainWindow(Database(":memory:"))
    qapp.processEvents()
    w.close()
    return "main window builds"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("libraries", _check_imports), ("writable folder", _check_writable), ("bundled data", _check_data), ("knowledge", _check_knowledge),
    ("database", _check_database), ("logging", _check_logging), ("screen reading (OCR)", _check_ocr), ("window", _check_window),
]


def run(out_path: str | None = None, skip: tuple[str, ...] = ()) -> int:
    """Run the checks, write a JSON report if `out_path` is given, print a summary when there is a console. Returns 0 when every check passed."""
    from shared.version import APP_VERSION
    results = []
    for name, fn in CHECKS:
        if name in skip:
            continue
        t = time.perf_counter()
        try:
            detail, ok = fn(), True
        except Exception as e:
            detail, ok = f"{type(e).__name__}: {e}", False
            traceback.print_exc(file=sys.stderr) if sys.stderr else None
        results.append({"check": name, "ok": ok, "detail": detail, "seconds": round(time.perf_counter() - t, 2)})
    report = {"app": "GuideWire", "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)), "python": sys.version.split()[0],
              "passed": all(r["ok"] for r in results), "results": results}
    if out_path:
        Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if sys.stdout:
        for r in results:
            print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']:22} {r['detail']}")
    return 0 if report["passed"] else 1
