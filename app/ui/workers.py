"""Run a slow call (an AI model, a video) off the window's thread, so the window never freezes, and hand the result back on the window's thread."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class Worker(QThread):
    """`fn(on_status)` runs in the background; `done` carries its result, or the exception it raised."""
    done = pyqtSignal(object)
    status = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(self.status.emit))
        except Exception as e:                    # never let a background error close the app
            self.done.emit(e)


def run_call(owner, fn, on_done, on_status=None, sync: bool = False) -> None:
    """Start `fn` in a Worker kept alive on `owner`; in `sync` mode (tests) run it right here."""
    if sync:
        try:
            result = fn(on_status or (lambda _m: None))
        except Exception as e:
            result = e
        on_done(result)
        return
    w = Worker(fn, owner)
    owner._worker = w                              # keep a reference so the thread is not collected while it runs
    w.done.connect(on_done)
    if on_status is not None:
        w.status.connect(on_status)
    w.start()
