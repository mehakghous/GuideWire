"""Which toolbar cells are on screen: the alignment of detected cells with Blender's ordered tool list. The first test uses a REAL detection (a Blender 5.2.2 window, Edit Mesh, toolbar not scrolled): the
tops were measured on screen. The others model scrolled toolbars with the same measured layout (pitch 34.5, 6.5 more at a separator, 9 px margin)."""
from __future__ import annotations

import pytest

from shared import shortcuts
from vision.toolbar_align import MARGIN, PITCH, SEPARATOR_EXTRA, align, cell_rect, full_cells, sep_flags


@pytest.fixture(scope="module")
def flags():
    rows = shortcuts.catalog()["tools"]["EDIT_MESH"]
    return sep_flags(["separator" in r for r in rows])


def model_cells(flags, scroll, region_h=548, ui=1.0):
    """The cells a toolbar scrolled by `scroll` shows, as (tops, heights), partial cells included (they are what the detector also finds)."""
    tops, hs = [], []
    for i in range(len(flags) + 1):
        top = (MARGIN + i * PITCH + sum(flags[:i]) * SEPARATOR_EXTRA) * ui - scroll
        if top + 34 > 0 and top < region_h:
            tops.append(round(max(top, 0))), hs.append(round(min(top + 34, region_h) - max(top, 0)))
    return tops, hs


def test_separator_flags_mark_the_pairs_of_cells_a_separator_lies_between():
    assert sep_flags([False, False, True, False, True, True, False]) == [False, True, True]
    assert sep_flags([True, False, False]) == [False]                              # a leading separator belongs to no pair


def test_on_a_real_unscrolled_detection_the_first_cell_is_the_first_tool(flags):
    tops = [9, 43, 84, 118, 153, 188, 229, 263, 304, 344, 378, 413, 448, 483]       # measured on screen: Blender 5.2.2, Edit Mesh, 548 px toolbar
    hs = [33, 34, 33, 34, 34, 34, 33, 34, 33, 33, 34, 34, 34, 34]
    al = align(tops, hs, 548, flags, 0.0)
    assert (al.first, al.count, al.confidence) == (0, 14, 0.95)
    assert al.visible(12) and al.relation(14) == "below" and "scroll distance puts it there" in " ".join(al.evidence)


@pytest.mark.parametrize("scroll,first", [(0, 0), (40, 1), (80, 2), (159, 5), (223, 6)])
def test_a_scrolled_toolbar_is_aligned_by_its_gaps_and_confirmed_by_the_scroll_distance(flags, scroll, first):
    tops, hs = model_cells(flags, scroll)
    al = align(tops, hs, 548, flags, scroll)
    assert al is not None and al.first == first, (scroll, al)
    assert al.confidence >= 0.85 and len(al.evidence) >= 2


def test_the_old_top_down_pairing_would_have_named_the_wrong_tool_here(flags):
    """What the old code did with 159 px scrolled: cell 0 of the screen = tool 0. The alignment says it is tool 5."""
    tops, hs = model_cells(flags, 159)
    assert align(tops, hs, 548, flags, 159).first == 5 != 0


def test_a_cell_cut_by_the_regions_edge_is_not_counted_as_visible(flags):
    tops, hs = model_cells(flags, 159)                                                # the first detected cell is cut at the top edge
    full = full_cells(tops, hs, 548)
    assert len(full) < len(tops)
    al = align(tops, hs, 548, flags, 159)
    assert al.first == 5 and al.relation(4) == "above"                                # cell 4 is partly hidden: not visible yet


def test_when_the_visible_gaps_fit_many_places_the_scroll_distance_chooses(flags):
    """A short toolbar (200 px) showing only the cells after the last separator: every place with no separator fits the gap pattern."""
    scroll = 330
    tops, hs = model_cells(flags, scroll, region_h=200)
    al = align(tops, hs, 200, flags, scroll)
    assert al is not None and al.first == next(i for i in range(len(flags) + 1) if MARGIN + i * PITCH + sum(flags[:i]) * SEPARATOR_EXTRA - scroll >= 1)
    assert "scroll distance puts it there" in " ".join(al.evidence) and al.confidence < 0.95          # the shape alone cannot tell the places apart: only the scroll distance chooses, so less sure


