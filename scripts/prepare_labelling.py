"""Choose held-out tutorials for human labelling and prepare everything an annotator needs. Nothing here labels anything.

    python scripts/prepare_labelling.py --n 10              # dry run: shows the selection, writes nothing, no network
    python scripts/prepare_labelling.py --n 10 --fetch      # writes the manifest + blank sheets, fetches transcripts (opt-in caption adapter)

Selection (fixed, so it cannot drift toward easy videos): from knowledge/tutorial_index_candidates.json keep videos of 4-15 minutes, never one already in the
reviewed index (those tuned the rules), at most one video per channel; walk the 8 search topics round-robin and take, inside each topic, the video with the
smallest sha256(salt + id). With --fetch a video without usable English captions is skipped and the next one in its topic is tried.

Network: --fetch uses ingestion.youtube.captions (a third-party library on an undocumented endpoint; the project owner's opt-in decision, plan section 77):
one request set per video, no retries, stops at the first block. Transcripts go to local_data/labelling/ (git-ignored; YouTube-derived, kept local).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.tutorials import load_index  # noqa: E402
from ingestion.youtube.captions import CaptionsBlocked, CaptionsUnavailable, fetch_captions  # noqa: E402

LABELS = ROOT / "eval_data" / "labels"
TRANSCRIPTS = ROOT / "local_data" / "labelling"
SALT = "guidewire-heldout-v1"
SECOND_ANNOTATOR_EVERY = 3        # every 3rd selected video is double-annotated (about 30%)


def ranked_by_topic(candidates: list[dict], reviewed_ids: set[str]) -> dict[str, list[dict]]:
    pool = [e for e in candidates if 240 <= (e.get("duration_s") or 0) <= 900 and e["id"] not in reviewed_ids]
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for e in pool:
        by_topic[e["found_by"][0]].append(e)
    return {t: sorted(v, key=lambda e: hashlib.sha256((SALT + e["id"]).encode()).hexdigest()) for t, v in sorted(by_topic.items())}


def choose(candidates: list[dict], reviewed_ids: set[str], n: int, accept=lambda e: True) -> list[dict]:
    """Round-robin over topics; one video per channel; `accept` lets --fetch skip videos without captions."""
    queues = {t: list(v) for t, v in ranked_by_topic(candidates, reviewed_ids).items()}
    chosen, channels = [], set()
    while len(chosen) < n and any(queues.values()):
        for t in list(queues):
            while queues[t]:
                e = queues[t].pop(0)
                if e["channel"] in channels or not accept(e):
                    continue
                chosen.append({**e, "topic": t})
                channels.add(e["channel"])
                break
            if len(chosen) >= n:
                break
    return chosen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--fetch", action="store_true", help="fetch transcripts and write the manifest and blank sheets (network)")
    a = ap.parse_args(argv)
    cands = json.loads((ROOT / "knowledge" / "tutorial_index_candidates.json").read_text(encoding="utf-8"))["entries"]
    reviewed = {e["id"] for e in load_index()}
    transcripts: dict[str, tuple[str, str]] = {}

    def accept(e):
        if not a.fetch:
            return True
        try:
            r = fetch_captions(e["id"])
        except CaptionsBlocked as ex:
            raise SystemExit(f"stopped (no retry): {ex}")
        except CaptionsUnavailable as ex:
            print(f"  skip {e['id']}: {str(ex)[:90]}")
            return False
        transcripts[e["id"]] = (r.text, r.source)
        return True

    chosen = choose(cands, reviewed, a.n, accept)
    print(f"{len(chosen)} videos, {len({e['channel'] for e in chosen})} channels, {len({e['topic'] for e in chosen})} topics")
    for i, e in enumerate(chosen, 1):
        print(f" {i:>2}. {e['id']} {e['duration_s'] // 60}:{e['duration_s'] % 60:02d} {e['channel'][:24]:24} {e['title'][:60]}  [{transcripts.get(e['id'], ('', '?'))[1]}]")
    if not a.fetch:
        print("dry run: nothing written. Re-run with --fetch to write the manifest, blank sheets and transcripts.")
        return 0
    LABELS.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    videos = []
    for i, e in enumerate(chosen, 1):
        who = ["ayesha"] + (["second"] if i % SECOND_ANNOTATOR_EVERY == 0 else [])
        (TRANSCRIPTS / f"{e['id']}.transcript.txt").write_text(transcripts[e["id"]][0], encoding="utf-8")
        for w in who:
            sheet = LABELS / f"{e['id']}.{w}.csv"
            if not sheet.exists():                                       # never overwrite a sheet somebody has started
                sheet.write_text("start,end,action,evidence,importance,keys_or_menu,notes\n", encoding="utf-8")
        videos.append({"video_id": e["id"], "title": e["title"], "channel": e["channel"], "url": e["url"], "duration_s": e["duration_s"], "topic": e["topic"],
                       "app_version": e.get("blender_version_hint"), "captions": transcripts[e["id"]][1], "annotators": who})
    (LABELS / "manifest.json").write_text(json.dumps({"_about": "Held-out tutorials for human labelling (docs/labelling_guide.md). Sheets are blank until a person fills them. "
                                                      "'second' = the double-annotating person: rename the file to their name and edit `annotators` here.",
                                                      "selection": f"scripts/prepare_labelling.py, salt {SALT}", "transcripts_dir": "local_data/labelling", "videos": videos}, indent=1), encoding="utf-8")
    md = ["# Labelling assignments", "", "| # | Video | Length | Channel | Topic | Captions | Annotators |", "|---|---|---|---|---|---|---|"]
    md += [f"| {i} | [{v['title'][:55]}]({v['url']}) | {v['duration_s'] // 60}:{v['duration_s'] % 60:02d} | {v['channel']} | {v['topic'].replace('blender ', '')[:30]} | {v['captions']} | {', '.join(v['annotators'])} |"
           for i, v in enumerate(videos, 1)]
    (LABELS / "ASSIGNMENTS.md").write_text("\n".join(md) + "\n\nSheets: `eval_data/labels/<video id>.<name>.csv`. Transcripts (local only): `local_data/labelling/`. Guide: `docs/labelling_guide.md`.\n", encoding="utf-8")
    print(f"wrote {LABELS / 'manifest.json'}, ASSIGNMENTS.md and {sum(len(v['annotators']) for v in videos)} blank sheets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
