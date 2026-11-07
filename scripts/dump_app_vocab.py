"""Dump the real vocabulary of each installed application into knowledge/app_vocab/<app>.json.

    python scripts/dump_app_vocab.py [blender] [maya] [houdini]      (default: every application that is installed)

Runs the scripts in verification/vocab_<app>.py inside the application (headless). Commit the JSON: it records which version the names come from, and
the profiles in ingestion/profiles.py are checked against it by tests/test_app_vocab.py.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verification.runner import HERE, find_app, run_script  # noqa: E402

OUT = ROOT / "knowledge" / "app_vocab"


def dump(app: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        req, out = Path(d, "request.json"), Path(d, "vocab.json")
        req.write_text(json.dumps({"out": str(out)}), encoding="utf-8")
        p = run_script(app, HERE / f"vocab_{app}.py", [str(req)], timeout=600)
        if not out.exists():
            raise RuntimeError(f"{app}: no vocabulary produced (exit {p.returncode}): " + " | ".join((p.stderr or p.stdout).strip().splitlines()[-4:]))
        return json.loads(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    apps = sys.argv[1:] or [a for a in ("blender", "maya", "houdini") if find_app(a)]
    OUT.mkdir(parents=True, exist_ok=True)
    for a in apps:
        data = dump(a)
        (OUT / f"{a}.json").write_text(json.dumps(data, indent=0, ensure_ascii=False), encoding="utf-8")
        print(a, data["version"], {k: len(v) for k, v in data.items() if isinstance(v, (list, dict))})
