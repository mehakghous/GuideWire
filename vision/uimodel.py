"""The interface as Blender reports it (snapshot v2 from the add-on), and the mapping from Blender's window pixels to the screen and to a captured frame. Pure: no Windows calls, no capture.

Why this exists: the screen can show that "something" is at a place; only Blender knows which area, region, tool and tab that is. The add-on reports every visible area and region with its rectangle
in WINDOW pixels (origin bottom-left, Blender's own convention). To use those rectangles for a highlight or to look at the pixels inside one, three things have to line up, and each was found to
be off in a real window (docs/vision-research.md, section 4):

  1. the y axis points UP in Blender and DOWN on the screen;
  2. Blender's window is the Win32 CLIENT area, which starts below the title bar (31 px in the measured window), while the capture vision takes is the whole window frame;
  3. the snapshot may describe an older window size than the one captured (the learner resized, or the display scaling differs).

`FrameMapper` does 1 and 2 and refuses (`valid` is False) for 3, so a rectangle that no longer means anything is never used to point at something.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.grounding import Rect

SIZE_TOLERANCE = 2          # px: a client area this close to the snapshot's window size is the same window (rounding in a frame border)


@dataclass(frozen=True)
class UiRegion:
    type: str                         # HEADER | TOOL_HEADER | TOOLS | UI | HUD | WINDOW | NAVIGATION_BAR | ...
    rect: Rect                        # window pixels, origin bottom-left
    view_top: float | None = None     # TOOLS only: the visible part of the toolbar in view coordinates (top is 1.0 when not scrolled)
    view_bottom: float | None = None


@dataclass(frozen=True)
class UiArea:
    type: str                         # VIEW_3D | PROPERTIES | OUTLINER | DOPESHEET_EDITOR | ...
    rect: Rect                        # window pixels, origin bottom-left
    regions: tuple[UiRegion, ...] = ()
    context: str | None = None        # PROPERTIES: the active tab
    tabs: tuple[str, ...] = ()        # PROPERTIES: tabs available now, in order
    toolbar_shown: bool | None = None # VIEW_3D
    sidebar_shown: bool | None = None
    has_hud: bool = False             # VIEW_3D: the redo panel (Loop Cut and Slide, ...) is open

    def region(self, kind: str) -> UiRegion | None:
        return next((r for r in self.regions if r.type == kind), None)


@dataclass(frozen=True)
class ToolCell:
    """One cell of the toolbar: the tools that share it (the cell shows one of them) or a separator."""
    tools: tuple[tuple[str, str], ...] = ()    # (id, label) pairs
    separator: bool = False


@dataclass(frozen=True)
class UiModel:
    window_w: int
    window_h: int
    ui_scale: float
    areas: tuple[UiArea, ...]
    tools: tuple[ToolCell, ...] = ()           # the toolbar for the current mode, in order; empty when the add-on could not read it
    mode: str | None = None
    active_tool: str | None = None
    ui_rev: int = 0                            # goes up only when the interface changed
    scene_rev: int = 0                         # goes up only when the scene changed
    version: str | None = None                 # Blender version string
    pid: int | None = None
    keys: dict = field(default_factory=dict)   # operator -> keymap entries asked for

    def area(self, kind: str) -> UiArea | None:
        """The first area of that type; when two 3D views are open, the largest."""
        found = [a for a in self.areas if a.type == kind]
        return max(found, key=lambda a: a.rect.w * a.rect.h, default=None)

    def region(self, area_kind: str, region_kind: str) -> UiRegion | None:
        a = self.area(area_kind)
        return None if a is None else a.region(region_kind)

    def tool_cell_ids(self) -> list[list[str]]:
        """The tool ids of each real cell (separators dropped), in toolbar order."""
        return [[t[0] for t in c.tools] for c in self.tools if not c.separator]


def _rect(d: dict) -> Rect:
    return Rect(int(d["x"]), int(d["y"]), int(d["width"]), int(d["height"]))


def parse(state: dict | None) -> UiModel | None:
    """The UI model from a probe state, or None when the state has no interface block (an add-on older than snapshot v2, or no add-on). Never raises on a malformed state: None."""
    if not state or not isinstance(state.get("ui"), dict):
        return None
    try:
        ui = state["ui"]
        areas = []
        for a in ui["areas"]:
            regions = tuple(UiRegion(r["type"], _rect(r), r.get("view_top"), r.get("view_bottom")) for r in a.get("regions", []))
            areas.append(UiArea(a["type"], _rect(a), regions, a.get("context"), tuple(a.get("tabs", ())), a.get("toolbar_shown"), a.get("sidebar_shown"), bool(a.get("has_hud", False))))
        cells = []
        for item in state.get("tools", []) or []:
            if item.get("separator"):
                cells.append(ToolCell(separator=True))
            else:
                cells.append(ToolCell(tuple((t["id"], t.get("label", t["id"])) for t in item.get("group", []))))
        win = ui["window"]
        return UiModel(int(win["width"]), int(win["height"]), float(ui.get("ui_scale", 1.0)), tuple(areas), tuple(cells), state.get("mode"), state.get("active_tool"),
                       int(state.get("ui_rev", 0)), int(state.get("scene_rev", 0)), state.get("blender_version"), state.get("pid"), dict(state.get("keys") or {}))
    except (KeyError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FrameMapper:
    """Maps rectangles from Blender's window pixels (origin bottom-left) to screen pixels and to the pixels of a captured frame (origin top-left).

    client:   the Win32 client area of the Blender window on the screen (physical pixels): where Blender's drawing starts.
    frame:    the screen rectangle the capture covers (what `vision.capture.grab` was asked for), and the size in pixels of the image it returned.
    """
    window_w: int                    # Blender's window size from the snapshot
    window_h: int
    client: Rect                     # screen pixels
    frame: Rect                      # screen pixels
    image_w: int
    image_h: int

    @property
    def valid(self) -> bool:
        """False when the snapshot and the capture cannot describe the same window: a different size (resized, other scaling) or a client area that is not inside the frame."""
        same_size = abs(self.client.w - self.window_w) <= SIZE_TOLERANCE and abs(self.client.h - self.window_h) <= SIZE_TOLERANCE
        inside = (self.client.x >= self.frame.x - SIZE_TOLERANCE and self.client.y >= self.frame.y - SIZE_TOLERANCE
                  and self.client.x + self.client.w <= self.frame.x + self.frame.w + SIZE_TOLERANCE and self.client.y + self.client.h <= self.frame.y + self.frame.h + SIZE_TOLERANCE)
        return same_size and inside and min(self.image_w, self.image_h, self.frame.w, self.frame.h) > 0

    def to_screen(self, r: Rect) -> Rect:
        """A rectangle in Blender window pixels -> screen pixels."""
        return Rect(self.client.x + r.x, self.client.y + (self.window_h - (r.y + r.h)), r.w, r.h)

    def to_frame(self, r: Rect) -> Rect:
        """A rectangle in Blender window pixels -> pixels of the captured image (the one OCR and the pixel checks read)."""
        s = self.to_screen(r)
        kx, ky = self.image_w / self.frame.w, self.image_h / self.frame.h
        return Rect(round((s.x - self.frame.x) * kx), round((s.y - self.frame.y) * ky), round(s.w * kx), round(s.h * ky))

    def from_frame(self, r: Rect) -> Rect:
        """A rectangle in captured-image pixels -> Blender window pixels (to ask which region a detected thing is in)."""
        kx, ky = self.frame.w / self.image_w, self.frame.h / self.image_h
        sx, sy, sw, sh = self.frame.x + r.x * kx, self.frame.y + r.y * ky, r.w * kx, r.h * ky
        return Rect(round(sx - self.client.x), round(self.window_h - (sy - self.client.y + sh)), round(sw), round(sh))


def mapper_for(model: UiModel, client: Rect, frame: Rect, image_w: int, image_h: int) -> FrameMapper:
    return FrameMapper(model.window_w, model.window_h, client, frame, image_w, image_h)
