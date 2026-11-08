"""Blender editor-area (region) detection from a screenshot of the Blender window.

Blender tiles its window into rectangular areas separated by thin dark gaps. We find those
gaps and split the window recursively (the layout is always a binary tiling), then name each
area from its position in the default layout (3D viewport, Outliner, Properties, Timeline,
top bar, status bar).

Limits, on purpose and stated: this is geometry only. It does not read text, so a re-arranged
layout gives correct rectangles but guessed names (`confidence` drops). The thresholds are
tuned on synthetic frames until real Blender 1920x1080 captures are added to tests/fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from shared.grounding import Rect

RegionName = Literal["topbar", "viewport", "outliner", "properties", "timeline", "statusbar", "unknown"]

MIN_AREA = 60          # px; do not try to split a rectangle smaller than twice this
MIN_STRIP = 16         # px; thinnest area a split may leave (the status bar is ~24px at 1080p)
GAP_TOLERANCE = 2      # luminance levels either side of the gap colour
LINE_COVERAGE = 0.90   # fraction of the line that must be gap colour
EDGE_MARGIN = 16       # never split this close to a rectangle edge
GAP_SHARE = 0.003      # the gap colour must cover at least this share of the image
GAP_CONTRAST = 8       # and be at least this much darker than the typical pixel


@dataclass(frozen=True)
class Region:
    name: RegionName
    rect: Rect          # in the coordinates of the analysed image


@dataclass(frozen=True)
class Layout:
    regions: tuple[Region, ...]
    confidence: float   # 1.0 = every default area found where expected; 0.0 = nothing matched

    def get(self, name: RegionName) -> Rect | None:
        return next((r.rect for r in self.regions if r.name == name), None)


def luminance(bgr: np.ndarray) -> np.ndarray:
    b, g, r = bgr[..., 0], bgr[..., 1], bgr[..., 2]
    return (0.114 * b + 0.587 * g + 0.299 * r).astype(np.float32)


def find_gap_level(lum: np.ndarray) -> float | None:
    """Luminance of the gaps between areas: the darkest level that covers a real share of
    the image. Text and icon pixels are too sparse to qualify; None if nothing stands out."""
    counts = np.bincount(np.clip(lum, 0, 255).astype(np.uint8).ravel(), minlength=256)
    smooth = counts + np.roll(counts, 1) + np.roll(counts, -1)
    big = np.flatnonzero(smooth[:128] >= GAP_SHARE * lum.size)
    if big.size == 0:
        return None
    level = float(big[0])
    return level if float(np.median(lum)) - level >= GAP_CONTRAST else None


def _gap_score(lum: np.ndarray, level: float, rect: Rect, vertical: bool) -> np.ndarray:
    """Per column (vertical=True) or row: fraction of the line that is gap colour."""
    sub = lum[rect.y:rect.y + rect.h, rect.x:rect.x + rect.w]
    if not vertical:
        sub = sub.T
    return (np.abs(sub - level) <= GAP_TOLERANCE).mean(axis=0)


def _best_split(lum: np.ndarray, level: float, rect: Rect) -> tuple[bool, int, int] | None:
    """(vertical?, first, last offset of the gap inside rect) for the strongest gap line."""
    best: tuple[float, bool, int, int] | None = None
    for vertical in (True, False):
        score = _gap_score(lum, level, rect, vertical)
        length = rect.w if vertical else rect.h
        lo, hi = EDGE_MARGIN, length - EDGE_MARGIN
        if hi <= lo:
            continue
        hits = np.flatnonzero(score[lo:hi] >= LINE_COVERAGE) + lo
        if hits.size == 0:
            continue
        # Adjacent columns form one gap; keep the strongest gap (longest, then best covered).
        for c in np.split(hits, np.flatnonzero(np.diff(hits) > 1) + 1):
            s = float(score[c].mean())
            if best is None or s > best[0]:
                best = (s, vertical, int(c[0]), int(c[-1]))
    return None if best is None else best[1:]


def split_areas(lum: np.ndarray, level: float, rect: Rect | None = None, depth: int = 0) -> list[Rect]:
    """Recursive guillotine split of the image into areas."""
    if rect is None:
        rect = Rect(0, 0, lum.shape[1], lum.shape[0])
    if depth > 6 or rect.w < 2 * MIN_AREA or rect.h < 2 * MIN_AREA:
        return [rect]
    split = _best_split(lum, level, rect)
    if split is None:
        return [rect]
    vertical, first, last = split
    if vertical:
        a = Rect(rect.x, rect.y, first, rect.h)
        b = Rect(rect.x + last + 1, rect.y, rect.w - last - 1, rect.h)
    else:
        a = Rect(rect.x, rect.y, rect.w, first)
        b = Rect(rect.x, rect.y + last + 1, rect.w, rect.h - last - 1)
    if min(a.w, a.h, b.w, b.h) < MIN_STRIP:
        return [rect]
    return split_areas(lum, level, a, depth + 1) + split_areas(lum, level, b, depth + 1)


def name_areas(areas: list[Rect], image_w: int, image_h: int) -> Layout:
    """Name areas by their place in Blender's default layout."""
    if not areas:
        return Layout((), 0.0)
    names: dict[int, RegionName] = {}
    thin = image_h * 0.12   # title+menu strip is a fixed pixel height, so a smaller window makes it a bigger share
    for i, a in enumerate(areas):
        if a.h <= thin and a.w >= image_w * 0.95:
            names[i] = "topbar" if a.y < image_h / 2 else "statusbar"
    rest = [i for i in range(len(areas)) if i not in names]
    if rest:
        viewport = max(rest, key=lambda i: areas[i].w * areas[i].h)
        names[viewport] = "viewport"
        v = areas[viewport]
        for i in rest:
            if i == viewport:
                continue
            a = areas[i]
            right = a.x >= v.x + v.w - 2 and a.w < image_w * 0.45
            below = a.y >= v.y + v.h - 2 and a.x < v.x + v.w
            if right:
                names[i] = "outliner" if a.y + a.h / 2 < image_h * 0.5 else "properties"
            elif below:
                names[i] = "timeline"
    found = {n for n in names.values()}
    expected = {"topbar", "viewport", "outliner", "properties", "timeline", "statusbar"}
    regions = tuple(Region(names.get(i, "unknown"), a) for i, a in enumerate(areas))
    return Layout(regions, len(found & expected) / len(expected))


