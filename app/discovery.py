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


@dataclass
class DiscoveryResult:
    suggestions: list[Suggestion] = field(default_factory=list)
    message: str = ""            # what to tell the person: a question, "nothing matched", a warning
    notes: list[str] = field(default_factory=list)
    source: str = ""             # "live" | "saved" | "local" | ""
    app: str | None = None


def _suggestion(rec) -> Suggestion:
    minutes = round(rec.duration_s / 60) if getattr(rec, "duration_s", None) else None
    year = (rec.published or "")[:4]
    summary = " | ".join(x for x in (rec.channel, f"{minutes} min" if minutes else "", year) if x)
    return Suggestion(rec.title, rec.url, rec.channel or "", minutes, float(rec.score or 0.0), summary, rec.note or "", rec.url.rsplit("=", 1)[-1])


def live_functions():
    """(search, metadata) for the YouTube Data API, or None when no key is set."""
    from dotenv import load_dotenv
    load_dotenv()
    if not os.environ.get("YOUTUBE_API_KEY", "").strip():
        return None
    from ingestion.youtube import api
    return (lambda q, n: api.search_videos(q, max_results=n)), api.videos_metadata


def _read_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_tutorials(goal: str, app: str | None = None, *, limit: int = 3, live: bool = True, search=None, metadata=None,
                   cache_path: Path | None = CACHE_PATH, now=time.time) -> DiscoveryResult:
    """Never raises: every problem comes back as a message."""
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
    if not rigging:                                                # not a rigging or animation goal: the small local list
        d = discover_local(goal, load_index(), None, limit=limit)
        sug = [_suggestion(r) for r in d.recommendations]
        return DiscoveryResult(sug, "" if sug else "Nothing in GuideWire's small local list matches that. Try describing a rigging or animation goal.", [*d.notes, CAVEAT], "local", g.app)
    key = hashlib.sha256(f"{goal.lower()}|{g.app}|{limit}".encode()).hexdigest()[:20]
    if cache_path is not None:
        hit = _read_cache(cache_path).get(key)
        if hit and now() - hit["ts"] < CACHE_TTL_S:
            return DiscoveryResult([Suggestion(**s) for s in hit["suggestions"]], hit.get("message", ""), hit.get("notes", []), "saved", g.app)
    funcs = (search, metadata) if (search and metadata) else (live_functions() if live else None)
    notes: list[str] = []
    source = "local"
    rd = None
    if funcs is not None:
        try:
            rd = discover_rigging(goal, app=g.app, limit=limit, search=funcs[0], metadata=funcs[1])
            source = "live"
        except Exception as e:                                      # no quota, no network, a bad key: say so and fall back
            notes.append(f"The live YouTube search is not available right now ({type(e).__name__}); these come from GuideWire's small local list instead.")
    elif live:
        notes.append("No YouTube search key is set on this computer (YOUTUBE_API_KEY in .env), so these come from GuideWire's small local list.")
    if rd is None:
        rd = discover_rigging(goal, app=g.app, limit=limit, local=load_index())
    sug = [_suggestion(r) for r in rd.recommendations]
    notes = [*notes, *rd.notes, CAVEAT]
    msg = "" if sug else "I found no tutorial that matches that well. Try fewer words, or say which part you want to learn (the leg, skinning, IK)."
    if source == "live" and sug and cache_path is not None:
        try:
            cache = _read_cache(cache_path)
            cache[key] = {"ts": now(), "suggestions": [asdict(s) for s in sug], "message": msg, "notes": notes}
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return DiscoveryResult(sug, msg, notes, source, g.app)
