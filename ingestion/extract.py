"""Step extraction: written instructions or a public YouTube URL -> validated StepList.

Flow: prompt provider (schema-constrained JSON) -> parse -> sanitise to the closed predicate
vocabulary and add semantic flags -> structural validation. On a parse or structural failure the
provider is re-asked once with ALL violations listed; a second failure raises ExtractionError,
which carries the last parsed (unaccepted) StepList as `.partial` for inspection. Nothing is
silently clamped, dropped or repaired.

Prompt versions:
  v2  the prompt used in all live runs recorded in docs/ingestion-technical-plan.md (baseline,
      timestamps as seconds). Kept unchanged so experiments can compare against it.
  v3  OFFLINE-ONLY CANDIDATE, not yet evaluated live: timestamps as MM:SS (Gemini's documented
      convention), an explicit `support` field, a coverage instruction, a rule that expected
      state must change something, and permission to answer null instead of guessing.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from shared.step_record import Action, PredicateKind, StatePredicate, Step, StepKind, StepList, Support

from .profiles import AppProfile, get_profile
from .providers.base import LLMProvider, ProviderError, QuotaError
from .timecode import parse_timestamp
from .validate import Issue, ValidationFailure, check_structure, sanitize_and_annotate

log = logging.getLogger(__name__)

DEFAULT_PROMPT_VERSION = "v2"  # stays the baseline until a live experiment justifies v3
PROMPT_VERSIONS = ("v2", "v3")


class ExtractionError(RuntimeError):
    def __init__(self, message: str, partial: StepList | None = None, issues: list[Issue] | None = None):
        super().__init__(message)
        self.partial = partial
        self.issues = issues or []


class DraftPredicate(BaseModel):
    """Model-facing predicate. Field names differ from the shared StatePredicate on purpose:
    live testing showed the model confused `target`/`value` and put the kind in `target`."""

    kind: PredicateKind
    name: str = Field(description="the mode / tool id / workspace / selection type / panel name, or the property path")
    expected_value: str | float | None = Field(
        default=None, description="ONLY for kind=property_equals: the value the property must equal; otherwise null"
    )

    def to_state(self) -> StatePredicate:
        return StatePredicate(
            kind=self.kind,
            target=self.name,
            value=self.expected_value if self.kind == "property_equals" else None,
        )


class DraftStep(BaseModel):
    """Shape the model is asked to produce (ids/order/flags are assigned by us)."""

    goal: str
    actions: list[Action] = Field(default_factory=list)
    start_state: list[DraftPredicate] = Field(default_factory=list)
    expected_state: list[DraftPredicate] = Field(default_factory=list)
    video_start_s: float | str | None = None  # seconds, or "MM:SS" / "H:MM:SS" (parsed deterministically)
    video_end_s: float | str | None = None
    alternatives: list[str] = Field(default_factory=list)
    version_dependent: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    kind: StepKind = Field(default="mechanics", description='"craft" when the result is judged by eye (timing, arcs, weight, feel) and has no checkable end state; otherwise "mechanics"')
    support: Support = "unknown"
    visual_evidence: str | None = None  # what is visible on screen (cursor target, key overlay, mode, shape)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("video_start_s", "video_end_s", mode="after")
    @classmethod
    def _to_seconds(cls, v):
        return parse_timestamp(v)


class DraftStepList(BaseModel):
    app_version_tutorial: str | None = None
    title: str | None = None
    steps: list[DraftStep]


_COMMON_RULES = """- One step = one learner goal achievable in a few actions. Keep tutorial order.
- actions: use verbs click, select, press_keys, drag, set_value, open_menu, other.
  Put the UI label EXACTLY as the tutorial shows/says it in ui_element (menu paths as "Add > Mesh > Cube").
  Never invent UI names. If the tutorial says "click this" and you cannot tell what, use verb "other",
  leave ui_element null, and lower confidence."""


def build_system_prompt(profile: AppProfile, version: str = DEFAULT_PROMPT_VERSION) -> str:
    vocab = f"""  mode: {sorted(profile.modes)}
  active_tool: {sorted(profile.tools)}
  workspace: {sorted(profile.workspaces)}
  selection_type: {sorted(profile.selection_types)}
  panel_open: {sorted(profile.panels)}
  property_equals: name = property path, expected_value = expected value (only when a value is explicitly given).
  Predicate JSON looks like {{"kind": "mode", "name": "EDIT_MESH"}} or
  {{"kind": "property_equals", "name": "object.location.x", "expected_value": 2.0}}.
  `name` must be one of the listed strings exactly; do not put the kind in `name`."""
    if version == "v2":
        return f"""You convert software tutorials into precise, ordered step records for {profile.name}.

