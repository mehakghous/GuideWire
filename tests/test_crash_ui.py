"""The window side of logging and crash reports (offscreen Qt), and the log lines the session engine, the worker and the vision bridge write."""
from __future__ import annotations

import os
import sys
from collections import deque
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import QtMsgType  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import crash_ui  # noqa: E402
from shared import diagnostics as d  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIDEWIRE_LOG_DIR", str(tmp_path / "logs"))
    saved = dict(d._state)
    d._state.update({"dir": None, "tail": deque(maxlen=d.TAIL_LINES), "context": {}, "last_throttle": {}})
    yield
    d.uninstall_crash_handlers()
    import logging
    root = logging.getLogger(d.LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    d._state.update(saved)


def _text(tmp_path) -> str:
    return (tmp_path / "logs" / d.LOG_FILE).read_text(encoding="utf-8")


def test_several_errors_in_a_row_show_one_notice_and_the_rest_are_only_logged(qapp, tmp_path):
    d.setup_logging()
    shown = []
    n = crash_ui.CrashNotifier(None, show=lambda parent, path, msg: shown.append(msg))
    for i in range(5):
        n.notify(None, f"error {i}")
    qapp.processEvents()
    assert shown == ["error 0"]                                       # the others came within the quiet period
    assert "another error while a notice was already shown" in _text(tmp_path)


def test_the_notice_limit_per_run_is_respected(qapp, monkeypatch):
    monkeypatch.setattr(crash_ui, "MIN_SECONDS_BETWEEN_NOTICES", 0)
    monkeypatch.setattr(crash_ui, "MAX_NOTICES_PER_RUN", 2)
    shown = []
    n = crash_ui.CrashNotifier(None, show=lambda parent, path, msg: shown.append(msg))
    for i in range(5):
        n.notify(None, f"error {i}")
        qapp.processEvents()
    assert shown == ["error 0", "error 1"]


def test_an_error_on_a_background_thread_reaches_the_window_thread(qapp, tmp_path):
    import threading
    d.setup_logging()
    shown = []
    notifier = crash_ui.CrashNotifier(None, show=lambda parent, path, msg: shown.append((path, msg)))
    d.install_crash_handlers(notify=notifier.notify, native_log=open(tmp_path / "native.log", "w"))   # noqa: SIM115

    def boom():
        raise RuntimeError("worker exploded")
    t = threading.Thread(target=boom, name="vision-worker")
    t.start()
    t.join()
    qapp.processEvents()
    assert len(shown) == 1 and shown[0][0] is not None and shown[0][0].exists() and "worker exploded" in shown[0][1]


def test_qt_messages_go_to_the_log_and_known_noise_does_not(qapp, tmp_path):
    d.setup_logging()
    crash_ui._qt_message(QtMsgType.QtWarningMsg, None, "QWidget: something odd")
    crash_ui._qt_message(QtMsgType.QtWarningMsg, None, "qt.qpa.window: SetProcessDpiAwarenessContext() failed: Access is denied.")
    text = _text(tmp_path)
    assert "guidewire.qt" in text and "something odd" in text and "SetProcessDpiAwarenessContext" not in text


def test_install_starts_logging_marks_the_run_and_reports_the_previous_unclean_exit(qapp, tmp_path, monkeypatch):
    notices = []
    monkeypatch.setattr(crash_ui, "show_unclean_exit_notice", lambda parent, started: notices.append(started))
    monkeypatch.setattr(crash_ui, "qInstallMessageHandler", lambda handler: None)
    folder = tmp_path / "logs"
    d.mark_running(folder)                                            # the previous run never said goodbye
    crash_ui.install(qapp, None, context={"screen": lambda: "Home"})
    assert len(notices) == 1 and (folder / d.MARKER).exists() and sys.excepthook is not sys.__excepthook__
    assert "did not exit cleanly" in _text(tmp_path) and d.build_report(None, None, None).count("screen: Home") == 1
    d.mark_clean_exit()
    d.uninstall_crash_handlers()
    crash_ui.install(qapp, None, notify_unclean=True)                 # a clean previous run: no notice
    assert len(notices) == 1


def test_the_profile_screen_buttons_open_the_logs_and_say_so_when_there_is_no_report(qapp, monkeypatch):
    from app.accounts import Accounts
    from app.db import Database
    from app.ui.screens import ProfileScreen
    screen = ProfileScreen(Accounts(Database(":memory:")))
    opened = []
    monkeypatch.setattr(crash_ui, "open_log_folder", lambda: opened.append("logs") or True)
    monkeypatch.setattr(crash_ui, "open_latest_report", lambda: False)
    screen.logs_button.click()
    assert opened == ["logs"] and screen.message.text() == ""
    screen.report_button.click()
    assert "no crash report" in screen.message.text().lower()
    monkeypatch.setattr(crash_ui, "open_log_folder", lambda: False)
    screen.logs_button.click()
    assert "Could not open the folder" in screen.message.text()


def test_a_failing_background_task_is_logged_not_lost(qapp, tmp_path):
    from app.ui.workers import run_call
    d.setup_logging()
    results = []
    run_call(None, lambda _s: 1 / 0, results.append, sync=True)
    assert isinstance(results[0], ZeroDivisionError)                  # the caller still gets the error ...
    assert "background task failed" in _text(tmp_path) and "ZeroDivisionError" in _text(tmp_path)     # ... and so does the log


def test_session_progress_is_logged_without_personal_details(tmp_path):
    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    d.setup_logging()
    db = Database(":memory:")
    uid = db.add_user("umaima@example.com", b"h")
    tid = StepEditor.from_json_file(Path("shared/examples/blender_cube_extrude.json")).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    e.complete(by="observed")
    e.back()
    text = _text(tmp_path)
    assert "started (blender, 4 steps)" in text and "step 1/4 done by observed" in text and "back to step 1/4" in text
    assert "umaima@example.com" not in text


def test_the_vision_bridge_logs_what_it_decided(tmp_path):
    from app import vision_bridge as vb
    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    from tests.test_app_vision_bridge import FakeService
    d.setup_logging()
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(Path("shared/examples/blender_cube_extrude.json")).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    e.complete()                                                      # s02 "Enter Edit Mode"
    svc = FakeService(observed={"mode": "EDIT_MESH"})
    bridge = vb.VisionBridge(lambda app: svc)
    bridge.tick(e)                                                    # already true when the step started
    svc.observed = {"mode": "OBJECT"}
    bridge.tick(e)
    svc.observed = {"mode": "EDIT_MESH"}
    bridge.tick(e)                                                    # seen to become true: completed
    text = _text(tmp_path)
    assert "already true when it started" in text and "completed because the screen saw it become true" in text


def test_a_vision_service_that_cannot_start_is_logged_once(tmp_path):
    from app import vision_bridge as vb
    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    d.setup_logging()
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(Path("shared/examples/blender_cube_extrude.json")).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()

    def factory(app):
        raise ImportError("No module named 'winrt'")
    bridge = vb.VisionBridge(factory)
    for _ in range(4):
        bridge.tick(e)
    assert _text(tmp_path).count("screen guidance unavailable for blender") == 1
