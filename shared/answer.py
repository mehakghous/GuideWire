"""AnswerBundle: what GuideWire returns for a request, with explanations kept DISTINCT from executable steps.

A concise conceptual answer is not a UI action, so it is never forced into a StepList. A bundle may hold steps, explanations
(optionally linked to steps), tutorial recommendations, a clarification question, pointers to official pages, or an explicit
"a model / network is needed" result. `fallback_required` and `outside_index` mean NOTHING was called: the caller decides whether
to spend quota or network. Additive to the step contract; it reuses StepList unchanged.

Trust levels (highest first), carried in `trust` and in each step's `provenance`:
  reviewed        a named person approved the workflow for a Blender version range
  catalog         hand-curated and source-verified entry (ingestion/catalog.py)
  doc_extracted   deterministically extracted from a manual page's Reference block (mode / menu / shortcut); NOT reviewed
  doc_passage     an excerpt of manual prose offered as explanation only, never turned into steps
  index_pointer   a link to an official page that is not in the local index (titles only, no content)
  tutorial_metadata  a tutorial found in a curated index (title, link, version); its content is NOT understood
  none            nothing trustworthy was produced
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .step_record import StepList

Kind = Literal["procedure", "concept", "troubleshooting", "mixed", "clarification", "unsupported", "needs_model",
               "tutorial_recommendation", "needs_state", "decline"]
Route = Literal["session", "reviewed_workflow", "catalog", "text_parser", "transcript_parser", "manual_steps", "clarify", "fallback_required",
                "docs_index", "outside_index", "tutorial_index", "tutorial_import", "decline", "rigging_text", "rigging_knowledge"]
Trust = Literal["reviewed", "catalog", "doc_extracted", "doc_passage", "index_pointer", "tutorial_metadata", "none"]


class SourceRef(BaseModel):
    kind: Literal["manual", "tutorial_video", "user", "template", "forum"]            # forum: community advice (forum thread, bug report, course notes)
    title: str
    url: str | None = None
    version: str | None = None        # which version of the source was read, e.g. "main (Blender 5.2 LTS manual)"
    verified_on: str | None = None    # date the source was actually read
    licence: str | None = None


class Explanation(BaseModel):
    text: str                                            # catalog wording, or an attributed manual excerpt
    applies_to_steps: list[str] = Field(default_factory=list)  # step ids this explanation belongs to
    sources: list[SourceRef] = Field(default_factory=list)
    provenance: Literal["catalog_template", "user_text", "transcript_rules", "model", "documentation"] = "catalog_template"
    start_s: float | None = None                         # transcript explanations keep their time span
    end_s: float | None = None
    is_excerpt: bool = False                             # True when `text` is quoted from a source (needs the attribution)


class TutorialRecommendation(BaseModel):
    title: str
    url: str
    channel: str | None = None
    source_tier: Literal["official", "community", "unknown"] = "unknown"
    duration_s: float | None = None
    blender_version_hint: str | None = None
    licence: str | None = None
    captions_available: bool | None = None               # a flag from metadata: it does NOT mean we hold a transcript
    chapters: int | None = None
    caption_kind: Literal["creator", "auto", "none"] | None = None   # verified through the Data API for the shortlist; None = NOT CHECKED (the platform flag is not used)
    published: str | None = None                          # YYYY-MM-DD from the platform, when known
    level_claim: Literal["beginner", "advanced"] | None = None       # what the TITLE claims about its audience; the author's claim, not verified
    matched_terms: list[str] = Field(default_factory=list)
    score: float = 0.0
    convertible: Literal["no_transcript_or_model", "needs_user_transcript_or_video_model"] = "needs_user_transcript_or_video_model"
    note: str = ""


class SourceSection(BaseModel):
    """Which part of a source was processed (a video span or a topic window), so a result never looks like it covers the whole source."""
    start_s: float | None = None
    end_s: float | None = None
    topic: list[str] = Field(default_factory=list)
    how_determined: str = ""                              # "time range in the request", "chapter 'Joining objects'", ...
    confirmed: bool = False                               # a located (not stated) section is a candidate until the user confirms it


class RequestSummary(BaseModel):
    """What the USER asked for, kept separate from what a source claims (Step.evidence) and what GuideWire recommends (Step.goal)."""
    goal: str                                             # the user's own words
    task_type: Literal["procedure", "concept", "troubleshooting", "discovery", "follow_up", "ingest_source", "unclear"] = "unclear"
    constraints: dict[str, str | int | float | None] = Field(default_factory=dict)   # version, level, max_duration_s, ...
    context: Literal["standalone", "session"] = "standalone"
    refers_to_step: str | None = None                      # the step a follow-up was resolved against


class AnswerBundle(BaseModel):
    kind: Kind
    route: Route
    steps: StepList | None = None
    explanations: list[Explanation] = Field(default_factory=list)
    recommendations: list[TutorialRecommendation] = Field(default_factory=list)
    pointers: list[SourceRef] = Field(default_factory=list)       # official pages to read (index_pointer): titles only
    clarification: str | None = None
    questions: list[str] = Field(default_factory=list)            # what we need to know about the user's state
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)            # sources disagree: reported, never merged
    sources: list[SourceRef] = Field(default_factory=list)
    trust: Trust = "none"
    version_note: str | None = None
    unmet_prerequisites: list[str] = Field(default_factory=list)  # known unmet from OBSERVED state
    fallback_reason: str | None = None
    needs: list[str] = Field(default_factory=list)                # what a next step would need: 'network', 'model', 'transcript', 'user_state'
    unsupported: list[str] = Field(default_factory=list)
    api_calls: int = 0                                            # model/API calls made to produce this bundle
    network_calls: int = 0
    reasons: list[str] = Field(default_factory=list)              # why this route was chosen (for audit)
    request: RequestSummary | None = None                         # what the user asked for (additive, schema 0.6)
    source_section: SourceSection | None = None                   # which part of the source was processed (additive, schema 0.6)
