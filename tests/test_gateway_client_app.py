"""The app talks to the AI gateway (audit H-2): the client, the app adapters and the gateway's full reading, all over the gateway's own TestClient (no network, no provider key)."""
import pytest
from fastapi.testclient import TestClient

from app import remote
from app.pipeline import video_steps
from gateway.app import create_app
from ingestion.gateway_client import GatewayClient
from ingestion.providers.base import ProviderError, QuotaError
from ingestion.providers.fake import ScriptedProvider

GOOD = {"steps": [{"goal": "Press Tab to enter Edit Mode", "confidence": 0.9, "support": "narrated", "evidence": ["press tab"]}]}
VID = "34FBeC9mktE"
URL = f"https://www.youtube.com/watch?v={VID}"
META = [{"id": VID, "title": "Rig a leg", "duration_s": 600.0, "privacy": "public"}]


def client_for(responses=None, **kw):
    prov = ScriptedProvider(responses if responses is not None else [GOOD] * 6)
    api = create_app(provider_factory=lambda: prov, tokens={"t1": "u1"}, **kw)
    http = TestClient(api)
    return GatewayClient(lambda p, json=None, headers=None: http.post(p, json=json, headers=headers),
                         "t1", get=lambda p, params=None, headers=None: http.get(p, params=params, headers=headers), sleep=lambda _s: None), prov


def test_from_env_needs_both_url_and_token():
    assert GatewayClient.from_env({}) is None
    assert GatewayClient.from_env({"GUIDEWIRE_GATEWAY_URL": "https://x.example"}) is None
    assert GatewayClient.from_env({"GUIDEWIRE_GATEWAY_URL": "https://x.example/", "GUIDEWIRE_GATEWAY_TOKEN": "t"}) is not None


def test_answer_with_no_tutorial_uses_the_knowledge_base_route():
    c, prov = client_for()
    raw = c.answer("what is edit mode", model=False)
    from shared.answer import AnswerBundle
    assert AnswerBundle.model_validate(raw).explanations                  # a real, validated answer
    assert prov.calls == []                                           # no paid call


def test_videos_and_search_go_through_the_gateway(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    c, _ = client_for(yt_get=lambda url, params, headers: {"items": []})
    assert c.videos([VID]) == [] and c.search("rig a leg") == []


def test_gateway_upstream_failure_does_not_leak_its_detail(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    c, _ = client_for()
    with pytest.raises(ProviderError) as e:
        c.videos([VID])
    assert "YOUTUBE_API_KEY" not in str(e.value)


def test_wrong_token_is_a_plain_message():
    c, _ = client_for()
    bad = GatewayClient(c._post, "nope", get=c._get, sleep=lambda _s: None)
    with pytest.raises(ProviderError) as e:
        bad.answer("hi", model=False)
    assert "sign-in" in str(e.value) and "401" not in str(e.value)


def test_network_failure_is_a_plain_message():
    def boom(*_a, **_k):
        raise ConnectionError("getaddrinfo failed")
    c = GatewayClient(boom, "t", sleep=lambda _s: None)
    with pytest.raises(ProviderError) as e:
        c.extract(text="x")
    assert "ConnectionError" not in str(e.value) and "internet" in str(e.value)


def test_quota_is_quota():
    c, _ = client_for(paid_per_day=0)
    with pytest.raises(QuotaError):
        c.extract(text="Press Tab to enter Edit Mode")


def test_gateway_reads_a_video_like_the_app_does():
    c, prov = client_for([GOOD, {"steps": []}, GOOD, GOOD, GOOD], metadata_fetch=lambda v: None)
    sl = c.extract(video_url=URL, app="blender", duration_s=600, title_hint="Rig a leg", group=False)
    assert sl.steps and sl.title == "Rig a leg"


def test_video_steps_through_the_gateway_needs_no_provider_factory():
    c, _ = client_for()
    c.videos = lambda ids: META                                        # the YouTube lookup is the gateway's, faked here
    out = video_steps(URL, "blender", gateway=c, group=False)
    assert out.steps is not None and "found" in out.message


def test_video_steps_gateway_quota_and_error_are_plain():
    c, _ = client_for()
    c.videos = lambda ids: META
    c.extract = lambda **k: (_ for _ in ()).throw(QuotaError("daily cap"))
    assert "tomorrow" in video_steps(URL, "blender", gateway=c).message
    c.extract = lambda **k: (_ for _ in ()).throw(ProviderError("the AI service is overloaded: paste the written steps instead"))
    assert "overloaded" in video_steps(URL, "blender", gateway=c).message


def test_private_video_is_refused_before_any_paid_call():
    c, prov = client_for()
    c.videos = lambda ids: [{**META[0], "privacy": "private"}]
    out = video_steps(URL, "blender", gateway=c)
    assert out.steps is None and "private" in out.message and prov.calls == []


def test_tutorial_brief_carries_the_current_step():
    from ingestion.session import Session
    from shared.step_record import HowTo, Step, StepList
    sl = StepList(source_type="youtube", app="blender", title="T", steps=[Step(id="s1", order=1, goal="One", how_to=[HowTo(text="do it", support="said")]), Step(id="s2", order=2, goal="Two")])
    sess = Session(app="blender")
    sess.load(sl)
    sess.goto("s2")
    brief = remote.tutorial_brief(sess)
    assert brief["current"] == "s2" and [s["id"] for s in brief["steps"]] == ["s1", "s2"] and brief["steps"][0]["how_to"] == ["do it"]
    assert remote.tutorial_brief(Session(app="blender")) is None
