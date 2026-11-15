"""Loopback server shared by the Maya and Houdini probes (same protocol as the Blender add-on).

Protocol version 1: GET /state with header `X-GuideWire-Token`, optional query `properties=a,b` and
`attributes=c`, answers JSON {"v": 1, "state": {...}}. Loopback only (127.0.0.1); the token is random per
session and written, with the port and the application name, to %LOCALAPPDATA%/GuideWire/probe.json.

`read(properties, attributes) -> dict` is the application-specific part. It is called on the server
thread, so the probe must hand it to the application's main thread itself (Maya:
maya.utils.executeInMainThreadWithResult, Houdini: hdefereval.executeInMainThreadWithResult).
Nothing here imports an application.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PROTOCOL_VERSION = 1
MAX_WANTED, MAX_PATH = 64, 200

Reader = Callable[[list[str], list[str]], dict]


def info_path() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GuideWire", "probe.json")


def split_paths(query: dict[str, list[str]], key: str) -> list[str]:
    """The paths in one query key: comma separated, trimmed, over-long ones and anything past the cap dropped."""
    out: list[str] = []
    for item in ",".join(query.get(key, [])).split(","):
        item = item.strip()
        if item and len(item) <= MAX_PATH and len(out) < MAX_WANTED:
            out.append(item)
    return out


def make_handler(token: str, read: Reader):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path != "/state" or self.headers.get("X-GuideWire-Token") != token:
                self.send_response(403)
                self.end_headers()
                return
            query = parse_qs(url.query)
            try:
                state = read(split_paths(query, "properties"), split_paths(query, "attributes"))
            except Exception as e:                       # report, do not crash the application
                state = {"probe_error": f"{type(e).__name__}: {e}"[:200]}
            body = json.dumps({"v": PROTOCOL_VERSION, "state": state}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    return Handler


def start(app: str, read: Reader) -> HTTPServer:
    """Start serving on a free loopback port and publish the connection details."""
    token = secrets.token_hex(16)
    server = HTTPServer(("127.0.0.1", 0), make_handler(token, read))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    path = info_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"v": PROTOCOL_VERSION, "app": app, "port": server.server_address[1], "token": token,
                   "pid": os.getpid()}, f)
    return server


def stop(server: HTTPServer | None) -> None:
    if server is not None:
        server.shutdown()
    try:
        os.remove(info_path())
    except OSError:
        pass
