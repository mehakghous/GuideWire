"""The list of ALL the steps of a session, with the one you are on highlighted.

One row per step: its number, its goal (wrapped, never cut off) and a status word on the right ("Now", "Done", "Skipped"; nothing for a step still to do), so the state is never carried by colour alone. Clicking a
row only LOOKS at that step (`chosen`): it never moves the session. Colours come from the style sheet (`QFrame#stepRow[state=...]` in app/ui/style.py), so they follow the theme.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

WORDS = {"current": "Now", "done": "Done", "skipped": "Skipped", "pending": ""}
MARKS = {"current": "▶", "done": "✓", "skipped": "↷", "pending": ""}


class StepRow(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, number: int, goal: str):
        super().__init__()
        self.number = number
        self.setObjectName("stepRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setToolTip(goal)
        self.mark = QLabel("")
        self.mark.setObjectName("stepMark")
        self.mark.setFixedWidth(18)
        self.mark.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.text = QLabel(f"{number}. {goal}")
        self.text.setObjectName("stepText")
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)        # takes the row's width and wraps; never pushes the list sideways
        self.word = QLabel("")
        self.word.setObjectName("stepWord")
        self.word.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 12, 6)
        row.setSpacing(8)
        row.addWidget(self.mark)
        row.addWidget(self.text, 1)
        row.addWidget(self.word)
        self.set_state("pending", False)

    def set_state(self, state: str, viewing: bool) -> None:
        self.setProperty("state", state)
        self.setProperty("viewing", viewing)
        self.mark.setText(MARKS.get(state, ""))
        self.word.setText(WORDS.get(state, ""))
        self.setAccessibleDescription(f"Step {self.number}: {WORDS.get(state) or 'to do'}" + (", being looked at" if viewing else ""))
        self.style().unpolish(self)
        self.style().polish(self)                       # the style sheet's [state=...] rules apply again

    @property
    def state(self) -> str:
        return str(self.property("state"))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.number)
        super().mousePressEvent(event)


class StepList(QScrollArea):
    """Every step of the tutorial in order. `set_steps` once per session, `show_state` after every change."""
    chosen = pyqtSignal(int)             # 1-based number of the row that was clicked

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("stepScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows: list[StepRow] = []
        self._inner = QWidget()
        self._inner.setObjectName("stepInner")
        self._box = QVBoxLayout(self._inner)
        self._box.setContentsMargins(0, 0, 4, 0)
        self._box.setSpacing(3)
        self._box.addStretch(1)
        self.setWidget(self._inner)
        self._last_current: int | None = None

    def set_steps(self, goals: list[str]) -> None:
        for r in self.rows:
            self._box.removeWidget(r)
            r.deleteLater()
        self.rows = []
        for i, goal in enumerate(goals, start=1):
            row = StepRow(i, goal)
            row.clicked.connect(self.chosen.emit)
            self._box.insertWidget(self._box.count() - 1, row)
            self.rows.append(row)
        self._last_current = None

    def show_state(self, statuses: list[str], current: int | None, viewing: int | None = None) -> None:
        """`statuses` are pending | done | skipped for each step; `current` the 1-based step being worked on (None = no step is active); `viewing` a step being looked at that is not the current one."""
        for i, (row, st) in enumerate(zip(self.rows, statuses, strict=False), start=1):
            row.set_state("current" if i == current else st, i == viewing)
        if current is not None and current != self._last_current:
            self.ensure_row_visible(current)                      # the learner never has to hunt for where they are
        self._last_current = current

    def ensure_row_visible(self, number: int) -> None:
        if 1 <= number <= len(self.rows):
            self.ensureWidgetVisible(self.rows[number - 1], 0, 24)

    def states(self) -> list[str]:
        return [r.state for r in self.rows]
