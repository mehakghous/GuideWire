"""Logging and crash reports: redaction, the rotating log, crash reports for every kind of unhandled exception, the 'last run ended badly' marker. All local files."""
from __future__ import annotations

import logging
import sys
import threading
from collections import deque

import pytest

from shared import diagnostics as d

BS, NL = chr(92), chr(10)
GOOGLE_KEY = "AIza" + "SyD" * 4 + "abcdefghijklmnopqrstu"          # shaped like a Google API key (made up)


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.delenv("GUIDEWIRE_LOG_DIR", raising=False)
    monkeypatch.delenv("GUIDEWIRE_LOG_LEVEL", raising=False)
    for name in ("LLM_API_KEY", "GEMINI_API_KEY", "YOUTUBE_API_KEY", "SOME_TOKEN", "MY_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    saved = dict(d._state)
    d._state.update({"dir": None, "tail": deque(maxlen=d.TAIL_LINES), "context": {}, "last_throttle": {}})
    yield
    d.uninstall_crash_handlers()
    root = logging.getLogger(d.LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    d._state.update(saved)


# ---------------------------------------------------------------------------------------------- redaction
@pytest.mark.parametrize("text, gone", [
    (f"calling https://x.example/v1?key={GOOGLE_KEY}&alt=json", GOOGLE_KEY),
    (f"GEMINI_API_KEY={GOOGLE_KEY}", GOOGLE_KEY),
    ("header Authorization: Bearer abcdef1234567890abcdef", "abcdef1234567890abcdef"),
    ("OpenAI sk-abcdefghijklmnopqrstuvwx1234 was used", "sk-abcdefghijklmnopqrstuvwx1234"),
    ("login failed for umaima.fatima@example.com", "umaima.fatima@example.com"),
    ("opened C:\\Users\\umaim\\OneDrive\\Desktop\\Uni\\FYP\\app.py", "umaim"),
    ("opened C:/Users/umaim/Documents/x.txt", "umaim"),
    ("X-GuideWire-Token: 0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
    ('password="hunter2hunter2"', "hunter2hunter2"),
])
def test_secrets_and_personal_details_never_survive_redaction(text, gone):
    assert gone not in d.redact(text, secrets=[])


def test_ordinary_text_is_left_alone_and_paths_keep_their_shape():
    text = "step s02 completed by the screen in 0.31 s at C:\\Program Files\\Blender Foundation\\Blender 5.2"
    assert d.redact(text, secrets=[]) == text
    assert d.redact("C:\\Users\\umaim\\x.py", secrets=[]) == "C:\\Users\\<user>\\x.py"


def test_the_values_of_secret_environment_variables_are_masked_even_when_no_pattern_matches(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "plainvalue-with-no-known-shape")
    monkeypatch.setenv("SHORT_TOKEN", "abc")                         # too short to treat as a secret
    out = d.redact("failed with plainvalue-with-no-known-shape and abc")
    assert "plainvalue-with-no-known-shape" not in out and "abc" in out


# ---------------------------------------------------------------------------------------------- the log file
def test_logging_writes_a_rotating_file_with_redacted_lines(tmp_path):
    folder = d.setup_logging(tmp_path / "logs", level="DEBUG")
    log = d.get_logger("vision")
    log.info("probe read ok key=%s for %s", GOOGLE_KEY, "umaima@example.com")
    try:
        raise ValueError(f"bad token {GOOGLE_KEY}")
    except ValueError:
        log.exception("it failed")
    text = (folder / d.LOG_FILE).read_text(encoding="utf-8")
    assert "starting" in text and "guidewire.vision" in text and "probe read ok" in text
    assert GOOGLE_KEY not in text and "umaima@example.com" not in text and "[redacted" in text
    assert "ValueError" in text and "Traceback" in text                # the traceback is kept (redacted), not dropped


def test_the_log_rotates_instead_of_growing_forever(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "MAX_BYTES", 2000)
    monkeypatch.setattr(d, "BACKUPS", 2)
    folder = d.setup_logging(tmp_path, level="INFO")
    log = d.get_logger("spam")
    for i in range(300):
        log.info("line number %d with some padding to fill the file quickly", i)
    files = sorted(p.name for p in folder.glob("guidewire.log*"))
    assert d.LOG_FILE in files and len(files) <= 3


def test_the_level_and_folder_can_be_set_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIDEWIRE_LOG_DIR", str(tmp_path / "env"))
    monkeypatch.setenv("GUIDEWIRE_LOG_LEVEL", "WARNING")
    folder = d.setup_logging()
    d.get_logger("x").info("quiet")
    d.get_logger("x").warning("loud")
    text = (folder / d.LOG_FILE).read_text(encoding="utf-8")
    assert folder == tmp_path / "env" and "loud" in text and "quiet" not in text


def test_setup_survives_an_unwritable_folder(tmp_path, monkeypatch):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    monkeypatch.chdir(tmp_path)
    folder = d.setup_logging(blocker / "logs")                       # cannot be created: falls back instead of crashing the app
    assert folder.exists()


def test_a_repeating_message_is_logged_once_per_interval(tmp_path):
    d.setup_logging(tmp_path)
    log = d.get_logger("vision")
    assert d.log_every(log, "no-window", 60, logging.WARNING, "Blender is not visible")
    assert not d.log_every(log, "no-window", 60, logging.WARNING, "Blender is not visible")
    assert d.log_every(log, "other", 60, logging.WARNING, "different problem")
    assert (tmp_path / d.LOG_FILE).read_text(encoding="utf-8").count("Blender is not visible") == 1


# ---------------------------------------------------------------------------------------------- crash reports
def _boom():
    raise RuntimeError(f"exploded while using key={GOOGLE_KEY} for umaima@example.com")


def test_a_crash_report_has_the_traceback_versions_context_and_log_tail_and_no_secrets(tmp_path):
    d.setup_logging(tmp_path)
    d.get_logger("app").info("opened tutorial 3 (maya)")
    d.set_context("screen", lambda: "SessionScreen")
    d.set_context("broken", lambda: 1 / 0)
    try:
        _boom()
    except RuntimeError:
        path = d.write_crash_report(*sys.exc_info(), where="main thread", directory=tmp_path)
    assert path is not None and path.parent == tmp_path / "crashes"
    text = path.read_text(encoding="utf-8")
    for needle in ("GuideWire crash report", "RuntimeError", "_boom", "app: GuideWire 0.1.0", "python:", "screen: SessionScreen", "could not read: ZeroDivisionError",
                   "opened tutorial 3 (maya)", "stays on your computer"):
        assert needle in text, needle
    assert GOOGLE_KEY not in text and "umaima@example.com" not in text


def test_the_unhandled_exception_hook_writes_a_report_and_tells_the_window(tmp_path):
    d.setup_logging(tmp_path)
    told = []
    d.install_crash_handlers(notify=lambda path, msg: told.append((path, msg)), native_log=open(tmp_path / "native.log", "w"))   # noqa: SIM115
    try:
        _boom()
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    assert len(told) == 1 and told[0][0] is not None and told[0][0].exists() and "RuntimeError" in told[0][1]
    assert GOOGLE_KEY not in told[0][1] and "umaima@example.com" not in told[0][1]      # the short message for the dialog is redacted as well
    assert "crash report written" in (tmp_path / d.LOG_FILE).read_text(encoding="utf-8")


def test_an_exception_in_a_background_thread_is_caught_too(tmp_path):
    d.setup_logging(tmp_path)
    told = []
    d.install_crash_handlers(notify=lambda path, msg: told.append((path, msg)), native_log=open(tmp_path / "native.log", "w"))   # noqa: SIM115
    t = threading.Thread(target=_boom, name="vision-worker")
    t.start()
    t.join()
    assert told and told[0][0] is not None and "thread vision-worker" in told[0][0].read_text(encoding="utf-8")


def test_ctrl_c_is_not_a_crash(tmp_path):
    d.setup_logging(tmp_path)
    told = []
    d.install_crash_handlers(notify=lambda *a: told.append(a), native_log=open(tmp_path / "native.log", "w"))   # noqa: SIM115
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert not told and d.latest_report(tmp_path) is None


def test_a_failing_notifier_or_unwritable_folder_never_raises(tmp_path):
    d.setup_logging(tmp_path)
    d.install_crash_handlers(notify=lambda *a: 1 / 0, native_log=open(tmp_path / "native.log", "w"))   # noqa: SIM115
    sys.excepthook(RuntimeError, RuntimeError("x"), None)              # the notifier blows up: swallowed
    blocker = tmp_path / "plain-file"
    blocker.write_text("x")
    assert d.write_crash_report(RuntimeError, RuntimeError("x"), None, directory=blocker) is None


def test_only_the_newest_reports_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "KEEP_REPORTS", 3)
    for i in range(6):
        assert d.write_crash_report(RuntimeError, RuntimeError(str(i)), None, directory=tmp_path) is not None
    reports = sorted((tmp_path / "crashes").glob("crash-*.txt"))
    assert len(reports) == 3 and d.latest_report(tmp_path) == reports[-1] and "RuntimeError: 5" in reports[-1].read_text(encoding="utf-8")


def test_uninstall_puts_the_original_hooks_back(tmp_path):
    before = (sys.excepthook, threading.excepthook)
    d.install_crash_handlers(native_log=open(tmp_path / "native.log", "w"))   # noqa: SIM115
    assert sys.excepthook is not before[0]
    d.uninstall_crash_handlers()
    assert (sys.excepthook, threading.excepthook) == before


# ---------------------------------------------------------------------------------------------- "the last run ended badly"
def test_an_unclean_exit_is_noticed_on_the_next_start_and_a_clean_one_is_not(tmp_path):
    assert d.previous_run_ended_badly(tmp_path) is None                # first ever run
    d.mark_running(tmp_path)                                           # run 1 starts ...
    assert d.previous_run_ended_badly(tmp_path) is not None            # ... and never says goodbye: run 2 sees the marker
    d.mark_clean_exit(tmp_path)
    assert d.previous_run_ended_badly(tmp_path) is None


def test_the_marker_carries_the_process_and_version(tmp_path):
    path = d.mark_running(tmp_path)
    assert path is not None and "0.1.0" in path.read_text(encoding="utf-8")
    blocker = tmp_path / "plain-file"
    blocker.write_text("x")
    assert d.mark_running(blocker / "sub") is None                      # an unwritable place is not an error


def test_a_native_crash_log_is_turned_into_a_redacted_report_and_emptied(tmp_path):
    raw = tmp_path / d.NATIVE_LOG
    win_path = "C:" + BS + "Users" + BS + "umaim" + BS + "app" + BS + "x.py"
    raw.write_text("Windows fatal exception: access violation" + NL + NL + "Thread 0x1 (most recent call first):" + NL + '  File "' + win_path + '", line 3 in boom' + NL, encoding="utf-8")
    report = d.collect_native_crash(tmp_path)
    assert report is not None and report.parent == tmp_path / "crashes" and report.name.endswith("-native.txt")
    text = report.read_text(encoding="utf-8")
    assert "access violation" in text and "umaim" not in text and "C:" + BS + "Users" + BS + "<user>" in text and "environment" in text
    assert raw.read_text(encoding="utf-8") == ""                      # the raw file (with real paths) is emptied
    assert d.collect_native_crash(tmp_path) is None and d.collect_native_crash(tmp_path / "nowhere") is None
