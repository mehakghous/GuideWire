"""How good are the feature tags the transcript reader gives to REAL spoken tutorials? Scores steps against the hand labels in
tests/fixtures/rubrics/real_speech_labels.json (video id + the second a step starts at + the acceptable features).

  precision   of the steps the reader tagged that sit on a labelled moment, the share whose tag is an acceptable one
  false steps labelled "not a rigging step" but turned into a step with a tag anyway
  recall      of the labelled moments that DO have an acceptable feature, the share where the reader produced a correct tag
  unlabelled  steps at a moment nobody labelled yet: not scored, listed so they get labelled next
One labeller made the labels, so these numbers measure progress between versions, not accuracy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from shared.step_record import StepList

LABELS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "rubrics" / "real_speech_labels.json"
WINDOW_S = 4.0                                          # a step belongs to a label if it starts within this many seconds of it


def load_labels(path: Path = LABELS) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))["videos"]


@dataclass
class TagScore:
    tagged: int = 0
    correct: int = 0
    false_steps: int = 0
    labelled_positive: int = 0
    found: int = 0
    unlabelled: list[tuple[str, float, str | None]] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return round(100.0 * self.correct / self.tagged, 1) if self.tagged else 0.0

    @property
    def recall(self) -> float:
        return round(100.0 * self.found / self.labelled_positive, 1) if self.labelled_positive else 0.0

    def render(self) -> str:
        return (f"tag precision {self.precision}% ({self.correct}/{self.tagged}); false steps {self.false_steps}; "
                f"recall {self.recall}% ({self.found}/{self.labelled_positive}); unlabelled steps {len(self.unlabelled)}")


def score_tags(steplists: dict[str, StepList], labels: dict | None = None) -> TagScore:
    labels = labels or load_labels()
    out = TagScore()
    for vid, sl in steplists.items():
        lab = {float(k): set(v) for k, v in labels[vid]["labels"].items()}
        hit_positions = set()
        for st in sl.steps:
            t = st.video_start_s if st.video_start_s is not None else -999.0
            near = min(lab, key=lambda k: abs(k - t), default=None)
            if near is None or abs(near - t) > WINDOW_S:
                out.unlabelled.append((vid, t, st.feature_id))
                continue
            ok = lab[near]
            if st.feature_id:
                out.tagged += 1
                if st.feature_id in ok:
                    out.correct += 1
                    hit_positions.add(near)
                elif not ok:
                    out.false_steps += 1
        out.labelled_positive += sum(1 for ok in lab.values() if ok)
        out.found += len(hit_positions)
    return out
