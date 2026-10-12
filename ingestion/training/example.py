"""Training/evaluation example record (PROPOSED, offline only; nothing here trains or calls a model).

Reuses `shared.step_record.StepList` as the target for step-producing tasks. Adds only what a dataset needs and the step
schema does not carry: where the label came from, how it was checked, and which dependency group it belongs to (for
leakage-safe splitting). See docs/ingestion-technical-plan.md Part X.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from shared.step_record import StepList

Task = Literal["transcript_to_steps", "text_to_steps", "question_to_route", "clarification", "ui_state",
               "before_after_change", "narrated_vs_demonstrated"]
# How the LABEL was produced. Only `human` and `blender_executed` may serve as evaluation truth.
LabelOrigin = Literal["human", "blender_executed", "rules", "weak_alignment", "teacher_model"]
InputOrigin = Literal["real", "synthetic"]
Review = Literal["none", "spot_checked", "human_verified"]


class Check(BaseModel):
    name: str                  # e.g. "schema", "transcript_evidence", "blender_postcondition", "doc_cross_check"
    passed: bool
    detail: str | None = None


class TrainingExample(BaseModel):
    example_id: str
    task: Task
    blender_version: str | None = None
    input_origin: InputOrigin
    label_origin: LabelOrigin
    # Dependency group: every example that shares a source video / page / scene template MUST share this key.
    group_key: str = Field(min_length=1)
    input_text: str | None = None
    frame_refs: list[str] = Field(default_factory=list)      # paths or hashes; media itself is never embedded
    time_span_s: tuple[float, float] | None = None
    target_steps: StepList | None = None
    target_label: str | None = None                          # route / class / mode name for non-step tasks
    clarification_required: bool = False
    clarification_question: str | None = None
    teacher_model: str | None = None
    checks: list[Check] = Field(default_factory=list)
    review: Review = "none"
    reviewer: str | None = None
    licence: str | None = None                               # of the INPUT material
    notes: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "TrainingExample":
        if self.label_origin == "teacher_model" and not self.teacher_model:
            raise ValueError("teacher_model label needs teacher_model id")
        if self.review == "human_verified" and not self.reviewer:
            raise ValueError("human_verified needs a reviewer")
        if self.label_origin == "human" and self.review != "human_verified":
            raise ValueError("a human label must be recorded as human_verified")
        if self.target_steps is None and self.target_label is None and not self.clarification_required:
            raise ValueError("example has no target")
        if self.clarification_required and not self.clarification_question:
            raise ValueError("clarification_required needs a question")
        if self.label_origin == "blender_executed":
            if not any(c.name == "blender_postcondition" and c.passed for c in self.checks):
                raise ValueError("blender_executed label needs a passing blender_postcondition check")
        return self

    @property
    def eval_eligible(self) -> bool:
        """May this example be used as ground truth? Teacher output, rules and weak alignment never may, however many
        automatic checks they pass: a passing check shows consistency, not correctness."""
        if self.label_origin == "human":
            return True
        if self.label_origin == "blender_executed":
            # state transition verified in a real Blender run; says nothing about wording or tutorial fidelity
            return self.input_origin == "synthetic" or self.review == "human_verified"
        return False
