"""Grounders: where, on the screen, is the thing a resolved target (`TargetRef`) means, and can the learner reach it right now? One grounder per kind of target, each returning a `Grounded` that says what it
KNOWS, not just where to draw:

  visible            the control is on screen and was located (a rectangle, with the evidence it rests on);
  offscreen          it exists but is scrolled out of view (the rectangle is the REGION to scroll, `direction` says which way);
  container_hidden   the editor part that holds it is not shown (the toolbar is hidden);
  wrong_context      it does not exist where the learner is (a Loop Cut tool while in Object Mode; the Data tab is not the open one);
  not_open           it only appears after an action (the redo panel, a menu not opened yet);
  not_found          it should be there and was not found;
  ambiguous          several equally good places: pointing at one would be a guess;
  unknown            there is not enough to tell (no add-on and the toolbar might be scrolled);
  words_only         nothing on screen names it (a gizmo handle, a key press): the words are the guidance.

Nothing here draws or decides what to show: `vision/verify.py` gates a result before a rectangle is used, and `app/step_state.py` turns results into the learner's next move.

Everything is pure over a `GroundContext` (what Blender reported, the captured frame and the words read from it), so it is tested with fixtures. Rectangles in the result are SCREEN pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.grounding import CaptureGeometry, Rect
from shared.step_record import TargetRef
from vision.locate import Located, find_phrase, locate
from vision.ocr import Word
from vision.toolbar_align import Alignment, align, cell_rect, full_cells, sep_flags
from vision.uimodel import FrameMapper, UiModel

# Blender spells some modes two ways: `context.mode` (what the add-on reports) and the `Object.mode` enum (what the mode dropdown lists).
CONTEXT_MODE_LABELS = {
    "OBJECT": "Object Mode", "POSE": "Pose Mode", "SCULPT": "Sculpt Mode", "PARTICLE": "Particle Edit", "PAINT_WEIGHT": "Weight Paint", "PAINT_VERTEX": "Vertex Paint", "PAINT_TEXTURE": "Texture Paint",
}
VISIBLE, OFFSCREEN, HIDDEN, WRONG, NOT_OPEN, NOT_FOUND, AMBIGUOUS, UNKNOWN, WORDS = ("visible", "offscreen", "container_hidden", "wrong_context", "not_open", "not_found", "ambiguous", "unknown", "words_only")


@dataclass(frozen=True)
class Grounded:
    kind: str                                  # the target kind this answers for
    state: str                                 # one of the states above
    rect: Rect | None = None                   # screen pixels: the control (visible) or the region to act in (offscreen, hidden, wrong_context, not_open)
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    note: str = ""                             # what to tell the learner about this state, in words
    direction: str | None = None               # offscreen: up | down (which way to scroll)
    matched: str = ""                          # menu paths: the part of the path that was found
    complete: bool = False                     # menu paths: the found part is the last one (the thing to click now)
    ambiguous: bool = False
    label: str = ""

    @property
    def located(self) -> bool:
        """Found on screen as the control itself (not a region hint)."""
        return self.state == VISIBLE and self.rect is not None


@dataclass
class GroundContext:
    """Everything a grounder may look at for ONE look at the screen."""
    ui: UiModel | None                         # what Blender reported (None without the add-on)
    mapper: FrameMapper | None                 # Blender window pixels -> screen and frame; None when the snapshot cannot be trusted for this frame
    geometry: CaptureGeometry | None           # captured frame -> screen
    pixels: Any                                # BGR frame
    words: list[Word] = field(default_factory=list)
    layout: Any = None                         # vision.regions.Layout (from the add-on when trusted, else guessed)
    mode: str | None = None                    # the mode Blender is in (probe) or the screen showed, else None
    changed: Rect | None = None                # frame area re-read at this look (a menu that just opened), if any
    epoch: Any = None                          # (interface revision, scene revision, window, words serial, settled): a result stays valid while it is unchanged
    settled: bool = True                       # the interface has not changed for a moment: Blender scrolls smoothly, so for about a second after a change the picture lags what the add-on reports
    maya: Any = None                           # Maya only: vision.mayaui.MayaUi built from the probe, when it describes the window as it is on screen now (then `ui` and `mapper` stay None)
    houdini: dict | None = None                # Houdini: the probe's interface snapshot (vision/probes/houdini_probe.py `ui`): panes, node tiles, the parameter pane's node and labels; screen pixels

    def screen_to_frame(self, r: Rect) -> Rect | None:
        """A screen rectangle in the captured frame's pixels (the inverse of `frame_to_screen` without a Blender mapper); None without a capture."""
        g = self.geometry
        if g is None:
            return None
        m = g.monitor
        sx, sy = g.image_w / m.w, g.image_h / m.h
        return Rect(round((r.x - m.x) * sx), round((r.y - m.y) * sy), round(r.w * sx), round(r.h * sy))

    def frame_to_screen(self, r: Rect) -> Rect:
        if self.mapper is not None:
            return self.mapper.frame_to_screen(r)
        g = self.geometry
        if g is None:
            return r
        m = g.monitor
        sx, sy = m.w / g.image_w, m.h / g.image_h
        return Rect(round(m.x + r.x * sx), round(m.y + r.y * sy), round(r.w * sx), round(r.h * sy))

    def window_to_screen(self, r: Rect) -> Rect | None:
        return None if self.mapper is None else self.mapper.to_screen(r)

    def window_to_frame(self, r: Rect) -> Rect | None:
        return None if self.mapper is None else self.mapper.to_frame(r)


def mode_label(mode: str | None) -> str:
    if not mode:
        return "the current mode"
    return "Edit Mode" if mode.startswith("EDIT_") else CONTEXT_MODE_LABELS.get(mode, mode.replace("_", " ").title())


# ---------------------------------------------------------------- toolbar
def _tool_entries(ctx: GroundContext, mode: str | None) -> list[bool] | None:
    """The toolbar in order as separator flags (True = separator): the add-on's live list, else the catalog's list for the mode."""
    if ctx.ui is not None and ctx.ui.tools:
        return [c.separator for c in ctx.ui.tools]
    if mode:
        from shared import shortcuts
        rows = shortcuts.catalog().get("tools", {}).get(mode)
        if rows:
            return ["separator" in r for r in rows]
    return None


