"""Offline tests for vision/: window flags, capture maths, region detection, overlay marks.

Region tests run on synthetic frames shaped like Blender's default layout; they prove the
algorithm, not real-Blender accuracy (that needs recorded frames, see vision/regions.py).
"""
import sys

import pytest

from shared.grounding import GroundingResult, Rect, to_screen
from vision import winplatform
from vision.capture import downscale_size
from vision.overlay import highlight_mark, pointer_mark, to_local, visible_marks

np = pytest.importorskip("numpy")

from vision.capture import Frame  # noqa: E402
from vision.regions import default_layout, detect_layout, region_at  # noqa: E402

GAP = 20


def blender_like(w=1920, h=1080) -> "np.ndarray":
    """Dark gaps between flat areas laid out like Blender's default workspace."""
    img = np.full((h, w, 3), GAP, dtype=np.uint8)

    def fill(x, y, fw, fh, v):
        img[y:y + fh, x:x + fw] = v

    fill(0, 0, w, 60, 50)                 # top bar
    fill(0, 64, 1560, 776, 70)            # viewport
    fill(0, 844, 1560, 208, 45)           # timeline
    fill(1564, 64, w - 1564, 316, 40)     # outliner
    fill(1564, 384, w - 1564, 668, 55)    # properties
    fill(0, 1056, w, h - 1056, 48)        # status bar
    return img


def test_downscale_keeps_aspect_and_never_upscales():
    assert downscale_size(1920, 1080, 1280) == (1280, 720)
    assert downscale_size(800, 600, 1280) == (800, 600)


def test_frame_geometry_round_trips_through_grounding():
    f = Frame(np.zeros((720, 1280, 3), dtype=np.uint8), Rect(100, 50, 1920, 1080))
    r = to_screen(f.geometry, 640, 360)
    assert (r.status, r.x, r.y) == ("ok", 100 + 960, 50 + 540)


def test_click_through_flags_include_transparent_and_no_activate():
    s = winplatform.apply_style_flags(0)
    for flag in (winplatform.WS_EX_TRANSPARENT, winplatform.WS_EX_NOACTIVATE,
                 winplatform.WS_EX_LAYERED, winplatform.WS_EX_TOPMOST):
        assert s & flag


@pytest.mark.skipif(sys.platform == "win32", reason="off-Windows behaviour")
def test_windows_calls_refuse_elsewhere():
    with pytest.raises(winplatform.PlatformUnavailable):
        winplatform.find_window()


def test_detects_default_blender_layout():
    layout = detect_layout(blender_like())
    assert layout.confidence == 1.0
    assert {r.name for r in layout.regions} >= {
        "topbar", "viewport", "outliner", "properties", "timeline", "statusbar"}
    vp = layout.get("viewport")
    assert abs(vp.w - 1560) <= 8 and abs(vp.h - 776) <= 8
    assert region_at(layout, 1700, 100) == "outliner"
    assert region_at(layout, 1700, 600) == "properties"
    assert region_at(layout, 300, 900) == "timeline"
    assert region_at(layout, 300, 400) == "viewport"


def test_scales_with_display_scaling():
    big = np.repeat(np.repeat(blender_like(), 2, axis=0), 2, axis=1)   # 3840x2160, gaps 8px
    layout = detect_layout(big)
    assert layout.confidence == 1.0
    assert abs(layout.get("viewport").w - 3120) <= 16


def test_uniform_image_is_not_split():
    layout = detect_layout(np.full((1080, 1920, 3), 70, dtype=np.uint8))
    assert len(layout.regions) == 1 and layout.confidence < 0.5


def test_default_layout_fallback_is_low_confidence_but_complete():
    layout = default_layout(1920, 1080)
    assert layout.confidence == 0.0 and layout.get("viewport") is not None


def test_pointer_only_for_ok_grounding():
    ok = to_screen(Frame(np.zeros((100, 100, 3), dtype=np.uint8), Rect(0, 0, 100, 100)).geometry, 50, 50)
    assert pointer_mark(ok).rect.contains(50, 50)
    assert pointer_mark(GroundingResult("none")) is None
    assert pointer_mark(GroundingResult("out_of_bounds")) is None


def test_marks_are_localised_and_offscreen_marks_dropped():
    origin = Rect(1000, 500, 800, 600)
    inside = highlight_mark(Rect(1100, 600, 50, 20), "Extrude")
    outside = highlight_mark(Rect(0, 0, 50, 20))
    assert to_local(inside, origin).rect.x == 1100 - 4 - 1000
    assert visible_marks([inside, outside], origin) == [to_local(inside, origin)]


def test_real_blender_5_2_default_layout():
    cv2 = pytest.importorskip("cv2")
    img = cv2.imread("tests/fixtures/vision/blender_5_2_default_1920x1008.png")
    layout = detect_layout(img)
    assert layout.confidence == 1.0
    assert region_at(layout, 800, 400) == "viewport"
    assert region_at(layout, 1750, 150) == "outliner"
    assert region_at(layout, 1750, 500) == "properties"
    assert region_at(layout, 800, 940) == "timeline"
    assert region_at(layout, 800, 995) == "statusbar"
    assert region_at(layout, 800, 50) == "topbar"


def test_window_change_classification():
    from vision.tracker import classify
    a = Rect(100, 100, 800, 600)
    assert classify(None, None).kind == "same"
    assert classify(None, a).kind == "found"
    assert classify(a, None).kind == "lost"
    assert classify(a, a).kind == "same"
    moved = classify(a, Rect(150, 90, 800, 600))
    assert (moved.kind, moved.dx, moved.dy) == ("moved", 50, -10)
    assert classify(a, Rect(100, 100, 900, 600)).kind == "resized"


def test_shift_mark_follows_a_window_move():
    from vision.overlay import shift_mark
    m = highlight_mark(Rect(200, 200, 50, 20), "Extrude")
    s = shift_mark(m, 30, -5)
    assert (s.rect.x, s.rect.y, s.rect.w, s.rect.h, s.label) == (m.rect.x + 30, m.rect.y - 5, m.rect.w, m.rect.h, "Extrude")
