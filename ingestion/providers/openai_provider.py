"""OpenAI provider: text-only structured answers through the Chat Completions API, behind the same interface as the Gemini provider (providers/base.py), so the cost guard
(ingestion/budget.py: cache, ceilings, log) wraps it unchanged.

Basis (OpenAI documentation read 2026-11-09): `POST https://api.openai.com/v1/chat/completions`; structured outputs are requested with
`response_format = {"type": "json_schema", "json_schema": {"name", "schema", "strict": true}}`; strict mode needs every object to list ALL its properties as required and to set
`additionalProperties: false` (done here by `strict_schema`, the caller's schema is not changed); the response carries `usage.prompt_tokens`, `usage.completion_tokens` (which INCLUDES the hidden
reasoning tokens, and those are billed as output) and `usage.completion_tokens_details.reasoning_tokens`; a refusal comes back as `message.refusal`. Prices are in ingestion/experiment.py PRICES.

Not supported, on purpose: a YouTube URL. OpenAI cannot be given a video link, so `video_url` raises a ProviderError; extraction and the video recheck stay on Gemini.
Errors follow the Gemini provider: 429 raises QuotaError at once; other 4xx raise ProviderError at once; 5xx, 408 and network errors are retried with backoff and end as OverloadError.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import random
import time
from typing import Any

from .base import OverloadError, ProviderError, QuotaError

log = logging.getLogger(__name__)

URL = "https://api.openai.com/v1/chat/completions"
CHEAP_MODEL = "gpt-5.6-luna"        # 0.20 / 1.20 USD per 1M tokens (input / output), after the 30 July 2026 price cut
STRONG_MODEL = "gpt-5.6-terra"      # 2.00 / 12.00


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy of `schema` that satisfies strict structured outputs: every object lists all its properties as required and forbids extras."""
    s = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                props = node.get("properties", {})
                node["properties"] = props
                node["required"] = list(props)
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


class OpenAIProvider:
    def __init__(self, api_key: str | None = None, model: str | None = None, max_attempts: int = 3, timeout_s: float = 120.0, max_output_tokens: int = 4000):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key or not key.strip():
            raise ProviderError("OPENAI_API_KEY is not set (see .env.example)")
        self._secret = key.strip()
        self.model_id = model or os.environ.get("OPENAI_MODEL") or CHEAP_MODEL
        self._max_attempts, self._timeout_s, self._max_output_tokens = max_attempts, timeout_s, max_output_tokens
        self.usage: list[dict[str, int]] = []
        self.events: list[dict[str, Any]] = []
        self.last_raw_text: str | None = None
        self._sleep, self._rand = time.sleep, random.uniform
        import requests                                                # lazy: unit tests inject `_post` and need no network
        self._post = requests.post

    def _redact(self, text: str) -> str:
        return text.replace(self._secret, "[REDACTED]")

    def generate_json(self, *, system: str, prompt: str, schema: dict[str, Any], video_url: str | None = None) -> dict[str, Any]:
        if video_url:
            raise ProviderError("the OpenAI provider cannot be given a video URL; use the Gemini provider for anything that must watch a video")
        body = {"model": self.model_id, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": strict_schema(schema)}},
                "max_completion_tokens": self._max_output_tokens}
        headers = {"Authorization": f"Bearer {self._secret}", "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            t0 = time.time()
            try:
                resp = self._post(URL, headers=headers, json=body, timeout=self._timeout_s)
            except Exception as e:                                         # network error or timeout: retried
                msg = self._redact(str(e))[:300]
                self.events.append({"attempt": attempt, "status": "error", "latency_s": round(time.time() - t0, 2), "error": msg})
                last = OverloadError(msg)
            else:
                code = resp.status_code
                self.events.append({"attempt": attempt, "status": code, "latency_s": round(time.time() - t0, 2)})
                if code == 429:
                    raise QuotaError(f"HTTP 429 (quota/rate limit): {self._redact(resp.text)[:300]}")
                if 400 <= code < 500 and code != 408:
                    raise ProviderError(f"HTTP {code}: {self._redact(resp.text)[:300]}")
                if code >= 500 or code == 408:
                    last = OverloadError(f"HTTP {code}: {self._redact(resp.text)[:200]}")
                else:
                    return self._parse(resp.json())
            log.warning("openai attempt %d/%d failed: %s", attempt, self._max_attempts, str(last)[:120])
            if attempt < self._max_attempts:
                self._sleep(5 * 2 ** (attempt - 1) * self._rand(0.5, 1.5))
        raise OverloadError(f"OpenAI request failed after {self._max_attempts} attempts: {last}")

    def _parse(self, data: dict[str, Any]) -> dict[str, Any]:
        u = data.get("usage") or {}
        reasoning = ((u.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0
        completion = u.get("completion_tokens") or 0
        self.usage.append({"prompt": u.get("prompt_tokens") or 0, "output": max(0, completion - reasoning), "thoughts": reasoning, "total": u.get("total_tokens") or 0})
        msg = ((data.get("choices") or [{}])[0]).get("message") or {}
        if msg.get("refusal"):
            raise ProviderError("the model refused: " + str(msg["refusal"])[:200])
        text = msg.get("content")
        self.last_raw_text = text
        if not text:
            raise ProviderError("empty model response (possibly truncated: the reasoning used the output budget)")
        return json.loads(text)                                            # JSONDecodeError (a ValueError) propagates, as for Gemini
