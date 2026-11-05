"""Official YouTube Data API v3 helpers for tutorial discovery: playlist expansion, batch video metadata, search.

Only documented endpoints, metadata only (no media, no captions). One HTTP request per call, NO retries (a failure is raised, not repeated).
The key travels in a header, never in a URL, and is never written to any result. `get` is injectable so tests never touch the network.
Quota (per the Data API documentation as I recall it; verify against the Google console before relying on the numbers):
  playlistItems.list 1 unit per page of up to 50 videos; videos.list 1 unit per call of up to 50 ids; search.list about 100 units per call.
Every function returns plain dicts of what the API said. Nothing is invented, and fields the API omits stay None.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from .metadata import parse_chapters, parse_iso_duration

BASE = "https://www.googleapis.com/youtube/v3/"
QUOTA_UNITS = {"playlistItems": 1, "videos": 1, "search": 100, "captions": 50}
Get = Callable[[str, dict, dict], Any]      # (url, params, headers) -> parsed JSON; raises on HTTP errors


class YouTubeApiError(RuntimeError):
    """Any failure of a Data API call, with the key redacted. Never retried by this module."""


def _default_get(url: str, params: dict, headers: dict) -> Any:       # pragma: no cover - the real network path
    import httpx
    r = httpx.get(url, params=params, headers=headers, timeout=20)
    if r.status_code != 200:
        msg = r.text[:300].replace(headers.get("x-goog-api-key", "\0"), "[key]")
        raise YouTubeApiError(f"HTTP {r.status_code}: {msg}")
    return r.json()


def _call(endpoint: str, params: dict, api_key: str | None, get: Get | None) -> Any:
    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise YouTubeApiError("YOUTUBE_API_KEY is not set (see .env.example)")
    try:
        return (get or _default_get)(BASE + endpoint, params, {"x-goog-api-key": key})
    except YouTubeApiError:
        raise
    except Exception as e:
        raise YouTubeApiError(f"{type(e).__name__}: {str(e).replace(key, '[key]')[:300]}") from e


def playlist_items(playlist_id: str, *, api_key: str | None = None, get: Get | None = None, max_items: int = 50) -> list[dict]:
    """The videos of one playlist, in playlist order (first page only: at most 50). Unavailable (deleted/private) entries are reported, not dropped."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", playlist_id or ""):
        raise YouTubeApiError(f"not a playlist id: {playlist_id!r}")
    data = _call("playlistItems", {"part": "snippet,contentDetails,status", "playlistId": playlist_id, "maxResults": min(max_items, 50)}, api_key, get)
    out = []
    for it in data.get("items", []):
        sn, cd = it.get("snippet", {}), it.get("contentDetails", {})
        vid = cd.get("videoId") or sn.get("resourceId", {}).get("videoId")
        title = sn.get("title")
        out.append({"video_id": vid, "title": title, "position": sn.get("position"), "channel": sn.get("videoOwnerChannelTitle") or sn.get("channelTitle"),
                    "available": bool(vid) and title not in ("Deleted video", "Private video") and it.get("status", {}).get("privacyStatus", "public") == "public"})
    return out


def videos_metadata(ids: list[str], *, api_key: str | None = None, get: Get | None = None) -> list[dict]:
    """Metadata of up to 50 videos in ONE call. Missing ids (private, deleted, region-blocked) are simply absent from the result."""
    ids = [i for i in dict.fromkeys(ids) if i][:50]
    if not ids:
        return []
    data = _call("videos", {"part": "snippet,contentDetails,status", "id": ",".join(ids), "maxResults": 50}, api_key, get)
    out = []
    for it in data.get("items", []):
        sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("status", {})
        try:
            dur = parse_iso_duration(cd["duration"]) if cd.get("duration") else None
        except ValueError:
            dur = None
        from ..tutorials import version_hint_from_title        # lazy: tutorials does not import this module
        out.append({"version_in_description": version_hint_from_title((sn.get("description") or "")[:600]), "id": it["id"], "url": f"https://www.youtube.com/watch?v={it['id']}", "title": sn.get("title"), "channel": sn.get("channelTitle"),
                    "duration_s": dur, "licence": st.get("license"), "captions_flag": (cd.get("caption") == "true") if cd.get("caption") is not None else None,
                    "chapters": len(parse_chapters(sn.get("description", ""))), "chapter_titles": [c.title for c in parse_chapters(sn.get("description", ""))], "description_head": (sn.get("description") or "")[:600], "published": (sn.get("publishedAt") or "")[:10] or None,
                    "embeddable": st.get("embeddable"), "privacy": st.get("privacyStatus")})
    return out


def search_videos(query: str, *, api_key: str | None = None, get: Get | None = None, max_results: int = 10) -> list[dict]:
    """Video search (about 100 quota units per call). Returns id/title/channel only: a search hit is a CANDIDATE, to be verified with videos_metadata."""
    data = _call("search", {"part": "snippet", "q": query, "type": "video", "maxResults": min(max_results, 50), "videoEmbeddable": "true", "relevanceLanguage": "en", "safeSearch": "strict"}, api_key, get)
    return [{"video_id": it.get("id", {}).get("videoId"), "title": it.get("snippet", {}).get("title"), "channel": it.get("snippet", {}).get("channelTitle")}
            for it in data.get("items", []) if it.get("id", {}).get("videoId")]


def caption_tracks(video_id: str, *, api_key: str | None = None, get: Get | None = None) -> list[dict]:
    """Caption TRACKS of one public video through captions.list with a plain API key (verified live 2026-10-11 on a video whose contentDetails.caption flag
    said false: it returned an automatic English track). Track kinds: 'standard' = uploaded by the creator, 'asr' = automatic, 'forced'. About 50 quota
    units per call. This lists tracks only; downloading caption TEXT is not possible with an API key and is not attempted here."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise YouTubeApiError(f"not a video id: {video_id!r}")
    data = _call("captions", {"part": "snippet", "videoId": video_id}, api_key, get)
    return [{"language": it.get("snippet", {}).get("language"), "kind": it.get("snippet", {}).get("trackKind"), "name": it.get("snippet", {}).get("name") or None,
             "last_updated": (it.get("snippet", {}).get("lastUpdated") or "")[:10] or None} for it in data.get("items", [])]
