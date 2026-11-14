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


def find_target(words, pixels, ui_element: str, mode_hint: str | None = None, toolbar: bool = True) -> Located | None:
    """Text first (menus, panels); icon-only toolbar tools by name when the text search fails."""
    from vision.locate import locate, parse_path
    from vision.regions import default_layout, detect_layout
    from vision.toolbar import find_cells, locate_tool, modes_matching
    found = locate(words, ui_element)
    if found is not None and found.complete or not toolbar:
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


SAME_SCREEN_DIFF = 1.5     # mean grey-level change below which two captures count as the same screen
CACHE_SECONDS = 5.0        # never reuse a reading older than this


class VisionService:
    """One capture and one OCR pass are shared by `ground` and `observe` while the screen is unchanged,
    so the app can call both every tick without paying for the read twice."""

    def __init__(self, title: str | None = None, use_probe: bool = True, app: str = "blender") -> None:
        from vision.apps import profile
        self.profile = profile(app)
        self.title = title or self.profile.title
        self.use_probe = use_probe
        self._cache: dict[str, Any] = {}

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

    def _scene(self):
        """(window, frame, pixels, words, layout) for the screen as it is now, reusing the last read if
        nothing changed. (None, ...) when the window is not visible."""
        import time

        import cv2

        from vision.ocr import read_text
        from vision.regions import default_layout, detect_layout
        win, grabbed = self._frame()
        if win is None:
            return None, None, None, [], None
        frame, pixels = grabbed
        thumb = cv2.resize(cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY), (192, 108), interpolation=cv2.INTER_AREA)
        c = self._cache
        if (c and c["rect"] == win.rect and time.monotonic() - c["at"] < CACHE_SECONDS
                and float(abs(c["thumb"].astype("int16") - thumb.astype("int16")).mean()) < SAME_SCREEN_DIFF):
            return win, frame, pixels, c["words"], c["layout"]
        layout = detect_layout(pixels)
        if layout.confidence < 0.5:
            layout = default_layout(pixels.shape[1], pixels.shape[0])
        words = read_text(pixels)
        self._cache = {"rect": win.rect, "thumb": thumb, "at": time.monotonic(), "words": words, "layout": layout}
        return win, frame, pixels, words, layout

    def ground(self, ui_element: str) -> Guidance:
        win, frame, pixels, words, _ = self._scene()
        if win is None:
            return Guidance(GroundingResult("none", reason=f"no visible window titled '{self.title}'"))
        from vision.probe_client import read_probe
        probe = read_probe(app=self.profile.key) if self.use_probe else None
        found = find_target(words, pixels, ui_element, (probe or {}).get("mode"), toolbar=self.profile.toolbar)
        return ground_located(frame.geometry, win.rect, found)

    def observe(self, properties: list[str] | None = None, attributes: list[str] | None = None) -> dict[str, Any]:
        """State for the evaluator. `properties` / `attributes` are the paths the active step needs read
        by the Blender probe (ignored when the probe is not running)."""
        from vision.observe import observe_blender
        from vision.probe_client import merge_observed, read_probe
        win, _, pixels, words, layout = self._scene()
        probe = (read_probe(properties=properties, attributes=attributes, app=self.profile.key)
                 if self.use_probe else None)
        if win is None or not self.profile.validated:      # hidden, or an app whose screen layout is not built yet
            return merge_observed({}, probe)               # the probe can still answer
        screen = observe_blender(words, pixels, layout, mode_hint=(probe or {}).get("mode"))
        return merge_observed(screen, probe)
