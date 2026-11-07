"""The gateway picks the rigging prompt (v7) for Maya and Houdini and keeps the baseline for Blender; /v1/answer takes the application."""


def test_gateway_uses_the_rigging_prompt_for_maya_and_the_baseline_for_blender():
    from fastapi.testclient import TestClient

    from gateway.app import create_app
    from ingestion.providers.fake import ScriptedProvider
    good = {"steps": [{"goal": "Create joints", "confidence": 0.9, "support": "narrated", "evidence": ["create joints"]}]}
    prov = ScriptedProvider([good, good])
    c = TestClient(create_app(provider_factory=lambda: prov, tokens={"t": "u"}))
    h = {"Authorization": "Bearer t"}
    assert c.post("/v1/extract", json={"text": "create joints", "app": "maya"}, headers={**h, "Idempotency-Key": "a"}).status_code == 200
    assert c.post("/v1/extract", json={"text": "press tab", "app": "blender"}, headers={**h, "Idempotency-Key": "b"}).status_code == 200
    assert "character rigging and animation tutorial for maya" in prov.calls[0]["system"]
    assert "character rigging" not in prov.calls[1]["system"]
    r = c.post("/v1/answer", json={"question": "Create joints down the arm\nCreate an IK handle on the arm", "app": "maya"}, headers=h)
    assert r.status_code == 200 and r.json()["route"] == "rigging_text"
