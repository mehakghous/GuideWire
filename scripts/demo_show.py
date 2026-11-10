"""Show a saved step list the way you would explain it: what the video was, how many steps, the groups, and one step in full.

    python scripts/demo_show.py demo/data/blender_armature_EBgHRd5tJfE.json            # summary and the groups
    python scripts/demo_show.py demo/data/blender_armature_EBgHRd5tJfE.json --step s02  # one step in full

Offline: it only reads the file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.eval.phase1 import structure  # noqa: E402
from ingestion.video_recheck import mmss  # noqa: E402
from shared.step_record import Step, StepList  # noqa: E402


def step_line(s: Step) -> str:
    t = f"{mmss(s.video_start_s)}" if s.video_start_s is not None else "--:--"
    ui = next((a.ui_element for a in s.actions if a.ui_element), None)
    state = ", ".join(f"{p.kind}={p.target}" for p in s.expected_state)
    return f"    {s.id}  {t}  {s.goal}" + (f"   [click: {ui}]" if ui else "") + (f"   [check: {state}]" if state else "")


def show(sl: StepList) -> str:
    st = structure(sl)
    out = [f"{sl.title}", f"  application: {sl.app}   source: {sl.source_type}   steps: {len(sl.steps)}   groups: {len(sl.groups)}   model: {sl.model_id}   prompt: {sl.prompt_version}",
           f"  steps with something to point at: {st['with_target']:.0%}   steps that can also be auto-checked: {st['guidable']:.0%}   with how-to lines: {st['with_how_to']:.0%}", ""]
    for gid, label, steps in sl.groups:
        out.append(f"  {gid or '--'}  {label}  ({len(steps)} step{'s' if len(steps) != 1 else ''})")
        out += [step_line(s) for s in steps]
    return "\n".join(out)


def show_step(sl: StepList, step_id: str) -> str:
    s = next((x for x in sl.steps if x.id == step_id), None)
    if s is None:
        return f"no step {step_id!r}; steps are {sl.steps[0].id} to {sl.steps[-1].id}"
    lines = [f"{s.id}: {s.goal}", f"  group     : {s.group or '-'}", f"  time      : {mmss(s.video_start_s) if s.video_start_s is not None else '-'} to {mmss(s.video_end_s) if s.video_end_s is not None else '-'}",
             f"  kind      : {s.kind}   confidence: {s.model_confidence}   review: {s.review_status}"]
    lines += [f"  action    : {a.verb} {a.ui_element or ''} {' + '.join(a.keys) if a.keys else ''} {a.value or ''}".rstrip() for a in s.actions]
    lines += [f"  expected  : {p.kind} {p.target}{' = ' + str(p.value) if p.value is not None else ''}" for p in s.expected_state] or ["  expected  : nothing the system can check"]
    lines += [f"  how to    : {h.text}  ({h.support})" for h in s.how_to] + [f"  check     : {h.text}  ({h.support})" for h in s.check]
    if s.result:
        lines.append(f"  result    : {s.result}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--step", help="show one step in full, for example s02")
    a = ap.parse_args(argv)
    sl = StepList.model_validate_json(a.file.read_text(encoding="utf-8"))
    print(show_step(sl, a.step) if a.step else show(sl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
