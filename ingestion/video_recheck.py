"""Second look at the video for a question the extracted steps could not answer (plan item B1).

The answer model sees the steps as TEXT. When the question is about the tutorial but the steps do not contain the answer (it says "not in the tutorial", `in_tutorial = "no"`), the steps may simply be
too coarse: a small setting, a reason, a value the instructor typed. So the question is put to the video model again, on a SHORT CLIP around the right moment (`...#t=start,end`, the same clip
mechanism as extraction), with the rule that it may only report what is shown or said in that clip.

  * the moment is chosen from, in order: a time in the question ("at 2:10"), the step the model named, the step whose words best match the question, the step the learner is on;
  * found     -> the answer, with the clip it was found in ("the video shows this somewhere in 4:04 to 6:04"), not a point in time: the model's own time was about 40 s wrong when checked;
  * not found -> the first answer is kept and one sentence is added: "I also checked the video around 1:25 to 3:25 and it is not shown there". The recheck is NEVER allowed to guess: not saying
    "not shown" when it is not shown is exactly what the "not in the tutorial" rule was written to prevent (docs/evaluation_report_2026-11-09.md, section 3.4);
  * any provider error or budget stop keeps the first answer unchanged.
One extra call per such question, on a clip of at most WINDOW_BEFORE_S + WINDOW_AFTER_S seconds, through the same cost guard (cache, ceilings, log) as every other call.
With `extra_windows` (the gateway and chat use 3) it goes on to other parts of the video while the answer is "not shown", because the first guess is the wrong part of the video when the question has no time in it.
Measured on 27 labelled actions the steps missed, with a time in the question the first clip found 27 and 24 were correct; with no time the first clip found 19 (18 correct) and the sweep found 26 (22 correct, 2 wrong); 36 of 36 unanswerable questions were
answered "not shown" with and without the sweep (docs/evaluation_report_2026-11-09.md, section 3.10).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .rigging_knowledge import _tokens
from .session import Session

WINDOW_BEFORE_S = 45
WINDOW_AFTER_S = 75

SYSTEM = """You answer ONE learner question about ONE short clip of a tutorial video. Use only what is SHOWN on screen or SAID in the clip. If the clip does not show or say the answer, set found to false and say so: never guess, never use general knowledge, never describe what the video "probably" does.
If found, answer in one to three plain sentences and name the menu, tool or value exactly as the clip shows it.
Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {"found": {"type": "boolean"}, "answer": {"type": "string", "description": "what the clip shows or says that answers the question; empty when found is false"}},
    "required": ["found", "answer"],
}


@dataclass(frozen=True)
class Window:
    start_s: int
    end_s: int
    why: str


def mmss(t: float) -> str:
    t = int(round(t))
    return f"{t // 60}:{t % 60:02d}"


def video_url_of(session: Session) -> str | None:
    """The public YouTube URL of the loaded tutorial, from the session's tutorial record (a url, or an 11-character video id)."""
    from .youtube.metadata import canonical_url, parse_video_id
    t = session.tutorial or {}
    for key in ("url", "video_id", "id"):
        v = t.get(key)
        if isinstance(v, str) and v:
            try:
                return canonical_url(parse_video_id(v))
            except ValueError:
                continue
    return None


def _duration(session: Session) -> float | None:
    sl = session.steps
    if sl is None:
        return None
    ends = [s.video_end_s for s in sl.steps if s.video_end_s is not None]
    return sl.video_duration_s or (max(ends) if ends else None)


def pick_window(question: str, session: Session, step_ids: list[str] | None = None) -> Window | None:
    """The clip to look at, or None when nothing in the question or the steps says where."""
    sl = session.steps
    if sl is None:
        return None
    anchor, why = None, ""
    m = re.search(r"\b(\d{1,2}):([0-5]\d)\b", question)
    if m:
        anchor, why = int(m.group(1)) * 60 + int(m.group(2)), "the time in the question"
    if anchor is None:
        named = next((s for s in sl.steps if s.id in (step_ids or []) and s.video_start_s is not None), None)
        if named is not None:
            anchor, why = int(named.video_start_s), f"step {named.id}"
    if anchor is None:
        q = _tokens(question)
        best = max(((len(q & _tokens(s.goal + " " + " ".join(h.text for h in s.how_to))), s) for s in sl.steps if s.video_start_s is not None), key=lambda t: t[0], default=(0, None))
        if best[1] is not None and best[0] >= 1:
            anchor, why = int(best[1].video_start_s), f"step {best[1].id}"
    if anchor is None and session.current:
        cur = session.step(session.current)
        if cur is not None and cur.video_start_s is not None:
            anchor, why = int(cur.video_start_s), "the step the learner is on"
    if anchor is None:
        return None
    dur = _duration(session)
    start = max(0, anchor - WINDOW_BEFORE_S)
    end = anchor + WINDOW_AFTER_S
    if dur:
        end = min(end, int(dur))
        start = min(start, max(0, end - 20))
    return Window(start, end, why) if end > start else None


