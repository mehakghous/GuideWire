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
import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from shared.step_record import Action, StatePredicate, Step, StepKind, StepList, Support

from .instructions import compose_instructions
from .profiles import AppProfile, get_profile
from .providers.base import LLMProvider, ProviderError, QuotaError
from .scene_chain import derive_state, flag_order_errors
from .timecode import parse_timestamp
from .validate import Issue, ValidationFailure, check_structure, refresh_coverage_warnings, sanitize_and_annotate

log = logging.getLogger(__name__)

DEFAULT_PROMPT_VERSION = "v2"  # stays the baseline until a live experiment justifies v3
PROMPT_VERSIONS = ("v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10", "v10-nokb", "v10-outline", "v10-preds")


class ExtractionError(RuntimeError):
    def __init__(self, message: str, partial: StepList | None = None, issues: list[Issue] | None = None):
        super().__init__(message)
        self.partial = partial
        self.issues = issues or []


# The model is offered the seven kinds of schema 0.10. name_exists, attribute_exists and node_count (0.11) exist in the contract, the checker and the
# harness, but no prompt teaches them yet (that needs a live run, and it would change MODEL_SCHEMA_TAG and every cache key).
ModelPredicateKind = Literal["mode", "active_tool", "workspace", "selection_type", "panel_open", "property_equals", "node_exists"]


class DraftPredicate(BaseModel):
    """Model-facing predicate. Field names differ from the shared StatePredicate on purpose:
    live testing showed the model confused `target`/`value` and put the kind in `target`."""

    kind: ModelPredicateKind
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


class DraftHowTo(BaseModel):
    """Model-facing instruction line. `catalog` is not offered to the model: only we may add guidance the video did not show."""
    text: str
    support: Literal["shown", "said"]
    evidence: str | None = Field(default=None, description="what you saw or heard that supports this line: a quote, or a short description of the screen")


# "v10-preds" offers the model the three kinds of schema 0.11 as well, so renames, parameter edits and counts get a checkable end state. Only that version sees the wider schema; every other
# version keeps DraftPredicate exactly as it was (its request, its cache key and its recorded runs do not change).
ExtendedPredicateKind = Literal["mode", "active_tool", "workspace", "selection_type", "panel_open", "property_equals", "node_exists", "name_exists", "attribute_exists", "node_count"]


class DraftPredicateExt(DraftPredicate):
    kind: ExtendedPredicateKind
    name: str = Field(description="the mode / tool id / workspace / selection type / panel name, the property path, the node type, the name the learner typed (name_exists), or object.attribute (attribute_exists)")
    expected_value: str | float | None = Field(default=None, description="ONLY for kind=property_equals (the value the property must equal) and node_count (a whole number: at least this many exist); otherwise null")

    def to_state(self) -> StatePredicate:
        return StatePredicate(kind=self.kind, target=self.name, value=self.expected_value if self.kind in ("property_equals", "node_count") else None)


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
    result: str | None = Field(default=None, description="one sentence: what the learner has after this step")
    how_to: list[DraftHowTo] = Field(default_factory=list, description="ordered imperative lines: what to select, which menu or panel to open, which setting to enter, only what the video shows or says")
    check: list[DraftHowTo] = Field(default_factory=list, description="how the learner can tell it worked, only if the video shows or says it")
    feature_id: str | None = Field(default=None, description="id from the feature list in the prompt (e.g. SKEL-01) when the step teaches that feature, else null")
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


class DraftStepExt(DraftStep):
    start_state: list[DraftPredicateExt] = Field(default_factory=list)
    expected_state: list[DraftPredicateExt] = Field(default_factory=list)


class DraftStepListExt(DraftStepList):
    steps: list[DraftStepExt]


def _extended(prompt_version: str) -> bool:
    return prompt_version == "v10-preds"


_COMMON_RULES = """- One step = one learner goal achievable in a few actions. Keep tutorial order.
- actions: use verbs click, select, press_keys, drag, set_value, open_menu, other.
  Put the UI label EXACTLY as the tutorial shows/says it in ui_element (menu paths as "Add > Mesh > Cube").
  Never invent UI names. If the tutorial says "click this" and you cannot tell what, use verb "other",
  leave ui_element null, and lower confidence."""


