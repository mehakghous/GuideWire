"""Offline tests for the no-model routes: corpus, catalog integrity, router policy, reviewed workflows, manual steps, CLI.
Nothing here uses the network, a key, or a model."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.catalog import OPERATIONS, BY_ID, normalise_shortcut, version_status
from ingestion.eval.offline_report import check, load_cases, run_all, run_case
from ingestion.evaluator import evaluate_step
from ingestion.knowledge import finish, how_to_steps, make_step
from ingestion.profiles import BLENDER
from ingestion.router import route
from ingestion.validate import ValidationFailure
from ingestion.workflows import ReviewedWorkflowStore, normalise_manual_steps, op_key, text_key
from shared.step_record import Step, StepList

ROOT = Path(__file__).resolve().parent.parent
CASES = load_cases()


# ---------------------------------------------------------------- the corpus
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_corpus_case(case):
    bundle, _ = run_case(case)
    assert check(case, bundle) == []


def test_corpus_summary_is_consistent():
    s = run_all()["summary"]
    assert s["cases"] == len(CASES) >= 35
    assert s["model_calls_made"] == 0 and s["schema_valid_rate"] == 1.0
    assert s["fallback_required"] >= 3 and s["clarifications"] >= 3          # the corpus covers declining and asking
    cats = {c["category"].split("/")[0] for c in CASES}
    for need in ("procedural", "howto", "concept", "troubleshooting", "mixed", "ambiguous", "unsupported", "missing prerequisite",
                 "conflicting", "version-sensitive", "duplicate", "long transcript"):
        assert any(need in c for c in cats), f"corpus lacks category {need}"


# ---------------------------------------------------------------- catalog integrity
def test_every_operation_states_its_basis():
    for op in OPERATIONS:
        assert op.sources, op.id
        for s in op.sources:
            assert s.verified_on and s.licence and s.version, (op.id, s.title)
        if any(s.kind == "manual" for s in op.sources):
            assert all("Blender Documentation Team" in (s.licence or "") for s in op.sources if s.kind == "manual")
        for sc in op.shortcuts:
            assert sc == normalise_shortcut(sc), (op.id, sc)


def test_templates_use_only_the_known_vocabulary_and_build_valid_steps():
    for op in OPERATIONS:
        for tpl in ([op.clause] if op.clause else []) + list(op.how_to):
            for p in (*tpl.start_state, *tpl.expected_state):
                if p.kind == "mode":
                    assert p.target in BLENDER.modes
        if op.how_to:
            steps = [make_step(i + 1, t, op, "catalog_template") for i, t in enumerate(op.how_to)]
            sl = finish(steps, "catalog")
            assert all(s.provenance == "catalog_template" and s.source_refs[0].startswith("catalog:") for s in sl.steps)


def test_version_status_never_claims_verification_for_unread_manuals():
    op = BY_ID["object.join"]
    assert version_status(op, "2.80")[0] == "unverified"
    assert version_status(op, "2.70")[0] == "incompatible"
    assert version_status(op, None)[0] == "unknown"


def test_catalog_expected_states_work_with_the_observed_state_evaluator():
    steps, ctx, _ = how_to_steps(BY_ID["mode.enter_edit"], "2.80")
    sl = finish(steps, "catalog")
    tab = sl.steps[-1]
    assert evaluate_step(tab, {"mode": "EDIT_MESH"}).status == "met"
    assert evaluate_step(tab, {"mode": "OBJECT"}).status == "unmet"
    assert evaluate_step(tab, {"active_tool": "builtin.move"}).status == "unverifiable"   # mode not observed: not a failure
    assert evaluate_step(sl.steps[0], {"mode": "OBJECT"}).status == "unverifiable"        # a step with no checkable state


# ---------------------------------------------------------------- router policy
def test_router_cannot_reach_a_model():
    code = ("import ingestion.router, ingestion.catalog, ingestion.text_steps, ingestion.transcript_ingest, sys;"
            "bad=[m for m in sys.modules if m.split('.')[0] in ('google','httpx','requests','urllib3','openai')];print(bad)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env={"PYTHONPATH": str(ROOT)})
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_no_socket_is_needed(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    for case in CASES[:12]:
        run_case(case)


def test_fallback_is_explicit_never_silent():
    b = route("How do I bevel an edge?", version="2.80")
    assert b.route == "fallback_required" and b.api_calls == 0 and b.fallback_reason and b.steps is None
    assert "no model was called" in " ".join(b.reasons)


def test_clarification_instead_of_inventing():
    b = route("how do I do it")
    assert b.kind == "clarification" and b.steps is None and "Which Blender operation" in b.clarification


def test_documentation_does_not_count_as_observation():
    unknown = route("How do I join two mesh objects?", version="2.80")                 # no observed state
    assert unknown.clarification and unknown.assumptions
    observed_ok = route("How do I join two mesh objects?", version="2.80", observed={"mode": "OBJECT", "selected_objects": ["MESH", "MESH"]})
    assert not observed_ok.unmet_prerequisites and not observed_ok.clarification
    wrong_types = route("How do I join two mesh objects?", version="2.80", observed={"mode": "OBJECT", "selected_objects": ["MESH", "CAMERA"]})
    assert wrong_types.unmet_prerequisites                                             # mixed types: the manual says join needs one type
    in_edit = route("How do I join two mesh objects?", version="2.80", observed={"mode": "EDIT_MESH", "selected_objects": ["MESH", "MESH"]})
    assert in_edit.steps.steps[0].provenance == "catalog_context" and "First:" in in_edit.steps.steps[0].goal


def test_provenance_and_sources_on_every_catalog_step():
    b = route("How do I separate selected geometry into a new object?", version="2.80")
    assert b.sources and all(s.kind in ("manual", "tutorial_video") for s in b.sources)
    manual = [s for s in b.sources if s.kind == "manual"]
    assert manual and all(s.verified_on == "2026-10-11" and "CC-BY-SA" in s.licence for s in manual)
    for s in b.steps.steps:
        assert s.provenance == "catalog_template" and s.support == "unknown"           # never narrated/demonstrated
        assert any(r.startswith("catalog:mesh.separate@") for r in s.source_refs)
        assert s.review_status == "drafted_automatically"


def test_written_route_keeps_user_wording_and_adds_no_steps():
    b = route("Enter Edit Mode, select a vertex", version="2.80")
    assert [s.goal for s in b.steps.steps] == ["Enter Edit Mode", "Select a vertex"]
    assert all(s.provenance == "user_text" for s in b.steps.steps)


def test_conceptual_answer_is_not_forced_into_steps():
    b = route("What is Edit Mode?", version="2.80")
    assert b.steps is None and b.explanations and b.kind == "concept"


# ---------------------------------------------------------------- reviewed workflows
def reviewed_list():
    s = Step(id="s01", order=1, goal="Press Tab", review_status="reviewed")
    return StepList(source_type="written", app="blender", steps=[s])


def test_store_serves_only_reviewed_version_compatible_workflows(tmp_path):
    store = ReviewedWorkflowStore(tmp_path)
    key = op_key(["mode.enter_edit"])
    with pytest.raises(ValueError):
        store.save(key, reviewed_list(), reviewed_by=" ")
    drafted = reviewed_list()
    drafted.steps[0].review_status = "drafted_automatically"
    with pytest.raises(ValueError):
        store.save(key, drafted, reviewed_by="Ayesha")
    store.save(key, reviewed_list(), reviewed_by="Ayesha", min_version="2.80", max_version="4.2")
    assert store.find(key, "2.80") is not None
    assert store.find(key, "4.5") is None            # outside the reviewed range
    assert store.find(key, None) is None             # unknown version: do not claim it fits
    assert store.find(op_key(["object.join"]), "2.80") is None


def test_router_prefers_a_reviewed_workflow(tmp_path):
    store = ReviewedWorkflowStore(tmp_path)
    store.save(op_key(["mode.enter_edit"]), reviewed_list(), reviewed_by="Ayesha", min_version="2.80")
    b = route("How do I switch to Edit Mode?", version="2.80", store=store)
    assert b.route == "reviewed_workflow" and b.steps.steps[0].provenance == "reviewed_workflow"
    assert any(r.startswith("reviewed:") and "Ayesha" in r for r in b.steps.steps[0].source_refs)
    assert route("How do I switch to Edit Mode?", version="2.80", store=ReviewedWorkflowStore(tmp_path / "empty")).route == "catalog"


def test_store_starts_empty_and_example_fixtures_are_not_reviewed(tmp_path):
    # shared/examples are hand-written fixtures, not person-reviewed workflows: an empty store serves nothing
    assert ReviewedWorkflowStore(tmp_path / "none").find(op_key(["mode.enter_edit"]), "2.80") is None
    assert text_key("Press Tab!") == text_key("press   tab")


# ---------------------------------------------------------------- manually entered steps
def test_manual_steps_are_validated_and_normalised():
    data = json.loads((ROOT / "shared" / "examples" / "blender_cube_extrude.json").read_text(encoding="utf-8"))
    sl, notes = normalise_manual_steps(data, "2.80")
    assert sl.source_type == "manual" and sl.steps[0].provenance == "user_text"
    assert any("no checkable expected state" in n for n in notes)
    b = route(json.dumps(data), version="2.80")
    assert b.route == "manual_steps" and b.steps.source_type == "manual"


def test_manual_steps_reject_malformed_input_without_repair():
    with pytest.raises(ValidationError):
        normalise_manual_steps({"source_type": "written", "app": "blender", "steps": [{"id": "a", "order": 0, "goal": "x"}]})
    with pytest.raises(ValidationFailure):
        normalise_manual_steps({"source_type": "written", "app": "blender", "video_duration_s": 10,
                                "steps": [{"id": "a", "order": 1, "goal": "x", "video_start_s": 50}]})


# ---------------------------------------------------------------- CLI
def test_cli_ask_runs_without_any_key(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from ingestion.cli import main
    assert main(["ask", "How do I join two mesh objects?", "--version", "2.80", "--mode", "EDIT_MESH", "--selected", "MESH"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["route"] == "catalog" and out["api_calls"] == 0 and out["steps"]["steps"][0]["provenance"] == "catalog_context"
