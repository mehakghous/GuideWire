"""Which KINDS of action does extraction miss? Recall per action kind against the human gold, so a weak spot ("toggles", "mode changes") is a number, not a feeling.

A gold action can have several kinds (a keyboard shortcut that enters Edit Mode is both). The kinds are read from the labeller's own words with plain patterns, so they
are a rough sorting aid: read the listed misses before trusting a figure. "Small" kinds are the ones a beginner loses most easily when a step is skipped.

    python -m ingestion.eval.small_actions runs/phase1/*.json [--gold-dir eval_data/gold]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from shared.step_record import StepList

from .phase1 import covered_actions, load_gold

_I = re.IGNORECASE
KINDS: list[tuple[str, bool, re.Pattern]] = [(name, small, re.compile(rx, _I)) for name, small, rx in [
    ("mode change", True, r"\b(?:enter|exit|leave|switch(?: back)? to|go (?:in|back)|return to|change to|toggle)\b.{0,40}\b(?:mode|modify|pose|object mode|edit mode)\b|\bpress tab\b|\bmodify mode\b|\bcreate mode\b"),
    ("toggle or checkbox", True, r"\b(?:enable|disable|toggle|turn (?:on|off)|tick|untick|check|uncheck|checkbox|check box|activate|deactivate|show|hide|display)\b"),
    ("dropdown or option choice", True, r"\b(?:drop-?down|choose|pick|select(?:ing)? (?:the )?(?:option|mode|type|axis|method|solver|preset))\b|\bset (?:the )?[\w ]{1,30} to [a-z][a-z ]{2,}\b"),
    ("panel, tab or window", True, r"\b(?:open|close|switch to|go to|show|expand|collapse)\b.{0,40}\b(?:panel|tab|editor|window|outliner|properties|network|attribute editor|channel box|menu set|workspace|viewport|spreadsheet|node graph|options)\b"),
    ("keyboard shortcut", True, r"\bpress(?:ing)?\b|\bhotkey\b|\bshortcut\b|\b(?:shift|ctrl|alt|cmd)\b\s*\+|\bkey\b"),
    ("tool selection", True, r"\b(?:tool|brush|manipulator|gizmo|handle)\b"),
    ("typed value or setting", True, r"\b(?:set|enter|type|input|change|adjust|increase|decrease|scale to|value)\b.{0,40}\b(?:\d|to\b|value|field|parameter|slider|amount|size|radius|weight)"),
    ("naming", True, r"\b(?:rename|name(?:d)?|call it|label)\b"),
    ("selection", True, r"\b(?:select(?:ing)?|pick|click on|click the|choose)\b"),
    ("view or navigation", True, r"\b(?:orbit|zoom|pan|frame|rotate the view|camera|front view|side view|top view|perspective|focus on)\b"),
    ("create or add", False, r"\b(?:create|add|new|extrude|duplicate|insert|place|draw|generate|build|import)\b"),
    ("connect, parent or constrain", False, r"\b(?:connect|wire|link|parent|unparent|constrain|constraint|bind|attach|assign|skin|merge)\b"),
]]


def kinds_of(text: str, keys: str = "") -> list[str]:
    t = f"{text} {keys}"
    return [name for name, _small, rx in KINDS if rx.search(t)] or ["other"]


def report(paths: list[Path], gold_dir: Path) -> dict:
    """Per application and kind: how many core gold actions of that kind, and how many were covered by the right words / only by time."""
    tally: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    misses: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for p in paths:
        sl = StepList.model_validate_json(p.read_text(encoding="utf-8"))
        gold = load_gold(gold_dir, sl.video_id)
        if gold is None:
            continue
        for g, in_span, in_words in covered_actions(sl, gold):
            if g.importance != "core":
                continue
            keys = " ".join(k for a in g.actions for k in a.keys)
            for k in kinds_of(g.goal, keys):
                t = tally[sl.app][k]
                t[0] += 1
                t[1] += in_words
                t[2] += in_span
            if not in_words:
                misses[sl.app].append((sl.video_id, int(g.t_start), g.goal))
    small = {n for n, s, _ in KINDS if s}
    out: dict = {"per_application": {}, "all_applications": {}, "misses": dict(misses)}
    allt: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for app, kinds in tally.items():
        out["per_application"][app] = {k: {"actions": v[0], "text_recall": round(v[1] / v[0], 3), "time_recall": round(v[2] / v[0], 3)} for k, v in sorted(kinds.items())}
        for k, v in kinds.items():
            for i in range(3):
                allt[k][i] += v[i]
    out["all_applications"] = {k: {"actions": v[0], "text_recall": round(v[1] / v[0], 3), "time_recall": round(v[2] / v[0], 3), "small": k in small} for k, v in sorted(allt.items())}
    small_all = [allt[k] for k in allt if k in small]
    big_all = [allt[k] for k in allt if k not in small and k != "other"]
    out["small_vs_major"] = {"small_kinds_text_recall": round(sum(v[1] for v in small_all) / max(1, sum(v[0] for v in small_all)), 3),
                             "major_kinds_text_recall": round(sum(v[1] for v in big_all) / max(1, sum(v[0] for v in big_all)), 3)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ingestion.eval.small_actions")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--gold-dir", type=Path, default=Path("eval_data") / "gold")
    a = ap.parse_args(argv)
    print(json.dumps(report(a.files, a.gold_dir), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