Rules:
{_COMMON_RULES}
- expected_state: list ONLY conditions that are certain after the step, using ONLY these predicate kinds/targets:
{vocab}
  If the result of a step cannot be read from the application state (e.g. an aesthetic result), leave expected_state EMPTY.
  start_state follows the same rules and describes what must already hold before the step.
- confidence in [0,1]: lower it when inputs are invisible (keyboard/mouse not shown), narration is vague,
  or you infer anything. evidence: short quotes or observations that justify the step.
- Record alternatives the instructor mentions, controls that differ between software versions
  (version_dependent), and common mistakes only if stated or obvious.
- app_version_tutorial: only if the tutorial states or clearly shows a version, else null.
"""
    if version == "v3":
        return f"""You convert software tutorials into precise, ordered step records for {profile.name}.

A tutorial has TWO sources of instruction. Extract BOTH:
  (a) what the instructor SAYS;
  (b) what the instructor visibly DOES on screen: cursor targets, clicks, menus opening, tool and mode changes
      (read the mode name in the header), selections, keys pressed, values changing, objects appearing, moving,
      rotating or being duplicated. Many tutorials draw key and mouse presses as overlay text in a screen corner
      (for example "Tab", "Ctrl + Z x2", "Shift + Left Mouse"): read them.
Instructors often keep performing a demonstration while they talk about something else. A spoken explanation must
NEVER replace a concrete operation you can see. If the screen shows operations while the narration is conceptual,
still emit one step per distinct operation.

Rules:
{_COMMON_RULES}
- Work through the whole video in time order and do not skip a stretch in which operations are visible. Include
  brief shortcut presses that are shown on screen. Group an identical operation repeated many times in a row
  (the same shortcut pressed 21 times) into ONE step and say how many times in the goal.
- Include only operations a learner would need to reproduce. Do not make a step out of every hover, camera
  movement or incidental UI change. Skip intros, outros, sponsor segments and explanation with nothing to do.
- support (required): "demonstrated" = visible on screen but not said; "narrated" = only said, nothing on screen
  shows it; "both" = said and shown; "inferred" = you are filling it in (rare, low confidence).
- visual_evidence: REQUIRED when support is "demonstrated" or "both": one short sentence on what is visible at
  that moment (the overlay text, the mode in the header, the cursor target, the shape before/after). Otherwise null.
  Describe only what you actually see. If you cannot see it, do not claim it.
- evidence: short text you actually heard or read. Do not fabricate quotes.
- Timestamps: video_start_s / video_end_s are "MM:SS" (or "H:MM:SS") positions in the video where the action
  begins and ends. They must lie inside the video. If you cannot locate the moment, use null. Never guess.
- Never invent a step to cover more of the video. If you are not sure an operation happened, leave it out or use
  support "inferred" with low confidence.
- expected_state: list ONLY conditions that are certain AFTER the step AND were not already true before it.
  If the step changes none of the listed state kinds, leave expected_state EMPTY. Use ONLY these predicate kinds/targets:
{vocab}
  start_state follows the same rules and describes what must already hold before the step.
- confidence in [0,1]: your honest estimate that this step is correct and complete.
- Record alternatives the instructor mentions, controls that differ between software versions
  (version_dependent), and common mistakes only if stated or obvious.
