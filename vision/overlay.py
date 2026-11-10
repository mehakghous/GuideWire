"""Pointer and highlight overlay.

`Mark` and the helpers are pure (testable without a display). `OverlayWindow` is the PyQt6
window that draws them: transparent, always on top, never takes focus or mouse input, so the
learner keeps working in Blender. It only draws; it never sends input to the application.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.grounding import GroundingResult, Rect

MarkKind = Literal["pointer", "highlight"]

POINTER_RADIUS = 14
HIGHLIGHT_PAD = 4


@dataclass(frozen=True)
class Mark:
    kind: MarkKind
    rect: Rect               # screen physical pixels; a pointer is a small square around its point
    label: str = ""


def pointer_mark(result: GroundingResult, label: str = "") -> Mark | None:
    """A pointer at a grounded point, or None if grounding did not produce a usable point."""
    if result.status != "ok" or result.x is None or result.y is None:
        return None
    r = POINTER_RADIUS
    return Mark("pointer", Rect(result.x - r, result.y - r, 2 * r, 2 * r), label)


def highlight_mark(rect: Rect, label: str = "") -> Mark:
    p = HIGHLIGHT_PAD
    return Mark("highlight", Rect(rect.x - p, rect.y - p, rect.w + 2 * p, rect.h + 2 * p), label)


def to_local(mark: Mark, origin: Rect) -> Mark:
    """Express a screen-space mark in the overlay window's own coordinates."""
    r = mark.rect
    return Mark(mark.kind, Rect(r.x - origin.x, r.y - origin.y, r.w, r.h), mark.label)


def visible_marks(marks: list[Mark], origin: Rect) -> list[Mark]:
    """Marks that touch the overlay's area, in local coordinates. Off-window marks are dropped."""
    out = []
    for m in marks:
        r = m.rect
        if r.x < origin.x + origin.w and r.x + r.w > origin.x \
                and r.y < origin.y + origin.h and r.y + r.h > origin.y:
            out.append(to_local(m, origin))
    return out


def make_overlay_window():
    """Build the PyQt6 overlay widget. Imported lazily so non-GUI code and CI never need Qt."""
    import sys

    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QPainter, QPen
    from PyQt6.QtWidgets import QApplication, QWidget

    class OverlayWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowTransparentForInput
                | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self._origin = Rect(0, 0, 1, 1)
            self._marks: list[Mark] = []

        def _scale(self) -> float:
            screen = QApplication.primaryScreen()
            return screen.devicePixelRatio() if screen else 1.0

        def cover(self, area: Rect) -> None:
            """Sit exactly over `area` (physical pixels), e.g. the Blender window."""
            self._origin = area
            k = self._scale()
            self.setGeometry(QRect(round(area.x / k), round(area.y / k),
                                   round(area.w / k), round(area.h / k)))
            self.update()

        def set_marks(self, marks: list[Mark]) -> None:
            self._marks = visible_marks(marks, self._origin)
            self.update()

        def show_click_through(self) -> None:
            self.show()
            if sys.platform == "win32":
                from vision import winplatform
                winplatform.make_click_through(int(self.winId()))

        def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            k = self._scale()
            for m in self._marks:
                r = QRect(round(m.rect.x / k), round(m.rect.y / k),
                          round(m.rect.w / k), round(m.rect.h / k))
                p.setPen(QPen(QColor(255, 190, 0), 3))
                if m.kind == "pointer":
                    p.setBrush(QColor(255, 190, 0, 70))
                    p.drawEllipse(r)
                else:
                    p.setBrush(QColor(255, 190, 0, 40))
                    p.drawRoundedRect(r, 4, 4)
                if m.label:
                    p.setFont(QFont("Segoe UI", 10))
                    p.setPen(QColor(255, 255, 255))
                    p.fillRect(r.x(), r.bottom() + 4, 8 * len(m.label) + 12, 22, QColor(0, 0, 0, 170))
                    p.drawText(r.x() + 6, r.bottom() + 20, m.label)

    return OverlayWindow()
