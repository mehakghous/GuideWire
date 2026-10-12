"""User-supplied transcripts (SRT / WebVTT) and a deterministic evidence check.

GuideWire never fetches third-party captions (see docs/ingestion-technical-plan.md, section on
transcripts). A learner may paste or upload a subtitle file they obtained themselves, or we may
use captions of videos we own. This module only parses such text and checks that the quotes a model
offers as `evidence` actually occur in it, near the claimed time. It is a check against a
user-supplied reference, not against the model's own output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from shared.step_record import StepList

_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE = re.compile(rf"{_TIME}\s*-->\s*{_TIME}")
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9']+")

NOT_FOUND_PENALTY = 0.8


@dataclass(frozen=True)
class Cue:
    start_s: float
    end_s: float
    text: str


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_cues(text: str) -> list[Cue]:
    """Parse SRT or WebVTT. Raises ValueError if no cue is found."""
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for b in blocks:
        lines = [ln for ln in b.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = _CUE.search(ln)
            if m:
                g = m.groups()
                body = " ".join(_TAG.sub("", x).strip() for x in lines[i + 1:])
                if body:
                    cues.append(Cue(_secs(*g[0:4]), _secs(*g[4:8]), body))
                break
    if not cues:
        raise ValueError("no subtitle cues found (expected SRT or WebVTT)")
    return sorted(cues, key=lambda c: c.start_s)


def transcript_for_prompt(cues: list[Cue]) -> str:
    return "\n".join(f"[{c.start_s:.0f}s] {c.text}" for c in cues)


def _words(s: str) -> list[str]:
    return _WORD.findall(s.lower())


def quote_found(quote: str, cues: list[Cue], t0: float | None, t1: float | None, slack_s: float = 15.0) -> str:
    """'in_window' | 'elsewhere' | 'not_found'. A quote counts as found when >= 80% of its words
    (min 3 words) occur in order-insensitive overlap with a window of the transcript."""
    q = _words(quote)
    if len(q) < 3:
        return "in_window"  # too short to judge; do not penalise
    def covers(sel: list[Cue]) -> bool:
        pool = set(_words(" ".join(c.text for c in sel)))
        return bool(sel) and sum(w in pool for w in q) / len(q) >= 0.8
    if t0 is not None:
        lo, hi = t0 - slack_s, (t1 if t1 is not None else t0) + slack_s
        if covers([c for c in cues if c.end_s >= lo and c.start_s <= hi]):
            return "in_window"
    return "elsewhere" if covers(cues) else "not_found"


def check_evidence(sl: StepList, cues: list[Cue]) -> StepList:
    """Flag steps whose evidence quotes are absent from, or mistimed against, the supplied transcript.
    Does not delete or rewrite anything."""
    for s in sl.steps:
        bad = []
        for q in s.evidence:
            r = quote_found(q, cues, s.video_start_s, s.video_end_s)
            if r == "not_found":
                bad.append(f"evidence quote not found in the supplied transcript: '{q[:60]}'")
            elif r == "elsewhere" and s.video_start_s is not None:
                bad.append(f"evidence quote occurs in the transcript but not near {s.video_start_s:g}s: '{q[:60]}'")
        if bad:
            s.flags.extend(bad)
            s.confidence = round(s.confidence * NOT_FOUND_PENALTY, 3)
    return sl
