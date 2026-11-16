"""Dump the structure of Blender's interface (tools per mode, operators and their redo-panel properties, panels, Properties tabs, the default keymap) into knowledge/app_vocab/blender_ui.json.

    python scripts/dump_ui_catalog.py

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


if __name__ == "__main__":
    data = dump()
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(data["version"], {k: len(v) for k, v in data.items() if isinstance(v, (list, dict))}, f"{OUT.stat().st_size // 1024} KB")
