"""Tutorial DISCOVERY over a curated local index, kept separate from understanding a tutorial.

Finding a video is not understanding it: the index holds a title, link, channel, duration, licence, a captions flag and a chapter
count, all read from platform metadata. None of that tells us which actions the video shows, so every recommendation is marked as
not yet convertible to steps without a user-supplied transcript or a video model. If nothing in the index matches the request,
the result is EMPTY with an explicit "needs external search"; an unrelated video is never recommended to fill the list.

Ranking (deterministic): topic-word matches against title and keywords dominate; an official source (the Blender channel) ranks above
a community one; a version hint close to the user's version helps and a far one is penalised and called out; a Creative Commons
licence, available captions and chapters add small bonuses because they make later conversion easier.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shared.answer import TutorialRecommendation

from .catalog import parse_version
from .kb.index import stem, terms

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "knowledge" / "tutorial_index.json"

# request words that describe the REQUEST, not the topic
REQUEST_WORDS = frozenset("""tutorial tutorials course courses lesson lessons guide guides learn learning teach recommend recommendation good best
create creating make making build building walk follow along interactive workflow step steps help find looking
video videos while through me us""".split())
# words too broad to justify a recommendation on their own
GENERIC = frozenset({"model", "modeling", "modelling", "basics", "basic", "blender", "3d", "object", "mesh", "beginner", "beginners"})


def load_index(path: str | Path = DEFAULT_INDEX) -> list[dict]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))["entries"] if p.exists() else []


def topic_terms(query: str) -> list[str]:
    return [t for t in terms(query) if t not in REQUEST_WORDS]


def rank(query: str, entries: list[dict], version: str | None = None, limit: int = 3) -> tuple[list[TutorialRecommendation], list[str]]:
    """(recommendations, topic terms). Empty list when no entry matches the topic."""
    tt = topic_terms(query)
    specific = [t for t in tt if t not in GENERIC]
    uv = parse_version(version)
    out: list[TutorialRecommendation] = []
    for e in entries:
        blob = {stem(w) for w in re.findall(r"[a-z0-9]+", (e["title"] + " " + " ".join(e.get("keywords", []))).lower())}
        matched = [t for t in tt if stem(t) in blob]
        if specific and not [t for t in specific if stem(t) in blob]:
            continue                      # the request names a topic and this entry does not match it
        if not matched:
            continue
        score = 3.0 * len(matched)
        notes: list[str] = []
        if e.get("source_tier") == "official":
            score += 1.0
        hint = parse_version(e.get("blender_version_hint"))
        if hint and uv:
            gap = abs(hint[0] - uv[0]) + abs(hint[1] - uv[1]) / 100.0
            if gap < 0.05:
                score += 1.0
            elif hint[0] != uv[0] or abs(hint[1] - uv[1]) > 20:
                score -= 1.0
                notes.append(f"recorded for Blender {e['blender_version_hint']}, you use {version}: menus and shortcuts may differ")
        elif hint and not uv:
            notes.append(f"recorded for Blender {e['blender_version_hint']}; tell me your version to check compatibility")
        if e.get("licence") == "creativeCommon":
            score += 0.2
        if e.get("captions_flag"):
            score += 0.2
        if e.get("chapters"):
            score += 0.2
        notes.append("Not yet converted: its on-screen actions are unknown until a transcript is supplied or a video model is run.")
        out.append(TutorialRecommendation(
            title=e["title"], url=e["url"], channel=e.get("channel"), source_tier=e.get("source_tier", "unknown"),
            duration_s=e.get("duration_s"), blender_version_hint=e.get("blender_version_hint"), licence=e.get("licence"),
            captions_available=e.get("captions_flag"), chapters=e.get("chapters") or None, matched_terms=matched,
            score=round(score, 2), note=" ".join(notes)))
    out.sort(key=lambda r: (-r.score, r.title))
    return out[:limit], tt


# ---------------------------------------------------------------------------------------------------------------------
# Request understanding and constraint handling (added after probing: "Blender 4.2", "under 15 minutes" and "beginner" were
# silently ignored, and a request with no topic returned an empty "nothing matches" instead of a question).
# Everything here is deterministic and reads only the curated index; it invents no metadata.
# ---------------------------------------------------------------------------------------------------------------------
from dataclasses import dataclass, field

SHORT_DEFAULT_S = 600          # "short" with no number: an assumption, stated to the user every time it is applied
_LEVEL_WORDS = {"beginner": ("beginner", "beginners", "newbie", "new to blender", "never used blender", "first time", "starter"),
                "intermediate": ("intermediate",), "advanced": ("advanced", "expert", "professional")}
_NON_TOPIC = frozenset("""compare compared compatible compatibility few one skill level short quick brief fast under less than within minutes
minute min mins hour hours friendly version for with on about best""".split())
_VER_BLENDER = re.compile(r"\bblender\s*v?(\d{1,2})(?:\.(\d{1,2}|x))?\b", re.I)
_VER_BARE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2}|x)(?![\d])", re.I)
_MAXDUR = re.compile(r"\b(?:under|less than|within|no (?:more|longer) than|at most|max(?:imum)?(?: of)?|up to|below)\s*(\d+(?:\.\d+)?)\s*"
                     r"(hours?|hrs?|h|minutes?|mins?|m)\b", re.I)
_SHORT = re.compile(r"\b(short|quick|brief|fast)\b", re.I)


@dataclass
class Want:
    topic: list[str]
    version: str | None = None            # as the user wrote it: "4.2" or "4.x"
    version_from: str | None = None       # "request" | "argument"
    major: int | None = None
    minor: int | None = None
    level: str | None = None
    max_duration_s: int | None = None
    duration_assumed: bool = False
    needs_topic: bool = False


@dataclass
class Discovery:
    recommendations: list[TutorialRecommendation]
    want: Want
    excluded: list[str] = field(default_factory=list)      # matching tutorials removed by an explicit constraint
    notes: list[str] = field(default_factory=list)          # things the user must know about how the list was built
    comparison: list[str] = field(default_factory=list)


def parse_request(query: str, version: str | None = None) -> Want:
    q = query or ""
    v, src = (version, "argument") if version else (None, None)
    if v is None:
        m = _VER_BLENDER.search(q) or _VER_BARE.search(q)
        if m:
            v, src = f"{m.group(1)}.{m.group(2) or 'x'}", "request"
    major = minor = None
    mm = re.match(r"^(\d+)\.(\d+|x)", v or "", re.I)
    if mm:
        major = int(mm.group(1))
        minor = int(mm.group(2)) if mm.group(2).isdigit() else None
    low = q.lower()
    level = next((lvl for lvl, ws in _LEVEL_WORDS.items() if any(re.search(rf"\b{re.escape(w)}\b", low) for w in ws)), None)
    maxd, assumed = None, False
    md = _MAXDUR.search(q)
    if md:
        n, unit = float(md.group(1)), md.group(2).lower()
        maxd = int(n * (3600 if unit.startswith("h") else 60))
    elif _SHORT.search(q):
        maxd, assumed = SHORT_DEFAULT_S, True
    tt = [t for t in topic_terms(q) if t not in _NON_TOPIC and not t.isdigit() and t != "x"]
    return Want(topic=tt, version=v, version_from=src, major=major, minor=minor, level=level, max_duration_s=maxd,
                duration_assumed=assumed, needs_topic=not tt)


_TITLE_VERSION = re.compile(r"\bblender\s*v?(\d{1,2})(?:\.(\d{1,2}))?(?!\d)(?:\s*\+)?|\b((?:2\.[7-9]\d?|3\.\d|4\.\d|5\.\d))\b", re.I)
_BEGINNER_TITLE = re.compile(r"\b(beginners?|basics?|basic|introduction|intro|getting started|crash course|for dummies|first time|from scratch|fundamentals|101|easy|simple)\b", re.I)
_ADVANCED_TITLE = re.compile(r"\b(advanced|expert|masterclass|master class|pro workflow|in[- ]depth|deep dive|production|professional)\b", re.I)
SHORT_FLOOR_S = 180            # below this a tutorial is a teaser/speed-run: too little to follow step by step (penalised unless the user asked for short)
FOLLOW_ALONG_S = (300, 2400)   # 5 to 40 minutes: the usual length of a follow-along tutorial; used only as a LATE tie-break, never a filter


def version_hint_from_title(title: str | None) -> str | None:
    """A Blender version stated IN THE TITLE: '4.2', '2.8', or just a major ('Blender 3' -> '3.x'). A bare year ('Blender 2026') is not a version.
    None when the title does not say; nothing is inferred from the date or the channel."""
    for m in _TITLE_VERSION.finditer(title or ""):
        if m.group(3):
            return m.group(3)
        major, minor = int(m.group(1)), m.group(2)
        if major > 6 and not minor:
            continue                   # 'Blender 2026'
        return f"{major}.{minor}" if minor else f"{major}.x"
    return None


def level_claim_from_title(title: str | None) -> str | None:
    """What the TITLE claims about its audience ('beginner' / 'advanced'), or None. This is the author's claim, not a verified level."""
    t = title or ""
    adv, beg = bool(_ADVANCED_TITLE.search(t)), bool(_BEGINNER_TITLE.search(t))
    return "advanced" if adv and not beg else "beginner" if beg and not adv else None


