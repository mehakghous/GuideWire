"""What the learner sees while working in the application: a highlight, a short label, and an instruction box.

* The HIGHLIGHT (Umaima's `vision/overlay.py`) is transparent, always on top, never takes focus and lets every click through, so the learner keeps working in Blender; it only draws. It is hidden
  from screen capture, so vision never reads GuideWire's own marks back. It carries a short label ("Click Add, then Mesh > Cylinder") and FOLLOWS the application window: a move carries the mark along,
  a resize clears it until the next look has found the element again.
* The INSTRUCTION BOX (`InstructionPanel`) is a small always-on-top clay card in the app's own colours (app/ui/style.py): the step's goal and how-to lines and the next move in words (no animation),
  and Done, Back, Skip. It sits OUTSIDE the application window when the screen has room (below it, then beside it), so it never hides what vision must read; it does not take focus, and it is hidden
  from capture. Closing it hides it for that step; the next step shows it again.

Everything lazy and failure-proof: with no Windows, no display or no vision packages the calls return False and the session carries on without them.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .style import current_palette

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


def panel_style() -> str:
    """The guide box's style sheet, from the app's palette so it matches every other screen (and follows the theme)."""
    c = current_palette()
    return (f"#instructionPanel {{ background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 {c['tile_hi']}, stop:1 {c['tile']}); border: 2px solid {c['hi']}; border-radius: 22px; }} "
            f"QLabel {{ background: transparent; color: {c['text']}; font-family: 'Segoe UI'; font-size: 10pt; }} "
            f"QLabel#kicker {{ color: {c['kicker']}; font-weight: 700; font-size: 9pt; }} "
            f"QLabel#goal {{ font-weight: 700; font-size: 11pt; }} "
            f"QLabel#hint {{ color: {c['accent']}; font-weight: 700; }} "
            f"QLabel#lines {{ color: {c['muted']}; font-size: 9.5pt; }} "
            f"QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 {c['tile_hi']}, stop:1 {c['field']}); border: 2px solid {c['hi']}; border-radius: 14px; padding: 3px 14px; font-weight: 600; color: {c['text']}; }} "
            f"QPushButton:hover {{ background: {c['accent_soft']}; }} "
            f"QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 {c['accent_hi']}, stop:1 {c['accent']}); border: 2px solid {c['accent_hi']}; color: {c['accent_text']}; font-weight: 700; }} "
            f"QPushButton#tool {{ background: transparent; border: 0; font-size: 11pt; padding: 0 6px; color: {c['muted']}; }} "
            f"QPushButton#tool:hover {{ color: {c['accent']}; }}")


class InstructionPanel(QWidget):
    """A small guide that sits at the side like a browser extension: the step's goal and the next move in words, in a box you can
    DRAG (by its header), RESIZE (by the corner grip), MINIMIZE (the dash: it becomes a thin tab that is still draggable; click the tab to open it again) and close (the cross).
    It is placed once, outside the application when there is room; as soon as you move or resize it yourself it stays where you put it."""
    done_clicked = pyqtSignal()
    back_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()
    closed = pyqtSignal()

    NORMAL_SIZE = (320, 190)
    MIN_SIZE = (240, 130)
    TAB_SIZE = (190, 30)

    def __init__(self) -> None:
        super().__init__()
        from PyQt6.QtWidgets import QSizeGrip
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("instructionPanel")
        self.setStyleSheet(panel_style())
        self.minimized = False
        self.moved_by_user = False
        self._drag: tuple[int, int] | None = None
        self._press = None
        self._normal_size = self.NORMAL_SIZE
        self.header = QLabel("")
        self.header.setObjectName("kicker")
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        self.header.setToolTip("Drag to move")
        self.minimize_button = QPushButton("–")
        self.minimize_button.setObjectName("tool")
        self.minimize_button.setToolTip("Minimize to a small tab")
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("tool")
        self.close_button.setToolTip("Close this box for this step (it comes back on the next step)")
        self.goal = QLabel("")
        self.goal.setObjectName("goal")
        self.goal.setWordWrap(True)
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.lines = QLabel("")
        self.lines.setObjectName("lines")
        self.lines.setWordWrap(True)
        self.lines.setVisible(False)
        self.more_button = QPushButton("Details ▾")
        self.more_button.setObjectName("tool")
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("primary")
        self.skip_button = QPushButton("Skip")
        self.back_button = QPushButton("Back")
        self.back_button.setToolTip("Go back to the previous step")
        self.grip = QSizeGrip(self)
        self.minimize_button.clicked.connect(self.toggle_minimized)
        self.close_button.clicked.connect(self._close)
        self.more_button.clicked.connect(self._toggle_details)
        self.done_button.clicked.connect(self.done_clicked.emit)
        self.skip_button.clicked.connect(self.skip_clicked.emit)
        self.back_button.clicked.connect(self.back_clicked.emit)
        top = QHBoxLayout()
        top.addWidget(self.header, 1)
        top.addWidget(self.minimize_button)
        top.addWidget(self.close_button)
        row = QHBoxLayout()
        row.addWidget(self.done_button)
        row.addWidget(self.back_button)
        row.addWidget(self.skip_button)
        row.addWidget(self.more_button)
        row.addStretch()
        row.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        body.addWidget(self.goal)
        body.addWidget(self.hint)
        body.addWidget(self.lines)
        body.addStretch(1)
        body.addLayout(row)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 12, 10)
        root.setSpacing(4)
        root.addLayout(top)
        root.addWidget(self.body, 1)
        self.setMinimumSize(*self.MIN_SIZE)
        self.resize(*self.NORMAL_SIZE)

    def restyle(self) -> None:
        """Follow the app's theme (light or dark)."""
        self.setStyleSheet(panel_style())

    # ---- content
    def set_content(self, header: str, goal: str, lines: list[str], hint: str, keys: tuple[str, ...] = ()) -> None:
        """Words only: the goal, the next move (the hint, with the keys to press said in it), and the how-to lines under "Details"."""
        self._title = header
        self.header.setText(self._tab_text() if self.minimized else header)
        self.goal.setText(goal)
        self.lines.setText("\n".join(f"• {x}" for x in lines))
        self.more_button.setVisible(bool(lines))
        if not lines:
            self.lines.setVisible(False)
        text = hint
        if keys and not any(k.lower() in hint.lower() for k in keys):
            text = (hint + " " if hint else "") + "Press " + " then ".join(keys) + "."
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def _tab_text(self) -> str:
        """The short words on the minimized tab: "GuideWire 3/18 ▸"."""
        return getattr(self, "_title", "GuideWire").replace("GuideWire · step ", "GuideWire ").replace(" of ", "/") + " ▸"

    def _toggle_details(self) -> None:
        on = not self.lines.isVisible()
        self.lines.setVisible(on)
        self.more_button.setText("Details ▴" if on else "Details ▾")

    # ---- minimize, close, move
    def toggle_minimized(self) -> None:
        title = getattr(self, "_title", self.header.text().replace("  ▸", ""))
        if self.minimized:
            self.minimized = False
            self.body.setVisible(True)
            self.minimize_button.setVisible(True)
            self.close_button.setVisible(True)
            self.setMinimumSize(*self.MIN_SIZE)
            self.resize(*self._normal_size)
            self.header.setText(title)
        else:
            self._normal_size = (self.width(), self.height())
            self.minimized = True
            self.body.setVisible(False)
            self.minimize_button.setVisible(False)
            self.close_button.setVisible(False)
            self.setMinimumSize(0, 0)
            self.resize(*self.TAB_SIZE)
            self.header.setText(self._tab_text())

    def _close(self) -> None:
        self.hide()
        self.closed.emit()

    def mousePressEvent(self, e) -> None:  # noqa: N802 (Qt override)
        if e.button() == Qt.MouseButton.LeftButton:
            p = e.globalPosition().toPoint()
            self._drag = (p.x() - self.x(), p.y() - self.y())
            self._press = p
            e.accept()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None:
            p = e.globalPosition().toPoint()
            self.move(p.x() - self._drag[0], p.y() - self._drag[1])
            self.moved_by_user = True

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and self.minimized and self._press is not None and (e.globalPosition().toPoint() - self._press).manhattanLength() < 4:
            self.toggle_minimized()                      # a click on the tab opens it again; a drag only moves it
        self._drag = None

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.isVisible() and not self.minimized and e.oldSize().isValid() and e.oldSize() != e.size() and self.grip.underMouse():
            self.moved_by_user = True                    # the learner sized it: it stays as they made it

    def put(self, x: int, y: int) -> None:
        """Place the box where the app suggests, only until the learner has moved or resized it themselves."""
        if not self.moved_by_user:
            self.move(x, y)
        if not self.isVisible():
            self.restyle()
            self.show()
            import sys
            if sys.platform == "win32":
                try:
                    from vision import winplatform
                    winplatform.exclude_from_capture(int(self.winId()))         # vision must never read GuideWire's own box
                except Exception:
                    pass
