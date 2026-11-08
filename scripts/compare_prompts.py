"""Run several extraction settings over the labelled videos and print one comparison table. Use it the day a stronger model is available.

    python scripts/compare_prompts.py --tier report --versions v7,v9,v10 --windows 0,60

`--windows 0` is one pass, `--windows 60` is overlapping 60 s clips. Every call goes through the cost guard (cache, ceilings, log), so a repeated run costs nothing and
`--dry-run` shows the worst-case cost without calling a model. Scores need the human gold files (eval_data/gold/<video id>.gold.json); only videos that have one are run.
Outputs: runs/compare/<tier>/<version>_w<window>/<app>_<video>.json and a summary printed at the end.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.eval import phase1  # noqa: E402

VIDEOS = [("blender", "EBgHRd5tJfE", 267), ("maya", "8RqfDcoP0jI", 190), ("houdini", "LJeap3wpyJA", 377), ("blender", "PctSMB-RGsM", 386), ("maya", "TmhC35PqZvQ", 392),
          ("houdini", "xWnI7is6e7Q", 397)]
COLS = [("steps", "steps"), ("core_recall", "1:1 recall"), ("precision", "1:1 prec"), ("text_recall_core", "words-in-span"), ("time_recall_core", "time-in-span"), ("step_support", "support"),
        ("timestamp_accuracy", "ts-acc"), ("checkable_end_state", "checkable")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["iterate", "report"], default="iterate")
    ap.add_argument("--versions", default="v7,v9")
    ap.add_argument("--windows", default="0", help="comma list of window lengths in seconds; 0 = one pass")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    gold_dir = ROOT / "eval_data" / "gold"
    table = []
    for ver in a.versions.split(","):
        for w in (float(x) for x in a.windows.split(",")):
            out_dir = ROOT / "runs" / "compare" / a.tier / f"{ver}_w{w:g}"
            out_dir.mkdir(parents=True, exist_ok=True)
            files = []
            for app, vid, dur in VIDEOS:
                if not (gold_dir / f"{vid}.gold.json").exists():
                    continue
                out = out_dir / f"{app}_{vid}.json"
                cmd = [sys.executable, "-m", "ingestion.cli", "video", f"https://www.youtube.com/watch?v={vid}", "--app", app, "--prompt-version", ver, "--tier", a.tier,
                       "--duration", str(dur), "-o", str(out)] + (["--window-s", f"{w:g}"] if w else []) + (["--dry-run"] if a.dry_run else [])
                r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                if a.dry_run:
                    print(ver, w, vid, r.stdout.replace("\n", " ")[:160])
                    continue
                if r.returncode != 0 or not out.exists():
                    print(f"{ver} w{w:g} {vid}: failed ({r.returncode}): {(r.stderr or r.stdout).strip().splitlines()[-1][:160] if (r.stderr or r.stdout).strip() else ''}")
                    continue
                files.append(out)
            if files:
                rows = phase1.report(files, gold_dir)
                table.append((f"{ver} w{w:g}", len(rows), {k: round(sum(r[k] for r in rows if r.get(k) is not None) / len(rows), 3) for k, _ in COLS}))
    if table:
        print("setting".ljust(12), "videos", *(n.rjust(13) for _, n in COLS))
        for name, n, m in table:
            print(name.ljust(12), str(n).rjust(6), *(str(m[k]).rjust(13) for k, _ in COLS))
        (ROOT / "runs" / "compare" / f"summary_{a.tier}.json").write_text(json.dumps([{"setting": n, "videos": c, **m} for n, c, m in table], indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
