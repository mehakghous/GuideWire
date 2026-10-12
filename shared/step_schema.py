from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class ActionType(str, Enum):
    CLICK = "click"
    SELECT = "select"
    TOGGLE = "toggle"
    TYPE = "type"


class SourceType(str, Enum):
    YOUTUBE = "youtube"
    WRITTEN = "written"
    QUESTION = "question"


class Step(BaseModel):
    step_number: int = Field(ge=1)
    instruction_text: str = Field(min_length=1)   # what the user should do, in plain words
    action_type: ActionType
    target_ui_element: str = Field(min_length=1)  # Blender element name, e.g. "Edit Mode"
    expected_result: str = Field(min_length=1)    # how to tell the step is done
    timestamp: Optional[float] = None             # seconds into the video; None for written/question input


class Tutorial(BaseModel):
    title: str
    source_type: SourceType
    source_url: Optional[str] = None
    blender_version: Optional[str] = None         # only if a version cue was found
    steps: List[Step]

    @model_validator(mode="after")
    def steps_are_in_order(self):
        numbers = [s.step_number for s in self.steps]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("step_number must run 1, 2, 3... with no gaps or repeats")
        return self