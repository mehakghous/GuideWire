"""The app's one door to Ayesha's ingestion code: text in, a step list (or a plain message) out.

This version is OFFLINE: it calls `ingestion.router.route`, which uses the catalog and the parsers and never calls a model or the network
(`api_calls` and `network_calls` stay 0). It understands written instructions (one per line), pasted timed transcripts (SRT/VTT/timed text)
and a hand-made step list in JSON, because `route` detects those forms itself.
A YouTube link needs the AI gateway (keys, `POST /v1/extract`); that connection is not made yet, so a link is answered with a clear message
and nothing is sent anywhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.router import route
from shared.step_record import StepList

APPS = ("blender", "maya", "houdini")
_YOUTUBE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)
YOUTUBE_MESSAGE = ("YouTube links need the AI gateway, which is not connected to the app yet. "
                   "For now paste the instructions (one per line) or a timed transcript.")


@dataclass
class PipelineResult:
    steps: StepList | None
    message: str = ""                                    # what to tell the user when there are no steps, or the main note when there are
    notes: list[str] = field(default_factory=list)       # assumptions, caveats and questions from the pipeline, in plain words
    route: str = ""
    api_calls: int = 0
    network_calls: int = 0


MAX_VIDEO_S = 25 * 60                                   # a longer video is refused: it would cost more and take too long for the app to wait


def default_video_provider():
    """The real model for turning a video into steps: Gemini 3.6 Flash behind the cost guard (cache, ceilings, log). Raises RuntimeError with a plain message when no key is set."""
    from dotenv import load_dotenv

    from ingestion.budget import BudgetedProvider, BudgetExceeded, Ceilings, api_key_for
    from ingestion.providers.gemini import GeminiProvider
    load_dotenv()
    try:
        return BudgetedProvider(GeminiProvider(api_key=api_key_for("default")), ceilings=Ceilings.from_env(max_usd_run=0.6), label="default")
    except BudgetExceeded as e:
        raise RuntimeError("The AI model is not set up on this computer: put GEMINI_API_KEY in the .env file.") from e


def video_steps(url: str, app: str = "blender", *, provider_factory=None, fetch_meta=None, group: bool = True, on_status=None) -> PipelineResult:
    """A YouTube link in, a step list out: read the video's title and length, have the model watch it (the prompt chosen by measurement for this application), then give the steps display groups.
    Never raises: every failure comes back as a plain message and no steps. `provider_factory` and `fetch_meta` are injected so tests need no network."""
    from ingestion.extract import ExtractionError, extract_from_video, recommended_video_prompt_version
    from ingestion.grouping import group_steps
    from ingestion.youtube.metadata import fetch_metadata, parse_video_id
    say = on_status or (lambda _m: None)
    if provider_factory is None:
        return PipelineResult(None, YOUTUBE_MESSAGE, route="youtube")
    if app not in APPS:
        return PipelineResult(None, f"Unknown application {app!r}: choose one of {', '.join(APPS)}.")
    m = _YOUTUBE.search(url or "")
    try:
        vid = parse_video_id(m.group(0) if m else url)
    except Exception:
        return PipelineResult(None, "That does not look like a YouTube link. Paste the full address of the video.")
    say("Looking up the video...")
    title, duration = None, None
    try:
        md = (fetch_meta or fetch_metadata)(vid)
        if md.privacy_status != "public":
            return PipelineResult(None, f"The video is '{md.privacy_status}': GuideWire can only read public videos.")
        title, duration = md.title, md.duration_s
    except Exception:
        pass                                                # no YouTube key or no network: go on without the length (the steps still work, the cost estimate is rougher)
    if duration and duration > MAX_VIDEO_S:
        return PipelineResult(None, f"That video is {duration / 60:.0f} minutes long. For now GuideWire reads videos up to {MAX_VIDEO_S // 60} minutes: choose a shorter one, or one chapter of it.")
    try:
        provider = provider_factory()
    except Exception as e:
        return PipelineResult(None, str(e))
    if hasattr(provider, "video_seconds"):
        provider.video_seconds = duration
    say("The AI is watching the video. This takes about one to two minutes...")
    try:
        sl = extract_from_video(provider, vid, app=app, duration_s=duration, title_hint=title, prompt_version=recommended_video_prompt_version(app, True))
    except ExtractionError as e:
        return PipelineResult(None, f"The AI could not turn that video into valid steps ({str(e)[:160]}). Try another video.")
    except Exception as e:                                   # quota, network, budget stop
        return PipelineResult(None, f"The video could not be read right now ({type(e).__name__}). Try again in a minute.")
    if title and not sl.title:
        sl = sl.model_copy(update={"title": title})
    notes = [f"Drafted automatically by {sl.model_id} ({sl.prompt_version}) from the video; review the steps before you use them."]
    if group:
        say("Grouping the steps...")
        try:
            sl = group_steps(sl, provider_factory())
        except Exception:
            pass
        if not any(s.group_id for s in sl.steps):               # group_steps never raises: on a failure it returns the steps unchanged with a warning
            notes.append("The steps could not be grouped; they are shown one by one.")
    return PipelineResult(sl, f"{len(sl.steps)} steps found" + (f" in {len(sl.groups)} groups." if any(s.group_id for s in sl.steps) else "."), notes, "youtube_video", api_calls=1, network_calls=1)


def request_steps(text: str, app: str = "blender", *, duration_s: float | None = None) -> PipelineResult:
    text = (text or "").strip()
    if not text:
        return PipelineResult(None, "Paste the tutorial steps first.")
    if app not in APPS:
        return PipelineResult(None, f"Unknown application {app!r}: choose one of {', '.join(APPS)}.")
    if _YOUTUBE.search(text):
        return PipelineResult(None, YOUTUBE_MESSAGE, route="youtube")
    try:
        b = route(text, app=app, duration_s=duration_s)
    except ValueError as e:                              # for example malformed JSON or an invalid step list
        return PipelineResult(None, f"Could not read that input: {e}")
    notes = [*b.assumptions, *b.caveats, *b.questions]
    if b.steps is not None and b.steps.steps:
        return PipelineResult(b.steps, f"{len(b.steps.steps)} steps found.", notes, b.route, b.api_calls, b.network_calls)
    reason = b.clarification or b.fallback_reason or next((e.text for e in b.explanations), "") or "No steps were found in that text."
    return PipelineResult(None, reason, notes, b.route, b.api_calls, b.network_calls)
