"""The starter plan (ingestion/starter_plan.py): "where do I start" answered with a STEP LIST from the knowledge base, no model call, labelled as a draft. Scripted provider, no network."""
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from ingestion.answer_model import ModelAnswerer
from ingestion.providers.fake import ScriptedProvider
from ingestion.service import Service
from ingestion.session import Session
from ingestion.starter_plan import ORDER, app_in, plan_request, starter_bundle, starter_plan

APPS = ("blender", "maya", "houdini")


@pytest.mark.parametrize("text, mode", [
    ("where do i start rigging in maya im a beginner", "start"), ("im new to blender how do i start rigging a character", "start"), ("how do i get started with kinefx", "start"),
    ("what should i do to my model before rigging", "before"), ("wat do i do to my model b4 rigging it", None),                      # "b4" is not recognised: it is left to the model
    ("i made the skeleton whats next", "after_skeleton"), ("ok i made the joints whats next", "after_skeleton"),
    ("how do i make bones for my character", None), ("how do i add ik to a leg", None), ("whats the difference between fk and ik", None), ("ok whats next", None)])
def test_which_questions_ask_for_a_starter_plan(text, mode):
    assert plan_request(text) == mode


def test_the_application_is_read_from_the_words_only_when_exactly_one_is_named():
    assert app_in("where do i start in houdini") == "houdini" and app_in("start with kinefx") == "houdini"
    assert app_in("where do i start") is None and app_in("blender or maya?") is None and app_in("x", "maya") == "maya"


@pytest.mark.parametrize("app", APPS)
def test_the_plan_is_a_valid_labelled_draft_in_the_order_of_the_proposals_stages(app):
    sl = starter_plan(app)
    assert sl.source_type == "goal_draft" and sl.prompt_version == "starter-plan-v1" and sl.group_problems == [] and len(sl.groups) >= 7
    assert [s.order for s in sl.steps] == list(range(1, len(sl.steps) + 1)) and len({s.id for s in sl.steps}) == len(sl.steps)
    assert all(s.provenance == "catalog_template" and s.review_status == "drafted_automatically" and s.kind == "mechanics" and s.group_id and s.source_refs[0].startswith("kb:") for s in sl.steps)
    assert all(h.support == "catalog" for s in sl.steps for h in (*s.how_to, *s.check))                   # guidance the knowledge base gives, never "shown" in a video
    assert not [f for s in sl.steps for f in s.flags if "vocabulary" in f]                               # menu paths are real names of the application
    labels = [label.lower() for _, label, _ in sl.groups]
    skel = next(i for i, g in enumerate(labels) if "joint" in g or "skeleton" in g or "bones" in g)
    skin = next(i for i, g in enumerate(labels) if "bind" in g or "attach" in g)
    ik = next(i for i, g in enumerate(labels) if "ik" in g)
    assert skel < skin < ik                                                                             # the beginner order: skeleton, then bind the mesh, then IK
    assert [e.split(".")[1] for e in ORDER[app]][0] in sl.steps[0].source_refs[0]


def test_stage_labels_use_the_applications_own_words_and_every_entry_has_one():
    from ingestion.starter_plan import LABELS
    for app in APPS:
        assert all(i in LABELS for i in ORDER[app])
        assert [lab for _, lab, _ in starter_plan(app).groups] == [LABELS[i] for i in ORDER[app]]
    assert not any("history" in lab.lower() for _, lab, _ in starter_plan("blender").groups)                     # a Maya idea, not a Blender one
    assert "Joint Capture, then Joint Deform" in [lab for _, lab, _ in starter_plan("houdini").groups][4]


def test_menu_paths_lose_their_bracketed_notes_for_the_overlay():
    sl = starter_plan("maya")
    assert sl.steps[0].actions[0].ui_element == "Modify > Freeze Transformations"


def test_modes_before_and_after_the_skeleton():
    assert [g for _, g, _ in starter_plan("blender", "before").groups] == ["Apply the object's transforms (Object > Apply)"]
    assert starter_plan("houdini", "before") is None                                                    # the knowledge base has nothing for it: no invented answer
    after = [g.lower() for _, g, _ in starter_plan("maya", "after_skeleton").groups]
    assert after[0].startswith("name the joints") and any("bind" in g for g in after) and not any("freeze" in g or "create a joint" in g for g in after)       # naming comes next; neither the clean-up nor the joints are repeated
    blender = [g.lower() for _, g, _ in starter_plan("blender", "after_skeleton").groups]
    assert any("attach the mesh" in g for g in blender) and not any("add the bones" in g or "apply" in g for g in blender)                                        # binding the mesh is not lost


def test_the_bundle_says_it_is_a_draft_names_the_gap_and_asks_for_the_application_when_unknown():
    b = starter_bundle("where do i start rigging", "maya")
    assert b.kind == "procedure" and b.route == "rigging_knowledge" and b.trust == "catalog" and b.steps and b.api_calls == 0
    assert any("not from a tutorial" in c for c in b.caveats) and any("scene units" in c for c in b.caveats)
    ask = starter_bundle("where do i start rigging", None)
    assert ask.kind == "clarification" and "Which application" in ask.clarification and not ask.steps
    assert starter_bundle("how do i add ik to a leg", "maya") is None


