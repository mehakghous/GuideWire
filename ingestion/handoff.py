"""From a chosen tutorial to ingestion: source classification, section requests, and an honest plan for what can run offline now.

This module NEVER touches the network or a model. It decides which local source (a user-supplied transcript, or captions already
cached by the opt-in adapter) can feed the offline transcript route, slices that text to a requested section, and otherwise reports
what is missing. A caller that wants the opt-in caption fetch passes it in as `fetch`; its failures become a stated reason, never a crash.

Finding a tutorial does not prove its instructions are right or complete: every step produced here is `narrated` evidence from captions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from shared.answer import AnswerBundle, SourceRef, SourceSection

from .kb.index import stem, terms
from .transcript_ingest import ingest_transcript, parse_timed_text
from .youtube.captions import CACHE_DIR, CaptionResult, CaptionsUnavailable, purge_expired, to_timed_text
from .youtube.metadata import parse_video_id

_URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}"


def ts_to_s(ts: str) -> float:
    s = 0.0
    for p in ts.split(":"):
        s = s * 60 + float(p)
    return s


# ---------------------------------------------------------------------------------------------------------------- URLs
@dataclass
class UrlInfo:
    kind: str                       # youtube_video | youtube_playlist | youtube_other | other
    url: str
    video_id: str | None = None
    host: str | None = None
    start_s: float | None = None    # from ?t= / &start=
    playlist_id: str | None = None  # from ?list=; for a bare playlist link kind is youtube_playlist


def _parse_t(v: str) -> float | None:
    v = v.strip().lower()
    if v.isdigit():
        return float(v)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", v)
    if m and any(m.groups()):
        h, mi, s = (int(x or 0) for x in m.groups())
        return float(h * 3600 + mi * 60 + s)
    return None


def find_urls(text: str) -> list[str]:
    return [u.rstrip(".,;") for u in _URL.findall(text)]


def classify_url(url: str) -> UrlInfo:
    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host not in ("youtube.com", "youtu.be", "music.youtube.com", "youtube-nocookie.com"):
        return UrlInfo("other", url, host=host or None)
    q = parse_qs(u.query)
    start = next((_parse_t(q[k][0]) for k in ("t", "start") if k in q and q[k]), None)
    pl = (q.get("list") or [None])[0]
    if u.path.rstrip("/") == "/playlist" and pl:
        return UrlInfo("youtube_playlist", url, host=host, playlist_id=pl)
    try:
        return UrlInfo("youtube_video", url, video_id=parse_video_id(url), host=host, start_s=start, playlist_id=pl)
    except ValueError:
        return UrlInfo("youtube_other", url, host=host)       # channel, search results, malformed id


# ------------------------------------------------------------------------------------------------------ section requests
@dataclass
class Section:
    start_s: float | None = None
    end_s: float | None = None
    topic: list[str] = field(default_factory=list)       # words to locate in captions/chapters when no times were given
    source: str = ""                                      # how it was understood, for the audit trail

    @property
    def is_empty(self) -> bool:
        return self.start_s is None and self.end_s is None and not self.topic


_RANGE = re.compile(rf"\b(?:from|between)\s+({_TS})\s*(?:to|and|-|–|until)\s*({_TS})", re.I)
_AFTER = re.compile(rf"\b(?:after|from|starting at|start at|at|beyond)\s+({_TS})\b", re.I)
_FIRST = re.compile(r"\bfirst\s+(\d+)\s*(minutes?|mins?|seconds?|secs?)\b", re.I)
_TOPIC = re.compile(r"\b(?:only|just)?\s*(?:the\s+)?(?:part|section|bit|chapter|segment|portion)\s+(?:about|on|where|that covers|covering|for)\s+(.+?)(?:[.?!]|$)", re.I)


def parse_section(text: str, url_start_s: float | None = None) -> Section:
    t = _URL.sub(" ", text)
    m = _RANGE.search(t)
    if m:
        return Section(ts_to_s(m.group(1)), ts_to_s(m.group(2)), source="time range in the request")
    m = _FIRST.search(t)
    if m:
        n = float(m.group(1)) * (60 if m.group(2).lower().startswith("min") else 1)
        return Section(0.0, n, source="'first N minutes' in the request")
    m = _AFTER.search(t)
    if m:
        return Section(ts_to_s(m.group(1)), None, source="start time in the request")
    m = _TOPIC.search(t)
    if m:
        tt = [w for w in terms(m.group(1)) if w not in ("tutorial", "video", "blender")]
        if tt:
            return Section(topic=tt, source="topic phrase in the request")
    if url_start_s is not None:
        return Section(url_start_s, None, source="start time in the link (t=)")
    return Section()


def slice_timed_text(text: str, start_s: float | None = None, end_s: float | None = None, duration_s: float | None = None) -> str:
    """Keep the cues that start inside [start_s, end_s). Timestamps stay ABSOLUTE so step times still point into the original video."""
    cues = parse_timed_text(text, duration_s)
    keep = [c for c in cues if (start_s is None or c.start_s >= start_s) and (end_s is None or c.start_s < end_s)]
    return to_timed_text([{"start": c.start_s, "text": c.text} for c in keep])


def locate_topic(text: str, topic: list[str], *, chapters: list[tuple[float, str]] | None = None, max_gap_s: float = 30.0,
                 pad_s: float = 10.0, limit: int = 3) -> list[tuple[float, float, str]]:
    """Candidate windows (start, end, why) for a topic, best first. Chapters win when one title matches; otherwise clusters of captions that
    mention the topic. These are CANDIDATES for the user to confirm: mentioning a word is not teaching it."""
    want = {stem(t) for t in topic}
    if not want:
        return []
    out: list[tuple[float, float, str]] = []
    if chapters:
        ch = sorted(chapters)
        for i, (st, title) in enumerate(ch):
            if want & {stem(w) for w in re.findall(r"[a-z0-9]+", title.lower())}:
                out.append((st, ch[i + 1][0] if i + 1 < len(ch) else st + 600.0, f"chapter '{title}'"))
    cues = parse_timed_text(text)
    hits = [c for c in cues if want & {stem(w) for w in re.findall(r"[a-z0-9]+", c.text.lower())}]
    clusters: list[list] = []
    for c in hits:
        if clusters and c.start_s - clusters[-1][-1].start_s <= max_gap_s:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    scored = sorted(clusters, key=lambda cl: (-len(cl), cl[0].start_s))
    for cl in scored:
        out.append((max(0.0, cl[0].start_s - pad_s), cl[-1].end_s + pad_s, f"{len(cl)} caption line(s) mention {', '.join(topic)}"))
    return out[:limit]


# ----------------------------------------------------------------------------------------------------- the handoff plan
@dataclass
class IngestionPlan:
    status: str                      # ready | needs_transcript | invalid_source
    video_id: str | None = None
    source: str | None = None        # user_transcript | cached_captions | fetched_captions
    caption_kind: str | None = None  # creator | auto | unknown (user text)
    section: Section | None = None
    reasons: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    bundle: AnswerBundle | None = None


def read_cached_captions(video_id: str, cache_dir: Path = CACHE_DIR) -> CaptionResult | None:
    """Local read only: never fetches. Honours the 30-day rule by purging expired records first."""
    import json
    purge_expired(cache_dir)
    f = Path(cache_dir) / f"{video_id}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return CaptionResult(video_id, to_timed_text(d["snippets"]), d["source"], d["language"], d["fetched_at"], True,
                         [tuple(x) for x in d.get("tracks", [])])


NO_TRANSCRIPT_OPTIONS = [
    "Paste or upload a subtitle file (SRT/VTT) or a timestamped transcript you already have: this runs offline.",
    "Ask for the opt-in caption fetch for this one video (third-party, undocumented endpoint, against the platform's terms; see the plan, section 77).",
    "Run the video route with a model (needs quota and approval; unverified until a person checks it).",
]


def plan_ingestion(selected: str, *, entry: dict | None = None, transcript_text: str | None = None, section: Section | None = None,
                   chapters: list[tuple[float, str]] | None = None, version: str | None = None, duration_s: float | None = None,
                   cache_dir: Path = CACHE_DIR, fetch: Callable[[str], CaptionResult] | None = None) -> IngestionPlan:
    """`selected` is a URL or id (from a recommendation). `entry` is its curated-index record, if any. Returns what can run NOW."""
    try:
        vid = parse_video_id(selected)
    except ValueError:
        return IngestionPlan("invalid_source", reasons=[f"not a YouTube video link or id: {selected!r}"], options=NO_TRANSCRIPT_OPTIONS[:1])
    plan = IngestionPlan("needs_transcript", video_id=vid, section=section)
    text, kind = None, None
    if transcript_text and transcript_text.strip():
        text, plan.source, kind = transcript_text, "user_transcript", "unknown"
    else:
        cached = read_cached_captions(vid, cache_dir)
        if cached is not None:
            text, plan.source, kind = cached.text, "cached_captions", cached.source
        elif fetch is not None:
            try:
                got = fetch(vid)
                text, plan.source, kind = got.text, "fetched_captions", got.source
            except CaptionsUnavailable as e:
                plan.reasons.append(f"caption retrieval failed: {e}")
    if text is None:
        plan.options = list(NO_TRANSCRIPT_OPTIONS)
        plan.reasons.append("no local transcript for this video; nothing was inferred from its title or metadata")
        return plan
    plan.caption_kind = kind
    try:
        parse_timed_text(text)
    except ValueError as e:
        plan.reasons.append(f"the transcript could not be read: {e}")
        plan.options = list(NO_TRANSCRIPT_OPTIONS[:1])
        return plan
    sec = section or Section()
    if sec.topic and not (sec.start_s or sec.end_s):
        wins = locate_topic(text, sec.topic, chapters=chapters)
        if not wins:
            plan.reasons.append(f"nothing in the transcript mentions {', '.join(sec.topic)}; the whole transcript was not processed")
            plan.options = ["Name a time range (for example 'from 1:20 to 2:40') or pick a different topic."]
            return plan
        sec = Section(wins[0][0], wins[0][1], sec.topic, f"best candidate: {wins[0][2]}")
        others = "; other candidates: " + "; ".join(f"{x:g}-{y:g}s" for x, y, _ in wins[1:]) if len(wins) > 1 else ""
        plan.reasons.append(f"section located automatically ({wins[0][2]}, {wins[0][0]:g}-{wins[0][1]:g}s): please confirm{others}")
        plan.section = sec
    work = slice_timed_text(text, sec.start_s, sec.end_s, duration_s) if (sec.start_s is not None or sec.end_s is not None) else text
    if not work.strip():
        plan.reasons.append("the requested section contains no captions")
        return plan
    title = (entry or {}).get("title")
    res = ingest_transcript(work, duration_s=duration_s or (entry or {}).get("duration_s"), version=version, video_id=vid, title=title)
    hint = (entry or {}).get("blender_version_hint")
    caveats = list(res.limitations)
    if plan.caption_kind == "auto":
        caveats.append("These are automatic captions: wording errors are likely and names of Blender tools may be mis-heard.")
    if hint and version and hint.split(".")[0] != version.split(".")[0]:
        caveats.append(f"The tutorial was recorded for Blender {hint}; you use {version}: menus and shortcuts may differ.")
    if sec.start_s is not None or sec.end_s is not None:
        caveats.append(f"Only the section {sec.start_s or 0:g}s to {('%gs' % sec.end_s) if sec.end_s is not None else 'the end'} was processed ({sec.source or 'requested'}).")
    plan.status = "ready"
    plan.section = sec if not sec.is_empty else None
    located = bool(sec.topic) and not (section and (section.start_s or section.end_s))      # found automatically from a topic: a candidate, not stated
    plan.bundle = AnswerBundle(
        kind="procedure" if res.steplist else "unsupported", route="transcript_parser", steps=res.steplist, explanations=res.explanations, caveats=caveats,
        sources=[SourceRef(kind="tutorial_video", title=title or f"YouTube video {vid}", url=f"https://www.youtube.com/watch?v={vid}", version=hint,
                           verified_on=(entry or {}).get("retrieved"))],
        reasons=[f"selected tutorial {vid}; transcript source: {plan.source}" + (f" ({plan.caption_kind} captions)" if plan.caption_kind else ""),
                 f"transcript parsed offline: {res.stats}"],
        fallback_reason=None if res.steplist else "no instructional operation recognised in the selected portion; a model could read it, none was called",
        source_section=SourceSection(start_s=sec.start_s, end_s=sec.end_s, topic=sec.topic, how_determined=sec.source, confirmed=not located)
        if (sec.start_s is not None or sec.end_s is not None) else None)
    return plan
