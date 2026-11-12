"""Read the live Blender probe (vision/blender_addon/guidewire_probe.py) and merge it with OCR.

The probe sees what the screen cannot (active tool, selection, exact mode); OCR still works
without it. If the probe is not installed or not running, `read_probe` returns None.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

PROTOCOL_VERSION = 1


def _info_path() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GuideWire", "probe.json")


def read_probe(timeout: float = 0.5, info_path: str | None = None, properties: list[str] | None = None,
               attributes: list[str] | None = None) -> dict[str, Any] | None:
    """Current Blender state, or None. `properties` / `attributes` are paths to read; the probe reads
    them on Blender's main thread, so a value asked for the first time may only appear on the next call."""
    query = urllib.parse.urlencode({k: ",".join(v) for k, v in
                                    (("properties", properties), ("attributes", attributes)) if v})
    try:
        with open(info_path or _info_path(), encoding="utf-8") as f:
            info = json.load(f)
        if info.get("v") != PROTOCOL_VERSION:
            return None
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
    return out
