"""Building blocks for the bento layout: tiles on a grid. Pure layout, no behaviour.

    grid = page_grid(widget)                          # the page's grid, with the app's margins and gaps
    grid.addWidget(header("Find a tutorial", back=self.back_button), 0, 0, 1, 3)
    box = Tile("Results", variant="soft"); box.body.addWidget(...); grid.addWidget(box, 1, 0)

A `Tile` is a rounded box with an optional heading; `ActionTile` is a whole tile that is also a button. Colours live in app/ui/style.py.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

GAP = 14
MARGIN = 20


def page_grid(widget: QWidget) -> QGridLayout:
    """Give a screen the app's canvas and a grid with even gaps. Columns and rows share space equally unless the screen says otherwise."""
    widget.setObjectName("page")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    grid = QGridLayout(widget)
    grid.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    grid.setSpacing(GAP)
    return grid


class Tile(QFrame):
    """A rounded box. `body` is the vertical layout to put content in. `variant` is one of: "", soft, mint, amber, lilac, accent."""

    def __init__(self, title: str | None = None, hint: str | None = None, variant: str = "", padding: int = 18):
        super().__init__()
        self.setObjectName("tile")
        self.setProperty("variant", variant)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(10)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("tileTitle")
            self.body.addWidget(self.title_label)
        if hint:
            h = QLabel(hint)
            h.setObjectName("tileHint")
            h.setWordWrap(True)
            self.body.addWidget(h)


class ActionTile(QPushButton):
    """A tile you click. Keeps the title as the button's text (for accessibility and tests) but paints its own two labels."""

    def __init__(self, title: str, hint: str = "", variant: str = "", min_height: int = 92, bottom: bool = False):
        super().__init__(title)
        self.setObjectName("action")
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("tileTitle")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("tileHint")
        self.hint_label.setWordWrap(True)
        for lab in (self.title_label, self.hint_label):
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)      # clicks go to the button underneath
        if bottom:
            box.addStretch()                      # tall tiles read better with their text sitting at the bottom
        box.addWidget(self.title_label)
        box.addWidget(self.hint_label)
        if not bottom:
            box.addStretch()

    def set_texts(self, title: str, hint: str) -> None:
        self.setText(title)
        self.title_label.setText(title)
        self.hint_label.setText(hint)


def tidy_list(lst) -> None:
    """A list that never scrolls sideways: long lines are trimmed with an ellipsis (the full text is the item's tooltip)."""
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    lst.setTextElideMode(Qt.TextElideMode.ElideRight)
    lst.setWordWrap(False)


def header(title: str, subtitle: str = "", back: QPushButton | None = None, extra: QWidget | None = None) -> Tile:
    """The page's top tile: its title and a one-line hint, with the Back button and anything else on the right."""
    tile = Tile(variant="soft", padding=16)
    row = QHBoxLayout()
    texts = QVBoxLayout()
    texts.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    texts.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("tileHint")
        s.setWordWrap(True)
        texts.addWidget(s)
    row.addLayout(texts, 1)
    if extra is not None:
        row.addWidget(extra)
    if back is not None:
        row.addWidget(back)
    tile.body.addLayout(row)
    tile.page_title = t                       # type: ignore[attr-defined]
    return tile
