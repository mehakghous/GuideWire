"""Gemini retry behaviour without any network: bounded, backed off with jitter, and the failure classes stay distinct."""
from types import SimpleNamespace

import pytest

from ingestion.providers.base import OverloadError, ProviderError, QuotaError
from ingestion.providers.gemini import GeminiProvider


class Err(Exception):
    def __init__(self, code, msg="x"):
        super().__init__(msg)
        self.code = code


def provider(responses):
    p = GeminiProvider(api_key="test-key", max_attempts=3)
    seq = list(responses)
    calls = []
    def gen(**kw):
        calls.append(kw)
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(text='{"steps": []}', usage_metadata=None)
    p._client = SimpleNamespace(models=SimpleNamespace(generate_content=gen))
    sleeps = []
    p._sleep, p._rand = sleeps.append, lambda a, b: 1.0
    return p, calls, sleeps


def call(p):
    return p.generate_json(system="s", prompt="p", schema={})


def test_overload_is_retried_with_growing_pauses_then_reported_as_overload():
    p, calls, sleeps = provider([Err(503)] * 3)
    with pytest.raises(OverloadError, match="after 3 attempts"):
        call(p)
    assert len(calls) == 3 and sleeps == [5.0, 10.0]                    # exponential, and no pause after the last attempt


def test_a_retry_that_works_returns_the_answer_and_records_every_attempt():
    p, calls, sleeps = provider([Err(503), {"ok": 1}])
    assert call(p) == {"steps": []} and len(calls) == 2 and [e["status"] for e in p.events] == [503, 200] and "latency_s" in p.events[-1]


def test_jitter_scales_each_pause():
    p, _, sleeps = provider([Err(503), Err(503), Err(503)])
    p._rand = lambda a, b: 0.5
    with pytest.raises(OverloadError):
        call(p)
    assert sleeps == [2.5, 5.0]


def test_permanent_errors_are_not_retried_and_quota_is_its_own_class():
    p, calls, sleeps = provider([Err(400, "bad request")])
    with pytest.raises(ProviderError) as e:
        call(p)
    assert not isinstance(e.value, OverloadError) and len(calls) == 1 and sleeps == []
    p, calls, sleeps = provider([Err(429, "quota")])
    with pytest.raises(QuotaError):
        call(p)
    assert len(calls) == 1


def test_the_api_key_never_appears_in_the_error():
    p, _, _ = provider([Err(503, "failure for key test-key")] * 3)
    with pytest.raises(OverloadError) as e:
        call(p)
    assert "test-key" not in str(e.value) and "[REDACTED]" in str(e.value)


def test_cli_says_nothing_was_charged_when_the_model_is_at_capacity(monkeypatch, capsys):
    from ingestion import cli
    import ingestion.cli as c
    class Boom:
        model_id = "x"
        def __init__(self, **k): pass
        def generate_json(self, **k): raise OverloadError("503")
    monkeypatch.setattr(c, "GeminiProvider", Boom)
    assert cli.main(["video", "https://www.youtube.com/watch?v=dc3iRo0hb3g", "--no-metadata", "--app", "maya"]) == 1
    assert "at capacity" in capsys.readouterr().err


def test_every_prompt_version_the_code_has_is_accepted_by_the_extraction_commands():
    """Twice a new prompt version was added and the CLI still refused it (v4, v5): the allowed list now comes from the code."""
    from ingestion import cli
    from ingestion.extract import PROMPT_VERSIONS
    import pytest as _pytest
    for v in PROMPT_VERSIONS:
        with _pytest.raises(SystemExit) as e:             # parse only; --help exits 0 after the parser accepted the whole command line
            cli.main(["video", "https://www.youtube.com/watch?v=dc3iRo0hb3g", "--prompt-version", v, "--help"])
        assert e.value.code == 0
