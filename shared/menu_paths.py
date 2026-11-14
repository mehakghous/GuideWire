"""Exact menu paths: turn "add a cube" into `Add > Mesh > Cube`, in any supported application.

The data (`shared/menus/<app>_menus.json`) is dumped from the real application by the scripts in
`vision/menus/` (Blender: menus drawn into a recording layout, shortcuts from the default keymap).
Nothing is guessed or written by hand: a path is only offered if the menu really contains it. If an
application has no dump yet, `find_menu_paths` returns nothing instead of inventing a path.

Pure and offline: no application code, no network. Used by the answering pipeline (to put the exact
dropdown items into a step) and by the on-screen guide (to turn a plain request into a path to light up).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

MENU_DIR = Path(__file__).parent / "menus"
APPS = ("blender", "maya", "houdini")
MIN_SCORE = 0.6
MIN_COVER = 0.6          # share of the request's words that the path must account for

_STOP = frozenset("a an the to of in on at for with my me i how do does can you please want need would like what where which "
                  "is are it this that and or then from into using use via by up top bottom two three several selected scene now next "
                  "first again new all".split())
_SYNONYMS = {"make": "add", "create": "add", "new": "add", "insert": "add", "spawn": "add", "place": "add",
             "remove": "delete", "erase": "delete", "kill": "delete", "move": "move", "translate": "move",
             "duplicate": "duplicate", "clone": "duplicate", "bevel": "bevel", "chamfer": "bevel",
             "merge": "merge", "weld": "merge", "combine": "join", "join": "join", "separate": "separate", "split": "split",
             "save": "save", "export": "export", "import": "import"}
# When several menus hold an item of the same name, the common one is listed first (Add > Mesh > Cube before Add > Empty > Cube).
_PREFERRED_PARENTS = {"blender": ("Mesh",)}
_MODE_LABEL = {"OBJECT": "Object Mode", "EDIT_MESH": "Edit Mode (mesh)", "SCULPT": "Sculpt Mode", "TOPBAR": "any mode"}


@dataclass(frozen=True)
class MenuPath:
    app: str
    path: tuple[str, ...]               # exact labels, top menu first: ("Add", "Mesh", "Cube")
    where: str                          # where the top menu is: "3D Viewport header" or "top bar"
    modes: tuple[str, ...]              # where it is available: Blender modes ("OBJECT", "EDIT_MESH"), or menu sets / panes
    labels: tuple[str, ...] = ()        # readable names for `modes` ("Rigging menu set"); falls back to the built-in ones
    keys: str | None = None             # shortcut for the final item, if it has one
    op: str | None = None               # application command id, e.g. mesh.primitive_cube_add
    submenu: bool = False               # the final item opens a further menu
    score: float = 0.0
    alternatives: int = 0               # other DIFFERENT commands that match equally well (0 = a clear choice)
    note: str | None = None             # what to do first when the item exists in one place only (e.g. switch menu set)

    @property
    def text(self) -> str:
        return " > ".join(self.path)

    @property
    def needs(self) -> str | None:
        """What to do first when the menu is not available in every mode."""
        if self.note:
            return self.note
        if "TOPBAR" in self.modes or "OBJECT" in self.modes:
            return None
        if "EDIT_MESH" in self.modes:
            return "Enter Edit Mode first (select the object, press Tab)."
        if "SCULPT" in self.modes:
            return "Enter Sculpt Mode first (mode dropdown in the viewport header)."
        return None

    def describe(self) -> str:
        modes = ", ".join(self.labels or [_MODE_LABEL.get(m, m) for m in self.modes])
        out = f"{self.text}  ({self.where}; {modes})"
        if self.keys:
            out += f". Shortcut: {self.keys}"
        return out


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    out = []
    for w in re.findall(r"[a-z0-9]+", spaced.lower()):
        w = _SYNONYMS.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]                                    # vertices -> vertice is fine: both sides are stemmed the same way
        out.append(w)
    return out


def _content(text: str) -> list[str]:
    return [w for w in _words(text) if w not in _STOP]


def _same(a: str, b: str) -> bool:
    return a == b or (len(a) >= 5 and len(b) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.85)


@dataclass
class _Entry:
    path: tuple[str, ...]
    where: str
    modes: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    keys: str | None = None
    op: str | None = None
    submenu: bool = False


@lru_cache(maxsize=None)
def load_menus(app: str) -> tuple[_Entry, ...]:
    """Every menu item of an application, one entry per distinct path. Empty if no dump exists."""
    f = MENU_DIR / f"{app.lower()}_menus.json"
    if not f.exists():
        return ()
    data = json.loads(f.read_text(encoding="utf-8"))
    merged: dict[tuple[str, ...], _Entry] = {}      # keyed by (where, *path): the same path in two places stays two entries

    def add(items: list[dict], where: str, mode: str, label: str, prefix: tuple[str, ...] = (), note: str | None = None) -> None:
        for it in items:
            path = prefix + (it["label"],)
            if "op" in it or it.get("children") is not None:
                e = merged.setdefault((where,) + path, _Entry(path, where, keys=it.get("keys"), op=it.get("op"), submenu=bool(it.get("children"))))
                if mode not in e.modes:
                    e.modes.append(mode)
                    e.labels[mode] = label
                    if note:
                        e.notes[mode] = note
                e.keys = e.keys or it.get("keys")
            add(it.get("children", []), where, mode, label, path, note)

    add(data.get("topbar", []), "top bar", "TOPBAR", _MODE_LABEL["TOPBAR"])
    for mode, tree in data.get("viewport", {}).items():
        add(tree, "3D Viewport header", mode, _MODE_LABEL.get(mode, mode))
    for g in data.get("groups", []):                           # Maya / Houdini dumps: menu sets, panes, tab menus
        add(g["tree"], g["where"], g["id"], g.get("label", g["id"]), (), g.get("needs"))
    return tuple(merged.values())


def find_menu_paths(app: str, query: str, mode: str | None = None, limit: int = 5) -> list[MenuPath]:
    """The best matching menu items for a request, best first. `mode` (e.g. "EDIT_MESH") puts items that
    exist in that mode first. Empty when nothing matches well enough or the app has no menu data."""
    q = _content(query)
    if not q:
        return []
    scored: list[tuple[float, _Entry]] = []
    for e in load_menus(app):
        leaf = _content(e.path[-1])
        path_words = [w for label in e.path for w in _content(label)]
        if not leaf:
            continue
        hit_leaf = sum(any(_same(w, x) for x in leaf) for w in q)
        hit_path = sum(any(_same(w, x) for x in path_words) for w in q)
        if hit_leaf == 0 and hit_path < len(q):
            continue                                       # the final item must matter to the request
        cover = hit_path / len(q)
        if cover < MIN_COVER:
            continue
        leaf_share = sum(any(_same(x, w) for w in q) for x in leaf) / len(leaf)
        score = 0.6 * cover + 0.3 * leaf_share + 0.1 / len(e.path)
        if e.path[:-1] and e.path[-2] in _PREFERRED_PARENTS.get(app.lower(), ()):
            score += 0.15
        if mode:
            score += 0.03 if mode in e.modes else 0.0
        elif "OBJECT" in e.modes or "TOPBAR" in e.modes:
            score += 0.03                                   # no mode given: assume the learner is in the default one
        scored.append((score, e))
    scored.sort(key=lambda s: (-s[0], len(s[1].path), s[1].path))
    out: list[MenuPath] = []
    for score, e in scored:
        if score < MIN_SCORE or len(out) >= limit:
            break
        key = e.op or e.path[-1]                          # two routes to the same command are not an ambiguity
        ties = len({o.op or o.path[-1] for s, o in scored if (o.op or o.path[-1]) != key and abs(s - score) <= 0.02})
        out.append(MenuPath(app.lower(), e.path, e.where, tuple(e.modes), tuple(e.labels.get(m, m) for m in e.modes),
                            e.keys, e.op, e.submenu, round(score, 3), ties,
                            next(iter(e.notes.values())) if len(e.modes) == 1 and e.notes else None))
    return out


def best_menu_path(app: str, query: str, mode: str | None = None) -> MenuPath | None:
    """The single most likely path, or None when there is no confident, unambiguous answer."""
    hits = find_menu_paths(app, query, mode, limit=1)
    return hits[0] if hits and hits[0].score >= 0.9 and not hits[0].alternatives else None
