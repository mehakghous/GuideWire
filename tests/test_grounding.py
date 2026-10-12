"""Offline tests for shared/grounding.py (pure geometry; no screen, no model)."""
import pytest

from shared.grounding import (
    CaptureGeometry, Rect, aspect_ratio_drift, check_declared_size, to_screen,
)

# 1920x1080 monitor, image downscaled to 1280x720 (same aspect ratio).
PRIMARY = CaptureGeometry(Rect(0, 0, 1920, 1080), 1280, 720)
# Second monitor sits to the right, offset on the virtual desktop.
SECOND = CaptureGeometry(Rect(1920, -200, 2560, 1440), 1280, 720)


def test_scales_image_pixels_to_screen():
    r = to_screen(PRIMARY, 640, 360)
    assert (r.status, r.x, r.y) == ("ok", 960, 540)


def test_second_monitor_offset_is_applied():
    r = to_screen(SECOND, 0, 0)
    assert (r.x, r.y) == (1920, -200)  # negative y is legal on a virtual desktop
    r = to_screen(SECOND, 1280, 720)
    assert (r.x, r.y) == (1920 + 2560, -200 + 1440)


def test_norm1000_matches_pixels():
    assert to_screen(PRIMARY, 500, 500, "norm1000") == to_screen(PRIMARY, 640, 360, "pixels")


def test_none_is_explicit_abstention():
    r = to_screen(PRIMARY, None, None)
    assert r.status == "none" and r.x is None


def test_slightly_outside_is_clamped_and_flagged():
    r = to_screen(PRIMARY, 1285, 360)  # 5 px past the right edge, within 2 %
    assert r.status == "ok" and r.clamped and r.x == 1920


def test_far_outside_is_refused_not_clamped():
    r = to_screen(PRIMARY, 2000, 360)  # Clicky would clamp this to the edge
    assert r.status == "out_of_bounds" and r.x is None


def test_target_window_rejects_point_outside_blender():
    blender = Rect(100, 100, 1000, 800)
    assert to_screen(PRIMARY, 640, 360, target=blender).status == "ok"
    miss = to_screen(PRIMARY, 1270, 710, target=blender)  # bottom-right corner, outside window
    assert miss.status == "outside_target"


def test_declared_size_mismatch_is_reported():
    assert check_declared_size(PRIMARY, 1280, 720) is None
    assert "2560x1440" in check_declared_size(PRIMARY, 2560, 1440)  # the Retina-style bug


def test_aspect_drift():
    assert aspect_ratio_drift(PRIMARY) == pytest.approx(0.0)
    stretched = CaptureGeometry(Rect(0, 0, 1920, 1080), 1024, 768)  # 16:9 squeezed to 4:3
    assert aspect_ratio_drift(stretched) > 0.2


def test_bad_geometry():
    assert to_screen(CaptureGeometry(Rect(0, 0, 0, 1080), 1280, 720), 1, 1).status == "bad_geometry"
