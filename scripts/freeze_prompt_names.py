"""Freeze (or refresh) the menu and option names that the extraction prompts print.

    python scripts/freeze_prompt_names.py                 # snapshot of the CURRENT knowledge base: this CHANGES the prompt text
    python scripts/freeze_prompt_names.py --kb path.json  # snapshot of another knowledge base file (for example an older one)
    python scripts/freeze_prompt_names.py --check         # exit 1 when the snapshot no longer matches the knowledge base (information only: a growing knowledge base is expected)

Why: the prompts (v6 and later) list the menu paths and official option names of the knowledge base for the application. The knowledge base keeps growing, and a prompt that grows with it
changes the text a cached video result is keyed on, so earlier measurements would describe a different prompt. The prompts therefore read `knowledge/prompt_names.json`. Refreshing it is a
deliberate act: it changes the prompt text of every version from v6, so cached video runs are no longer reused and the measured results need a note (or a re-run).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.extract import PROMPT_NAMES_PATH, menu_lines  # noqa: E402
from ingestion.rigging_knowledge import Knowledge  # noqa: E402

KB = ROOT / "knowledge" / "rigging_knowledge.json"
APPS = ("blender", "maya", "houdini")


def snapshot(kb_path: Path, note: str = "") -> dict:
    raw = kb_path.read_bytes()
    kb = Knowledge(json.loads(raw.decode("utf-8")))
    return {"frozen_from_sha256": hashlib.sha256(raw).hexdigest(), "frozen_on": date.today().isoformat(), "note": note,
            "apps": {app: menu_lines(app, kb.entries) for app in APPS}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", type=Path, default=KB)
    ap.add_argument("--note", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        try:
            cur = json.loads(PROMPT_NAMES_PATH.read_text(encoding="utf-8"))
        except OSError:
            print("no snapshot yet")
            return 1
        live = snapshot(a.kb)
        same = cur["apps"] == live["apps"]
        print("snapshot matches the knowledge base" if same else "snapshot differs from the knowledge base (expected as it grows; refresh deliberately)")
        return 0 if same else 1
    snap = snapshot(a.kb, a.note)
    PROMPT_NAMES_PATH.write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", PROMPT_NAMES_PATH, {k: len(v) for k, v in snap["apps"].items()}, "lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
