"""Grounding geometry (PROPOSAL v0.1, for Umaima to accept or change): turn a point the model
reports on a screenshot into a point on the real screen, or refuse.

Pure functions, no I/O. Nothing here finds UI elements; it only makes the hand-off between
"a model said (x, y) on this image" and "draw the highlight here" checkable.

Idea adapted from the Clicky reference app (MIT): label the image with the pixel size the
model sees, then scale image -> display. Differences, on purpose:
  * Clicky silently clamps out-of-range points to the edge. Here a point clearly outside the
    image is REFUSED (a clamped point highlights the wrong control, which is worse than none).
  * Clicky can answer "no element" (`[POINT:none]`). Here that is an explicit `none` result.
  * An optional target rectangle (the Blender window) rejects points that land outside it,
    e.g. on the taskbar or another monitor's window.
All screen coordinates are physical pixels of the virtual desktop, origin top-left.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Slack, as a fraction of the image size, before a point counts as "outside the image".
# Models are slightly imprecise at the edges; anything further out is treated as a miss.
EDGE_TOLERANCE = 0.02

Space = Literal["pixels", "norm1000"]  # norm1000 = 0..1000 on both axes, as some vision models return
Status = Literal["ok", "none", "out_of_bounds", "outside_target", "bad_geometry"]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass(frozen=True)
class CaptureGeometry:
    """What one captured image is: its pixel size and where its monitor sits on the desktop."""
    monitor: Rect          # the monitor, in virtual-desktop physical pixels
    image_w: int           # pixel size of the image actually sent to the model
    image_h: int

    def validate(self) -> str | None:
        if min(self.image_w, self.image_h, self.monitor.w, self.monitor.h) <= 0:
            return "image and monitor sizes must be positive"
        return None


@dataclass(frozen=True)
class GroundingResult:
    status: Status
    x: int | None = None   # screen point, set only when status == "ok"
    y: int | None = None
    clamped: bool = False  # True if the model point was within tolerance but outside the image
    reason: str = ""


def check_declared_size(geometry: CaptureGeometry, declared_w: int, declared_h: int) -> str | None:
    """Return a problem string if the size we TOLD the model differs from the image we SENT.

    Clicky's source documents this exact failure: on Retina a 2x bitmap was sent while the
    tool declared 1x, so every coordinate came back at the wrong scale. Check it before the call.
    """
    if (geometry.image_w, geometry.image_h) != (declared_w, declared_h):
        return (f"declared {declared_w}x{declared_h} but image is "
                f"{geometry.image_w}x{geometry.image_h}")
    return None


def aspect_ratio_drift(geometry: CaptureGeometry) -> float:
    """Relative difference between image and monitor aspect ratios (0 = identical).

    A resize that changes the aspect ratio distorts one axis (Clicky's comments tie this to
    X-axis error). Callers can log or reject captures with large drift.
    """
    a = geometry.image_w / geometry.image_h
    b = geometry.monitor.w / geometry.monitor.h
    return abs(a - b) / b


def to_screen(
    geometry: CaptureGeometry,
    x: float | None,
    y: float | None,
    space: Space = "pixels",
    target: Rect | None = None,
) -> GroundingResult:
    """Map a model-reported point to physical screen pixels, or say why not."""
    problem = geometry.validate()
    if problem:
        return GroundingResult("bad_geometry", reason=problem)
    if x is None or y is None:
        return GroundingResult("none", reason="model reported no element")

    if space == "norm1000":
        ix, iy = x / 1000.0 * geometry.image_w, y / 1000.0 * geometry.image_h
    else:
        ix, iy = float(x), float(y)

    tol_x, tol_y = EDGE_TOLERANCE * geometry.image_w, EDGE_TOLERANCE * geometry.image_h
    if not (-tol_x <= ix <= geometry.image_w + tol_x and -tol_y <= iy <= geometry.image_h + tol_y):
        return GroundingResult(
            "out_of_bounds",
            reason=f"({ix:.0f},{iy:.0f}) is outside {geometry.image_w}x{geometry.image_h}")
    clamped = not (0 <= ix <= geometry.image_w and 0 <= iy <= geometry.image_h)
    ix = min(max(ix, 0.0), float(geometry.image_w))
    iy = min(max(iy, 0.0), float(geometry.image_h))

    m = geometry.monitor
    sx = round(m.x + ix * m.w / geometry.image_w)
    sy = round(m.y + iy * m.h / geometry.image_h)

    if target is not None and not target.contains(sx, sy):
        return GroundingResult("outside_target", sx, sy, clamped,
                               "point is outside the expected application window")
    return GroundingResult("ok", sx, sy, clamped)
