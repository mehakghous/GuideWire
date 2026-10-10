"""Controlled experiment runner: cached cells, cost ledger with hard stops, scoring against a frozen reference.

  python -m ingestion.experiment run   --video 34FBeC9mktE --arms A,B --repeats 3
  python -m ingestion.experiment score --video 34FBeC9mktE --reference eval_data/gold/34FBeC9mktE.reference.v1.json

Arms: A = baseline (prompt v2, the prompt of all earlier live runs), B = candidate (prompt v3).
Everything else (model, video, schema, validation, token cap, temperature) is identical between arms.

Safety: a run never exceeds HARD_CAP_USD of *notional* cost (what a paid key would charge; on a free tier the
actual charge is $0 but quota is consumed). It stops on HTTP 429, on other 4xx, on repeated 503s, and when
the call, token, video-second or dollar limits are reached. Completed cells are cached by a key over every
input that can change the result, so identical configurations are never paid for twice. No API key is
ever written to the cache, ledger or logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from shared.step_record import SCHEMA_VERSION, StepList

from .extract import ExtractionError, build_system_prompt, extract_from_video, video_prompt
from .profiles import get_profile
from .providers.base import ProviderError, QuotaError

log = logging.getLogger(__name__)

HARD_CAP_USD = 3.00           # the approved ceiling: refuse to configure anything above it
EST_VIDEO_TOKENS_PER_S = 96   # measured all-in on 2026-10-10 (low media resolution)
EST_FIXED_TOKENS = 3000
PRICES = {                    # USD per 1M tokens (input, output incl. thinking), pricing page 2026-10-10, paid tier
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}
ARMS = {"A": {"prompt_version": "v2"}, "B": {"prompt_version": "v3"}}


class StopExperiment(RuntimeError):
    """A safety limit was hit; nothing further is called."""


def price_of(model: str) -> tuple[float, float]:
    return PRICES.get(model, PRICES["gemini-3.6-flash"])  # unknown model: assume the dearer known price


def cost_of(usage: list[dict[str, int]], model: str) -> float:
    pin, pout = price_of(model)
    return sum(u["prompt"] * pin + (u["output"] + u.get("thoughts", 0)) * pout for u in usage) / 1e6


@dataclass
class Limits:
    max_usd: float = 2.50
    max_calls: int = 30            # HTTP attempts, 503s included
    max_video_seconds: float = 9000  # 2.5 h, under the free-tier 8 h/day cap
    max_output_tokens: int = 16384
    max_consecutive_503: int = 4

    def __post_init__(self):
        if self.max_usd > HARD_CAP_USD:
            raise ValueError(f"max_usd {self.max_usd} exceeds the approved hard cap ${HARD_CAP_USD}")


@dataclass
class Ledger:
    path: Path
    notional_usd: float = 0.0
    calls: int = 0
    video_seconds: float = 0.0
    quota_errors: int = 0
    consecutive_503: int = 0
    cells: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        path = Path(path)
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(path=path, **d)
        return cls(path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d.pop("path")
        self.path.write_text(json.dumps(d, indent=1), encoding="utf-8")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def cell_key(*, model: str, prompt_version: str, video_id: str, duration_s: float, repeat: int,
             max_output_tokens: int, media_resolution: str | None, title_hint: str | None) -> str:
    """Cache key over every input that can change the result (prompt text, model, schema, video, settings)."""
    sys_h = _h(build_system_prompt(get_profile("blender"), prompt_version))
    usr_h = _h(video_prompt(prompt_version, duration_s, title_hint))
    blob = json.dumps({"m": model, "sys": sys_h, "usr": usr_h, "v": video_id, "d": duration_s, "r": repeat,
                       "schema": SCHEMA_VERSION, "mo": max_output_tokens, "res": media_resolution,
                       "temp": 0.2}, sort_keys=True)
    return _h(blob)


def preflight_cost(duration_s: float, model: str, lim: Limits, attempts: int = 2) -> float:
    pin, pout = price_of(model)
    est_in = duration_s * EST_VIDEO_TOKENS_PER_S + EST_FIXED_TOKENS
    return attempts * (est_in * pin + lim.max_output_tokens * pout) / 1e6


def _check_before(ledger: Ledger, lim: Limits, duration_s: float, model: str) -> None:
    est = preflight_cost(duration_s, model, lim)
    if ledger.notional_usd + est > lim.max_usd:
        raise StopExperiment(f"budget: spent ${ledger.notional_usd:.3f} + worst case ${est:.3f} > cap ${lim.max_usd:.2f}")
    if ledger.calls + 2 > lim.max_calls:
        raise StopExperiment(f"call limit: {ledger.calls} used of {lim.max_calls}")
    if ledger.video_seconds + 2 * duration_s > lim.max_video_seconds:
        raise StopExperiment(f"video-seconds limit: {ledger.video_seconds:.0f} used of {lim.max_video_seconds:.0f}")
    if ledger.quota_errors:
        raise StopExperiment("an earlier HTTP 429 stopped this experiment; wait for the quota to reset")
    if ledger.consecutive_503 >= lim.max_consecutive_503:
        raise StopExperiment(f"{ledger.consecutive_503} consecutive 503s: provider overloaded, pause and retry later")


def run_cell(
    *, provider_factory: Callable[[], Any], model: str, arm: str, video_id: str, duration_s: float,
    title_hint: str | None, repeat: int, cache_dir: Path, ledger: Ledger, lim: Limits,
    media_resolution: str | None = None, sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run one (arm, video, repeat) cell, or return the cached result. Raises StopExperiment on a limit."""
    pv = ARMS[arm]["prompt_version"]
    key = cell_key(model=model, prompt_version=pv, video_id=video_id, duration_s=duration_s, repeat=repeat,
                   max_output_tokens=lim.max_output_tokens, media_resolution=media_resolution, title_hint=title_hint)
    path = Path(cache_dir) / f"{key}.json"
    if path.exists():
        cell = json.loads(path.read_text(encoding="utf-8"))
        cell["cached"] = True
        return cell
    for pause in (0, 30, 60):  # a cell that only ever got 503s is retried twice after a pause, then given up
        _check_before(ledger, lim, duration_s, model)
        if pause:
            sleep(pause)
        provider = provider_factory()
        attempts: list[dict[str, Any]] = []
        t0 = time.time()
        steplist = partial = err = None
        quota = False
        try:
            steplist = extract_from_video(provider, video_id, duration_s=duration_s, title_hint=title_hint,
                                          prompt_version=pv, on_attempt=attempts.append)
        except QuotaError as e:
            err, quota = f"QuotaError: {e}", True
        except ExtractionError as e:
            err = str(e)
            partial = e.partial
        except ProviderError as e:
            err = f"ProviderError: {e}"
        latency = time.time() - t0
        usage = list(getattr(provider, "usage", []))
        events = list(getattr(provider, "events", []))
        cost = cost_of(usage, model)
        ledger.notional_usd += cost
        ledger.calls += max(len(events), 1)
        ledger.video_seconds += duration_s * len(usage)
        statuses = [e.get("status") for e in events]
        ledger.consecutive_503 = ledger.consecutive_503 + 1 if (statuses and statuses[-1] == 503) else 0
        if quota:
            ledger.quota_errors += 1
        got_response = bool(usage)
        cell = {
            "key": key, "arm": arm, "prompt_version": pv, "model": model, "video_id": video_id,
            "duration_s": duration_s, "repeat": repeat, "schema_version": SCHEMA_VERSION,
            "started_utc": datetime.now(timezone.utc).isoformat(), "latency_s": round(latency, 1),
            "accepted": steplist is not None, "error": err, "attempts": attempts, "events": events,
            "usage": usage, "cost_notional_usd": round(cost, 5), "cached": False,
            "steplist": json.loads(steplist.model_dump_json()) if steplist else None,
            "partial": json.loads(partial.model_dump_json()) if partial else None,
        }
        ledger.history.append({"key": key, "arm": arm, "repeat": repeat, "accepted": cell["accepted"],
                               "cost": cell["cost_notional_usd"], "statuses": statuses, "error": (err or "")[:120]})
        ledger.cells += 1
        ledger.save()
        # Only COMPLETE cells are cached: accepted, or rejected by validation after the model answered twice.
        # A cell cut short by 503/429 is kept for the record (incomplete/) but will be re-run on resume.
        complete = cell["accepted"] or (got_response and not quota and (err or "").startswith("model output still invalid"))
        if complete:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cell, indent=1, default=str), encoding="utf-8")
        elif got_response or quota:
            inc = Path(cache_dir).parent / "incomplete"
            inc.mkdir(parents=True, exist_ok=True)
            (inc / f"{key}.{int(time.time())}.json").write_text(json.dumps(cell, indent=1, default=str), encoding="utf-8")
        if quota:
            raise StopExperiment(f"HTTP 429 after cell {arm}/{repeat}: stopping; the result so far was saved")
        if complete or not statuses or statuses[-1] != 503:
            return cell
    return cell  # only 503s three times: not cached, reported with its events


