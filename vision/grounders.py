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


def _tool_result(ctx: GroundContext, ref: TargetRef, idx: int, al: Alignment | None, cells, tops, heights, flags, tb: Rect, region_win: Rect, groups, mode) -> Grounded:
    label = ref.label
    region_screen = ctx.window_to_screen(region_win) if ctx.mapper is not None else None
    if al is None:
        return Grounded("tool", UNKNOWN, region_screen, 0.0, ("the cells in the picture do not match the tool list",), f"Look for {label} in the toolbar (the tool strip at the left of the 3D view); scroll it if you cannot see it.", label=label)
    rel = al.relation(idx)
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
        return Grounded("property", WRONG, nav_screen, 1.0, (f"the open tab is {area.context}, the step needs {ref.tab}",),
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
        return Grounded("property", OFFSCREEN, win_screen, 0.6, (f"the panel '{ref.panel}' was not read in the {tab_name} tab",), f"Scroll the Properties editor to find the {ref.panel} panel.", label=ref.label)
    below = Rect(box.x, panel[0][0].y if panel else box.y, box.w, box.h - ((panel[0][0].y - box.y) if panel else 0))
    field_hit = [(r, s) for r, s in find_phrase(ctx.words, ref.prop or ref.label, below, min_score=0.9) if not panel or r.y > panel[0][0].y]
    if field_hit:
        r, s = field_hit[0]
        ev = (f"the panel header '{ref.panel}' and the label '{ref.prop}' beneath it were both read",) if panel else (f"the label '{ref.prop}' was read in the {tab_name} tab",)
        return Grounded("property", VISIBLE, ctx.frame_to_screen(r), round(min(s, 0.95 if panel else 0.8), 2), ev, f"Find {ref.prop} in the {ref.panel or tab_name} panel.", complete=True, label=ref.label)
    if panel:
        return Grounded("property", OFFSCREEN, ctx.frame_to_screen(panel[0][0]), 0.6, (f"the header '{ref.panel}' is shown but '{ref.prop}' is not under it",),
                        f"Open the {ref.panel} panel (click its header; it may be collapsed) and scroll to {ref.prop}.", label=ref.label)
    return Grounded("property", UNKNOWN, win_screen, 0.3, ("the tab is open; its content was not read",), f"Look for {ref.prop} in the {tab_name} tab.", label=ref.label)


def ground_operator_panel(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """A field of the panel an operator leaves after it ran (Loop Cut and Slide > Number of Cuts), or a choice in the popup an operator shows (Set Parent To > With Automatic Weights)."""
    ui = ctx.ui
    if ref.id:                                                         # a choice in a popup: text, wherever the popup opened
        hits = find_phrase(ctx.words, ref.label, None, min_score=0.9)
        if len(hits) == 1:
            return Grounded("operator_panel", VISIBLE, ctx.frame_to_screen(hits[0][0]), round(hits[0][1], 2), (f"the choice '{ref.label}' was read",), f"Click {ref.label}.", complete=True, label=ref.label)
        if len(hits) > 1:
            return Grounded("operator_panel", AMBIGUOUS, None, 0.3, (f"'{ref.label}' appears {len(hits)} times",), "", ambiguous=True, label=ref.label)
        return Grounded("operator_panel", NOT_OPEN, None, 0.0, ("the popup is not open",), f"The choices appear after the shortcut or menu item that started them; then click {ref.label}.", label=ref.label)
    area = None if ui is None else ui.area("VIEW_3D")
    hud = None if area is None else area.region("HUD")
    if area is None or hud is None or ctx.mapper is None:
        return Grounded("operator_panel", NOT_OPEN, None, 0.0, ("no redo panel is open",), f"Do the action first: Blender then shows its settings panel at the bottom left of the 3D view, where you set {ref.label}.", label=ref.label)
    box = ctx.window_to_frame(hud.rect)
    hits = find_phrase(ctx.words, ref.label, box, min_score=0.9)
    if hits:
        return Grounded("operator_panel", VISIBLE, ctx.frame_to_screen(hits[0][0]), round(hits[0][1], 2), (f"the redo panel is open and '{ref.label}' was read in it",), f"Set {ref.label} in the panel at the bottom left of the 3D view.", complete=True, label=ref.label)
    return Grounded("operator_panel", VISIBLE, ctx.window_to_screen(hud.rect), 0.75, ("the redo panel is open (Blender reports its region); the field's label was not read",),
                    f"Set {ref.label} in the panel at the bottom left of the 3D view (click its header if it is collapsed).", label=ref.label)


def ground_context_menu(ctx: GroundContext, ref: TargetRef) -> Grounded:
    hits = find_phrase(ctx.words, ref.label, None, min_score=0.9)
    if len(hits) == 1:
        return Grounded("context_menu", VISIBLE, ctx.frame_to_screen(hits[0][0]), round(hits[0][1], 2), (f"'{ref.label}' was read once on screen",), f"Click {ref.label}.", complete=True, label=ref.label)
    if len(hits) > 1:
        return Grounded("context_menu", AMBIGUOUS, None, 0.3, (f"'{ref.label}' appears {len(hits)} times",), "", ambiguous=True, label=ref.label)
    return Grounded("context_menu", NOT_OPEN, None, 0.0, ("the context menu is not open",), f"Right-click in the 3D view, then choose {ref.label}.", label=ref.label)


def ground_target(ctx: GroundContext, ref: TargetRef) -> Grounded:
    """The grounder for this kind of target. Keys and viewport items have nothing on screen to find: the answer is `words_only`."""
    if ref.kind == "tool":
        return ground_tool(ctx, ref)
    if ref.kind == "menu":
        return ground_menu(ctx, ref)
    if ref.kind == "mode":
        return ground_mode(ctx, ref)
    if ref.kind == "property":
        return ground_property(ctx, ref)
    if ref.kind == "operator_panel":
        return ground_operator_panel(ctx, ref)
    if ref.kind == "context_menu":
        return ground_context_menu(ctx, ref)
    return Grounded(ref.kind, WORDS, None, 1.0, ("nothing on screen names it",), label=ref.label)