def _fmt_min(s: float | None) -> str:
    return "length unknown" if s is None else f"{s / 60:.0f} min" if s >= 60 else f"{s:.0f} s"


def _vparts(hint: str | None) -> tuple[int, int | None] | None:
    m = re.match(r"^(\d+)(?:\.(\d+|x))?", hint or "")
    return (int(m.group(1)), int(m.group(2)) if m.group(2) and m.group(2).isdigit() else None) if m else None


_CAP_RANK = {"creator": 0, "auto": 1, "unknown": 2, "none": 3}
_TIER_RANK = {"official": 0, "community": 1, "unknown": 2}


def discover(query: str, entries: list[dict], version: str | None = None, limit: int = 3) -> Discovery:
    """Rank a tutorial index for a learning request, applying the constraints the request states. Never returns an entry that is not in
    `entries`; says so when a constraint removed matches or could not be checked.

    Ranking (deterministic, every factor is a stored fact or a stated assumption):
      relevance      3 points per topic word found in the title/keywords, +1.5 when ALL topic words are in the title
      version        match with the requested version +1, different major -2, unknown -> neutral and said so
      level          the TITLE's claim ('beginner'/'advanced') against the requested level (+1 match, -1.5 clash); labelled as a title claim
      length         under 3 minutes -1.5 (a teaser cannot teach steps) unless the user asked for something short
      source         official channel +1; Creative Commons +0.2; chapters +0.2
      captions       NOT scored from the platform's flag (it is false for almost every video, including ones with automatic captions).
                     Verified caption tracks (`caption_kind`, from the Data API) add: creator +0.5, automatic +0.3, none -0.5
      ties           more topic coverage, then verified captions, then official, then a 5-40 minute length, then newer, then title
    """
    want = parse_request(query, version)
    if want.needs_topic:
        return Discovery([], want, notes=["The request does not say what to learn."])
    recs, _ = rank(" ".join(want.topic), entries, None, limit=len(entries) or 1)
    by_url = {e["url"]: e for e in entries}
    notes: list[str] = []
    excluded: list[str] = []
    kept: list[tuple[TutorialRecommendation, tuple]] = []
    for r in recs:
        e = by_url[r.url]
        tt_all = [stem(t) for t in want.topic if t not in ("beginner", "beginners")]
        title_words = {stem(w) for w in re.findall(r"[a-z0-9]+", (e["title"] or "").lower())}
        coverage = sum(t in title_words for t in tt_all) / len(tt_all) if tt_all else 0.0
        r.score = round(r.score - (0.2 if e.get("captions_flag") else 0.0) + (1.5 if coverage == 1.0 and tt_all else 0.0), 2)   # undo rank()'s flag bonus
        if want.max_duration_s is not None and e.get("duration_s") is not None and e["duration_s"] > want.max_duration_s:
            excluded.append(f"{r.title} ({_fmt_min(e['duration_s'])})")
            continue
        if want.major is not None:        # the version is known now, so rank()'s "tell me your version" prompt is stale
            r.note = re.sub(r"recorded for Blender [\d.]+; tell me your version to check compatibility\s*", "", r.note).strip()
        extra: list[str] = []
        if want.max_duration_s is not None and e.get("duration_s") is None:
            extra.append("duration unknown, so the time limit could not be checked")
        if e.get("duration_s") is not None and e["duration_s"] < SHORT_FLOOR_S and want.max_duration_s is None:
            r.score = round(r.score - 1.5, 2)
            extra.append(f"only {_fmt_min(e['duration_s'])} long: probably too short to follow step by step")
        hint = e.get("blender_version_hint") or version_hint_from_title(e.get("title"))
        r.blender_version_hint = hint
        hv = _vparts(hint)
        if want.major is not None and hv:
            if hv[0] != want.major:
                r.score = round(r.score - 2.0, 2)
                extra.append(f"recorded for Blender {hint}, you asked for {want.version}: menus, names and shortcuts may differ")
            elif want.minor is not None and hv[1] is not None and hv[1] != want.minor:
                extra.append(f"recorded for Blender {hint}, you use {want.version}: small differences are possible")
            else:
                r.score = round(r.score + 1.0, 2)
        elif want.major is not None:
            when = f" (published {e['published'][:4]})" if e.get("published") else ""
            extra.append(f"its Blender version is not stated{when}, so compatibility is unknown")
        claim = level_claim_from_title(e.get("title"))
        if want.level and claim:
            clash = (want.level == "beginner" and claim == "advanced") or (want.level == "advanced" and claim == "beginner")
            r.score = round(r.score + (-1.5 if clash else 1.0), 2)
            extra.append(f"the title claims '{claim}' (the author's claim, not verified)")
        ck = e.get("caption_kind") or ("creator" if e.get("captions_flag") is True else None)    # flag TRUE = creator captions exist; FALSE says nothing (automatic ones are not counted)
        r.caption_kind = ck
        if ck:
            r.score = round(r.score + {"creator": 0.5, "auto": 0.3, "none": -0.5}.get(ck, 0.0), 2)
            r.captions_available = ck in ("creator", "auto")
        else:
            r.captions_available = None                       # the platform flag is not trusted: unknown until checked
        r.published = e.get("published")
        r.level_claim = claim
        r.note = " ".join(x for x in [r.note, *[x[0].upper() + x[1:] + "." for x in extra]] if x)
        dur = e.get("duration_s")
        fit = 0 if dur is None else 0 if FOLLOW_ALONG_S[0] <= dur <= FOLLOW_ALONG_S[1] else min(abs(dur - FOLLOW_ALONG_S[0]), abs(dur - FOLLOW_ALONG_S[1]))
        key = (-r.score, -coverage, _CAP_RANK.get(ck or "unknown", 2), _TIER_RANK.get(r.source_tier, 2), fit, -int((e.get("published") or "0000")[:4]), r.title)
        kept.append((r, key))
    top = [r for r, _ in sorted(kept, key=lambda t: t[1])][:limit]
    if excluded:
        notes.append(f"Left out because longer than {_fmt_min(want.max_duration_s)}: " + "; ".join(excluded) + ".")
    if want.duration_assumed:
        notes.append(f"'short' was read as {_fmt_min(SHORT_DEFAULT_S)} or less; tell me a limit if you mean something else.")
    if want.level:
        notes.append(f"Skill level '{want.level}' is not recorded for any tutorial; only the wording of a title ('beginner', 'advanced') was used, and it is the author's claim.")
    if top and any(r.caption_kind is None for r in top):
        notes.append("Caption availability has not been checked for these results (the platform's own flag is unreliable); it can be verified for this shortlist through the official API.")
    if top and want.major is not None and all("may differ" in r.note for r in top):
        notes.append(f"None of these was recorded for Blender {want.version}; follow along carefully and expect some differences.")
    comparison: list[str] = []
    if re.search(r"\b(compare|comparison|which (?:one )?is best|best one|recommend)\b", query, re.I) and len(top) >= 2:
        for r in top:
            comparison.append(f"{r.title}: {_fmt_min(r.duration_s)}, "
                              f"{'Blender ' + r.blender_version_hint if r.blender_version_hint else 'version not stated'}, "
                              f"{r.source_tier} source, captions {r.caption_kind or 'not checked'}, matches {', '.join(r.matched_terms) or 'nothing specific'}")
        notes.append("This comparison uses metadata only; which video teaches the technique better has not been judged.")
    return Discovery(top, want, excluded, notes, comparison)


