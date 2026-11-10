"""Find a tutorial: describe what you want to learn, get up to three suggested videos.

Wraps `app.discovery.find_tutorials`. Each suggestion can be opened in the browser, or turned into steps (that opens "New from text or video link" with the link filled in).
A suggestion is judged from the video's title, channel and length only, and the screen says so.
"""
from __future__ import annotations

import html

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTextBrowser, QWidget

from ..discovery import DiscoveryResult, Suggestion
from ..pipeline import APPS
from .bento import Tile, header, page_grid
from .workers import run_call

FROM_WORDS = "(from my words)"


class FindScreen(QWidget):
    back = pyqtSignal()
    make_steps = pyqtSignal(str, str)              # video url, application ("" when not known)

    def __init__(self, sync: bool = False):
        super().__init__()
        self.sync = sync
        self.finder = None                          # set by the main window: (goal, app or None) -> DiscoveryResult. None = not available
        self.open_url = lambda url: QDesktopServices.openUrl(QUrl(url))
        self.result: DiscoveryResult | None = None
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("What do you want to learn? e.g. I am a beginner and want to rig a leg with IK in Maya")
        self.app = QComboBox()
        self.app.addItem(FROM_WORDS)
        self.app.addItems(APPS)
        self.search_button = QPushButton("Find tutorials")
        self.search_button.setObjectName("primary")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setObjectName("hint")
        self.results = QListWidget()
        self.details = QTextBrowser()
        self.open_button = QPushButton("Open in browser")
        self.steps_button = QPushButton("Turn this video into steps")
        self.back_button = QPushButton("Back")
        for b in (self.open_button, self.steps_button):
            b.setEnabled(False)
        self.search_button.clicked.connect(self.search)
        self.goal.returnPressed.connect(self.search)
        self.results.currentRowChanged.connect(self._show)
        self.open_button.clicked.connect(lambda: (s := self.selected()) and self.open_url(s.url))
        self.steps_button.clicked.connect(lambda: (s := self.selected()) and self.make_steps.emit(s.url, self.result.app or ""))
        self.back_button.clicked.connect(self.back.emit)
        grid = page_grid(self)
        grid.addWidget(header("Find a tutorial", "Say what you want to learn and get up to three suggested videos.", back=self.back_button), 0, 0, 1, 2)
        search = Tile("What do you want to learn?", variant="soft")
        search.body.addWidget(self.goal)
        row = QHBoxLayout()
        row.addWidget(QLabel("Application"))
        row.addWidget(self.app)
        row.addStretch()
        row.addWidget(self.search_button)
        search.body.addLayout(row)
        search.body.addWidget(self.message)
        found = Tile("Suggestions")
        found.body.addWidget(self.results, 1)
        about = Tile("About this video")
        about.body.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.steps_button)
        about.body.addLayout(buttons)
        grid.addWidget(search, 1, 0, 1, 2)
        grid.addWidget(found, 2, 0)
        grid.addWidget(about, 2, 1)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        self.reset()

    def reset(self) -> None:
        self.result = None
        self.results.clear()
        self.details.setHtml("")
        self.open_button.setEnabled(False)
        self.steps_button.setEnabled(False)
        self.message.setText("Describe what you want to learn. GuideWire searches YouTube and suggests up to three videos." if self.finder else "Finding tutorials is not available on this computer.")

    def prefill(self, goal: str, app: str | None = None) -> None:
        self.goal.setText(goal)
        self.app.setCurrentText(app if app in APPS else FROM_WORDS)

    def selected(self) -> Suggestion | None:
        i = self.results.currentRow()
        return self.result.suggestions[i] if self.result and 0 <= i < len(self.result.suggestions) else None

    def search(self) -> None:
        goal = self.goal.text().strip()
        if not goal or self.finder is None:
            return
        app = self.app.currentText()
        app = None if app == FROM_WORDS else app
        self.search_button.setEnabled(False)
        self.message.setText("Searching YouTube...")
        run_call(self, lambda _status: self.finder(goal, app), self._on_result, sync=self.sync)

    def _on_result(self, result) -> None:
        self.search_button.setEnabled(True)
        self.results.clear()
        self.details.setHtml("")
        if isinstance(result, Exception):
            self.result = None
            self.message.setText(f"Sorry, the search failed ({type(result).__name__}). Try again.")
            return
        self.result = result
        for s in result.suggestions:
            self.results.addItem(f"{s.title}   ({s.summary})")
        src = {"live": "Live YouTube results", "saved": "Saved from an earlier search today", "local": "From GuideWire's small local list"}.get(result.source, "")
        self.message.setText((result.message + " " if result.message else "") + (f"{src}: {len(result.suggestions)} suggestion(s). Pick one to see why." if result.suggestions else ""))
        if result.suggestions:
            self.results.setCurrentRow(0)

    def _show(self, _row: int) -> None:
        s = self.selected()
        self.open_button.setEnabled(s is not None)
        self.steps_button.setEnabled(s is not None)
        if s is None or self.result is None:
            return
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in self.result.notes)
        self.details.setHtml(f"<h3>{html.escape(s.title)}</h3><p>{html.escape(s.summary)}<br><a href='{html.escape(s.url)}'>{html.escape(s.url)}</a></p><p>{html.escape(s.note)}</p><ul>{notes}</ul>")
