"""The app's door to tutorial DISCOVERY: describe what you want to learn, get up to three suggested videos.

No Qt in here, so it is fully testable. It wraps ingestion's finder (the same code as `python -m ingestion.cli find`):
  * a rigging or animation goal, in any application, is searched live on YouTube (two searches, about 200 units of the daily search quota, no money), the videos' metadata is read, and the candidates are
    ranked on how well their title and chapters match the goal, the application and version, the length, how recent they are, and whether they are about an automatic rigging tool (only a small
    penalty, and none for a beginner or quick goal). A video is JUDGED FROM ITS TITLE, CHANNEL AND LENGTH, never from watching it, and every suggestion says so;
  * anything else is looked up in GuideWire's small local list;
  * when the request is too vague (no application named, or the answer would change which tutorial is right) the finder's own question comes back instead of a search;
  * a search is remembered for a day in `local_data/discovery_cache.json`, so asking again costs no quota, and if the live search fails (no key, no quota, no network) the local list is used and
    the person is told.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

APPS = ("blender", "maya", "houdini")
CACHE_PATH = Path(__file__).resolve().parents[1] / "local_data" / "discovery_cache.json"
CACHE_TTL_S = 24 * 3600
CAVEAT = "Judged from the video's title, channel and length: GuideWire has not watched it, so check it fits before you use it."


@dataclass
class Suggestion:
    title: str
    url: str
    channel: str = ""
    minutes: int | None = None
    score: float = 0.0
    summary: str = ""            # one line: channel, length, year
    note: str = ""               # why it was suggested and what to watch out for, in plain words
    video_id: str = ""
    published: str = ""          # the upload date as YouTube gives it (YYYY-MM-DD), or "" when it is not known


@dataclass
class DiscoveryResult:
    suggestions: list[Suggestion] = field(default_factory=list)
    message: str = ""            # what to tell the person: a question, "nothing matched", a warning
    notes: list[str] = field(default_factory=list)
    source: str = ""             # "live" | "saved" | "local" | ""
    app: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "DiscoveryResult":
        """A result saved by `to_json`. Unknown or missing fields are tolerated, so an older saved search still opens."""
        d = json.loads(text)
        known = Suggestion.__dataclass_fields__
        return cls([Suggestion(**{k: v for k, v in s.items() if k in known}) for s in d.get("suggestions", [])], d.get("message", ""), list(d.get("notes", [])), d.get("source", ""), d.get("app"))


_TECHNICAL = re.compile(r"^(?:this matches what|i read this as|the request does not say|uploaded|title/chapters|judged from metadata|not checked against)", re.I)
_AREAS = re.compile(r"areas you need \(([^)]*)\)", re.I)


def friendly_note(note: str) -> str:
    """What a learner wants to know about a suggestion, in plain words: what the video seems to cover. The upload-date arithmetic, the 'judged from metadata' disclaimer and the matching scores that the finder
    writes are for the finder, not for the learner. The sentence the model wrote after watching the first two minutes is the best description there is; without it the title's matched topics are said."""
    note = (note or "").strip()
    if "Checked the first" in note:
        said = note.split("of the video:", 1)[-1].strip()
        shows = re.match(r"it shows (.+?), not (.+?)\.?$", said, re.I)
        return f"This video seems to be about {shows.group(1)}, not {shows.group(2)}." if shows else said
    hit = _AREAS.search(note)
    if hit and hit.group(1).strip().lower() not in ("", "none"):
        return f"From its title, it looks like it covers {hit.group(1).strip()}."
    return "Picked from its title and length."


def friendly_notes(notes: list[str]) -> list[str]:
    """The list-level notes a learner should read (a search that fell back, a video left out, how far to trust the suggestions); not the finder's reasoning about the request."""
    return [n for n in notes if n and not _TECHNICAL.match(n.strip())]


