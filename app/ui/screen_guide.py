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

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
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
        self._pointer = False
        self._pulse_big = False
        self._timer: Any = None

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
            win.set_marks([self._mark(Rect(*self._rect), highlight_mark)] if self._rect is not None else [])
            win.show_click_through()
            self.visible = True
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {str(e)[:80]}"
            return False

    def _mark(self, rect, highlight_mark):
        """A box around a found element; for a place only ("move the mouse into the 3D viewport") a circle that pulses, so it reads as 'here' and not as 'this is the button'."""
        from shared.grounding import Rect
        from vision.overlay import Mark
        if not self._pointer:
            return highlight_mark(rect, self._label)
        r = 34 if self._pulse_big else 24
        cx, cy = rect.x + rect.w // 2, rect.y + rect.h // 2
        return Mark("pointer", Rect(cx - r, cy - r, 2 * r, 2 * r), "")

    def _start_pulse(self) -> None:
        if self._timer is not None:
            return
        try:
            from PyQt6.QtCore import QTimer
            self._timer = QTimer()
            self._timer.setInterval(450)
            self._timer.timeout.connect(self._pulse)
            self._timer.start()
        except Exception:
            self._timer = None

    def _pulse(self) -> None:
        if self._pointer and self.visible and self._rect is not None:
            self._pulse_big = not self._pulse_big
            self._draw()

    def show(self, rect: Rect4, window: Rect4 | None, label: str = "", pointer: bool = False) -> bool:
        """Highlight `rect` (screen pixels) with a short `label`. The overlay covers the application's `window` so a moved window carries the mark; without a window nothing is drawn."""
        if window is None:
            self.clear()
            return False
        self._window, self._rect, self._label, self._pointer = window, rect, label, pointer
        if pointer:
            self._start_pulse()
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
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
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


