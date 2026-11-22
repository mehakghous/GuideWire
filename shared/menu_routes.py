"""The menu route that does the same thing as a shortcut ("Shift+A" -> the Add menu; "Alt+P" -> Object > Parent > Clear Parent), from what Blender itself reports. Pure; reads
`knowledge/app_vocab/blender_menus.json`, which `python scripts/dump_ui_catalog.py --menus` writes by drawing every menu once in the installed Blender (verification/menuitems_blender.py).

What it answers
  * `routes_for(operator, mode)`                      the routes in the 3D view header that run an operator in a mode, shortest first, as menu labels: ("Object", "Parent", "Clear Parent");
  * `menu_route(menu_id, mode)`                       where a menu sits: VIEW3D_MT_add -> ("Add",), VIEW3D_MT_object_parent -> ("Object", "Parent");
  * `alternative_for_keys(keys, operator, mode)`      the route for a key press: a key that opens a menu (wm.call_menu) gives that menu, any other key gives its operator's route.

It never invents a route: no entry in the dump, no route. A key with no menu equivalent (a typed value, a modal key) has none, and the caller says nothing about it.
Modes are Blender's own (OBJECT, EDIT_ARMATURE, POSE, EDIT_MESH): the ones whose header menus were dumped. Another mode, or an unknown one, gives no route rather than another mode's.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from shared import shortcuts

MENUS = Path(__file__).resolve().parent.parent / "knowledge" / "app_vocab" / "blender_menus.json"
MAX_DEPTH = 5            # header menu, up to three submenus, the item
MAX_ROUTES = 3           # per operator: the shortest few are enough to point at


def build_routes(raw: dict[str, Any]) -> dict[str, Any]:
    """The compact file from the raw dump (`menus`: id -> label and items; `headers`: mode -> the header's own menus, each with the text the header shows). Per mode: `ops` (operator -> routes) and `menus` (menu id -> route).
    A route is the list of labels the learner clicks, starting with the header menu. Inline menus are flattened into the menu that includes them; a menu is never entered twice on one route."""
    menus, out = raw["menus"], {}
    for mode, roots in raw["headers"].items():
        ops: dict[str, list[list[str]]] = {}
        where: dict[str, list[str]] = {}

        def walk(menu_id: str, path: list[str], seen: frozenset[str]) -> None:
            node = menus.get(menu_id)
            if node is None or menu_id in seen or len(path) >= MAX_DEPTH:
                return
            seen = seen | {menu_id}
            for it in node["items"]:
                if "inline" in it:
                    walk(it["inline"], path, seen)
                elif "menu" in it:
                    sub = [*path, it["text"]]
                    where.setdefault(it["menu"], sub)
                    walk(it["menu"], sub, seen)
                elif "op" in it and it.get("text"):
                    ops.setdefault(it["op"], []).append([*path, it["text"]])

        for root in roots:
            rid, text = (root["id"], root.get("text")) if isinstance(root, dict) else (root, None)
            label = text or (menus.get(rid) or {}).get("label") or rid        # the header shows "Add" where the menu class is called "Mesh" or "Armature"
            where.setdefault(rid, [label])
            walk(rid, [label], frozenset())
        out[mode] = {"ops": {op: _shortest(rs) for op, rs in ops.items()}, "menus": where}
    return {"app": raw.get("app", "blender"), "version": raw.get("version"), "modes": out}


def _shortest(routes: list[list[str]]) -> list[list[str]]:
    seen: list[list[str]] = []
    for r in sorted(routes, key=lambda r: (len(r), r)):
        if r not in seen:
            seen.append(r)
    return seen[:MAX_ROUTES]


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    try:
        return json.loads(MENUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def available() -> bool:
    return bool(_data().get("modes"))


def modes() -> list[str]:
    return list(_data().get("modes", {}))


def routes_for(operator: str, mode: str | None) -> list[tuple[str, ...]]:
    """The header-menu routes that run `operator` in `mode`, shortest first. Empty for an unknown mode or an operator no header menu holds."""
    node = _data().get("modes", {}).get(mode or "")
    return [tuple(r) for r in (node or {}).get("ops", {}).get(operator, [])]


def menu_route(menu_id: str, mode: str | None) -> tuple[str, ...] | None:
    node = _data().get("modes", {}).get(mode or "")
    r = (node or {}).get("menus", {}).get(menu_id)
    return None if r is None else tuple(r)


def alternative_for_keys(keys: list[str] | tuple[str, ...] | str, operator: str | None, mode: str | None = None) -> tuple[str, tuple[str, ...]] | None:
    """(mode, route) for a key press that runs `operator`, or None. With `mode` None every dumped mode is tried in turn and the first that has a route wins; with a mode only that one is."""
    if not operator:
        return None
    for m in ([mode] if mode else modes()):
        if m not in _data().get("modes", {}):
            continue
        if operator == "wm.call_menu":
            for row in shortcuts.rows_for_keys(keys, m):
                if row["op"] == "wm.call_menu":
                    r = menu_route(str(row["props"].get("name", "")), m)
                    if r is not None:
                        return m, r
            continue
        rs = routes_for(operator, m)
        if rs:
            return m, rs[0]
    return None
