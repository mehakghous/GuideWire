"""What Ask GuideWire remembers inside one conversation, and how it reads what the person says against it. No Qt, no database, no network: fully testable.

A chat keeps:
  * the tutorials (videos) the assistant recommended, and which of them is in focus (picked, or the one just talked about);
  * the last search (its words and application), so "10 more" or "give me 10 tutorials" means more of the SAME goal;
  * the guide made from a video (its steps, and the tutorial it was saved as), so "explain step 4" and "what does he do in step 3" are about it.

The functions here turn words into decisions: how many tutorials were asked for, whether a message asks to turn a video into steps, which video "the first one", "this" or "the leg IK one" means (or that it
cannot be told), whether the question is about a tutorial or a general one about the software. Nothing here makes up content: a step is described only from what its record holds.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ingestion.rigging_discovery import CHATTER
from shared.step_record import Step, StepList

DEFAULT_COUNT = 3                                   # what "recommend a tutorial" gets when no number is asked for
MAX_COUNT = 20                                      # the most one request can return (the pool of two searches)
APPS = ("blender", "maya", "houdini")

_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6, "seventh": 7, "7th": 7,
             "eighth": 8, "8th": 8, "ninth": 9, "9th": 9, "tenth": 10, "10th": 10}
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20}
_NUM = r"(?:\d{1,3}|" + "|".join(_NUMBERS) + r")"
_VIDEO_NOUN = r"(?:tutorials?|videos?|courses?|lessons?|walk-?throughs?)"
_COUNT = re.compile(rf"\b({_NUM})\b(?!\s*(?:min|mins|minutes?|hours?|hrs?|seconds?|steps?|parts?|k\b|%))(?:\s+[\w'-]+){{0,3}}?\s+{_VIDEO_NOUN}\b", re.I)
_TOP_COUNT = re.compile(rf"\btop\s+({_NUM})\b", re.I)
_YOUTUBE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)
_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})")


def video_id(url: str) -> str:
    m = _VIDEO_ID.search(url or "")
    return m.group(1) if m else ""


def requested_count(text: str) -> tuple[int | None, bool]:
    """(how many tutorials were asked for or None, whether that was more than one request can give). "give me 10 tutorials" -> (10, False); "a 10 minute tutorial" -> (None, False)."""
    m = _COUNT.search(text or "") or _TOP_COUNT.search(text or "")
    if not m:
        return None, False
    raw = m.group(1).lower()
    n = int(raw) if raw.isdigit() else _NUMBERS[raw]
    if n < 1:
        return None, False
    return min(n, MAX_COUNT), n > MAX_COUNT


_FILLER = frozenset("""give me us show find get want need looking look for some any more another other different additional new good best top great please can could would you i a an the of on in with
about to and also plus my is are tutorial tutorials video videos course courses lesson lessons recommend recommendation suggest suggestions suggest more again too else ones one please
list links link""".split()) | set(_NUMBERS) | set(APPS)


def has_topic(text: str) -> bool:
    """Does a request say WHAT to learn ("rig a leg with IK"), or only ask for more of something ("give me 10 tutorials")?"""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return any(w not in _FILLER and w not in CHATTER and not w.isdigit() for w in words)


# a request to learn a whole application, not one technique: "10 tutorials for Blender after which I can make whatever I want", "learn Blender from scratch", "5 beginner tutorials"
_LEVEL = frozenset("beginner beginners basics basic fundamentals fundamental scratch start started starting intro introduction easy simple newbie zero complete full entire whole learn learning master mastering whatever anything everything".split())


def is_broad_goal(text: str) -> bool:
    """True when the request names no technique, only that the person wants to learn the application or reach a level: it is answered with an ordered learning path, not a search for one topic."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    rest = [w for w in words if w not in _FILLER and w not in CHATTER and w not in _LEVEL and not w.isdigit()]
    return not rest and any(w in _LEVEL for w in words)


