"""Resolve the actions of saved step files against Blender's interface catalog and print what resolved, what did not, and what is uncertain.

    python scripts/resolve_targets.py                      # the demo tutorials in demo/data
    python scripts/resolve_targets.py path/to/steps.json   # any step file
    python scripts/resolve_targets.py --show               # also print every resolved target

Read-only: it prints; it writes nothing. The same resolver runs when the app imports a tutorial (`app/step_loader.py`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.step_loader import load_steps  # noqa: E402
from ingestion.targets import resolve_steplist  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    files = [Path(f) for f in a.files] or sorted((ROOT / "demo" / "data").glob("blender_*.json"))
    done = with_text = 0
    for f in files:
        sl = load_steps(json.loads(f.read_text(encoding="utf-8")))
        if sl.app != "blender":
            print(f"{f.name}: {sl.app} (the catalog is Blender's): skipped")
            continue
        resolved, r = resolve_steplist(sl)
        if a.show:
            for st in resolved.steps:
                for act in st.actions:
                    if act.target:
                        t = act.target
                        print(f"  {st.id} {act.ui_element or '+'.join(act.keys)!r:55} -> {t.kind:14} id={t.id} op={t.operator} mode={t.mode} tab={t.tab} prop={t.prop} conf={t.confidence}")
        print(f"{f.name}: {r.resolved}/{r.with_text} actions with text resolved {r.by_kind}")
        for line in r.unresolved:
            print("   unresolved:", line)
        for line in r.low_confidence:
            print("   uncertain: ", line)
        done, with_text = done + r.resolved, with_text + r.with_text
    print(f"TOTAL {done}/{with_text} resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
