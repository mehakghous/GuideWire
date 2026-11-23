"""The session screen shows the instructor's reason and the pitfalls of a step (schema 0.15 `why`, and `common_mistakes`), and says nothing when the tutorial gave none."""
import pytest

pytest.importorskip("PyQt6")

from app.ui.screens import SessionScreen  # noqa: E402
from shared.step_record import HowTo, Step  # noqa: E402


def _step(**kw):
    return Step(id="s01", order=1, goal="Mirror the leg joints", how_to=[HowTo(text="Choose YZ, then click Mirror.", support="shown", evidence="dialog")], **kw)


def test_why_and_watch_out_are_shown_before_and_after_the_how_to():
    text = SessionScreen._detail_for(_step(why="So the right leg gets its own joints.", common_mistakes=["The default plane mirrors the wrong way."]))
    assert text.index("Why\nSo the right leg gets its own joints.") < text.index("How to do it") < text.index("Watch out\n• The default plane mirrors the wrong way.")


def test_no_reason_no_why_line():
    text = SessionScreen._detail_for(_step())
    assert "Why" not in text and "Watch out" not in text