def build_system_prompt(profile: AppProfile, version: str = DEFAULT_PROMPT_VERSION) -> str:
    # "v10-nokb" and "v10-outline" are v10 with the knowledge block removed or replaced by typical sequences: a measured experiment (docs/evaluation_report_2026-11-09.md), not a default.
    full_version = version
    version, _, kb_mode = version.partition("-")
    if kb_mode and (version != "v10" or kb_mode not in ("nokb", "outline", "preds")):
        raise ValueError(f"unknown prompt version {full_version!r}; choose from {PROMPT_VERSIONS}")
    # Blender gained a node vocabulary (objects, bones, constraints, modifiers) after the recorded runs; the frozen prompts v2 to v6 must not change, so only v7 shows it.
    node_line = f"\n  node_exists: {sorted(profile.nodes)} (a node or object of that type must exist)" if profile.nodes and (profile.name != "blender" or version in ("v7", "v8", "v9", "v10")) else ""
    vocab = f"""  mode: {sorted(profile.modes)}
  active_tool: {sorted(profile.tools)}
  workspace: {sorted(profile.workspaces)}
  selection_type: {sorted(profile.selection_types)}
  panel_open: {sorted(profile.panels)}{node_line}
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
    if version in ("v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10"):
        base = f"""You convert software tutorials into precise, ordered step records for {profile.name}.

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
        return base + (_rigging_rules(profile, version) if version in ("v4", "v5", "v6", "v7", "v8", "v9", "v10") else "") + (_ACTIONABLE_RULES if version in ("v5", "v6", "v7", "v8", "v9", "v10") else "") + (_knowledge_notes(profile) if version in ("v6", "v7", "v8", "v9", "v10") and kb_mode != "nokb" else "") + (_knowledge_outlines(profile) if kb_mode == "outline" else "") + (_ATOMIC_RULES if version in ("v8", "v9", "v10") else "") + (_COVERAGE_RULES if version in ("v9", "v10") else "") + (_NO_PADDING_RULES if version == "v10" else "") + (_PREDICATE_RULES if kb_mode == "preds" else "")
    raise ValueError(f"unknown prompt version {full_version!r}; choose from {PROMPT_VERSIONS}")


_ACTIONABLE_RULES = """
ACTIONABLE STEPS. A beginner must be able to perform each step in the application without reopening the video.
- One step = one operation the learner performs and can check. Split a compound action ("duplicate the chain and rename it") into separate steps. Never replace a run of operations with one summary.
- how_to: ordered, short, imperative lines covering, wherever the video shows or says them: what to select (the object, joint or control, and in which window); the exact menu path, shelf
  button, tool, panel or shortcut, written as shown ("Skeleton > Orient Joint"); every setting and value typed or chosen; every name typed. Give each line support "shown" (visible on screen)
  or "said" (only narrated) and an evidence quote or a short description of the screen.
- NEVER write a menu location, button, shortcut, value or name that the video does not show or say, even if it is standard practice. If a needed detail cannot be read, omit it and add
  "detail not visible in the video" to the step's assumptions.
- check: how the learner can tell the step worked, only if the video shows or says it. Do not add generic checks.
- result: one sentence saying what the learner has after the step.
- No steps for introductions, recaps or talk with nothing to do.
"""


# v8 (2026-11-09). The first human-labelled comparison (docs/evaluation_report_2026-11-09.md) found that v7 steps cover several of a person's small actions each: 4 to 13 steps
# for 25 to 62 labelled actions, with whole stretches of some videos empty. v7 itself asks to group repeats and to skip incidental changes, so v8 states the opposite for
# operations a learner must perform, and puts it last so it wins over the earlier rules.
_ATOMIC_RULES = """
ATOMIC STEPS. These rules replace any earlier rule about grouping, summarising or leaving out small operations.
- Write ONE step per independent operation the learner performs, however small: a mode or state change (a key such as Tab, a mode menu, pressing Enter in the viewport to start or stop a tool),
  selecting a named object, joint, bone or node, choosing a tool, ticking or clearing a checkbox, choosing an item in a dropdown or menu, typing or changing a value, naming or renaming,
  opening or switching a panel, tab, editor, window or workspace, pressing a shortcut, connecting nodes, parenting, constraining.
- Never merge two independent operations into one step. "Create a skeleton and name it Base" is two steps: create it, then name it.
- Do not skip an operation because the instructor does not mention it. If the screen shows it (a mode label changes, a box is ticked, a panel opens, a value changes), it is a step with support
  "demonstrated". If it is only said, support "narrated".
- Keep the order in which the operations happen, and give EVERY step its own video_start_s and video_end_s, even when it lasts a second or two.
- Still leave out: intros, outros, recaps, talk with nothing to do, and view movement (orbit, pan, zoom) that does not change the result. Identical repetitions may be ONE step only when each
  repetition is exactly the same; say how many times.
- Keep how_to to one or two short lines per step (the menu path, the value, the name): atomic steps are small, so a long tutorial can have many dozens of them.
"""


