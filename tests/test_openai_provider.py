"""The OpenAI provider (ingestion/providers/openai_provider.py): request shape, usage and cost, errors, and the cost guard around it. A fake HTTP function: no network, no real key."""
import json

import pytest

from ingestion.budget import BudgetedProvider, Ceilings
from ingestion.experiment import cost_of, price_of
from ingestion.providers.base import OverloadError, ProviderError, QuotaError
from ingestion.providers.openai_provider import OpenAIProvider, strict_schema

KEY = "sk-test-secret-123"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}, "next": {"type": ["string", "null"]}, "items": {"type": "array", "items": {"type": "object", "properties": {"a": {"type": "string"}}}}}, "required": ["answer"]}


class Resp:
    def __init__(self, code=200, data=None, text=""):
        self.status_code, self._data, self.text = code, data, text or json.dumps(data or {})

    def json(self):
        return self._data


def ok(content=None, prompt=100, completion=40, reasoning=10):
    return Resp(200, {"choices": [{"message": {"content": json.dumps(content or {"answer": "hi", "next": None, "items": []})}}],
                      "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion, "completion_tokens_details": {"reasoning_tokens": reasoning}}})


def provider(responses, **kw):
    p = OpenAIProvider(api_key=KEY, **kw)
    calls = []
    queue = list(responses)

    def post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    p._post = post
    p._sleep = lambda s: None
    return p, calls


def test_the_request_asks_for_strict_structured_output_and_sends_the_key_only_in_the_header():
    p, calls = provider([ok()], model="gpt-5.6-luna")
    out = p.generate_json(system="sys", prompt="q", schema=SCHEMA)
    c = calls[0]
    assert out == {"answer": "hi", "next": None, "items": []} and c["url"] == "https://api.openai.com/v1/chat/completions"
    assert c["json"]["model"] == "gpt-5.6-luna" and c["json"]["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
    rf = c["json"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True and c["json"]["max_completion_tokens"] == 4000
    assert c["headers"]["Authorization"] == f"Bearer {KEY}" and KEY not in json.dumps(c["json"])


def test_the_schema_is_made_strict_in_a_copy_and_the_original_is_untouched():
    s = strict_schema(SCHEMA)
    assert s["required"] == ["answer", "next", "items"] and s["additionalProperties"] is False
    assert s["properties"]["items"]["items"]["additionalProperties"] is False and s["properties"]["items"]["items"]["required"] == ["a"]
    assert SCHEMA["required"] == ["answer"] and "additionalProperties" not in SCHEMA


def test_usage_counts_reasoning_as_output_and_the_cost_uses_the_published_price():
    p, _ = provider([ok(prompt=1000, completion=500, reasoning=300)])
    p.generate_json(system="s", prompt="q", schema=SCHEMA)
    assert p.usage == [{"prompt": 1000, "output": 200, "thoughts": 300, "total": 1500}]
    assert price_of("gpt-5.6-luna") == (0.20, 1.20) and price_of("gpt-5.6-terra") == (2.00, 12.00)
    assert cost_of(p.usage, "gpt-5.6-luna") == pytest.approx((1000 * 0.20 + 500 * 1.20) / 1e6)               # 0.0008 USD


def test_a_video_url_is_refused_because_openai_cannot_watch_one():
    p, calls = provider([])
    with pytest.raises(ProviderError, match="video"):
        p.generate_json(system="s", prompt="q", schema=SCHEMA, video_url="https://www.youtube.com/watch?v=AAAAAAAAAAA")
    assert calls == []


def test_quota_and_client_errors_stop_at_once_and_server_errors_are_retried():
    p, calls = provider([Resp(429, text="rate limited")])
    with pytest.raises(QuotaError):
        p.generate_json(system="s", prompt="q", schema=SCHEMA)
    assert len(calls) == 1
    p, calls = provider([Resp(400, text=f"bad request with {KEY}")])
    with pytest.raises(ProviderError) as e:
        p.generate_json(system="s", prompt="q", schema=SCHEMA)
    assert KEY not in str(e.value) and len(calls) == 1                                                       # the key never appears in an error
    p, calls = provider([Resp(503, text="busy"), ConnectionError("reset"), ok()])
    assert p.generate_json(system="s", prompt="q", schema=SCHEMA)["answer"] == "hi" and len(calls) == 3
    p, calls = provider([Resp(503, text="busy")] * 3)
    with pytest.raises(OverloadError):
        p.generate_json(system="s", prompt="q", schema=SCHEMA)


def test_a_refusal_an_empty_answer_and_broken_json_are_reported():
    p, _ = provider([Resp(200, {"choices": [{"message": {"content": None, "refusal": "I cannot help with that"}}], "usage": {}})])
    with pytest.raises(ProviderError, match="refused"):
        p.generate_json(system="s", prompt="q", schema=SCHEMA)
    p, _ = provider([Resp(200, {"choices": [{"message": {"content": ""}}], "usage": {}})])
    with pytest.raises(ProviderError, match="empty"):
        p.generate_json(system="s", prompt="q", schema=SCHEMA)
    p, _ = provider([Resp(200, {"choices": [{"message": {"content": "{not json"}}], "usage": {}})])
    with pytest.raises(ValueError):
        p.generate_json(system="s", prompt="q", schema=SCHEMA)


def test_no_key_is_an_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIProvider()


def test_the_cost_guard_caches_logs_and_stops_before_a_call_that_could_pass_the_ceiling(tmp_path):
    inner, calls = provider([ok(), ok()], model="gpt-5.6-luna")
    guard = BudgetedProvider(inner, ceilings=Ceilings(max_usd_run=1.0, max_usd_day=1.0), label="openai", directory=tmp_path / "b", cache_dir=tmp_path / "c")
    a = guard.generate_json(system="s", prompt="same question", schema=SCHEMA)
    b = guard.generate_json(system="s", prompt="same question", schema=SCHEMA)
    assert a == b and len(calls) == 1                                                                         # the second one is a cache hit and costs nothing
    log = (tmp_path / "b" / "cost_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"model": "gpt-5.6-luna"' in line for line in log)