def detect_layout(bgr: np.ndarray) -> Layout:
    """Find and name the editor areas in a screenshot of the Blender window."""
    h, w = bgr.shape[:2]
    lum = luminance(bgr)
    level = find_gap_level(lum)
    if level is None:
        return name_areas([Rect(0, 0, w, h)], w, h)
    return name_areas(split_areas(lum, level), w, h)


# Fraction-of-window fallback for the default layout. Approximate until measured on real
# captures; only use when detect_layout confidence is low, and never trust it for clicks.
_DEFAULT_FRACTIONS: dict[RegionName, tuple[float, float, float, float]] = {
    "topbar": (0.0, 0.0, 1.0, 0.055),
    "viewport": (0.0, 0.055, 0.82, 0.72),
    "outliner": (0.82, 0.055, 0.18, 0.30),
    "properties": (0.82, 0.355, 0.18, 0.60),
    "timeline": (0.0, 0.775, 0.82, 0.18),
    "statusbar": (0.0, 0.955, 1.0, 0.045),
}


def default_layout(w: int, h: int) -> Layout:
    regions = tuple(
        Region(n, Rect(round(x * w), round(y * h), round(fw * w), round(fh * h)))
        for n, (x, y, fw, fh) in _DEFAULT_FRACTIONS.items())
    return Layout(regions, 0.0)


def region_at(layout: Layout, x: int, y: int) -> RegionName:
    """Which named area a point in the analysed image falls in."""
    for r in layout.regions:
        if r.rect.contains(x, y):
            return r.name
    return "unknown"
