"""The app's connection to the GuideWire AI service (the gateway): video reading, answers and YouTube lookups without any provider key on the learner's computer (product audit H-2).

`connection()` returns the gateway client when GUIDEWIRE_GATEWAY_URL and GUIDEWIRE_GATEWAY_TOKEN are set, else None; the app then falls back to keys on this computer (development). Nothing here
knows about providers: it sends the question or the link, and gets the same objects back (StepList, AnswerBundle) that the local path produces, validated on arrival."""
from __future__ import annotations

from types import SimpleNamespace

from ingestion.gateway_client import GatewayClient
from ingestion.providers.base import ProviderError
from shared.answer import AnswerBundle


def connection(env: dict[str, str] | None = None) -> GatewayClient | None:
    return GatewayClient.from_env(env)


def tutorial_brief(session, *, video_url: str | None = None) -> dict | None:
    """The tutorial and where the learner is in it, as the gateway's TutorialIn expects (brief: the request is limited to 64 KB). None when no tutorial is loaded."""
    sl = getattr(session, "steps", None)
    if session is None or sl is None or not sl.steps:
        return None
    steps = [{"id": s.id, "goal": s.goal[:300], "start_s": s.video_start_s, "how_to": [h.text[:200] for h in s.how_to[:3]]} for s in sl.steps[:120]]
    meta = getattr(session, "tutorial", None) or {}
    return {"title": (sl.title or meta.get("title") or "")[:200] or None, "app_version": sl.app_version_tutorial, "video_url": video_url or meta.get("url"),
            "steps": steps, "current": getattr(session, "current", None)}


class GatewayAnswerer:
    """Same call as ingestion.answer_model.ModelAnswerer, answered by the gateway: `answerer(question, session)` -> AnswerBundle."""

    def __init__(self, client: GatewayClient, *, has_video: bool = False):
        self.client, self.has_video = client, has_video

    def __call__(self, question: str, session=None, app: str | None = None) -> AnswerBundle:
        app = app or (session.app if session is not None else "blender")
        turns = [t.user for t in list(getattr(session, "turns", []))[-3:]] if session is not None else []
        raw = self.client.answer(question, app=app, model=True, tutorial=tutorial_brief(session), version=getattr(session, "version", None), history=[t[:300] for t in turns])
        try:
            return AnswerBundle.model_validate(raw)
        except ValueError as e:
            raise ProviderError("the GuideWire service sent an answer GuideWire could not read") from e


def answer_factory(client: GatewayClient):
    """The `model_factory` of app.ask.Asker, backed by the gateway."""
    return lambda has_video=False: GatewayAnswerer(client, has_video=has_video)


def video_metadata(client: GatewayClient, video_id: str):
    """What app.pipeline.video_steps needs to know about a video (privacy_status, title, duration_s), looked up by the gateway. Raises ProviderError when it cannot be looked up."""
    rows = client.videos([video_id])
    if not rows:
        raise ProviderError("that video could not be found")
    r = rows[0]
    return SimpleNamespace(privacy_status=r.get("privacy") or "public", title=r.get("title"), duration_s=r.get("duration_s"))


def discovery_functions(client: GatewayClient):
    """(search, metadata) for app.discovery, answered by the gateway's YouTube endpoints (same shapes as ingestion.youtube.api.search_videos and videos_metadata)."""
    return (lambda query, n: client.search(query, n)), client.videos
