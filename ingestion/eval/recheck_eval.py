"""A real test of the video recheck (ingestion/video_recheck.py), using the human labels as ground truth.

For each labelled video, take actions the human listed that the extracted steps MISSED (no step covers them) and ask the recheck about them, as a learner would:

  * "with time"   : "How does he do this: <the labelled action>? Around 2:10"  (the time is the labelled time rounded to 10 s, as a person remembers it);
  * "without time": the same question with no time, so the clip must be chosen from the steps alone;
  * "unanswerable": questions no tutorial video answers (the music, the instructor's email, a course price), asked at the start of the video and around the middle. The right outcome is "not shown";
    any "found" answer there is an invented answer and is listed for a person to read.

Scored automatically, no person needed:
  * window hit : does the chosen clip contain the labelled moment (+/- 5 s)?
  * found      : did the video model report an answer?
  * correct    : for a found answer on a missed action, does a second model (a different family, text only) say it describes the labelled action? ("yes", "partly", "no")
Numbers are counts, not a verdict on the recheck in general: the questions are a sample of one labeller's misses on six videos.

    python -m ingestion.eval.recheck_eval --steps-dir runs/compare/gemini-3.6-flash/v10_w0 --clip-model gemini-3.5-flash-lite -o runs/qa/recheck_eval.json [--judge]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from shared.step_record import StepList

from ..session import Session
from ..video_recheck import mmss, pick_window, recheck
from . import phase1

UNANSWERABLE = ["what music is playing in the background", "what is the instructor's email address", "what price does he say the paid course costs"]

JUDGE_SYSTEM = """You compare a short answer about a tutorial video with the action a human labeller wrote for the same moment.
Say whether the ANSWER describes that ACTION: "yes" (the same operation, the same tool or menu), "partly" (the right area but a different or vaguer operation, or only part of it), or "no" (a different operation, or nothing about it).
Judge only the operation described, not the wording. Return JSON only."""
JUDGE_SCHEMA = {"type": "object", "properties": {"match": {"type": "string", "enum": ["yes", "partly", "no"]}}, "required": ["match"]}


def session_for(sl: StepList, video_id: str) -> Session:
    s = Session(app=sl.app)
    s.load(sl, tutorial={"id": video_id, "title": f"saved extraction of {video_id}", "source_type": "youtube"})
    return s


def lower_first(text: str) -> str:
    t = text.strip().rstrip(".")
    return t[:1].lower() + t[1:]


def build_items(sl: StepList, gold, per_video: int = 5, decoys: list[str] | None = None) -> list[dict[str, Any]]:
    """Questions for one video: a spread of the labelled actions the steps missed (each asked with and without a time), and the unanswerable ones."""
    missed = [g for g, _ins, words in phase1.covered_actions(sl, gold) if g.importance == "core" and not words]
    n = min(per_video, len(missed))
    pick = [missed[round(i * (len(missed) - 1) / max(1, n - 1))] for i in range(n)] if missed else []          # an even spread through the video
    seen, items = set(), []
    for g in pick:
        if g.order in seen:
            continue
        seen.add(g.order)
        rounded = int(round(g.t_start / 10.0) * 10)
        base = f"how does he do this in the video: {lower_first(g.goal)}"
        items.append({"kind": "with_time", "question": f"{base}? around {mmss(rounded)}", "gold": g.goal, "t": g.t_start})
        items.append({"kind": "without_time", "question": f"{base}?", "gold": g.goal, "t": g.t_start})
    mid = int((gold.duration_s or 300) / 2)
    for d in decoys or []:                                                          # real actions from ANOTHER video: plausible, but not in this one
        items.append({"kind": "decoy", "question": f"how does he do this in the video: {lower_first(d)}?", "gold": None, "t": None})
        items.append({"kind": "decoy", "question": f"how does he do this in the video: {lower_first(d)}? around {mmss(mid)}", "gold": None, "t": None})
    for q in UNANSWERABLE:
        items.append({"kind": "unanswerable", "question": f"{q}?", "gold": None, "t": None})
        items.append({"kind": "unanswerable", "question": f"{q}? around {mmss(mid)}", "gold": None, "t": None})
    return items


def judge_match(judge_provider, answer: str, gold_goal: str) -> str:
    out = judge_provider.generate_json(system=JUDGE_SYSTEM, prompt=f"ACTION (human label): {gold_goal}\nANSWER about the video: {answer}", schema=JUDGE_SCHEMA)
    return out.get("match", "no") if out.get("match") in ("yes", "partly", "no") else "no"


def pick_decoys(gold, others: list, n: int = 3) -> list[str]:
    """Actions from other labelled videos of the same application that share almost no words with any action of this video."""
    from ..rigging_knowledge import _tokens                                        # drops stop words, so "the" and "and" do not count as shared words

    def overlap(a: str, b: str) -> float:
        ta, tb = _tokens(a), _tokens(b)
        return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    mine = [g.goal for g in gold.steps]
    out: list[str] = []
    for og in others:
        for g in og.steps:
            if g.importance == "core" and len(g.goal.split()) >= 4 and all(overlap(g.goal, m) <= 0.2 for m in mine) and g.goal not in out:
                out.append(g.goal)
    step = max(1, len(out) // max(1, n))
    return out[::step][:n]


def run_video(clip_provider, sl: StepList, gold, video_id: str, per_video: int = 5, judge_provider=None, decoys: list[str] | None = None, sweep: int = 0) -> list[dict[str, Any]]:
    sess = session_for(sl, video_id)
    rows = []
    for it in build_items(sl, gold, per_video, decoys):
        win = pick_window(it["question"], sess, [])
        got = recheck(clip_provider, it["question"], sess, [], sweep) if win else None
        row = {"video": video_id, "app": sl.app, **it, "window": [win.start_s, win.end_s] if win else None, "window_why": win.why if win else None,
               "window_hit": bool(win and it["t"] is not None and win.start_s - 5 <= it["t"] <= win.end_s + 5), "asked": got is not None,
               "found": bool(got and got[1]["found"] and (got[1].get("answer") or "").strip()), "answer": (got[1].get("answer") if got else None),
               "clips_asked": len(got[1].get("tried", [])) if got else 0, "found_window": [got[0].start_s, got[0].end_s] if got and got[1]["found"] else None}
        if row["found"] and it["t"] is not None and row["found_window"]:
            row["found_window_hit"] = row["found_window"][0] - 5 <= it["t"] <= row["found_window"][1] + 5
        if row["found"] and it["gold"] and judge_provider is not None:
            row["correct"] = judge_match(judge_provider, row["answer"], it["gold"])
        rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind in ("with_time", "without_time"):
        r = [x for x in rows if x["kind"] == kind]
        if not r:
            continue
        c = Counter(x.get("correct") for x in r if x["found"])
        out[kind] = {"questions": len(r), "window_contains_the_moment": sum(x["window_hit"] for x in r), "found": sum(x["found"] for x in r),
                     "correct_yes": c["yes"], "correct_partly": c["partly"], "correct_no": c["no"], "found_but_not_judged": c[None]}
    for kind in ("with_time", "without_time"):
        r = [x for x in rows if x["kind"] == kind]
        if r:
            out[kind]["clips_asked"] = sum(x["clips_asked"] for x in r)
            out[kind]["found_in_a_clip_with_the_moment"] = sum(1 for x in r if x.get("found_window_hit"))
    for kind in ("decoy", "unanswerable"):
        u = [x for x in rows if x["kind"] == kind]
        if not u:
            continue
        out[kind] = {"clips_asked": sum(x["clips_asked"] for x in u), "questions": len(u), "said_not_shown": sum(1 for x in u if x["asked"] and not x["found"]), "no_clip_asked": sum(1 for x in u if not x["asked"]),
                     "invented_an_answer": [{"video": x["video"], "question": x["question"], "answer": x["answer"]} for x in u if x["found"]]}
    u = []
    if u:
        out["unanswerable"] = {"questions": len(u), "said_not_shown": sum(1 for x in u if x["asked"] and not x["found"]), "no_clip_asked": sum(1 for x in u if not x["asked"]),
                               "invented_an_answer": [{"video": x["video"], "question": x["question"], "answer": x["answer"]} for x in u if x["found"]]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ingestion.eval.recheck_eval")
    ap.add_argument("--steps-dir", type=Path, required=True, help="saved step lists (one json per video, from compare_prompts or the video command)")
    ap.add_argument("--gold-dir", type=Path, default=Path("eval_data") / "gold")
    ap.add_argument("--clip-model", default="gemini-3.5-flash-lite", help="the Gemini model that looks at the clip")
    ap.add_argument("--per-video", type=int, default=5)
    ap.add_argument("--sweep", type=int, default=0, help="other parts of the video to try when the first clip does not show it")
    ap.add_argument("--judge", action="store_true", help="have OpenAI (gpt-5.6-terra) say whether each found answer matches the labelled action")
    ap.add_argument("--max-usd", type=float, default=2.0)
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    from ..budget import BudgetedProvider, Ceilings, api_key_for
    from ..providers.gemini import GeminiProvider
    clip = BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model=a.clip_model), ceilings=Ceilings.from_env(max_usd_run=a.max_usd), label="default")
    judge = None
    if a.judge:
        from ..providers.openai_provider import STRONG_MODEL, OpenAIProvider
        judge = BudgetedProvider(OpenAIProvider(model=STRONG_MODEL), ceilings=Ceilings.from_env(max_usd_run=1.0), label="openai")
    rows: list[dict[str, Any]] = []
    loaded = []
    for f in sorted(a.steps_dir.glob("*.json")):
        sl = StepList.model_validate_json(f.read_text(encoding="utf-8"))
        gold = phase1.load_gold(a.gold_dir, sl.video_id)
        if gold is not None and sl.video_id:
            loaded.append((sl, gold))
    for sl, gold in loaded:
        others = [g for s2, g in loaded if s2.video_id != sl.video_id and s2.app == sl.app]
        rows += run_video(clip, sl, gold, sl.video_id, a.per_video, judge, pick_decoys(gold, others), a.sweep)
    res = {"clip_model": a.clip_model, "summary": summarize(rows), "rows": rows}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1, ensure_ascii=True)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
