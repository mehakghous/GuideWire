"""Find the icon of ONE tab in Blender's Properties editor.

The column of tab icons (Tool, Render, Output, ..., Object, ..., Data) has no text, so OCR cannot read it, and the add-on lists the tabs but not where each is drawn. What is known is the ORDER of the
tabs (from the add-on) and the column's rectangle. The icons themselves are found from the pixels: each is a short run of rows that differ from the column's background. When the number of runs found equals
the number of tabs, the run at the tab's position IS that tab's icon, and the highlight can be put on it; when the counts differ nothing is claimed (the caller then points at the whole column and says so).
Pure image code (numpy), no Blender and no screen needed.
"""
from __future__ import annotations

from shared.grounding import Rect

MIN_ICON = 8              # px: a run of rows shorter than this is noise
MAX_GAP = 4               # px: gaps this small are inside one icon (its strokes), larger gaps separate two icons
INK = 28                  # how far a pixel must differ from the column's background (0-255 per channel) to count as part of an icon


def icon_runs(bgr, column: Rect) -> list[tuple[int, int]]:
    """Vertical runs (top, bottom) in frame pixels of the icons in `column`, top to bottom."""
    import numpy as np
    h, w = bgr.shape[:2]
    x0, x1 = max(column.x, 0), min(column.x + column.w, w)
    y0, y1 = max(column.y, 0), min(column.y + column.h, h)
    if x1 - x0 < 6 or y1 - y0 < MIN_ICON:
        return []
    strip = bgr[y0:y1, x0:x1].astype("int16")
    bg = np.median(strip.reshape(-1, 3), axis=0)                          # the column is mostly empty background
    ink = (np.abs(strip - bg).max(axis=2) > INK).sum(axis=1) >= 2          # a row belongs to an icon when a couple of its pixels differ
    runs: list[list[int]] = []
    start = None
    for i, on in enumerate(list(ink) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if runs and start - runs[-1][1] <= MAX_GAP:
                runs[-1][1] = i
            else:
                runs.append([start, i])
            start = None
    return [(y0 + a, y0 + b) for a, b in runs if b - a >= MIN_ICON]


def tab_cell(bgr, column: Rect, tabs: list[str], tab: str) -> tuple[Rect | None, str]:
    """The cell of `tab` among `tabs` (the add-on's list, top to bottom) in `column`, and the evidence in words. (None, why) when the icons found do not match the tabs one to one.
    The scroll arrows at the bottom of a long column are not tabs: one extra run at the very end is ignored."""
    if tab not in tabs:
        return None, f"{tab} is not among the tabs"
    runs = icon_runs(bgr, column)
    n = len(tabs)
    if len(runs) == n + 1:                                                # the arrow that scrolls the column
        runs = runs[:-1]
    if len(runs) != n:
        return None, f"{len(runs)} icons were found in the column but the add-on lists {n} tabs"
    top, bottom = runs[tabs.index(tab)]
    pad = max(2, (min(column.w, 40) - (bottom - top)) // 2)                  # the clickable cell is a little bigger than its glyph
    return Rect(column.x, top - pad, column.w, (bottom - top) + 2 * pad), f"{n} icons found = {n} tabs; icon {tabs.index(tab) + 1} of {n} is {tab}"
