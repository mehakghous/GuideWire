"""GuideWire read-only probe for Blender. Install via Edit > Preferences > Add-ons > Install from Disk.

Publishes a small snapshot of Blender's state on 127.0.0.1 so GuideWire can verify steps. It only
reads: no operator is run and nothing is changed. Loopback only; every request needs the
per-session token, which is written to %LOCALAPPDATA%/GuideWire/probe.json (current user only).
Protocol version 1: GET /state with header `X-GuideWire-Token` -> JSON {"v": 1, "state": {...}}.
Optional query `properties=a.b,c.d` and `attributes=obj.attr`: paths the caller wants read. The web
thread only records them; Blender is read on its main thread by the timer, so the first answer
after a new request may not hold the value yet (the caller treats that as "not observable").
Paths are attribute and index access only (no calls), the same rule as verification/snapshot_blender.py.

Snapshot v2 (additive: a v1 reader ignores the new keys): `snapshot_version`, `pid`, `blender_version`, a `ui` block (window size, UI scale, every visible area and region with its rectangle in
WINDOW pixels, origin bottom-left; the toolbar's scroll range; the Properties tabs available now), the ordered `tools` list for the current mode, `keys` for the operators the caller asked for
(query `keys=mesh.loopcut_slide,wm.tool_set_by_id|name=builtin.loop_cut`), and two counters, `ui_rev` and `scene_rev`, that change only when that part of the state changes: a caller that sees the same
number twice has nothing new to read. Each new part is read inside its own try/except, so one part failing (Blender's internal modules differ between versions) leaves the others.
"""
bl_info = {"name": "GuideWire Probe", "author": "GuideWire", "version": (0, 2, 0),
           "blender": (5, 2, 0), "category": "System",
           "description": "Read-only state probe for the GuideWire tutorial assistant"}

import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PROTOCOL_VERSION = 1
SNAPSHOT_VERSION = 2
INTERVAL = 0.5
WANTED_TTL = 30.0                    # seconds a requested path stays wanted after the caller last asked for it (a finished step's paths are dropped)
KEYS_TTL = 10.0                      # seconds a keymap lookup is reused (the keymap changes only when the learner edits it)
_state: dict = {"mode": None}
_lock = threading.Lock()
_server = None
_seq = [0]
_wanted: dict = {"properties": {}, "attributes": {}, "keys": {}}      # path -> time.monotonic() it was last asked for; guarded by _lock
_keys_cache: dict = {"at": 0.0, "entries": (), "value": {}}
MAX_WANTED, MAX_PATH = 64, 200
SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\[\]'\" ]*$")      # attribute/index access only: no calls, no dunder names


def node_types(bpy) -> dict:
    """Count of each node type in the scene (same naming as verification/collect_blender.py)."""
    out: dict = {}

    def bump(k):
        out[k] = out.get(k, 0) + 1

    for ob in bpy.data.objects:
        bump(ob.type)
        if ob.type == "ARMATURE":
            for _ in ob.data.bones:
                bump("BONE")
        for c in ob.constraints:
            bump("CONSTRAINT_" + c.type)
        if ob.pose:
            for pb in ob.pose.bones:
                for c in pb.constraints:
                    bump("CONSTRAINT_" + c.type)
        for m in ob.modifiers:
            bump("MODIFIER_" + m.type)
    return out


def read_path(bpy, path: str):
    """Value at an attribute path such as objects['Cube'].location[0], or None if unreadable."""
    if len(path) > MAX_PATH or not SAFE.match(path) or "__" in path:
        return None
    try:
        v = eval(path, {"__builtins__": {}}, {"objects": bpy.data.objects, "scene": bpy.context.scene,
                                              "armatures": bpy.data.armatures})
        if isinstance(v, (int, float, str)):
            return v
        return float(v) if hasattr(v, "__float__") else str(v)
    except Exception:
        return None


def has_attr(bpy, path: str):
    """True/False whether "Name.attr" exists on an object or pose bone called Name; None if unreadable."""
    try:
        name, _, attr = path.partition(".")
        ob = bpy.data.objects.get(name)
        if ob is not None:
            return bool(attr and (attr in ob.keys() or hasattr(ob, attr)))
        for o in bpy.data.objects:
            pb = o.pose.bones.get(name) if o.pose else None
            if pb is not None:
                return bool(attr and (attr in pb.keys() or hasattr(pb, attr)))
        return False
    except Exception:
        return None


# ---- snapshot v2: the interface itself (what the screen shows, read from Blender instead of guessed from pixels)
UI_REGION_TYPES = ("HEADER", "TOOL_HEADER", "TOOLS", "UI", "HUD", "WINDOW", "NAVIGATION_BAR", "FOOTER", "CHANNELS", "ASSET_SHELF", "ASSET_SHELF_HEADER")