# v9 = v8 plus a coverage rule. The first live v8 run (docs/evaluation_report_2026-11-09.md) split the tutorial into small steps but left long stretches with none (for example 65 s
# of a 190 s video), so one-to-one recall rose while the share of the video covered fell.
_COVERAGE_RULES = """
COVERAGE. Work through the video from the first operation to the last, in time order, without stopping early. Do not leave a stretch of more than about 15 seconds without a step
if anything is performed in it: when you reach a gap, look at that stretch again. The steps must reach the last operation of the tutorial; the final step's video_end_s should be close to
the end of the video unless the video ends with talk only.
"""


# v10 = v9 plus a rule against padding. In the first windowed v9 run about a quarter of the steps matched nothing the human labeller listed, and many were not operations at all
# ("Inspect ...", "Explain ...", "Prepare to ...", "Select the node" repeated). Only operations that choose or change something are steps.
_NO_PADDING_RULES = """
ONLY OPERATIONS. A step is something the learner does that chooses or changes something in the application. Never write a step for looking at, inspecting, checking, explaining,
discussing, preparing for, planning or "being ready to" do something; put what to look for in the preceding step's check line instead. Never repeat an operation already written for the
same moment. If nothing is performed in a stretch (only talk, or only the cursor moving), write no step for it.
"""


# v10-preds = v10 plus the three newer kinds of expected state. In the v10 runs on gemini-3.6-flash only about half of the mechanics steps had an end state (Blender 66 %, Houdini 46 %,
# Maya 43 %), and the missing ones were renames, option toggles, parameter edits and connections: nothing the seven older kinds could say.
_PREDICATE_RULES = """
EXPECTED STATE FOR MORE STEPS. Besides the kinds listed above you may use three more in expected_state (and only when the video makes the result visible):
  name_exists: name = the exact name the learner types for a node, object, bone or joint, e.g. "leftToe" or "jnt_L_hip". Use it for every rename step.
  attribute_exists: name = "object.attribute" as shown in the Channel Box, Attribute Editor, Properties editor or parameter pane, e.g. "l_switch_GEO.FK_IK_Switch". Use it when a step adds an attribute or a parameter.
  node_count: name = the node or object type, expected_value = a whole number: at least that many exist, e.g. {"kind": "node_count", "name": "joint", "expected_value": 9} after the learner has made nine joints.
A setting or toggle that is switched on or off or given a value is property_equals with the property path and the value. A step that only moves, rotates or scales has no expected state. Give every mechanics
step an expected_state when one of these kinds fits; leave it empty only when none fits. Never invent a name, count or attribute the video does not show.
"""


def _knowledge_notes(profile: AppProfile) -> str:
    """v6: the menu paths and option names the researched documentation gives for this application (knowledge/rigging_knowledge.json). They help the model spell what it
    sees the way the application does, and make clear that anything neither seen nor listed must not be written. Official names only; community advice is not put in a prompt."""
    from .rigging_knowledge import load as knowledge
    lines = []
    for e in knowledge().entries:
        if profile.name not in e.apps:
            continue
        for u in e.ui:
            opts = u.get("options") if u.get("options_tier") == "official" else None
            lines.append(f"  - {u['path']}" + (f"  [options: {', '.join(opts)}]" if opts else ""))
    if not lines:
        return ""
    return (f"""
Menu locations and option names reported for {profile.name} (from its documentation and from tutorials; they differ between versions, so write what the video SHOWS and use these spellings only when the video shows the same thing):
""" + "\n".join(lines) + """
If the video shows a different menu or label from the one above, write the video's. Never write a name that the video does not show and this list does not give.
""")


