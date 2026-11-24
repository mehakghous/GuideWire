"""The app's door to the question answering: type a question, get an answer and, when the answer is a list of steps, the steps themselves.

No Qt in here, so it is fully testable. It wraps ingestion's `Service` (the same code as `python -m ingestion.cli chat`):
  * with no tutorial chosen, "where do I start", "what before rigging", "give me the steps to ..." come back as a STEP LIST built from the knowledge base (no model call),
    other questions are answered by the rules, or by the AI model when the model is switched on;
  * with a tutorial chosen, the tutorial is loaded so "what is he doing at 1:30", "go back to ...", "what's next" work on its steps; with a video link the AI can also look at the video clip
    when the steps cannot answer.
A conversation is kept per (application, tutorial): changing either starts a new one. Nothing is saved except by the caller.

What a CHAT remembers lives in `app.chat_context.ChatContext` (`Asker.context`): the tutorials it recommended, the last search, and the guide made from a video. That is what lets
"turn the first one into steps", "which one is best for beginners" and "explain step 4" be answered without loading anything by hand. A video is turned into steps by the same
`app.pipeline.video_steps` the New tutorial screen uses (`video_runner`); the screen saves the result as a normal tutorial.
"""
from __future__ import annotations

import inspect
import re
import threading
from dataclasses import dataclass, field

from ingestion.service import Service
from ingestion.session import Session
from shared.step_record import StepList

from .chat_context import (DEFAULT_COUNT, DEFAULT_PATH_COUNT, PATH_STAGES, app_in_text, goal_label, is_broad_goal, path_quota, ChatContext, Video, best_of, clearly_general, describe_step, has_topic, is_retry, requested_count, resolve_video, step_number, tutorial_specific,
                           video_details, video_id, wants_best, wants_details, wants_more, wants_selection, wants_steps_from_video, which_one)


def _for_the_app(text: str) -> str:
    """The terminal chat ends some answers with "(say /load last ...)": a command that means nothing in the app, where there is a Save button instead."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("(say /load")).strip()


_WANTS_TUTORIAL = re.compile(r"\b(tutorials?|videos?|recommend\w*|suggest\w*|courses?)\b", re.I)
_NOT_A_REQUEST = re.compile(r"\b(steps?|why|at \d|what is he|what's next|done)\b", re.I)
VIDEO_TIMEOUT_S = 15 * 60                                  # a video that takes longer than this to read is given up on (the app never waits for ever)


def asks_for_a_tutorial(text: str) -> bool:
    """'recommend a tutorial for rigging a leg', 'find me a video on skinning', 'give me 10 tutorials': a request for something to WATCH, not a question about a tutorial already chosen."""
    return bool(_WANTS_TUTORIAL.search(text)) and not _NOT_A_REQUEST.search(text)


def format_suggestions(r, wanted: int | None = None, goal: str = "") -> str:
    """The suggestions as plain text: title, creator, length, publication date and link of each, and plainly 'not available' for what the video's metadata did not give."""
    if not r.suggestions:
        return r.message or "I found nothing that fits."
    n = len(r.suggestions)
    lines = []
    for i, s in enumerate(r.suggestions, 1):
        v = _video_of(s, r.app or "")
        lines.append(f"{i}. {s.title}\n   {v.details()}\n   {s.url}")
    head = f"Here are {n} tutorial{'s' if n != 1 else ''} that fit" + (f" \"{goal}\"" if goal else "") + ":"
    if wanted and n < wanted:
        head += f"\nYou asked for {wanted}, but only {n} {'were' if n != 1 else 'was'} relevant to that, so I did not add unrelated videos to fill the list."
    tail = "\n".join(r.notes[-1:])
    return head + "\n" + "\n".join(lines) + (f"\n{tail}" if tail else "") + "\nSay \"turn the first one into steps\" (or use its Turn into steps button) to get its steps here."


def _video_of(s, app: str = "") -> Video:
    return Video(s.title, s.url, s.channel or "", s.minutes, getattr(s, "published", "") or "", s.video_id or video_id(s.url), s.note or "", float(s.score or 0.0), app)


@dataclass
class AskResult:
    text: str
    steps: StepList | None = None          # a step list the user can save as a tutorial (a starter plan, steps for a topic)
    route: str = ""
    used_model: bool = False
    headline: str = ""                     # with videos: the short line shown above their cards (`text` is the whole list, for a plain transcript)
    videos: list[Video] = field(default_factory=list)       # the tutorials this answer recommends: each gets a card with its own Turn into steps action
    guide: StepList | None = None          # a guide just made from a video: the screen saves it as a tutorial
    guide_video: Video | None = None
    failed_video: Video | None = None      # a video whose steps could not be made: it gets a Retry
    reused_tutorial_id: int | None = None  # the guide is an already saved tutorial (nothing new to save)


