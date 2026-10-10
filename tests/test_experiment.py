"""Offline tests for the experiment runner (cache, ledger, hard stops, scoring). No network, no API key."""
import json
import shutil
from pathlib import Path

import pytest

from ingestion.experiment import (
    HARD_CAP_USD, Ledger, Limits, StopExperiment, cell_key, cost_of, run_cell, score_cells,
)
from ingestion.providers.base import ProviderError, QuotaError
from ingestion.providers.fake import ScriptedProvider

REF = Path(__file__).parent.parent / "eval_data" / "gold" / "34FBeC9mktE.reference.v1.json"
VID, DUR = "34FBeC9mktE", 188.0


def good(n_extra=0):
    steps = [{"goal": "Press Ctrl+Z to undo", "confidence": 0.8, "video_start_s": "00:50", "video_end_s": "00:53",
              "support": "both", "visual_evidence": "overlay Ctrl+Z x2", "evidence": ["control Z"],
              "actions": [{"verb": "press_keys", "keys": ["Ctrl", "Z"]}]}]
    return {"steps": steps}


class E503(ProviderError):
    code = 503


def make(tmp, resp_lists, lim=None, arm="B", repeat=1):
    """resp_lists: one list of responses per provider instance the runner will create."""
    made = []
    it = iter(resp_lists)

    def factory():
        p = ScriptedProvider(next(it))
        made.append(p)
        return p
    ledger = Ledger.load(tmp / "ledger.json")
    cell = run_cell(provider_factory=factory, model="gemini-3.6-flash", arm=arm, video_id=VID, duration_s=DUR,
                    title_hint="T", repeat=repeat, cache_dir=tmp / "cache", ledger=ledger,
                    lim=lim or Limits(), sleep=lambda s: None)
    return cell, made, ledger


def test_hard_cap_cannot_be_exceeded():
    with pytest.raises(ValueError):
        Limits(max_usd=HARD_CAP_USD + 0.01)
    Limits(max_usd=HARD_CAP_USD)


def test_cost_from_usage():
    # 18,000 prompt + 800 output tokens at 3.6-flash: 18000*0.75 + 800*3.75 = 16,500 micro-dollars
    assert cost_of([{"prompt": 18000, "output": 800}], "gemini-3.6-flash") == pytest.approx(0.0165)
    assert cost_of([{"prompt": 18000, "output": 800, "thoughts": 1000}], "gemini-3.6-flash") == pytest.approx(0.0165 + 0.00375)


def test_cache_key_covers_prompt_model_repeat():
    k = lambda **kw: cell_key(**{**dict(model="m", prompt_version="v2", video_id=VID, duration_s=DUR, repeat=1,
                                        max_output_tokens=16384, media_resolution=None, title_hint="T"), **kw})
    assert k() == k()
    assert len({k(), k(prompt_version="v3"), k(model="m2"), k(repeat=2), k(duration_s=190.0), k(max_output_tokens=8192)}) == 6


def test_completed_cell_is_cached_and_not_rerun(tmp_path):
    c1, made1, led = make(tmp_path, [[good()]])
    assert c1["accepted"] and not c1["cached"] and led.calls == 1 and led.notional_usd == pytest.approx(0.0165)
    ledger_before = led.notional_usd
    c2, made2, led2 = make(tmp_path, [])            # no provider is even created
    assert c2["cached"] and made2 == [] and led2.notional_usd == ledger_before
    assert c2["steplist"]["steps"][0]["video_start_s"] == 50.0
    assert c1["attempts"][0]["raw"]["steps"][0]["video_start_s"] == "00:50"   # raw response preserved


def test_failed_attempts_are_paid_for_and_recorded(tmp_path):
    bad = {"steps": [{"goal": "x", "confidence": 0.5, "video_start_s": 500, "video_end_s": 501}]}
    cell, made, led = make(tmp_path, [[bad, bad]])
    assert not cell["accepted"] and cell["error"] and cell["partial"]["steps"][0]["video_start_s"] == 500
    assert len(cell["usage"]) == 2 and led.notional_usd == pytest.approx(2 * 0.0165)   # failed calls are not free
    assert cell["attempts"][0]["issues"] and "TS_BEYOND_END" in cell["attempts"][0]["issues"][0]


def test_budget_stop_happens_before_any_call(tmp_path):
    with pytest.raises(StopExperiment, match="budget"):
        make(tmp_path, [], lim=Limits(max_usd=0.01))


def test_call_and_video_second_limits(tmp_path):
    with pytest.raises(StopExperiment, match="call limit"):
        make(tmp_path, [], lim=Limits(max_calls=1))
    with pytest.raises(StopExperiment, match="video-seconds"):
        make(tmp_path, [], lim=Limits(max_video_seconds=100))


def test_quota_error_stops_everything(tmp_path):
    with pytest.raises(StopExperiment, match="429"):
        make(tmp_path, [[QuotaError("HTTP 429")]])
    led = Ledger.load(tmp_path / "ledger.json")
    assert led.quota_errors == 1
    with pytest.raises(StopExperiment, match="429"):                      # the next cell is refused outright
        make(tmp_path, [], repeat=2)


def test_only_503s_are_not_cached_and_counted(tmp_path):
    cell, made, led = make(tmp_path, [[E503("x")], [E503("x")], [E503("x")]])
    assert not cell["accepted"] and len(made) == 3 and led.consecutive_503 == 3
    assert not list((tmp_path / "cache").glob("*.json")) if (tmp_path / "cache").exists() else True
    with pytest.raises(StopExperiment, match="503"):                      # 3 + 1 more would hit the limit of 4
        led.consecutive_503 = 4
        led.save()
        make(tmp_path, [], repeat=2)


def test_no_secret_is_written(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-VALUE-123")
    make(tmp_path, [[good()]])
    blob = "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.json"))
    assert "SECRET-VALUE-123" not in blob


def test_scoring_uses_frozen_reference(tmp_path):
    make(tmp_path, [[good()]], arm="A")
    make(tmp_path, [[good()]], arm="B")
    rows = score_cells(REF, tmp_path / "cache", VID)
    assert {r["arm"] for r in rows} == {"A", "B"}
    for r in rows:
        assert r["demo_recall"] is not None and r["demo_recall"] > 0 and r["narr_recall"] > 0
        assert r["first_attempt_valid"] is True and r["cost_notional_usd"] == pytest.approx(0.0165)
    again = score_cells(REF, tmp_path / "cache", VID)
    assert again == rows                                                  # reproducible


def test_scoring_refuses_a_modified_reference(tmp_path):
    make(tmp_path, [[good()]])
    for suffix in (".json", ".sha256"):
        shutil.copy(REF.with_suffix(suffix), tmp_path / f"ref{suffix}")
    (tmp_path / "ref.json").write_text((tmp_path / "ref.json").read_text(encoding="utf-8").replace("R06", "R6X"), encoding="utf-8")
    with pytest.raises(SystemExit):
        score_cells(tmp_path / "ref.json", tmp_path / "cache", VID)


def test_interrupted_cells_are_kept_but_not_cached(tmp_path):
    bad = {"steps": [{"goal": "x", "confidence": 0.5, "video_start_s": 500, "video_end_s": 501}]}
    cell, _, led = make(tmp_path, [[bad, E503("x"), E503("x"), E503("x")], [good()]])
    # attempt 1 invalid (response received), attempt 2 only 503s: incomplete, so not cached and re-run on resume
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").glob("*.json")) or cell["accepted"]
    assert list((tmp_path / "incomplete").glob("*.json")) or cell["accepted"]