# The stages of a learning path for any of the applications: the subject areas a beginner meets in order. Each is searched for the chosen application like any other goal.
PATH_STAGES: tuple[tuple[str, str], ...] = (
    ("Interface and navigation", "interface and navigation basics for beginners"),
    ("Modeling", "modeling basics for beginners"),
    ("Materials and shading", "materials and shading basics for beginners"),
    ("Lighting and rendering", "lighting and rendering basics for beginners"),
    ("Animation", "animation basics for beginners"),
    ("A whole project", "complete beginner project start to finish"),
)
DEFAULT_PATH_COUNT = 6


def path_quota(n: int, stages: int = len(PATH_STAGES)) -> list[int]:
    """How many tutorials each stage gets out of `n`: spread evenly, the earlier stages taking the remainder (10 over 6 stages: 2, 2, 2, 2, 1, 1)."""
    base, extra = divmod(max(n, 1), stages)
    return [base + (1 if i < extra else 0) for i in range(stages)]


_LEAD = re.compile(r"^\W*(?:(?:can|could|would) you\s+|please\s+|i (?:want|need|would like)\s+(?:to\s+)?)*(?:(?:give|show|find|get|recommend|suggest)(?: me| us)?\s+)?(?:\d+|[a-z]+)?\s*(?:tutorials?|videos?|courses?)\s+(?:for|on|about|to learn)\s+", re.I)


def goal_label(text: str) -> str:
    """The request without its leading "can you give 10 tutorials for", so a reply says what the tutorials are FOR, not the whole sentence back."""
    t = (text or "").strip().rstrip("?.! ")
    s = _LEAD.sub("", t).strip()
    return s if len(s) >= 3 else t


_MORE = re.compile(r"\b(more|another|other|different|else|additional|new ones|again)\b", re.I)


def wants_more(text: str) -> bool:
    return bool(_MORE.search(text or ""))


# ---------------------------------------------------------------------------------------------- the videos of a chat
@dataclass
class Video:
    title: str
    url: str
    channel: str = ""
    minutes: int | None = None
    published: str = ""
    video_id: str = ""
    note: str = ""
    score: float = 0.0
    app: str = ""
    status: str = "new"                  # new | processing | done | failed
    error: str = ""                      # why it failed, in plain words
    tutorial_id: int | None = None       # the saved tutorial made from it
    stage: str = ""                      # in a learning path: the subject area this video is the answer for ("Modeling")

    @property
    def key(self) -> str:
        return self.video_id or video_id(self.url) or self.url

    def details(self) -> str:
        """Creator, length and publication on one line, and plainly 'not available' for what is not known."""
        bits = (f"Creator: {self.channel or 'not available'}", f"Length: {self.minutes} min" if self.minutes else "Length: not available", f"Published: {self.published or 'not available'}")
        return " | ".join(((f"Stage: {self.stage}",) if self.stage else ()) + bits)


