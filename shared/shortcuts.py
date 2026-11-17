"""Blender shortcuts as knowledge, not text sprinkled into steps. Pure: reads the dumped catalog (`knowledge/app_vocab/blender_ui.json`, Blender's own DEFAULT keymap) and, when the add-on supplies it,
the learner's own keymap (`keys` in probe snapshot v2), which wins.

What it answers
  * `shortcuts_for(operator, mode)`      the keys that run an operator in a mode, only the ones valid there (a key in the "Mesh" keymap does nothing in Object Mode);
  * `operator_for_keys(keys, mode)`      what a key press does in that mode (a tutorial says "Press Ctrl+P": which operator is that here);
  * `tool_shortcut(tool_id, mode)`       the key that SELECTS a tool, if it has one. Most tools have none: `S` runs the scale operator, it does not pick the Scale tool, and `Ctrl+R` runs Loop Cut and
                                         Slide without making Loop Cut the active tool;
  * `advise(...)`                        whether guidance should show a shortcut now, and why. A shortcut is shown only when it is the better way AND it leaves the application in the state the step expects.

Versions: the catalog records the Blender version it was dumped from (`catalog_version`). Another Blender may bind keys differently; `Advice.version_note` says so instead of pretending, and a custom keymap
from the add-on is used whenever available.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parent.parent / "knowledge" / "app_vocab" / "blender_ui.json"

# Blender's own keymap names -> where they apply. A keymap is active in one interaction mode ("Mesh" = Edit Mode on a mesh), in every mode of an editor ("3D View"), or everywhere ("Window").
# These are the names Blender gives its keymaps (checked against the dump by tests); the mode ids are those of `Object.mode` / the toolbar modes.
KEYMAP_MODES: dict[str, frozenset[str]] = {
    "Object Mode": frozenset({"OBJECT"}), "Mesh": frozenset({"EDIT_MESH"}), "Armature": frozenset({"EDIT_ARMATURE"}), "Pose": frozenset({"POSE"}),
    "Curve": frozenset({"EDIT_CURVE", "EDIT_SURFACE"}), "Curves": frozenset({"EDIT_CURVES"}), "Metaball": frozenset({"EDIT_METABALL"}), "Lattice": frozenset({"EDIT_LATTICE"}),
    "Font": frozenset({"EDIT_TEXT"}), "Sculpt": frozenset({"SCULPT"}), "Sculpt Curves": frozenset({"SCULPT_CURVES"}), "Weight Paint": frozenset({"PAINT_WEIGHT"}),
    "Vertex Paint": frozenset({"PAINT_VERTEX"}), "Image Paint": frozenset({"PAINT_TEXTURE"}), "Particle": frozenset({"PARTICLE"}), "Grease Pencil": frozenset({"EDIT_GPENCIL", "PAINT_GREASE_PENCIL"}),
}
ANY_MODE_KEYMAPS = frozenset({"3D View", "3D View Generic", "Object Non-modal", "Window", "Screen", "Frames"})     # valid in every mode of the 3D viewport
MODIFIER_ORDER = ("ctrl", "alt", "shift", "oskey")
_ALIASES = {"control": "ctrl", "cmd": "oskey", "command": "oskey", "win": "oskey", "return": "enter", "escape": "esc", "del": "delete", "spacebar": "space", "space bar": "space"}


@dataclass(frozen=True)
class Shortcut:
    keys: tuple[str, ...]            # as written on a keyboard: ("Ctrl", "R")
    display: str                     # "Ctrl R" (Blender's own wording)
    keymap: str                      # the Blender keymap it lives in
    kind: str = "operator"           # operator: runs the operator | tool: selects the tool
    source: str = "default keymap"   # default keymap | your keymap (the add-on read the learner's)
    modes: frozenset[str] = field(default_factory=frozenset)      # empty = every mode of the 3D viewport


@dataclass(frozen=True)
class Advice:
    show: bool
    reason: str                      # why or why not, in words (also what tests assert)
    shortcut: Shortcut | None = None
    version_note: str = ""


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def catalog() -> dict[str, Any]:
    """The dumped Blender interface catalog (empty when the file is missing)."""
    return _catalog()


def catalog_version() -> str | None:
    return _catalog().get("version")


def normalize_key(name: str) -> str:
    n = name.strip().lower()
    return _ALIASES.get(n, n)


def canonical(keys: list[str] | tuple[str, ...] | str) -> tuple[str, ...]:
    """Key names in one order: modifiers (Ctrl, Alt, Shift, OSKey) first, then the key. `["P", "Ctrl"]`, "Ctrl+P" and "ctrl p" all give ("ctrl", "p")."""
    if isinstance(keys, str):
        keys = [k for k in keys.replace("+", " ").replace("-", " ").split() if k]
    norm = [normalize_key(k) for k in keys]
    mods = [m for m in MODIFIER_ORDER if m in norm]
    rest = [k for k in norm if k not in MODIFIER_ORDER]
    return tuple(mods + rest)


def _display(keys: tuple[str, ...]) -> str:
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "oskey": "OSKey"}
    return " ".join(names.get(k, k.upper() if len(k) == 1 else k.capitalize()) for k in keys)


def modes_of(keymap: str) -> frozenset[str]:
    """The modes a keymap applies in; empty for the ones that apply in every mode."""
    return KEYMAP_MODES.get(keymap, frozenset())


def _valid_in(keymap: str, mode: str | None) -> bool:
    if keymap in KEYMAP_MODES:
        return mode is None or mode in KEYMAP_MODES[keymap]
    return keymap in ANY_MODE_KEYMAPS                 # property editor, outliner and other editors' keymaps do not apply in the viewport


def _row_keys(row: dict) -> tuple[str, ...]:
    return canonical(row["key"])


def shortcuts_for(operator: str, mode: str | None = None, props: dict | None = None, user_keys: list[dict] | None = None) -> list[Shortcut]:
    """The keys that run `operator` (optionally with those property values) in `mode`, most specific keymap first. `user_keys` is the add-on's answer for this operator (`keys[operator]` of snapshot v2): when
    it is given, the learner's own keymap is the truth and the default one is not used."""
    out: list[Shortcut] = []
    if user_keys is not None:
        for e in user_keys:
            if _valid_in(e.get("keymap", ""), mode) and not _is_pointer(e["key"]):
                out.append(Shortcut(canonical(e["key"]), e["key"], e["keymap"], "operator", "your keymap" if e.get("user") else "default keymap", modes_of(e["keymap"])))
        return _specific_first(out)
    for row in _catalog().get("keymap", []):
        if row["op"] != operator or not _valid_in(row["keymap"], mode) or _is_pointer(row["key"]):
            continue
        if props and any(k in row["props"] and str(row["props"][k]) != str(v) for k, v in props.items()):
            continue
        k = _row_keys(row)
        out.append(Shortcut(k, _display(k), row["keymap"], "operator", "default keymap", modes_of(row["keymap"])))
    return _specific_first(out)


