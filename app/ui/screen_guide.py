"""What the learner sees while working in the application: a highlight, a short label, and an instruction box.

* The HIGHLIGHT (Umaima's `vision/overlay.py`) is transparent, always on top, never takes focus and lets every click through, so the learner keeps working in Blender; it only draws. It is hidden
  from screen capture, so vision never reads GuideWire's own marks back. It carries a short label ("Click Add, then Mesh > Cylinder") and FOLLOWS the application window: a move carries the mark along,
  a resize clears it until the next look has found the element again.
* The INSTRUCTION BOX (`InstructionPanel`) is a small always-on-top box with the step's goal and how-to lines, the hint, and Done, Skip and a close button. It sits OUTSIDE the application window
  when the screen has room (below it, then beside it), so it never hides what vision must read; it does not take focus, and it is hidden from capture. Closing it hides it for that step; the next step shows it again.

Everything lazy and failure-proof: with no Windows, no display or no vision packages the calls return False and the session carries on without them.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

Rect4 = tuple[int, int, int, int]


class ScreenGuide:
    def __init__(self, make_overlay: Callable[[], Any] | None = None):
        """`make_overlay()` returns an object with `cover(rect)`, `set_marks(list)`, `show_click_through()`, `hide()`, `close()` (default: vision.overlay.make_overlay_window)."""
        self._make = make_overlay
        self._win: Any = None
        self.error: str | None = None
        self.visible = False
        self._window: Rect4 | None = None
        self._rect: Rect4 | None = None
        self._label = ""

    def _overlay(self):
        if self._win is None and self.error is None:
            try:
                make = self._make
                if make is None:
                    from vision.overlay import make_overlay_window as make
                self._win = make()
            except Exception as e:
                self.error = f"{type(e).__name__}: {str(e)[:80]}"
        return self._win

    def _draw(self) -> bool:
        win = self._overlay()
        if win is None or self._window is None:
            return False
        try:
            from shared.grounding import Rect
            from vision.overlay import highlight_mark
            win.cover(Rect(*self._window))
            win.set_marks([highlight_mark(Rect(*self._rect), self._label)] if self._rect is not None else [])
            win.show_click_through()
            self.visible = True
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {str(e)[:80]}"
            return False

    def show(self, rect: Rect4, window: Rect4 | None, label: str = "") -> bool:
        """Highlight `rect` (screen pixels) with a short `label`. The overlay covers the application's `window` so a moved window carries the mark; without a window nothing is drawn."""
        if window is None:
            self.clear()
            return False
        self._window, self._rect, self._label = window, rect, label
        return self._draw()

    def follow_window(self, window: Rect4 | None) -> str:
        """Called often with the application window's rectangle. Returns same | found | moved | resized | lost.
        A move carries the highlight along at once; a resize clears it (its place no longer means anything) so the caller can look again."""
        last = self._window
        if window is None:
            if last is not None:
                self.clear()
                self._window = None
            return "lost"
        if last is None:
            self._window = window
            return "found"
        if window == last:
            return "same"
        if (window[2], window[3]) == (last[2], last[3]) and self._rect is not None:
            dx, dy = window[0] - last[0], window[1] - last[1]
            self._window = window
            self._rect = (self._rect[0] + dx, self._rect[1] + dy, self._rect[2], self._rect[3])
            if self.visible:
                self._draw()
            return "moved"
        self._window, self._rect = window, None
        if self.visible:
            self._draw()                                   # still covers the window, marks cleared
        return "resized"

    def clear(self) -> None:
        self._rect = None
        if self._win is not None and self.visible:
            try:
                self._win.set_marks([])
                self._win.hide()
            except Exception:
                pass
        self.visible = False

    def close(self) -> None:
        self.clear()
        if self._win is not None:
            try:
                self._win.close()
            except Exception:
                pass
            self._win = None


def panel_position(window: Rect4 | None, screen: Rect4, size: tuple[int, int], scale: float = 1.0, gap: int = 8) -> tuple[int, int, str]:
    """Where to put the instruction box (logical pixels): below the application window if the screen has room, else beside it, else above it, else inside its bottom-right corner.
    `window` is in physical pixels (as vision reports it), `screen` and `size` in logical pixels, `scale` the device pixel ratio. Returns (x, y, where)."""
    sx, sy, sw, sh = screen
    w, h = size
    if window is None:
        return sx + sw - w - 16, sy + sh - h - 16, "corner"
    bx, by, bw, bh = (round(v / scale) for v in window)

    def clamp_x(x: int) -> int:
        return max(sx, min(x, sx + sw - w))
    if by + bh + gap + h <= sy + sh:
        return clamp_x(bx), by + bh + gap, "below"
    if bx + bw + gap + w <= sx + sw:
        return bx + bw + gap, max(sy, min(by, sy + sh - h)), "beside"
    if by - gap - h >= sy:
        return clamp_x(bx), by - gap - h, "above"
    return clamp_x(bx + bw - w - 12), max(sy, by + bh - h - 12), "inside"


class InstructionPanel(QWidget):
    done_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("instructionPanel")
        self.setStyleSheet("#instructionPanel { background: #20242b; border: 2px solid #ffbe00; border-radius: 8px; } QLabel { color: #f2f2f2; } QLabel#hint { color: #ffd966; font-weight: bold; } "
                           "QPushButton { background: #3a4150; color: white; border: 0; border-radius: 4px; padding: 4px 12px; } QPushButton:hover { background: #4b5568; } "
                           "QPushButton#close { background: transparent; font-size: 16px; padding: 0 8px; }")
        self.header = QLabel("")
        self.header.setStyleSheet("font-weight: bold; color: #ffbe00;")
        self.goal = QLabel("")
        self.goal.setWordWrap(True)
        self.goal.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.lines = QLabel("")
        self.lines.setWordWrap(True)
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("close")
        self.close_button.setToolTip("Close this box for this step (it comes back on the next step; turn it off in GuideWire)")
        self.done_button = QPushButton("Done")
        self.skip_button = QPushButton("Skip")
        self.close_button.clicked.connect(self._close)
        self.done_button.clicked.connect(self.done_clicked.emit)
        self.skip_button.clicked.connect(self.skip_clicked.emit)
        top = QHBoxLayout()
        top.addWidget(self.header, 1)
        top.addWidget(self.close_button)
        row = QHBoxLayout()
        row.addWidget(self.done_button)
        row.addWidget(self.skip_button)
        row.addStretch()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.addLayout(top)
        root.addWidget(self.goal)
        root.addWidget(self.lines)
        root.addWidget(self.hint)
        root.addLayout(row)
        self.setFixedWidth(420)

    def _close(self) -> None:
        self.hide()
        self.closed.emit()

    def set_content(self, header: str, goal: str, lines: list[str], hint: str) -> None:
        self.header.setText(header)
        self.goal.setText(goal)
        self.lines.setText("\n".join(f"• {x}" for x in lines))
        self.lines.setVisible(bool(lines))
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.adjustSize()

    def put(self, x: int, y: int) -> None:
        self.move(x, y)
        if not self.isVisible():
            self.show()
            import sys
            if sys.platform == "win32":
                try:
                    from vision import winplatform
                    winplatform.exclude_from_capture(int(self.winId()))         # vision must never read GuideWire's own box
                except Exception:
                    pass
