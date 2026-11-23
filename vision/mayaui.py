"""Maya's interface as Maya itself reports it (the `interface` block of the Maya probe's state), and how to find a tool, shelf button or menu in it.

Maya draws its tool box and shelf as icons with no text, so the screen alone cannot say which icon is "Move". Maya's own widgets can: the probe lists every tool-box
button (with its name, tooltip, on-screen rectangle and whether it is the active tool), the buttons of the current shelf tab (with their tooltips) and the menu-bar items,
all in SCREEN pixels. They match the real screen to within a pixel (checked on Maya 2027.3 against OCR of the same menu words), so a highlight needs no pixel guessing.

Pure: no Windows calls, no capture, no Maya. `MayaUi.valid_for(client)` refuses a snapshot that describes a different window size than the one on screen (the learner moved or
resized Maya since the probe looked), so a rectangle that no longer means anything is never used to point at something.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shared.grounding import Rect

SIZE_TOLERANCE = 3          # px: Maya's window client area may differ from the snapshot's by a border rounding

# What a request calls each tool-box tool -> the button's object name in Maya.
TOOL_ALIASES = {
    "select": "selectTool", "selection": "selectTool", "select tool": "selectTool",
    "lasso": "lassoTool", "lasso select": "lassoTool", "lasso selection": "lassoTool",
    "paint selection": "paintSelectTool", "paint select": "paintSelectTool", "paint": "paintSelectTool",
    "move": "moveTool", "translate": "moveTool",
    "rotate": "rotateTool", "rotation": "rotateTool",
    "scale": "scaleTool", "scaling": "scaleTool",
}
_TOOLBOX_WORDS = {"toolbox", "tool box", "toolbar", "tools", "tool"}
_SHELF_WORDS = {"shelf", "shelves"}
_SPLIT = re.compile(r"\s*(?:>|›|→)\s*")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def _rect(d: dict[str, Any] | None) -> Rect | None:
    if not d:
        return None
    try:
        return Rect(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))
    except (KeyError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MayaTool:
    name: str                 # selectTool, moveTool, ...
    tip: str                  # "Move Tool"
    context: str              # the Maya tool context it selects: moveSuperContext, ...
    rect: Rect
    active: bool


@dataclass(frozen=True)
class MayaShelfButton:
    name: str
    title: str                # the part of the tooltip before the colon: "Polygon Cube"
    annotation: str           # the whole tooltip
    rect: Rect


@dataclass(frozen=True)
class MayaHit:
    kind: str                 # tool | shelf | menu | menu_set | region
    name: str                 # what was matched: "Move Tool", "Polygon Cube", "Create"
    rect: Rect                # screen pixels
    complete: bool            # True when this is the thing to click now; False for the first part of a longer menu path
    active: bool | None = None


@dataclass(frozen=True)
class MayaUi:
    window: Rect
    tools: tuple[MayaTool, ...] = ()
    shelf_tab: str = ""
    shelf: tuple[MayaShelfButton, ...] = ()
    menubar: tuple[tuple[str, Rect], ...] = ()
    menu_set: tuple[str, str, Rect] | None = None             # (label, id, dropdown rect)
    regions: dict[str, Rect] = field(default_factory=dict)

    # ---- reading
    @classmethod
    def parse(cls, state: dict[str, Any] | None) -> MayaUi | None:
        """From a Maya probe state, or None when it has no usable interface block."""
        ui = (state or {}).get("interface")
        window = _rect(ui.get("window")) if isinstance(ui, dict) else None
        if window is None or ui is None:
            return None
        tools = tuple(MayaTool(t["name"], t.get("tip", ""), t.get("context", ""), r, bool(t.get("checked")))
                      for t in ui.get("toolbox", []) if (r := _rect(t.get("rect"))) is not None and t.get("name"))
        shelf = []
        for b in (ui.get("shelf") or {}).get("buttons", []):
            r, note = _rect(b.get("rect")), (b.get("annotation") or "").strip()
            if r is None or not (note or b.get("label")):
                continue                                          # a separator
            shelf.append(MayaShelfButton(b.get("name", ""), (note.split(":")[0] if note else b.get("label", "")).strip(), note, r))
        menubar = tuple((m["label"], r) for m in ui.get("menubar", []) if m.get("label") and (r := _rect(m.get("rect"))) is not None)
        ms = ui.get("menu_set")
        menu_set = (ms.get("label", ""), ms.get("id", ""), r) if ms and (r := _rect(ms.get("rect"))) is not None else None
        regions = {k: r for k, v in (ui.get("regions") or {}).items() if (r := _rect(v)) is not None}
        return cls(window, tools, (ui.get("shelf") or {}).get("tab", ""), tuple(shelf), menubar, menu_set, regions)

    def valid_for(self, client: Rect | None) -> bool:
        """True when the snapshot describes the window as it is now (same place and size, within a border's rounding)."""
        if client is None:
            return False
        w = self.window
        return (abs(w.x - client.x) <= SIZE_TOLERANCE and abs(w.y - client.y) <= SIZE_TOLERANCE
                and abs(w.w - client.w) <= SIZE_TOLERANCE and abs(w.h - client.h) <= SIZE_TOLERANCE)

    @property
    def active_tool(self) -> MayaTool | None:
        return next((t for t in self.tools if t.active), None)

    @property
    def current_menu_set(self) -> str | None:
        return self.menu_set[1] if self.menu_set else None

    # ---- finding
    def find(self, ui_element: str) -> MayaHit | None:
        """The tool, shelf button or menu-bar item a UI path names, or None. Deeper menu items are not here (they exist only while the menu is open: the
        screen text finds those); for a path like "Create > Polygon Primitives > Cube" this returns the "Create" menu with `complete` False."""
        parts = [p.strip() for p in _SPLIT.split(ui_element.strip()) if p.strip()]
        if not parts:
            return None
        if "menu set" in _norm(ui_element):
            return self.menu_set_dropdown()                           # "Rigging menu set": the dropdown that switches it
        head = _norm(parts[0])
        if head in _TOOLBOX_WORDS and len(parts) > 1:
            return self._tool(parts[-1])
        if head in _SHELF_WORDS and len(parts) > 1:
            return self._shelf(parts[-1])
        if len(parts) == 1:
            if "tool" not in _norm(parts[0]).split():                 # a bare word that is exactly a menu's name ("Select", "Create") means the menu; "Select Tool" the tool
                menu = self._menu(parts[0], complete=True)
                if menu is not None:
                    return menu
            return self._tool(parts[0]) or self._shelf(parts[0]) or self._menu(parts[0], complete=True)
        menu = self._menu(parts[0], complete=False)
        return menu

    def _tool(self, text: str) -> MayaHit | None:
        words = _norm(text)
        words = re.sub(r"\btool\b", "", words).strip()
        name = TOOL_ALIASES.get(words) or TOOL_ALIASES.get(words + " tool")
        for t in self.tools:
            if t.name == name or _norm(t.tip) == _norm(text):
                return MayaHit("tool", t.tip or t.name, t.rect, True, t.active)
        return None

    def _shelf(self, text: str) -> MayaHit | None:
        want = _norm(text)
        if not want:
            return None
        exact = [b for b in self.shelf if _norm(b.title) == want]
        if len(exact) == 1:
            return MayaHit("shelf", exact[0].title, exact[0].rect, True)
        if exact:
            return None                                           # several buttons with this name: not a clear target
        tokens = set(want.split())
        loose = [b for b in self.shelf if len(tokens) >= 2 and tokens <= set(_norm(b.title).split())]
        return MayaHit("shelf", loose[0].title, loose[0].rect, True) if len(loose) == 1 else None

    def _menu(self, text: str, complete: bool) -> MayaHit | None:
        want = _norm(text)
        for label, r in self.menubar:
            if _norm(label) == want:
                return MayaHit("menu", label, r, complete)
        return None

    def menu_set_dropdown(self) -> MayaHit | None:
        if self.menu_set is None:
            return None
        return MayaHit("menu_set", self.menu_set[0], self.menu_set[2], True)

    def region(self, name: str) -> Rect | None:
        return self.regions.get(name)
