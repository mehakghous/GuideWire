"""Human labelling sheets: a CSV a person fills in while watching a tutorial, converted into the existing reference format (GoldSet).

Columns (one row per action the learner is told to do OR is shown doing):
  start        when the action BEGINS: m:ss, h:mm:ss or seconds
  end          when it ends (optional; blank = a moment)
  action       what the learner does, in the annotator's words ("Press Tab to enter Edit Mode")
  evidence     said | shown | both     said = only narrated; shown = only visible on screen; both = narrated AND shown
  importance   core | optional         core = the tutorial's result depends on it
  keys_or_menu the key or menu path as shown/said, if any ("Tab", "Add > Mesh > Cube")  [optional]
  notes        anything the next reader needs  [optional]

The annotator labels from the VIDEO, never from system output (the guide in docs/labelling_guide.md says why). Rows that fail validation are
reported with their row numbers; nothing is silently repaired.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from shared.step_record import Action

from .coverage import similarity
from .gold import GoldSet, GoldStep

COLUMNS = ["start", "end", "action", "evidence", "importance", "keys_or_menu", "notes"]
EVIDENCE = {"said": "narrated", "shown": "demonstrated", "both": "both"}
_KEY = re.compile(r"^(?:(?:ctrl|control|shift|alt|cmd)\s*[+-]\s*)*[a-z0-9]$|^(?:tab|esc|enter|space|delete|backspace|f\d{1,2})$", re.I)


def parse_time(v: str) -> float:
    v = (v or "").strip()
    if not v:
        raise ValueError("empty time")
    if re.fullmatch(r"\d+(?:\.\d+)?", v):
        return float(v)
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)", v)
    if not m:
        raise ValueError(f"cannot read time {v!r} (use m:ss, h:mm:ss or seconds)")
    h, mi, s = m.groups()
    if float(s) >= 60 or (h and int(mi) >= 60):
        raise ValueError(f"minutes/seconds out of range in {v!r}")
    return int(h or 0) * 3600 + int(mi) * 60 + float(s)


def _actions(cell: str) -> list[Action]:
    cell = (cell or "").strip()
    if not cell:
        return []
    if _KEY.match(cell.replace(" ", "")) or re.fullmatch(r"(?:\w+\s*\+\s*)+\w+", cell):
        return [Action(verb="press_keys", keys=[k.strip().title() if len(k.strip()) > 1 else k.strip().upper() for k in re.split(r"\s*\+\s*", cell)])]
    return [Action(verb="click", ui_element=cell)]


@dataclass
class LabelProblems:
    errors: list[str] = field(default_factory=list)     # make the sheet unusable until fixed
    warnings: list[str] = field(default_factory=list)   # worth a look, sheet still usable


def load_csv(path_or_text: str | Path, *, duration_s: float, video_id: str, title: str | None, annotator: str,
             app_version: str | None = None, tol_s: float = 5.0) -> tuple[GoldSet | None, LabelProblems]:
    text = Path(path_or_text).read_text(encoding="utf-8-sig") if not (isinstance(path_or_text, str) and "\n" in path_or_text) else path_or_text
    pr = LabelProblems()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        pr.errors.append("the sheet has no rows")
        return None, pr
    missing = [c for c in ("start", "action", "evidence", "importance") if c not in (rows[0] or {})]
    if missing:
        pr.errors.append(f"missing column(s): {', '.join(missing)}")
        return None, pr
    steps: list[GoldStep] = []
    last = -1.0
    for i, r in enumerate(rows, start=2):                       # row 1 is the header
        if not any((v or "").strip() for v in r.values()):
            continue
        try:
            t0 = parse_time(r["start"])
            t1 = parse_time(r["end"]) if (r.get("end") or "").strip() else None
        except ValueError as e:
            pr.errors.append(f"row {i}: {e}")
            continue
        act = (r.get("action") or "").strip()
        ev = (r.get("evidence") or "").strip().lower()
        imp = (r.get("importance") or "").strip().lower()
        if not act:
            pr.errors.append(f"row {i}: the action is empty")
        if ev not in EVIDENCE:
            pr.errors.append(f"row {i}: evidence must be said, shown or both (got {ev!r})")
        if imp not in ("core", "optional"):
            pr.errors.append(f"row {i}: importance must be core or optional (got {imp!r})")
        if t1 is not None and t1 < t0:
            pr.errors.append(f"row {i}: end is before start")
        if t0 > duration_s or (t1 is not None and t1 > duration_s + 1):
            pr.errors.append(f"row {i}: time is past the end of the video ({duration_s:g} s)")
        if t0 < last - 0.01:
            pr.warnings.append(f"row {i}: starts before the previous row (sheet should be in time order)")
        last = max(last, t0)
        if any(abs(s.t_start - t0) < 1.0 and similarity(s.goal, act) >= 0.8 for s in steps):
            pr.warnings.append(f"row {i}: looks like a duplicate of an earlier row")
        if ev and ev in EVIDENCE and act:
            steps.append(GoldStep(order=len(steps) + 1, id=f"H{len(steps) + 1:02d}", goal=act, t_start=t0, t_end=t1, tol_s=tol_s, actions=_actions(r.get("keys_or_menu", "")),
                                  evidence_kind="directly_evidenced", evidence_type=EVIDENCE[ev], verification="human", verification_confidence="high",
                                  importance=imp if imp in ("core", "optional") else "core", note=(r.get("notes") or "").strip() or None))
    if pr.errors or not steps:
        if not steps and not pr.errors:
            pr.errors.append("no usable rows")
        return None, pr
    return GoldSet(video_id=video_id, title=title, duration_s=duration_s, app_version=app_version, annotator=annotator,
                   verification_note="human labels from the video via ingestion.eval.labels (docs/labelling_guide.md)", steps=steps), pr


def to_csv(g: GoldSet) -> str:
    inv = {v: k for k, v in EVIDENCE.items()}
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for s in g.steps:
        keys = " + ".join(s.actions[0].keys) if s.actions and s.actions[0].keys else (s.actions[0].ui_element if s.actions and s.actions[0].ui_element else "")
        mm = lambda t: "" if t is None else f"{int(t // 60)}:{t % 60:04.1f}".replace(".0", "")
        w.writerow([mm(s.t_start), mm(s.t_end), s.goal, inv.get(s.evidence_type or "both", "both"), s.importance, keys, s.note or ""])
    return out.getvalue()


# ----------------------------------------------------------------------------------------------------------------- agreement
@dataclass
class Agreement:
    n_a: int
    n_b: int
    matched: int
    only_a: list[str]
    only_b: list[str]
    dice: float                       # 2 * matched / (n_a + n_b): 1.0 = both found exactly the same actions
    evidence_agreement: float | None  # of the matched pairs, share that agree on said / shown / both
    importance_agreement: float | None
    median_start_diff_s: float | None


def agreement(a: GoldSet, b: GoldSet, *, tol_s: float = 6.0, min_similarity: float = 0.2) -> Agreement:
    """One-to-one alignment of two annotators' steps: start times within `tol_s` and the wording at least loosely alike. Greedy by smallest time gap.
    It bounds what any system score can mean: a system cannot reliably beat the disagreement between two careful people."""
    pairs = sorted(((abs(x.t_start - y.t_start), i, j) for i, x in enumerate(a.steps) for j, y in enumerate(b.steps)
                    if abs(x.t_start - y.t_start) <= tol_s and similarity(x.goal, y.goal) >= min_similarity), key=lambda t: t[0])
    used_a, used_b, got = set(), set(), []
    for d, i, j in pairs:
        if i not in used_a and j not in used_b:
            used_a.add(i), used_b.add(j), got.append((i, j, d))
    ev = [a.steps[i].evidence_type == b.steps[j].evidence_type for i, j, _ in got]
    im = [a.steps[i].importance == b.steps[j].importance for i, j, _ in got]
    diffs = sorted(d for _, _, d in got)
    return Agreement(len(a.steps), len(b.steps), len(got), [a.steps[i].goal for i in range(len(a.steps)) if i not in used_a],
                     [b.steps[j].goal for j in range(len(b.steps)) if j not in used_b], round(2 * len(got) / (len(a.steps) + len(b.steps)), 3),
                     round(sum(ev) / len(ev), 3) if ev else None, round(sum(im) / len(im), 3) if im else None, diffs[len(diffs) // 2] if diffs else None)


def main(argv=None) -> int:
    """python -m ingestion.eval.labels eval_data/labels/<video id>.<name>.csv   -> validates one sheet against the manifest and says what to fix."""
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--manifest", default=str(Path(__file__).resolve().parents[2] / "eval_data" / "labels" / "manifest.json"))
    a = ap.parse_args(argv)
    sheet = Path(a.sheet)
    vid, who = sheet.name.split(".")[0], sheet.name.split(".")[1]
    m = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    v = next((x for x in m["videos"] if x["video_id"] == vid), None)
    if v is None:
        print(f"error: {vid} is not in the manifest")
        return 2
    g, pr = load_csv(sheet, duration_s=v["duration_s"], video_id=vid, title=v.get("title"), annotator=who)
    for e in pr.errors:
        print("ERROR  ", e)
    for w in pr.warnings:
        print("warning", w)
    if g:
        ev = {k: sum(s.evidence_type == EVIDENCE[k] for s in g.steps) for k in EVIDENCE}
        print(f"OK: {len(g.steps)} actions ({ev['said']} said, {ev['shown']} shown, {ev['both']} both; {sum(s.importance == 'core' for s in g.steps)} core) for \"{v['title'][:50]}\" ({v['duration_s'] // 60}:{v['duration_s'] % 60:02d})")
    return 0 if g else 1


if __name__ == "__main__":
    raise SystemExit(main())
