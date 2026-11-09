"""The gateway's /v1/answer with model=true: one paid, capped call with the knowledge base and the client's tutorial as context; progress questions stay rule-based. Scripted provider."""
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from ingestion.providers.base import OverloadError, QuotaError
from ingestion.providers.fake import ScriptedProvider

H = {"Authorization": "Bearer t1"}
REPLY = {"answer": "It is the rotate plane solver, which gives pole vector control.", "grounding": "knowledge_base", "source_ids": [], "step_ids": ["s02"], "confidence": "high",
         "in_tutorial": "yes", "clarifying_question": None}
TUTORIAL = {"title": "Leg rig", "app_version": "Maya 2017", "current": "s02", "steps": [
    {"id": "s01", "goal": "Create the hip joint", "start_s": 10, "how_to": ["Skeleton > Create Joints"]},
    {"id": "s02", "goal": "Change the solver to ikRPsolver", "start_s": 40, "how_to": []},
    {"id": "s03", "goal": "Create an IK handle", "start_s": 70, "how_to": []}]}


def make(responses, **kw):
    prov = ScriptedProvider(list(responses))
    return TestClient(create_app(provider_factory=lambda: prov, tokens={"t1": "u1"}, **kw)), prov


def ask(c, **body):
    return c.post("/v1/answer", json={"question": "why did he change the solver to rp", "app": "maya", **body}, headers=H)


def test_without_model_true_nothing_is_paid():
    c, prov = make([])
    assert ask(c).status_code == 200 and prov.calls == []


def test_model_true_makes_one_call_with_the_tutorial_in_the_prompt():
    c, prov = make([REPLY])
    r = ask(c, model=True, tutorial=TUTORIAL, history=["i did that"])
    assert r.status_code == 200 and r.json()["route"] == "model" and r.json()["api_calls"] == 1
    assert r.json()["explanations"][0]["applies_to_steps"] == ["s02"]
    assert len(prov.calls) == 1
    prompt = prov.calls[0]["prompt"]
    assert "s02 [0:40]: Change the solver to ikRPsolver" in prompt and "Maya 2017" in prompt and "The learner is on s02" in prompt and "i did that" in prompt
    assert prov.calls[0]["video_url"] is None


def test_progress_questions_stay_rule_based_even_with_model_true():
    c, prov = make([])
    r = ask(c, model=True, tutorial=TUTORIAL, question="what is next")
    assert r.status_code == 200 and prov.calls == [] and r.json()["route"] != "model"


def test_a_model_answer_counts_against_the_daily_cap():
    c, prov = make([REPLY, REPLY], paid_per_day=1)
    assert ask(c, model=True).status_code == 200
    assert ask(c, model=True).status_code == 429 and len(prov.calls) == 1


@pytest.mark.parametrize("err,code", [(QuotaError("429"), 429), (OverloadError("busy"), 503)])
def test_provider_failures_are_429_and_503(err, code):
    c, _ = make([err])
    assert ask(c, model=True).status_code == code


def test_too_many_steps_and_an_unknown_current_step():
    big = {**TUTORIAL, "steps": [{"id": f"s{i:03d}", "goal": "x"} for i in range(121)]}
    c, _ = make([REPLY])
    assert ask(c, model=True, tutorial=big).status_code == 422
    assert ask(c, model=True, tutorial={**TUTORIAL, "current": "s99"}).status_code == 200      # ignored, not an error
