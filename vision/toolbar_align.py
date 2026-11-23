"""Which tools of the toolbar are on screen right now? Pure geometry: no capture, no Blender.

The old way paired the detected toolbar cells with a tool list from the TOP: cell 0 = first tool. That is only true when the toolbar is not scrolled, which is why Loop Cut was highlighted three cells too low
(measured live: 14 cells visible of 21, 159 px scrolled). Here the two things that are known are combined instead:

  * the add-on gives the ORDERED tool list of the current mode, with where its separators are (Blender's own list), and how far the toolbar is scrolled;
  * the pixels give the cells that are visible: where their tops are.

The pixels cannot say WHICH tools those cells are, but their positions can: Blender puts a larger gap at each separator (measured on 5.2.2: normal pitch 34.5 px, 41 px across a separator), so each place the
visible cells could be in the ordered list predicts a different set of tops, and only the right one fits. The fit uses the median deviation, so a cell the detector filled in or cut a few pixels off does not
spoil it (this was found on real scrolled frames: a boolean "is this gap a separator" pattern broke on them). When the visible part holds no separator (every place fits equally) the scroll distance decides.
Blender's layout (a margin, a pitch and a separator extra, all in proportion to the UI scale) is measured and used as the prior.
A result carries the evidence it rests on, so a caller can refuse to point when the evidence is thin.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Blender 5.2.2, default theme, UI scale 1.0 (measured on a real window, see docs/vision-research.md). They scale with the UI scale and are only priors: the pitch is re-measured from the cells.
MARGIN = 9.0           # px from the top of the toolbar region to the first cell
PITCH = 34.5           # px from the top of one cell to the top of the next
SEPARATOR_EXTRA = 6.5  # extra px at a separator
SEP_RATIO = 1.12       # a gap this much larger than the smallest one is a separator


@dataclass(frozen=True)
class Alignment:
    first: int                       # index (among real cells, separators not counted) of the first fully visible cell
    count: int                       # how many consecutive cells are fully visible
    confidence: float
    evidence: tuple[str, ...]
    pitch: float                     # measured, px
    sep_extra: float

    def visible(self, index: int) -> bool:
        return self.first <= index < self.first + self.count

    def relation(self, index: int) -> str:
        """visible | above | below: where a cell is relative to the part that is on screen."""
        return "visible" if self.visible(index) else ("above" if index < self.first else "below")


def sep_flags(entries: list[bool]) -> list[bool]:
    """`entries` is the toolbar in order, True = a separator, False = a cell. Returns, for each pair of consecutive cells, whether a separator lies between them."""
    flags: list[bool] = []
    seen_cell, pending = False, False
    for is_sep in entries:
        if is_sep:
            pending = True
            continue
        if seen_cell:
            flags.append(pending)
        seen_cell, pending = True, False
    return flags


def _content_position(i: int, flags: list[bool], pitch: float, extra: float, margin: float) -> float:
    return margin + i * pitch + sum(flags[:i]) * extra


def full_cells(tops: Sequence[float], heights: Sequence[float], region_h: float) -> list[tuple[float, float]]:
    """(top, height) of the cells that lie wholly inside the toolbar region. A cell cut by the region's edge has a wrong top (and may be the very tool wanted: it counts as not visible yet)."""
    return [(t, h) for t, h in zip(tops, heights, strict=True) if t >= 1 and t + h <= region_h - 1]


