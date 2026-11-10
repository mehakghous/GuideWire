"""Follow the target window: classify how its rectangle changed between polls.

Pure logic, no Windows calls: the caller supplies the rectangle (from `winplatform.find_window`)
so replay tests can feed recorded rectangles.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.grounding import Rect

Change = Literal["same", "moved", "resized", "found", "lost"]


@dataclass(frozen=True)
class WindowChange:
    kind: Change
    rect: Rect | None
    dx: int = 0
    dy: int = 0


def classify(prev: Rect | None, now: Rect | None) -> WindowChange:
    """What happened to the window between two polls (None = not visible or minimized)."""
    if now is None:
        return WindowChange("same" if prev is None else "lost", None)
    if prev is None:
        return WindowChange("found", now)
    if (prev.w, prev.h) != (now.w, now.h):
        return WindowChange("resized", now)
    if (prev.x, prev.y) != (now.x, now.y):
        return WindowChange("moved", now, now.x - prev.x, now.y - prev.y)
    return WindowChange("same", now)
