"""Scripted provider for unit tests ONLY. It returns queued responses; it is not a model."""
from __future__ import annotations

from typing import Any


class ScriptedProvider:
    model_id = "scripted-test-provider"

    def __init__(self, responses: list[dict[str, Any] | Exception], usage_per_call: tuple[int, int] = (18000, 800)):
        self._responses = list(responses)
        self._usage = usage_per_call
        self.calls: list[dict[str, Any]] = []
        self.usage: list[dict[str, int]] = []
        self.events: list[dict[str, Any]] = []
        self.last_raw_text: str | None = None

    def generate_json(self, *, system, prompt, schema, video_url=None):
        self.calls.append(
            {"system": system, "prompt": prompt, "schema": schema, "video_url": video_url}
        )
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of responses")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            self.events.append({"status": getattr(r, "code", "error"), "error": str(r)[:100]})
            raise r
        self.events.append({"status": 200})
        self.usage.append({"prompt": self._usage[0], "output": self._usage[1], "thoughts": 0,
                           "total": sum(self._usage)})
        return r
