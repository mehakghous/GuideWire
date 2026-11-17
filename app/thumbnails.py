"""Video thumbnails for the tutorial suggestions: the small picture YouTube shows beside a video in its own search results.

A thumbnail is a public still image that YouTube serves for exactly this use. It is fetched on demand, held in memory only and never written to disk, so no video, audio or frame is stored (SRS NFR-025). No key is needed.
"""
from __future__ import annotations

import re
import urllib.request

URL = "https://i.ytimg.com/vi/{id}/mqdefault.jpg"            # 320 x 180
_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
MAX_BYTES = 400_000                                           # a thumbnail is a few kilobytes; anything much bigger is not one


def fetch(video_id: str, timeout: float = 4.0) -> bytes | None:
    """The thumbnail's image bytes, or None when there is no connection or no such video. Never raises."""
    if not _ID.match(video_id or ""):
        return None
    try:
        with urllib.request.urlopen(URL.format(id=video_id), timeout=timeout) as r:      # noqa: S310 (a fixed https address)
            data = r.read(MAX_BYTES + 1)
    except Exception:
        return None
    return data if 0 < len(data) <= MAX_BYTES else None


def fetch_all(video_ids: list[str]) -> dict[str, bytes]:
    """Thumbnails for several videos (those that could be fetched), one after the other."""
    out: dict[str, bytes] = {}
    for vid in video_ids:
        data = fetch(vid)
        if data is not None:
            out[vid] = data
    return out