- app_version_tutorial: only if the tutorial states or clearly shows a version, else null.
"""
    raise ValueError(f"unknown prompt version {version!r}; choose from {PROMPT_VERSIONS}")


def _schema() -> dict:
    return DraftStepList.model_json_schema()


def _to_steplist(
    draft: DraftStepList, *, source_type: Literal["youtube", "written"], app: str,
    video_id: str | None, model_id: str, prompt_version: str,
) -> StepList:
    steps = []
    for i, d in enumerate(draft.steps, start=1):
        steps.append(
            Step(
                id=f"s{i:02d}",
                order=i,
                review_status="drafted_automatically",
                model_confidence=d.confidence,
                **{
                    **d.model_dump(exclude={"start_state", "expected_state"}),
                    "start_state": [p.to_state() for p in d.start_state],
                    "expected_state": [p.to_state() for p in d.expected_state],
                },
            )
        )
    return StepList(
        source_type=source_type, app=app, app_version_tutorial=draft.app_version_tutorial,
        video_id=video_id, title=draft.title, steps=steps, model_id=model_id,
        prompt_version=prompt_version,
    )


def _retry_note(err: str, issues: list[Issue]) -> str:
    if issues:
        listing = "\n".join(f"- {i}" for i in issues[:20])
        return f"Your previous answer was rejected. Violations:\n{listing}\n"
    return f"Your previous answer was rejected: {err[:800]}\n"


def _run(
    provider: LLMProvider, *, prompt: str, video_url: str | None,
    source_type: Literal["youtube", "written"], app: str, video_id: str | None,
    video_duration_s: float | None, prompt_version: str, max_attempts: int = 2,
    on_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> StepList:
    profile = get_profile(app)
    system = build_system_prompt(profile, prompt_version)
    schema = _schema()
    prompt_hash = hashlib.sha256((system + "\n--\n" + prompt).encode("utf-8")).hexdigest()[:16]
    current_prompt = prompt
    last_err, last_issues, last_partial = "", [], None
    for attempt in range(1, max_attempts + 1):
        rec: dict[str, Any] = {"attempt": attempt, "prompt_version": prompt_version,
                               "model_id": provider.model_id, "video_id": video_id, "prompt_hash": prompt_hash}
        n_usage = len(getattr(provider, "usage", []))
        try:
            raw = provider.generate_json(
                system=system, prompt=current_prompt, schema=schema, video_url=video_url
            )
            rec["raw"] = raw
            usage = getattr(provider, "usage", [])
            if len(usage) > n_usage:
                rec["usage"] = usage[-1]
            draft = DraftStepList.model_validate(raw)
            sl = _to_steplist(
                draft, source_type=source_type, app=app, video_id=video_id,
                model_id=provider.model_id, prompt_version=prompt_version,
            )
            sl = sanitize_and_annotate(sl, profile, video_duration_s)
            last_partial = sl
            check_structure(sl, video_duration_s)
            rec["accepted"] = True
            if on_attempt:
                on_attempt(rec)
            return sl
        except (ValidationError, ValidationFailure, ValueError) as e:
            last_err = str(e)
            last_issues = list(e.issues) if isinstance(e, ValidationFailure) else []
            rec.update(accepted=False, error=last_err[:1500], issues=[str(i) for i in last_issues])
            if "raw" not in rec and getattr(provider, "last_raw_text", None):
                rec["raw_text"] = provider.last_raw_text[:30000]  # e.g. truncated/invalid JSON
            if on_attempt:
                on_attempt(rec)
            log.warning("extraction attempt %d/%d invalid: %s", attempt, max_attempts, last_err[:300])
            current_prompt = (
                f"{prompt}\n\n{_retry_note(last_err, last_issues)}"
                "Return corrected JSON that follows the schema and rules. Do not change steps that were not "
                "listed as violations, and do not invent content only to satisfy a rule: use null instead."
            )
        except QuotaError as e:  # quota/rate limit: surfaces unwrapped so callers can stop everything
            rec.update(accepted=False, error=f"provider: {e}"[:1500], provider_error="QuotaError")
            if on_attempt:
                on_attempt(rec)
            raise
        except ProviderError as e:
            rec["events"] = list(getattr(provider, "events", []))[-3:]
            rec.update(accepted=False, error=f"provider: {e}"[:1500], provider_error=type(e).__name__)
            if on_attempt:
                on_attempt(rec)
            raise ExtractionError(f"provider failure: {e}") from e
    raise ExtractionError(
        f"model output still invalid after {max_attempts} attempts: {last_err[:600]}",
        partial=last_partial, issues=last_issues,
    )


def extract_from_text(
    provider: LLMProvider, text: str, *, app: str = "blender",
    prompt_version: str = DEFAULT_PROMPT_VERSION, on_attempt=None,
) -> StepList:
    if not text or not text.strip():
        raise ExtractionError("empty instruction text")
    prompt = (
        "Convert these written instructions into step records. "
        "Do not add steps that the text does not imply. "
        "video_start_s/video_end_s must be null.\n\n--- INSTRUCTIONS ---\n" + text.strip()
    )
    sl = _run(
        provider, prompt=prompt, video_url=None, source_type="written", app=app, video_id=None,
        video_duration_s=None, prompt_version=prompt_version, on_attempt=on_attempt,
    )
    for s in sl.steps:  # written input has no video times
        s.video_start_s = s.video_end_s = None
    return sl


def extract_from_video(
    provider: LLMProvider, video_id: str, *, app: str = "blender",
    duration_s: float | None = None, title_hint: str | None = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION, on_attempt=None, transcript_cues=None,
) -> StepList:
    """transcript_cues: optional user-supplied subtitle cues (ingestion.transcript.parse_cues). They are shown
    to the model as a hint and used to check its evidence quotes. They are never fetched by this code."""
    from .transcript import check_evidence
    from .youtube.metadata import canonical_url

    prompt = video_prompt(prompt_version, duration_s, title_hint, transcript_cues)
    sl = _run(
        provider, prompt=prompt, video_url=canonical_url(video_id), source_type="youtube",
        app=app, video_id=video_id, video_duration_s=duration_s, prompt_version=prompt_version,
        on_attempt=on_attempt,
    )
    return check_evidence(sl, transcript_cues) if transcript_cues else sl


def video_prompt(prompt_version: str, duration_s: float | None, title_hint: str | None = None,
                 transcript_cues=None) -> str:
    """The per-request (user) prompt for a video. Exposed so experiments can hash it for cache keys."""
    from .transcript import transcript_for_prompt

    if prompt_version == "v3":
        time_fmt = "as MM:SS (or H:MM:SS)"
        dur_txt = (f"\nThe video is exactly {_mmss(duration_s)} long; every timestamp must be within 00:00 to "
                   f"{_mmss(duration_s)}." if duration_s else "")
        scan = (" Scan the whole video in order, and at every point ask: did the instructor perform an operation "
                "here (a key, a click, a menu, a mode or tool change, a selection, an object added, moved, rotated or "
                "duplicated)? If yes it needs a step, even when the narration is about something else.")
    else:
        time_fmt = "in seconds"
        dur_txt = (f"\nThe video is exactly {duration_s:.0f} seconds long; every timestamp must be <= {duration_s:.0f}."
                   if duration_s else "")
        scan = ""
    return (
        f"Watch this tutorial and extract step records. video_start_s/video_end_s are positions {time_fmt} "
        "from the start of the video when the step is shown/performed. If a spoken instruction "
        "is vague ('click this') use what is visible on screen at that moment; if you cannot tell, "
        "lower confidence and say so in evidence. Skip intro/outro/sponsor segments." + scan
        + (f"\nVideo title: {title_hint}" if title_hint else "")
        + dur_txt
        + (
            "\n\nA reference transcript supplied by the user follows (times in seconds). Treat it as a hint about "
            "what is said; the video is the source of truth for what is shown.\n"
            + transcript_for_prompt(transcript_cues)
            if transcript_cues else ""
        )
    )


def _mmss(s: float) -> str:
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
