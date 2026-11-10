"""Budget guard: cache, ceilings, unknown-model refusal, cost log without secrets, dry run. No network, no real model."""
import json
from datetime import date

import pytest

from ingestion.budget import BudgetedProvider, BudgetExceeded, Ceilings, api_key_for, dry_run, estimate
from ingestion.providers.fake import ScriptedProvider

GOOD = {"steps": [{"goal": "Create joints", "confidence": 0.9, "support": "narrated", "evidence": ["create joints"]}]}
MODEL = "gemini-3.6-flash"
SCHEMA = {"type": "object"}


def make(tmp_path, responses=None, ceilings=None, **kw):
    inner = ScriptedProvider(responses if responses is not None else [GOOD] * 6, usage_per_call=(10_000, 1_000))
    inner.model_id = kw.pop("model", MODEL)
    return BudgetedProvider(inner, ceilings=ceilings or Ceilings(), directory=tmp_path / "b", cache_dir=tmp_path / "c", today=date(2026, 10, 22), **kw), inner


def call(p, prompt="p", system="s", video_url=None):
    return p.generate_json(system=system, prompt=prompt, schema=SCHEMA, video_url=video_url)


def test_second_identical_request_is_a_cache_hit_and_costs_nothing(tmp_path):
    p, inner = make(tmp_path)
    assert call(p) == GOOD and call(p) == GOOD
    assert len(inner.calls) == 1 and p.calls == 1 and p.hits == 1
    assert p.usage[-1]["cached"] == 1 and p.usage[-1]["prompt"] == 0


def test_what_the_model_sees_is_the_key_so_app_prompt_or_video_changes_it(tmp_path):
    p, inner = make(tmp_path)
    call(p, system="maya prompt")
    call(p, system="houdini prompt")                       # another application's system prompt: not a hit
    call(p, prompt="other hint")
    call(p, video_url="https://www.youtube.com/watch?v=aaaaaaaaaaa")
    assert len(inner.calls) == 4 and p.hits == 0
    q, _ = make(tmp_path, model="gemini-3.5-flash-lite")   # another model: not a hit either
    call(q, system="maya prompt")
    assert q.hits == 0 and q.calls == 1


def test_fresh_skips_the_cache_read_but_still_writes_it(tmp_path):
    p, inner = make(tmp_path)
    call(p)
    f, inner2 = make(tmp_path, fresh=True)
    call(f)
    assert len(inner2.calls) == 1 and f.hits == 0
    g, inner3 = make(tmp_path)
    call(g)
    assert g.hits == 1 and not inner3.calls


def test_ceilings_stop_before_the_call_that_would_pass_them(tmp_path):
    p, inner = make(tmp_path, ceilings=Ceilings(max_usd_run=0.17, max_usd_day=10.0))
    p.video_seconds = 1200
    call(p, prompt="a", video_url="https://www.youtube.com/watch?v=aaaaaaaaaaa")             # worst case about 0.149 each; a call actually costs about 0.012
    for i in range(3):
        try:
            call(p, prompt=f"b{i}", video_url="https://www.youtube.com/watch?v=aaaaaaaaaaa")
        except BudgetExceeded as e:
            assert "run ceiling" in str(e)
            break
    else:
        pytest.fail("the run ceiling never stopped the batch")
    assert len(inner.calls) == 2 and p.run_usd < 0.17


def test_daily_ceiling_counts_earlier_runs_of_the_same_day(tmp_path):      # worst case for a 600 s video is about 0.107; one real call spent about 0.012
    a, _ = make(tmp_path, ceilings=Ceilings(max_usd_day=0.115))
    a.video_seconds = 600
    call(a, video_url="https://www.youtube.com/watch?v=aaaaaaaaaaa")
    b, inner = make(tmp_path, ceilings=Ceilings(max_usd_day=0.115))                        # a new run, same day, same ledger
    b.video_seconds = 600
    with pytest.raises(BudgetExceeded, match="daily ceiling"):
        call(b, prompt="another", video_url="https://www.youtube.com/watch?v=aaaaaaaaaaa")
    assert not inner.calls


def test_token_ceiling(tmp_path):
    p, inner = make(tmp_path, ceilings=Ceilings(max_tokens_run=1000))
    with pytest.raises(BudgetExceeded, match="token ceiling"):
        call(p)
    assert not inner.calls


def test_unknown_model_is_refused_not_priced_like_another(tmp_path):
    p, inner = make(tmp_path, model="gemini-9-imaginary")
    with pytest.raises(BudgetExceeded, match="no price is known"):
        call(p)
    assert not inner.calls


