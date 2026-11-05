"""Model-provider interface. All network/LLM access goes through this seam."""
from __future__ import annotations

from typing import Any, Protocol


class ProviderError(RuntimeError):
    """The provider failed (network, quota, refusal, unparseable output)."""


class OverloadError(ProviderError):
    """The provider is out of capacity (HTTP 408/5xx or a network failure) and kept failing after the bounded retries. Retry LATER; nothing was charged and the request itself was fine."""


class QuotaError(ProviderError):
    """HTTP 429: quota or rate limit. Never retried; experiments stop on it."""


class LLMProvider(Protocol):
    model_id: str

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        video_url: str | None = None,
    ) -> dict[str, Any]:
        """Return a JSON object conforming (hopefully) to `schema`.

        `video_url` is a public YouTube URL. Implementations must pass the URL only;
        never download or upload media.
        """
        ...
