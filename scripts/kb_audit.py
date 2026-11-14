"""Audit the rigging knowledge base against the feature matrix (read-only).

    python scripts/kb_audit.py            # a summary
    python scripts/kb_audit.py --detail   # every entry with a problem

Reports, per application: entries without a menu path (ui), ui or facts whose only source is a tutorial or unconfirmed, entries with no official fact, features of the matrix that no entry covers.
Writes nothing and calls no model.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge" / "rigging_knowledge.json"
FEATURES = ROOT / "knowledge" / "rigging_features.json"


def load():
    kb = json.loads(KB.read_text(encoding="utf-8"))
    feats = json.loads(FEATURES.read_text(encoding="utf-8"))
    return kb, feats


def feature_ids(feats) -> dict[str, dict]:
    """{feature id: its record}, whatever shape the features file has (list, or dict of lists/records)."""
    out: dict[str, dict] = {}

    def walk(x):
        if isinstance(x, dict):
            if "id" in x and isinstance(x["id"], str) and "-" in x["id"]:
                out[x["id"]] = x
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(feats)
    return out


def audit(kb, feats) -> dict:
    entries = kb["entries"]
    feat = feature_ids(feats)
    covered = collections.defaultdict(set)
    rows = []
    for e in entries:
        apps = e.get("apps") or []
        for f in e.get("features") or []:
            for a in apps:
                covered[f].add(a)
        ui = e.get("ui") or []
        facts = e.get("facts") or []
        tiers = [f.get("tier") for f in facts]
        problems = []
        if not ui:
            problems.append("no menu path")
        if not any(t == "official" for t in tiers):
            problems.append("no official fact")
        if not e.get("sources_checked") and not any(f.get("sources") for f in facts):
            problems.append("no source on any fact")
        if any(u.get("tier") not in ("official",) for u in ui):
            problems.append("menu path not from an official page")
        unconfirmed = [f["text"][:60] for f in facts if f.get("tier") in ("unconfirmed", "unverified", None)]
        if unconfirmed:
            problems.append(f"{len(unconfirmed)} unconfirmed fact(s)")
        rows.append({"id": e["id"], "apps": apps, "facts": len(facts), "official": sum(t == "official" for t in tiers), "problems": problems})
    gaps = {f: sorted({a for a in ("blender", "maya", "houdini") if (rec.get(a) or "").strip()} - covered.get(f, set())) for f, rec in feat.items()}
    return {"entries": rows, "uncovered": {f: a for f, a in gaps.items() if a}, "features": feat, "covered": covered}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args(argv)
    kb, feats = load()
    r = audit(kb, feats)
    rows = r["entries"]
    by_app = collections.Counter(app for e in rows for app in e["apps"])
    print(f"{len(rows)} entries; by application: {dict(by_app)}")
    for label in ("no menu path", "no official fact", "no source on any fact", "menu path not from an official page"):
        hit = [e["id"] for e in rows if label in e["problems"]]
        print(f"- {label}: {len(hit)}" + (f"  {hit}" if a.detail or len(hit) <= 8 else ""))
    unc = [e["id"] for e in rows if any("unconfirmed" in p for p in e["problems"])]
    print(f"- entries with unconfirmed facts: {len(unc)} {unc}")
    unc_f = r["uncovered"]
    print(f"matrix features: {len(r['features'])}; with no entry for at least one application: {len(unc_f)}")
    for pr in ("P0", "P1", "P2", "P3"):
        tot = [f for f, rec in r["features"].items() if rec.get("priority") == pr]
        cells = sum(len([x for x in ("blender", "maya", "houdini") if (r["features"][f].get(x) or "").strip()]) for f in tot)
        miss = sum(len(unc_f.get(f, [])) for f in tot)
        print(f"   {pr}: {len(tot)} features, {cells} feature-application cells, {cells - miss} covered ({round(100 * (cells - miss) / max(cells, 1))}%)")
    for pr in ("P0",) if not a.detail else ("P0", "P1"):
        for f in sorted(unc_f):
            rec = r["features"][f]
            if rec.get("priority") == pr:
                print(f"   {pr} {f}: no entry for {unc_f[f]}  ({rec.get('name', '')[:58]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
