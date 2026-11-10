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
