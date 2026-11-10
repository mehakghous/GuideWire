"""The app's door to the question answering: type a question, get an answer and, when the answer is a list of steps, the steps themselves.

No Qt in here, so it is fully testable. It wraps ingestion's `Service` (the same code as `python -m ingestion.cli chat`):
  * with no tutorial chosen, "where do I start", "what before rigging", "give me the steps to ..." come back as a STEP LIST built from the knowledge base (no model call),
    other questions are answered by the rules, or by the AI model when the model is switched on;
  * with a tutorial chosen, the tutorial is loaded so "what is he doing at 1:30", "go back to ...", "what's next" work on its steps; with a video link the AI can also look at the video clip
    when the steps cannot answer.
A conversation is kept per (application, tutorial): changing either starts a new one. Nothing is saved except by the caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.service import Service
from ingestion.session import Session
from shared.step_record import StepList


def _for_the_app(text: str) -> str:
    """The terminal chat ends some answers with "(say /load last ...)": a command that means nothing in the app, where there is a Save button instead."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("(say /load")).strip()


_WANTS_TUTORIAL = re.compile(r"\b(tutorials?|videos?|recommend\w*|suggest\w*)\b", re.I)
_NOT_A_REQUEST = re.compile(r"\b(steps?|why|at \d|what is he|what's next|done)\b", re.I)


def asks_for_a_tutorial(text: str) -> bool:
    """'recommend a tutorial for rigging a leg', 'find me a video on skinning': a request for something to WATCH, not a question about a tutorial already chosen."""
    return bool(_WANTS_TUTORIAL.search(text)) and not _NOT_A_REQUEST.search(text)


def format_suggestions(r) -> str:
    if not r.suggestions:
        return r.message or "I found nothing that fits."
    lines = [f"{i}. {s.title}\n   {s.summary}\n   {s.url}" for i, s in enumerate(r.suggestions, 1)]
    tail = "\n".join(r.notes[-1:])
    return "Here are some tutorials that fit:\n" + "\n".join(lines) + (f"\n{tail}" if tail else "") + "\nTo get its steps, use Find a tutorial on Home and click 'Turn this video into steps'."


@dataclass
class AskResult:
    text: str
    steps: StepList | None = None          # a step list the user can save as a tutorial (a starter plan, steps for a topic)
    route: str = ""
    used_model: bool = False


class Asker:
    def __init__(self, model_factory=None, discover=None):
        """`model_factory()` returns a ModelAnswerer (or raises when no key is set). None means the AI model is not available."""
        self.model_factory = model_factory
        self.discover = discover                  # (goal, app) -> DiscoveryResult; None = tutorial requests go to the knowledge base's own answer
        self._svc: Service | None = None
        self._key: tuple | None = None

    @property
    def model_available(self) -> bool:
        return self.model_factory is not None

    def _service(self, app: str, tutorial: StepList | None, title: str | None, url: str | None, use_model: bool) -> Service:
        key = (app, title if tutorial is not None else None, use_model)
        if self._svc is None or key != self._key:
            svc = Service.open(None, use_kb=True)
            svc.session = Session(app=app)
            svc.app_known = True
            if tutorial is not None:
                rec = {"id": title or "tutorial", "title": title or "tutorial", "source_type": tutorial.source_type, **({"url": url} if url else {})}
                svc.session.load(tutorial, tutorial=rec)
            svc.answerer = self.model_factory(has_video=bool(url)) if (use_model and self.model_factory) else None
            self._svc, self._key = svc, key
        return self._svc

    def reset(self) -> None:
        self._svc = self._key = None

    def ask(self, text: str, app: str, *, tutorial: StepList | None = None, title: str | None = None, url: str | None = None, use_model: bool = False) -> AskResult:
        text = (text or "").strip()
        if not text:
            return AskResult("Type a question first.")
        if tutorial is None and self.discover is not None and asks_for_a_tutorial(text):
            try:
                r = self.discover(text, app)
                return AskResult(format_suggestions(r), None, "discovery", False)
            except Exception as e:
                return AskResult(f"I could not search for tutorials right now ({type(e).__name__}).", None, "discovery", False)
        try:
            svc = self._service(app, tutorial, title, url, use_model)
        except Exception as e:                                           # no key, no network: say so and fall back to the rules
            self.model_factory = None
            svc = self._service(app, tutorial, title, url, False)
            out = svc.message(text)
            return AskResult(f"(The AI model is not available: {str(e)[:120]}. This is the answer from the rules.)\n{_for_the_app(out['text'])}", self._steps(svc), out["route"], False)
        out = svc.message(text)
        steps = self._steps(svc)
        if steps is None and out["route"] == "standalone" and tutorial is None and svc.answerer is None:
            # the rules have no answer for a plain how-to ("how do i bind my mesh in maya"): use the knowledge base's steps for the topic when it has them, instead of the generic deflection
            from ingestion.service import render
            from ingestion.starter_plan import topic_bundle
            b = topic_bundle(text, app)
            if b is not None:
                return AskResult(_for_the_app(render(b)), b.steps, "rigging_knowledge", False)
        return AskResult(_for_the_app(out["text"]), steps, out["route"], out["route"] == "model")

    @staticmethod
    def _steps(svc: Service) -> StepList | None:
        b = svc.last_bundle
        svc.last_bundle = None                                          # a bundle belongs to the answer that made it
        return b.steps if b is not None and b.steps is not None and b.steps.steps else None


def default_model_factory(has_video: bool = False):
    """The real AI for answering: Gemini 3.5 Flash-Lite behind the cost guard, grounded on the knowledge base; with a video link it can also look at a short clip when the steps cannot answer.
    Raises RuntimeError with a plain message when no key is set."""
    from dotenv import load_dotenv

    from ingestion.answer_model import ModelAnswerer, default_manual
    from ingestion.budget import TIERS, BudgetedProvider, BudgetExceeded, Ceilings, api_key_for
    from ingestion.providers.gemini import GeminiProvider
    load_dotenv()
    try:
        provider = BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model=TIERS["iterate"]), ceilings=Ceilings.from_env(max_usd_run=0.5), label="default")
    except BudgetExceeded as e:
        raise RuntimeError("The AI model is not set up on this computer: put GEMINI_API_KEY in the .env file.") from e
    return ModelAnswerer(provider, manual=default_manual(), recheck=has_video, recheck_sweep=3 if has_video else 0)
