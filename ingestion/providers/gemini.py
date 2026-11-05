"""Gemini provider (google-genai SDK).

Verified live on 2026-10-10: text and public-YouTube-URL requests work with `gemini-3.6-flash` and
`gemini-3.5-flash-lite` on a free-tier key. Behaviour notes:
- 429 (quota) and other 4xx errors are raised immediately, never retried.
- 5xx / 408 / network errors are retried with backoff (503 "high demand" was common on larger models).
- Invalid or truncated JSON is NOT retried here: it propagates as a ValueError so the extraction layer can
  retry once with the error message, and every attempt is counted.
- Every HTTP attempt is recorded in `self.events`; token usage of every response in `self.usage`.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any

from .base import OverloadError, ProviderError, QuotaError

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.6-flash"  # 2.5-flash is closed to new keys (404, verified 2026-10-10)


class GeminiProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        media_resolution: str | None = None,  # e.g. "MEDIA_RESOLUTION_HIGH"; None = API default
        max_attempts: int = 3,
        timeout_s: float = 300.0,
        max_output_tokens: int | None = None,
    ):
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set (see .env.example)")
        from google import genai  # lazy: keeps unit tests free of the SDK
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000))
        )
        self.model_id = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self._media_resolution = media_resolution
        self._max_attempts = max_attempts
        self._max_output_tokens = max_output_tokens
        self.usage: list[dict[str, int]] = []   # per response: prompt/output/total tokens
        self.events: list[dict[str, Any]] = []  # per HTTP attempt: status, latency, error text
        self.last_raw_text: str | None = None
        self._secret = key
        self._sleep, self._rand = time.sleep, random.uniform          # injectable, so retry timing is testable

    def _redact(self, text: str) -> str:
        return text.replace(self._secret, "[REDACTED]")

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        video_url: str | None = None,
    ) -> dict[str, Any]:
        t = self._types
        parts = []
        if video_url:
            parts.append(t.Part(file_data=t.FileData(file_uri=video_url)))
        parts.append(t.Part(text=prompt))
        cfg_kwargs: dict[str, Any] = dict(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.2,
        )
        if self._media_resolution:
            cfg_kwargs["media_resolution"] = self._media_resolution
        if self._max_output_tokens:
            cfg_kwargs["max_output_tokens"] = self._max_output_tokens
        config = t.GenerateContentConfig(**cfg_kwargs)

        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            t0 = time.time()
            try:
                resp = self._client.models.generate_content(
                    model=self.model_id,
                    contents=[t.Content(role="user", parts=parts)],
                    config=config,
                )
            except Exception as e:  # SDK raises APIError subclasses carrying .code
                code = getattr(e, "code", None)
                msg = self._redact(str(e))[:300]
                self.events.append({"attempt": attempt, "status": code or "error",
                                    "latency_s": round(time.time() - t0, 2), "error": msg})
                if code == 429:
                    raise QuotaError(f"HTTP 429 (quota/rate limit): {msg}") from e
                if isinstance(code, int) and 400 <= code < 500 and code != 408:
                    raise ProviderError(f"HTTP {code}: {msg}") from e
                last = OverloadError(msg)
                log.warning("gemini attempt %d/%d failed: %s", attempt, self._max_attempts, msg[:120])
                if attempt < self._max_attempts:
                    self._sleep(5 * 2 ** (attempt - 1) * self._rand(0.5, 1.5))        # exponential backoff with jitter, bounded by max_attempts
                continue
            self.events.append({"attempt": attempt, "status": 200, "latency_s": round(time.time() - t0, 2)})        # also copied into the run log by extract._run
            um = getattr(resp, "usage_metadata", None)
            if um is not None:
                self.usage.append({
                    "prompt": um.prompt_token_count or 0,
                    "output": um.candidates_token_count or 0,
                    "thoughts": getattr(um, "thoughts_token_count", None) or 0,
                    "total": um.total_token_count or 0,
                })
            self.last_raw_text = resp.text
            if not resp.text:
                raise ProviderError("empty model response (possibly blocked or truncated)")
            return json.loads(resp.text)  # JSONDecodeError (a ValueError) propagates to the caller
        raise OverloadError(f"Gemini request failed after {self._max_attempts} attempts: {last}")
