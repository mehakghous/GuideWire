"""Tests for the opt-in caption adapter. A fake caption source is injected: no network, no third-party library needed."""
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingestion.transcript_ingest import ingest_transcript
from ingestion.youtube import captions as C

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


@dataclass
class Snip:
    start: float
    duration: float
    text: str


class Track:
    def __init__(self, lang, generated, snippets):
        self.language_code, self.is_generated, self._s = lang, generated, snippets

    def fetch(self):
        return [Snip(*x) for x in self._s]


class FakeApi:
    def __init__(self, tracks, error=None):
        self.tracks, self.error, self.list_calls = tracks, error, 0

    def list(self, video_id):
        self.list_calls += 1
        if self.error:
            raise self.error
        return self.tracks


AUTO = Track("en", True, [(0.1, 2, "auto words"), (3.0, 2, "to press tab")])
CREATOR = Track("en", False, [(0.0, 3, "creator words"), (4.0, 3, "now go into edit mode")])


def test_prefers_creator_written_over_auto(tmp_path):
    r = C.fetch_captions("vid", api=FakeApi([AUTO, CREATOR]), cache_dir=tmp_path, now=NOW)
    assert r.source == "creator" and "creator words" in r.text and r.tracks == [("en", True), ("en", False)]
    only_auto = C.fetch_captions("vid2", api=FakeApi([AUTO]), cache_dir=tmp_path, now=NOW)
    assert only_auto.source == "auto"


def test_no_matching_language_is_reported_not_guessed(tmp_path):
    with pytest.raises(C.CaptionsUnavailable, match="no caption track"):
        C.fetch_captions("vid", api=FakeApi([Track("de", False, [(0, 1, "hallo")])]), cache_dir=tmp_path, now=NOW)


def test_second_request_comes_from_the_cache_without_a_call(tmp_path):
    api = FakeApi([CREATOR])
    first = C.fetch_captions("vid", api=api, cache_dir=tmp_path, now=NOW)
    again = C.fetch_captions("vid", api=api, cache_dir=tmp_path, now=NOW + timedelta(days=1))
    assert api.list_calls == 1 and again.from_cache and not first.from_cache and again.text == first.text


def test_cache_is_deleted_after_thirty_days(tmp_path):
    C.fetch_captions("old", api=FakeApi([CREATOR]), cache_dir=tmp_path, now=NOW)
    C.fetch_captions("new", api=FakeApi([CREATOR]), cache_dir=tmp_path, now=NOW + timedelta(days=20))
    removed = C.purge_expired(tmp_path, NOW + timedelta(days=31))
    assert removed == ["old"] and (tmp_path / "new.json").exists() and not (tmp_path / "old.json").exists()
    api = FakeApi([CREATOR])                                     # an expired entry is re-fetched, not served
    C.fetch_captions("old", api=api, cache_dir=tmp_path, now=NOW)
    C.fetch_captions("old", api=api, cache_dir=tmp_path, now=NOW + timedelta(days=45))
    assert api.list_calls == 2


def test_a_block_is_reported_once_and_never_retried(tmp_path):
    class RequestBlocked(Exception):
        pass
    api = FakeApi([], error=RequestBlocked("blocked"))
    with pytest.raises(C.CaptionsBlocked):
        C.fetch_captions("vid", api=api, cache_dir=tmp_path, now=NOW)
    assert api.list_calls == 1                                   # no retry, no workaround
    other = FakeApi([], error=ValueError("boom"))
    with pytest.raises(C.CaptionsUnavailable) as ei:
        C.fetch_captions("vid", api=other, cache_dir=tmp_path, now=NOW)
    assert not isinstance(ei.value, C.CaptionsBlocked)


def test_output_feeds_the_offline_transcript_route(tmp_path):
    r = C.fetch_captions("vid", api=FakeApi([CREATOR]), cache_dir=tmp_path, now=NOW)
    assert r.text.splitlines()[1].startswith("00:00:04.000 now go into edit mode")
    res = ingest_transcript(r.text, duration_s=20, version="2.80")
    assert [s.source_refs[0].split(":")[1].split("@")[0] for s in res.steplist.steps] == ["mode.enter_edit"]
    assert res.steplist.steps[0].support == "narrated"            # captions are narrated evidence, never visual


def test_nothing_in_the_product_fetches_captions_automatically():
    code = ("import ingestion.router, ingestion.answer_kb, ingestion.transcript_ingest, ingestion.cli, sys;"
            "print([m for m in sys.modules if m.startswith('youtube_transcript_api')])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env={"PYTHONPATH": str(ROOT)})
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_a_url_in_a_question_does_not_trigger_a_fetch(monkeypatch):
    from ingestion.router import route
    monkeypatch.setattr(C, "fetch_captions", lambda *a, **k: (_ for _ in ()).throw(AssertionError("captions fetched automatically")))
    b = route("Turn this tutorial into an interactive workflow: https://www.youtube.com/watch?v=34FBeC9mktE", kb=None, tutorials=[])
    assert b.route == "tutorial_import" and b.network_calls == 0
