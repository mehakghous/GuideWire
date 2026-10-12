"""Data API helpers and playlist expansion with a FAKE transport: no network, no key needed. The real integration is exercised separately,
only when the project owner has authorised it (see scripts/grow_tutorial_catalog.py)."""
import pytest

from ingestion.handoff import classify_url, plan_ingestion
from ingestion.tutorials import playlist_recommendations
from ingestion.youtube import api

KEY = "SECRET-KEY-VALUE"


class Fake:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, params, headers):
        self.calls.append((url, dict(params), dict(headers)))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def pl_page():
    return {"items": [
        {"snippet": {"title": "Intro", "position": 0, "resourceId": {"videoId": "AAAAAAAAAAA"}, "videoOwnerChannelTitle": "Blender"}, "contentDetails": {"videoId": "AAAAAAAAAAA"}, "status": {"privacyStatus": "public"}},
        {"snippet": {"title": "Deleted video", "position": 1, "resourceId": {"videoId": "BBBBBBBBBBB"}}, "contentDetails": {"videoId": "BBBBBBBBBBB"}, "status": {"privacyStatus": "public"}},
        {"snippet": {"title": "Private video", "position": 2, "resourceId": {"videoId": "CCCCCCCCCCC"}}, "contentDetails": {"videoId": "CCCCCCCCCCC"}, "status": {"privacyStatus": "private"}},
        {"snippet": {"title": "Join objects", "position": 3, "resourceId": {"videoId": "DDDDDDDDDDD"}, "videoOwnerChannelTitle": "Blender"}, "contentDetails": {"videoId": "DDDDDDDDDDD"}, "status": {"privacyStatus": "public"}}]}


def meta_page():
    return {"items": [
        {"id": "AAAAAAAAAAA", "snippet": {"title": "Intro", "channelTitle": "Blender", "publishedAt": "2019-07-16T00:00:00Z", "description": "0:00 a\n1:00 b\n2:00 c"},
         "contentDetails": {"duration": "PT3M8S", "caption": "true"}, "status": {"license": "creativeCommon", "embeddable": True, "privacyStatus": "public"}}]}


def test_playlist_links_are_classified_and_a_video_inside_a_playlist_stays_a_video():
    i = classify_url("https://www.youtube.com/playlist?list=PLabcdefghijk")
    assert (i.kind, i.playlist_id, i.video_id) == ("youtube_playlist", "PLabcdefghijk", None)
    v = classify_url("https://www.youtube.com/watch?v=34FBeC9mktE&list=PLabcdefghijk&index=3")
    assert (v.kind, v.video_id, v.playlist_id) == ("youtube_video", "34FBeC9mktE", "PLabcdefghijk")


def test_playlist_items_keep_order_and_mark_unavailable_entries():
    g = Fake([pl_page()])
    items = api.playlist_items("PLabcdefghijk", api_key=KEY, get=g)
    assert [i["position"] for i in items] == [0, 1, 2, 3] and [i["available"] for i in items] == [True, False, False, True]
    url, params, headers = g.calls[0]
    assert url.endswith("/playlistItems") and params["playlistId"] == "PLabcdefghijk" and params["maxResults"] == 50
    assert headers == {"x-goog-api-key": KEY} and KEY not in url and KEY not in str(params)       # the key is a header, never a URL/param


def test_recommendations_only_contain_verified_available_videos_in_playlist_order():
    items = api.playlist_items("PLabcdefghijk", api_key=KEY, get=Fake([pl_page()]))
    meta = api.videos_metadata(["AAAAAAAAAAA", "DDDDDDDDDDD"], api_key=KEY, get=Fake([meta_page()]))          # videos.list did not return DDDDDDDDDDD
    recs, skipped = playlist_recommendations(items, meta, "PLabcdefghijk")
    assert [r.url.split("=")[1] for r in recs] == ["AAAAAAAAAAA"]
    assert recs[0].duration_s == 188 and recs[0].captions_available is None and recs[0].caption_kind is None and recs[0].chapters == 3     # (the platform flag is deliberately not copied) and recs[0].blender_version_hint is None
    assert len(skipped) == 3 and any("Deleted video" in x for x in skipped) and any("Join objects" in x for x in skipped)
    assert "not recorded" in recs[0].note and "Not yet converted" in recs[0].note


def test_a_failure_is_raised_once_with_the_key_redacted_and_never_retried():
    g = Fake([RuntimeError(f"boom {KEY}"), pl_page()])
    with pytest.raises(api.YouTubeApiError) as e:
        api.playlist_items("PLabcdefghijk", api_key=KEY, get=g)
    assert KEY not in str(e.value) and len(g.calls) == 1


def test_missing_key_and_bad_playlist_id_fail_before_any_request(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    g = Fake([])
    with pytest.raises(api.YouTubeApiError, match="not set"):
        api.playlist_items("PLabcdefghijk", get=g)
    with pytest.raises(api.YouTubeApiError, match="not a playlist id"):
        api.playlist_items("bad id!", api_key=KEY, get=g)
    assert g.calls == []


def test_search_hits_are_candidates_with_no_invented_fields():
    hits = api.search_videos("blender join objects", api_key=KEY, get=Fake([{"items": [
        {"id": {"videoId": "AAAAAAAAAAA"}, "snippet": {"title": "Join", "channelTitle": "X"}}, {"id": {"kind": "youtube#channel"}, "snippet": {"title": "skip me"}}]}]))
    assert hits == [{"video_id": "AAAAAAAAAAA", "title": "Join", "channel": "X"}]


def test_videos_metadata_dedupes_caps_and_tolerates_missing_fields():
    g = Fake([{"items": [{"id": "AAAAAAAAAAA", "snippet": {"title": "t"}, "contentDetails": {}, "status": {}}]}])
    m = api.videos_metadata(["AAAAAAAAAAA"] * 3 + [f"{i:011d}" for i in range(80)], api_key=KEY, get=g)
    assert len(g.calls[0][1]["id"].split(",")) == 50
    assert m[0]["duration_s"] is None and m[0]["captions_flag"] is None and m[0]["licence"] is None        # absent in the API reply -> None, not a guess


def test_playlist_entries_hand_off_one_video_at_a_time(tmp_path):
    p = plan_ingestion("https://www.youtube.com/watch?v=AAAAAAAAAAA&list=PLabcdefghijk", cache_dir=tmp_path)
    assert p.status == "needs_transcript" and p.video_id == "AAAAAAAAAAA"
