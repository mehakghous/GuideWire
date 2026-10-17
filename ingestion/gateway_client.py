"""Client side of the AI Gateway (SRS CI-9, PERF-13): one idempotency key per logical request, reused on every retry, so a retried
extraction is never billed twice. Overload (503) is retried with backoff; quota (429) and bad input (4xx) are never retried."""
from __future__ import annotations

import time
import uuid
from typing import Callable

from pydantic import ValidationError

from shared.step_record import StepList

from .providers.base import ProviderError, QuotaError


class GatewayClient:
    def __init__(self, post: Callable, token: str, *, attempts: int = 3, sleep: Callable[[float], None] = time.sleep):
        """post(path, json=, headers=) -> response with .status_code/.json(); httpx.Client(base_url=...).post fits, so does a TestClient."""
        self._post, self._token, self._attempts, self._sleep = post, token, attempts, sleep

    def extract(self, *, video_url: str | None = None, text: str | None = None, **opts) -> StepList:
        key = str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {self._token}", "Idempotency-Key": key}
        body = {"video_url": video_url, "text": text, **opts}
        for n in range(1, self._attempts + 1):
            r = self._post("/v1/extract", json=body, headers=headers)
            if r.status_code == 200:
                try:
                    return StepList.model_validate(r.json())      # the gateway's answer is data: validate it locally (SEC-15)
                except ValidationError as e:
                    raise ProviderError(f"gateway returned an invalid step list: {e}") from e
            if r.status_code == 429:
                raise QuotaError(r.json().get("detail", "quota"))
            if r.status_code != 503:
                raise ProviderError(f"gateway HTTP {r.status_code}: {r.json().get('detail', '')}")
            if n < self._attempts:
                self._sleep(2 ** n)
        raise ProviderError("the AI service is overloaded: paste the written steps instead")