@dataclass
class ChatContext:
    videos: list[Video] = field(default_factory=list)
    shown: list[int] = field(default_factory=list)          # indexes into `videos` of the latest list the assistant showed: "the first one" means shown[0]
    focus: int | None = None                                # the video being talked about: picked, or the last one referred to
    last_goal: str = ""
    last_app: str = ""
    last_path: bool = False                                 # the last search was a learning path: "10 more" continues it
    guide_tutorial_id: int | None = None                    # the saved tutorial made from a video in this chat
    guide_title: str = ""
    guide_video: int | None = None
    pending: str = ""                                       # "make_steps" while a "which one?" question is waiting for its answer
    guide_steps: StepList | None = field(default=None, repr=False)      # not stored in a chat message: reloaded from the saved tutorial

    # ---- the list
    def add_videos(self, found: list[Video]) -> list[Video]:
        """Remember what a search found (a video already known keeps its state and is not listed twice). The new list becomes the one 'the first one' refers to."""
        shown: list[int] = []
        out: list[Video] = []
        for v in found:
            have = next((i for i, x in enumerate(self.videos) if x.key == v.key), None)
            if have is None:
                self.videos.append(v)
                have = len(self.videos) - 1
            if have not in shown:
                shown.append(have)
                out.append(self.videos[have])
        self.shown = shown
        if self.focus is not None and self.focus not in shown:
            self.focus = None
        return out

    def video_at(self, i: int | None) -> Video | None:
        return self.videos[i] if i is not None and 0 <= i < len(self.videos) else None

    def index_of(self, v: Video) -> int | None:
        return next((i for i, x in enumerate(self.videos) if x is v), None)

    def known_ids(self) -> list[str]:
        return [v.key for v in self.videos]

    @property
    def focus_video(self) -> Video | None:
        return self.video_at(self.focus)

    @property
    def has_guide(self) -> bool:
        return self.guide_steps is not None

    # ---- to and from a chat message's `meta` (so a reopened chat still knows its videos)
    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "guide_steps"}
        for v in d["videos"]:
            if v["status"] == "processing":
                v["status"] = "new"                          # nothing is running after a restart
        return d

    @classmethod
    def from_dict(cls, d: dict | None) -> "ChatContext":
        d = d or {}
        known = Video.__dataclass_fields__
        c = cls([Video(**{k: v for k, v in x.items() if k in known}) for x in d.get("videos", []) if isinstance(x, dict) and x.get("url")])
        n = len(c.videos)
        c.shown = [i for i in d.get("shown", []) if isinstance(i, int) and 0 <= i < n]
        c.focus = d["focus"] if isinstance(d.get("focus"), int) and 0 <= d["focus"] < n else None
        c.guide_video = d["guide_video"] if isinstance(d.get("guide_video"), int) and 0 <= d["guide_video"] < n else None
        c.last_goal, c.last_app, c.last_path = d.get("last_goal", "") or "", d.get("last_app", "") or "", bool(d.get("last_path"))
        c.guide_tutorial_id, c.guide_title, c.pending = d.get("guide_tutorial_id"), d.get("guide_title", "") or "", d.get("pending", "") or ""
        return c


# ---------------------------------------------------------------------------------------------- reading a message
_STEPS = r"(?:steps?|a guide|guide|walk-?through|step[- ]by[- ]step(?: guide)?|instructions)"
_MAKE_A = re.compile(rf"\b(?:turn|convert|transform|change|break|process|extract|generate|make|create|build|produce|write|get|give)\b[^.?!]*\b(?:into|to|as|for|from|out of|of)\b[^.?!]*\b{_STEPS}\b", re.I)
_MAKE_B = re.compile(rf"\b(?:{_STEPS})\b[^.?!]{{0,30}}\b(?:for|from|of|out of)\b[^.?!]*", re.I)
_MAKE_VERB = re.compile(r"\b(?:turn|convert|transform|change|break|process|extract|generate|make|create|build|produce|write|get|give|need|want|do|can|could)\b", re.I)
_REF_WORDS = re.compile(r"\b(?:this|that|it|here|these|those|one|ones|video|tutorial|link|url|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last|previous|earlier|top|[1-9]\d?(?:st|nd|rd|th))\b", re.I)
_RETRY = re.compile(r"^\W*(?:please\s+)?(?:retry|try (?:it |that )?again|have another go|once more|re-?run(?: it)?|do it again|try once more)\W*$", re.I)
_SELECT = re.compile(r"\b(?:select|pick|choose|go with|going with|i'?ll (?:take|use|go with|watch|pick)|let'?s (?:do|use|go with|pick|take)|use|take|open|load|switch to|work (?:on|with))\b", re.I)
_DETAIL = re.compile(r"\b(?:tell me (?:more )?about|more about|more details?|details? (?:of|on|about)|what(?:'s| is) (?:the )?\w+ (?:one|video|tutorial) about|what does (?:the )?\w+ (?:one|video|tutorial) (?:cover|teach|show))\b", re.I)
_BEST = re.compile(r"\b(?:which|what)\b[^.?!]*\b(?:best|better|easiest|easier|simplest|shortest|quickest|fastest|newest|latest|most recent|recommend\w*|should i (?:watch|pick|choose|use|start with|go with)|good for|suits?|right for)\b", re.I)
_EXPLAIN_STEP = re.compile(r"\b(?:explain|describe|elaborate|detail|walk me through|what(?:'s| is| does| do)|tell me about|how (?:do|does|to)|more (?:on|about)|clarify)\b[^.?!]*\bstep\s*(?:number\s*|no\.?\s*|#\s*)?(\d{1,3})\b|\bstep\s*(?:number\s*|no\.?\s*|#\s*)?(\d{1,3})\b[^.?!]*\b(?:explain|mean|about|do|involve)\b", re.I)
_TUTORIAL_MARK = re.compile(r"\b(?:instructor|teacher|author|presenter|narrator|creator|he|she|they|the (?:video|tutorial|guide|lesson)|this (?:video|tutorial|guide|lesson|step|part)|that step|next step|previous step|last step|"
                            r"step\s*\d+|at \d{1,2}:\d{2}|in the (?:video|tutorial)|what(?:'s| is) next|what now|what should i (?:click|do|press|select) (?:next|now)|where was i)\b", re.I)
