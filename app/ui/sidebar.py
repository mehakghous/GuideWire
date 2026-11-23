"""The left navigation panel, shown on every screen once someone is signed in (the plum panel in docs/design option 1).

It only emits signals; MainWindow decides what each one opens. Colours come from the palette (app/ui/style.py), so it follows the theme.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from .bento import soft_shadow

ITEMS = (("home", "Home"), ("find", "Find a Tutorial"), ("ask", "Ask GuideWire"), ("import", "New Tutorial"), ("history", "History"), ("privacy", "Privacy"), ("settings", "Settings"))


class Sidebar(QFrame):
    chosen = pyqtSignal(str)          # one of the keys in ITEMS
    logout = pyqtSignal()
    sync_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(220)
        soft_shadow(self, 34, 10)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 24, 14, 14)
        box.setSpacing(4)
        logo = QLabel("GuideWire")
        logo.setObjectName("sideLogo")
        box.addWidget(logo)
        box.addSpacing(22)
        self.buttons: dict[str, QPushButton] = {}
        for key, label in ITEMS:
            b = QPushButton(label)
            b.setObjectName("navItem")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("on", False)
            b.clicked.connect(lambda _=False, k=key: self.chosen.emit(k))
            box.addWidget(b)
            self.buttons[key] = b
        box.addStretch()
        self.conn_card = QFrame()
        self.conn_card.setObjectName("connCard")
        ccbox = QVBoxLayout(self.conn_card)
        ccbox.setContentsMargins(14, 10, 14, 10)
        ccbox.setSpacing(2)
        ctitle = QLabel("Connection")
        ctitle.setObjectName("sideSmall")
        self.conn_status = QLabel("")
        self.conn_status.setObjectName("sideStatus")
        self.conn_hint = QLabel("")
        self.conn_hint.setObjectName("sideSmall")
        self.conn_hint.setWordWrap(True)
        self.sync_button = QPushButton("Sync now")
        self.sync_button.setObjectName("navLogout")
        self.sync_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_button.clicked.connect(self.sync_requested)
        for w in (ctitle, self.conn_status, self.conn_hint, self.sync_button):
            ccbox.addWidget(w)
        box.addWidget(self.conn_card)
        box.addSpacing(6)
        card = QFrame()
        card.setObjectName("sideCard")
        soft_shadow(card, 18, 6, 3)
        cbox = QVBoxLayout(card)
        cbox.setContentsMargins(14, 12, 14, 12)
        cbox.setSpacing(3)
        title = QLabel("Companion")
        title.setObjectName("sideSmall")
        self.status = QLabel("")
        self.status.setObjectName("sideStatus")
        self.status_hint = QLabel("")
        self.status_hint.setObjectName("sideSmall")
        self.status_hint.setWordWrap(True)
        for w in (title, self.status, self.status_hint):
            cbox.addWidget(w)
        box.addWidget(card)
        box.addSpacing(8)
        self.user_label = QLabel("")
        self.user_label.setObjectName("sideUser")
        box.addWidget(self.user_label)
        self.logout_button = QPushButton("Log Out")
        self.logout_button.setObjectName("navLogout")
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.clicked.connect(self.logout)
        box.addWidget(self.logout_button)

    def set_active(self, key: str | None) -> None:
        for k, b in self.buttons.items():
            b.setProperty("on", k == key)
            b.style().unpolish(b)
            b.style().polish(b)

    def set_user(self, name: str) -> None:
        self.user_label.setText(name)

    def set_companion(self, watching: bool) -> None:
        self.status.setText("Watching Your 3D App" if watching else "Guidance Is Off")
        self.status_hint.setText("It points at the next step on your screen." if watching else "Steps are done by hand here.")

    def set_connection(self, status: str, hint: str, can_sync: bool, kind: str = "ok") -> None:
        """The Connection card: `kind` is ok, busy, offline or problem (it marks the card so the style sheet can colour it)."""
        self.conn_status.setText(status)
        self.conn_hint.setText(hint)
        self.sync_button.setVisible(can_sync)
        self.conn_card.setProperty("kind", kind)
        self.conn_card.style().unpolish(self.conn_card)
        self.conn_card.style().polish(self.conn_card)
