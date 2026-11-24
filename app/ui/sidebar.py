"""The left navigation panel, shown on every screen once someone is signed in (the plum panel in docs/design option 1).

It only emits signals; MainWindow decides what each one opens. Colours come from the palette (app/ui/style.py), so it follows the theme.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from .bento import soft_shadow

ITEMS = (("home", "Home"), ("find", "Find a Tutorial"), ("ask", "Ask GuideWire"), ("import", "New Tutorial"), ("history", "History"), ("progress", "Progress"), ("paths", "Learning Paths"), ("badges", "Achievements"), ("settings", "Settings"))


class Sidebar(QFrame):
    chosen = pyqtSignal(str)          # one of the keys in ITEMS
    logout = pyqtSignal()

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