def _knowledge_outlines(profile: AppProfile) -> str:
    """v10-outline (experiment): the typical order of operations the researched knowledge base gives for each topic of this application, one line per topic. The aim is to remind the
    model of small operations that usually occur (a state key, an options box, a rename) so it LOOKS for them; the rule below says it must write only what the video shows, because
    a model given an outline can copy it instead of watching. Only official and tutorial statements are used."""
    from .rigging_knowledge import load as knowledge
    lines = []
    for e in knowledge().entries:
        if profile.name not in e.apps:
            continue
        steps = [x.text.rstrip(".") for x in e.outline if x.tier in ("official", "tutorial")][:6]
        if len(steps) >= 2:
            lines.append(f"  - {e.id.split('.', 1)[-1].replace('_', ' ')}: " + " -> ".join(steps))
    if not lines:
        return ""
    return ("\nTypical order of operations for common topics in " + profile.name + " (from its documentation and tutorials). Use them ONLY to remember small operations that usually happen "
            "(a key that starts a tool, an options box, a rename) and to look for them in the video. A tutorial may skip, reorder or do things differently: write ONLY what the video shows "
            "or says, never a step because it is on this list.\n" + "\n".join(lines) + "\n")


NODE_EXAMPLES = {            # v7: what a node_exists name looks like in each application (checked against the real installs by tests/test_app_vocab.py)
    "maya": "for example joint, ikHandle, skinCluster: Maya's node type names",
    "houdini": "for example Skeleton, Rig Doctor, Joint Deform: the label the node type has in the network editor, without any internal prefix",
    "blender": "for example ARMATURE or BONE (objects and bones), CONSTRAINT_IK or CONSTRAINT_COPY_ROTATION (a constraint on a bone or object), MODIFIER_ARMATURE (a modifier): Blender's upper-case type names, with CONSTRAINT_ or MODIFIER_ in front",
}
RIGGING_APPS = ("maya", "houdini")


def default_prompt_version(app: str, rigging: bool = False) -> str:
    """Rigging and animation is the main use for Maya and Houdini, so they get the newest prompt; Blender keeps the modelling baseline (v2) unless the caller says the video is about rigging."""
    return "v7" if rigging or app in RIGGING_APPS else DEFAULT_PROMPT_VERSION


def _rigging_rules(profile: AppProfile, version: str = "v6") -> str:
    """v4 addition for character rigging and animation tutorials: the feature list the model may tag steps with."""
    from .features import CRAFT_FEATURES, load_catalog
    cat = load_catalog()
    feats = "\n".join(f"  {f.id}: {f.name}" for f in cat.supported(profile.name, ("N", "P", "C")))
    # v6 and earlier gave Maya examples to every application (a Houdini or Blender prompt told the model "joint, ikHandle, skinCluster"); v7 gives each its own.
    node_example = NODE_EXAMPLES[profile.name] if version in ("v7", "v8", "v9", "v10") else "for example joint, ikHandle, skinCluster"
    return f"""
This is a character rigging and animation tutorial for {profile.name}.
- feature_id: when a step teaches one of the features below, set feature_id to its id exactly; otherwise null. Never invent an id.
{feats}
- video_start_s and video_end_s: give them for EVERY step ("MM:SS" or "H:MM:SS"), because the learner is taken to that moment in the video; use null only when you truly cannot locate it.
- expected_state: when a step creates a node or object of one of the node types listed in the node_exists line above ({node_example}), add
  {{"kind": "node_exists", "name": "<that type exactly>"}}. Leave it empty for steps whose result cannot be read from the application.
- kind: "craft" when the result is judged by eye (timing, arcs, weight, feel; for example {", ".join(sorted(CRAFT_FEATURES))}); otherwise "mechanics".
  A craft step has no expected_state.
- Name the rig's parts as the tutorial does ("bone" in Blender, "joint" in Maya and Houdini). Do not translate between applications.
"""


# The first live v5 run (2026-10-16) showed that a model filling a JSON schema SKIPS optional fields however firmly the prompt asks for them: it returned no
# how_to, check, result, times or expected_state at all. These are therefore REQUIRED in the schema the model sees (empty list / null are still allowed answers).
# Parsing stays lenient, so older recorded outputs and fakes that omit them still load.
MODEL_REQUIRED = ("actions", "expected_state", "video_start_s", "video_end_s", "result", "how_to", "check")


