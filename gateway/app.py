"""AI Gateway (SRS SI-14, Table 3.5): the only place that holds provider keys and calls the AI and YouTube APIs.

Per request it checks the bearer token, rate-limits per user, caps paid calls per user per day, limits body size, accepts only JSON with
YouTube-pattern URLs or text (no media), and replays the stored answer for a repeated Idempotency-Key so a client retry is never billed twice.
Stateless in spirit but the counters below live in this process.
shortcut: counters, tokens and the idempotency store are in memory (one worker), swap for Redis and Supabase JWT checks before running more than one worker.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ingestion.starter_plan import starter_bundle
from ingestion.answer_model import ModelAnswerer, changes_progress, default_manual, session_from_tutorial
from ingestion.budget import BudgetedProvider, BudgetExceeded
from ingestion.extract import ExtractionError, default_prompt_version, extract_from_text, extract_from_video, recommended_video_prompt_version
from ingestion.followup import respond
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


class TutorialStepIn(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    goal: str = Field(min_length=1, max_length=300)
    start_s: float | None = Field(default=None, ge=0)
    how_to: list[str] = Field(default_factory=list, max_length=3)


class TutorialIn(BaseModel):
    """The tutorial the learner is following, as the client holds it (the gateway keeps no session). Brief on purpose: the request body is limited to 64 KB."""
    title: str | None = Field(default=None, max_length=200)
    app_version: str | None = Field(default=None, max_length=40)
    video_url: str | None = Field(default=None, max_length=200)           # the tutorial's public YouTube URL: lets the answer model look at a short clip when the steps cannot answer
    steps: list[TutorialStepIn] = Field(max_length=120)
    current: str | None = Field(default=None, max_length=20)


class AnswerIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    version: str | None = Field(default=None, max_length=20)
    app: str = "blender"
    model: bool = False                                                       # True: answer with the model, grounded on the knowledge base (one paid call)
    tutorial: TutorialIn | None = None                                        # only used with model=True, or for a session question such as "what is next"
    history: list[str] = Field(default_factory=list, max_length=3)           # the learner's last messages, oldest first


def tokens_from_env() -> dict[str, str]:
    """GATEWAY_TOKENS='tokenA:userA,tokenB:userB'"""
    return dict(p.split(":", 1) for p in os.environ.get("GATEWAY_TOKENS", "").split(",") if ":" in p)


def create_app(*, provider_factory: Callable, tokens: dict[str, str] | None = None, yt_get=None, metadata_fetch: Callable = fetch_metadata, now: Callable[[], float] = time.time,
               rate_per_min: int = 30, paid_per_day: int = 200, max_extractions: int = 4) -> FastAPI:
    app = FastAPI(title="GuideWire AI Gateway")
    tokens = tokens_from_env() if tokens is None else tokens
    recent: dict[str, deque] = defaultdict(deque)           # user -> request times in the last minute
    paid: dict[tuple[str, int], int] = defaultdict(int)     # (user, day) -> paid calls
    searches: dict[int, int] = defaultdict(int)             # day -> YouTube searches, all users share the API quota
    idem: dict[tuple[str, str], tuple[float, str, dict]] = {}   # (user, key) -> (time, request fingerprint, answer)
    key_locks: dict[tuple[str, str], threading.Lock] = {}      # shortcut: a lock whose request failed stays until restart, a few bytes per key
    guard = threading.Lock()
    slots = threading.BoundedSemaphore(max_extractions)         # slow provider calls must not use up every worker thread

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

    def lock_for(uid: str, key: str | None) -> threading.Lock:
        if not key or len(key) > 128:
            raise HTTPException(400, "Idempotency-Key header is required (1 to 128 characters)")
        with guard:
            for k, (t, _, _) in list(idem.items()):
                if now() - t > IDEM_TTL_S:
                    del idem[k]
                    key_locks.pop(k, None)
            return key_locks.setdefault((uid, key), threading.Lock())

    def provider_call(fn):
        try:
            return fn()
        except BudgetExceeded as e:                           # the cost guard stopped the call before anything was sent
            raise HTTPException(503, f"cost guard: {e}")
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
        lock = lock_for(uid, idempotency_key)
        fp = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        with lock:                                           # a second identical request waits here, then replays instead of paying again
            hit = idem.get((uid, idempotency_key))
            if hit:
                if hit[1] != fp:
                    raise HTTPException(409, "this Idempotency-Key was already used for a different request")
                return hit[2]
            vid = None
            if body.video_url:
                try:
                    vid = parse_video_id(body.video_url)     # rejects anything that is not a YouTube video URL
                except ValueError as e:
                    raise HTTPException(422, str(e))
            if not slots.acquire(blocking=False):
                raise HTTPException(503, "gateway is busy, retry shortly")
            try:
                charge(uid)
                provider = provider_factory()
                if hasattr(provider, "video_seconds"):
                    provider.video_seconds = body.duration_s
                sl = provider_call(lambda: extract_from_video(provider, vid, app=body.app, duration_s=body.duration_s, title_hint=body.title_hint,
                                                      prompt_version=recommended_video_prompt_version(body.app))
                                   if vid else extract_from_text(provider, body.text, app=body.app, prompt_version=default_prompt_version(body.app)))
            finally:
                slots.release()
            out = sl.model_dump(mode="json")
            idem[(uid, idempotency_key)] = (now(), fp, out)
            return out

    @app.post("/v1/answer")
    def answer(body: AnswerIn, uid: str = Depends(user)):
        # default: offline knowledge-base route, no paid call; documentation text is never stored (SEC-10).
        # model=true: one paid call to the model (cost guard, daily cap), with the knowledge base, the manual index and the tutorial as context. Questions that change or read the
        # learner's progress (done, skip, go back, next, a timestamp) stay rule-based: the model never moves the learner, and the gateway keeps no session.
        try:
            if not (body.tutorial and body.tutorial.steps):                      # "where do I start": a starter step list from the knowledge base, no model call and no charge
                plan = starter_bundle(body.question, body.app)
                if plan is not None:
                    return plan.model_dump(mode="json")
            if body.model:
                sess = session_from_tutorial(body.app, [s.model_dump() for s in body.tutorial.steps] if body.tutorial else [], title=body.tutorial.title if body.tutorial else None,
                                             app_version=body.tutorial.app_version if body.tutorial else None, current=body.tutorial.current if body.tutorial else None, video_url=body.tutorial.video_url if body.tutorial else None,
                                             history=[h[:300] for h in body.history])
                sess.version = body.version
                if changes_progress(body.question, sess):
                    return respond(sess, body.question).bundle.model_dump(mode="json")
                if not slots.acquire(blocking=False):
                    raise HTTPException(503, "gateway is busy, retry shortly")
                try:
                    charge(uid)
                    answerer = ModelAnswerer(provider_factory(), manual=default_manual(), recheck=bool(body.tutorial and body.tutorial.video_url))
                    return provider_call(lambda: answerer(body.question, sess)).model_dump(mode="json")
                finally:
                    slots.release()
            return route(body.question, version=body.version, app=body.app).model_dump(mode="json")
        except ValueError as e:                              # JSON-looking text that is not a valid step list (JSONDecodeError and pydantic errors are ValueErrors)
            raise HTTPException(422, str(e).splitlines()[0][:200])

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
    # every request goes through the cost guard: content-hash cache, per-run and per-day dollar ceilings, cost log (ingestion/budget.py)
    uvicorn.run(create_app(provider_factory=lambda: BudgetedProvider(GeminiProvider(), label="default")), host="127.0.0.1", port=8080)
