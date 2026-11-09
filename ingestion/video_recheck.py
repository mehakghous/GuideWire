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


def recheck(provider, question: str, session: Session, step_ids: list[str] | None = None) -> tuple[Window, dict] | None:
    """Ask the video model about the clip. Returns (window, result) or None when there is no video, no moment, or the call failed. Never raises."""
    url = video_url_of(session)
    win = pick_window(question, session, step_ids)
    if url is None or win is None:
        return None
    old = getattr(provider, "video_seconds", None)
    try:
        if hasattr(provider, "video_seconds"):
            provider.video_seconds = float(win.end_s - win.start_s)
        res = provider.generate_json(system=SYSTEM, prompt=f"Learner question: {question}", schema=SCHEMA, video_url=f"{url}#t={win.start_s},{win.end_s}")
    except Exception:
        return None
    finally:
        if hasattr(provider, "video_seconds"):
            provider.video_seconds = old
    if not isinstance(res, dict) or not isinstance(res.get("found"), bool):
        return None
    return win, res


def apply_recheck(text: str, win: Window, res: dict) -> tuple[str, str]:
    """(the answer text, a one-line caveat). Found: the clip's answer with its time. Not found: the first answer plus one honest sentence."""
    span = f"{mmss(win.start_s)} to {mmss(win.end_s)}"
    if res["found"] and (res.get("answer") or "").strip():
        # no exact time: in the first live run the model's "at" time was about 40 s off the human-labelled moment, so only the clip it was shown is reported
        return res["answer"].strip() + f" (the video shows this somewhere in {span})", f"Checked the video around {span}: this is what it shows or says there."
    return text.rstrip() + f" I also checked the video around {span} and it is not shown there.", f"Checked the video around {span}: not shown."
