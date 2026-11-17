"""Fit check for tutorial suggestions (plan item D2): a model WATCHES the first part of each top suggestion and says whether it fits the request.

Discovery ranks videos from their title, channel, length and chapters only. That can be wrong in ways a title hides (a "Maya leg rig" that is really a plugin ad, a video in another application,
a video that is advanced when the person said beginner). The fit check looks at a short clip at the start of the video (the introduction usually says what is built) and reads three things:
  * which application the clip SHOWS (it must match the request: a wrong application is the one mistake a learner cannot recover from);
  * whether the clip is about what the person asked for (yes / partly / no / unclear);
  * the level it teaches at.
The result adjusts the score a little (never replaces the title ranking), adds a plain-words note to the suggestion, and may push a clear mismatch out of the top three.

How it stays inside the rules (docs/compliance/google_youtube_questions.md):
  * the video is passed to the Gemini API by its public URL with a clip window, exactly as extraction does; GuideWire downloads no video, audio, frames or thumbnails. THUMBNAILS ARE NOT USED: reading one
    would mean fetching an image from YouTube ourselves, which the stated plan does not allow, so that part of D2 is dropped by rule, not by test;
  * only a few words of text come back, and they are kept for a day (the discovery cache), not 30 days of media;
  * every call goes through the cost guard (price known, cache, daily ceiling). A failed or refused call leaves the suggestion unchanged and says "not checked".
Cost: a 120 s clip is about 12,000 input tokens at the measured 96 tokens per second, about 0.4 cent on gemini-3.5-flash-lite; three suggestions are about 1 cent.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.answer import TutorialRecommendation

CLIP_S = 120
SYSTEM = """You judge whether ONE tutorial video fits what a learner asked for, from a short clip of its start. Use only what the clip SHOWS on screen or SAYS. Never guess from the title.
Return JSON only. app_shown is the application visible in the clip (blender, maya, houdini, other, or unclear when the clip shows no application). covers says whether the clip is about what the learner
wants: yes (the clip is clearly about it or says the video will do it), partly (related but narrower, wider or only a step of it), no (a different topic), unclear (the clip does not say). level is the level
the clip teaches at: beginner, intermediate, advanced or unclear. teaches is one plain sentence on what the video is about, in your own words. problem is one short sentence naming a mismatch with the request, or an empty string."""

SCHEMA = {
    "type": "object",
    "properties": {
        "app_shown": {"type": "string", "enum": ["blender", "maya", "houdini", "other", "unclear"]},
        "covers": {"type": "string", "enum": ["yes", "partly", "no", "unclear"]},
        "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced", "unclear"]},
        "teaches": {"type": "string"},
        "problem": {"type": "string"},
    },
    "required": ["app_shown", "covers", "level", "teaches", "problem"],
}

# how the answer moves the title score (titles range about 3 to 10): a nudge, never an override, except a wrong application which no title can excuse
ADJUST = {"covers": {"yes": 1.0, "partly": 0.0, "no": -2.5, "unclear": 0.0}, "wrong_app": -4.0}


@dataclass
class Fit:
    checked: bool
    app_shown: str = "unclear"
    covers: str = "unclear"
    level: str = "unclear"
    teaches: str = ""
    problem: str = ""
    reason: str = ""            # why it was not checked
    clip: tuple[int, int] = (0, 0)


def clip_url(url: str, duration_s: float | None, start_s: int = 0, clip_s: int = CLIP_S) -> tuple[str, tuple[int, int]]:
    end = start_s + clip_s
    if duration_s:
        end = int(min(end, duration_s))
    start = max(0, min(start_s, max(0, end - 10)))
    return f"{url.split('#')[0]}#t={start},{end}", (start, end)


def goal_text(goal_words: str, app: str | None, level: str | None) -> str:
    parts = [f"The learner asked: {goal_words.strip()!r}."]
    if app:
        parts.append(f"They use {app.capitalize()}.")
    if level:
        parts.append(f"They said their level is {level}.")
    return " ".join(parts)


def check_fit(provider, rec: TutorialRecommendation, goal_words: str, app: str | None, level: str | None = None, *, clip_s: int = CLIP_S, start_s: int = 0) -> Fit:
    """One call on one clip. Never raises: a failure is a Fit with checked=False and the reason."""
    url, win = clip_url(rec.url, rec.duration_s, start_s, clip_s)
    try:
        out = provider.generate_json(system=SYSTEM, prompt=goal_text(goal_words, app, level) + "\nJudge the clip against this request.", schema=SCHEMA, video_url=url)
    except Exception as e:                                         # budget stop, quota, network, a refused or private video
        return Fit(False, reason=f"{type(e).__name__}: {str(e)[:100]}", clip=win)
    if not isinstance(out, dict):
        return Fit(False, reason="the model's answer could not be read", clip=win)
    return Fit(True, str(out.get("app_shown", "unclear")), str(out.get("covers", "unclear")), str(out.get("level", "unclear")), str(out.get("teaches", ""))[:240], str(out.get("problem", ""))[:200], clip=win)


def wrong_application(fit: Fit, app: str | None) -> bool:
    """The clip clearly shows a different application from the one asked for. 'other' and 'unclear' are not a mismatch: an intro can be a title card or a talking head."""
    return bool(app) and fit.checked and fit.app_shown in ("blender", "maya", "houdini") and fit.app_shown != app


def adjustment(fit: Fit, app: str | None) -> float:
    if not fit.checked:
        return 0.0
    return ADJUST["wrong_app"] if wrong_application(fit, app) else ADJUST["covers"].get(fit.covers, 0.0)


def describe(fit: Fit, app: str | None, level: str | None = None) -> str:
    """The sentence added to a suggestion's note, in plain words."""
    if not fit.checked:
        return "Not checked against the video itself."
    a, b = fit.clip
    lead = f"Checked the first {round((b - a) / 60, 1):g} min of the video: "
    if wrong_application(fit, app):
        return lead + f"it shows {fit.app_shown.capitalize()}, not {str(app).capitalize()}."
    bits = [fit.teaches.rstrip(".") + "." if fit.teaches else ""]
    if fit.covers == "yes":
        bits.append("It matches what you asked for.")
    elif fit.covers == "partly":
        bits.append("It covers only part of what you asked for.")
    elif fit.covers == "no":
        bits.append("It does not seem to be about what you asked for.")
    if level and fit.level in ("beginner", "intermediate", "advanced") and fit.level != level and level in ("beginner", "intermediate", "advanced"):
        bits.append(f"It teaches at {fit.level} level; you said {level}.")
    if fit.problem and fit.covers in ("no", "partly"):
        bits.append(fit.problem.rstrip(".") + ".")
    return lead + " ".join(b for b in bits if b)


def apply_fit_checks(recs: list[TutorialRecommendation], provider, goal_words: str, app: str | None, level: str | None = None, *, top: int = 3, clip_s: int = CLIP_S,
                     drop_wrong_app: bool = False) -> tuple[list[TutorialRecommendation], list[Fit]]:
    """Check the first `top` suggestions, adjust their scores, add the note, and re-sort. The rest keep their title ranking and are not checked.
    Returns (the new list, the fits of the checked ones in the OLD order). With `drop_wrong_app` a video whose clip clearly shows another application is left out of the list."""
    head: list[TutorialRecommendation] = []
    fits: list[Fit] = []
    for r in recs[:top]:
        f = check_fit(provider, r, goal_words, app, level, clip_s=clip_s)
        fits.append(f)
        if drop_wrong_app and wrong_application(f, app):
            continue
        note = (r.note + " " if r.note else "") + describe(f, app, level)
        head.append(r.model_copy(update={"score": round(r.score + adjustment(f, app), 2), "note": note.strip()}))
    return sorted(head, key=lambda r: r.score, reverse=True) + list(recs[top:]), fits