def test_cost_log_has_tokens_and_dollars_but_never_the_key_prompt_or_answer(tmp_path):
    p, _ = make(tmp_path, label="dev")
    call(p, prompt="SECRET-PROMPT-TEXT", system="SECRET-SYSTEM")
    call(p, prompt="SECRET-PROMPT-TEXT", system="SECRET-SYSTEM")
    text = (tmp_path / "b" / "cost_log.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(x) for x in text.splitlines()]
    assert [x["cache"] for x in lines] == ["miss", "hit"] and lines[0]["key_label"] == "dev" and lines[0]["tokens"] == 11_000 and lines[0]["usd"] > 0
    assert "SECRET" not in text and "Create joints" not in text
    ledger = json.loads((tmp_path / "b" / "ledger-2026-10-22.json").read_text(encoding="utf-8"))
    assert ledger["calls"] == 1 and ledger["usd"] == pytest.approx((10_000 * 0.75 + 1_000 * 3.75) / 1e6)


def test_a_failed_call_is_not_cached(tmp_path):
    from ingestion.providers.base import QuotaError
    p, inner = make(tmp_path, responses=[QuotaError("429"), GOOD])
    with pytest.raises(QuotaError):
        call(p)
    assert call(p) == GOOD and len(inner.calls) == 2


def test_key_labels_read_their_own_variable_and_say_which_is_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY_DEV", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_TEST", "t-key")
    assert api_key_for("test") == "t-key"
    with pytest.raises(BudgetExceeded, match="GEMINI_API_KEY_DEV"):
        api_key_for("dev")


def test_estimate_and_dry_run_call_nothing_and_report_the_cache(tmp_path):
    e = estimate(MODEL, video_s=1151, text_chars=0, max_output_tokens=16384, on=date(2026, 10, 22))
    assert 0.07 < e["usd"] < 0.20                          # the measured real run cost 0.09 to 0.10
    r = dry_run(MODEL, video_s=600, system="s", prompt="p", schema=SCHEMA, video_url="https://www.youtube.com/watch?v=aaaaaaaaaaa", cache_dir=tmp_path / "c")
    assert r["cached"] is False and r["usd_worst_case"] > 0 and r["within_run_ceiling"]


def test_cli_dry_run_and_budget_stop_make_no_model_call(monkeypatch, capsys, tmp_path):
    import ingestion.cli as c
    monkeypatch.chdir(tmp_path)

    class Never:
        model_id = MODEL

        def __init__(self, **k):
            self.made = k

        def generate_json(self, **k):
            raise AssertionError("the model must not be called")
    monkeypatch.setattr(c, "GeminiProvider", Never)
    assert c.main(["video", "https://www.youtube.com/watch?v=dc3iRo0hb3g", "--no-metadata", "--duration", "1151", "--app", "houdini", "--dry-run", "--tier", "report"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model"] == "gemini-3.8-flash" and out["prompt_version"] == "v10-hou" and out["video_seconds"] == 1151 and out["cached"] is False      # the measured default for a Houdini video (was v7)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert c.main(["video", "https://www.youtube.com/watch?v=dc3iRo0hb3g", "--no-metadata", "--duration", "1151", "--app", "maya", "--max-usd-run", "0.01"]) == 3
    assert "stopped by the budget guard" in capsys.readouterr().err


def test_gateway_turns_a_budget_stop_into_a_clear_503_and_calls_nothing(tmp_path):
    from fastapi.testclient import TestClient

    from gateway.app import create_app
    inner = ScriptedProvider([GOOD])
    inner.model_id = MODEL
    guarded = BudgetedProvider(inner, ceilings=Ceilings(max_usd_run=0.0001), directory=tmp_path / "b", cache_dir=tmp_path / "c")
    c = TestClient(create_app(provider_factory=lambda: guarded, tokens={"t": "u"}))
    r = c.post("/v1/extract", json={"text": "create joints", "app": "maya"}, headers={"Authorization": "Bearer t", "Idempotency-Key": "k"})
    assert r.status_code == 503 and "cost guard" in r.json()["detail"] and not inner.calls


def test_a_repeat_run_gets_its_own_cache_key_and_repeat_one_is_unchanged(monkeypatch):
    from ingestion.budget import content_key
    args = ("m", "sys", "prompt", {"j": 1}, "https://x", {"mr": 1})
    monkeypatch.delenv("GW_REPEAT", raising=False)
    base = content_key(*args)
    monkeypatch.setenv("GW_REPEAT", "1")
    assert content_key(*args) == base                      # every key recorded before repeats existed is still valid
    monkeypatch.setenv("GW_REPEAT", "2")
    two = content_key(*args)
    monkeypatch.setenv("GW_REPEAT", "3")
    assert len({base, two, content_key(*args)}) == 3


def test_gemini_4_prices_rise_on_the_first_of_december_2026():
    from datetime import date

    from ingestion.experiment import price_of
    for m in ("gemini-4-carbon", "gemini-4-argon"):
        assert price_of(m, date(2026, 11, 30)) == (2.00, 10.00) and price_of(m, date(2026, 12, 1)) == (4.00, 20.00)