def _run_limited(fn, seconds: float):
    """Run `fn` and give up after `seconds` (TimeoutError). The work cannot be cancelled, but the app stops waiting for it and says so."""
    box: dict = {}

    def work() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:               # noqa: BLE001 - handed back to the caller
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"no answer after {int(seconds)} seconds")
    if "error" in box:
        raise box["error"]
    return box["value"]


class Asker:
    def __init__(self, model_factory=None, discover=None, video_runner=None, video_timeout_s: float = VIDEO_TIMEOUT_S):
        """`model_factory()` returns a ModelAnswerer (or raises when no key is set). None means the AI model is not available.
        `discover(goal, app[, limit=, exclude=])` -> DiscoveryResult; None = tutorial requests go to the knowledge base's own answer.
        `video_runner(url, app, on_status)` -> PipelineResult is what turns a video into steps (app.pipeline.video_steps); None = no AI for videos on this computer.
        `saved_tutorials` ({video id: (StepList, title, tutorial id)}) is filled by the caller, on the thread that owns the database, with the tutorials already saved from videos of this chat, so a video is not read twice."""
        self.model_factory = model_factory
        self.discover = discover
        self.video_runner = video_runner
        self.saved_tutorials: dict[str, tuple[StepList, str, int]] = {}
        self.video_timeout_s = video_timeout_s
        self.context = ChatContext()
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
        """Forget the answering session (the application or the tutorial changed). What the chat remembers (`context`) stays."""
        self._svc = self._key = None

    def new_conversation(self, context: ChatContext | None = None) -> None:
        """A different chat: its own memory (None = an empty one)."""
        self.context = context or ChatContext()
        self.reset()

    # ------------------------------------------------------------------ the one door
    def ask(self, text: str, app: str, *, tutorial: StepList | None = None, title: str | None = None, url: str | None = None, use_model: bool = False,
            on_status=None, action: str = "", video_key: str = "") -> AskResult:
        """`action` is "steps" or "select" with `video_key` when a card's button was pressed: the video is named outright, nothing is guessed."""
        text = (text or "").strip()
        if not text:
            return AskResult("Type a question first.")
        say = on_status or (lambda _m: None)
        ctx = self.context
        pending, ctx.pending = ctx.pending, ""                                    # a "which one?" question is answered by the next message only
        try:
            if action in ("steps", "select") and video_key:
                v = next((x for x in ctx.videos if x.key == video_key), None)
                if v is None:
                    return AskResult("That tutorial is no longer in this chat.", route="context")
                return self._steps_for(v, app, say) if action == "steps" else self._select(v)
            if is_retry(text):
                v = self._failed_video()
                if v is None:
                    return AskResult("There is nothing to retry: no video failed to turn into steps in this chat.", route="context")
                return self._steps_for(v, app, say)
            if pending == "make_steps" and len(text.split()) <= 8 and not asks_for_a_tutorial(text):
                res = resolve_video(text, ctx, strict=True)
                if res.video is not None:
                    return self._steps_for(res.video, app, say)
            if wants_steps_from_video(text, ctx):
                return self._steps_request(text, app, say)
            have = tutorial if tutorial is not None else ctx.guide_steps
            n = step_number(text)
            if n is not None and have is not None:
                return AskResult(describe_step(have, n), None, "tutorial_step", False)
            if ctx.shown and wants_selection(text) and not asks_for_a_tutorial(text):
                res = resolve_video(text, ctx, strict=True)
                if res.video is not None:
                    return self._select(res.video)
                if res.problem:
                    return AskResult(res.problem, None, "context", False)
            if wants_best(text) and (ctx.videos or re.search(r"\b(tutorials?|videos?|which one|these|those)\b", text, re.I)):
                return AskResult(best_of(text, [ctx.videos[i] for i in ctx.shown] or ctx.videos), None, "context", False)
            if ctx.videos and wants_details(text):
                res = resolve_video(text, ctx)
                if res.video is not None:
                    ctx.focus = ctx.index_of(res.video)
                    return AskResult(video_details(res.video), None, "context", False)
                if res.ambiguous:
                    ctx.pending = "details"
                    return AskResult(which_one(res.candidates, "hear about"), None, "clarify", False)
            if self.discover is not None and asks_for_a_tutorial(text):
                return self._find(text, app, say)
            return self._answer(text, app, tutorial, title, url, use_model)
        except Exception as e:                                                      # the chat must never end on an error of its own
            return AskResult(f"Sorry, something went wrong on my side ({type(e).__name__}). Try again.", None, "error", False)

    # ------------------------------------------------------------------ finding tutorials
    def _call_discover(self, goal: str, app: str, limit: int, exclude: list[str], check: bool | None = None):
        try:
            params = inspect.signature(self.discover).parameters
        except (TypeError, ValueError):
            params = {}
        var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        kw = {}
        if "limit" in params or var_kw:
            kw["limit"] = limit
        if exclude and ("exclude" in params or var_kw):
            kw["exclude"] = exclude
        if check is not None and ("check" in params or var_kw):
            kw["check"] = check
        return self.discover(goal, app, **kw)

    def _find(self, text: str, app: str, say) -> AskResult:
        ctx = self.context
        wanted, clamped = requested_count(text)
        more = wants_more(text)
        app = app_in_text(text) or app                                           # "...in Maya" means Maya, whatever the toggle says
        label = {"blender": "Blender", "maya": "Maya", "houdini": "Houdini"}.get(app, app)
        if is_broad_goal(text) or (not has_topic(text) and ctx.last_path and ctx.last_goal):
            return self._find_path(text, app, wanted, clamped, more, say)                # "learn Blender", "10 tutorials after which I can make whatever I want": an ordered path, not one topic
        new_goal = has_topic(text)
        if new_goal:
            goal = text
        elif ctx.last_goal:
            goal, app = ctx.last_goal, ctx.last_app or app                         # "give me 10 tutorials", "more": the same goal as before
        else:
            return AskResult(f"What do you want to learn in {label}? Tell me the task (for example rigging a leg with IK) and your level, and I will search for that"
                             + (f" and show up to {wanted} tutorials" if wanted else "") + f". Or say \"{label} for beginners\" and I will put together a path from the basics.", None, "clarify", False)
        limit = wanted or DEFAULT_COUNT
        say("Searching for tutorials...")
        try:
            r = self._call_discover(goal, app, limit, ctx.known_ids() if more else [])
        except Exception as e:
            return AskResult(f"I could not search for tutorials right now ({type(e).__name__}). Try again in a moment.", None, "discovery", False)
        sug = list(r.suggestions)[:limit]
        r.suggestions = sug
        if not sug:
            if more and ctx.videos:
                return AskResult(r.message or "I found no more relevant tutorials beyond the ones I already showed you. Try describing a different part of the task.", None, "discovery", False)
            return AskResult(r.message or "I found nothing that fits.", None, "discovery", False)
        ctx.last_goal, ctx.last_app = goal, r.app or app
        videos = ctx.add_videos([_video_of(s, r.app or app) for s in sug])
        ctx.last_path = False
        full = format_suggestions(r, wanted, goal_label(goal) if new_goal else "")
        n = len(videos)
        head = f"Here {'are' if n != 1 else 'is'} {n}{'' if new_goal else ' more'} tutorial{'s' if n != 1 else ''} for \"{goal_label(goal)}\"."
        if wanted and n < wanted:
            head += f"\nYou asked for {wanted}, but only {n} {'were' if n != 1 else 'was'} relevant to that, so I did not add unrelated videos to fill the list."
        if clamped:
            head += "\nI can show at most 20 at a time."
        if r.message:
            head += "\n" + r.message
        tail = "\n".join(r.notes[-1:])
        head += (f"\n{tail}" if tail else "") + "\nPick one with Turn into steps, or tell me which one (for example: turn the first one into steps)."
        return AskResult(full, None, "discovery", False, headline=head, videos=videos)

    def _find_path(self, text: str, app: str, wanted: int | None, clamped: bool, more: bool, say) -> AskResult:
        """A learning path for the whole application: the subject areas a beginner meets in order (interface, modeling, materials, lighting and rendering, animation, a whole project), each searched like
        any other goal, a few tutorials each, so that together they take someone from nothing to making their own things. Nothing is added to fill a stage that has no relevant video."""
        ctx = self.context
        label = {"blender": "Blender", "maya": "Maya", "houdini": "Houdini"}.get(app, app)
        n = wanted or DEFAULT_PATH_COUNT
        known = ctx.known_ids() if more else []
        quotas = path_quota(n)
        pool: list[list[Video]] = []
        for (stage, query), q in zip(PATH_STAGES, quotas):
            say(f"Searching for {stage.lower()} tutorials...")
            try:
                r = self._call_discover(f"{label} {query}", app, q + 1, known + [v.key for vs in pool for v in vs], check=False)
            except Exception as e:
                if not any(pool):
                    return AskResult(f"I could not search for tutorials right now ({type(e).__name__}). Try again in a moment.", None, "discovery", False)
                pool.append([])
                continue
            got = [_video_of(s, r.app or app) for s in list(r.suggestions)[:q + 1]]
            for v in got:
                v.stage = stage
            pool.append(got)
        chosen = [vs[:q] for vs, q in zip(pool, quotas)]                              # each stage's share first ...
        spare = [v for vs, q in zip(pool, quotas) for v in vs[q:]]
        for v in spare:                                                                # ... then a stage that came up short is made up from another stage's extra, never from unrelated videos
            if sum(map(len, chosen)) >= n:
                break
            chosen[next(i for i, vs in enumerate(pool) if v in vs)].append(v)
        found = [v for vs in chosen for v in vs]
        if not found:
            return AskResult(f"I found no relevant {label} tutorials for a path from the basics right now. Try again later, or tell me one thing you want to make or learn.", None, "discovery", False)
        ctx.last_goal, ctx.last_app, ctx.last_path = text, app, True
        videos = ctx.add_videos(found)
        lines = []
        for i, v in enumerate(videos, 1):
            lines.append(f"{i}. [{v.stage}] {v.title}\n   {v.details().split(' | ', 1)[1]}\n   {v.url}")
        stages = [st for st, _q in PATH_STAGES if any(v.stage == st for v in videos)]
        head = (f"Here {'is' if len(videos) == 1 else 'are'} {len(videos)} {label} tutorial{'s' if len(videos) != 1 else ''}, ordered as a path from the basics to making your own things: "
                + ", ".join(stages) + ". Watch them in this order.")
        if wanted and len(videos) < wanted:
            head += f"\nYou asked for {wanted}, but only {len(videos)} {'were' if len(videos) != 1 else 'was'} relevant, so I did not add unrelated videos to fill the list."
        if clamped:
            head += "\nI can show at most 20 at a time."
        head += ("\nThe order is by subject: they are judged from title, creator and length only, GuideWire has not watched them, and no one video teaches everything."
                 "\nPick one with Turn into steps, or tell me which one (for example: turn the first one into steps).")
        return AskResult(head + "\n" + "\n".join(lines), None, "discovery", False, headline=head, videos=videos)

    # ------------------------------------------------------------------ choosing and turning a video into steps
    def _select(self, v: Video) -> AskResult:
        ctx = self.context
        ctx.focus = ctx.index_of(v)
        more = "Its steps are ready: ask me about any step." if v.status == "done" else "Say \"turn it into steps\" and I will make its steps here."
        return AskResult(f"Picked \"{v.title}\". {more}", None, "context", False)

    def _failed_video(self) -> Video | None:
        ctx = self.context
        if ctx.focus_video is not None and ctx.focus_video.status == "failed":
            return ctx.focus_video
        return next((v for v in reversed(ctx.videos) if v.status == "failed"), None)

    def _steps_request(self, text: str, app: str, say) -> AskResult:
        ctx = self.context
        res = resolve_video(text, ctx)
        if res.problem:
            return AskResult(res.problem, None, "context", False)
        if res.new_url:
            v = Video("This video", res.new_url, video_id=video_id(res.new_url), app=app)
            ctx.videos.append(v)
            return self._steps_for(v, app, say)
        if res.video is not None:
            return self._steps_for(res.video, app, say)
        if res.ambiguous:
            ctx.pending = "make_steps"
            return AskResult(which_one(res.candidates), None, "clarify", False)
        return AskResult("There is no video to turn into steps yet: I have not recommended one in this chat and you have not given me a link. "
                         "Ask me to find tutorials for what you want to learn, or paste a YouTube link and say \"turn this into steps\".", None, "context", False)

    def _steps_for(self, v: Video, app: str, say) -> AskResult:
        ctx = self.context
        i = ctx.index_of(v)
        ctx.focus = i
        if v.status == "done" and ctx.guide_steps is not None and ctx.guide_video == i:
            return AskResult(self._guide_text(v, ctx.guide_steps, []) + "\n(These steps were already made in this chat.)", None, "video_steps", False, guide_video=v)
        saved = self.saved_tutorials.get(v.key)
        if saved is not None:
            steps, saved_title, tid = saved
            v.status, v.error, v.tutorial_id = "done", "", tid
            ctx.guide_steps, ctx.guide_title, ctx.guide_video, ctx.guide_tutorial_id = steps, saved_title, i, tid
            return AskResult(self._guide_text(v, steps, []) + f"\nYou already had these steps saved as \"{saved_title}\", so I used them instead of reading the video again.", None, "video_steps", False,
                             guide=steps, guide_video=v, reused_tutorial_id=tid)
        if self.video_runner is None:
            v.status, v.error = "failed", "the AI model for videos is not set up on this computer (GEMINI_API_KEY in the .env file)"
            return AskResult(f"I cannot turn \"{v.title}\" into steps here: {v.error}.", None, "video_steps", False, failed_video=v)
        v.status, v.error = "processing", ""
        say(f"Reading \"{v.title}\"...")
        try:
            result = _run_limited(lambda: self.video_runner(v.url, v.app or app, say), self.video_timeout_s)
        except TimeoutError:
            v.status, v.error = "failed", "it took too long (more than %d minutes)" % max(1, round(self.video_timeout_s / 60))
            return AskResult(f"I gave up turning \"{v.title}\" into steps: {v.error}. Say \"try again\" to retry, or pick a shorter video.", None, "video_steps", False, failed_video=v)
        except Exception as e:
            v.status, v.error = "failed", f"{type(e).__name__}"
            return AskResult(f"I could not turn \"{v.title}\" into steps ({v.error}). Say \"try again\" to retry.", None, "video_steps", False, failed_video=v)
        if result.steps is None or not result.steps.steps:
            v.status, v.error = "failed", (result.message or "no steps were found").strip()
            return AskResult(f"I could not turn \"{v.title}\" into steps: {v.error}\nNothing was saved. Say \"try again\" to retry, or pick another tutorial.", None, "video_steps", False, failed_video=v)
        steps = result.steps
        v.status, v.error = "done", ""
        ctx.guide_steps, ctx.guide_title, ctx.guide_video, ctx.guide_tutorial_id = steps, steps.title or v.title, i, None
        return AskResult(self._guide_text(v, steps, result.notes), None, "video_steps", False, guide=steps, guide_video=v)

    @staticmethod
    def _guide_text(v: Video, steps: StepList, notes: list[str]) -> str:
        shown = steps.steps[:12]
        lines = [f"I made {len(steps.steps)} steps from \"{v.title}\":"] + [f"  {s.order}. {s.goal}" for s in shown]
        if len(steps.steps) > len(shown):
            lines.append(f"  ... and {len(steps.steps) - len(shown)} more")
        lines += [f"Note: {n}" for n in notes[:2]]
        lines.append("Ask me about any step (for example: explain step 4).")
        return "\n".join(lines)

    # ------------------------------------------------------------------ answering a question
    def _answer(self, text: str, app: str, tutorial: StepList | None, title: str | None, url: str | None, use_model: bool) -> AskResult:
        ctx = self.context
        about = tutorial_specific(text)
        have, htitle, hurl = tutorial, title, url
        if have is None and ctx.guide_steps is not None:
            gv = ctx.video_at(ctx.guide_video)
            have, htitle, hurl = ctx.guide_steps, ctx.guide_title or None, gv.url if gv else None
        if about and have is None:
            if ctx.videos:
                return AskResult("I cannot say what the instructor does yet: no tutorial has been turned into steps in this chat. "
                                 "Say \"turn the first one into steps\" (or pick another) and then ask me about it.", None, "context", False)
            return AskResult("There is no tutorial in this chat yet, so I cannot say what an instructor does. Ask me to find tutorials for what you want to learn, "
                             "or pick one of your tutorials below the box. Meanwhile I can answer general questions about the software.", None, "context", False)
        general = have is not None and clearly_general(text)                        # a question about the software, not the tutorial: answered as one, not from its steps
        use_tut = have if (have is not None and not general) else None
        out = self._ask_service(text, app, use_tut, htitle, hurl, use_model)
        if general:
            out.text += "\n(This is a general answer about the software, not something from the tutorial.)"
        return out

    def _ask_service(self, text: str, app: str, tutorial: StepList | None, title: str | None, url: str | None, use_model: bool) -> AskResult:
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
    from shared.paths import load_env

    from ingestion.answer_model import ModelAnswerer, default_manual
    from ingestion.budget import TIERS, BudgetedProvider, BudgetExceeded, Ceilings, api_key_for
    from ingestion.providers.gemini import GeminiProvider
    load_env()
    try:
        provider = BudgetedProvider(GeminiProvider(api_key=api_key_for("default"), model=TIERS["iterate"]), ceilings=Ceilings.from_env(max_usd_run=0.5), label="default")
    except BudgetExceeded as e:
        raise RuntimeError("The AI model is not set up on this computer: put GEMINI_API_KEY in the .env file.") from e
    return ModelAnswerer(provider, manual=default_manual(), recheck=has_video, recheck_sweep=3 if has_video else 0)
