"""Find the icon-only tools in Blender's left toolbar and read which one is active.

The toolbar has no text, so OCR cannot see it. Its cells are found from pixels (dark rounded
cells in one column; the active one is blue) and named by position using the tool order Blender
itself reports for the current mode (`toolbars.json`, dumped from Blender 5.2.3 with
`bl_ui...tools_from_context`). A cell may hold several tools (a group: Tweak / Select Box /
Lasso): the cell shows the last-used one, so we only know the group, not which member is shown.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from shared.grounding import Rect

MIN_CELL, MAX_CELL = 30, 120          # px: height of one toolbar cell
CELL_DARKNESS = 0.75                  # cell background vs the viewport's own brightness
BLUE_SATURATION = 90


@dataclass(frozen=True)
class Cell:
    rect: Rect                        # frame pixels
    active: bool


_TOOLS: dict | None = None


def _tools() -> dict:
    global _TOOLS
    if _TOOLS is None:
        with open(os.path.join(os.path.dirname(__file__), "toolbars.json"), encoding="utf-8") as f:
            _TOOLS = json.load(f)
    return _TOOLS


def tool_groups(mode: str) -> list[list[dict]]:
    """Groups of tools (each `{"id", "label"}`) in toolbar order for a mode such as OBJECT."""
    return _tools().get(mode, [])


def _runs(flags) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(flags)))
    return out


def _longest_chain(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest run of cells stacked with small gaps. Header buttons above the toolbar are
    separated from it by a larger gap (and are not as tall), so they fall out of the chain."""
    if not runs:
        return []
    height = sorted(b - a for a, b in runs)[len(runs) // 2]
    chains: list[list[tuple[int, int]]] = [[runs[0]]]
    for prev, run in zip(runs, runs[1:], strict=False):
        if run[0] - prev[1] <= 0.35 * height and abs((run[1] - run[0]) - height) <= 0.3 * height:
            chains[-1].append(run)
        else:
            chains.append([run])
    return max(chains, key=len)


def find_cells(bgr, viewport: Rect) -> list[Cell]:
    """Toolbar cells top to bottom, from the pixels of the viewport's left edge."""
    import cv2
    import numpy as np
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype("float32")
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 1]
    y0, y1 = viewport.y, min(viewport.y + viewport.h, bgr.shape[0])
    # What the plain viewport looks like, to tell the darker cells from it.
    sample = gray[y0 + (y1 - y0) // 2: y1, viewport.x + viewport.w // 3: viewport.x + 2 * viewport.w // 3]
    if sample.size == 0:
        return []
    dark = float(np.median(sample)) * CELL_DARKNESS
    best: list[tuple[int, int]] = []
    best_x = viewport.x
    reach = max(48, int(0.05 * viewport.w))
    for x in range(viewport.x + 4, viewport.x + reach, 2):       # try each column near the left edge
        col = gray[y0:y1, x:x + 3].mean(axis=1)
        blue = (sat[y0:y1, x:x + 3] > BLUE_SATURATION).mean(axis=1) > 0.5
        runs = _longest_chain([r for r in _runs((col < dark) | blue) if MIN_CELL <= r[1] - r[0] <= MAX_CELL])
        if len(runs) > len(best):
            best, best_x = runs, x
    widths = []
    for a, _ in best:
        row = y0 + a + 4                                         # near the cell's top, clear of the icon
        x_end = best_x
        while x_end < bgr.shape[1] - 1 and (gray[row, x_end] < dark or sat[row, x_end] > BLUE_SATURATION):
            x_end += 1
        widths.append(x_end - best_x)
    width = max(int(np.median(widths)), 1) if widths else 1      # icon pixels can cut a scan short
    cells = []
    for a, b in best:
        mid = (y0 + a + y0 + b) // 2
        active = float((sat[mid - 3: mid + 3, best_x: best_x + 3] > BLUE_SATURATION).mean()) > 0.5
        cells.append(Cell(Rect(best_x, y0 + a, width, b - a), active))
    return cells


def observe_tool(cells: list[Cell], mode: str) -> dict:
    """What the toolbar shows: the active group, and the exact tool when the group has one tool."""
    groups = tool_groups(mode)
    if not groups or not 0 < len(cells) <= len(groups):
        return {}                                                # layout does not match: say nothing
    for cell, group in zip(cells, groups, strict=False):
        if cell.active:
            out: dict = {"active_tool_candidates": [t["id"] for t in group]}
            if len(group) == 1:
                out["active_tool"] = group[0]["id"]
            return out
    return {}


def modes_matching(cells: list[Cell], mode_hint: str | None = None) -> list[str]:
    """Modes whose toolbar could be what is on screen, best first: the hinted mode, then modes with
    exactly as many tools as cells, then modes with more (a tall toolbar is cut off by the window
    and shows only its first tools)."""
    tools = _tools()
    modes = [m for m in tools if not m.startswith("_") and len(tools[m]) >= len(cells) > 0]
    return sorted(modes, key=lambda m: (m != mode_hint, len(tools[m]) != len(cells)))


def locate_tool(cells: list[Cell], mode: str, name: str) -> Rect | None:
    """The cell holding a tool, matched by its label or id (case-insensitive), or None."""
    groups = tool_groups(mode)
    if not groups or not 0 < len(cells) <= len(groups):
        return None
    want = name.strip().lower()
    for cell, group in zip(cells, groups, strict=False):
        if any(want in (t["label"].lower(), t["id"].lower()) for t in group):
            return cell.rect
    return None
