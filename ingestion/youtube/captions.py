"""Optional, on-request caption fetch for a public YouTube video (third-party library, undocumented endpoint).

STATUS AND RISK, stated plainly: `youtube-transcript-api` reads captions through the endpoint the YouTube web client uses. It is not
the official Data API, it can stop working at any time, YouTube may block automated access (especially from cloud addresses), and
automated access outside the documented API is against YouTube's terms. The project owner decided to try it (2026-10-11). To keep the
footprint small and honest:
  - nothing in the product calls this automatically: the router never imports it, a caller must ask for a specific video;
  - one list request and one fetch per video, no retries, no proxies, no attempt to get around a block (a block raises CaptionsBlocked);
  - creator-written captions are preferred over auto-generated ones, and the choice is reported;
  - the result is cached locally (git-ignored) and deleted after 30 days, matching the 30-day rule for YouTube-derived data.
The text then goes through the ordinary OFFLINE transcript route: it is narrated evidence only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "local_data" / "captions"
TTL_DAYS = 30


class CaptionsUnavailable(RuntimeError):
    """No usable caption track, or the request failed for a reason other than a block."""


class CaptionsBlocked(CaptionsUnavailable):
    """YouTube refused the automated request (IP or request block). Not retried, and no workaround is attempted."""


@dataclass
class CaptionResult:
    video_id: str
    text: str                      # '00:00:12.340 words' lines, ready for ingestion.transcript_ingest
    source: str                    # 'creator' | 'auto'
    language: str
    fetched_at: str
    from_cache: bool
    tracks: list[tuple[str, bool]] = field(default_factory=list)   # (language, is_generated) of every track offered


def to_timed_text(snippets: list[dict]) -> str:
    out = []
    for s in snippets:
        t = float(s["start"])
        words = " ".join(str(s["text"]).split())
        if words:
            out.append(f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f} {words}")
    return "\n".join(out)


def purge_expired(cache_dir: Path = CACHE_DIR, now: datetime | None = None, ttl_days: int = TTL_DAYS) -> list[str]:
    """Delete cached caption files older than the TTL (by the fetched_at recorded INSIDE the file). Returns the video ids removed."""
    now = now or datetime.now(timezone.utc)
    removed = []
    for f in Path(cache_dir).glob("*.json") if Path(cache_dir).exists() else []:
        try:
            fetched = datetime.fromisoformat(json.loads(f.read_text(encoding="utf-8"))["fetched_at"])
        except Exception:
            fetched = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)      # unreadable record: fall back to file age
        if now - fetched > timedelta(days=ttl_days):
            f.unlink()
            removed.append(f.stem)
    return removed


def _pick(tracks, languages, prefer_creator: bool):
    wanted = [t for t in tracks if t.language_code in languages] or []
    creator = [t for t in wanted if not t.is_generated]
    auto = [t for t in wanted if t.is_generated]
    order = (creator + auto) if prefer_creator else (auto + creator)
    return order[0] if order else None


def fetch_captions(video_id: str, *, api=None, cache_dir: Path = CACHE_DIR, now: datetime | None = None,
                   languages: tuple[str, ...] = ("en",), prefer_creator: bool = True) -> CaptionResult:
    """Captions for ONE video, on request. `api` is injectable for tests; by default the library is imported here, lazily."""
    now = now or datetime.now(timezone.utc)
    purge_expired(cache_dir, now)
    cache = Path(cache_dir) / f"{video_id}.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        return CaptionResult(video_id, to_timed_text(d["snippets"]), d["source"], d["language"], d["fetched_at"], True,
                             [tuple(x) for x in d.get("tracks", [])])
    if api is None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as e:   # pragma: no cover
            raise CaptionsUnavailable("youtube-transcript-api is not installed (pip install youtube-transcript-api)") from e
        api = YouTubeTranscriptApi()
    try:
        listing = list(api.list(video_id))
        tracks = [(t.language_code, bool(t.is_generated)) for t in listing]
        chosen = _pick(listing, languages, prefer_creator)
        if chosen is None:
            raise CaptionsUnavailable(f"no caption track in {languages} for {video_id}; tracks offered: {tracks}")
        snippets = [{"start": s.start, "duration": s.duration, "text": s.text} for s in chosen.fetch()]
    except CaptionsUnavailable:
        raise
    except Exception as e:                                   # the library raises many specific errors; map blocks, report the rest
        name = type(e).__name__
        if "Block" in name or "TooManyRequests" in name:
            raise CaptionsBlocked(f"YouTube refused the request ({name}); not retried and no workaround attempted") from e
        raise CaptionsUnavailable(f"{name}: {str(e)[:200]}") from e
    source = "auto" if chosen.is_generated else "creator"
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"video_id": video_id, "fetched_at": now.isoformat(), "source": source, "language": chosen.language_code,
                                 "tracks": tracks, "snippets": snippets}), encoding="utf-8")
    return CaptionResult(video_id, to_timed_text(snippets), source, chosen.language_code, now.isoformat(), False, tracks)