_GENERAL = re.compile(r"^\W*(?:what(?:'s| is| are| does)\s+(?:an?\s+|the\s+)?[\w /-]{1,40}?\b(?:mean|do)?\W*$|what(?:'s| is| are)\b|how (?:do|can|would|should|to) (?:i|you|we)\b|how to\b|why (?:does|is|do|are|did) my\b|my\b|why (?:does|is|do|are)\b)", re.I)


def app_in_text(text: str) -> str | None:
    """The application a message names, when it names exactly one ("rig a leg in Maya"): what the person typed outranks the chat's toggle."""
    named = [a for a in APPS if re.search(rf"\b{a}\b", text or "", re.I)]
    return named[0] if len(named) == 1 else None


def tutorial_specific(text: str) -> bool:
    """Is this about the tutorial's own content (what the instructor does, a step, a time in the video, what to click next) rather than about the software in general?"""
    return bool(_TUTORIAL_MARK.search(text or ""))


def clearly_general(text: str) -> bool:
    """A question about the software that the tutorial has nothing to do with: "what is IK", "how do I make an IK handle in Maya", "why does my IK knee bend wrong"."""
    return bool(_GENERAL.search(text or "")) and not tutorial_specific(text)


def step_number(text: str) -> int | None:
    m = _EXPLAIN_STEP.search(text or "")
    return int(m.group(1) or m.group(2)) if m else None


def is_retry(text: str) -> bool:
    return bool(_RETRY.search(text or ""))


def wants_steps_from_video(text: str, ctx: ChatContext) -> bool:
    """"turn the first one into steps", "make steps for this tutorial", "turn this video into a guide", "can't I just turn into steps here", or a link with a request for steps."""
    t = _YOUTUBE.sub(" this video ", text or "")                                  # a link has dots in it, which the sentence patterns below stop at
    if not (_MAKE_A.search(t) or (_MAKE_B.search(t) and _MAKE_VERB.search(t)) or re.search(rf"\b(?:turn|convert|make)\b[^.?!]{{0,40}}\binto\b[^.?!]{{0,20}}\b{_STEPS}\b", t, re.I)):
        return False
    if _YOUTUBE.search(text or "") or ctx.videos:
        return bool(_YOUTUBE.search(text or "") or _REF_WORDS.search(t) or ctx.videos)
    # nothing was recommended yet and no link was given: only a clear "turn ... into steps" or a mention of the video itself counts ("give me the steps for it" is an ordinary question)
    return bool(re.search(r"(?<!\w)(?:turn|convert|transform|change|make|create|generate|build)(?!\w)[^.?!]{0,40}(?<!\w)into(?!\w)", t, re.I) or re.search(r"(?<!\w)(?:video|tutorial|link|walk-?through)(?!\w)", t, re.I))


def wants_selection(text: str) -> bool:
    return bool(_SELECT.search(text or "")) and not re.search(_STEPS, text or "", re.I)


def wants_details(text: str) -> bool:
    return bool(_DETAIL.search(text or ""))


def wants_best(text: str) -> bool:
    return bool(_BEST.search(text or ""))


# ---------------------------------------------------------------------------------------------- which video is meant
@dataclass
class Resolution:
    video: Video | None = None
    candidates: list[Video] = field(default_factory=list)     # when it cannot be told: the ones it could be
    problem: str = ""                                          # a reference that cannot be right ("the 12th" of 5)
    new_url: str = ""                                          # a link in the message that is not in the chat yet

    @property
    def ambiguous(self) -> bool:
        return self.video is None and not self.problem and not self.new_url and len(self.candidates) > 1


