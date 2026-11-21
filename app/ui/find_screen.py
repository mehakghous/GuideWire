"""Find a tutorial: describe what you want to learn, get up to three suggested videos.

Wraps `app.discovery.find_tutorials`. Each suggestion can be opened in the browser, or turned into steps (that opens "New from text or video link" with the link filled in).
A suggestion is judged from the video's title, channel and length only, and the screen says so.

The screen is PERSISTENT: leaving it and coming back shows the same search and results, and every search is saved for the signed-in learner (`Database.save_search`), so after a restart the last one is
still there and the HISTORY section can open any earlier one again without a new search (no quota spent). Thumbnails are never stored (SRS NFR-025): they are fetched again when a saved search opens.

Every suggestion is a CARD that shows its whole text (title, channel, length, year and why it was suggested) wrapped, in a list that scrolls, and the whole page scrolls too, so nothing is cut off.
"""
from __future__ import annotations

import html

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget

from .. import thumbnails
from ..db import Database
from ..discovery import DiscoveryResult, Suggestion, friendly_note, friendly_notes
from ..pipeline import APPS
from .bento import HeroTile, Tile, header, page_grid, tidy_list
from .workers import run_call

FROM_WORDS = "(from my words)"
THUMB_W, THUMB_H = 128, 72


class SuggestionCard(QFrame):
    """One suggested video: its picture beside its title, channel / length / year and the reason it was suggested, all in full."""
    clicked = pyqtSignal(int)

    def __init__(self, index: int, s: Suggestion):
        super().__init__()
        self.index = index
        self.setObjectName("card")
        self.setProperty("selected", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.has_picture = False
        self.picture = QLabel("")
        self.picture.setFixedSize(THUMB_W, THUMB_H)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setVisible(False)                                   # no picture (yet): the text uses the whole card
        self.title = QLabel(s.title)
        self.title.setObjectName("cardTitle")
        self.meta = QLabel(s.summary)
        self.meta.setObjectName("cardMeta")
        self.note = QLabel(friendly_note(s.note))
        self.note.setObjectName("cardMeta")
        for lab in (self.title, self.meta, self.note):
            lab.setWordWrap(True)
            lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)      # takes the card's width and wraps: never pushes the list sideways, never elided
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.meta.setVisible(bool(s.summary))
        self.note.setVisible(bool(self.note.text()))
        self.picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(self.title)
        texts.addWidget(self.meta)
        texts.addWidget(self.note)
        texts.addStretch(1)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 14, 10)
        row.setSpacing(12)
        row.addWidget(self.picture, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        self.setToolTip(s.title)

    def set_picture(self, pix: QPixmap) -> None:
        self.picture.setPixmap(pix.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.picture.setVisible(True)
        self.has_picture = True

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class CardList(QScrollArea):
    """A vertical, scrolling list of suggestion cards with one selected. A small stand-in for QListWidget (count, currentRow, setCurrentRow, currentRowChanged) that can show wrapped text and pictures."""
    currentRowChanged = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("resultScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards: list[SuggestionCard] = []
        self._row = -1
        inner = QWidget()
        self._box = QVBoxLayout(inner)
        self._box.setContentsMargins(0, 0, 6, 0)
        self._box.setSpacing(8)
        self._box.addStretch(1)
        self.setWidget(inner)

    def clear(self) -> None:
        for c in self.cards:
            self._box.removeWidget(c)
            c.deleteLater()
        self.cards, self._row = [], -1

    def add(self, s: Suggestion) -> SuggestionCard:
        card = SuggestionCard(len(self.cards), s)
        card.clicked.connect(self.setCurrentRow)
        self._box.insertWidget(self._box.count() - 1, card)
        self.cards.append(card)
        return card

    def count(self) -> int:
        return len(self.cards)

    def card(self, i: int) -> SuggestionCard:
        return self.cards[i]

    def currentRow(self) -> int:  # noqa: N802 (mirrors QListWidget)
        return self._row

    def setCurrentRow(self, row: int) -> None:  # noqa: N802
        row = row if 0 <= row < len(self.cards) else -1
        if row == self._row:
            return
        self._row = row
        for i, c in enumerate(self.cards):
            c.set_selected(i == row)
        self.currentRowChanged.emit(row)


class FindScreen(QWidget):
    back = pyqtSignal()
    make_steps = pyqtSignal(str, str)              # video url, application ("" when not known)

    def __init__(self, sync: bool = False):
        super().__init__()
        self.sync = sync
        self.finder = None                          # set by the main window: (goal, app or None) -> DiscoveryResult. None = not available
        self.open_url = lambda url: QDesktopServices.openUrl(QUrl(url))
        self.thumbnail_fetcher = thumbnails.fetch_all          # ([video id]) -> {video id: image bytes}; tests give a fake, so no network is used
        self.pictures: dict[str, QPixmap] = {}                 # in memory only
        self.result: DiscoveryResult | None = None
        self.db: Database | None = None
        self.user_id: int | None = None
        self.history_rows: list[dict] = []
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
        self.results = CardList()
        self.thumb = QLabel("")                                  # the larger picture of the chosen video
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.thumb.setVisible(False)
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        self.open_button = QPushButton("Open in browser")
        self.steps_button = QPushButton("Turn this video into steps")
        self.back_button = QPushButton("Back")
        self.history = QListWidget()                             # earlier searches, newest first
        tidy_list(self.history)
        self.history_empty = QLabel("Nothing yet. Every search you make is kept here, so you can open it again without searching.")
        self.history_empty.setObjectName("tileHint")
        self.history_empty.setWordWrap(True)
        self.forget_button = QPushButton("Remove from history")
        self.clear_button = QPushButton("Clear history")
        for b in (self.open_button, self.steps_button, self.forget_button, self.clear_button):
            b.setEnabled(False)
        self.search_button.clicked.connect(self.search)
        self.goal.returnPressed.connect(self.search)
        self.results.currentRowChanged.connect(self._show)
        self.open_button.clicked.connect(lambda: (s := self.selected()) and self.open_url(s.url))
        self.steps_button.clicked.connect(lambda: (s := self.selected()) and self.make_steps.emit(s.url, self.result.app or ""))
        self.back_button.clicked.connect(self.back.emit)
        self.history.currentRowChanged.connect(self._history_picked)
        self.forget_button.clicked.connect(self.forget_selected)
        self.clear_button.clicked.connect(self.clear_history)
        content = QWidget()                                      # the page scrolls as a whole, so the suggestions and their descriptions can always be reached
        grid = page_grid(content)
        grid.addWidget(header("Find a tutorial", "Say what you want to learn and get up to three suggested videos.", back=self.back_button, kicker="Discover"), 0, 0, 1, 2)
        search = HeroTile("What do you want to learn?")
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
        about.body.addWidget(self.thumb)
        about.body.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.steps_button)
        about.body.addLayout(buttons)
        past = Tile("History", hint="Your earlier searches. Pick one to see what it found.")
        past.body.addWidget(self.history_empty)
        past.body.addWidget(self.history, 1)
        hrow = QHBoxLayout()
        hrow.addWidget(self.forget_button)
        hrow.addWidget(self.clear_button)
        hrow.addStretch()
        past.body.addLayout(hrow)
        found.setMinimumHeight(380)
        about.setMinimumHeight(380)
        past.setMinimumHeight(240)
        grid.addWidget(search, 1, 0, 1, 2)
        grid.addWidget(found, 2, 0)
        grid.addWidget(about, 2, 1)
        grid.addWidget(past, 3, 0, 1, 2)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.scroll = scroll
        self.reset()

    # ---- state
    def reset(self) -> None:
        """Nothing shown (a different learner, or no search yet). The saved history is not touched."""
        self.result = None
        self.results.clear()
        self.pictures = {}
        self.thumb.setVisible(False)
        self.details.setHtml("")
        self.open_button.setEnabled(False)
        self.steps_button.setEnabled(False)
        self.message.setText("Describe what you want to learn. GuideWire searches YouTube and suggests up to three videos." if self.finder else "Finding tutorials is not available on this computer.")

    def set_user(self, db: Database, user_id: int) -> None:
        """Called whenever the screen is opened. The same learner finds the screen as they left it; a different learner starts clean and sees their own last search."""
        changed = self.user_id != user_id
        self.db, self.user_id = db, user_id
        if changed:
            self.reset()
            self.goal.clear()
            self.app.setCurrentText(FROM_WORDS)
        self._load_history()
        if changed and self.history_rows:
            self.history.setCurrentRow(0)                        # the last search comes back, as it was left before a restart

    def prefill(self, goal: str, app: str | None = None) -> None:
        self.goal.setText(goal)
        self.app.setCurrentText(app if app in APPS else FROM_WORDS)

    def selected(self) -> Suggestion | None:
        i = self.results.currentRow()
        return self.result.suggestions[i] if self.result and 0 <= i < len(self.result.suggestions) else None

    # ---- searching
    def search(self) -> None:
        goal = self.goal.text().strip()
        if not goal or self.finder is None:
            return
        app = self.app.currentText()
        app = None if app == FROM_WORDS else app
        self.search_button.setEnabled(False)
        self.message.setText("Searching YouTube...")
        run_call(self, lambda _status: self.finder(goal, app), lambda r, g=goal, a=app: self._on_result(r, g, a), sync=self.sync)

    def _on_result(self, result, goal: str = "", app: str | None = None) -> None:
        self.search_button.setEnabled(True)
        if isinstance(result, Exception):
            self.result = None
            self.results.clear()
            self.details.setHtml("")
            self.message.setText(f"Sorry, the search failed ({type(result).__name__}). Try again.")
            return
        self._present(result)
        if self.db is not None and self.user_id is not None and goal and result.suggestions:
            self.db.save_search(self.user_id, goal, app, result.to_json())
            self._load_history(select_first=True)

    def _present(self, result: DiscoveryResult, saved_note: str = "") -> None:
        """Show a result (a new search, or a saved one): the cards, the message, and the pictures (fetched again unless already held)."""
        self.results.clear()
        self.details.setHtml("")
        self.result = result
        for s in result.suggestions:
            card = self.results.add(s)
            if s.video_id in self.pictures:
                card.set_picture(self.pictures[s.video_id])
        n = len(result.suggestions)
        found = f"Here {'is' if n == 1 else 'are'} {n} video{'s' if n != 1 else ''} for you. Click one to read about it." if n else ""
        where = {"local": " (From GuideWire's small built-in list, not a live search.)"}.get(result.source, "")
        self.message.setText((saved_note + " " if saved_note else "") + (result.message + " " if result.message else "") + found + (where if n else ""))
        if result.suggestions:
            self.results.setCurrentRow(0)
            ids = [s.video_id for s in result.suggestions if s.video_id and s.video_id not in self.pictures]
            if ids:
                run_call(self, lambda _status: self.thumbnail_fetcher(ids), self._on_thumbnails, sync=self.sync)
        else:
            self._show(-1)

    def _on_thumbnails(self, found) -> None:
        """The pictures arrived (or none did: then the cards simply stay text). Each one goes into its card."""
        if isinstance(found, Exception) or not found or self.result is None:
            return
        for i, s in enumerate(self.result.suggestions):
            data = found.get(s.video_id)
            if not data or i >= self.results.count():
                continue
            pix = QPixmap()
            if pix.loadFromData(data):
                self.pictures[s.video_id] = pix
                self.results.card(i).set_picture(pix)
        self._show(self.results.currentRow())

    def _show(self, _row: int) -> None:
        s = self.selected()
        self.open_button.setEnabled(s is not None)
        self.steps_button.setEnabled(s is not None)
        if s is None or self.result is None:
            self.thumb.setVisible(False)
            return
        pix = self.pictures.get(s.video_id)
        self.thumb.setVisible(pix is not None)
        if pix is not None:
            self.thumb.setPixmap(pix.scaledToWidth(320, Qt.TransformationMode.SmoothTransformation))
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in friendly_notes(self.result.notes))
        self.details.setHtml(f"<h3>{html.escape(s.title)}</h3><p>{html.escape(s.summary)}<br><a href='{html.escape(s.url)}'>{html.escape(s.url)}</a></p><p>{html.escape(friendly_note(s.note))}</p><ul>{notes}</ul>")

    # ---- history
    @staticmethod
    def describe(row: dict) -> str:
        n = len(DiscoveryResult.from_json(row["result"]).suggestions) if row.get("result") else 0
        when = (row.get("created_at") or "")[:16].replace("T", " ")
        return f"{row['goal']}   ({row['app'] or 'any application'}, {n} video{'s' if n != 1 else ''}{', ' + when if when else ''})"

    def _load_history(self, select_first: bool = False) -> None:
        self.history.blockSignals(True)
        self.history.clear()
        self.history_rows = self.db.list_searches(self.user_id) if self.db is not None and self.user_id is not None else []
        for r in self.history_rows:
            self.history.addItem(self.describe(r))
            self.history.item(self.history.count() - 1).setToolTip(r["goal"])
        if select_first and self.history_rows:
            self.history.setCurrentRow(0)                        # the search just made is the newest entry
        self.history.blockSignals(False)
        self.history_empty.setVisible(not self.history_rows)
        self.history.setVisible(bool(self.history_rows))
        self._history_buttons()

    def _history_buttons(self) -> None:
        self.forget_button.setEnabled(0 <= self.history.currentRow() < len(self.history_rows))
        self.clear_button.setEnabled(bool(self.history_rows))

    def _history_picked(self, row: int) -> None:
        """An earlier search was picked: its words and application come back, and what it found is shown again (no new search is made)."""
        self._history_buttons()
        if not 0 <= row < len(self.history_rows):
            return
        r = self.history_rows[row]
        try:
            result = DiscoveryResult.from_json(r["result"])
        except Exception:
            self.message.setText("That saved search could not be opened. Remove it, or search again.")
            return
        self.prefill(r["goal"], r["app"])
        self._present(result, "Saved search. Press Find tutorials to look again.")

    def forget_selected(self) -> None:
        row = self.history.currentRow()
        if self.db is None or self.user_id is None or not 0 <= row < len(self.history_rows):
            return
        self.db.delete_search(self.user_id, self.history_rows[row]["id"])
        self._load_history()

    def clear_history(self) -> None:
        if self.db is not None and self.user_id is not None:
            self.db.clear_searches(self.user_id)
            self._load_history()
