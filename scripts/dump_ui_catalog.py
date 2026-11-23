"""Dump the structure of Blender's interface (tools per mode, operators and their redo-panel properties, panels, Properties tabs, the default keymap) into knowledge/app_vocab/blender_ui.json.

    python scripts/dump_ui_catalog.py            # the interface catalog (knowledge/app_vocab/blender_ui.json)
    python scripts/dump_ui_catalog.py --menus    # what every menu holds, as menu routes per mode (knowledge/app_vocab/blender_menus.json); leaves blender_ui.json untouched

Runs verification/uicatalog_blender.py inside the installed Blender, which opens a window for a few seconds (the editor keymaps only load with one) and closes it. Commit the JSON: it records the Blender version the names come from, and `ingestion/targets.py` and
`shared/shortcuts.py` resolve tutorial words against it. Run it again when the pinned Blender version changes.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verification.runner import HERE, find_app  # noqa: E402

OUT = ROOT / "knowledge" / "app_vocab" / "blender_ui.json"
MENUS_OUT = ROOT / "knowledge" / "app_vocab" / "blender_menus.json"


def dump() -> dict:
    with tempfile.TemporaryDirectory() as d:
        req, out = Path(d, "request.json"), Path(d, "ui.json")
        req.write_text(json.dumps({"out": str(out)}), encoding="utf-8")
        inst = find_app("blender")
        if inst is None:
            raise FileNotFoundError("Blender is not installed (set GW_BLENDER to its blender executable)")
        # With a window: the editor keymaps (Mesh, Object Mode, ...) are not loaded in background mode. The window opens for a few seconds and closes by itself.
        p = subprocess.run([inst.exe, "--factory-startup", "--window-geometry", "0", "0", "800", "600", "--python", str(HERE / "uicatalog_blender.py"), "--", str(req)], capture_output=True, text=True, timeout=600)
        if not out.exists():
            raise RuntimeError(f"no catalog produced (exit {p.returncode}): " + " | ".join((p.stderr or p.stdout).strip().splitlines()[-4:]))
        return json.loads(out.read_text(encoding="utf-8"))


def dump_menus() -> dict:
    """Draw every menu once in a headless Blender (no window needed) and reduce what it recorded to menu routes per mode (shared/menu_routes.py)."""
    from shared.menu_routes import build_routes
    with tempfile.TemporaryDirectory() as d:
        req, out = Path(d, "request.json"), Path(d, "menus.json")
        req.write_text(json.dumps({"out": str(out)}), encoding="utf-8")
        inst = find_app("blender")
        if inst is None:
            raise FileNotFoundError("Blender is not installed (set GW_BLENDER to its blender executable)")
        p = subprocess.run([inst.exe, "--background", "--factory-startup", "--python", str(HERE / "menuitems_blender.py"), "--", str(req)], capture_output=True, text=True, timeout=600)
        if not out.exists():
            raise RuntimeError(f"no menu dump produced (exit {p.returncode}): " + " | ".join((p.stderr or p.stdout).strip().splitlines()[-4:]))
        raw = json.loads(out.read_text(encoding="utf-8"))
    routes = build_routes(raw)
    routes["failed"] = sorted(f["id"] for f in raw["failed"] if f["id"].startswith(("VIEW3D", "TOPBAR")))      # the 3D view menus that could not be drawn headless: listed, so a missing route is explained
    return routes


if __name__ == "__main__":
    if "--menus" in sys.argv[1:]:
        routes = dump_menus()
        MENUS_OUT.write_text(json.dumps(routes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(routes["version"], {m: len(v["ops"]) for m, v in routes["modes"].items()}, f"{MENUS_OUT.stat().st_size // 1024} KB, {len(routes['failed'])} 3D view menus not drawn")
        raise SystemExit(0)
    data = dump()
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(data["version"], {k: len(v) for k, v in data.items() if isinstance(v, (list, dict))}, f"{OUT.stat().st_size // 1024} KB")
