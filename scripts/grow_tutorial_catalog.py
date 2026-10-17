"""Find tutorial CANDIDATES with the official YouTube Data API and write them, unreviewed, to knowledge/tutorial_index_candidates.json.

    python scripts/grow_tutorial_catalog.py --max-searches 8

Authorised by the project owner (2026-10-11). Guard rails:
  - search.list costs about 100 quota units per call, so --max-searches is a hard cap (default 8 = about 800 of the 10,000 daily units);
  - one HTTP request per call, no retries; the first failure stops the run;
  - candidates go to a SEPARATE file, never into tutorial_index.json, so the frozen evaluation sets and the reviewed index are untouched;
  - every field comes from the API reply. `keywords` come from the TITLE words only and `review` is "unreviewed": a person must check level,
    topic and version before an entry is promoted into the index. A search hit is not a recommendation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from ingestion.tutorials import load_index, version_hint_from_title  # noqa: E402
from ingestion.youtube import api  # noqa: E402

QUERIES = [
    "blender join objects tutorial",
    "blender object mode vs edit mode beginner",
    "blender extrude inset bevel modeling basics",
    "blender low poly tree tutorial",
    "blender realistic glass material tutorial",
    "blender rigging a character armature beginner",
    "blender fix shading artifacts smooth shading normals",
    "blender select move rotate scale objects beginner",
]
OFFICIAL = {"Blender", "Blender Studio"}
STOP = frozenset("a an and the in of to for with how blender tutorial tutorials your you my is on this that part".split())
_VERSION = re.compile(r"\b((?:2\.[7-9]\d?|3\.\d|4\.\d|5\.\d))\b")


def to_entry(m: dict) -> dict:
    words = [w for w in re.findall(r"[a-z0-9]+", (m["title"] or "").lower()) if w not in STOP and len(w) > 2]
    title_v, desc_v = version_hint_from_title(m["title"]), m.get("version_in_description")
    m = {k: v for k, v in m.items() if k not in ("captions_flag", "version_in_description")}      # the platform captions flag is unreliable and not stored
    return {**m, "blender_version_hint": title_v or desc_v, "version_source": "title" if title_v else "description" if desc_v else None, "source_tier": "official" if m.get("channel") in OFFICIAL else "community",
            "keywords": list(dict.fromkeys(words))[:8], "review": "unreviewed"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-searches", type=int, default=8)
    ap.add_argument("--per-query", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "knowledge" / "tutorial_index_candidates.json"))
    ap.add_argument("--refresh-hints", action="store_true", help="no search: re-read version hints for the stored candidates (about 1 quota unit per 50 videos)")
    a = ap.parse_args(argv)
    load_dotenv()
    if a.refresh_hints:
        f = Path(a.out)
        d = json.loads(f.read_text(encoding="utf-8"))
        meta = {}
        try:
            ids = [e["id"] for e in d["entries"]]
            for i in range(0, len(ids), 50):
                meta.update({m["id"]: m for m in api.videos_metadata(ids[i:i + 50])})
        except api.YouTubeApiError as e:
            print(f"stopped (no retry): {e}", file=sys.stderr)
            return 1
        for e in d["entries"]:
            m = meta.get(e["id"])
            t_v, d_v = version_hint_from_title(e["title"]), (m or {}).get("version_in_description")
            e["blender_version_hint"], e["version_source"] = t_v or d_v, "title" if t_v else "description" if d_v else None
            e.pop("captions_flag", None)
        d["approx_quota_units_used"] = d.get("approx_quota_units_used", 0) + (len(ids) + 49) // 50
        f.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        from collections import Counter
        print(f"hints: {sum(bool(e['blender_version_hint']) for e in d['entries'])} of {len(d['entries'])}; sources {dict(Counter(e['version_source'] for e in d['entries']))}")
        return 0
    existing = {e["id"] for e in load_index()}
    queries = QUERIES[: a.max_searches]
    units, found = 0, {}
    try:
        for q in queries:
            hits = api.search_videos(q, max_results=a.per_query)
            units += api.QUOTA_UNITS["search"]
            for h in hits:
                if h["video_id"] not in existing:
                    found.setdefault(h["video_id"], {"queries": []})["queries"].append(q)
        ids = list(found)
        meta = []
        for i in range(0, len(ids), 50):
            meta += api.videos_metadata(ids[i:i + 50])
            units += api.QUOTA_UNITS["videos"]
    except api.YouTubeApiError as e:
        print(f"stopped (no retry): {e}", file=sys.stderr)
        return 1
    kept, dropped = [], []
    for m in meta:
        why = ("not public" if m["privacy"] != "public" else "not embeddable" if not m["embeddable"] else "no duration" if m["duration_s"] is None
               else "shorter than 1 minute" if m["duration_s"] < 60 else "longer than 3 hours" if m["duration_s"] > 10800 else None)
        (dropped.append({"id": m["id"], "why": why}) if why else kept.append({**to_entry(m), "found_by": found[m["id"]]["queries"]}))
    out = {"_about": "UNREVIEWED tutorial candidates from YouTube Data API search + videos.list. Metadata is exactly what the API returned; keywords are title words only; "
                     "level, topic fit and Blender version must be checked by a person before promotion into tutorial_index.json. Not used by any router or evaluation.",
           "retrieved": date.today().isoformat(), "queries": queries, "approx_quota_units_used": units, "dropped": dropped, "entries": kept}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(queries)} searches, {len(meta)} videos described, {len(kept)} kept, {len(dropped)} dropped; about {units} quota units; wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