def _region(r) -> dict:
    out = {"type": r.type, "x": r.x, "y": r.y, "width": r.width, "height": r.height}
    if r.type == "TOOLS":
        # The visible part of the toolbar in view coordinates: the top is 1 when scrolled to the start, and scrolling down makes both numbers more negative.
        try:
            out["view_top"] = round(float(r.view2d.region_to_view(0, r.height)[1]), 1)
            out["view_bottom"] = round(float(r.view2d.region_to_view(0, 0)[1]), 1)
        except Exception:
            pass
    return out


def properties_tabs(space) -> list | None:
    """The Properties editor tabs available right now, in order. Blender builds this enum for the active object, and an invalid assignment fails with a message that lists it (the static
    `enum_items` lists every tab, including ones that are not shown). Nothing is stored: the invalid value is rejected first. None when it cannot be read."""
    try:
        space.context = "__guidewire_probe__"
    except TypeError as e:
        found = re.search(r"not found in \((.*)\)", str(e))
        return re.findall(r"'([A-Z_]+)'", found.group(1)) if found else None
    except Exception:
        return None
    return None


def ui_snapshot(bpy) -> dict:
    """Window, UI scale and every visible area and region, in window pixels (origin bottom-left, Blender's own convention; the reader adds the Windows client origin)."""
    ctx = bpy.context
    win = getattr(ctx, "window", None) or ctx.window_manager.windows[0]
    system = ctx.preferences.system
    out: dict = {"window": {"width": win.width, "height": win.height}, "ui_scale": system.ui_scale, "pixel_size": system.pixel_size, "dpi": system.dpi, "areas": []}
    for a in win.screen.areas:
        entry: dict = {"type": a.type, "x": a.x, "y": a.y, "width": a.width, "height": a.height, "regions": []}
        for r in a.regions:
            if r.width > 1 and r.height > 1 and r.type in UI_REGION_TYPES:       # Blender keeps a hidden region at 1x1
                entry["regions"].append(_region(r))
        space = a.spaces.active
        if a.type == "PROPERTIES":
            entry["context"] = getattr(space, "context", None)
            tabs = properties_tabs(space)
            if tabs:
                entry["tabs"] = tabs
        if a.type == "VIEW_3D":
            entry["toolbar_shown"] = bool(getattr(space, "show_region_toolbar", False))
            entry["sidebar_shown"] = bool(getattr(space, "show_region_ui", False))
            entry["has_hud"] = any(r.type == "HUD" and r.width > 1 for r in a.regions)
        out["areas"].append(entry)
    return out


def tool_list(bpy) -> list | None:
    """The 3D viewport toolbar for the current mode, in order: `{"group": [{"id", "label"}, ...]}` (one toolbar cell; it shows one member) or `{"separator": true}`. This is Blender's own list
    (`bl_ui.space_toolsystem_common`, an internal module whose layout may change between versions), so it returns None rather than raising."""
    try:
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        cls = ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D")
        items: list = []
        for item in cls.tools_from_context(bpy.context):
            if item is None:
                items.append({"separator": True})
                continue
            group = item if (isinstance(item, tuple) and not hasattr(item, "idname")) else (item,)
            tools = [{"id": t.idname, "label": t.label} for t in group if t is not None and hasattr(t, "idname")]
            if tools:
                items.append({"group": tools})
        return items
    except Exception:
        return None


def _wanted_key(entry: str):
    """`operator` or `operator|prop=value,prop2=value2` -> (operator id, {prop: value})."""
    op, _, rest = entry.partition("|")
    props = dict(p.split("=", 1) for p in rest.split(",") if "=" in p)
    return op.strip(), {k.strip(): v.strip() for k, v in props.items()}


def key_lookup(bpy, entries) -> dict:
    """For each wanted `operator` / `operator|prop=value`, the keymap items that run it: `{"keymap", "space", "key", "user"}` ("user": the learner changed it). Read from the user key
    configuration, so a custom keymap is honoured. Keymaps hold thousands of items, so a result is reused for KEYS_TTL seconds."""
    entries = tuple(sorted(entries))
    now = time.monotonic()
    if _keys_cache["entries"] == entries and now - _keys_cache["at"] < KEYS_TTL:
        return _keys_cache["value"]
    out: dict = {e: [] for e in entries}
    try:
        wanted = {e: _wanted_key(e) for e in entries}
        for km in bpy.context.window_manager.keyconfigs.user.keymaps:
            for kmi in km.keymap_items:
                if not kmi.active:
                    continue
                for e, (op, props) in wanted.items():
                    if kmi.idname != op or len(out[e]) >= 8:
                        continue
                    try:
                        if any(str(getattr(kmi.properties, k, None)) != v for k, v in props.items()):
                            continue
                    except Exception:
                        continue
                    out[e].append({"keymap": km.name, "space": km.space_type, "key": kmi.to_string(), "user": bool(kmi.is_user_modified)})
    except Exception:
        out = {}
    _keys_cache.update(at=now, entries=entries, value=out)
    return out


