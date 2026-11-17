"""Read the live Blender probe (vision/blender_addon/guidewire_probe.py) and merge it with OCR.

The probe sees what the screen cannot (active tool, selection, exact mode); OCR still works
without it. If the probe is not installed or not running, `read_probe` returns None.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any

PROTOCOL_VERSION = 1


def _info_path() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GuideWire", "probe.json")


def _process_state(pid: int) -> tuple[bool | None, str]:
    """(alive, program file name) of the process that wrote probe.json. (None, "") when it cannot be told (not Windows): the file is then trusted, as before."""
    if sys.platform != "win32":
        return None, ""
    try:
        from vision import winplatform
        alive = winplatform.process_alive(pid)
        return alive, winplatform.process_exe(pid) if alive else ""
    except Exception:
        return None, ""


def probe_info(app: str | None = None, info_path: str | None = None) -> dict[str, Any] | None:
    """The connection file the add-on wrote, or None when it is missing, for another application, or stale: probe.json outlives a Blender that crashed, and a reused process id must not be taken for it.
    The process named in it must still be running and, when its program name can be read, be the application's own."""
    try:
        with open(info_path or _info_path(), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    if info.get("v") != PROTOCOL_VERSION or (app and info.get("app", "blender") != app):
        return None
    pid = info.get("pid")
    if isinstance(pid, int):
        alive, exe = _process_state(pid)
        if alive is False:
            return None
        if app and exe:
            from vision.apps import profile
            want = profile(app).exe
            if want and not any(w in exe for w in want):
                return None
    return info


def read_probe(timeout: float = 0.5, info_path: str | None = None, properties: list[str] | None = None,
               attributes: list[str] | None = None, app: str | None = None, keys: list[str] | None = None) -> dict[str, Any] | None:
    """Current Blender state, or None. `properties` / `attributes` are paths to read; the probe reads
    them on Blender's main thread, so a value asked for the first time may only appear on the next call. `keys` are operators (`mesh.loopcut_slide`, or `wm.tool_set_by_id|name=builtin.move`)
    whose keymap entries are wanted; the answer is under `keys` in the state (snapshot v2)."""
    query = urllib.parse.urlencode({k: ",".join(v) for k, v in
                                    (("properties", properties), ("attributes", attributes), ("keys", keys)) if v})
    info = probe_info(app, info_path)                     # None: no add-on, another application's probe, or a stale file
    if info is None:
        return None
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{int(info['port'])}/state" + (f"?{query}" if query else ""),
                                     headers={"X-GuideWire-Token": str(info["token"])})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.load(r)
        return body["state"] if body.get("v") == PROTOCOL_VERSION else None
    except (OSError, ValueError, KeyError):
        return None


def merge_observed(screen: dict[str, Any], probe: dict[str, Any] | None) -> dict[str, Any]:
    """Probe values win (they are exact); screen values fill what the probe lacks."""
    out = dict(screen)
    if probe:
        out.update({k: v for k, v in probe.items() if v not in (None, [], "")})
        out["probe"] = True                                 # the evaluator may judge node_count / name_exists / attribute_exists
    return out
