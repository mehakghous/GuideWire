"""Screen capture: grab a monitor or a window's screen area and describe it for grounding.

`Frame` carries the pixels plus the `CaptureGeometry` that `shared.grounding.to_screen` needs,
so a point the model reports on a (possibly downscaled) frame maps back to the real screen.
The capture is of the screen area under the window, so another window covering Blender is
captured too; callers that care should check `find_window` still reports Blender in front.
Captured frames are only held in memory; saving them is the caller's choice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.grounding import CaptureGeometry, Rect

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class Frame:
    pixels: "np.ndarray"       # H x W x 3, BGR, uint8
    region: Rect               # where these pixels came from, virtual-desktop physical pixels

    @property
    def geometry(self) -> CaptureGeometry:
        h, w = self.pixels.shape[:2]
        return CaptureGeometry(self.region, w, h)


def downscale_size(w: int, h: int, max_long_edge: int) -> tuple[int, int]:
    """Size with the same aspect ratio whose longer edge is at most `max_long_edge`."""
    long_edge = max(w, h)
    if long_edge <= max_long_edge:
        return w, h
    k = max_long_edge / long_edge
    return max(1, round(w * k)), max(1, round(h * k))


def grab(region: Rect) -> Frame:
    """Capture a rectangle of the virtual desktop."""
    import mss
    import numpy as np
    with mss.mss() as sct:
        shot = sct.grab({"left": region.x, "top": region.y, "width": region.w, "height": region.h})
    bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
    return Frame(np.ascontiguousarray(bgra[:, :, :3]), region)


def grab_primary_monitor() -> Frame:
    import mss
    with mss.mss() as sct:
        m = sct.monitors[1]
    return grab(Rect(m["left"], m["top"], m["width"], m["height"]))


def grab_window(hwnd: int) -> Frame:
    from vision import winplatform
    return grab(winplatform.window_rect(hwnd))


def mask_occluders(pixels, window: Rect, occluders: list[Rect]):
    """Black out the parts of a captured window frame that another window covers, so text from
    the covering window is never read as if it belonged to this one. Returns a new array."""
    out = pixels.copy()
    h, w = out.shape[:2]
    for o in occluders:
        x0, y0 = max(o.x - window.x, 0), max(o.y - window.y, 0)
        x1, y1 = min(o.x + o.w - window.x, w), min(o.y + o.h - window.y, h)
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = 0
    return out


def resized(frame: Frame, max_long_edge: int) -> Frame:
    """Downscale for a model call. `frame.geometry` then records the new image size."""
    import cv2
    h, w = frame.pixels.shape[:2]
    nw, nh = downscale_size(w, h, max_long_edge)
    if (nw, nh) == (w, h):
        return frame
    return Frame(cv2.resize(frame.pixels, (nw, nh), interpolation=cv2.INTER_AREA), frame.region)
