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


def find_target(words, pixels, ui_element: str, mode_hint: str | None = None) -> Located | None:
    """Text first (menus, panels); icon-only toolbar tools by name when the text search fails."""
    from vision.locate import locate, parse_path
    from vision.regions import default_layout, detect_layout
    from vision.toolbar import find_cells, locate_tool, modes_matching
    found = locate(words, ui_element)
    if found is not None and found.complete:
        return found
    layout = detect_layout(pixels)
    viewport = (layout if layout.confidence >= 0.5 else default_layout(pixels.shape[1], pixels.shape[0])).get("viewport")
    if viewport is None:
        return found
    cells = find_cells(pixels, viewport)
    path = parse_path(ui_element)
    for mode in modes_matching(cells, mode_hint):
        rect = locate_tool(cells, mode, path[-1]) if path else None
        if rect is not None:
            return Located(rect, path[-1], len(path) - 1, len(path), 1.0)
    return found


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
        from vision.ocr import read_text
        win, grabbed = self._frame()
        if win is None:
            return Guidance(GroundingResult("none", reason=f"no visible window titled '{self.title}'"))
        frame, pixels = grabbed
        from vision.probe_client import read_probe
        probe = read_probe() if self.use_probe else None
        found = find_target(read_text(pixels), pixels, ui_element, (probe or {}).get("mode"))
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
        probe = read_probe() if self.use_probe else None
        screen = observe_blender(read_text(pixels), pixels, layout, mode_hint=(probe or {}).get("mode"))
        return merge_observed(screen, probe)
