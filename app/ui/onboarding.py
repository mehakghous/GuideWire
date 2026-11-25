"""First-run welcome and the Privacy screen. They say, in plain words, what GuideWire does, what stays on this computer, what goes online and when, and let the learner switch each online part off.

The choices are stored as preferences (app/accounts.py): `sync` (keep my tutorials and progress online), `ai` (send my text, questions and video links to the AI model),
`overlay` (watch the application window and highlight the next click), `onboarded` (the welcome was seen). The screens only collect them; MainWindow stores them and the
features check them (the sync, the Ask screen and New tutorial).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QWidget

from .bento import HeroTile, Tile, header, page_grid, pill

DEFAULTS = {"sync": True, "ai": True, "overlay": True}

# What happens to the learner's data. Each line must stay true: change this text together with the feature.
ON_THIS_COMPUTER = (
    "Your tutorials, steps, progress and settings are saved in a database on this computer.",
    "Your password is never stored as text: only a bcrypt hash of it is kept.",
    "Screen guidance reads the window of your 3D application on this computer. It never clicks, types or moves anything, and nothing from your screen is sent online.",
)
SENT_ONLINE = (
    "If you use an online account: your email, name, tutorials, steps, progress and settings are kept in your private online space so they follow you to another computer. Nobody else can read them.",
    "Only when you use them: the text or video link you paste into New tutorial, and the questions you type in Ask GuideWire, are sent to the AI model to answer you.",
)
YOUR_CONTROL = (
    "Turn off online syncing or the AI model below at any time; GuideWire keeps working on this computer.",
    "Log out to stop. Deleting an online account is not in the app yet.",
)


def _bullets(lines) -> str:
    return "<br>".join(f"• {line}" for line in lines)


def _text(html: str) -> QLabel:
    lab = QLabel(html)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    return lab


def _choices() -> tuple[QCheckBox, QCheckBox, QCheckBox]:
    sync = QCheckBox("Keep my tutorials and progress online (needs an online account)")
    ai = QCheckBox("Use the AI model for my pasted text, video links and questions")
    overlay = QCheckBox("Watch my 3D application's window and highlight the next click")
    return sync, ai, overlay


class OnboardingScreen(QWidget):
    """Shown once, right after the first login."""
    finished = pyqtSignal(dict)           # the chosen preferences

    def __init__(self):
        super().__init__()
        self.sync_box, self.ai_box, self.overlay_box = _choices()
        self.start_button = QPushButton("Get started")
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumHeight(40)
        self.start_button.clicked.connect(lambda: self.finished.emit(self.choices()))
        grid = page_grid(self)
        grid.addWidget(header("Welcome to GuideWire", "Learn Blender, Maya and Houdini one step at a time, right on your own screen.", kicker="Hello"), 0, 0, 1, 3)
        hero = HeroTile("How it works", padding=24)
        hero.body.addWidget(_text(_bullets((
            "Pick a tutorial (or let GuideWire find or write one) and review its steps.",
            "Start a session: GuideWire shows the step you are on and, if you allow it, points at the next click in your application.",
            "You do every action yourself. GuideWire only looks, and ticks a step off when it sees it done.",
            "Pause any time: your place is saved.",
        ))), 1)
        local = Tile("On this computer")
        local.body.addWidget(_text(_bullets(ON_THIS_COMPUTER)), 1)
        online = Tile("Sent online, and when", variant="mint")
        online.body.addWidget(_text(_bullets(SENT_ONLINE)), 1)
        choose = Tile("Your choices")
        choose.body.addWidget(pill("You can change these later in Privacy"), 0, Qt.AlignmentFlag.AlignLeft)
        for box in (self.sync_box, self.ai_box, self.overlay_box):
            choose.body.addWidget(box)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.start_button)
        choose.body.addLayout(row)
        grid.addWidget(hero, 1, 0, 1, 3)
        grid.addWidget(local, 2, 0)
        grid.addWidget(online, 2, 1)
        grid.addWidget(choose, 2, 2)
        grid.setRowStretch(1, 2)
        grid.setRowStretch(2, 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        self.load({})

    def load(self, prefs: dict, online_enabled: bool = False) -> None:
        self.sync_box.setChecked(bool(prefs.get("sync", DEFAULTS["sync"])) and online_enabled)
        self.sync_box.setEnabled(online_enabled)
        self.sync_box.setToolTip("" if online_enabled else "The online service is not set up on this computer, so everything stays here.")
        self.ai_box.setChecked(bool(prefs.get("ai", DEFAULTS["ai"])))
        self.overlay_box.setChecked(bool(prefs.get("overlay", DEFAULTS["overlay"])))

    def choices(self) -> dict:
        return {"sync": self.sync_box.isChecked(), "ai": self.ai_box.isChecked(), "overlay": self.overlay_box.isChecked(), "onboarded": True}


class PrivacyScreen(QWidget):
    """What GuideWire does with the learner's data, and the switches. Changing a switch is saved at once."""
    back = pyqtSignal()
    changed = pyqtSignal(dict)           # the preferences that changed

    def __init__(self):
        super().__init__()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back.emit)
        self.sync_box, self.ai_box, self.overlay_box = _choices()
        self._loading = False
        for box, key in ((self.sync_box, "sync"), (self.ai_box, "ai"), (self.overlay_box, "overlay")):
            box.toggled.connect(lambda on, k=key: None if self._loading else self.changed.emit({k: bool(on)}))
        grid = page_grid(self)
        grid.addWidget(header("Privacy", "What GuideWire does with your information, in plain words.", back=self.back_button, kicker="Your data"), 0, 0, 1, 2)
        local = HeroTile("Stays on this computer")
        local.body.addWidget(_text(_bullets(ON_THIS_COMPUTER)), 1)
        online = Tile("Goes online, and when", variant="mint")
        online.body.addWidget(_text(_bullets(SENT_ONLINE)), 1)
        control = Tile("Your choices")
        for box in (self.sync_box, self.ai_box, self.overlay_box):
            control.body.addWidget(box)
        control.body.addWidget(_text(_bullets(YOUR_CONTROL)))
        grid.addWidget(local, 1, 0)
        grid.addWidget(online, 1, 1)
        grid.addWidget(control, 2, 0, 1, 2)
        grid.setRowStretch(1, 2)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

    def load(self, prefs: dict, online_enabled: bool = False) -> None:
        self._loading = True
        self.sync_box.setChecked(bool(prefs.get("sync", DEFAULTS["sync"])) and online_enabled)
        self.sync_box.setEnabled(online_enabled)
        self.sync_box.setToolTip("" if online_enabled else "The online service is not set up on this computer, so everything stays here.")
        self.ai_box.setChecked(bool(prefs.get("ai", DEFAULTS["ai"])))
        self.overlay_box.setChecked(bool(prefs.get("overlay", DEFAULTS["overlay"])))
        self._loading = False
