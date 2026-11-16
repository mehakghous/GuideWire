"""Test doubles for the vision service: what the bridge talks to (`look()` and `reset()`), with words on a fake screen and optionally the add-on's interface snapshot. No screen, no Windows, no OCR.

Used by the bridge, the session-screen and the live-service tests, so they all describe the same fake world.
"""
from __future__ import annotations

import numpy as np

from shared.grounding import CaptureGeometry, Rect
from vision import uimodel
from vision.grounders import GroundContext
from vision.ocr import Word
from vision.regions import Layout, Region

W, H = 1920, 1080
WINDOW = Rect(0, 0, W, H)
TOPBAR = Rect(0, 0, W, 60)


def word(text: str, x: int, y: int, w: int = 60, h: int = 16, line: int = 1) -> Word:
    return Word(text, Rect(x, y, w, h), line)


def phrase(text: str, x: int, y: int, h: int = 16, line: int = 1) -> list[Word]:
    """One Word per token, the way the OCR returns a phrase ("Object Mode" is two words on one line)."""
    out, cx = [], x
    for tok in text.split():
        w = 8 * len(tok)
        out.append(Word(tok, Rect(cx, y, w, h), line))
        cx += w + 6
    return out


# a screen with the Add menu in the top bar: the words the old fake service stood for
MENU_BAR = [word("Add", 250, 20, 40, 16, 1), word("Object", 330, 20, 60, 16, 1)]


def layout(topbar: Rect = TOPBAR) -> Layout:
    return Layout((Region("topbar", topbar), Region("viewport", Rect(0, 60, 1500, 900))), 1.0)


def make_context(words=None, ui_state=None, mode=None, epoch=None, pixels=None) -> GroundContext:
    """A context for one fake look. `ui_state` is a probe-state dict (snapshot v2) when the add-on should be present: the interface model is parsed from it and the window and frame coincide."""
    model = uimodel.parse(ui_state) if ui_state else None
    mapper = None
    if model is not None:
        mapper = uimodel.mapper_for(model, Rect(0, 0, model.window_w, model.window_h), Rect(0, 0, model.window_w, model.window_h), model.window_w, model.window_h)
    px = pixels if pixels is not None else np.zeros((H, W, 3), np.uint8)
    ph, pw = px.shape[:2]
    geo = CaptureGeometry(Rect(0, 0, pw, ph), pw, ph)
    return GroundContext(model, mapper, geo, px, list(MENU_BAR if words is None else words), layout(), mode, None, epoch)


class FakeService:
    """`look()` returns what a real service would: the observed dict and a context (None when the window is not visible)."""

    def __init__(self, observed=None, words=None, found=True, ui_state=None, boom=None, epoch=None, pixels=None):
        self.observed, self.words, self.found, self.ui_state, self.boom, self.epoch, self.pixels = observed or {}, words, found, ui_state, boom, epoch, pixels
        self.looks: list[tuple] = []
        self.resets = 0

    def look(self, properties=None, attributes=None, keys=None):
        self.looks.append((properties, attributes, keys))
        if self.boom:
            raise self.boom
        observed = dict(self.observed)
        if not self.found:
            return observed, None
        return observed, make_context(self.words, self.ui_state, observed.get("mode"), self.epoch, self.pixels)

    def observe(self, properties=None, attributes=None):
        return self.look(properties, attributes)[0]

    def reset(self):
        self.resets += 1


# ---- a toolbar world: the add-on's snapshot and a frame whose pixels hold the toolbar cells, for the tool grounder
CELL_H, CELL_W, CELL_X = 33, 37, 6                              # the detector scans from 4 px inside the viewport: a cell must start there
TB_X, TB_TOP_FROM_BOTTOM, TB_W, TB_H = 2, 71, 56, 548           # the toolbar region of the measured 1366x697 window (window pixels, origin bottom-left)
WIN_W, WIN_H = 1366, 697


