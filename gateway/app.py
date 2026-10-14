"""AI Gateway (SRS SI-14, Table 3.5): the only place that holds provider keys and calls the AI and YouTube APIs.

Per request it checks the bearer token, rate-limits per user, caps paid calls per user per day, limits body size, accepts only JSON with
YouTube-pattern URLs or text (no media), and replays the stored answer for a repeated Idempotency-Key so a client retry is never billed twice.
Stateless in spirit but the counters below live in this process.
shortcut: counters, tokens and the idempotency store are in memory (one worker), swap for Redis and Supabase JWT checks before running more than one worker.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ingestion.extract import ExtractionError, extract_from_text, extract_from_video
from ingestion.providers.base import ProviderError, QuotaError
from ingestion.router import route
from ingestion.youtube import api as yt_api
from ingestion.youtube.metadata import fetch_metadata, parse_video_id

MAX_BODY = 64_000                  # text and URLs only; a frame endpoint (/v1/ground) will raise this for single images
MAX_TEXT = 20_000
IDEM_TTL_S = 3600
YT_SEARCH_PER_DAY = 100            # search.list quota limit (SRS SI-5)


class ExtractIn(BaseModel):
    video_url: str | None = Field(default=None, max_length=300)
    text: str | None = Field(default=None, max_length=MAX_TEXT)
    app: str = "blender"
    duration_s: float | None = Field(default=None, ge=0)
    title_hint: str | None = Field(default=None, max_length=200)


class AnswerIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    version: str | None = Field(default=None, max_length=20)


def tokens_from_env() -> dict[str, str]:
    """GATEWAY_TOKENS='tokenA:userA,tokenB:userB'"""
    return dict(p.split(":", 1) for p in os.environ.get("GATEWAY_TOKENS", "").split(",") if ":" in p)


def create_app(*, provider_factory: Callable, tokens: dict[str, str] | None = None, yt_get=None, metadata_fetch: Callable = fetch_metadata, now: Callable[[], float] = time.time,
               rate_per_min: int = 30, paid_per_day: int = 200) -> FastAPI:
    app = FastAPI(title="GuideWire AI Gateway")
    tokens = tokens_from_env() if tokens is None else tokens
    recent: dict[str, deque] = defaultdict(deque)           # user -> request times in the last minute
    paid: dict[tuple[str, int], int] = defaultdict(int)     # (user, day) -> paid calls
    searches: dict[int, int] = defaultdict(int)             # day -> YouTube searches, all users share the API quota
    idem: dict[tuple[str, str], tuple[float, dict]] = {}

    def user(authorization: str | None = Header(default=None)) -> str:
        uid = tokens.get((authorization or "").removeprefix("Bearer ").strip())
        if not uid:
            raise HTTPException(401, "missing or invalid token")
        t = now()
        q = recent[uid]
        while q and t - q[0] > 60:
            q.popleft()
        if len(q) >= rate_per_min:
            raise HTTPException(429, "rate limit: too many requests, slow down")
        q.append(t)
        return uid

    @app.middleware("http")
    async def small_json_only(request: Request, call_next):
        if request.method == "POST":
            if not request.headers.get("content-type", "").startswith("application/json"):
                return _err(415, "only application/json is accepted (no media)")
            if int(request.headers.get("content-length") or 0) > MAX_BODY:
                return _err(413, "request too large")
        return await call_next(request)

    def charge(uid: str) -> None:
        day = int(now() // 86400)
        if paid[(uid, day)] >= paid_per_day:
            raise HTTPException(429, "daily limit reached for this account")
        paid[(uid, day)] += 1

    def replay(uid: str, key: str | None) -> dict | None:
        if not key:
            raise HTTPException(400, "Idempotency-Key header is required")
        for k, (t, _) in list(idem.items()):
            if now() - t > IDEM_TTL_S:
                del idem[k]
        hit = idem.get((uid, key))
        return hit[1] if hit else None

    def provider_call(fn):
        try:
            return fn()
        except QuotaError as e:                              # never retried (SRS CI-9)
            raise HTTPException(429, f"AI quota exhausted: {e}")
        except ProviderError as e:
            raise HTTPException(503, f"AI service failed: {e}")
        except ExtractionError as e:                         # a provider failure is retryable (503); unusable model output is not
            raise HTTPException(503 if isinstance(e.__cause__, ProviderError) else 422, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post("/v1/extract")
    def extract(body: ExtractIn, uid: str = Depends(user), idempotency_key: str | None = Header(default=None)):
        if bool(body.video_url) == bool(body.text):
            raise HTTPException(422, "send exactly one of video_url or text")
        done = replay(uid, idempotency_key)
        if done:
            return done
        vid = None
        if body.video_url:
            try:
                vid = parse_video_id(body.video_url)         # rejects anything that is not a YouTube video URL
            except ValueError as e:
                raise HTTPException(422, str(e))
        charge(uid)
        provider = provider_factory()
        sl = provider_call(lambda: extract_from_video(provider, vid, app=body.app, duration_s=body.duration_s, title_hint=body.title_hint)
                           if vid else extract_from_text(provider, body.text, app=body.app))
        out = sl.model_dump(mode="json")
        idem[(uid, idempotency_key)] = (now(), out)
        return out

    @app.post("/v1/answer")
    def answer(body: AnswerIn, uid: str = Depends(user)):
        # offline knowledge-base route, no paid call; documentation text is never stored (SEC-10)
        return route(body.question, version=body.version).model_dump(mode="json")

    @app.get("/v1/youtube/metadata")
    def metadata(video_id: str, uid: str = Depends(user)):
        try:
            vid = parse_video_id(video_id)
        except ValueError as e:
            raise HTTPException(422, str(e))
        try:
            m = metadata_fetch(vid)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except Exception as e:                               # network, quota or missing key: never leak the key, say only that it failed
            raise HTTPException(502, f"YouTube metadata failed: {type(e).__name__}")
        d = asdict(m)
        return {k: d[k] for k in ("video_id", "title", "duration_s", "chapters", "license", "embeddable")}

    @app.get("/v1/youtube/search")
    def search(q: str, limit: int = 10, uid: str = Depends(user)):
        if not q.strip() or len(q) > 200:
            raise HTTPException(422, "query must be 1 to 200 characters")
        day = int(now() // 86400)
        if searches[day] >= YT_SEARCH_PER_DAY:
            raise HTTPException(429, "YouTube search quota for today is used up")
        searches[day] += 1
        try:
            return {"results": yt_api.search_videos(q, get=yt_get, max_results=max(1, min(limit, 10)))}
        except yt_api.YouTubeApiError as e:
            raise HTTPException(502, str(e))

    return app


def _err(code: int, msg: str):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": msg}, status_code=code)


def main() -> None:                                          # pragma: no cover
    import uvicorn
    from ingestion.providers.gemini import GeminiProvider
    uvicorn.run(create_app(provider_factory=GeminiProvider), host="127.0.0.1", port=8080)