def _cells_of(ctx: GroundContext, mode: str | None) -> list[list[str]]:
    if ctx.ui is not None and ctx.ui.tools:
        return ctx.ui.tool_cell_ids()
    if mode:
        from shared import shortcuts
        return [[t["id"] for t in r["group"]] for r in shortcuts.catalog().get("tools", {}).get(mode, []) if "group" in r]
    return []


def ground_tool(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A toolbar tool: is it in the toolbar of the mode Blender is in, is the toolbar shown, is the tool's cell on screen (and which cell is it, with the toolbar scrolled)?"""
    label = ref.label
    mode = ctx.mode or (ctx.ui.mode if ctx.ui else None)
    groups = _cells_of(ctx, mode)
    idx = next((i for i, g in enumerate(groups) if ref.id in g), None)
    if groups and idx is None:
        where = f"the toolbar of {mode_label(ref.mode)}" if ref.mode and ref.mode != mode else "another mode's toolbar"
        return Grounded("tool", WRONG, None, 1.0, (f"{ref.id} is not in the toolbar list of {mode or 'the current mode'}",), f"{label} is in {where}; {mode_label(mode)} does not have it. Switch mode first.", label=label)
    if idx is None:                                                  # no tool list at all (no add-on and the mode is not known): nothing to align with
        return Grounded("tool", UNKNOWN, None, 0.0, ("the toolbar's tools are not known",), f"Pick {label} in the toolbar (the tool strip at the left of the 3D view; scroll it if you cannot see it).", label=label)
    flags = sep_flags(_tool_entries(ctx, mode) or [])
    ui, mp = ctx.ui, ctx.mapper
    if ui is None or mp is None:
        return _tool_without_addon(ctx, ref, mode, groups, idx, flags)

    area = ui.area("VIEW_3D")
    tools = None if area is None else area.region("TOOLS")
    if area is None:
        return Grounded("tool", NOT_FOUND, None, 0.0, ("there is no 3D view in the window",), "There is no 3D view in this window.", label=label)
    if area.toolbar_shown is False or tools is None:
        edge = Rect(area.rect.x, area.rect.y, min(24, area.rect.w), area.rect.h)                        # the strip at the left edge where the toolbar sits (and where Blender shows a small arrow to bring it back)
        return Grounded("tool", HIDDEN, ctx.window_to_screen(edge), 1.0, ("the 3D view's toolbar region is hidden",),
                        f"The toolbar is hidden, so {label} cannot be reached. Show it (View > Toolbar, or the arrow at the left edge of the 3D view).", label=label)
    from vision.toolbar import find_cells
    viewport = ui.region("VIEW_3D", "WINDOW")
    if viewport is None:
        return Grounded("tool", UNKNOWN, None, 0.0, ("the 3D view has no drawing region in the snapshot",), f"Look for {label} in the toolbar.", label=label)
    tb = mp.to_frame(tools.rect)
    cells = [c for c in find_cells(ctx.pixels, mp.to_frame(viewport.rect)) if tb.x - 4 <= c.rect.x and c.rect.x + c.rect.w <= tb.x + tb.w + 4 and tb.y - 4 <= c.rect.y and c.rect.y + c.rect.h <= tb.y + tb.h + 4]
    if not ctx.settled:                                              # the toolbar (or the window) changed a moment ago and Blender animates it: cell positions in the picture are between two places
        return Grounded("tool", UNKNOWN, ctx.window_to_screen(tools.rect), 0.3, ("the interface changed a moment ago and Blender is still moving it",), f"Look for {label} in the toolbar (it will be pointed out as soon as the toolbar stops moving).", label=label)
    tops, heights = [c.rect.y - tb.y for c in cells], [c.rect.h for c in cells]
    scroll = 1.0 - (tools.view_top if tools.view_top is not None else 1.0)
    al = align(tops, heights, tb.h, flags, scroll, ui.ui_scale)
    return _tool_result(ctx, ref, idx, al, cells, tops, heights, flags, tb, tools.rect, groups, mode)


def _blue_cell_disagrees(ctx: GroundContext, al, cells, tops, heights, tb: Rect, groups) -> bool:
    """True when the cell Blender draws in blue (the active tool's) is visible and the alignment puts the active tool in another cell: then the alignment cannot be trusted."""
    active_tool = ctx.ui.active_tool if ctx.ui else None
    ai = None if not active_tool else next((i for i, g in enumerate(groups) if active_tool in g), None)
    if ai is None:
        return False
    kept = [k for k, (t, hh) in enumerate(zip(tops, heights, strict=True)) if t >= 1 and t + hh <= tb.h - 1]
    active_j = next((j for j, k in enumerate(kept) if cells[k].active), None)
    return active_j is not None and al.first + active_j != ai


def _tool_result(ctx: GroundContext, ref: TargetRef, idx: int, al: Alignment | None, cells, tops, heights, flags, tb: Rect, region_win: Rect, groups, mode) -> Grounded:
    label = ref.label
    region_screen = ctx.window_to_screen(region_win) if ctx.mapper is not None else None
    if al is None:
        return Grounded("tool", UNKNOWN, region_screen, 0.0, ("the cells in the picture do not match the tool list",), f"Look for {label} in the toolbar (the tool strip at the left of the 3D view); scroll it if you cannot see it.", label=label)
    rel = al.relation(idx)
    if _blue_cell_disagrees(ctx, al, cells, tops, heights, tb, groups):                # the alignment of a few visible cells can be one cell off (seen at Resolution Scale 1.5 with 4 cells in view): never say "scroll" or point at a cell when the blue one says otherwise
        return Grounded("tool", UNKNOWN, region_screen, 0.3, al.evidence + ("the blue (active) cell is NOT where the alignment puts the active tool",), f"Look for {label} in the toolbar.", label=label)
    if rel != VISIBLE:
        away = (al.first - idx) if rel == "above" else (idx - (al.first + al.count - 1))
        way = "up" if rel == "above" else "down"
        return Grounded("tool", OFFSCREEN, region_screen, al.confidence, al.evidence + (f"{label} is the toolbar's cell {idx + 1} of {len(groups)}; the visible cells are {al.first + 1} to {al.first + al.count}",),
                        f"{label} is {'above' if rel == 'above' else 'below'} the visible tools ({away} {'cell' if away == 1 else 'cells'} away): scroll the toolbar {way} until you see it.", direction=way, label=label)
    full = full_cells(tops, heights, tb.h)
    cr = cell_rect(idx, al, full, flags)
    if cr is None:
        return Grounded("tool", UNKNOWN, region_screen, 0.2, al.evidence, f"Look for {label} in the toolbar.", label=label)
    top, h = cr
    x = cells[0].rect.x if cells else tb.x + 4
    w = cells[0].rect.w if cells else tb.w - 8
    evidence = list(al.evidence)
    detected = 0 <= idx - al.first < len(full)
    evidence.append("a cell was detected in the picture at that place" if detected else "that cell was not detected in the picture; its place is computed from the cells around it")
    conf = al.confidence if detected else min(al.confidence, 0.7)
    # a second, independent check: the cell Blender draws in blue is the active tool's
    kept = [k for k, (t, hh) in enumerate(zip(tops, heights, strict=True)) if t >= 1 and t + hh <= tb.h - 1]       # the cells `align` used, as indexes into `cells`
    active_j = next((j for j, k in enumerate(kept) if cells[k].active), None)
    active_tool = ctx.ui.active_tool if ctx.ui else None
    ai = None if not active_tool else next((i for i, g in enumerate(groups) if active_tool in g), None)
    if ai is not None and active_j is not None:
        if al.first + active_j == ai:
            evidence.append("the blue (active) cell is the active tool's cell, as the alignment says")
            conf = min(1.0, conf + 0.03)
        else:
            return Grounded("tool", UNKNOWN, region_screen, 0.3, tuple(evidence) + ("the blue (active) cell is NOT where the alignment puts the active tool",), f"Look for {label} in the toolbar.", label=label)
    rect = ctx.frame_to_screen(Rect(round(x), round(tb.y + top), round(w), round(h)))
    return Grounded("tool", VISIBLE, rect, conf, tuple(evidence), f"Click {label} in the toolbar.", label=label)


def _tool_without_addon(ctx: GroundContext, ref: TargetRef, mode: str | None, groups, idx, flags) -> Grounded:
    """No add-on (or a snapshot that does not fit this frame): the toolbar can be located only when it is certain nothing is scrolled off, i.e. every tool of the mode is visible."""
    label = ref.label
    words = f"Pick {label} in the toolbar (the tool strip at the left of the 3D view; scroll it if you cannot see it)."
    layout = ctx.layout
    viewport = None if layout is None else layout.get("viewport")
    if not groups or idx is None or viewport is None:
        return Grounded("tool", UNKNOWN, None, 0.0, ("no add-on: the toolbar cannot be read",), words, label=label)
    from vision.toolbar import find_cells
    cells = find_cells(ctx.pixels, viewport)
    if len(cells) != len(groups):
        return Grounded("tool", UNKNOWN, None, 0.0, (f"{len(cells)} cells are visible but the mode has {len(groups)} tools: the toolbar may be scrolled, and without the add-on there is no way to tell",), words, label=label)
    c = cells[idx].rect
    return Grounded("tool", VISIBLE, ctx.frame_to_screen(c), 0.8, (f"all {len(groups)} tools of the mode are visible, so the toolbar is not scrolled",), f"Click {label} in the toolbar.", label=label)


# ---------------------------------------------------------------- text controls
def _header_rects(ctx: GroundContext) -> list[Rect]:
    """Frame rectangles where a root menu of a tutorial path can be: the 3D view's header, then the top bar. Empty without the add-on's layout."""
    out: list[Rect] = []
    ui, mp = ctx.ui, ctx.mapper
    if ui is not None and mp is not None:
        for kind in ("HEADER", "TOOL_HEADER"):
            r = ui.region("VIEW_3D", kind)
            if r is not None:
                out.append(mp.to_frame(r.rect))
    if ctx.layout is not None:
        top = ctx.layout.get("topbar")
        if top is not None:
            out.append(top)
    return out


def hint_for(target: str | None, matched: str, complete: bool = False) -> str:
    """Words for the next click on a menu path from the part of it that was found: "Click Add, then Mesh > Cylinder"; "Open: Add > Mesh > Cylinder" when nothing of the path is visible yet."""
    parts = [p.strip() for p in (target or "").split(">") if p.strip()]
    if not parts:
        return ""
    low = [p.lower() for p in parts]
    i = max((n for n, p in enumerate(low) if p == (matched or "").strip().lower()), default=None)
    if i is None:
        return "Open: " + " > ".join(parts)
    rest = parts[i + 1:]
    return f"Click {parts[i]}" if complete or not rest else f"Click {parts[i]}, then " + " > ".join(rest)


def _from_located(kind: str, found: Located, ctx: GroundContext, region: str, path: str = "") -> Grounded:
    rect = ctx.frame_to_screen(found.rect)
    if found.alternatives > 0:
        return Grounded(kind, AMBIGUOUS, None, found.score * 0.5, (f"{found.alternatives + 1} equally good places match '{found.matched}'",), "Several places on the screen match; open the menu and it will narrow down.",
                        matched=found.matched, ambiguous=True)
    return Grounded(kind, VISIBLE, rect, round(found.score * (1.0 if region else 0.85), 2), (f"the text '{found.matched}' was read{(' inside ' + region) if region else ''}",),
                    hint_for(path, found.matched, found.complete), matched=found.matched, complete=found.complete)


def ground_menu(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A menu path ("Add > Mesh > Cylinder"). The FIRST part is searched only where menu bars are (the 3D view's header and the top bar), so the 'Add Cylinder' panel at the bottom of the view is never
    mistaken for the Add menu; the following parts are found where they open, beside the part before."""
    path = " > ".join(ref.path or [ref.label])
    for region in _header_rects(ctx):
        found = locate(ctx.words, path, within=region, below_first=True)
        if found is not None:
            return _from_located("menu", found, ctx, "a header", path)
    if not _header_rects(ctx):                                        # no layout at all: anywhere (the old behaviour)
        found = locate(ctx.words, path)
        if found is not None:
            return _from_located("menu", found, ctx, "", path)
    return Grounded("menu", NOT_FOUND, None, 0.0, ("the first part of the path is not in any header",), "Open: " + " > ".join(ref.path or [ref.label]), label=ref.label)


def ground_mode(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """The mode dropdown (found by the name of the mode Blender is in now, inside the 3D view's header), or its item once the dropdown is open."""
    target = (ref.label or "").strip()
    now = mode_label(ctx.mode or (ctx.ui.mode if ctx.ui else None))
    item = [(r, s) for r, s in find_phrase(ctx.words, target, None, min_score=0.9)]
    heads = _header_rects(ctx)[:1]
    drop = [(r, s) for r, s in find_phrase(ctx.words, now, heads[0] if heads else None, min_score=0.9)]
    if item and drop:
        below = [(r, s) for r, s in item if r.y > drop[0][0].y + 2 and abs(r.x - drop[0][0].x) < 400]          # the list opens below the dropdown
        if below:
            r, s = below[0]
            return Grounded("mode", VISIBLE, ctx.frame_to_screen(r), round(s, 2), (f"'{target}' was read in the list that opened below the mode dropdown",), f"Click {target}.", matched=target, complete=True, label=target)
    if drop:
        r, s = drop[0]
        return Grounded("mode", VISIBLE, ctx.frame_to_screen(r), round(s * 0.95, 2), (f"the dropdown was found by the mode it shows now ('{now}')",), f"Click the mode dropdown (top left of the 3D view), then {target}.", matched=now, complete=False, label=target)
    return Grounded("mode", NOT_FOUND, None, 0.0, (f"'{now}' was not read in the 3D view's header",), f"Open the mode dropdown at the top left of the 3D view and choose {target}.", label=target)


def _tab_icon(ctx: GroundContext, nav, tabs: tuple[str, ...] | list[str], tab: str) -> tuple[Rect | None, str]:
    """The screen rectangle of one tab's icon in the Properties editor's tab column, with the evidence (or the reason it could not be found)."""
    if nav is None or ctx.pixels is None or not tabs:
        return None, "the tab column was not available"
    box = ctx.window_to_frame(nav.rect)
    if box is None:
        return None, "the snapshot does not fit this frame"
    from vision.tabs import tab_cell
    cell, why = tab_cell(ctx.pixels, box, list(tabs), tab)
    return (None if cell is None else ctx.frame_to_screen(cell)), why


def ground_property(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A Properties editor field: the right tab open? then its panel's header, then the field's label under it. The tab icons are not located (the add-on lists the tabs but not where they are drawn): the highlight is
    the column that holds them, with the words saying which tab."""
    ui = ctx.ui
    area = None if ui is None else ui.area("PROPERTIES")
    tab_name = (ref.tab or "").replace("_", " ").title()
    if ui is None or area is None or ctx.mapper is None:
        return Grounded("property", UNKNOWN, None, 0.0, ("no add-on or no Properties editor in the snapshot",), f"In the Properties editor (right side) open the {tab_name} tab, then {' > '.join(ref.path[1:]) if ref.path else ref.label}.", label=ref.label)
    nav = area.region("NAVIGATION_BAR")
    nav_screen = ctx.window_to_screen(nav.rect) if nav is not None else None
    if area.tabs and ref.tab and ref.tab not in area.tabs:
        return Grounded("property", WRONG, nav_screen, 1.0, (f"the {tab_name} tab is not among the tabs available now: {', '.join(area.tabs)}",),
                        f"The {tab_name} tab is not available for what is selected. Select the object it belongs to first.", label=ref.label)
    if ref.tab and area.context != ref.tab:
        icon, why = _tab_icon(ctx, nav, area.tabs, ref.tab)
        if icon is not None:                                           # the tab's own icon, found from the pixels and the order of the tabs
            return Grounded("property", WRONG, icon, 0.85, (f"the open tab is {area.context}, the step needs {ref.tab}", why),
                            f"Click the {tab_name} tab: the highlighted icon in the column at the left of the Properties editor.", label=ref.label, matched=tab_name)
        return Grounded("property", WRONG, nav_screen, 1.0, (f"the open tab is {area.context}, the step needs {ref.tab}", why),
                        f"Open the {tab_name} tab: it is one of the icons in the column at the left of the Properties editor (hover an icon to read its name).", label=ref.label)
    win = area.region("WINDOW")
    if win is None:
        return Grounded("property", NOT_FOUND, nav_screen, 0.0, ("the Properties editor has no content region",), "", label=ref.label)
    box = ctx.window_to_frame(win.rect)
    if box is None:
        return Grounded("property", UNKNOWN, None, 0.0, ("the snapshot does not fit this frame",), f"Look for {ref.prop} in the {tab_name} tab.", label=ref.label)
    panel = find_phrase(ctx.words, ref.panel, box, min_score=0.9) if ref.panel else []
    win_screen = ctx.window_to_screen(win.rect)
    if ref.panel and not panel:
        lone = _lone_field(ctx, ref, box, f"the {tab_name} tab")
        if lone is not None:
            return lone
        return Grounded("property", OFFSCREEN, win_screen, 0.6, (f"the panel '{ref.panel}' was not read in the {tab_name} tab",), f"Scroll the Properties editor to find the {ref.panel} panel.", label=ref.label)
    below = Rect(box.x, panel[0][0].y if panel else box.y, box.w, box.h - ((panel[0][0].y - box.y) if panel else 0))
    field_hit = [(r, s) for r, s in find_phrase(ctx.words, ref.prop or ref.label, below, min_score=0.9) if not panel or r.y > panel[0][0].y]
    if field_hit:
        r, s = field_hit[0]
        ev = (f"the panel header '{ref.panel}' and the label '{ref.prop}' beneath it were both read",) if panel else (f"the label '{ref.prop}' was read in the {tab_name} tab",)
        return Grounded("property", VISIBLE, ctx.frame_to_screen(widget_rect(ctx.words, r, box)), round(min(s, 0.95 if panel else 0.8), 2), ev, f"Find {ref.prop} in the {ref.panel or tab_name} panel.", complete=True, label=ref.label)
    if panel:
        header = panel[0][0]
        if _panel_open(ctx, header, box, ref.tab):                     # open, and the field is under the part that is in view: it needs a scroll, not a click on the header
            strip = ctx.window_to_screen(Rect(win.rect.x, win.rect.y, win.rect.w, 36))          # Blender's region rectangles count from the bottom: this is the bottom edge of the editor
            return Grounded("property", OFFSCREEN, strip, 0.6, (f"the panel '{ref.panel}' is open and '{ref.prop}' is not in the part that is in view",),
                            f"{ref.panel} is open. Scroll down in the Properties editor to {ref.prop}.", label=ref.label, direction="down")
        return Grounded("property", OFFSCREEN, ctx.frame_to_screen(header), 0.6, (f"the header '{ref.panel}' is shown and the panel under it is closed",),
                        f"Click {ref.panel} to open it; {ref.prop} is inside.", label=ref.label, matched=ref.panel or "")
    return Grounded("property", UNKNOWN, win_screen, 0.3, ("the tab is open; its content was not read",), f"Look for {ref.prop} in the {tab_name} tab.", label=ref.label)


def _lone_field(ctx: GroundContext, ref: TargetRef, box: Rect, where: str, kind: str = "property") -> Grounded | None:
    """The field's label when its panel header could not be read. Some panels are not headed by a fixed word: a constraint or a modifier is headed by its NAME, which the learner may have changed, and the
    OCR reads a header with a field in it unreliably. The label itself is enough when it appears ONCE in the editor (a second place would make pointing at one a guess: nothing is pointed at then). The
    confidence is lower than with the header, and the evidence says so."""
    label = ref.prop or ref.label
    hits = find_phrase(ctx.words, label, box, min_score=0.9)
    if len(hits) == 1:
        r, s = hits[0]
        return Grounded(kind, VISIBLE, ctx.frame_to_screen(widget_rect(ctx.words, r, box)), round(min(s, 0.8), 2),
                        (f"the label '{label}' was read once in {where}; the header of '{ref.panel}' was not read, so only the label is evidence",), f"Find {label} in the {ref.panel} panel.", complete=True, label=ref.label)
    if len(hits) > 1:
        return Grounded(kind, AMBIGUOUS, None, 0.3, (f"'{label}' appears {len(hits)} times in {where} and the header of '{ref.panel}' was not read",), f"Find {label} in the {ref.panel} panel (it appears in more than one place).", ambiguous=True, label=ref.label)
    return None


def _panel_open(ctx: GroundContext, header: Rect, box: Rect, tab: str | None) -> bool:
    """Whether the panel whose header is at `header` is open. A closed panel is followed at once by the next panel's header; an open one by its own content. The headers that can follow are the panels of the
    same tab in the application's own catalog, so nothing is guessed from the word shapes. With nothing readable under it, it is taken as closed (the safe thing to tell the learner is to click it)."""
    below = [w for w in ctx.words if w.rect.y > header.y + header.h and box.contains(w.rect.x, w.rect.y) and any(c.isalpha() for c in w.text)]          # the arrow of a closed panel is read as a word of its own: not text
    if not below:
        return False
    first_line = min(below, key=lambda w: (w.rect.y, w.rect.x)).line
    text = " ".join(w.text for w in sorted((w for w in below if w.line == first_line), key=lambda w: w.rect.x))
    try:
        from ingestion.targets import _n, load_catalog
        cat = load_catalog()
    except Exception:
        cat = None
    if cat is None or not tab:
        return True
    labels = {label for (context, label) in cat.panels if context == tab.lower()}
    return _n(text) not in labels


def widget_rect(words: list[Word], label: Rect, region: Rect, reach: int = 190) -> Rect:
    """A Properties field is its label AND its widget: a checkbox is drawn at the LEFT of its label (the tick in front of "In Front"), a value box at the right ("Display As [Octahedral]"). The label's rectangle
    grown to cover the checkbox on its left and the value on its right, inside `region`."""
    r = field_rect(words, label, reach)
    left = max(region.x, label.x - 22)                                   # the box of a checkbox, about as wide as the row is high plus its gap
    x = min(r.x, left) if not any(w.rect.x + w.rect.w <= label.x and label.x - (w.rect.x + w.rect.w) <= 22 and abs(w.rect.y - label.y) <= label.h for w in words) else r.x
    return Rect(x, r.y, r.x + r.w - x, r.h)


def ground_sidebar(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A field of the 3D view's sidebar (the N panel): is the sidebar shown, is the right panel in it, is the field's label under that panel? The sidebar's tabs (Item, Tool, View) are drawn along its right
    edge and are not located: the words say which one. Without the add-on the sidebar's place is not known: the panel header and the label are looked for on the whole screen and believed only when they
    agree (a header with the label under it) and the label is read once."""
    label = ref.prop or ref.label
    tab = (ref.tab or "").title()
    way = f"Open the sidebar (press N with the mouse over the 3D view){', its ' + tab + ' tab' if tab else ''}"
    path = f"{ref.panel + ' > ' if ref.panel else ''}{label}"
    ui = ctx.ui
    area = None if ui is None else ui.area("VIEW_3D")
    known = False
    region_screen = None
    if ui is not None and area is not None and ctx.mapper is not None:
        known = True
        shown = area.region("UI")
        if area.sidebar_shown is False or shown is None:
            edge = Rect(area.rect.x + max(0, area.rect.w - 24), area.rect.y, min(24, area.rect.w), area.rect.h)          # the right edge of the 3D view, where Blender shows a small arrow to bring the sidebar back
            return Grounded("sidebar", HIDDEN, ctx.window_to_screen(edge), 1.0, ("the 3D view's sidebar region is hidden",), f"{way}, then {path}. (View > Sidebar also opens it.)", label=ref.label)
        box = ctx.window_to_frame(shown.rect)
        if box is None:
            return Grounded("sidebar", UNKNOWN, None, 0.0, ("the snapshot does not fit this frame",), f"{way}, then {path}.", label=ref.label)
        region_screen, where = ctx.window_to_screen(shown.rect), "the sidebar"
    else:
        box, where = Rect(0, 0, 100000, 100000), "the window"
    panel = find_phrase(ctx.words, ref.panel, box, min_score=0.9) if ref.panel else []
    if ref.panel and not panel:
        lone = _lone_field(ctx, ref, box, where, "sidebar") if known else None
        if lone is not None:
            return lone
        if not known:
            return Grounded("sidebar", UNKNOWN, None, 0.0, ("no add-on: the sidebar cannot be read",), f"{way}, then {path}.", label=ref.label)
        return Grounded("sidebar", OFFSCREEN, region_screen, 0.6, (f"the panel '{ref.panel}' was not read in the sidebar",),
                        f"Look in the sidebar{' (' + tab + ' tab)' if tab else ''} for the {ref.panel} panel, scrolling it if needed, then {label}.", label=ref.label)
    below = Rect(box.x, panel[0][0].y, box.w, box.y + box.h - panel[0][0].y) if panel else box
    hits = [(r, s) for r, s in find_phrase(ctx.words, label, below, min_score=0.9) if not panel or r.y > panel[0][0].y]
    if hits and (known or len(hits) == 1):
        r, s = hits[0]
        ev = (f"the panel header '{ref.panel}' and the label '{label}' beneath it were both read in {where}",) if panel else (f"the label '{label}' was read in {where}",)
        conf = min(s, 0.95 if panel else 0.8) * (1.0 if known else 0.9)
        return Grounded("sidebar", VISIBLE, ctx.frame_to_screen(widget_rect(ctx.words, r, box)), round(conf, 2), ev, f"Find {label}{' in the ' + ref.panel + ' panel' if ref.panel else ''} in the sidebar.", complete=True, label=ref.label)
    if hits:
        return Grounded("sidebar", AMBIGUOUS, None, 0.3, (f"'{label}' appears {len(hits)} times on screen",), "", ambiguous=True, label=ref.label)
    if panel:
        return Grounded("sidebar", OFFSCREEN, ctx.frame_to_screen(panel[0][0]), 0.6, (f"the header '{ref.panel}' is shown and '{label}' is not under it",),
                        f"Click {ref.panel} to open it, or scroll the sidebar: {label} is inside.", label=ref.label, matched=ref.panel or "")
    return Grounded("sidebar", UNKNOWN, region_screen, 0.3, ("the sidebar is open; the label was not read in it",), f"Look for {label} in the sidebar{' (' + tab + ' tab)' if tab else ''}.", label=ref.label)


def ground_operator_panel(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A field of the panel an operator leaves after it ran (Loop Cut and Slide > Number of Cuts), or a choice in the popup an operator shows (Set Parent To > With Automatic Weights)."""
    if ref.id:                                                         # a choice in a popup: text, wherever the popup opened
        hits = find_phrase(ctx.words, ref.label, None, min_score=0.9)
        if len(hits) == 1:
            return Grounded("operator_panel", VISIBLE, ctx.frame_to_screen(hits[0][0]), round(hits[0][1], 2), (f"the choice '{ref.label}' was read",), f"Click {ref.label}.", complete=True, label=ref.label)
        if len(hits) > 1:
            return Grounded("operator_panel", AMBIGUOUS, None, 0.3, (f"'{ref.label}' appears {len(hits)} times",), "", ambiguous=True, label=ref.label)
        return Grounded("operator_panel", NOT_OPEN, None, 0.0, ("the popup is not open",), f"The choices appear after the shortcut or menu item that started them; then click {ref.label}.", label=ref.label)
    # A tool's or an operator's field is shown in one of two places, and which one depends on the Blender version and on what ran: the TOOL SETTINGS bar along the top of the 3D view (Loop Cut's
    # "Number of Cuts" sits there while the tool is active) or the REDO PANEL at the bottom left (after an operator ran). The label is looked for in both, so the highlight goes to where it really is.
    places = _field_places(ctx)
    for where, box in places:
        hits = find_phrase(ctx.words, ref.label, box, min_score=0.9)
        if hits:
            rect = field_rect(ctx.words, hits[0][0])
            return Grounded("operator_panel", VISIBLE, ctx.frame_to_screen(rect), round(hits[0][1], 2), (f"'{ref.label}' was read in the {where}",), f"Set {ref.label} in the {where}.", complete=True, label=ref.label)
    if not places:
        hits = find_phrase(ctx.words, ref.label, None, min_score=0.9)                                  # no add-on: the label is searched on the whole screen, and only a single match is believed
        if len(hits) == 1:
            return Grounded("operator_panel", VISIBLE, ctx.frame_to_screen(field_rect(ctx.words, hits[0][0])), round(hits[0][1] * 0.85, 2), (f"'{ref.label}' was read once on screen",), f"Set {ref.label}.", complete=True, label=ref.label)
        return Grounded("operator_panel", NOT_OPEN, None, 0.0, ("no settings panel is open",), f"Do the action first: Blender then shows its settings for it, along the top of the 3D view or in a panel at the bottom left, where you set {ref.label}.", label=ref.label)
    where, box = places[0]
    area = None if ctx.ui is None else ctx.ui.area("VIEW_3D")
    reported = _hud_window_rect(ctx) or (None if area is None else area.rect)
    return Grounded("operator_panel", VISIBLE, None if reported is None else ctx.window_to_screen(reported), 0.75, (f"Blender reports the {where}; the label '{ref.label}' was not read in it",),
                    f"Set {ref.label} in the {where} (click its header if it is collapsed).", label=ref.label)


def _hud_window_rect(ctx: GroundContext):
    area = None if ctx.ui is None else ctx.ui.area("VIEW_3D")
    hud = None if area is None else area.region("HUD")
    return None if hud is None else hud.rect


def _field_places(ctx: GroundContext) -> list[tuple[str, Rect]]:
    """Where a tool's or operator's fields can be right now, in frame pixels: the settings panel at the bottom left (when Blender reports it open) and the tool settings bar at the top of the 3D view."""
    out: list[tuple[str, Rect]] = []
    ui, mp = ctx.ui, ctx.mapper
    if ui is None or mp is None:
        return out
    hud = _hud_window_rect(ctx)
    if hud is not None:
        box = ctx.window_to_frame(hud)
        if box is not None:
            out.append(("panel at the bottom left of the 3D view", box))
    th = ui.region("VIEW_3D", "TOOL_HEADER")
    if th is not None:
        box = ctx.window_to_frame(th.rect)
        if box is not None:
            out.append(("tool settings bar at the top of the 3D view", box))
    return out


def field_rect(words: list[Word], label: Rect, reach: int = 190) -> Rect:
    """A field is its label AND its value box ("Number of Cuts" and the 1 beside it): the label's rectangle grown over the words that follow it on the same line within `reach` pixels, so the highlight
    surrounds the whole field and not just the first words of it."""
    right = label.x + label.w
    row = [w for w in words if abs((w.rect.y + w.rect.h // 2) - (label.y + label.h // 2)) <= max(label.h // 2, 4) and w.rect.x >= right - 2]
    row.sort(key=lambda w: w.rect.x)
    out = label
    for w in row[:2]:
        if w.rect.x - (out.x + out.w) > reach // 2 or w.rect.x + w.rect.w - label.x > reach + label.w:
            break
        out = Rect(label.x, min(out.y, w.rect.y), w.rect.x + w.rect.w - label.x, max(out.y + out.h, w.rect.y + w.rect.h) - min(out.y, w.rect.y))
    return out


def ground_context_menu(ctx: GroundContext, ref: TargetRef) -> Grounded:
    hits = find_phrase(ctx.words, ref.label, None, min_score=0.9)
    if len(hits) == 1:
        return Grounded("context_menu", VISIBLE, ctx.frame_to_screen(hits[0][0]), round(hits[0][1], 2), (f"'{ref.label}' was read once on screen",), f"Click {ref.label}.", complete=True, label=ref.label)
    if len(hits) > 1:
        return Grounded("context_menu", AMBIGUOUS, None, 0.3, (f"'{ref.label}' appears {len(hits)} times",), "", ambiguous=True, label=ref.label)
    return Grounded("context_menu", NOT_OPEN, None, 0.0, ("the context menu is not open",), f"Right-click in the 3D view, then choose {ref.label}.", label=ref.label)


def ground_maya(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A target in Maya: a menu opened on screen is read from its text (the most specific answer); the tool box, shelf buttons and the menu bar are exact, from Maya's own widgets (`ctx.maya`)."""
    path = " > ".join(ref.path or [ref.label])
    found = locate(ctx.words, path)
    if found is not None and found.depth >= 1:                                           # a menu is open and its item was read from the screen
        return _from_located("menu", found, ctx, "", path)
    hit = ctx.maya.find(path if ref.kind == "menu" else (ref.label or path))
    if hit is None and ref.kind == "tool" and ref.id:
        hit = ctx.maya.find(ref.id)
    if hit is None:
        if found is not None:
            return _from_located("menu", found, ctx, "", path)
        return Grounded(ref.kind, NOT_FOUND, None, 0.0, ("Maya does not list that control",), "Open: " + path, label=ref.label)
    w = ctx.maya.window
    if not (w.x <= hit.rect.x and w.y <= hit.rect.y and hit.rect.x + hit.rect.w <= w.x + w.w and hit.rect.y + hit.rect.h <= w.y + w.h):
        return Grounded(ref.kind, HIDDEN, None, 0.6, ("that part of Maya is outside its window",), "That part of Maya is not visible.", label=ref.label)
    return Grounded(ref.kind, VISIBLE, hit.rect, 0.95, (f"Maya reports the {hit.kind} '{hit.name}' here",), hint_for(path, hit.name, hit.complete), matched=hit.name, complete=hit.complete, label=ref.label)


def ground_target(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """The grounder for this kind of target. Keys and viewport items have nothing on screen to find: the answer is `words_only`."""
    if ctx.maya is not None and ref.kind in ("tool", "menu", "mode", "property"):
        return ground_maya(ctx, ref)
    if ref.kind == "tool":
        return ground_tool(ctx, ref)
    if ref.kind == "menu":
        return ground_menu(ctx, ref)
    if ref.kind == "mode":
        return ground_mode(ctx, ref)
    if ref.kind == "property":
        return ground_property(ctx, ref)
    if ref.kind == "sidebar":
        return ground_sidebar(ctx, ref)
    if ref.kind == "operator_panel":
        return ground_operator_panel(ctx, ref)
    if ref.kind == "context_menu":
        return ground_context_menu(ctx, ref)
    if ref.kind == "node":
        return ground_houdini_node(ctx, ref)
    if ref.kind == "parm":
        return ground_houdini_parm(ctx, ref)
    if ref.kind == "pane":
        return ground_houdini_pane(ctx, ref)
    return Grounded(ref.kind, WORDS, None, 1.0, ("nothing on screen names it",), label=ref.label)


# ---------------------------------------------------------------- Houdini (docs/houdini_grounding.md)
# Houdini reports where its nodes and panes are (the probe's `ui` snapshot, checked against a capture of a real Houdini 22 window). Parameter fields are drawn by Houdini itself, so a parameter is
# found by reading the words INSIDE the parameter pane and matching them against the labels Houdini says that pane's node has: a closed list, never free text.
HOUDINI_PANE_WORDS = {"NetworkEditor": "the network editor", "SceneViewer": "the viewport", "Parm": "the parameter pane"}


def _hkey(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _hrect(r) -> Rect:
    return Rect(int(r[0]), int(r[1]), int(r[2]), int(r[3]))


def _same_node_label(a: str, b: str) -> bool:
    return bool(a and b) and _hkey(a).removeprefix("apex") == _hkey(b).removeprefix("apex")


def _houdini_nodes(ctx: GroundContext, ref: TargetRef) -> list[dict]:
    """The visible nodes the target means: by instance name when the step names one, else by type (label or type name)."""
    nodes = ((ctx.houdini or {}).get("network") or {}).get("nodes") or []
    if ref.path:
        return [n for n in nodes if n.get("name") == ref.path[0]]
    return [n for n in nodes if _same_node_label(n.get("label", ""), ref.label) or (ref.id and _hkey(n.get("type", "")) == _hkey(ref.id))]


def ground_houdini_node(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A node in the network editor: its tile as the probe reports it. One match is the node; several of the same type pick the selected one, else the answer is ambiguous (no box); none means it is not
    in the part of the network that is shown."""
    hou = ctx.houdini
    if not hou or not hou.get("network"):
        return Grounded("node", UNKNOWN, None, 0.0, ("the Houdini probe reports no network editor",), f"Find {ref.label} in the network editor.", label=ref.label)
    hits = _houdini_nodes(ctx, ref)
    if len(hits) > 1:
        sel = [n for n in hits if n.get("selected")]
        hits = sel if len(sel) == 1 else hits
    path = hou["network"].get("path", "")
    if len(hits) == 1:
        n = hits[0]
        return Grounded("node", VISIBLE, _hrect(n["rect"]), 0.95, ("the Houdini probe reports the node's tile", f"the node {n['name']} is in {path}"),
                        f"This is {n['name']} ({n.get('label') or ref.label}).", label=n["name"], complete=True)
    if len(hits) > 1:
        return Grounded("node", AMBIGUOUS, None, 0.5, (f"{len(hits)} nodes of this type are in view",), f"There are {len(hits)} {ref.label} nodes here: pick the one the step means.",
                        ambiguous=True, label=ref.label)
    net_rect = hou["network"].get("rect")
    return Grounded("node", NOT_FOUND, _hrect(net_rect) if net_rect else None, 0.6, (f"no {ref.label} node is in view in {path}",),
                    f"{ref.label} is not in the part of {path} that is shown: create it, or pan the network editor to it.", label=ref.label)


def ground_houdini_pane(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """The pane a key or an action belongs in (Tab in the network editor, F in the viewport): a region hint, with the key in words."""
    hou = ctx.houdini or {}
    keys = "+".join(ref.keys)
    where = HOUDINI_PANE_WORDS.get(ref.id or "", ref.label)
    rect = next((p.get("rect") for p in hou.get("panes", []) if p.get("type") == ref.id and p.get("rect")), None)
    note = f"Press {keys} with the mouse over {where}." if keys else f"Work in {where}."
    if rect is None:
        return Grounded("pane", WORDS, None, 1.0, (f"the Houdini probe reports no {ref.id} pane on screen",), note, label=ref.label)
    return Grounded("pane", HIDDEN, _hrect(rect), 0.9, ("the Houdini probe reports the pane's rectangle",), note, label=ref.label)


def ground_houdini_parm(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A parameter: the parameter pane must show the step's node (else point at that node first); the label must be one Houdini lists for it; then the label is found by the words read inside the pane.
    The box covers the parameter's row (label to the pane's right edge). Two places with the label: ambiguous, no box."""
    hou = ctx.houdini or {}
    parm = hou.get("parm")
    label = ref.prop or ref.label
    if not parm:
        return Grounded("parm", UNKNOWN, None, 0.0, ("the Houdini probe reports no parameter pane",), f"Find {label} in the parameter pane.", label=label)
    node_label = ref.panel or ""
    if node_label and not _same_node_label(node_label, parm.get("label", "")):
        node = ground_houdini_node(ctx, TargetRef(kind="node", label=node_label, id=ref.id))
        return Grounded("parm", WRONG, node.rect if node.located else None, 0.85, (f"the parameter pane shows {parm.get('node')}, the step needs a {node_label}",),
                        f"Select the {node_label} node first: its parameters, {label} among them, then show in the parameter pane.", label=label)
    labels = parm.get("labels") or []
    exact = next((x for x in labels if _hkey(x) == _hkey(label)), None)
    if exact is None:
        return Grounded("parm", WORDS, None, 1.0, (f"{parm.get('label')} has no parameter labelled {label} in this Houdini",), f"Look for {label} in the parameter pane.", label=label)
    pane = parm.get("rect")
    if not pane:
        return Grounded("parm", UNKNOWN, None, 0.3, ("the parameter pane's rectangle is not known",), f"Find {exact} in the parameter pane.", label=exact)
    pane_r = _hrect(pane)
    within = ctx.screen_to_frame(pane_r)
    hits = find_phrase(ctx.words, exact, within, min_score=0.85) if within is not None else []
    if len(hits) == 1:
        r, score = hits[0]
        s = ctx.frame_to_screen(r)
        row = Rect(s.x, s.y - 2, max(s.w, pane_r.x + pane_r.w - s.x - 4), s.h + 4)
        return Grounded("parm", VISIBLE, row, round(min(0.95, score), 2), (f"the parameter pane shows {parm.get('node')}", f"the label '{exact}' was read in it"),
                        f"Set {exact} here.", label=exact, complete=True)
    if len(hits) > 1:
        return Grounded("parm", AMBIGUOUS, None, 0.5, (f"'{exact}' was read {len(hits)} times in the pane",), f"Find {exact} in the parameter pane.", label=exact, ambiguous=True)
    return Grounded("parm", NOT_OPEN, pane_r, 0.6, (f"{exact} is a parameter of {parm.get('label')} but its label was not read in the pane",),
                    f"{exact} is in the parameter pane: scroll it or open the folder that holds it.", label=exact)
