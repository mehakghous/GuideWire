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
from typing import TYPE_CHECKING, Any

from shared.grounding import CaptureGeometry, GroundingResult, Rect, to_screen
from vision.locate import Located

if TYPE_CHECKING:
    from vision.uimodel import FrameMapper, UiModel


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


class VisionService:
    """One capture and one OCR pass are shared by `ground` and `observe`: `SceneReader` (vision/scene.py) decides on every call whether the pixels changed, and reads only what did."""

    takes_hints = True        # `ground` accepts `mode_hint` and `prefer_toolbar` as arguments (the bridge checks this before passing them)

    def __init__(self, title: str | None = None, use_probe: bool = True, app: str = "blender") -> None:
        from vision.apps import profile
        from vision.scene import SceneReader
        self.profile = profile(app)
        self.title = title or self.profile.title
        self.use_probe = use_probe
        self._reader = SceneReader(self._read_text, self._detect_layout)
        self.ui: UiModel | None = None            # vision.uimodel.UiModel from the add-on at the last look, or None (no add-on, an older one, or the snapshot is for another window size)
        self.mapper: FrameMapper | None = None        # vision.uimodel.FrameMapper for that look; None whenever `ui` cannot be trusted for the captured frame

    @staticmethod
    def _read_text(pixels, scale):
        from vision import ocr
        return ocr.read_text(pixels, scale)

    def _detect_layout(self, pixels):
        """The areas of the window: from what Blender reported when it can be trusted for this very frame, else guessed from pixel gaps (which failed on a plain default frame in a live check)."""
        from vision.regions import default_layout, detect_layout
        from vision.scene import layout_from_model
        if self.ui is not None and self.mapper is not None:
            return layout_from_model(self.ui, self.mapper, pixels.shape[1], pixels.shape[0])
        layout = detect_layout(pixels)
        return layout if layout.confidence >= 0.5 else default_layout(pixels.shape[1], pixels.shape[0])

    def _frame(self):
        from vision import winplatform
        from vision.capture import grab, mask_occluders
        winplatform.enable_dpi_awareness()
        win = None
        if self.use_probe:                                   # with two Blenders open, the one running the add-on is the one to read
            from vision.probe_client import probe_info
            info = probe_info(self.profile.key)
            if info and isinstance(info.get("pid"), int):
                win = winplatform.find_window(self.title, self.profile.exe, info["pid"])
        win = win or winplatform.find_window(self.title, self.profile.exe)
        if win is None:
            return None, None
        frame = grab(win.rect)
        pixels = mask_occluders(frame.pixels, win.rect, winplatform.windows_above(win.hwnd))
        return win, (frame, pixels)

    def _read_ui(self, win, frame, pixels) -> None:
        """The add-on's interface block for this frame: `self.ui`, and `self.mapper` only when the snapshot and the capture describe the same window (same size, client area inside the frame)."""
        self.ui = self.mapper = None
        if not self.use_probe or not getattr(frame, "region", None):
            return
        from vision import uimodel, winplatform
        from vision.probe_client import read_probe
        model = uimodel.parse(read_probe(app=self.profile.key))
        if model is None:
            return
        client = winplatform.client_rect(win.hwnd)
        mapper = None if client is None else uimodel.mapper_for(model, client, frame.region, pixels.shape[1], pixels.shape[0])
        self.ui, self.mapper = (model, mapper) if mapper is not None and mapper.valid else (None, None)

    def _scene(self):
        """(window, frame, pixels, words, layout) for the screen as it is now; only what changed since the last call is read. (None, ...) when the window is not visible."""
        win, grabbed = self._frame()
        if win is None:
            self._reader.reset()
            self.ui = self.mapper = None
            return None, None, None, [], None
        frame, pixels = grabbed
        self._read_ui(win, frame, pixels)
        busy = []
        if self.mapper is not None:                          # the 3D viewport redraws while the learner orbits or drags: that is not text
            viewport = self.ui.region("VIEW_3D", "WINDOW")
            if viewport is not None:
                busy.append(self.mapper.to_frame(viewport.rect))
        scene = self._reader.read(pixels, win.rect, busy=busy or None)
        return win, frame, pixels, scene.words, scene.layout

    def reset(self) -> None:
        """Forget what was read, so the next look reads the whole window."""
        self._reader.reset()

    def ground(self, ui_element: str, mode_hint: str | None = None, prefer_toolbar: bool = False) -> Guidance:
        win, frame, pixels, words, _ = self._scene()
        if win is None:
            return Guidance(GroundingResult("none", reason=f"no visible window titled '{self.title}'"))
        from vision.probe_client import read_probe
        probe = read_probe(app=self.profile.key) if self.use_probe else None
        if self.use_probe and probe is None:
            from shared.diagnostics import get_logger, log_every
            import logging
            log_every(get_logger("vision"), f"probe-missing-{self.profile.key}", 300, logging.INFO,
                      "no %s probe answered; using the screen alone (the probe gives exact state and tool positions)", self.profile.key)
        if self.profile.key == "maya":
            return self._ground_maya(ui_element, win, frame, pixels, words, probe)
        found = find_target(words, pixels, ui_element, mode_hint or (probe or {}).get("mode"), toolbar=self.profile.toolbar)
        return ground_located(frame.geometry, win.rect, found)

    # ---- Maya: its own widgets say where the icons and menus are; the screen text finds what opens beneath them
    def _maya_ui(self, win, probe):
        """The probe's interface model for Maya, only when it describes the window as it is on screen right now."""
        from vision import winplatform
        from vision.mayaui import MayaUi
        ui = MayaUi.parse(probe)
        if ui is None or not ui.valid_for(winplatform.client_rect(win.hwnd)):
            return None
        return ui

    def _ground_maya(self, ui_element, win, frame, pixels, words, probe) -> Guidance:
        from vision.locate import locate
        ui = self._maya_ui(win, probe)
        found = locate(words, ui_element)
        if found is not None and found.depth >= 1:                  # a menu is open and its item was read from the screen: that is the most specific answer
            return ground_located(frame.geometry, win.rect, found)
        hit = ui.find(ui_element) if ui is not None else None
        if hit is not None:                                         # icons and the menu bar: exact, from Maya itself
            r = hit.rect
            if not (win.rect.x <= r.x and win.rect.y <= r.y and r.x + r.w <= win.rect.x + win.rect.w and r.y + r.h <= win.rect.y + win.rect.h):
                return Guidance(GroundingResult("outside_target", reason="that part of Maya is outside its window"))
            point = GroundingResult("ok", r.x + r.w // 2, r.y + r.h // 2)
            return Guidance(point, r, hit.complete, False, hit.name)
        return ground_located(frame.geometry, win.rect, found)

    def region_rect(self, region: str, anchor: str = "center") -> Rect | None:
        """Where a named part of the application is, for pointing at "where it happens" when there is nothing to find by text. Maya only (from the probe)."""
        if self.profile.key != "maya" or not self.use_probe:
            return None
        from vision import winplatform
        from vision.mayaui import MayaUi
        from vision.probe_client import read_probe
        win = winplatform.find_window(self.title, self.profile.exe)
        ui = MayaUi.parse(read_probe(app="maya")) if win is not None else None
        if ui is None or win is None or not ui.valid_for(winplatform.client_rect(win.hwnd)):
            return None
        name = {"toolbar": "toolbox", "properties": "channelbox"}.get(region, region)
        return ui.region(name)

    def observe(self, properties: list[str] | None = None, attributes: list[str] | None = None) -> dict[str, Any]:
        """State for the evaluator. `properties` / `attributes` are the paths the active step needs read
        by the Blender probe (ignored when the probe is not running)."""
        from vision.observe import observe_blender
        from vision.probe_client import merge_observed, read_probe
        win, _, pixels, words, layout = self._scene()
        probe = (read_probe(properties=properties, attributes=attributes, app=self.profile.key)
                 if self.use_probe else None)
        if win is None or not self.profile.validated or self.profile.key != "blender":   # hidden, or an app with no screen-only reading (Maya, Houdini): the probe answers
            return merge_observed({}, probe)
        screen = observe_blender(words, pixels, layout, mode_hint=(probe or {}).get("mode"))
        return merge_observed(screen, probe)