_STOP = frozenset("the a an this that it one video tutorial tutorials videos turn into steps step make me for from of to and please can i just here guide convert use pick choose select open about tell more with in on my".split()) | set(_ORDINALS) | set(_NUMBERS)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1 and w not in _STOP and not w.isdigit()}


def _ordinal(text: str) -> int | None | str:
    """The position asked for (1 = first), "last", or None."""
    t = (text or "").lower()
    if re.search(r"\b(?:the )?last(?: one)?\b", t) and not re.search(r"\blast (?:step|time|message|question)\b", t):
        return "last"
    for w, n in _ORDINALS.items():
        if re.search(rf"\b{w}\b", t):
            return n
    m = re.search(r"(?:\b(?:number|no\.?|video|tutorial|option|result)\s*|#\s*)(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\W*(\d{1,2})\W*(?:please)?\W*", t)
    return int(m.group(1)) if m else None


_POINTS_BACK = re.compile(r"\b(?:this|that|it|the same|previous|earlier|before|last (?:one|video|tutorial)|that one|this one)\b", re.I)


def resolve_video(text: str, ctx: ChatContext, strict: bool = False) -> Resolution:
    """Which video a message means: a link in it, an ordinal ("the second one", "#3"), a name ("the leg IK one"), "this/that/it/the previous video" (the one in focus), or the only one there is.
    When several could be meant and nothing says which, `ambiguous` is true and `candidates` are what to ask about. With `strict`, only an explicit pointer counts (a link, an ordinal, a name, "this/that/it"): the
    only video in the list is not assumed."""
    t = text or ""
    m = _YOUTUBE.search(t)
    if m:
        url = m.group(0).rstrip(".,)")
        vid = video_id(url)
        have = next((v for v in ctx.videos if vid and v.key == vid), None)
        return Resolution(video=have) if have else Resolution(new_url=url)
    pool = [ctx.videos[i] for i in ctx.shown] or list(ctx.videos)
    if not pool:
        return Resolution()
    o = _ordinal(t)
    if o is not None:
        if o == "last":
            return Resolution(video=pool[-1])
        if 1 <= int(o) <= len(pool):
            return Resolution(video=pool[int(o) - 1])
        return Resolution(problem=f"There {'is only 1 tutorial' if len(pool) == 1 else f'are only {len(pool)} tutorials'} in the list, so there is no number {o}.")
    named = _words(t)
    if named:
        scored = sorted(((len(named & _words(v.title + " " + v.channel)), i) for i, v in enumerate(pool)), reverse=True)
        best = scored[0][0]
        if best >= 1 and (len(scored) == 1 or best > scored[1][0]) and (best >= 2 or len(named) <= 3):
            return Resolution(video=pool[scored[0][1]])
        if best >= 1:
            return Resolution(candidates=[pool[i] for s, i in scored if s == best])
    if _POINTS_BACK.search(t) and ctx.focus_video is not None:
        return Resolution(video=ctx.focus_video)
    if strict:
        return Resolution()
    if ctx.focus_video is not None and len(pool) > 1 and not _POINTS_BACK.search(t) and not named:
        return Resolution(video=ctx.focus_video) if ctx.focus_video in pool else Resolution(candidates=pool)
    if len(pool) == 1:
        return Resolution(video=pool[0])
    return Resolution(candidates=pool)


def which_one(candidates: list[Video], verb: str = "turn into steps") -> str:
    lines = [f"{i}. {v.title}" + (f" ({v.channel})" if v.channel else "") for i, v in enumerate(candidates, 1)]
    return f"Which one do you want me to {verb}? Say the number, or part of its title.\n" + "\n".join(lines)


# ---------------------------------------------------------------------------------------------- answers made from what the chat already holds
_BEGINNER_WORD = re.compile(r"\b(?:beginners?|basics?|basic|intro(?:duction)?|getting started|easy|simple|101|crash course|from scratch|first)\b", re.I)
_ADVANCED_WORD = re.compile(r"\b(?:advanced|expert|masterclass|deep dive|complex|in[- ]depth|production)\b", re.I)


