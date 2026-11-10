"""GuideWire read-only probe for Blender. Install via Edit > Preferences > Add-ons > Install from Disk.

Publishes a small snapshot of Blender's state on 127.0.0.1 so GuideWire can verify steps. It only
reads: no operator is run and nothing is changed. Loopback only; every request needs the
per-session token, which is written to %LOCALAPPDATA%/GuideWire/probe.json (current user only).
Protocol version 1: GET /state with header `X-GuideWire-Token` -> JSON {"v": 1, "state": {...}}.
"""
bl_info = {"name": "GuideWire Probe", "author": "GuideWire", "version": (0, 1, 0),
           "blender": (5, 2, 0), "category": "System",
           "description": "Read-only state probe for the GuideWire tutorial assistant"}

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PROTOCOL_VERSION = 1
INTERVAL = 0.5
_state: dict = {"mode": None}
_lock = threading.Lock()
_server = None


def gather(bpy) -> dict:
    """Read the state the evaluator understands. Runs on Blender's main thread only."""
    ctx = bpy.context
    out: dict = {"mode": ctx.mode}
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
            if self.path != "/state" or self.headers.get("X-GuideWire-Token") != token:
                self.send_response(403)
                self.end_headers()
                return
            with _lock:
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
        snap = gather(bpy)
        with _lock:
            _state.clear()
            _state.update(snap)
    except Exception:
        pass
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