def windows_to_try(question: str, session: Session, step_ids: list[str] | None = None, extra: int = 0) -> list[Window]:
    """The clip chosen by `pick_window`, then up to `extra` other parts of the video (the video cut in clips of WINDOW_BEFORE_S + WINDOW_AFTER_S seconds, those that mostly overlap an earlier clip
    left out, nearest to the first clip first). The sweep is for a question with no time in it, where the first guess can be the wrong part of the video."""
    first = pick_window(question, session, step_ids)
    if first is None:
        return []
    wins = [first]
    dur = _duration(session)
    if extra > 0 and dur:
        size = WINDOW_BEFORE_S + WINDOW_AFTER_S
        tiles = [Window(a, min(a + size, int(dur)), "a sweep of the video") for a in range(0, int(dur), size) if min(a + size, int(dur)) - a >= 20]
        tiles = [t for t in tiles if min(t.end_s, first.end_s) - max(t.start_s, first.start_s) < size / 2]
        centre = (first.start_s + first.end_s) / 2
        tiles.sort(key=lambda t: abs((t.start_s + t.end_s) / 2 - centre))
        wins += tiles[:extra]
    return wins


def recheck(provider, question: str, session: Session, step_ids: list[str] | None = None, extra_windows: int = 0) -> tuple[Window, dict] | None:
    """Ask the video model about the clip. Returns (window, result) or None when there is no video, no moment, or no call succeeded. Never raises.
    With `extra_windows` it goes on to other parts of the video while the answer is "not shown", and stops at the first clip that shows it; `result["tried"]` lists every clip asked."""
    url = video_url_of(session)
    wins = windows_to_try(question, session, step_ids, extra_windows)
    if url is None or not wins:
        return None
    old = getattr(provider, "video_seconds", None)
    tried: list[tuple[int, int]] = []
    first_ok: tuple[Window, dict] | None = None
    try:
        for win in wins:
            if hasattr(provider, "video_seconds"):
                provider.video_seconds = float(win.end_s - win.start_s)
            try:
                res = provider.generate_json(system=SYSTEM, prompt=f"Learner question: {question}", schema=SCHEMA, video_url=f"{url}#t={win.start_s},{win.end_s}")
            except Exception:
                break                                                              # an outage or a budget stop: keep what was asked so far
            if not isinstance(res, dict) or not isinstance(res.get("found"), bool):
                break
            tried.append((win.start_s, win.end_s))
            res = {**res, "tried": list(tried)}
            if first_ok is None:
                first_ok = (win, res)
            if res["found"] and (res.get("answer") or "").strip():
                return win, res
    finally:
        if hasattr(provider, "video_seconds"):
            provider.video_seconds = old
    if first_ok is None:
        return None
    return first_ok[0], {**first_ok[1], "tried": list(tried)}


def apply_recheck(text: str, win: Window, res: dict) -> tuple[str, str]:
    """(the answer text, a one-line caveat). Found: the clip's answer with its time. Not found: the first answer plus one honest sentence."""
    span = f"{mmss(win.start_s)} to {mmss(win.end_s)}"
    tried = res.get("tried") or []
    if not (res["found"] and (res.get("answer") or "").strip()) and len(tried) > 1:
        parts = ", ".join(f"{mmss(a)} to {mmss(b)}" for a, b in tried)
        return text.rstrip() + f" I also checked {len(tried)} parts of the video ({parts}) and it is not shown in any of them.", f"Checked {len(tried)} parts of the video: not shown."
    if res["found"] and (res.get("answer") or "").strip():
        # no exact time: in the first live run the model's "at" time was about 40 s off the human-labelled moment, so only the clip it was shown is reported
        return res["answer"].strip() + f" (the video shows this somewhere in {span})", f"Checked the video around {span}: this is what it shows or says there."
    return text.rstrip() + f" I also checked the video around {span} and it is not shown there.", f"Checked the video around {span}: not shown."