def _suggestion(rec) -> Suggestion:
    minutes = round(rec.duration_s / 60) if getattr(rec, "duration_s", None) else None
    year = (rec.published or "")[:4]
    summary = " | ".join(x for x in (rec.channel, f"{minutes} min" if minutes else "", year) if x)
    from ingestion.rigging_discovery import video_id_of
    return Suggestion(rec.title, rec.url, rec.channel or "", minutes, float(rec.score or 0.0), summary, rec.note or "", video_id_of(rec.url) or rec.url.rsplit("=", 1)[-1], (rec.published or "")[:10])


def live_functions():
    """(search, metadata) for the YouTube Data API, or None when no key is set."""
    from dotenv import load_dotenv
    load_dotenv()
    if not os.environ.get("YOUTUBE_API_KEY", "").strip():
        return None
    from ingestion.youtube import api
    return (lambda q, n: api.search_videos(q, max_results=n)), api.videos_metadata


def _vid(v: str) -> str:
    from ingestion.rigging_discovery import video_id_of
    return video_id_of(v) or (v or "").strip()


def _read_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


_BEGINNER = re.compile(r"\b(beginners?|new to|first time|never (?:rigged|used)|just starting|starting out)\b", re.I)


def default_fit_provider():
    """The model that watches the first two minutes of each top suggestion: Gemini 3.5 Flash-Lite behind the cost guard (about 0.4 cent a clip). Raises when no key is set."""
    from dotenv import load_dotenv

    from ingestion.budget import TIERS, BudgetedProvider, BudgetExceeded, Ceilings, api_key_for
    from ingestion.providers.gemini import GeminiProvider
    load_dotenv()
    try:
        return BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model=TIERS["iterate"]), ceilings=Ceilings.from_env(max_usd_run=0.2), label="default")
    except BudgetExceeded as e:
        raise RuntimeError("no Gemini key") from e


def nothing_found_message(failure: Exception | None = None, no_key: bool = False, dropped: int = 0) -> str:
    """Why the list is empty, in plain words and with what to do. "Nothing matches" is only the answer when a live search worked and found nothing; when the search itself could not run, only GuideWire's
    small built-in list was looked at, and saying "nothing matches that well" would blame the learner's words for a problem that is not theirs."""
    small = "so only GuideWire's small built-in list was searched, and it has nothing for this."
    if failure is not None:
        text = f"{type(failure).__name__} {failure}".lower()
        if "quota" in text or "403" in text or "ratelimit" in text:
            return f"YouTube's daily search limit seems to be used up (it resets every day), {small} Try again tomorrow, or paste a video link into New Tutorial."
        return f"GuideWire could not reach the YouTube search just now ({type(failure).__name__}), {small} Check your internet connection and try again in a moment."
    if no_key:
        return f"No YouTube search key is set on this computer (YOUTUBE_API_KEY in the .env file), {small}"
    if dropped:
        return "Every video I found seemed to show a different application from the one you asked for, so I left them out. Try naming the application, or describe the task another way."
    return "I found no tutorial that matches that well. Try fewer words, or say which part you want to learn (for example the leg, skinning, IK, or the shape you want to make)."


MAX_LIMIT = 20                      # the most tutorials one request returns: two searches of up to 10 results are the pool they come from