def tool_state(mode="EDIT_MESH", scroll=0.0, active_tool="builtin.select_box", toolbar_shown=True, hud=False, tabs=None, context="OBJECT", ui_rev=1, tb_h=TB_H):
    """A probe snapshot (v2) of a Blender window with the given mode, toolbar scroll and shown parts, using the REAL tool list of that mode from the catalog."""
    from shared import shortcuts
    rows = shortcuts.catalog()["tools"][mode]
    tools = [{"separator": True} if "separator" in r else {"group": [{"id": t["id"], "label": t["label"]} for t in r["group"]]} for r in rows]
    regions = [{"type": "HEADER", "x": 2, "y": 645, "width": 1119, "height": 26}, {"type": "WINDOW", "x": 2, "y": 71, "width": 1119, "height": 600}]
    if toolbar_shown:
        regions.append({"type": "TOOLS", "x": TB_X, "y": TB_TOP_FROM_BOTTOM, "width": TB_W, "height": tb_h, "view_top": round(1.0 - scroll, 1), "view_bottom": round(1.0 - scroll - tb_h, 1)})
    if hud:
        regions.append({"type": "HUD", "x": 58, "y": 71, "width": 300, "height": 120})
    return {"mode": mode, "active_tool": active_tool, "ui_rev": ui_rev, "scene_rev": 1, "snapshot_version": 2, "tools": tools, "pid": 1, "ui": {
        "window": {"width": WIN_W, "height": WIN_H}, "ui_scale": 1.0, "areas": [
            {"type": "VIEW_3D", "x": 2, "y": 71, "width": 1119, "height": 600, "toolbar_shown": toolbar_shown, "sidebar_shown": False, "has_hud": hud, "regions": regions},
            {"type": "PROPERTIES", "x": 1124, "y": 23, "width": 240, "height": 527, "context": context, "tabs": tabs or ["TOOL", "RENDER", "OBJECT", "MODIFIER", "DATA"],
             "regions": [{"type": "NAVIGATION_BAR", "x": 1124, "y": 23, "width": 29, "height": 501}, {"type": "WINDOW", "x": 1153, "y": 23, "width": 211, "height": 501}]}]}}


def toolbar_pixels(state: dict, scroll: float = 0.0, active_index: int | None = None, hover_missing: int | None = None, shift: float = 0.0):
    """A frame (window size) with the toolbar cells drawn the way Blender lays them out: pitch 34.5, 6.5 more at each separator, 9 px margin (measured on a real window, docs/vision-research.md). `shift` moves
    every cell (a frame caught before the toolbar finished scrolling); `hover_missing` leaves one cell undrawn (the hovered cell is lighter and is not found)."""
    from vision.toolbar_align import MARGIN, PITCH, SEPARATOR_EXTRA, sep_flags
    px = np.full((WIN_H, WIN_W, 3), 90, np.uint8)                      # the viewport's own grey
    flags = sep_flags([bool(t.get("separator")) for t in state["tools"]])
    tb_h = next((r["height"] for a in state["ui"]["areas"] for r in a["regions"] if r["type"] == "TOOLS"), TB_H)
    top0 = WIN_H - (TB_TOP_FROM_BOTTOM + tb_h)                          # toolbar region top in the frame
    for i in range(len(flags) + 1):
        top = MARGIN + i * PITCH + sum(flags[:i]) * SEPARATOR_EXTRA - scroll + shift
        y0, y1 = round(top0 + max(top, 0)), round(top0 + min(top + CELL_H, tb_h))
        if y1 - y0 <= 0 or top + CELL_H < 0 or top > tb_h or i == hover_missing:
            continue
        px[y0:y1, CELL_X:CELL_X + CELL_W] = (200, 120, 40) if i == active_index else (50, 50, 50)
    return px


def tool_world(mode="EDIT_MESH", scroll=0.0, active_tool="builtin.select_box", **kw):
    """(probe state, frame pixels) for a toolbar scrolled by `scroll` px; the cell of `active_tool` is drawn blue."""
    st = tool_state(mode, scroll, active_tool, **kw)
    groups = [[t["id"] for t in e["group"]] for e in st["tools"] if "group" in e]
    ai = next((i for i, g in enumerate(groups) if active_tool in g), None)
    return st, toolbar_pixels(st, scroll, ai)
