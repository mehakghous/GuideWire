"""Live smoke tests: real network, real keys, small cost. Run with:  pytest -m live -s

Never prints key values. Skipped automatically when keys are absent.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()
pytestmark = pytest.mark.live

needs_gemini = pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="no GEMINI_API_KEY")
needs_yt = pytest.mark.skipif(not os.environ.get("YOUTUBE_API_KEY"), reason="no YOUTUBE_API_KEY")

WRITTEN = """1. Delete the default cube by selecting it and pressing X.
2. Add a UV Sphere from Add > Mesh > UV Sphere.
3. Press Tab to enter Edit Mode.
4. Switch to the Sculpting workspace and pick the Draw brush.
5. Make it look nice."""


@needs_yt
def test_youtube_metadata_known_public_video():
    from ingestion.youtube.metadata import fetch_metadata

    m = fetch_metadata("dQw4w9WgXcQ")
    assert m.privacy_status == "public" and m.duration_s == 214 and m.embeddable


@needs_gemini
def test_written_pipeline_live():
    from ingestion.extract import extract_from_text
    from ingestion.providers.gemini import GeminiProvider

    sl = extract_from_text(GeminiProvider(max_attempts=2), WRITTEN)
    for s in sl.steps:
        print(s.order, s.goal, "| verifiable", s.verifiable, "| conf", s.confidence,
              [(p.kind, p.target) for p in s.expected_state], s.flags)
    assert len(sl.steps) >= 4
    assert sum(s.verifiable for s in sl.steps) >= 2  # mode / workspace / tool steps are checkable
    assert not sl.steps[-1].verifiable  # "make it look nice" must stay unverifiable
