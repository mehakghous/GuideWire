"""GuideWire read-only probe for Blender. Install via Edit > Preferences > Add-ons > Install from Disk.

Publishes a small snapshot of Blender's state on 127.0.0.1 so GuideWire can verify steps. It only
reads: no operator is run and nothing is changed. Loopback only; every request needs the
per-session token, which is written to %LOCALAPPDATA%/GuideWire/probe.json (current user only).
Protocol version 1: GET /state with header `X-GuideWire-Token` -> JSON {"v": 1, "state": {...}}.
Optional query `properties=a.b,c.d` and `attributes=obj.attr`: paths the caller wants read. The web
thread only records them; Blender is read on its main thread by the timer, so the first answer
after a new request may not hold the value yet (the caller treats that as "not observable").
Paths are attribute and index access only (no calls), the same rule as verification/snapshot_blender.py.
"""
bl_info = {"name": "GuideWire Probe", "author": "GuideWire", "version": (0, 1, 0),
           "blender": (5, 2, 0), "category": "System",
           "description": "Read-only state probe for the GuideWire tutorial assistant"}

import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PROTOCOL_VERSION = 1
INTERVAL = 0.5
_state: dict = {"mode": None}
_lock = threading.Lock()
_server = None
_seq = [0]
_wanted: dict = {"properties": set(), "attributes": set()}      # guarded by _lock
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


def gather(bpy, properties=(), attributes=()) -> dict:
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
            with _lock:
                for key in ("properties", "attributes"):
                    for item in ",".join(query.get(key, [])).split(","):
                        item = item.strip()
                        if item and len(item) <= MAX_PATH and len(_wanted[key]) < MAX_WANTED:
                            _wanted[key].add(item)
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


def _refresh():
    import bpy
    try:
        with _lock:
            props, attrs = sorted(_wanted["properties"]), sorted(_wanted["attributes"])
        snap = gather(bpy, props, attrs)
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
        json.dump({"v": PROTOCOL_VERSION, "port": _server.server_address[1], "token": token,
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
