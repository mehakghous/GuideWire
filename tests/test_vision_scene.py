"""The single screen reader: when to read again and how much. No screen, no OCR (a counting fake), no Windows."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from shared.grounding import Rect
from vision.ocr import Word

pytest.importorskip("cv2")
import cv2  # noqa: E402

from vision import scene as sc  # noqa: E402
from vision import uimodel  # noqa: E402

W, H = 1368, 729
WINDOW = Rect(0, 0, W, H)


def _frame(level=60):
    return np.full((H, W, 3), level, np.uint8)


class Ocr:
    """Counts reads and returns one word named after the size of what it was given."""

    def __init__(self):
        self.calls = []

    def __call__(self, px, scale):
        self.calls.append(px.shape[:2])
        return [Word(f"W{px.shape[0]}x{px.shape[1]}", Rect(1, 1, 10, 5), 1)]


@pytest.fixture
def reader():
    ocr, clock = Ocr(), SimpleNamespace(t=1000.0)
    r = sc.SceneReader(ocr, lambda px: SimpleNamespace(confidence=1.0), clock=lambda: clock.t)
    r.ocr, r.clock = ocr, clock
    return r


def test_the_first_look_reads_everything_and_a_still_screen_costs_nothing(reader):
    px = _frame()
    assert reader.read(px, WINDOW).how == "full"
    assert reader.read(px, WINDOW).how == "none" and reader.read(px, WINDOW).how == "none"
    assert reader.ocr.calls == [(H, W)]
    s = reader.stats
    assert (s.looks, s.full, s.area, s.none) == (3, 1, 0, 2)


def test_a_menu_opening_reads_only_its_area_and_keeps_the_other_words(reader):
    px = _frame()
    reader.read(px, WINDOW)
    px2 = px.copy()
    px2[60:260, 240:420] = 200                                           # a menu: a compact area
    s = reader.read(px2, WINDOW)
    assert s.how == "area" and s.box.w < W / 2 and s.box.h < H / 2
    assert reader.ocr.calls[-1] == (s.box.h, s.box.w)
    assert {w.text for w in s.words} >= {f"W{H}x{W}", f"W{s.box.h}x{s.box.w}"}      # the old word outside the area stays, the fresh one is added


def test_a_toggled_checkbox_is_seen_now_and_was_missed_before():
    """A checkbox is about 12 px wide and changes by ~40 grey levels. The old 192x108 thumbnail made that two cells (below the 3 needed); the reader's finer one makes it about nine."""
    a = _frame(60)
    b = a.copy()
    b[300:312, 500:512] = 100
    gray = lambda im, size: cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), size, interpolation=cv2.INTER_AREA)   # noqa: E731
    assert sc.changed_box(gray(a, sc.THUMB), gray(b, sc.THUMB)) is None
    assert sc.changed_box(gray(a, sc.READER_THUMB), gray(b, sc.READER_THUMB)) is not None
    r = sc.SceneReader(Ocr(), lambda px: None)
    r.read(a, WINDOW)
    assert r.read(b, WINDOW).how == "area"


def test_most_of_the_window_changing_or_the_window_moving_reads_everything(reader):
    reader.read(_frame(), WINDOW)
    assert reader.read(_frame(200), WINDOW).how == "full"
    assert reader.read(_frame(200), Rect(30, 40, W, H)).how == "full"             # moved
    assert reader.read(_frame(200), Rect(30, 40, W, H), force_full=True).how == "full"


def test_a_full_read_is_forced_now_and_then_so_merged_reads_cannot_drift(reader):
    px = _frame()
    reader.read(px, WINDOW)
    reader.clock.t += sc.REFRESH_SECONDS - 1
    assert reader.read(px, WINDOW).how == "none"
    reader.clock.t += 2
    assert reader.read(px, WINDOW).how == "full"


def test_a_redraw_of_the_busy_viewport_is_not_text_but_a_menu_over_it_still_is(reader):
    viewport = Rect(60, 90, 1000, 540)
    px = _frame()
    reader.read(px, WINDOW, busy=[viewport])
    rng = np.random.default_rng(1)
    orbit = px.copy()
    orbit[90:630, 60:1060] = rng.integers(0, 255, (540, 1000, 3), dtype=np.uint8)          # the whole 3D view redrawn
    assert reader.read(orbit, WINDOW, busy=[viewport]).how == "none"                      # no OCR for it
    assert reader.ocr.calls == [(H, W)]
    menu = orbit.copy()
    menu[150:350, 300:480] = 230                                                          # then a menu opens over the view
    s = reader.read(menu, WINDOW, busy=[viewport])
    assert s.how == "area", "the redraw must not make the later menu look like part of a redraw (the reference picture was brought up to date)"


def test_without_a_busy_region_the_same_redraw_costs_a_full_read(reader):
    px = _frame()
    reader.read(px, WINDOW)
    orbit = px.copy()
    orbit[90:630, 60:1060] = np.random.default_rng(1).integers(0, 255, (540, 1000, 3), dtype=np.uint8)
    assert reader.read(orbit, WINDOW).how == "full"                                       # what happened before


def test_small_changes_below_the_threshold_add_up_until_they_are_read(reader):
    px = _frame()
    reader.read(px, WINDOW)
    seen = []
    for i in range(6):
        px = px.copy()
        px[400:404, 300 + i * 4:304 + i * 4] = 120                                          # a few pixels each look: too small alone
        seen.append(reader.read(px, WINDOW).how)
    assert "none" in seen and "area" in seen                                              # compared with the last READ picture, so the sum is eventually seen


def test_the_layout_comes_from_what_blender_reported_when_it_can_be_trusted():
    state = {"ui": {"window": {"width": 1366, "height": 697}, "ui_scale": 1.0, "areas": [
        {"type": "VIEW_3D", "x": 2, "y": 71, "width": 1119, "height": 600, "regions": []},
        {"type": "OUTLINER", "x": 1124, "y": 520, "width": 240, "height": 140, "regions": []},
        {"type": "PROPERTIES", "x": 1124, "y": 23, "width": 240, "height": 493, "regions": []},
        {"type": "DOPESHEET_EDITOR", "x": 2, "y": 23, "width": 1119, "height": 44, "regions": []}]}}
    model = uimodel.parse(state)
    mp = uimodel.mapper_for(model, Rect(0, 31, 1366, 697), Rect(-1, 0, 1368, 729), 1368, 729)
    layout = sc.layout_from_model(model, mp, 1368, 729)
    assert layout.confidence == 1.0
    names = {r.name for r in layout.regions}
    assert {"viewport", "outliner", "properties", "timeline", "topbar", "statusbar"} <= names
    vp = layout.get("viewport")
    assert (vp.x, vp.y, vp.w, vp.h) == (3, 31 + 26, 1119, 600)                            # window pixels flipped and moved below the title bar
    assert layout.get("topbar").h == 57 and layout.get("statusbar").y == 31 + 697 - 23    # the band above the highest area; the band below the lowest