def verify_captions(recs: list[TutorialRecommendation], tracks_for, *, max_checks: int = 3) -> list[str]:
    """Check caption tracks for the top `max_checks` results through `tracks_for(video_id) -> list[{'language','kind'}]` (the official Data API,
    about 50 quota units per call, so only the shortlist is checked). Updates each recommendation and returns a log of what happened.
    A failed check leaves the result 'unknown'; it is never recorded as 'none'."""
    from .youtube.metadata import parse_video_id
    log: list[str] = []
    for r in recs[:max_checks]:
        vid = parse_video_id(r.url)
        try:
            tracks = tracks_for(vid)
        except Exception as e:                                # noqa: BLE001 - any failure means 'unknown', and is reported
            log.append(f"{vid}: caption check failed ({type(e).__name__}); left as unknown")
            continue
        en = [t for t in tracks if (t.get("language") or "").lower().startswith("en")]
        kind = "creator" if any(t["kind"] == "standard" for t in en) else "auto" if any(t["kind"] == "asr" for t in en) else "none"
        if kind == "none" and tracks:
            r.note = (r.note + f" Caption tracks exist only in other languages ({', '.join(sorted({t['language'] for t in tracks}))}).").strip()
        r.caption_kind, r.captions_available = kind, kind in ("creator", "auto")
        r.score = round(r.score + {"creator": 0.5, "auto": 0.3, "none": -0.5}[kind], 2)
        log.append(f"{vid}: {kind} captions ({len(tracks)} track(s))")
    recs.sort(key=lambda r: (-r.score, _CAP_RANK.get(r.caption_kind or "unknown", 2), _TIER_RANK.get(r.source_tier, 2), r.title))
    return log



def playlist_recommendations(items: list[dict], metadata: list[dict], playlist_id: str) -> tuple[list[TutorialRecommendation], list[str]]:
    """Playlist items joined with their verified video metadata, IN PLAYLIST ORDER. Entries the API reported as unavailable, or that videos.list
    did not return, are listed in the second result and never shown as recommendations. Nothing is inferred about what a video teaches."""
    by_id = {m["id"]: m for m in metadata}
    recs, skipped = [], []
    for it in items:
        m = by_id.get(it.get("video_id"))
        if not it.get("available") or m is None:
            skipped.append(f"position {it.get('position')}: {it.get('title') or 'unavailable video'}")
            continue
        recs.append(TutorialRecommendation(
            title=m["title"], url=m["url"], channel=m.get("channel"), source_tier="unknown", duration_s=m.get("duration_s"), blender_version_hint=None,
            licence=m.get("licence"), captions_available=None, chapters=m.get("chapters") or None, matched_terms=[], score=0.0,
            note=f"Item {int(it['position']) + 1 if it.get('position') is not None else '?'} of playlist {playlist_id}. Blender version and level are not recorded. "
                 "Not yet converted: its on-screen actions are unknown until a transcript is supplied or a video model is run."))
    return recs, skipped
