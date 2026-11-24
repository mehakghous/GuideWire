"""Logging and crash reports. Local only: nothing here sends anything anywhere (the project rule is that only AI-gateway data leaves the app).

* `setup_logging()` writes a rotating log (`guidewire.log`, 1 MB x 5) under `%LOCALAPPDATA%/GuideWire/logs` (override: `GUIDEWIRE_LOG_DIR`; level: `GUIDEWIRE_LOG_LEVEL`).
  Every record passes a redaction filter: API keys and tokens, passwords, e-mail addresses and the Windows user name in paths never reach the file.
* `install_crash_handlers()` catches unhandled exceptions on any thread and native crashes, and writes a crash report to `.../logs/crashes/`: the redacted traceback, the
  versions of everything involved, and the last log lines. The learner decides whether to share the file; the app never uploads it.
* A `running.marker` file exists while the app runs and is removed on a clean exit, so the next start can tell the learner "last time ended unexpectedly" even when
  the process died without a Python exception (a native crash, a killed process).

Qt-free and pure enough to test: the window part (a dialog, "Open folder") is `app/crash_ui.py`.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import platform
import re
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Mapping
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, TextIO

from shared.version import APP_NAME, APP_VERSION

LOGGER_NAME = "guidewire"
LOG_FILE = "guidewire.log"
MAX_BYTES, BACKUPS = 1_000_000, 5
TAIL_LINES = 200                      # log lines copied into a crash report
KEEP_REPORTS = 20
MARKER = "running.marker"

_SECRET_NAME = re.compile(r"(key|token|secret|password|passwd|credential)", re.I)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "[redacted-google-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[redacted-api-key]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)\b(api[_-]?key|key|token|secret|password|passwd|x-guidewire-token)\b(\s*[=:]\s*)[\"']?[^\s\"'&,;]{4,}"), r"\1\2[redacted]"),
    (re.compile(r"(?i)([?&](?:key|token|api_key|apikey|access_token)=)[^&\s\"']+"), r"\1[redacted]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[redacted-email]"),
    (re.compile(r"(?i)([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\s\"']+"), r"\1<user>"),
    (re.compile(r"(?i)(/Users/|/home/)[^/\s\"']+"), r"\1<user>"),
]


# ------------------------------------------------------------------------------------------------------------------------------ redaction
def _secret_values(env: Mapping[str, str] | None = None) -> list[str]:
    """Values of environment variables that look like secrets (their NAME says so), longest first, so exact occurrences are masked even if no pattern matches."""
    source: Mapping[str, str] = os.environ if env is None else env
    vals = {v for k, v in source.items() if _SECRET_NAME.search(k) and len(v) >= 8}
    return sorted(vals, key=len, reverse=True)


def redact(text: str, secrets: list[str] | None = None) -> str:
    """The text with keys, tokens, passwords, e-mail addresses and the user name in paths masked."""
    for s in (_secret_values() if secrets is None else secrets):
        text = text.replace(s, "[redacted-secret]")
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Redacts the formatted message, and the traceback text, of every record before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg, record.args = redact(message), None
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


# ------------------------------------------------------------------------------------------------------------------------------ places
def log_dir(override: str | os.PathLike[str] | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("GUIDEWIRE_LOG_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME / "logs"


def crash_dir(directory: Path | None = None) -> Path:
    return (directory or log_dir()) / "crashes"


# ------------------------------------------------------------------------------------------------------------------------------ logging
_state: dict[str, Any] = {"dir": None, "handler": None, "tail": deque(maxlen=TAIL_LINES), "context": {}, "last_throttle": {}}


class _TailHandler(logging.Handler):
    """Keeps the last formatted lines in memory, so a crash report has them even if the file cannot be read."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _state["tail"].append(self.format(record))
        except Exception:
            pass