# ------------------------------------------------------------------ scoring
def _frozen_ok(reference: Path) -> str:
    want = reference.with_suffix(".sha256")
    got = hashlib.sha256(reference.read_bytes()).hexdigest()
    if not want.exists():
        raise SystemExit(f"{want} missing: freeze the reference before scoring")
    if want.read_text().split()[0] != got:
        raise SystemExit("reference file differs from its frozen hash: create a new version, do not edit it")
    return got


def score_cells(reference: Path, cache_dir: Path, video_id: str) -> list[dict[str, Any]]:
    from .eval.coverage import demonstration_gap, evaluate_coverage, recall_in_window
    from .eval.gold import GoldSet

    _frozen_ok(reference)
    gold = GoldSet.model_validate(json.loads(reference.read_text(encoding="utf-8")))
    rows = []
    for f in sorted(Path(cache_dir).glob("*.json")):
        cell = json.loads(f.read_text(encoding="utf-8"))
        if cell["video_id"] != video_id:
            continue
        sl_json = cell["steplist"] or cell["partial"]
        atts = cell["attempts"]
        row = {
            "arm": cell["arm"], "repeat": cell["repeat"], "model": cell["model"], "prompt": cell["prompt_version"],
            "accepted": cell["accepted"], "extraction_attempts": len(atts),
            "rejected_attempts": sum(1 for a in atts if a.get("accepted") is False),
            "first_attempt_valid": bool(atts and atts[0].get("accepted")),
            "http_statuses": [e.get("status") for e in cell["events"]],
            "latency_s": cell["latency_s"], "prompt_tokens": sum(u["prompt"] for u in cell["usage"]),
            "output_tokens": sum(u["output"] for u in cell["usage"]),
            "thought_tokens": sum(u.get("thoughts", 0) for u in cell["usage"]),
            "cost_notional_usd": cell["cost_notional_usd"], "error": cell["error"],
            "issue_codes": sorted({i.split("]")[0].lstrip("[") for a in atts for i in a.get("issues", [])}),
        }
        if sl_json:
            sl = StepList.model_validate(sl_json)
            rep = evaluate_coverage(gold, sl)
            row.update({
                "n_steps": len(sl.steps), "from_partial": not cell["accepted"],
                "demo_recall": rep.demonstrated_recall, "narr_recall": rep.narrated_recall,
                "overall_recall": rep.overall_recall,
                "demo_recall_strict": rep.demonstrated_recall_strict, "narr_recall_strict": rep.narrated_recall_strict,
                "overall_recall_strict": rep.overall_recall_strict,
                "demo_only_recall": rep.demonstrated_only_recall, "narr_only_recall": rep.narrated_only_recall,
                "recall_38_92": recall_in_window(gold, rep, 38, 92), "gap_38_92": demonstration_gap(gold, rep, 38, 92),
                "precision_lenient": rep.precision_lenient, "precision_strict": rep.precision_strict,
                "unmatched_gen": rep.unmatched_gen, "beyond_end_gen": rep.beyond_end_gen, "broad_gen": rep.broad_gen,
                "duplicate_gen": rep.duplicate_gen, "untimed_gen": rep.untimed_gen,
                "temporal_within_tol": rep.temporal_within_tol, "temporal_median_abs_err_s": rep.temporal_median_abs_err_s,
                "state_recall": rep.state_recall, "state_wrong_rate": rep.state_wrong_rate,
                "order_inversion_rate": rep.order_inversion_rate,
                "prerequisite_violation_rate": rep.prerequisite_violation_rate,
                "visual_claims": rep.visual_claims, "false_visual_claims": rep.false_visual_claims,
                "demo_recall_claimed": rep.demonstrated_recall_claimed,
                "unverified_covered": rep.unverified_covered, "counts": rep.counts,
                "covered_refs": sorted(rep.lenient), "strict_pairs": rep.strict,
                "verifiable_rate": sum(s.verifiable for s in sl.steps) / len(sl.steps),
                "flag_count": sum(len(s.flags) for s in sl.steps), "warnings": sl.warnings,
            })
        rows.append(row)
    return rows