class InputHint(QWidget):
    """A small animation of what the hands do, step by step: a mouse with the LEFT or RIGHT button lit (a drag adds a moving arrow, a hover a wave), then the keys as key caps, lit one after the other.
    The events come from the step's own actions (`app.guidance.inputs_for`); it loops until the step changes. It draws only; it never touches the application."""
    TICK_MS = 450
    HOLD_TICKS = 4                                        # one event is shown for 4 ticks (1.8 s)

    def __init__(self) -> None:
        super().__init__()
        self.events: tuple[tuple[str, str], ...] = ()
        self.index = 0
        self.phase = 0
        self.setFixedHeight(60)
        self.timer = QTimer(self)
        self.timer.setInterval(self.TICK_MS)
        self.timer.timeout.connect(self.advance)

    def set_events(self, events: tuple[tuple[str, str], ...]) -> None:
        if tuple(events) == self.events:
            return
        self.events, self.index, self.phase = tuple(events), 0, 0
        self.setVisible(bool(events))
        if events and not self.timer.isActive():
            self.timer.start()
        elif not events:
            self.timer.stop()
        self.update()

    def advance(self) -> None:
        if not self.events:
            return
        self.phase += 1
        if self.phase >= self.HOLD_TICKS:
            self.phase, self.index = 0, (self.index + 1) % len(self.events)
        self.update()

    def label(self) -> str:
        if not self.events:
            return ""
        kind, what = self.events[self.index]
        return {"click": {"left": "Left click", "right": "Right click", "hover": "Hover (the submenu opens)"}.get(what, "Click"), "drag": "Hold the left button and drag",
                "keys": "Press " + what.replace("+", " + "), "type": f"Type {what}"}.get(kind, "")

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        if not self.events:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind, what = self.events[self.index]
        lit = self.phase % 2 == 0
        amber = QColor(255, 190, 0)
        h = self.height()
        if kind in ("click", "drag"):
            self._mouse(p, 4, 4, h - 8, what if kind == "click" else "left", lit, moving=kind == "drag")
            x_text = 4 + (h - 8) * 0.7 + 14
        else:
            x_text = 6
            parts = what.split("+") if kind == "keys" else [what]
            x = 6
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            for i, k in enumerate(parts):
                w = max(30, 12 + 8 * len(k))
                on = (self.phase // 2 == min(i, 1)) if len(parts) > 1 else lit
                p.setPen(QPen(QColor(17, 17, 17)))
                p.setBrush(amber if on else QColor(242, 242, 242))
                p.drawRoundedRect(QRectF(x, 10, w, 34), 6, 6)
                p.drawText(QRectF(x, 10, w, 34), Qt.AlignmentFlag.AlignCenter, k)
                x += w + 8
            x_text = x + 6
        p.setPen(QColor(242, 242, 242))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(x_text, 0, self.width() - x_text - 34, h), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, self.label())
        p.setPen(QColor(150, 158, 172))
        p.drawText(QRectF(self.width() - 34, 0, 30, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{self.index + 1}/{len(self.events)}")

    def _mouse(self, p: QPainter, x: float, y: float, h: float, button: str, lit: bool, moving: bool = False) -> None:
        w = h * 0.7
        amber, body = QColor(255, 190, 0), QColor(40, 44, 52)
        p.setPen(QPen(QColor(230, 230, 230), 2))
        p.setBrush(body)
        p.drawRoundedRect(QRectF(x, y, w, h), w / 2.2, w / 2.2)
        top = h * 0.42
        for side, rx in (("left", x), ("right", x + w / 2)):
            on = lit and button == side
            p.setBrush(amber if on else body)
            p.setPen(QPen(QColor(230, 230, 230), 1.5))
            p.drawRoundedRect(QRectF(rx + 1, y + 1, w / 2 - 2, top), 6, 6)
        p.setBrush(QColor(230, 230, 230))
        p.drawRoundedRect(QRectF(x + w / 2 - 2, y + 6, 4, top * 0.6), 2, 2)       # the wheel
        if moving or button == "hover":
            p.setPen(QPen(amber, 3))
            dx = 6 + 6 * (self.phase % 4)
            p.drawLine(int(x + w + 4), int(y + h * 0.7), int(x + w + 4 + dx), int(y + h * 0.7))
            p.drawLine(int(x + w + 4 + dx), int(y + h * 0.7), int(x + w + dx - 2), int(y + h * 0.7 - 5))
            p.drawLine(int(x + w + 4 + dx), int(y + h * 0.7), int(x + w + dx - 2), int(y + h * 0.7 + 5))


class InstructionPanel(QWidget):
    """A small guide that sits at the side like a browser extension: the step's goal, the keys to press, and the next click, in a box you can
    DRAG (by its header), RESIZE (by the corner grip), MINIMIZE (the dash: it becomes a thin tab that is still draggable; click the tab to open it again) and close (the cross).
    It is placed once, outside the application when there is room; as soon as you move or resize it yourself it stays where you put it."""
    done_clicked = pyqtSignal()
    back_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()
    closed = pyqtSignal()

    NORMAL_SIZE = (300, 190)
    MIN_SIZE = (220, 130)
    TAB_SIZE = (190, 26)

    def __init__(self) -> None:
        super().__init__()
        from PyQt6.QtWidgets import QSizeGrip
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("instructionPanel")
        self.setStyleSheet("#instructionPanel { background: #20242b; border: 2px solid #ffbe00; border-radius: 8px; } QLabel { color: #f2f2f2; font-size: 12px; } QLabel#hint { color: #ffd966; font-weight: bold; } "
                           "QLabel#keys { color: #111; background: #f2f2f2; border-radius: 4px; padding: 1px 7px; font-weight: bold; } "
                           "QPushButton { background: #3a4150; color: white; border: 0; border-radius: 4px; padding: 2px 10px; } QPushButton:hover { background: #4b5568; } "
                           "QPushButton#tool { background: transparent; font-size: 14px; padding: 0 6px; }")
        self.minimized = False
        self.moved_by_user = False
        self._drag: tuple[int, int] | None = None
        self._press = None
        self._normal_size = self.NORMAL_SIZE
        self.header = QLabel("")
        self.header.setStyleSheet("font-weight: bold; color: #ffbe00;")
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        self.header.setToolTip("Drag to move")
        self.minimize_button = QPushButton("\u2013")
        self.minimize_button.setObjectName("tool")
        self.minimize_button.setToolTip("Minimize to a small tab")
        self.close_button = QPushButton("\u2715")
        self.close_button.setObjectName("tool")
        self.close_button.setToolTip("Close this box for this step (it comes back on the next step)")
        self.goal = QLabel("")
        self.goal.setWordWrap(True)
        self.goal.setStyleSheet("font-weight: bold;")
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.keys_row = QHBoxLayout()
        self.keys_row.setSpacing(6)
        self._key_labels: list[QLabel] = []
        self.lines = QLabel("")
        self.lines.setWordWrap(True)
        self.lines.setVisible(False)
        self.more_button = QPushButton("Details \u25be")
        self.more_button.setObjectName("tool")
        self.done_button = QPushButton("Done")
        self.skip_button = QPushButton("Skip")
        self.back_button = QPushButton("Back")
        self.back_button.setToolTip("Go back to the previous step")
        self.input_hint = InputHint()
        self.input_hint.setVisible(False)
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
        body.setSpacing(4)
        body.addWidget(self.goal)
        body.addWidget(self.input_hint)
        body.addLayout(self.keys_row)
        body.addWidget(self.hint)
        body.addWidget(self.lines)
        body.addStretch(1)
        body.addLayout(row)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 8, 6)
        root.setSpacing(3)
        root.addLayout(top)
        root.addWidget(self.body, 1)
        self.setMinimumSize(*self.MIN_SIZE)
        self.resize(*self.NORMAL_SIZE)

    # ---- content
    def set_content(self, header: str, goal: str, lines: list[str], hint: str, keys: tuple[str, ...] = (), inputs: tuple[tuple[str, str], ...] = ()) -> None:
        self._title = header
        self.header.setText(self._tab_text() if self.minimized else header)
        self.goal.setText(goal)
        self.lines.setText("\n".join(f"\u2022 {x}" for x in lines))
        self.more_button.setVisible(bool(lines))
        if not lines:
            self.lines.setVisible(False)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.input_hint.set_events(inputs)
        for lab in self._key_labels:
            self.keys_row.removeWidget(lab)
            lab.deleteLater()
        self._key_labels = []
        for i, k in enumerate(keys):
            if i:
                then = QLabel("then")
                self._key_labels.append(then)
                self.keys_row.addWidget(then)
            cap = QLabel(k)
            cap.setObjectName("keys")
            self._key_labels.append(cap)
            self.keys_row.addWidget(cap)
        self.keys_row.addStretch(1)

    def _tab_text(self) -> str:
        """The short words on the minimized tab: "GuideWire 3/18 ▸"."""
        return getattr(self, "_title", "GuideWire").replace("GuideWire · step ", "GuideWire ").replace(" of ", "/") + " ▸"

    def _toggle_details(self) -> None:
        on = not self.lines.isVisible()
        self.lines.setVisible(on)
        self.more_button.setText("Details \u25b4" if on else "Details \u25be")

    # ---- minimize, close, move
    def toggle_minimized(self) -> None:
        title = getattr(self, "_title", self.header.text().replace("  \u25b8", ""))
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
            self.show()
            import sys
            if sys.platform == "win32":
                try:
                    from vision import winplatform
                    winplatform.exclude_from_capture(int(self.winId()))         # vision must never read GuideWire's own box
                except Exception:
                    pass
