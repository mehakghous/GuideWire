import pytest

from ingestion.extract import ExtractionError, extract_from_text, extract_from_video
from ingestion.providers.base import ProviderError
from ingestion.providers.fake import ScriptedProvider
from ingestion.youtube.metadata import (
    Chapter, parse_chapters, parse_iso_duration, parse_video_id,
)

GOOD = {
    "steps": [
        {"goal": "Enter Edit Mode", "actions": [{"verb": "press_keys", "keys": ["Tab"]}],
         "expected_state": [{"kind": "mode", "name": "EDIT_MESH"}], "confidence": 0.9,
         "evidence": ["'press Tab'"]},
        {"goal": "Pick Extrude Region",
         "actions": [{"verb": "click", "ui_element": "Extrude Region"}],
         "expected_state": [{"kind": "active_tool", "name": "builtin.extrude_region"}],
         "confidence": 0.8},
    ]
}


def test_text_extraction_happy_path():
    p = ScriptedProvider([GOOD])
    sl = extract_from_text(p, "1. Press Tab. 2. Choose Extrude Region.")
    assert [s.id for s in sl.steps] == ["s01", "s02"]
    assert all(s.verifiable for s in sl.steps)
    assert sl.source_type == "written" and sl.model_id == "scripted-test-provider"
    assert "EDIT_MESH" in p.calls[0]["system"] and p.calls[0]["video_url"] is None


def test_retry_after_invalid_output_includes_error():
    p = ScriptedProvider([{"steps": [{"goal": "x"}]}, GOOD])  # first misses confidence
    sl = extract_from_text(p, "do things")
    assert len(sl.steps) == 2 and len(p.calls) == 2
    assert "rejected" in p.calls[1]["prompt"]


def test_gives_up_after_second_invalid():
    p = ScriptedProvider([{"steps": []}, {"steps": []}])
    with pytest.raises(ExtractionError):
        extract_from_text(p, "do things")


def test_provider_error_surfaces_without_retry():
    p = ScriptedProvider([ProviderError("quota")])
    with pytest.raises(ExtractionError, match="quota"):
        extract_from_text(p, "do things")
    assert len(p.calls) == 1


def test_empty_text_rejected():
    with pytest.raises(ExtractionError):
        extract_from_text(ScriptedProvider([]), "   ")


def test_out_of_vocabulary_state_is_dropped_not_fatal():
    raw = {"steps": [{"goal": "x", "expected_state": [{"kind": "mode", "name": "SPACE"}],
                      "confidence": 0.9}]}
    sl = extract_from_text(ScriptedProvider([raw]), "x")
    assert sl.steps[0].verifiable is False and sl.steps[0].flags


def test_video_extraction_passes_url_only_and_checks_duration():
    raw = {"steps": [{"goal": "a", "video_start_s": 5, "video_end_s": 20, "confidence": 0.7}]}
    p = ScriptedProvider([raw])
    sl = extract_from_video(p, "dQw4w9WgXcQ", duration_s=100)
    assert p.calls[0]["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert sl.source_type == "youtube" and sl.video_id == "dQw4w9WgXcQ"
    bad = {"steps": [{"goal": "a", "video_start_s": 500, "confidence": 0.7}]}
    with pytest.raises(ExtractionError):
        extract_from_video(ScriptedProvider([bad, bad]), "dQw4w9WgXcQ", duration_s=100)


@pytest.mark.parametrize("u", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "dQw4w9WgXcQ",
])
def test_parse_video_id(u):
    assert parse_video_id(u) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("u", ["https://example.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/watch", "nope"])
def test_parse_video_id_rejects(u):
    with pytest.raises(ValueError):
        parse_video_id(u)


def test_chapters():
    d = "Intro text\n0:00 Intro\n1:30 - Modeling basics\n12:05 Rendering\nlinks: x"
    assert parse_chapters(d) == [Chapter(0, "Intro"), Chapter(90, "Modeling basics"), Chapter(725, "Rendering")]
    assert parse_chapters("0:00 a\n1:00 b") == []            # fewer than 3
    assert parse_chapters("0:10 a\n1:00 b\n2:00 c") == []    # must start at 0:00
    assert parse_chapters("0:00 a\n2:00 b\n1:00 c") == []    # must ascend
    assert parse_chapters("0:00 a\n1:00:30 b\n1:10:00 c")[1].start_s == 3630


def test_iso_duration():
    assert parse_iso_duration("PT15M33S") == 933
    assert parse_iso_duration("PT1H2M") == 3720
    assert parse_iso_duration("PT45S") == 45


def test_model_style_predicates_and_mode_alias():
    raw = {"steps": [{"goal": "x", "confidence": 0.9,
                      "expected_state": [{"kind": "mode", "name": "Edit Mode"},
                                         {"kind": "property_equals", "name": "a.b", "expected_value": 2}]}]}
    sl = extract_from_text(ScriptedProvider([raw]), "x")
    ex = sl.steps[0].expected_state
    assert ex[0].target == "EDIT_MESH" and ex[1].value == 2 and sl.steps[0].flags == []
