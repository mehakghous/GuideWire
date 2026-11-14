"""Read the real menu trees of Maya and Houdini. Pure logic: the application objects are passed in, so it is
tested here against fakes. PROTOTYPE: written from the maya.cmds and Houdini menu-XML documentation and not
yet run inside either application (neither is installed on the development machine). After the first real
run, open the JSON and spot-check a few paths against the application before relying on it.

Output groups look like {"id", "label", "where", "needs", "tree"} where `tree` is a list of
{"label", "op"?, "children"?}: the shape `shared/menu_paths.py` loads.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

MAX_DEPTH = 6


def _clean(label: str) -> str:
    """Menu labels carry keyboard-mnemonic markers ("&File") and trailing ellipses/option-box glyphs."""
    return re.sub(r"\s+", " ", label.replace("&", "")).strip()


# ----------------------------------------------------------------------------------------------- Maya
def _is_menu(cmds: Any, name: str) -> bool:
    """A top-level menu (cmds.menu) as opposed to a sub-menu item (cmds.menuItem)."""
    return bool(cmds.menu(name, exists=True))


def _child_ids(cmds: Any, name: str) -> list[str]:
    q = cmds.menu if _is_menu(cmds, name) else cmds.menuItem
    return list(q(name, q=True, itemArray=True) or [])


def _build_if_empty(cmds: Any, mel: Any, name: str) -> None:
    """Maya fills many menus only when they are opened: run the menu's own build command once."""
    if _child_ids(cmds, name):
        return
    q = cmds.menu if _is_menu(cmds, name) else cmds.menuItem
    post = q(name, q=True, postMenuCommand=True)
    if isinstance(post, str) and post:
        mel.eval(post)


def _maya_items(cmds: Any, mel: Any, parent: str, depth: int) -> list[dict]:
    """Items of a Maya menu or sub-menu, one level deeper per call."""
    if depth > MAX_DEPTH:
        return []
    try:
        _build_if_empty(cmds, mel, parent)
        ids = _child_ids(cmds, parent)
    except Exception:
        return []
    out: list[dict] = []
    for i in ids:
        try:
            if cmds.menuItem(i, q=True, divider=True) or cmds.menuItem(i, q=True, optionBox=True):
                continue
            label = _clean(cmds.menuItem(i, q=True, label=True) or "")
            if not label:
                continue
            if cmds.menuItem(i, q=True, subMenu=True):
                out.append({"label": label, "children": _maya_items(cmds, mel, i, depth + 1)})
            else:
                item: dict[str, Any] = {"label": label}
                cmd = cmds.menuItem(i, q=True, command=True)
                if isinstance(cmd, str) and cmd.strip():
                    item["op"] = cmd.strip()[:80]
                out.append(item)
        except Exception:
            continue
    return out


def maya_groups(cmds: Any, mel: Any) -> list[dict]:
    """One group per menu set (Modeling, Rigging, Animation, FX, Rendering): menu bar entries differ per set."""
    groups: list[dict[str, Any]] = []
    current = cmds.menuSet(q=True, currentMenuSet=True)
    try:
        for ms in cmds.menuSet(q=True, allMenuSets=True) or []:
            cmds.menuSet(currentMenuSet=ms)
            label = _clean(cmds.menuSet(ms, q=True, label=True) or ms)
            tree = []
            for m in cmds.window("MayaWindow", q=True, menuArray=True) or []:
                name = _clean(cmds.menu(m, q=True, label=True) or "")
                if name:
                    tree.append({"label": name, "children": _maya_items(cmds, mel, m, 1)})
            groups.append({"id": ms, "label": f"{label} menu set", "where": "Maya main menu bar",
                           "needs": f"Switch the menu set (top-left dropdown) to {label} first.", "tree": tree})
    finally:
        cmds.menuSet(currentMenuSet=current)                       # leave the learner's menu set as it was
    return groups


# --------------------------------------------------------------------------------------------- Houdini
_LEAF = {"scriptItem", "actionItem", "toolItem", "scriptToggleItem", "actionToggleItem"}


def _houdini_items(node: ET.Element) -> list[dict]:
    out = []
    for child in node:
        tag = child.tag
        label_el = child.find("label")
        label = _clean(label_el.text or "") if label_el is not None and label_el.text else ""
        if tag == "subMenu":
            if label:
                out.append({"label": label, "children": _houdini_items(child)})
            else:
                out.extend(_houdini_items(child))                  # an unlabelled sub-menu only groups its items
        elif tag in _LEAF and label:
            item: dict[str, Any] = {"label": label}
            ident = child.get("id") or child.get("name")
            if ident:
                item["op"] = ident
            out.append(item)
        elif tag == "menuBar":
            out.extend(_houdini_items(child))
    return out


def parse_houdini_menu_xml(text: str) -> list[dict]:
    """The main menu (File, Edit, Render, ...) from a Houdini menu XML file."""
    root = ET.fromstring(text)
    bars = root.findall(".//menuBar")
    return _houdini_items(bars[0] if bars else root)


def houdini_groups(hou: Any, read_file=None) -> list[dict]:
    """Main menu from the application's own menu XML, plus the Tab-menu node names of each network type."""
    groups: list[dict[str, Any]] = []
    for name in ("MainMenuCommon.xml", "MainMenuCommon"):
        path = hou.findFile(name) if hasattr(hou, "findFile") else None
        if path:
            text = (read_file or (lambda p: open(p, encoding="utf-8").read()))(path)
            tree = parse_houdini_menu_xml(text)
            if tree:
                groups.append({"id": "MAIN", "label": "main menu", "where": "Houdini main menu bar", "tree": tree})
                break
    for cat_name, cat in hou.nodeTypeCategories().items():
        items: list[dict] = []
        for t in cat.nodeTypes().values():
            try:
                if t.hidden() or t.deprecated():
                    continue
                items.append({"label": t.description(), "op": f"{cat_name.lower()}/{t.name()}"})
            except Exception:
                continue
        if items:
            groups.append({"id": f"TAB_{cat_name.upper()}", "label": f"{cat_name} network", "where":
                           "network editor Tab menu (press Tab, then type the name)",
                           "needs": f"Open a {cat_name} network in the Network Editor first.",
                           "tree": sorted(items, key=lambda x: x["label"].lower())})
    return groups