def _schema(prompt_version: str | None = None) -> dict:
    ext = bool(prompt_version) and _extended(prompt_version)
    sch = (DraftStepListExt if ext else DraftStepList).model_json_schema()
    req = sch["$defs"]["DraftStepExt" if ext else "DraftStep"]["required"]
    req += [f for f in MODEL_REQUIRED if f not in req]
    return sch


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


def sort_by_time(sl: StepList) -> bool:
    """Put the steps in the order of their start times when every step has one and the model listed them out of order (a stable sort; ids and order renumbered; the steps that
    moved are flagged). Times are what the video shows, so they decide; a list with a missing time is left alone. Returns True when anything moved."""
    steps = sl.steps
    if len(steps) < 2 or any(st.video_start_s is None for st in steps):
        return False
    ordered = sorted(steps, key=lambda st: st.video_start_s)
    if [id(x) for x in ordered] == [id(x) for x in steps]:
        return False
    moved = [x for x, y in zip(ordered, steps) if x is not y]
    for st in moved:
        st.flags.append("the model listed this step out of time order; steps were sorted by their start times")
    for i, st in enumerate(ordered, start=1):
        st.id, st.order = f"s{i:02d}", i
    sl.steps = ordered
    return True


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
    schema = _schema(prompt_version)
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
            draft = (DraftStepListExt if _extended(prompt_version) else DraftStepList).model_validate(raw)
            sl = _to_steplist(
                draft, source_type=source_type, app=app, video_id=video_id,
                model_id=provider.model_id, prompt_version=prompt_version,
            )
            compose_instructions(sl)                       # before validation, so unknown menu names get the usual "please check" flag
            derive_state(sl)
            sl = sanitize_and_annotate(sl, profile, video_duration_s)
            last_partial = sl
            check_structure(sl, video_duration_s)
            flag_order_errors(sl)
            rec["accepted"] = True
            rec["events"] = list(getattr(provider, "events", []))[-3:]               # HTTP attempts and their latency: cost AND time are now recorded
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
    # Last resort, only when the ONLY problem is steps listed out of time order: the times are what the video shows, so sort by them (flagged on the steps that moved) and check again.
    # Any other violation, or a second kind next to this one, is still reported and nothing is repaired.
    if last_partial is not None and last_issues and all(i.code == "TS_NOT_MONOTONIC" for i in last_issues) and sort_by_time(last_partial):
        try:
            check_structure(last_partial, video_duration_s)
            flag_order_errors(last_partial)
            return last_partial
        except ValidationFailure as e:
            last_issues = list(e.issues)
    raise ExtractionError(
        f"model output still invalid after {max_attempts} attempts: {last_err[:600]}",
        partial=last_partial, issues=last_issues,
    )


def written_prompt(text: str) -> str:
    """The per-request prompt for written instructions (exposed so the dry run and the cache key use exactly what is sent)."""
    return (
        "Convert these written instructions into step records. "
        "Do not add steps that the text does not imply. "
        "video_start_s/video_end_s must be null.\n\n--- INSTRUCTIONS ---\n" + text.strip()
    )


def extract_from_text(
    provider: LLMProvider, text: str, *, app: str = "blender",
    prompt_version: str = DEFAULT_PROMPT_VERSION, on_attempt=None,
) -> StepList:
    if not text or not text.strip():
        raise ExtractionError("empty instruction text")
    prompt = written_prompt(text)
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


