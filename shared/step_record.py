"""Shared step-record contract (v0.1, DRAFT: proposed by Ayesha, pending review by Mehak and Umaima).

A StepList is what the ingestion pipeline produces and what the review UI, session
engine and guidance engine consume. Expected state is expressed as a small closed set
of StatePredicate kinds so that a read-only adapter or the screen can actually check it.
A step with no checkable predicate is `verifiable=False` (guided but not checked).

Changing a field or a PredicateKind is a contract change: bump SCHEMA_VERSION and tell
the other owners.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "0.3"  # 0.2 (additive): Step.support, model_confidence, StepList.warnings/video_duration_s/prompt_version. 0.3 (additive): support "both", Step.visual_evidence

PredicateKind = Literal[
    "mode",            # target: interaction mode, e.g. OBJECT, EDIT_MESH, SCULPT
    "active_tool",     # target: tool id, e.g. builtin.extrude_region
    "workspace",       # target: workspace/page name, e.g. Shading
    "selection_type",  # target: kind of thing selected, e.g. MESH, LIGHT, CAMERA, NONE
    "panel_open",      # target: panel/editor name, e.g. Properties:Modifiers
    "property_equals", # target: property path; value: expected value
]

ActionVerb = Literal[
    "click", "select", "press_keys", "drag", "set_value", "open_menu", "other"
]

ReviewStatus = Literal["drafted_automatically", "reviewed", "drafted_without_source"]
SourceType = Literal["youtube", "written", "goal_draft"]
# How directly the source supports a step:
#   demonstrated = shown on screen only; narrated = only said; both = said AND shown;
#   inferred = the model filled it in; unknown = not stated.
Support = Literal["demonstrated", "narrated", "both", "inferred", "unknown"]


class StatePredicate(BaseModel):
    kind: PredicateKind
    target: str = Field(min_length=1)
    value: str | float | None = None

    @model_validator(mode="after")
    def _value_only_for_property(self) -> "StatePredicate":
        if self.kind == "property_equals" and self.value is None:
            raise ValueError("property_equals requires a value")
        if self.kind != "property_equals" and self.value is not None:
            raise ValueError(f"value is only allowed for property_equals, not {self.kind}")
        return self


class Action(BaseModel):
    verb: ActionVerb
    ui_element: str | None = None  # name as shown in the UI, e.g. "Add > Mesh > Cube"
    keys: list[str] = Field(default_factory=list)  # e.g. ["Shift", "A"]
    value: str | None = None       # typed/dragged value, e.g. "2.5 m"


class Step(BaseModel):
    id: str
    order: int = Field(ge=1)
    goal: str = Field(min_length=1)
    actions: list[Action] = Field(default_factory=list)
    start_state: list[StatePredicate] = Field(default_factory=list)
    expected_state: list[StatePredicate] = Field(default_factory=list)
    verifiable: bool = False  # derived: True iff expected_state is non-empty
    video_start_s: float | None = Field(default=None, ge=0)
    video_end_s: float | None = Field(default=None, ge=0)
    alternatives: list[str] = Field(default_factory=list)
    version_dependent: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)  # heuristic composite, NOT calibrated
    model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)  # the model's own self-rating
    support: Support = "unknown"
    visual_evidence: str | None = None  # what is visible on screen at that moment (cursor target, key overlay, mode, shape)
    evidence: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)  # validator warnings shown to the learner
    review_status: ReviewStatus = "drafted_automatically"

    @model_validator(mode="after")
    def _derive_verifiable(self) -> "Step":
        self.verifiable = bool(self.expected_state)
        if (
            self.video_start_s is not None
            and self.video_end_s is not None
            and self.video_end_s < self.video_start_s
        ):
            raise ValueError("video_end_s must be >= video_start_s")
        return self


class StepList(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source_type: SourceType
    app: str                            # "blender" | "unity" | "davinci_resolve"
    app_version_tutorial: str | None = None
    video_id: str | None = None
    title: str | None = None
    steps: list[Step]
    model_id: str | None = None
    prompt_version: str | None = None
    video_duration_s: float | None = None
    warnings: list[str] = Field(default_factory=list)  # list-level findings (coverage gaps etc.)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