def _mean(vals):
    v = [x for x in vals if x is not None]
    return round(statistics.mean(v), 3) if v else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        rs = [r for r in rows if r["arm"] == arm]
        scored = [r for r in rs if "demo_recall" in r]
        keys = ["demo_recall", "narr_recall", "overall_recall", "demo_recall_strict", "recall_38_92",
                "precision_lenient", "precision_strict", "temporal_within_tol", "temporal_median_abs_err_s",
                "state_recall", "state_wrong_rate", "order_inversion_rate", "prerequisite_violation_rate",
                "verifiable_rate", "n_steps"]
        out[arm] = {
            "runs": len(rs), "accepted": sum(r["accepted"] for r in rs),
            "first_attempt_valid": sum(r["first_attempt_valid"] for r in rs),
            "rejected_attempts": sum(r["rejected_attempts"] for r in rs),
            "mean": {k: _mean([r.get(k) for r in scored]) for k in keys},
            "min_max_demo_recall": [min((r["demo_recall"] for r in scored if r["demo_recall"] is not None), default=None),
                                    max((r["demo_recall"] for r in scored if r["demo_recall"] is not None), default=None)],
            "latency_s_mean": _mean([r["latency_s"] for r in rs]),
            "prompt_tokens_mean": _mean([r["prompt_tokens"] for r in rs]),
            "output_tokens_mean": _mean([r["output_tokens"] for r in rs]),
            "cost_notional_usd_total": round(sum(r["cost_notional_usd"] for r in rs), 4),
        }
    return out


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(prog="experiment")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--video", required=True)
    r.add_argument("--arms", default="A,B")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--model", default="gemini-3.6-flash")
    r.add_argument("--max-usd", type=float, default=2.50)
    r.add_argument("--max-calls", type=int, default=30)
    r.add_argument("--max-video-seconds", type=float, default=9000)
    r.add_argument("--max-output-tokens", type=int, default=16384)
    r.add_argument("--dir", default="runs")
    s = sub.add_parser("score")
    s.add_argument("--video", required=True)
    s.add_argument("--reference", required=True)
    s.add_argument("--tag", default="", help="suffix for the results file, e.g. v1 or v2-posthoc")
    s.add_argument("--dir", default="runs")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "google_genai", "google.genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    base = Path(args.dir)
    if args.cmd == "score":
        rows = score_cells(Path(args.reference), base / "cache", args.video)
        res = {"video": args.video, "scored_utc": datetime.now(timezone.utc).isoformat(),
               "reference_sha256": _frozen_ok(Path(args.reference)), "rows": rows, "aggregate": aggregate(rows)}
        (base / "results").mkdir(parents=True, exist_ok=True)
        out = base / "results" / (f"{args.video}.{args.tag}.json" if args.tag else f"{args.video}.json")
        out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(json.dumps(res["aggregate"], indent=1))
        print("wrote", out)
        return 0

    from .providers.gemini import GeminiProvider
    from .youtube.metadata import fetch_metadata

    lim = Limits(max_usd=args.max_usd, max_calls=args.max_calls, max_video_seconds=args.max_video_seconds,
                 max_output_tokens=args.max_output_tokens)
    md = fetch_metadata(args.video)
    if md.privacy_status != "public":
        print(f"video is {md.privacy_status}; the URL route needs a public video", file=sys.stderr)
        return 2
    ledger = Ledger.load(base / "ledger.json")
    factory = lambda: GeminiProvider(model=args.model, max_output_tokens=lim.max_output_tokens, max_attempts=3)
    try:
        for rep in range(1, args.repeats + 1):
            for arm in args.arms.split(","):
                cell = run_cell(provider_factory=factory, model=args.model, arm=arm, video_id=args.video,
                                duration_s=float(md.duration_s), title_hint=md.title, repeat=rep,
                                cache_dir=base / "cache", ledger=ledger, lim=lim)
                print(f"arm {arm} repeat {rep}: accepted={cell['accepted']} cached={cell['cached']} "
                      f"attempts={len(cell['attempts'])} statuses={[e.get('status') for e in cell['events']]} "
                      f"cost_notional=${cell['cost_notional_usd']:.4f} total=${ledger.notional_usd:.4f} "
                      f"calls={ledger.calls} err={(cell['error'] or '')[:80]}")
    except StopExperiment as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