def align(tops: Sequence[float], heights: Sequence[float], region_h: float, flags: list[bool], scroll: float, ui_scale: float = 1.0) -> Alignment | None:
    """Align the visible cells with the ordered tool list.

    tops / heights: the detected cells, top to bottom, tops relative to the top of the toolbar region (px).
    region_h: height of the toolbar region (px). flags: `sep_flags` of the ordered list (len = number of cells - 1).
    scroll: how far the toolbar is scrolled down (px; 0 = at the start), from the add-on.
    Returns None when there is nothing to go on (no usable cells and no list)."""
    total = len(flags) + 1
    if total < 1:
        return None
    full = full_cells(tops, heights, region_h)
    margin, pitch, extra = MARGIN * ui_scale, PITCH * ui_scale, SEPARATOR_EXTRA * ui_scale
    evidence: list[str] = []
    if len(full) < 2:
        return _by_scroll(full, total, flags, scroll, region_h, margin, pitch, extra, evidence)

    ts = [t for t, _ in full]
    diffs = [b - a for a, b in zip(ts, ts[1:], strict=False)]
    med = _median(diffs)                                             # most gaps are plain pitches: the median is not fooled by one cut cell (a shorter first gap) or a separator
    if med < 0.5 * pitch or med > 1.6 * pitch:
        return None                                                  # the cells are not the size of toolbar cells: not the toolbar
    normal = sorted(d for d in diffs if d <= med * SEP_RATIO)        # gaps between cells with no separator between them
    pitch_m = normal[len(normal) // 2]
    seps = [d - pitch_m for d in diffs if d > med * SEP_RATIO and d - pitch_m <= 1.6 * extra]
    extra_m = sum(seps) / len(seps) if seps else extra
    n = len(full)

    # Each place the visible cells could be in the list is tried: the cells' tops are compared with where that part of the list puts them. For every place two numbers come out: how well the tops fit
    # (`dev`, a trimmed mean so one cell the detector filled in or cut a few pixels off does not spoil it) and the scroll distance that place would need (`c` is minus that distance).
    scored: list[tuple[float, int, float]] = []
    for k in range(0, total - n + 1):
        r = [ts[j] - _content_position(k + j, flags, pitch_m, extra_m, margin) for j in range(n)]
        c = _median(r)
        d = sorted(abs(x - c) for x in r)
        keep = d[:max(int(len(d) * 0.8), 1)]
        scored.append((sum(keep) / len(keep), k, c))
    # The add-on's scroll distance says which place it is: consecutive places differ by a whole pitch, so there is one within half a pitch. The pixels then must FIT the list there. Real frames showed
    # why the fit alone is not used to choose: the cells' tops are only good to a few pixels, a separator moves a cell by 6.5, and neighbouring places fit almost equally well.
    off, k, c = min((abs(c + scroll), k, c) for _, k, c in scored)
    dev = next(d for d, kk, _ in scored if kk == k)
    if dev > 0.15 * pitch_m:
        return None                                                  # the cells' positions do not fit the tool list there: the wrong mode, a different list, or the detection is wrong
    best_dev, best_k, _ = min(scored)
    evidence.append(f"the positions of the {n} visible cells fit the tool list at that place (average {dev:.1f} px off)")
    if best_k != k and dev > best_dev + 1.5:
        # the pixels clearly prefer another place than the scroll distance gives: the picture was taken while the toolbar was still moving (Blender scrolls smoothly), or the add-on's snapshot is old
        return Alignment(best_k, n, 0.5, (f"the cells' positions say place {best_k + 1}, the add-on's scroll distance says place {k + 1}: the picture and the add-on disagree (a stale picture?)",), pitch_m, extra_m)
    shape_alone = best_k == k and len([t for t in scored if t[0] <= dev + 0.5]) == 1          # the cells' own gaps single this place out, without the scroll distance
    if shape_alone:
        evidence.append("and at no other place: the cells' gaps single it out without the scroll distance")
    if off <= 0.5 * pitch_m:
        evidence.append(f"the add-on's scroll distance puts it there (within {off:.0f} px)")
        return Alignment(k, n, 0.95 if shape_alone else 0.85, tuple(evidence), pitch_m, extra_m)
    return Alignment(k, n, 0.5, tuple(evidence) + (f"but the scroll distance disagrees by {off:.0f} px (a stale picture?)",), pitch_m, extra_m)


def _median(values: list[float]) -> float:
    v = sorted(values)
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _by_scroll(full, total, flags, scroll, region_h, margin, pitch, extra, evidence) -> Alignment | None:
    """No usable cells (fewer than two whole ones): the position from the scroll distance alone. Weak evidence: only one signal."""
    first = next((i for i in range(total) if _content_position(i, flags, pitch, extra, margin) >= scroll - 2), None)
    if first is None:
        return None
    count = 0
    for i in range(first, total):
        top = _content_position(i, flags, pitch, extra, margin) - scroll
        if top + pitch - 1 <= region_h:
            count += 1
        else:
            break
    evidence.append("from the scroll distance only (too few cells found in the picture)")
    return Alignment(first, max(count, 1), 0.5, tuple(evidence), pitch, extra)


def cell_rect(index: int, al: Alignment, full: list[tuple[float, float]], flags: list[bool]) -> tuple[float, float] | None:
    """(top, height) in toolbar-region pixels of a cell inside the aligned window: the detected cell at that place when there is one, else computed from the first detected cell and the measured pitch.
    `full` is `full_cells(...)` of the same detection that was aligned."""
    if not al.visible(index) or not full:
        return None
    j = index - al.first
    if 0 <= j < len(full):
        return full[j]
    t0, h0 = full[0]
    return t0 + j * al.pitch + sum(flags[al.first:index]) * al.sep_extra, h0
