"""The window side of logging and crash reports (the logic is `shared/diagnostics.py`).

* An unhandled error on ANY thread: the learner sees one short, calm notice ("GuideWire hit a problem and saved a report on this computer; nothing was sent anywhere")
  with Open folder / Copy path / Continue. Several errors in a row show at most one notice, so a loop of failures cannot bury the window in dialogs; every one is still logged.
* The next start after an unclean exit (a native crash, a killed process) says so and points at the log folder.
* Qt's own warnings and fatal messages go to the log instead of vanishing on a console nobody sees.
* The Profile screen has "Open logs folder" and "Open last crash report".
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QtMsgType, QUrl, pyqtSignal, qInstallMessageHandler
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from shared import diagnostics

MIN_SECONDS_BETWEEN_NOTICES = 8
MAX_NOTICES_PER_RUN = 3

_QT_LEVELS = {QtMsgType.QtDebugMsg: 10, QtMsgType.QtInfoMsg: 20, QtMsgType.QtWarningMsg: 30, QtMsgType.QtCriticalMsg: 40, QtMsgType.QtFatalMsg: 50}
_QT_NOISE = ("qt.qpa.window: SetProcessDpiAwarenessContext", "Qt's default DPI awareness", "QFont::setPointSize")      # known harmless lines (see docs)


def open_log_folder() -> bool:
    folder = diagnostics.log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_latest_report() -> bool:
    report = diagnostics.latest_report()
    return bool(report) and QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))


def _qt_message(kind: QtMsgType, context, message: str) -> None:
    if any(n in message for n in _QT_NOISE):
        return
    log = diagnostics.get_logger("qt")
    log.log(_QT_LEVELS.get(kind, 30), "%s", message)


class CrashNotifier(QObject):
    """Receives crash notices from any thread (the signal is queued onto the window's thread) and shows at most one notice at a time."""
    crashed = pyqtSignal(object, str)

    def __init__(self, parent: QWidget | None = None, show: Callable[[QWidget | None, Path | None, str], None] | None = None) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._show = show or show_crash_notice
        self._last = 0.0
        self._count = 0
        self.crashed.connect(self._on_crashed, Qt.ConnectionType.QueuedConnection)

    def notify(self, path: Path | None, message: str) -> None:           # called from the crash hook, on whatever thread crashed
        self.crashed.emit(path, message)

    def _on_crashed(self, path, message: str) -> None:
        now = time.monotonic()
        if self._count >= MAX_NOTICES_PER_RUN or (self._count and now - self._last < MIN_SECONDS_BETWEEN_NOTICES):
            diagnostics.get_logger("crash").warning("another error while a notice was already shown: %s", message[:200])
            return
        self._count, self._last = self._count + 1, now
        self._show(self._parent_widget, path, message)


def show_crash_notice(parent: QWidget | None, path: Path | None, message: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("GuideWire hit a problem")
    box.setText("GuideWire hit a problem. You can keep working, and your steps and progress are saved.")
    detail = f"{message[:300]}\n\n" + (f"A report was saved on this computer:\n{path}\n\n" if path else "A report could not be saved.\n\n")
    box.setInformativeText("Nothing was sent anywhere. If you want help, you can share the report file yourself.")
    box.setDetailedText(detail)
    open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
    copy_button = box.addButton("Copy path", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is open_button:
        open_log_folder()
    elif clicked is copy_button and path is not None:
        QApplication.clipboard().setText(str(path))


def show_unclean_exit_notice(parent: QWidget | None, started: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("GuideWire closed unexpectedly last time")
    box.setText("GuideWire did not close normally the last time it ran. Your saved tutorials and progress are safe.")
    box.setInformativeText("A log of what happened is on this computer. Nothing was sent anywhere.")
    box.setDetailedText(f"Previous run: {started}\nLog folder: {diagnostics.log_dir()}")
    open_button = box.addButton("Open logs folder", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    if box.clickedButton() is open_button:
        open_log_folder()


def install(app: QApplication, window: QWidget | None = None, context: dict[str, Callable[[], object]] | None = None, notify_unclean: bool = True) -> CrashNotifier:
    """Start logging, catch crashes, route Qt messages to the log, and tell the learner if the last run ended badly. Returns the notifier (kept alive by the caller)."""
    diagnostics.setup_logging()
    started = diagnostics.previous_run_ended_badly()                      # before marking this run
    diagnostics.mark_running()
    native = diagnostics.collect_native_crash()                           # a native crash last time becomes a redacted report now
    notifier = CrashNotifier(window)
    diagnostics.install_crash_handlers(notify=notifier.notify)
    qInstallMessageHandler(_qt_message)
    for name, provider in (context or {}).items():
        diagnostics.set_context(name, provider)
    app.aboutToQuit.connect(diagnostics.mark_clean_exit)
    log = diagnostics.get_logger("app")
    if native:
        log.warning("the previous run crashed natively; report saved as %s", native)
    if started:
        log.warning("the previous run did not exit cleanly (started %s)", started)
        if notify_unclean:
            show_unclean_exit_notice(window, started)
    return notifier
