"""Cost and cache guard around ANY model provider, so the main path (`cli video`, `cli written`, the gateway) is protected the way the experiment runner always was.

    provider = BudgetedProvider(GeminiProvider(...), ceilings=Ceilings.from_env(), label="dev")

* Content-hash cache: the key is a hash of everything the model sees (model, system prompt, user prompt, response schema, video URL, provider settings), so a
  different application, prompt version, transcript hint or model is a different key. A hit costs nothing and is logged. Responses are cached whether or not
  the extractor later accepts them; `fresh=True` (CLI `--fresh`) skips reading the cache to ask the model again.
* Ceilings checked BEFORE every paid call against a worst-case estimate: dollars per run and per day, tokens per run. A model whose price is unknown is refused
  (it is never assumed to cost the same as another). Hitting a ceiling raises BudgetExceeded; nothing further is called.
* Cost log: one JSON line per call (time, run, key label, model, video id, tokens, dollars, hit or miss, status) in runs/budget/cost_log.jsonl. Never the key,
  never the prompt or the answer. The daily ledger is runs/budget/ledger-YYYY-MM-DD.json.
The ceilings are safety rails, not a goal: defaults are generous so normal work is never blocked.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .experiment import EST_FIXED_TOKENS, EST_VIDEO_TOKENS_PER_S, PRICES, price_of

DEFAULT_DIR = Path("runs") / "budget"
DEFAULT_CACHE = Path("runs") / "cache" / "responses"
UNKNOWN_VIDEO_S = 1800          # when the length of a video is not known, assume half an hour for the worst-case estimate

# Named model tiers: iterate cheaply, report with the stronger one. Model ids are the ones the pricing table knows.
TIERS = {"iterate": "gemini-3.5-flash-lite", "report": "gemini-3.8-flash"}
KEY_ENV = {"default": "GEMINI_API_KEY", "dev": "GEMINI_API_KEY_DEV", "test": "GEMINI_API_KEY_TEST"}


class BudgetExceeded(RuntimeError):
    """A cost or token ceiling would be passed by the next call; nothing was called."""


@dataclass
class Ceilings:
    max_usd_run: float = 5.00
    max_usd_day: float = 10.00
    max_tokens_run: int = 5_000_000

    @classmethod
    def from_env(cls, **override: float) -> "Ceilings":
        c = cls(float(os.environ.get("GW_MAX_USD_RUN", cls.max_usd_run)), float(os.environ.get("GW_MAX_USD_DAY", cls.max_usd_day)),
                int(os.environ.get("GW_MAX_TOKENS_RUN", cls.max_tokens_run)))
        for k, v in override.items():
            if v is not None:
                setattr(c, k, type(getattr(c, k))(v))
        return c


def api_key_for(label: str) -> str:
    """The API key for a label ('default', 'dev', 'test') from the environment. Never printed; a missing one names the variable to set."""
    var = KEY_ENV[label]
    key = os.environ.get(var)
    if not key:
        raise BudgetExceeded(f"{var} is not set (see .env.example); the key label '{label}' reads it")
    return key


def strict_price(model: str, on: date | None = None) -> tuple[float, float]:
    if model not in PRICES:
        raise BudgetExceeded(f"no price is known for model {model!r}: add it to ingestion/experiment.py PRICES from the pricing page before using it (known: {sorted(PRICES)})")
    return price_of(model, on)


def estimate(model: str, *, video_s: float, text_chars: int, max_output_tokens: int, on: date | None = None) -> dict[str, float]:
    """Worst-case tokens and dollars for one call: video tokens from the length (0 for a text-only call), the text at 4 characters a token, the output ceiling as the output."""
    pin, pout = strict_price(model, on)
    tin = EST_FIXED_TOKENS + text_chars / 4 + video_s * EST_VIDEO_TOKENS_PER_S
    return {"tokens_in": tin, "tokens_out": max_output_tokens, "usd": (tin * pin + max_output_tokens * pout) / 1e6}


def content_key(model: str, system: str, prompt: str, schema: dict, video_url: str | None, settings: dict) -> str:
    # GW_REPEAT=2 (or more) gives a repeat run its OWN cache slot, so asking again never overwrites the first answer (`--fresh` alone does: it writes into the same slot). Unset or 1 leaves every key as it was.
    repeat = int(os.environ.get("GW_REPEAT", "1") or 1)
    if repeat > 1:
        settings = {**settings, "repeat": repeat}
    blob = json.dumps({"m": model, "s": system, "p": prompt, "j": schema, "v": video_url, "o": settings}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _video_id(url: str | None) -> str | None:
    return None if not url else url.rsplit("v=", 1)[-1][:20]


class BudgetedProvider:
    """Wraps a provider (anything with `model_id` and `generate_json`). Exposes the same `usage`, `events` and `last_raw_text` the extractor reads."""

    def __init__(self, inner, *, ceilings: Ceilings | None = None, label: str = "default", directory: Path = DEFAULT_DIR, cache_dir: Path = DEFAULT_CACHE,
                 video_seconds: float | None = None, fresh: bool = False, run_id: str | None = None, today: date | None = None):
        self.inner = inner
        self.model_id = inner.model_id
        self.ceilings, self.label, self.fresh = ceilings or Ceilings.from_env(), label, fresh
        self.dir, self.cache_dir = Path(directory), Path(cache_dir)
        self.video_seconds = video_seconds
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.today = today or date.today()
        self.usage: list[dict[str, int]] = []
        self.events: list[dict[str, Any]] = []
        self.last_raw_text: str | None = None
        self.run_usd = 0.0
        self.run_tokens = 0
        self.calls = self.hits = 0

    # ------------------------------------------------------------------ files
    @property
    def ledger_path(self) -> Path:
        return self.dir / f"ledger-{self.today.isoformat()}.json"

    def _ledger(self) -> dict:
        try:
            return json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"date": self.today.isoformat(), "usd": 0.0, "calls": 0, "tokens": 0}

    def _write(self, ledger: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
        os.replace(tmp, self.ledger_path)

    def _log(self, **rec: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        line = {"ts": round(time.time(), 1), "run": self.run_id, "key_label": self.label, "model": self.model_id, **rec}
        with (self.dir / "cost_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    # ------------------------------------------------------------------ the guarded call
    def _settings(self) -> dict:
        return {"res": getattr(self.inner, "_media_resolution", None), "max_out": getattr(self.inner, "_max_output_tokens", None), "temp": 0.2}

    def key_for(self, system: str, prompt: str, schema: dict, video_url: str | None) -> str:
        return content_key(self.model_id, system, prompt, schema, video_url, self._settings())

    def generate_json(self, *, system: str, prompt: str, schema: dict[str, Any], video_url: str | None = None) -> dict[str, Any]:
        key = self.key_for(system, prompt, schema, video_url)
        path = self.cache_dir / f"{key}.json"
        if path.exists() and not self.fresh:
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.hits += 1
            self.usage.append({"prompt": 0, "output": 0, "thoughts": 0, "total": 0, "cached": 1})
            self.events.append({"status": "cache", "key": key})
            self._log(video=_video_id(video_url), cache="hit", usd=0.0, key=key)
            self.last_raw_text = None
            return stored["response"]
        vs = (self.video_seconds if self.video_seconds is not None else UNKNOWN_VIDEO_S) if video_url else 0
        est = estimate(self.model_id, video_s=vs, text_chars=len(system) + len(prompt),
                       max_output_tokens=getattr(self.inner, "_max_output_tokens", None) or 16384, on=self.today)
        ledger = self._ledger()
        c = self.ceilings
        if ledger["usd"] + est["usd"] > c.max_usd_day:
            raise BudgetExceeded(f"daily ceiling: spent ${ledger['usd']:.3f} today + worst case ${est['usd']:.3f} > ${c.max_usd_day:.2f} (GW_MAX_USD_DAY)")
        if self.run_usd + est["usd"] > c.max_usd_run:
            raise BudgetExceeded(f"run ceiling: spent ${self.run_usd:.3f} + worst case ${est['usd']:.3f} > ${c.max_usd_run:.2f} (GW_MAX_USD_RUN)")
        if self.run_tokens + est["tokens_in"] + est["tokens_out"] > c.max_tokens_run:
            raise BudgetExceeded(f"token ceiling: {self.run_tokens:.0f} used + {est['tokens_in'] + est['tokens_out']:.0f} > {c.max_tokens_run} (GW_MAX_TOKENS_RUN)")
        n_usage, n_events = len(getattr(self.inner, "usage", [])), len(getattr(self.inner, "events", []))
        try:
            resp = self.inner.generate_json(system=system, prompt=prompt, schema=schema, video_url=video_url)
        except Exception as e:                              # a failed call may still have been billed (partial attempts): record whatever the provider counted
            self._account(n_usage, n_events, key, video_url, status=type(e).__name__)
            raise
        self.last_raw_text = getattr(self.inner, "last_raw_text", None)
        self._account(n_usage, n_events, key, video_url, status="ok")
        if isinstance(resp, dict):
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.model_id, "key": key, "response": resp}, ensure_ascii=False), encoding="utf-8")
        return resp

    def _account(self, n_usage: int, n_events: int, key: str, video_url: str | None, status: str) -> None:
        new_usage = list(getattr(self.inner, "usage", []))[n_usage:]
        self.usage.extend(new_usage)
        self.events.extend(list(getattr(self.inner, "events", []))[n_events:])
        pin, pout = strict_price(self.model_id, self.today)
        usd = sum(u.get("prompt", 0) * pin + (u.get("output", 0) + u.get("thoughts", 0)) * pout for u in new_usage) / 1e6
        tokens = sum(u.get("prompt", 0) + u.get("output", 0) + u.get("thoughts", 0) for u in new_usage)
        ledger = self._ledger()
        ledger["usd"] = round(ledger["usd"] + usd, 6)
        ledger["calls"] += 1
        ledger["tokens"] += tokens
        self._write(ledger)
        self.run_usd += usd
        self.run_tokens += tokens
        self.calls += 1
        self._log(video=_video_id(video_url), cache="miss", status=status, tokens=tokens, usd=round(usd, 6), key=key)


def dry_run(model: str, *, video_s: float | None, system: str, prompt: str, schema: dict, video_url: str | None, cache_dir: Path = DEFAULT_CACHE,
            ceilings: Ceilings | None = None, max_output_tokens: int = 16384, settings: dict | None = None) -> dict:
    """What a call WOULD cost and whether it is already cached. Calls nothing."""
    vs = (video_s if video_s is not None else UNKNOWN_VIDEO_S) if video_url else 0
    est = estimate(model, video_s=vs, text_chars=len(system) + len(prompt), max_output_tokens=max_output_tokens)
    key = content_key(model, system, prompt, schema, video_url, settings or {"res": None, "max_out": None, "temp": 0.2})
    c = ceilings or Ceilings.from_env()
    return {"model": model, "key": key, "cached": (Path(cache_dir) / f"{key}.json").exists(), "tokens_in": round(est["tokens_in"]), "tokens_out_max": est["tokens_out"],
            "usd_worst_case": round(est["usd"], 4), "within_run_ceiling": est["usd"] <= c.max_usd_run, "run_ceiling": c.max_usd_run, "day_ceiling": c.max_usd_day}