def _service():
    p = ScriptedProvider([])                                                                               # any model call would fail the test
    return Service(Session(), None, None, None, None, answerer=ModelAnswerer(p)), p


def test_the_service_answers_where_to_start_with_steps_and_no_model_call():
    svc, p = _service()
    out = svc.message("where do i start rigging in maya im a beginner")
    assert out["route"] == "rigging_knowledge" and p.calls == [] and svc.last_bundle.steps.app == "maya" and "/load last" in out["text"]
    loaded = svc.command("/load last")
    assert "Loaded" in loaded["text"] and svc.session.steps is not None and svc.session.steps.source_type == "goal_draft"


def test_the_service_asks_which_application_and_the_next_message_completes_the_question():
    svc, p = _service()
    first = svc.message("where do i start rigging")
    assert first["kind"] == "clarification" and svc.pending_plan and svc.last_bundle is None
    second = svc.message("houdini")
    assert second["route"] == "rigging_knowledge" and svc.last_bundle.steps.app == "houdini" and svc.pending_plan is None and p.calls == []


def test_with_a_tutorial_loaded_the_question_is_not_taken_over():
    svc, p = _service()
    svc.message("where do i start rigging in blender")
    svc.command("/load last")
    out = svc.message("where do i start in this tutorial")
    assert out["route"] != "rigging_knowledge"


H = {"Authorization": "Bearer t1"}


def test_the_gateway_returns_the_plan_without_a_model_call():
    prov = ScriptedProvider([])
    c = TestClient(create_app(provider_factory=lambda: prov, tokens={"t1": "u1"}))
    for model in (False, True):
        r = c.post("/v1/answer", json={"question": "where do i start rigging", "app": "houdini", "model": model}, headers=H)
        assert r.status_code == 200 and r.json()["route"] == "rigging_knowledge" and len(r.json()["steps"]["steps"]) >= 10 and r.json()["steps"]["source_type"] == "goal_draft"
    assert prov.calls == []


def test_a_chosen_application_is_used_but_the_default_is_not():
    svc, p = _service()
    assert svc.message("what should i do before rigging")["kind"] == "clarification"           # the session default of "blender" is not a choice
    svc.command("/app maya")
    out = svc.message("what should i do before rigging")
    assert out["route"] == "rigging_knowledge" and svc.last_bundle.steps.app == "maya" and p.calls == []


@pytest.mark.parametrize("text, app", [("give me the steps to rig a character in blender", "blender"), ("walk me through the whole rig in maya", "maya"), ("teach me rigging from scratch in houdini", "houdini")])
def test_an_explicit_request_for_the_whole_rig_gets_the_starter_plan(text, app):
    b = starter_bundle(text, app)
    assert b.route == "rigging_knowledge" and b.steps.title.startswith("Starter plan") and len(b.steps.groups) >= 7


@pytest.mark.parametrize("text, app, topic", [("give me steps to implement ik in maya", "maya", "ik"), ("show me the steps to mirror joints in maya", "maya", "mirror"),
                                              ("give me the steps to add an ik constraint in blender", "blender", "ik")])
def test_an_explicit_request_for_a_topic_gets_just_that_topic(text, app, topic):
    b = starter_bundle(text, app)
    assert b.route == "rigging_knowledge" and 0 < len(b.steps.groups) <= 2 and topic in b.steps.title.lower() and not b.steps.title.startswith("Starter plan")
    assert b.steps.source_type == "goal_draft" and b.steps.group_problems == [] and b.api_calls == 0


@pytest.mark.parametrize("text", ["give me steps to implement x", "give me steps to make a cake", "how do i add ik to a leg", "what is the next step in this tutorial", "how to add a bone"])
def test_what_is_not_a_clear_request_for_known_steps_is_left_to_the_model(text):
    assert starter_bundle(text, "maya") is None


def test_the_model_can_say_the_learner_wants_steps_and_the_steps_still_come_only_from_the_knowledge_base():
    from ingestion.answer_model import SCHEMA
    p = ScriptedProvider([{"answer": "Create the IK handle, then add a pole vector.", "grounding": "knowledge_base", "source_ids": ["maya.ik_handle", "maya.pole_vector"], "step_ids": [],
                           "confidence": "high", "in_tutorial": "not_applicable", "clarifying_question": None, "wants_steps": True}])
    b = ModelAnswerer(p)("could you list what i have to do, in order, to get ik working on the arm", Session(app="maya"))
    assert "wants_steps" in SCHEMA["required"] and b.api_calls == 1 and b.route == "model"
    refs = {s.source_refs[0] for s in b.steps.steps}
    assert b.steps is not None and b.kind == "procedure" and "kb:maya.ik_handle" in refs and refs <= {"kb:maya.ik_handle", "kb:maya.pole_vector"} and b.steps.source_type == "goal_draft"      # only topics it was offered
    assert all(h.support == "catalog" for s in b.steps.steps for h in s.how_to)
    no = ModelAnswerer(ScriptedProvider([{"answer": "x", "grounding": "knowledge_base", "source_ids": ["maya.ik_handle"], "step_ids": [], "confidence": "high", "in_tutorial": "not_applicable",
                                          "clarifying_question": None, "wants_steps": False}]))("what is ik", Session(app="maya"))
    assert no.steps is None                                                                           # an ordinary question keeps its text answer