def best_of(text: str, videos: list[Video]) -> str:
    """"Which one is best for beginners / the shortest / the newest" against the list the assistant just showed. It judges from the title, length and date only, and says so."""
    if not videos:
        return "I have not shown you any tutorials in this chat yet. Tell me what you want to learn and I will search."
    t = text.lower()
    if re.search(r"shortest|quickest|fastest|quick", t):
        known = [v for v in videos if v.minutes]
        if not known:
            return "None of these tutorials has a length I can read, so I cannot say which is shortest."
        v = min(known, key=lambda x: x.minutes)
        return f"The shortest is \"{v.title}\" at {v.minutes} min ({v.channel or 'creator not available'}). Say \"turn it into steps\" to get its steps."
    if re.search(r"newest|latest|most recent", t):
        known = [v for v in videos if v.published]
        if not known:
            return "None of these tutorials has a publication date I can read, so I cannot say which is newest."
        v = max(known, key=lambda x: x.published)
        return f"The newest is \"{v.title}\", published {v.published}. Its publication date is the upload date, not when the software version it shows was released."
    beginner = bool(re.search(r"beginner|new to|first time|starting|easiest|easier|simplest|simple|never", t))

    def points(v: Video) -> tuple[float, list[str]]:
        p, why = 0.0, []
        if beginner and _BEGINNER_WORD.search(v.title) and not _ADVANCED_WORD.search(v.title):
            p += 3
            why.append("its title says it is for beginners")
        if _ADVANCED_WORD.search(v.title):
            p -= 3 if beginner else 0
            if beginner:
                why.append("its title says advanced")
        if v.minutes:
            if beginner and 8 <= v.minutes <= 45:
                p += 1
                why.append(f"{v.minutes} min is a length a beginner can follow in one sitting")
            elif beginner and v.minutes > 90:
                p -= 1
                why.append(f"{v.minutes} min is long")
        return p + v.score * 0.1, why

    ranked = sorted(((points(v), i) for i, v in enumerate(videos)), key=lambda x: (-x[0][0], x[1]))
    (_p, why), i = ranked[0]
    v = videos[i]
    reason = ("; ".join(why) if why else "it ranked highest in the search for your goal")
    return (f"From the list, I would start with \"{v.title}\": {reason}. This is judged from titles, lengths and dates only: GuideWire has not watched any of them. "
            "Say \"turn it into steps\" to get its steps.")


def video_details(v: Video) -> str:
    lines = [f"\"{v.title}\"", v.details(), v.url]
    if v.note:
        lines.append(v.note)
    if v.status == "done":
        lines.append("Its steps are already made" + (" and saved as a tutorial." if v.tutorial_id else "."))
    elif v.status == "failed":
        lines.append(f"The last try to turn it into steps failed: {v.error or 'unknown reason'}.")
    else:
        lines.append("Judged from its title, creator and length: GuideWire has not watched it. Say \"turn it into steps\" to get its steps.")
    return "\n".join(lines)


def describe_step(sl: StepList, n: int) -> str:
    """One step explained only from what its record holds: its goal, how to do it, how to tell it worked, where in the video it starts. Nothing is added."""
    if not 1 <= n <= len(sl.steps):
        return f"This guide has {len(sl.steps)} steps, so there is no step {n}."
    s: Step = sl.steps[n - 1]
    out = [f"Step {n} of {len(sl.steps)}: {s.goal}"]
    if s.video_start_s is not None:
        m, sec = divmod(int(s.video_start_s), 60)
        out.append(f"It starts at {m}:{sec:02d} in the video.")
    if s.how_to:
        out.append("How to do it:\n" + "\n".join(f"  - {h.text}" for h in s.how_to))
    elif s.actions:
        acts = [a.ui_element for a in s.actions if a.ui_element]
        if acts:
            out.append("What it uses: " + ", ".join(acts))
    if s.check:
        out.append("How you can tell it worked:\n" + "\n".join(f"  - {h.text}" for h in s.check))
    if s.flags:
        out.append("Notes: " + "; ".join(s.flags[:3]))
    if len(out) == 1:
        out.append("The guide holds nothing more about this step than that line.")
    return "\n".join(out)
