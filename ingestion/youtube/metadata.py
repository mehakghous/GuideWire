"""YouTube URL parsing, chapter parsing and Data API metadata (videos.list, 1 quota unit).

Only metadata is fetched. No media, audio or transcript is ever downloaded or scraped.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url_or_id: str) -> str:
    s = url_or_id.strip()
    if _ID.match(s):
        return s
    u = urlparse(s)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            vid = parse_qs(u.query).get("v", [None])[0]
        else:
            m = re.match(r"^/(?:embed|shorts|live|v)/([^/?]+)", u.path)
            vid = m.group(1) if m else None
    if not vid or not _ID.match(vid):
        raise ValueError(f"Not a recognisable YouTube video URL or id: {url_or_id!r}")
    return vid


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class Chapter:
    start_s: int
    title: str


_CHAPTER = re.compile(r"^\s*[-••]?\s*\(?((?:\d{1,2}:)?\d{1,2}:\d{2})\)?\s*[-–—:|]?\s*(.+?)\s*$")


def _ts_to_s(ts: str) -> int:
    parts = [int(p) for p in ts.split(":")]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def parse_chapters(description: str) -> list[Chapter]:
    """YouTube chapters: description lines 'm:ss Title', first must be 0:00, >=3 entries,
    ascending. Returns [] if the description does not form valid chapters."""
    found = []
    for line in description.splitlines():
        m = _CHAPTER.match(line)
        if m:
            found.append(Chapter(_ts_to_s(m.group(1)), m.group(2)))
    if len(found) < 3 or found[0].start_s != 0:
        return []
    if any(b.start_s <= a.start_s for a, b in zip(found, found[1:])):
        return []
    return found


_ISO = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_iso_duration(d: str) -> int:
    m = _ISO.match(d)
    if not m:
        raise ValueError(f"bad ISO-8601 duration: {d!r}")
    days, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return ((days * 24 + h) * 60 + mi) * 60 + s


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    description: str
    duration_s: int
    embeddable: bool
    privacy_status: str
    license: str
    published_at: str
    chapters: list[Chapter]


def fetch_metadata(video_id: str, api_key: str | None = None) -> VideoMetadata:
    import httpx

    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set (see .env.example)")
    r = httpx.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet,contentDetails,status", "id": video_id},
        headers={"x-goog-api-key": key},  # header, not ?key=, so the secret never lands in URLs/logs
        timeout=20,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise LookupError(f"Video {video_id} not found or not accessible")
    it = items[0]
    sn, cd, st = it["snippet"], it["contentDetails"], it["status"]
    return VideoMetadata(
        video_id=video_id,
        title=sn["title"],
        description=sn.get("description", ""),
        duration_s=parse_iso_duration(cd["duration"]),
        embeddable=bool(st.get("embeddable", False)),
        privacy_status=st.get("privacyStatus", "unknown"),
        license=st.get("license", "unknown"),
        published_at=sn.get("publishedAt", ""),
        chapters=parse_chapters(sn.get("description", "")),
    )
