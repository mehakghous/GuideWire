"""Measure the discovery fit check (plan item D2) on videos whose content we know.

    python scripts/fit_check_eval.py --dry-run     # list the calls and the estimated cost, call nothing
    python scripts/fit_check_eval.py               # run it (about 18 short clips, under 10 cents, cached)

The six demo tutorials (demo/data) are the ground truth: each has a goal that describes it. For each goal three candidates are built, in the WORST order a title ranking could produce, with title-score gaps of 0.4 (the live top-three gaps seen were 0.37 and 0.02, so a bigger gap would make the test harder than real use):
  1. a video in another application (9.0),
  2. a video in the same application about something else (8.6),
  3. the video the goal describes (8.2).
Questions: does the fit check (a) flag the wrong application, (b) mark the other-topic video as not matching, (c) keep the right video, and (d) bring the right video to the top of the three?
It cannot say anything about real search results, where nobody has labelled which video is right; it only measures whether the check can tell a known right video from known wrong ones.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.answer import TutorialRecommendation  # noqa: E402

GOALS = {
    "EBgHRd5tJfE": ("a beginner guide to rigging with a basic armature and automatic weights", "blender", "beginner"),
    "PctSMB-RGsM": ("rig a leg with inverse kinematics", "blender", None),
    "LJeap3wpyJA": ("simple IK rigging with APEX", "houdini", None),
    "xWnI7is6e7Q": ("simple FK rigging with APEX", "houdini", None),
    "8RqfDcoP0jI": ("rig a whole character quickly as a beginner", "maya", "beginner"),
    "TmhC35PqZvQ": ("set up a leg with IK handles", "maya", None),
}


def videos() -> dict[str, dict]:
    m = json.loads((ROOT / "demo" / "data" / "manifest.json").read_text(encoding="utf-8"))
    return {x["video_id"]: x for x in m}


def candidates(vid: str, vids: dict[str, dict]) -> list[tuple[str, TutorialRecommendation, float]]:
    """[(role, recommendation, title score)] in the worst order."""
    app = GOALS[vid][1]
    other_app = next(v for v in vids if vids[v]["app"] != app)
    same_app = next(v for v in vids if vids[v]["app"] == app and v != vid)
    out = []
    for role, v, score in (("wrong_app", other_app, 9.0), ("other_topic", same_app, 8.6), ("target", vid, 8.2)):
        out.append((role, TutorialRecommendation(title=vids[v]["title"], url=vids[v]["url"], score=score), score))
    return out


def run(dry: bool) -> dict:
    from ingestion import fit_check as fc
    vids = videos()
    provider = None
    if not dry:
        from dotenv import load_dotenv

        from ingestion.budget import TIERS, BudgetedProvider, Ceilings, api_key_for
        from ingestion.providers.gemini import GeminiProvider
        load_dotenv()
        provider = BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model=TIERS["iterate"]), ceilings=Ceilings.from_env(max_usd_run=0.5), label="default")
    rows = []
    n_calls = 0
    for vid, (goal, app, level) in GOALS.items():
        cands = candidates(vid, vids)
        n_calls += len(cands)
        if dry:
            print(f"{app:8s} goal={goal!r}: {[r for r, _, _ in cands]}")
            continue
        recs = [c[1] for c in cands]
        roles = {r.url: role for role, r, _ in cands}
        before = [roles[r.url] for r in recs]
        new, fits = fc.apply_fit_checks(recs, provider, goal, app, level)
        fit_by_role = {before[i]: f for i, f in enumerate(fits)}
        rows.append({
            "goal": goal, "app": app,
            "order_before": before, "order_after": [roles[r.url] for r in new],
            "wrong_app_flagged": fc.wrong_application(fit_by_role["wrong_app"], app),
            "other_topic": {"covers": fit_by_role["other_topic"].covers, "app_shown": fit_by_role["other_topic"].app_shown},
            "target": {"covers": fit_by_role["target"].covers, "app_shown": fit_by_role["target"].app_shown, "wrongly_flagged": fc.wrong_application(fit_by_role["target"], app)},
            "checked": sum(f.checked for f in fits), "notes": [r.note for r in new],
        })
    print(f"{n_calls} calls (one 120 s clip each)")
    if dry:
        print("estimated cost: about", round(n_calls * 0.004, 3), "USD")
        return {}
    n = len(rows)
    summary = {
        "goals": n,
        "wrong_app_flagged": sum(r["wrong_app_flagged"] for r in rows),
        "other_topic_marked_no_or_partly": sum(r["other_topic"]["covers"] in ("no", "partly") for r in rows),
        "target_kept": sum((not r["target"]["wrongly_flagged"]) and r["target"]["covers"] != "no" for r in rows),
        "target_first_after": sum(r["order_after"][0] == "target" for r in rows),
        "target_first_before": 0,
        "all_checked": all(r["checked"] == 3 for r in rows),
        "usd": round(provider.run_usd, 4), "calls_made": provider.calls, "cache_hits": provider.hits, "model": provider.model_id,
    }
    return {"summary": summary, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-o", default=str(ROOT / "eval_data" / "fit_check_results.json"))
    a = ap.parse_args(argv)
    res = run(a.dry_run)
    if res:
        Path(a.o).parent.mkdir(parents=True, exist_ok=True)
        Path(a.o).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps(res["summary"], indent=1))
        for r in res["rows"]:
            print(f"\n{r['app']} / {r['goal']}\n  before {r['order_before']}\n  after  {r['order_after']}")
            for note in r["notes"]:
                print("   -", note[:230])
    return 0


if __name__ == "__main__":
    sys.exit(main())
