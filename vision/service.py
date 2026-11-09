"""The single entry point the app calls for vision. Observes only: it never sends input.

    svc = VisionService("Blender")
    guidance = svc.ground("File > Import > Wavefront (.obj)")   # where to point, in screen pixels
    observed = svc.observe()                                     # state for ingestion.evaluator

`ground` returns a `shared.grounding.GroundingResult` (the app draws only when status is "ok").
`observe` returns the dict `ingestion.evaluator` reads; keys that cannot be read are absent, which
the evaluator treats as unverifiable rather than wrong. When the Blender probe add-on is running
its exact values override what OCR read from the screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.grounding import CaptureGeometry, GroundingResult, Rect, to_screen
from vision.locate import Located


@dataclass(frozen=True)
class Guidance:
    grounding: GroundingResult          # screen point to point at (centre of the element)
    rect: Rect | None = None            # screen rect of the element, for a highlight
    complete: bool = False              # True when the last part of the path is the one found
    ambiguous: bool = False             # several equally good matches: ask instead of guessing
    matched: str = ""                   # the path part that was found
    observed: dict[str, Any] = field(default_factory=dict)


def ground_located(geometry: CaptureGeometry, window: Rect, found: Located | None) -> Guidance:
    """Turn a located element (frame pixels) into screen coordinates. Pure."""
    if found is None:
        return Guidance(to_screen(geometry, None, None, target=window))
    r = found.rect
    result = to_screen(geometry, r.x + r.w / 2, r.y + r.h / 2, target=window)
    if result.status != "ok":
        return Guidance(result)
    m = geometry.monitor
    sx, sy = m.w / geometry.image_w, m.h / geometry.image_h
    rect = Rect(round(m.x + r.x * sx), round(m.y + r.y * sy), round(r.w * sx), round(r.h * sy))
    return Guidance(result, rect, found.complete, found.alternatives > 0, found.matched)


class VisionService:
    def __init__(self, title: str = "Blender", use_probe: bool = True) -> None:
        self.title = title
        self.use_probe = use_probe

    def _frame(self):
        from vision import winplatform
        from vision.capture import grab, mask_occluders
        winplatform.enable_dpi_awareness()
        win = winplatform.find_window(self.title)
        if win is None:
            return None, None
        frame = grab(win.rect)
        pixels = mask_occluders(frame.pixels, win.rect, winplatform.windows_above(win.hwnd))
        return win, (frame, pixels)

    def ground(self, ui_element: str) -> Guidance:
        from vision.locate import locate
        from vision.ocr import read_text
        win, grabbed = self._frame()
        if win is None:
            return Guidance(GroundingResult("none", reason=f"no visible window titled '{self.title}'"))
        frame, pixels = grabbed
        found = locate(read_text(pixels), ui_element)
        return ground_located(frame.geometry, win.rect, found)

    def observe(self) -> dict[str, Any]:
        from vision.observe import observe_blender
        from vision.ocr import read_text
        from vision.probe_client import merge_observed, read_probe
        from vision.regions import default_layout, detect_layout
        win, grabbed = self._frame()
        if win is None:
            return {}
        _, pixels = grabbed
        layout = detect_layout(pixels)
        if layout.confidence < 0.5:
            layout = default_layout(pixels.shape[1], pixels.shape[0])
        screen = observe_blender(read_text(pixels), pixels, layout)
        return merge_observed(screen, read_probe() if self.use_probe else None)