def test_a_stale_picture_is_noticed_because_the_pixels_and_the_scroll_distance_disagree(flags):
    tops, hs = model_cells(flags, 159)
    al = align(tops, hs, 548, flags, 40)                                                # the add-on says 40 px; the picture shows 159 px scrolled
    assert al.first == 5 and al.confidence == 0.5 and "disagree" in " ".join(al.evidence)


def test_cells_that_match_no_part_of_the_list_give_no_alignment(flags):
    assert align([10, 100, 190], [34, 34, 34], 548, flags, 0) is None                 # not toolbar-sized gaps


def test_with_no_usable_cells_the_scroll_distance_alone_gives_a_weak_alignment(flags):
    al = align([], [], 548, flags, 223)
    assert al is not None and al.first >= 5 and al.confidence == 0.5 and "scroll distance only" in al.evidence[0]


def test_a_missing_middle_cell_breaks_the_gap_pattern_so_there_is_no_alignment_but_a_cell_is_placed_from_its_neighbours(flags):
    tops, hs = model_cells(flags, 0)
    miss = 5
    assert align(tops[:miss] + tops[miss + 1:], hs[:miss] + hs[miss + 1:], 548, flags, 0) is None          # the detector's gap is twice a pitch: not a toolbar pattern, so it refuses rather than guesses
    al = align(tops, hs, 548, flags, 0)
    top, _h = cell_rect(5, al, full_cells(tops, hs, 548)[:3], flags)                                        # only three cells detected: the fifth is computed from the first and the pitch
    assert abs(top - (MARGIN + 5 * PITCH + sum(flags[:5]) * SEPARATOR_EXTRA)) <= 3


def test_the_measured_constants_are_documented():
    assert (MARGIN, PITCH, SEPARATOR_EXTRA) == (9.0, 34.5, 6.5)
    assert "34.5" in open("docs/vision-research.md", encoding="utf-8").read()                                # the Part C measurements section records where they come from


# REAL detections from a Blender 5.2.2 window (scripts/vision_live_suite.py, Edit Mesh): the tops and heights `find_cells` returned, the toolbar's scroll distance from the add-on, and the cell Blender
# drew in blue (the active tool), which is where that tool REALLY is. The cells' tops are only good to a few pixels, which broke the first boolean gap-pattern matching.
REAL = [
    # (scroll px, tops, heights, index of the blue cell among the detected ones, tool index of the active tool)
    (79, [7, 38, 73, 108, 151, 183, 218, 266, 298, 333, 368, 403, 438, 473, 508], [30, 34, 34, 32, 31, 32, 34, 31, 34, 34, 34, 34, 34, 34, 34], 10, 12),       # Loop Cut active
    (222, [8, 40, 74, 122, 155, 190, 225, 260, 295, 330, 365, 400, 435, 470, 505], [31, 31, 34, 32, 34, 34, 34, 34, 34, 34, 34, 34, 34, 34, 31], 3, 9),          # Extrude Region active
]


@pytest.mark.parametrize("scroll,tops,heights,blue,tool_index", REAL)
def test_on_real_scrolled_detections_the_blue_cell_is_exactly_where_the_alignment_says_that_tool_is(flags, scroll, tops, heights, blue, tool_index):
    full = full_cells(tops, heights, 548)
    kept = [i for i, (t, h) in enumerate(zip(tops, heights, strict=True)) if t >= 1 and t + h <= 547]
    al = align(tops, heights, 548, flags, scroll)
    assert al is not None and al.confidence >= 0.85, al
    assert al.first + kept.index(blue) == tool_index                                   # the independent truth: the active tool's own cell
    assert len(full) == al.count
