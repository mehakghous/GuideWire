"""The window's floor: the canvas colour with a few big, soft clay balls drifting slowly behind everything (the app's one always-moving decoration).

It only paints; every screen sits on top of it. The animation pauses when the window is hidden.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

from .style import current_palette

# (x, y as fractions of the window, radius in pixels, palette colour, phase offset)
BALLS = ((0.92, 0.10, 150, "teal_hi", 0.0), (0.38, 1.02, 130, "hero_hi", 2.1), (0.05, 0.55, 90, "accent_soft", 4.2))


class Backdrop(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("shell")
        self._phase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(2 * math.pi)
        self._anim.setDuration(14000)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, value) -> None:
        self._phase = float(value)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._anim.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._anim.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pal = current_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(pal["canvas"]))
        p.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        for fx, fy, r, colour, offset in BALLS:
            cx = w * fx + math.sin(self._phase + offset) * 14
            cy = h * fy + math.cos(self._phase + offset) * 16
            g = QRadialGradient(QPointF(cx, cy), r)
            inner = QColor(pal[colour])
            inner.setAlpha(150)
            outer = QColor(pal[colour])
            outer.setAlpha(0)
            g.setColorAt(0, inner)
            g.setColorAt(1, outer)
            p.setBrush(g)
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()
