"""Evaluate multi-turn follow-up handling against a conversation file. Offline, deterministic, no model.

  python -m ingestion.eval.followup_eval --set tests/corpus/followups_dev.json --label dev

Metrics are computed per TURN (n = number of turns), each defined by the expectation fields in the file:
  intent_accuracy       predicted follow-up intent == labelled intent
  route_accuracy        session / standalone / clarify as labelled (context resolution: did it attach, detach or ask correctly?)
  kind_accuracy         AnswerBundle.kind as labelled, where labelled
  content_pass          all `contains` present and no `not_contains` present
  state_pass            status_after / current_after / active_after / verification_after / not_done / unmet as labelled
  false_completions     steps in a turn's `not_done` list that ended up done (a question must never complete a step)
  contamination         `not_contains` hits (e.g. text from a different tutorial)
  ungrounded_rate       turns labelled grounded that carry neither a source nor a step reference
  turn_pass             every check above passes
LIMITS: expectations are author-written; `contains` is a substring check, so it can pass for the wrong reason or fail for a correct paraphrase.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..followup import respond
from ..router import route
from ..session import Session

ROOT = Path(__file__).resolve().parents[2]
TEXTS = {
    "A": "Select both cubes. Press Ctrl+J to join them. Press Tab to enter Edit Mode. Select two vertices. Press G to move them.",
    "B": "Press Tab to enter Edit Mode. Select a face. Press S to scale it. Press Tab to return to Object Mode. Press Ctrl+Z to undo.",
}


def _bundle_for(key: str, version: str | None):
    if key == "T":
        vtt = (ROOT / "tests" / "corpus" / "transcript_synthetic.vtt").read_text(encoding="utf-8")
        return route(vtt, version=version, input_type="transcript", duration_s=100)
    return route(TEXTS[key], version=version)


def build_session(conv: dict, key: str | None = None) -> Session:
    key = key or conv["tutorial"]
    s = Session(version=conv.get("version"), observed=conv.get("observed"))
    b = _bundle_for(key, conv.get("version"))
    s.load(b, version=conv.get("version"))
    if conv.get("tutorial_version_hint"):
        s.tutorial["version_hint"] = conv["tutorial_version_hint"]
    for sid in conv.get("done", []):
        s.mark(sid, "done", "user")
    if conv.get("current"):
        s.goto(conv["current"])
    return s


def answer_text(b) -> str:
    parts = [b.clarification or "", *b.questions, *b.caveats, *b.assumptions, *b.unmet_prerequisites]
    parts += [e.text for e in b.explanations]
    if b.steps:
        parts += [s.goal for s in b.steps.steps]
    return " ".join(parts).lower()


def check_turn(s: Session, reply, exp: dict) -> dict:
    b, txt = reply.bundle, answer_text(reply.bundle)
    r: dict = {}
    if "intent" in exp:
        r["intent"] = reply.intent == exp["intent"]
    if "route" in exp:
        r["route"] = reply.route == exp["route"]
    if "kind" in exp:
        r["kind"] = b.kind == exp["kind"]
    miss = [c for c in exp.get("contains", []) if c.lower() not in txt]
    bad = [c for c in exp.get("not_contains", []) if c.lower() in txt]
    r["content"] = not miss and not bad
    st_ok = True
    for sid, want in exp.get("status_after", {}).items():
        st_ok &= s.status.get(sid) == want
    if "current_after" in exp:
        st_ok &= s.current == exp["current_after"]
    if "active_after" in exp:
        st_ok &= s.active == exp["active_after"]
    for sid, want in exp.get("verification_after", {}).items():
        st = s.step(sid)
        st_ok &= bool(st and st.verification and st.verification.outcome == want)
    if "unmet" in exp:
        st_ok &= bool(b.unmet_prerequisites) == exp["unmet"]
    false_done = [sid for sid in exp.get("not_done", []) if s.status.get(sid) == "done"]
    st_ok &= not false_done
    r["state"] = st_ok
    r["false_completions"] = len(false_done)
    r["contamination"] = len(bad)
    if exp.get("grounded"):
        r["grounded"] = bool(b.sources or any(e.applies_to_steps for e in b.explanations))
    r["_miss"], r["_bad"] = miss, bad
    return r


def evaluate(path: Path, label: str, kb=None, tutorials=None) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows, lat = [], []
    for conv in data["conversations"]:
        s = build_session(conv)
        for i, turn in enumerate(conv["turns"]):
            for act in turn.get("do", []):
                if act.startswith("load:"):
                    s.load(_bundle_for(act.split(":")[1], conv.get("version")), version=conv.get("version"))
            t0 = time.perf_counter()
            reply = respond(s, turn["say"], kb=kb, tutorials=tutorials)
            lat.append((time.perf_counter() - t0) * 1000)
            chk = check_turn(s, reply, turn["expect"])
            ok = all(v for k, v in chk.items() if isinstance(v, bool))
            rows.append({"conv": conv["id"], "turn": i + 1, "say": turn["say"], "pred_intent": reply.intent, "pred_route": reply.route, "kind": reply.bundle.kind,
                         "checks": {k: v for k, v in chk.items() if not k.startswith("_")}, "missing": chk["_miss"], "forbidden": chk["_bad"], "pass": ok,
                         "api_calls": reply.bundle.api_calls, "network_calls": reply.bundle.network_calls})
    def rate(key):
        xs = [r["checks"][key] for r in rows if key in r["checks"] and isinstance(r["checks"][key], bool)]
        return f"{sum(xs)}/{len(xs)}" if xs else "n/a"
    summary = {"label": label, "conversations": len(data["conversations"]), "turns": len(rows),
               "intent_accuracy": rate("intent"), "route_accuracy": rate("route"), "kind_accuracy": rate("kind"), "content_pass": rate("content"),
               "state_pass": rate("state"), "grounded": rate("grounded"),
               "false_completions": sum(r["checks"]["false_completions"] for r in rows), "contamination": sum(r["checks"]["contamination"] for r in rows),
               "turn_pass": f"{sum(r['pass'] for r in rows)}/{len(rows)}", "model_calls": sum(r["api_calls"] for r in rows),
               "network_calls": sum(r["network_calls"] for r in rows), "latency_ms_mean": round(sum(lat) / len(lat), 2), "latency_ms_max": round(max(lat), 2)}
    return {"summary": summary, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--label", required=True)
    a = ap.parse_args(argv)
    res = evaluate(Path(a.set), a.label)
    print(json.dumps(res["summary"], indent=1))
    for r in res["rows"]:
        if not r["pass"]:
            print(f"  FAIL {r['conv']}.{r['turn']} {r['say']!r}: intent={r['pred_intent']} route={r['pred_route']} kind={r['kind']} checks={r['checks']} missing={r['missing']} forbidden={r['forbidden']}")
    out = ROOT / "runs" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"followup_eval_{a.label}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