def video_windows(duration_s: float, window_s: float = 60.0, overlap_s: float = 8.0) -> list[tuple[int, int]]:
    """Overlapping (start, end) seconds that together cover the whole video. The last window is never shorter than 15 s (it is folded into the one before)."""
    if duration_s <= window_s:
        return [(0, int(duration_s))]
    step = max(1.0, window_s - overlap_s)
    out, start = [], 0.0
    while start < duration_s:
        end = min(duration_s, start + window_s)
        out.append((int(start), int(end)))
        if end >= duration_s:
            break
        start += step
    if len(out) > 1 and out[-1][1] - out[-1][0] < 15:
        out[-2] = (out[-2][0], out[-1][1])
        out.pop()
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def merge_window_steps(parts: list[list[Step]], duration_s: float) -> list[Step]:
    """Join the steps of consecutive windows in time order. A step from a later window that repeats one already kept (it starts inside the kept step's span plus 3 s and
    shares at least 60 % of the shorter goal's words) is the same action seen twice in an overlap and is dropped. Ids and order are renumbered."""
    kept: list[Step] = []
    for steps in parts:
        for st in sorted(steps, key=lambda s: (s.video_start_s if s.video_start_s is not None else 1e9)):
            dup = False
            for k in kept[-6:]:
                if st.video_start_s is None or k.video_start_s is None:
                    continue
                if k.video_start_s - 3 <= st.video_start_s <= (k.video_end_s if k.video_end_s is not None else k.video_start_s) + 3:
                    a, b = _words(st.goal), _words(k.goal)
                    if a and b and len(a & b) / min(len(a), len(b)) >= 0.6:
                        dup = True
                        break
            if not dup:
                kept.append(st)
    kept.sort(key=lambda s: (s.video_start_s if s.video_start_s is not None else 1e9))
    for i, st in enumerate(kept, start=1):
        st.id, st.order = f"s{i:02d}", i
        st.depends_on = []
    return kept


def extract_from_video_windows(
    provider: LLMProvider, video_id: str, *, app: str = "blender", duration_s: float, window_s: float = 60.0, overlap_s: float = 8.0,
    title_hint: str | None = None, prompt_version: str = DEFAULT_PROMPT_VERSION, on_attempt=None,
) -> StepList:
    """Extract a long video in short overlapping windows and join the results. Each call shows the model only that clip (`...#t=start,end`), so it cannot summarise or skip a long
    stretch; the model gives times from the start of its clip and they are shifted back to the video's timeline here. A window the model could not answer validly is reported in
    `warnings` and left empty rather than failing the whole video (a provider outage or quota error still raises)."""
    from .youtube.metadata import canonical_url

    wins = video_windows(duration_s, window_s, overlap_s)
    parts: list[list[Step]] = []
    warns: list[str] = []
    first: StepList | None = None
    for a, b in wins:
        if hasattr(provider, "video_seconds"):
            provider.video_seconds = b - a
        prompt = video_prompt(prompt_version, float(b - a), title_hint) + (
            f"\nThis video is a clip, seconds {a} to {b} of a longer tutorial. Give every timestamp as MM:SS counted from the START OF THIS CLIP. "
            "Steps of earlier or later parts are not your concern; do not repeat an operation only because it is half visible at the very start or end of the clip.")
        try:
            sl = _run(provider, prompt=prompt, video_url=f"{canonical_url(video_id)}#t={a},{b}", source_type="youtube", app=app, video_id=video_id,
                      video_duration_s=float(b - a), prompt_version=prompt_version, on_attempt=on_attempt)
        except ExtractionError as e:
            if isinstance(e.__cause__, ProviderError):
                raise
            if e.partial is None:
                warns.append(f"window {a}s to {b}s: no valid answer from the model ({str(e)[:120]})")
                parts.append([])
                continue
            sl = e.partial
            warns.append(f"window {a}s to {b}s: the model's answer had problems and was kept as drafted")
        first = first or sl
        for st in sl.steps:
            for attr in ("video_start_s", "video_end_s"):
                v = getattr(st, attr)
                if v is not None:
                    setattr(st, attr, min(float(duration_s), v + a))
        parts.append(sl.steps)
    merged = merge_window_steps(parts, duration_s)
    out = StepList(source_type="youtube", app=app, app_version_tutorial=first.app_version_tutorial if first else None, video_id=video_id, title=first.title if first else None,
                   steps=merged, model_id=provider.model_id, prompt_version=prompt_version, video_duration_s=duration_s)
    flag_order_errors(out)
    refresh_coverage_warnings(out)
    out.warnings = [f"extracted in {len(wins)} windows of about {window_s:g} s with {overlap_s:g} s overlap"] + warns + out.warnings
    return out


def video_prompt(prompt_version: str, duration_s: float | None, title_hint: str | None = None,
                 transcript_cues=None) -> str:
    """The per-request (user) prompt for a video. Exposed so experiments can hash it for cache keys."""
    from .transcript import transcript_for_prompt
    prompt_version = prompt_version.partition("-")[0]                  # "v10-nokb" and "v10-outline" differ only in the system prompt

    if prompt_version in ("v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10"):
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