def _dedupe(sug: list[Suggestion], exclude: set[str]) -> list[Suggestion]:
    """Each video once (the same video can come from the local list and from the search under two addresses), and none already in `exclude` (ids)."""
    from ingestion.rigging_discovery import video_id_of
    seen, out = set(exclude), []
    for s in sug:
        key = video_id_of(s.url) or s.video_id or s.url
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def find_tutorials(goal: str, app: str | None = None, *, limit: int = 3, live: bool = True, search=None, metadata=None,
                   cache_path: Path | None = CACHE_PATH, now=time.time, fit_provider=None, exclude=()) -> DiscoveryResult:
    """Never raises: every problem comes back as a message. `limit` is at most how many suggestions (up to MAX_LIMIT); fewer come back when fewer are relevant. `exclude`: video ids or links not to suggest again."""
    limit = max(1, min(int(limit or 3), MAX_LIMIT))
    skip = {x for x in (_vid(v) for v in exclude) if x}
    from ingestion.rigging_discovery import discover_rigging, parse_goal
    from ingestion.tutorials import discover as discover_local
    from ingestion.tutorials import load_index
    goal = (goal or "").strip()
    app = app if app in APPS else None
    if not goal:
        return DiscoveryResult(message="Describe what you want to learn, for example: I am a beginner and want to rig a leg with IK in Maya.")
    try:
        g = parse_goal(goal, app)
    except Exception as e:
        return DiscoveryResult(message=f"I could not read that request ({type(e).__name__}). Try rewording it.")
    if g.needs_app:
        return DiscoveryResult(message="Which application do you use: Blender, Maya or Houdini? Tutorials differ completely between them. Pick one, or name it in your request.")
    if g.clarification:
        return DiscoveryResult(message=g.clarification, app=g.app)
    rigging = g.app in ("maya", "houdini") or bool(g.stages)
    if not rigging:                                                # not a rigging or animation goal: the small local list first
        d = discover_local(goal, load_index(), None, limit=limit + len(skip))
        sug = _dedupe([_suggestion(r) for r in d.recommendations], skip)[:limit]
        if sug:
            return DiscoveryResult(sug, "", [*d.notes, CAVEAT], "local", g.app)
        # nothing in the local list: do not stop with "nothing matches"; search YouTube for it like any other goal (below)
    key = hashlib.sha256(f"{goal.lower()}|{g.app}|{limit}|{','.join(sorted(skip))}".encode()).hexdigest()[:20]
    if cache_path is not None:
        hit = _read_cache(cache_path).get(key)
        if hit and now() - hit["ts"] < CACHE_TTL_S:
            return DiscoveryResult([Suggestion(**s) for s in hit["suggestions"]], hit.get("message", ""), hit.get("notes", []), "saved", g.app)
    funcs = (search, metadata) if (search and metadata) else (live_functions() if live else None)
    notes: list[str] = []
    source = "local"
    rd = None
    failure: Exception | None = None                                 # why the live search could not be used, kept so an empty result can SAY why
    no_key = False
    dropped = 0
    if funcs is not None:
        try:
            rd = discover_rigging(goal, app=g.app, limit=limit, search=funcs[0], metadata=funcs[1], exclude=skip)
            source = "live"
        except Exception as e:                                      # no quota, no network, a bad key: say so and fall back
            failure = e
            notes.append(f"The live YouTube search is not available right now ({type(e).__name__}); these come from GuideWire's small local list instead.")
    elif live:
        no_key = True
        notes.append("No YouTube search key is set on this computer (YOUTUBE_API_KEY in .env), so these come from GuideWire's small local list.")
    if rd is None:
        rd = discover_rigging(goal, app=g.app, limit=limit, local=load_index(), exclude=skip)
    recs, caveat = rd.recommendations, CAVEAT
    if source == "live" and fit_provider is not None and recs:                  # D2: a model watches the first two minutes of each suggestion
        try:
            from ingestion.fit_check import apply_fit_checks
            before = len(recs)
            provider = fit_provider() if callable(fit_provider) and not hasattr(fit_provider, "generate_json") else fit_provider
            recs, _fits = apply_fit_checks(recs, provider, goal, g.app, "beginner" if _BEGINNER.search(goal) else None, drop_wrong_app=True)
            if len(recs) < before:
                dropped = before - len(recs)
                notes.append(f"{dropped} suggestion(s) were left out because the video itself shows a different application.")
            caveat = "Each suggestion was also checked against the first two minutes of its video (not the whole video), so check it fits before you use it."
        except Exception as e:                                                  # no key, no budget, no network: keep the title-only ranking and say so
            notes.append(f"The check against the videos themselves was not possible ({type(e).__name__}); these are ranked from titles only.")
    sug = _dedupe([_suggestion(r) for r in recs], skip)[:limit]
    notes = [*notes, *rd.notes, caveat]
    msg = "" if sug else nothing_found_message(failure, no_key, dropped)
    if source == "live" and sug and cache_path is not None:
        try:
            cache = _read_cache(cache_path)
            cache[key] = {"ts": now(), "suggestions": [asdict(s) for s in sug], "message": msg, "notes": notes}
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return DiscoveryResult(sug, msg, notes, source, g.app)