def setup_logging(directory: str | os.PathLike[str] | None = None, level: str | int | None = None, console: bool = False) -> Path:
    """Start logging to a rotating file. Safe to call again (it replaces the handlers). Returns the log directory."""
    folder = log_dir(directory)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:                                              # an unwritable folder must never stop the app: fall back to a temp-like folder next to the data
        folder = Path("local_data") / "logs"
        folder.mkdir(parents=True, exist_ok=True)
    lvl = level if level is not None else os.environ.get("GUIDEWIRE_LOG_LEVEL", "INFO")
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(lvl if isinstance(lvl, int) else str(lvl).upper())
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s")
    handlers: list[logging.Handler] = [RotatingFileHandler(folder / LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"), _TailHandler()]
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactingFilter())
        root.addHandler(h)
    root.propagate = False
    _state["dir"], _state["tail"] = folder, deque(maxlen=TAIL_LINES)
    logging.getLogger(LOGGER_NAME).info("%s %s starting (Python %s, %s)", APP_NAME, APP_VERSION, platform.python_version(), platform.platform())
    return folder


def get_logger(name: str) -> logging.Logger:
    """A logger under the app's tree: `get_logger("vision")` -> `guidewire.vision`."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if not name.startswith(LOGGER_NAME) else name)


def log_every(log: logging.Logger, key: str, seconds: float, level: int, msg: str, *args: Any) -> bool:
    """Log at most once per `seconds` for the same `key`: something that happens on every tick (a window that is not visible) must not fill the file."""
    now = time.monotonic()
    last = _state["last_throttle"].get(key)
    if last is not None and now - last < seconds:
        return False
    _state["last_throttle"][key] = now
    log.log(level, msg, *args)
    return True


def set_context(name: str, provider: Callable[[], Any]) -> None:
    """Register something worth putting in a crash report, evaluated only when one is written (the current screen, the open tutorial's app, the vision state)."""
    _state["context"][name] = provider


# ------------------------------------------------------------------------------------------------------------------------------ crash reports
def environment() -> dict[str, str]:
    info = {"app": f"{APP_NAME} {APP_VERSION}", "python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine()}
    try:
        from shared.step_record import SCHEMA_VERSION
        info["step schema"] = SCHEMA_VERSION
    except Exception:
        pass
    for mod, label in (("PyQt6.QtCore", "PyQt6"), ("cv2", "opencv"), ("numpy", "numpy"), ("mss", "mss")):
        try:
            m = __import__(mod, fromlist=["x"])
            info[label] = str(getattr(m, "PYQT_VERSION_STR", None) or getattr(m, "__version__", "installed"))
        except Exception:
            info[label] = "not installed"
    return info


def _tail_lines(directory: Path) -> list[str]:
    lines = list(_state["tail"])
    if lines:
        return lines
    try:
        return (directory / LOG_FILE).read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]
    except OSError:
        return []


def build_report(exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None, where: str = "main thread", directory: Path | None = None) -> str:
    """The text of a crash report. Everything in it is redacted."""
    folder = directory or _state["dir"] or log_dir()
    out = [f"{APP_NAME} crash report", f"time: {datetime.now().astimezone().isoformat(timespec='seconds')}", f"where: {where}", ""]
    out.append("== what happened ==")
    out.append("".join(traceback.format_exception(exc_type, exc, tb)).rstrip() if exc_type is not None else "(no Python exception: the previous run ended unexpectedly)")
    out += ["", "== environment =="] + [f"{k}: {v}" for k, v in environment().items()]
    ctx = {}
    for name, provider in dict(_state["context"]).items():
        try:
            ctx[name] = provider()
        except Exception as e:                                   # a broken provider must not stop the report
            ctx[name] = f"(could not read: {type(e).__name__})"
    if ctx:
        out += ["", "== context =="] + [f"{k}: {v}" for k, v in ctx.items()]
    out += ["", f"== last {TAIL_LINES} log lines =="] + _tail_lines(folder)
    out += ["", "This file stays on your computer. GuideWire never sends it anywhere; share it only if you choose to."]
    return redact("\n".join(out))


def write_crash_report(exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None, where: str = "main thread",
                       directory: Path | None = None) -> Path | None:
    """Write a report and return its path, or None when even that failed (it never raises: a crash handler that crashes hides the real problem)."""
    try:
        folder = crash_dir(directory)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.txt"
        path.write_text(build_report(exc_type, exc, tb, where, directory), encoding="utf-8")
        for old in sorted(folder.glob("crash-*.txt"))[:-KEEP_REPORTS]:
            try:
                old.unlink()
            except OSError:
                pass
        return path
    except Exception:
        return None


Notifier = Callable[[Path | None, str], None]
_notify: Notifier | None = None
_installed: dict[str, Any] = {}


def _handle(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None, where: str) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    log = get_logger("crash")
    try:
        log.critical("unhandled exception in %s: %s: %s", where, exc_type.__name__, exc, exc_info=(exc_type, exc, tb))
    except Exception:
        pass
    path = write_crash_report(exc_type, exc, tb, where)
    if path is not None:
        try:
            log.critical("crash report written to %s", path)
        except Exception:
            pass
    if _notify is not None:
        try:
            _notify(path, redact(f"{exc_type.__name__}: {exc}"))             # what the dialog shows is redacted too
        except Exception:
            pass


def install_crash_handlers(notify: Notifier | None = None, native_log: TextIO | None = None) -> None:
    """Catch unhandled exceptions on every thread, unraisable ones, and native crashes. `notify(report_path, short_message)` tells the learner (the window does)."""
    global _notify
    _notify = notify
    if "excepthook" not in _installed:
        _installed["excepthook"], _installed["thread"], _installed["unraisable"] = sys.excepthook, threading.excepthook, sys.unraisablehook
    sys.excepthook = lambda t, e, tb: _handle(t, e, tb, "main thread")
    threading.excepthook = lambda a: _handle(a.exc_type, a.exc_value if a.exc_value is not None else a.exc_type(), a.exc_traceback, f"thread {getattr(a.thread, 'name', '?')}")
    sys.unraisablehook = lambda u: _handle(type(u.exc_value) if u.exc_value is not None else RuntimeError, u.exc_value or RuntimeError(u.err_msg or "unraisable exception"),
                                           u.exc_traceback, "unraisable (" + (u.err_msg or "") + ")")
    folder = _state["dir"] or log_dir()
    try:
        if native_log is None:
            folder.mkdir(parents=True, exist_ok=True)
            native_log = open(folder / "native-crash.log", "a", encoding="utf-8")        # noqa: SIM115 (kept open for the life of the process: faulthandler writes to it)
        _installed["native"] = native_log
        faulthandler.enable(native_log, all_threads=True)
    except Exception:
        pass


NATIVE_LOG = "native-crash.log"


def collect_native_crash(directory: Path | None = None) -> Path | None:
    """Python's crash handler (faulthandler) writes straight to `native-crash.log` when the process dies without an exception, with raw paths. At the next start,
    turn whatever it wrote into a REDACTED crash report and empty the raw file. Call before `install_crash_handlers`. Returns the new report, or None."""
    folder = directory or _state["dir"] or log_dir()
    raw = folder / NATIVE_LOG
    try:
        text = raw.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        reports = crash_dir(folder)
        reports.mkdir(parents=True, exist_ok=True)
        body = ["GuideWire crash report", "where: the process ended without a Python exception (a native crash)", "", "== what Python saw ==", text, "",
                "== environment =="] + [f"{k}: {v}" for k, v in environment().items()]
        body += ["", "This file stays on your computer. GuideWire never sends it anywhere; share it only if you choose to."]
        path = reports / f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-native.txt"
        path.write_text(redact("\n".join(body)), encoding="utf-8")
        raw.write_text("", encoding="utf-8")
        return path
    except OSError:
        return None


def uninstall_crash_handlers() -> None:
    """Put the original hooks back (tests, and a clean shutdown)."""
    global _notify
    _notify = None
    if "excepthook" in _installed:
        sys.excepthook, threading.excepthook, sys.unraisablehook = _installed.pop("excepthook"), _installed.pop("thread"), _installed.pop("unraisable")
    try:
        faulthandler.disable()
    except Exception:
        pass
    native = _installed.pop("native", None)
    if native is not None:
        try:
            native.close()
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------------------------------------ "did the last run end badly?"
def mark_running(directory: Path | None = None) -> Path | None:
    """Create the marker that says the app is running. If it already exists the previous run did not exit cleanly."""
    try:
        folder = directory or _state["dir"] or log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / MARKER
        path.write_text(f"{os.getpid()} {datetime.now().astimezone().isoformat(timespec='seconds')} {APP_VERSION}\n", encoding="utf-8")
        return path
    except OSError:
        return None


def previous_run_ended_badly(directory: Path | None = None) -> str | None:
    """Text from the marker the previous run left behind (when it started), or None when it exited cleanly. Call BEFORE `mark_running`."""
    try:
        text = ((directory or _state["dir"] or log_dir()) / MARKER).read_text(encoding="utf-8").strip()
        return text or "unknown"
    except OSError:
        return None


def mark_clean_exit(directory: Path | None = None) -> None:
    folder = directory or _state["dir"] or log_dir()
    try:
        (folder / MARKER).unlink(missing_ok=True)
    except OSError:
        pass


def latest_report(directory: Path | None = None) -> Path | None:
    reports = sorted(crash_dir(directory).glob("crash-*.txt"))
    return reports[-1] if reports else None
