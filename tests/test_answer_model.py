"""Model-backed answering with a SCRIPTED provider (no network, no real model): what the model is shown, what comes back as a bundle, and that the session logic stays rule-based."""
import pytest

from ingestion import session as S
from ingestion.answer_model import SCHEMA, ModelAnswerer, build_prompt, retrieve_entries
from ingestion.providers.base import OverloadError
from ingestion.providers.fake import ScriptedProvider
from ingestion.service import Service
from shared.step_record import HowTo, Step, StepList


def reply(**kw):
    base = {"answer": "Use Skeleton > Create IK Handle.", "grounding": "knowledge_base", "source_ids": [], "step_ids": [], "confidence": "high", "in_tutorial": "not_applicable",
            "clarifying_question": None, "wants_steps": False}
    return {**base, **kw}


def tutorial():
    steps = [Step(id=f"s{i:02d}", order=i, goal=g, video_start_s=10.0 * i, video_end_s=10.0 * i + 8, how_to=[HowTo(text=f"do {g}", support="shown", evidence="x")])
             for i, g in enumerate(["Create the hip joint", "Create the knee joint", "Create an IK handle"], start=1)]
    return StepList(source_type="youtube", app="maya", title="Leg rig", app_version_tutorial="Maya 2017", steps=steps)


def session(loaded=True, app="maya"):
    s = S.Session(app=app)
    if loaded:
        s.load(tutorial(), tutorial={"id": "x", "title": "Leg rig", "source_type": "youtube"})
    return s


def test_the_prompt_carries_the_matching_entry_the_tutorial_and_the_question():
    system, prompt, entries = build_prompt("maya knee flips when i move the ik handle", "maya", session())
    assert any(e.id.startswith("maya.") for e in entries)
    assert "ENTRY maya." in prompt and "pole vector" in prompt.lower()
    assert "TUTORIAL:" in prompt and "s03 [0:30]: Create an IK handle" in prompt and "Maya 2017" in prompt and "The learner is on s01" in prompt
    assert prompt.rstrip().endswith("LEARNER QUESTION: maya knee flips when i move the ik handle")
    assert "NEVER say the tutorial" in system and "not in the tutorial" in system


def test_without_a_tutorial_the_prompt_says_so_and_other_applications_entries_are_not_offered():
    _, prompt, entries = build_prompt("what does rig doctor do", "houdini", None)
    assert "no tutorial" in prompt.lower() or "none is loaded" in prompt
    assert all("houdini" in e.apps for e in entries)
    assert all("maya" not in e.apps or "houdini" in e.apps for e in retrieve_entries("freeze transformations", "houdini"))


def test_an_answer_becomes_a_model_bundle_with_only_valid_step_ids_and_a_caveat_for_general_knowledge():
    p = ScriptedProvider([reply(answer="He creates the knee joint.", grounding="mixed", step_ids=["s02", "s99"], in_tutorial="yes")])
    b = ModelAnswerer(p)("what is he doing at 0:20", session())
    assert (b.kind, b.route, b.api_calls) == ("concept", "model", 1)
    assert b.explanations[0].applies_to_steps == ["s02"] and b.explanations[0].provenance == "model"
    assert any("general knowledge" in c for c in b.caveats)
    assert p.calls[0]["schema"] == SCHEMA and p.calls[0]["video_url"] is None


def test_a_low_confidence_reply_with_a_question_is_a_clarification():
    b = ModelAnswerer(ScriptedProvider([reply(answer="", confidence="low", clarifying_question="Where are the joints, after drawing or after import?")]))("all my joints are at the origin", session(False))
    assert b.kind == "clarification" and b.route == "clarify" and "after drawing" in b.clarification and not b.explanations


def test_the_service_sends_questions_to_the_model_but_never_state_changes():
    p = ScriptedProvider([reply(answer="It is a rotate plane solver.")])
    svc = Service(session(), None, None, None, None, answerer=ModelAnswerer(p))
    done = svc.message("i did that")                                   # rule-based: marks step 1 done, no model call
    assert done["route"] != "model" and p.calls == [] and svc.session.status["s01"] == "done"
    out = svc.message("what is the rp solver")
    assert out["route"] == "model" and "rotate plane" in out["text"] and len(p.calls) == 1
    assert svc.session.status["s01"] == "done" and svc.session.current == "s02"          # asking never moved the learner


def test_next_alone_is_a_rule_based_follow_up():
    p = ScriptedProvider([])
    svc = Service(session(), None, None, None, None, answerer=ModelAnswerer(p))
    out = svc.message("next?")
    assert out["route"] != "model" and p.calls == [] and "s01" in out["text"]


def test_when_the_model_cannot_be_reached_the_rules_answer_and_say_so():
    svc = Service(session(False), None, None, None, None, answerer=ModelAnswerer(ScriptedProvider([OverloadError("busy")])))
    out = svc.message("how do i join 2 objects")
    assert out["route"] != "model" and "model could not be reached" in out["text"]


@pytest.mark.parametrize("q", ["go back to the knee", "skip this", "what should i do next"])
def test_session_commands_do_not_call_the_model(q):
    p = ScriptedProvider([])
    svc = Service(session(), None, None, None, None, answerer=ModelAnswerer(p))
    svc.message(q)
    assert p.calls == []


def test_whats_next_with_no_tutorial_loaded_is_a_question_for_the_model():
    p = ScriptedProvider([reply(answer="Next, bind the mesh to the skeleton.")])
    svc = Service(session(False), None, None, None, None, answerer=ModelAnswerer(p))
    out = svc.message("ok and then whats next after that")
    assert out["route"] == "model" and "bind the mesh" in out["text"] and len(p.calls) == 1


def test_whats_next_with_a_tutorial_loaded_stays_a_progress_command():
    p = ScriptedProvider([])
    svc = Service(session(True), None, None, None, None, answerer=ModelAnswerer(p))
    out = svc.message("ok whats next")
    assert out["route"] != "model" and p.calls == []