class Revisions:
    """A counter per part of the state that goes up only when that part's content changes. A reader that sees the same number as last time has nothing new to read or to look at on screen."""

    def __init__(self) -> None:
        self._last: dict = {}
        self._n: dict = {}

    def bump(self, name: str, content) -> int:
        h = json.dumps(content, sort_keys=True, default=str)
        if self._last.get(name) != h:
            self._last[name] = h
            self._n[name] = self._n.get(name, 0) + 1
        return self._n.get(name, 0)


_revs = Revisions()


def gather(bpy, properties=(), attributes=(), keys=()) -> dict:
    """Read the state the evaluator understands. Runs on Blender's main thread only."""
    ctx = bpy.context
    out: dict = {"mode": ctx.mode}
    counts = node_types(bpy)
    out["node_counts"] = counts
    out["nodes"] = sorted(counts)
    out["node_names"] = [o.name for o in bpy.data.objects] + [b.name for a in bpy.data.armatures for b in a.bones]
    try:    # recent operators, oldest first: what the learner just did (read-only list kept by Blender)
        out["history"] = [{"id": o.bl_idname, "name": o.name} for o in ctx.window_manager.operators]
    except Exception:
        pass
    props = {p: v for p in properties if (v := read_path(bpy, p)) is not None}
    if props:
        out["properties"] = props
    attrs = {a: v for a in attributes if (v := has_attr(bpy, a)) is not None}
    if attrs:
        out["attributes"] = attrs
    ws = getattr(ctx, "workspace", None)
    if ws is not None:
        out["workspace"] = ws.name
        try:
            tool = ws.tools.from_space_view3d_mode(ctx.mode, create=False)
            if tool is not None:
                out["active_tool"] = tool.idname
        except Exception:
            pass
    out["selection_types"] = sorted({o.type for o in getattr(ctx, "selected_objects", [])})
    active = getattr(ctx, "active_object", None)
    if active is not None:
        out["active_object"] = {"name": active.name, "type": active.type}
    out["snapshot_version"] = SNAPSHOT_VERSION
    out["pid"] = os.getpid()
    try:
        out["blender_version"] = bpy.app.version_string
    except Exception:
        pass
    try:
        out["ui"] = ui_snapshot(bpy)
    except Exception:
        pass
    tools = tool_list(bpy)
    if tools is not None:
        out["tools"] = tools
    if keys:
        out["keys"] = key_lookup(bpy, keys)
    scene_part = {k: out.get(k) for k in ("mode", "node_counts", "node_names", "selection_types", "active_object", "properties", "attributes")}
    scene_part["history"] = len(out.get("history", []))
    out["scene_rev"] = _revs.bump("scene", scene_part)
    out["ui_rev"] = _revs.bump("ui", {"ui": out.get("ui"), "tools": tools, "mode": out.get("mode"), "active_tool": out.get("active_tool"), "workspace": out.get("workspace")})
    return out


def _make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path != "/state" or self.headers.get("X-GuideWire-Token") != token:
                self.send_response(403)
                self.end_headers()
                return
            query = parse_qs(url.query)
            now = time.monotonic()
            with _lock:
                for key in ("properties", "attributes", "keys"):
                    for item in ",".join(query.get(key, [])).split(","):
                        item = item.strip()
                        if item and len(item) <= MAX_PATH and (item in _wanted[key] or len(_wanted[key]) < MAX_WANTED):
                            _wanted[key][item] = now                      # asked again: stays wanted
                body = json.dumps({"v": PROTOCOL_VERSION, "state": _state}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    return Handler


def info_path() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GuideWire", "probe.json")


def expire_wanted(now: float) -> None:
    """Forget requested paths nobody has asked for in WANTED_TTL seconds: the step they were for is over. Call with _lock held."""
    for kind in _wanted.values():
        for path in [p for p, at in kind.items() if at < now - WANTED_TTL]:
            del kind[path]


def _refresh():
    import bpy
    try:
        with _lock:
            expire_wanted(time.monotonic())
            props, attrs, keys = sorted(_wanted["properties"]), sorted(_wanted["attributes"]), sorted(_wanted["keys"])
        snap = gather(bpy, props, attrs, keys)
        _seq[0] += 1
        snap["seq"] = _seq[0]               # counts refreshes: tells a caller the state is live
        with _lock:
            _state.clear()
            _state.update(snap)
    except Exception as e:                  # keep the last good state; say what went wrong
        import traceback
        traceback.print_exc()
        with _lock:
            _state["probe_error"] = f"{type(e).__name__}: {e}"[:200]
    return INTERVAL


def register():
    global _server
    import bpy
    token = secrets.token_hex(16)
    _server = HTTPServer(("127.0.0.1", 0), _make_handler(token))
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    path = info_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"v": PROTOCOL_VERSION, "app": "blender", "port": _server.server_address[1], "token": token,
                   "pid": os.getpid()}, f)
    bpy.app.timers.register(_refresh, first_interval=0.1, persistent=True)


def unregister():
    global _server
    import bpy
    if bpy.app.timers.is_registered(_refresh):
        bpy.app.timers.unregister(_refresh)
    if _server is not None:
        _server.shutdown()
        _server = None
    try:
        os.remove(info_path())
    except OSError:
        pass