def _is_pointer(key: str) -> bool:
    """A click or a drag ("Left Mouse", "drag-Left Mouse") is not a key to press."""
    return "mouse" in key.lower()


def _specific_first(items: list[Shortcut]) -> list[Shortcut]:
    seen, out = set(), []
    for s in sorted(items, key=lambda s: (not s.modes, len(s.keys), s.display)):     # a keymap of that mode first, then the simplest key
        if (s.keys, s.keymap) not in seen:
            seen.add((s.keys, s.keymap))
            out.append(s)
    return out


def operator_for_keys(keys: list[str] | tuple[str, ...] | str, mode: str | None = None) -> list[str]:
    """The operators a key press runs in `mode` (default keymap), e.g. ("ctrl", "p") in OBJECT -> ["object.parent_set"]. Several when the same key does different things (a menu key)."""
    want = canonical(keys)
    found: list[str] = []
    for row in _catalog().get("keymap", []):
        if _valid_in(row["keymap"], mode) and _row_keys(row) == want and row["op"] not in found and row["value"] in ("PRESS", "ANY", "CLICK"):
            found.append(row["op"])
    return found


def tool_operator(tool_id: str) -> str | None:
    """The operator a toolbar tool runs (Loop Cut -> mesh.loopcut_slide), from the catalog, or None."""
    for rows in _catalog().get("tools", {}).values():
        for row in rows:
            for t in row.get("group", []):
                if t["id"] == tool_id and t.get("operator"):
                    return t["operator"]
    return None


def tool_shortcut(tool_id: str, mode: str | None = None) -> Shortcut | None:
    """The key that SELECTS this tool (`wm.tool_set_by_id` with its id), or None: most tools have no key of their own."""
    for row in _catalog().get("keymap", []):
        if row["op"] == "wm.tool_set_by_id" and row["props"].get("name") == tool_id and _valid_in(row["keymap"], mode):
            k = _row_keys(row)
            return Shortcut(k, _display(k), row["keymap"], "tool", "default keymap", modes_of(row["keymap"]))
    return None


def _major_minor(version: str) -> tuple[str, str] | None:
    import re
    m = re.match(r"\s*(\d+)\.(\d+)", version)
    return (m.group(1), m.group(2)) if m else None


def advise(*, tool_id: str | None = None, operator: str | None = None, mode: str | None = None, visibility: str = "visible", tutorial_uses_keys: bool = False,
           expects_tool: str | None = None, user_keys: list[dict] | None = None, app_version: str | None = None) -> Advice:
    """Should guidance show a shortcut for this target now? `visibility`: visible | offscreen | container_hidden | unknown (from the grounder, Part C). `expects_tool`: the step's own check requires this
    tool to be active. The rules, in order:
      1. a shortcut that does not leave the application in the state the step expects is never shown (Ctrl+R runs Loop Cut and Slide but does not make the Loop Cut TOOL active);
      2. it is shown when the target cannot be reached on screen right now (hidden or scrolled out of the toolbar), or when the tutorial itself uses that key;
      3. otherwise the highlighted control is the guidance: not every step needs a shortcut."""
    note = ""
    cv = catalog_version()
    if app_version and cv and _major_minor(app_version) != _major_minor(cv):
        note = f"keys come from Blender {cv}; yours is {app_version}, so check them in Edit > Preferences > Keymap"
    candidate: Shortcut | None = None
    if tool_id:
        candidate = tool_shortcut(tool_id, mode)
        if candidate is None and operator:
            ops = shortcuts_for(operator, mode, user_keys=user_keys)
            if ops and not expects_tool:
                candidate = ops[0]
            elif ops:
                return Advice(False, f"{ops[0].display} runs the operator but does not make {tool_id} the active tool, which this step expects", None, note)
        if candidate is None:
            return Advice(False, "this tool has no key of its own", None, note)
    elif operator:
        ops = shortcuts_for(operator, mode, user_keys=user_keys)
        if not ops:
            return Advice(False, f"{operator} has no key in {mode or 'this mode'}", None, note)
        candidate = ops[0]
    if candidate is None:
        return Advice(False, "nothing to shortcut", None, note)
    if visibility in ("offscreen", "container_hidden"):
        return Advice(True, "the target is not reachable on screen right now", candidate, note)
    if tutorial_uses_keys:
        return Advice(True, "the tutorial itself uses this key", candidate, note)
    return Advice(False, "the target is visible: highlight it instead", candidate, note)
