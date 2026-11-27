"""Client side of the AI Gateway (SRS CI-9, PERF-13): one idempotency key per logical request, reused on every retry, so a retried
extraction is never billed twice. Overload (503) is retried with backoff; quota (429) and bad input (4xx) are never retried.

The learner's computer holds no provider keys (audit H-2): video reading, answers and YouTube lookups all go through this client."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Callable

from pydantic import ValidationError

from shared.step_record import StepList

from .providers.base import ProviderError, QuotaError

ENV_URL = "GUIDEWIRE_GATEWAY_URL"
ENV_TOKEN = "GUIDEWIRE_GATEWAY_TOKEN"
_UNREACHABLE = "The GuideWire service could not be reached. Check your internet connection and try again."


def _detail(r: Any) -> str:
    try:
        return str(r.json().get("detail", ""))
    except Exception:
        return ""


class GatewayClient:
    def __init__(self, post: Callable, token: str, *, get: Callable | None = None, attempts: int = 3, sleep: Callable[[float], None] = time.sleep):
        """post(path, json=, headers=) -> response with .status_code/.json(); httpx.Client(base_url=...).post fits, so does a TestClient.
        get(path, params=, headers=) is the same for the two read-only YouTube endpoints."""
        self._post, self._get, self._token, self._attempts, self._sleep = post, get, token, attempts, sleep

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, *, timeout_s: float = 240.0) -> "GatewayClient | None":
        """The client for the service named by GUIDEWIRE_GATEWAY_URL and GUIDEWIRE_GATEWAY_TOKEN, or None when either is not set (the app then uses keys on this computer, as in development)."""
        import httpx
        env = os.environ if env is None else env
        url, token = (env.get(ENV_URL) or "").strip().rstrip("/"), (env.get(ENV_TOKEN) or "").strip()
        if not url or not token:
            return None
        http = httpx.Client(base_url=url, timeout=timeout_s)
        return cls(http.post, token, get=http.get)

    def _headers(self, key: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", **({"Idempotency-Key": key} if key else {})}

    def _call(self, send: Callable[[], Any]) -> Any:
        """Send, retrying overload (503). Returns the 200 response; every other outcome is a plain ProviderError or QuotaError (never a raw HTTP or network error)."""
        for n in range(1, self._attempts + 1):
            try:
                r = send()
            except (ProviderError, QuotaError):
                raise
            except Exception as e:                                   # no network, DNS, timeout: the learner needs one sentence, not the class name
                raise ProviderError(_UNREACHABLE) from e
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                raise QuotaError(_detail(r) or "quota")
            if r.status_code in (401, 403):
                raise ProviderError("The GuideWire service did not accept this installation's sign-in. Update GuideWire or sign in again.")
            if r.status_code == 502:                                 # the gateway's own upstream failed: its detail is for the operator's log, not for the learner
                raise ProviderError("The GuideWire service could not look that up right now. Try again in a minute.")
            if r.status_code != 503:
                raise ProviderError(f"gateway HTTP {r.status_code}: {_detail(r)}")
            if n < self._attempts:
                self._sleep(2 ** n)
        raise ProviderError("the AI service is overloaded: paste the written steps instead")

    def extract(self, *, video_url: str | None = None, text: str | None = None, **opts) -> StepList:
        key = str(uuid.uuid4())
        body = {"video_url": video_url, "text": text, **opts}
        r = self._call(lambda: self._post("/v1/extract", json=body, headers=self._headers(key)))
        try:
            return StepList.model_validate(r.json())      # the gateway's answer is data: validate it locally (SEC-15)
        except (ValidationError, ValueError) as e:
            raise ProviderError(f"gateway returned an invalid step list: {e}") from e

    def answer(self, question: str, *, app: str = "blender", model: bool = True, tutorial: dict | None = None, version: str | None = None, history: list[str] | None = None) -> dict:
        """One question answered by the gateway: the AnswerBundle as a dict (validate it with AnswerBundle.model_validate). `tutorial` is the brief step list (see gateway.app.TutorialIn)."""
        body: dict[str, Any] = {"question": question, "app": app, "model": model, "history": history or []}
        if tutorial:
            body["tutorial"] = tutorial
        if version:
            body["version"] = version
        r = self._call(lambda: self._post("/v1/answer", json=body, headers=self._headers()))
        return r.json()

    def metadata(self, video_id: str) -> dict:
        r = self._call(lambda: self._need_get()("/v1/youtube/metadata", params={"video_id": video_id}, headers=self._headers()))
        return r.json()

    def videos(self, ids: list[str]) -> list[dict]:
        """Metadata of up to 50 videos in one call (the shape of ingestion.youtube.api.videos_metadata)."""
        r = self._call(lambda: self._need_get()("/v1/youtube/videos", params={"ids": ",".join(ids[:50])}, headers=self._headers()))
        return list(r.json().get("results", []))

    def search(self, query: str, limit: int = 10) -> list[dict]:
        r = self._call(lambda: self._need_get()("/v1/youtube/search", params={"q": query, "limit": limit}, headers=self._headers()))
        return list(r.json().get("results", []))

    def _need_get(self) -> Callable:
        if self._get is None:
            raise ProviderError("this gateway client was made without a GET function")
        return self._get
