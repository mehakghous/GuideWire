"""Pages that are planned and not finished: Progress, Learning paths, Achievements. Each says so plainly ("Work in progress") and shows what it will hold; Progress already shows the real numbers it can.

Pure layout, no behaviour of their own: MainWindow fills Progress from the database (`ProgressScreen.show_summary`).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from .bento import HeroTile, Tile, header, page_grid, pill


class WorkInProgressScreen(QWidget):
    """A page that is on its way. `planned` is a list of (title, what it will do) tiles."""
    back = pyqtSignal()

    def __init__(self, title: str, kicker: str, blurb: str, planned: list[tuple[str, str]]):
        super().__init__()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back.emit)
        self.page_title = title
        grid = page_grid(self)
        grid.addWidget(header(title, blurb, back=self.back_button, kicker=kicker), 0, 0, 1, 3)
        hero = HeroTile(padding=26)
        hero.body.addWidget(pill("Work in progress"), 0, Qt.AlignmentFlag.AlignLeft)
        self.hero_title = QLabel(f"{title} is being built")
        self.hero_title.setObjectName("big")
        self.hero_title.setStyleSheet("font-size: 19pt; font-weight: 800;")
        self.hero_title.setWordWrap(True)
        hero.body.addWidget(self.hero_title)
        note = QLabel("This page is not finished yet. Below is what it will do; nothing here changes your tutorials or sessions.")
        note.setObjectName("tileHint")
        note.setWordWrap(True)
        hero.body.addWidget(note)
        hero.body.addStretch()
        grid.addWidget(hero, 1, 0, 1, 3)
        self.tiles: list[Tile] = []
        for col, (name, text) in enumerate(planned[:3]):
            tile = Tile(name, variant=("mint", "amber", "soft")[col % 3])
            lab = QLabel(text)
            lab.setObjectName("tileHint")
            lab.setWordWrap(True)
            tile.body.addWidget(lab)
            tile.body.addStretch()
            grid.addWidget(tile, 2, col)
            self.tiles.append(tile)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
        for col in range(3):
            grid.setColumnStretch(col, 1)


class ProgressScreen(WorkInProgressScreen):
    """Progress: the real counts now (tutorials, sessions, steps), the charts later."""

    def __init__(self):
        super().__init__("Progress", "How you are doing", "Your tutorials, sessions and finished steps in one place.", [
            ("Streaks and time", "How many days in a row you practised, and how long a session takes you."),
            ("Per application", "Your steps done in Blender, Maya and Houdini side by side."),
            ("Where you get stuck", "The steps you skip or redo most, with a link to ask GuideWire about them."),
        ])
        self.numbers = QLabel("")
        self.numbers.setObjectName("big")
        self.numbers.setTextFormat(Qt.TextFormat.RichText)
        self.numbers.setWordWrap(True)
        self.hero_title.setText("Your numbers so far")
        hero = self.hero_title.parentWidget()
        hero.layout().insertWidget(2, self.numbers)

    def show_summary(self, s: dict[str, int]) -> None:
        self.numbers.setText(
            f"<b>{s['steps_done']}</b> steps done &middot; <b>{s['finished']}</b> sessions finished of <b>{s['sessions']}</b> started "
            f"&middot; <b>{s['tutorials']}</b> tutorials &middot; <b>{s['chats']}</b> chats")


def learning_paths() -> WorkInProgressScreen:
    return WorkInProgressScreen("Learning Paths", "Where to go next", "Ordered sets of tutorials that take you from a first rig to a finished character.", [
        ("Rigging basics", "Joints, skinning, IK and controls, in the order the knowledge base teaches them."),
        ("Switch application", "Take what you know in Blender to Maya or Houdini, step by step."),
        ("Your own path", "Pick tutorials and GuideWire orders them for you."),
    ])


def achievements() -> WorkInProgressScreen:
    return WorkInProgressScreen("Achievements", "Small wins", "Badges for finishing sessions, trying a new application and asking good questions.", [
        ("First session", "Finish a guided session from the first step to the last."),
        ("Three applications", "Do a session in Blender, Maya and Houdini."),
        ("Curious", "Ask GuideWire ten questions."),
    ])
