"""The tutorial video inside the session screen: YouTube's own embedded player (the official IFrame player), so the learner does not leave GuideWire to watch.

Only playback and seeking are used. GuideWire reads no frames, audio or captions from the player (SRS SC-11, NFR-025), and the learner's screen capture never includes it (the capture is limited to the
application's window). The player is shown through Qt WebEngine when that is installed; when it is not (or in tests), the same space says so and offers to open the video in the browser instead.

`VideoPlayer.seek(seconds)` jumps to a step's start time; `toggle_pause()` pauses and plays.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget

_VIDEO = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,20})")
ORIGIN = "https://guidewire.local/"             # the address the page claims to be on: YouTube's player wants one


def video_id_of(url: str | None) -> str | None:
    """The 11-character id inside a YouTube link, or None when it is not one."""
    m = _VIDEO.search(url or "")
    return m.group(1) if m else None


def page_html(video_id: str, start: float = 0.0) -> str:
    """The small page that holds YouTube's IFrame player and two functions the window calls: gwSeek(seconds) and gwToggle()."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>html,body,#p{{margin:0;width:100%;height:100%;background:#1b1512;overflow:hidden}}</style></head>
<body><div id="p"></div><script>
var player = null, pending = {max(start, 0.0)};
var tag = document.createElement('script'); tag.src = "https://www.youtube.com/iframe_api"; document.head.appendChild(tag);
function onYouTubeIframeAPIReady() {{
  player = new YT.Player('p', {{width: '100%', height: '100%', videoId: '{video_id}', playerVars: {{rel: 0, playsinline: 1, origin: '{ORIGIN.rstrip('/')}'}},
    events: {{onReady: function () {{ if (pending > 0) {{ player.seekTo(pending, true); }} }}}}}});
}}
function gwSeek(s) {{ if (player && player.seekTo) {{ player.seekTo(s, true); player.playVideo(); }} else {{ pending = s; }} }}
function gwToggle() {{ if (!player || !player.getPlayerState) return; if (player.getPlayerState() == 1) {{ player.pauseVideo(); }} else {{ player.playVideo(); }} }}
</script></body></html>"""


def _minor(version: str) -> str:
    parts = (version or "").split(".")
    return ".".join(parts[:2])


_PROBE = """
import sys
from PyQt6 import QtWebEngineWidgets
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication([])
from PyQt6.QtWebEngineWidgets import QWebEngineView
v = QWebEngineView()
v.resize(320, 200)
v.show()
print("ok", flush=True)
QTimer.singleShot(400, app.quit)
sys.exit(app.exec())
"""


def _cache_file():
    import os
    from pathlib import Path
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "GuideWire" / "webengine_probe.json"


def _probe_in_a_separate_process(key: str) -> str | None:
    """Show a web view in a throw-away process and see whether it survives. On some computers Qt WebEngine imports fine and then kills the whole process the moment a web view is shown (seen on the development
    machine with every flag tried), so GuideWire never shows one in its own process before this has passed. The answer is remembered for this version of Qt and WebEngine."""
    import json
    import subprocess
    import sys
    cache = _cache_file()
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            return data.get("problem")
    except Exception:
        pass
    problem: str | None
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, timeout=25)
        problem = None if (r.returncode == 0 and b"ok" in r.stdout) else f"Qt WebEngine stops the program on this computer (exit code {r.returncode}); the video opens in the browser instead."
    except Exception as e:
        problem = f"Qt WebEngine could not be tried here ({type(e).__name__}); the video opens in the browser instead."
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "problem": problem}), encoding="utf-8")
    except Exception:
        pass
    return problem


def web_engine_problem(probe: bool = True) -> str | None:
    """Why the embedded player cannot be used here, or None when it can. Qt WebEngine must be the same Qt version as the rest of Qt (a mismatched pair imports fine and then crashes the application), and a web view
    must survive being shown on this computer: that is tried once in a separate process (`probe=False` skips it, for tests)."""
    try:
        from PyQt6 import QtWebEngineWidgets  # noqa: F401
        from PyQt6.QtCore import QT_VERSION_STR
        from PyQt6.QtWebEngineCore import qWebEngineVersion
    except Exception:
        return "Qt WebEngine is not installed (pip install PyQt6-WebEngine)."
    if _minor(qWebEngineVersion()) != _minor(QT_VERSION_STR):
        return f"Qt WebEngine {qWebEngineVersion()} does not match Qt {QT_VERSION_STR}: install the same version of both (see requirements.txt)."
    return _probe_in_a_separate_process(f"{QT_VERSION_STR}|{qWebEngineVersion()}") if probe else None


def web_engine_available() -> bool:
    return web_engine_problem() is None


class VideoPlayer(QWidget):
    def __init__(self, web: bool = True):
        """`web=False` never touches Qt WebEngine (tests, and computers without it)."""
        super().__init__()
        self.video_id: str | None = None
        self.url: str | None = None
        self.paused = False
        self.view = None
        self.open_url = lambda url: QDesktopServices.openUrl(QUrl(url))
        self.note = QLabel("")
        self.note.setObjectName("empty")
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.open_button = QPushButton("Watch it in the browser")
        self.open_button.clicked.connect(lambda: self.url and self.open_url(self.url))
        self.placeholder = QWidget()
        box = QVBoxLayout(self.placeholder)
        box.addStretch()
        box.addWidget(self.note)
        box.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addStretch()
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.placeholder)
        if web and web_engine_available():
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            self.view = QWebEngineView()
            self.stack.addWidget(self.view)
        self.setMinimumHeight(240)
        self.set_video(None, None)

    @property
    def available(self) -> bool:
        """The embedded player can be shown (Qt WebEngine is installed and was asked for)."""
        return self.view is not None

    @property
    def showing_video(self) -> bool:
        return self.view is not None and self.stack.currentWidget() is self.view

    def set_video(self, video_id: str | None, url: str | None, start: float = 0.0) -> None:
        """Show this tutorial's video. With no video id (a written or catalogue tutorial) the space says so."""
        if video_id == self.video_id and self.view is not None and video_id:
            return                                                         # already loaded: keep playing
        self.video_id, self.url, self.paused = video_id, url, False
        if not video_id:
            self.note.setText("This tutorial has no video. Its steps are on the right.")
            self.open_button.setVisible(False)
            self.stack.setCurrentWidget(self.placeholder)
            return
        if self.view is None:
            self.note.setText(f"The embedded player cannot be used here: {web_engine_problem() or 'it was switched off'} The video can be watched in the browser.")
            self.open_button.setVisible(bool(url))
            self.stack.setCurrentWidget(self.placeholder)
            return
        self.view.setHtml(page_html(video_id, start), QUrl(ORIGIN))
        self.stack.setCurrentWidget(self.view)

    def seek(self, seconds: float | None) -> None:
        """Jump to a time in the video (a step's start). Does nothing without a playing embedded video."""
        if seconds is None or not self.showing_video:
            return
        self.paused = False
        self.view.page().runJavaScript(f"gwSeek({max(float(seconds), 0.0)})")

    def toggle_pause(self) -> bool:
        """Pause or play; returns True when it is now paused."""
        if self.showing_video:
            self.view.page().runJavaScript("gwToggle()")
        self.paused = not self.paused
        return self.paused
