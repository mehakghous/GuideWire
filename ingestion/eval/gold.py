"""Human-annotated reference ("gold") format. Annotators watch the video; model output is never
used as ground truth. See docs/ingestion-technical-plan.md, section on ground truth.

v2 (additive) adds what the demonstration-coverage experiment needs: an id, an end time, preconditions,
observable before/after states, evidence type (a step may be BOTH narrated and demonstrated), a
verification status with confidence, prerequisite links, and annotator-defined match terms for
deterministic matching."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from shared.step_record import Action, StatePredicate

EvidenceType = Literal["demonstrated", "narrated", "both"]
Verification = Literal["visual_assistant", "transcript", "human", "unverified"]


class GoldStep(BaseModel):
    order: int = Field(ge=1)
    id: str | None = None                    # e.g. "R06"
    goal: str                                # what the learner does, in the annotator's words
    t_start: float = Field(ge=0)             # second at which the action begins
    t_end: float | None = Field(default=None, ge=0)
    tol_s: float = Field(default=5.0, gt=0)  # acceptable +/- error on t_start
    actions: list[Action] = Field(default_factory=list)  # UI element as shown on screen
    preconditions: list[str] = Field(default_factory=list)
    before_state: str | None = None          # observable state before, in words
    after_state: str | None = None           # observable state after, in words
    expected_state: list[StatePredicate] = Field(default_factory=list)
    evidence_kind: Literal["directly_evidenced", "inferred", "unverifiable"] = "directly_evidenced"
    evidence_type: EvidenceType | None = None  # None = old-style file: derive from evidence_kind
    verification: Verification = "unverified"
    verification_confidence: Literal["high", "medium", "low"] | None = None
    importance: Literal["core", "optional"] = "core"  # core = the tutorial result depends on it
    verifiable_from_state: bool = False      # can the application state confirm completion?
    requires: list[str] = Field(default_factory=list)  # ids of steps that must happen first
    match_terms: list[list[str]] = Field(default_factory=list)  # OR of AND-groups of lowercase words
    note: str | None = None

    @property
    def is_verified(self) -> bool:
        """Counted in recall denominators: independently checked at medium+ confidence."""
        return self.verification != "unverified" and self.verification_confidence in ("high", "medium")


class GoldSet(BaseModel):
    video_id: str | None = None
    title: str | None = None
    duration_s: float
    app: str = "blender"
    app_version: str | None = None
    annotator: str
    verification_note: str | None = None
    steps: list[GoldStep]
