
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from ingestion.providers.base import ProviderError, QuotaError
from ingestion.providers.fake import ScriptedProvider
from ingestion.youtube.metadata import VideoMetadata

H = {"Authorization": "Bearer t1"}
GOOD = {"steps": [{"goal": "Press Tab to enter Edit Mode", "confidence": 0.9, "support": "narrated", "evidence": ["press tab"]}]}


def make(responses=None, **kw):
    prov = ScriptedProvider(responses if responses is not None else [GOOD] * 5)
    app = create_app(provider_factory=lambda: prov, tokens={"t1": "u1", "t2": "u2"}, **kw)
    return TestClient(app), prov


def post(c, body, key="k1", headers=H):
    return c.post("/v1/extract", json=body, headers={**headers, "Idempotency-Key": key} if key else headers)


def test_token_required():
    c, _ = make()
    assert c.post("/v1/extract", json={"text": "x"}).status_code == 401
    assert c.get("/v1/youtube/search?q=x", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_non_youtube_url_rejected_and_provider_untouched():
    c, prov = make()
    for url in ("https://evil.example/watch?v=34FBeC9mktE", "https://vimeo.com/123", "file:///etc/passwd"):
        assert post(c, {"video_url": url}).status_code == 422
    assert prov.calls == []


def test_media_and_oversize_bodies_rejected():
    c, _ = make()
    assert c.post("/v1/extract", content=b"\x00\x01", headers={**H, "Content-Type": "video/mp4", "Idempotency-Key": "a"}).status_code == 415
    assert post(c, {"text": "x" * 70_000}).status_code in (413, 422)


def test_idempotency_key_required_and_replay_costs_one_call():
    c, prov = make()
    assert post(c, {"text": "press tab"}, key=None).status_code == 400
    a, b = post(c, {"text": "press tab"}), post(c, {"text": "press tab"})
    assert a.status_code == 200 and a.json() == b.json()
    assert len(prov.calls) == 1


def test_quota_error_is_429_and_overload_is_503():
    c, _ = make([QuotaError("429")])
    assert post(c, {"text": "press tab"}).status_code == 429
    c, _ = make([ProviderError("overloaded")] * 3)
    assert post(c, {"text": "press tab"}, key="k2").status_code == 503


def test_daily_cap_per_user_and_rate_limit():
    c, _ = make(paid_per_day=1)
    assert post(c, {"text": "press tab"}, key="a").status_code == 200
    assert post(c, {"text": "press tab"}, key="b").status_code == 429
    assert post(c, {"text": "press tab"}, key="c", headers={"Authorization": "Bearer t2"}).status_code == 200   # other user unaffected
    c, _ = make(rate_per_min=2)
    codes = [c.post("/v1/answer", json={"question": "how do I extrude"}, headers=H).status_code for _ in range(3)]
    assert codes[-1] == 429


def test_search_stops_at_daily_youtube_quota(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    calls = []
    c, _ = make(rate_per_min=10_000, yt_get=lambda url, params, headers: calls.append(1) or {"items": []})
    import gateway.app as g
    codes = [c.get("/v1/youtube/search?q=blender", headers=H).status_code for _ in range(g.YT_SEARCH_PER_DAY + 1)]
    assert codes.count(200) == g.YT_SEARCH_PER_DAY and codes[-1] == 429 and len(calls) == g.YT_SEARCH_PER_DAY


def test_metadata_returns_only_the_documented_fields():
    m = VideoMetadata("34FBeC9mktE", "T", "long description", 188, True, "public", "CC", "2020", [])
    c, _ = make(metadata_fetch=lambda vid: m)
    r = c.get("/v1/youtube/metadata?video_id=34FBeC9mktE", headers=H).json()
    assert set(r) == {"video_id", "title", "duration_s", "chapters", "license", "embeddable"}
    assert c.get("/v1/youtube/metadata?video_id=bad", headers=H).status_code == 422


def test_client_retries_overload_with_one_key_and_never_retries_quota():
    from ingestion.gateway_client import GatewayClient
    keys, c = [], None

    class Spy:
        def __init__(self, c): self.c = c
        def __call__(self, path, json, headers):
            keys.append(headers["Idempotency-Key"])
            return self.c.post(path, json=json, headers=headers)

    c, prov = make([ProviderError("busy"), ProviderError("busy"), ProviderError("busy"), GOOD, GOOD])
    sleeps = []
    gc = GatewayClient(Spy(c), "t1", attempts=3, sleep=sleeps.append)
    with pytest.raises(ProviderError, match="written steps"):
        gc.extract(text="press tab")
    assert len(set(keys)) == 1 and sleeps == [2, 4]
    c, _ = make([QuotaError("429")])
    with pytest.raises(QuotaError):
        GatewayClient(Spy(c), "t1", sleep=sleeps.append).extract(text="press tab")
