"""State-aware checks: the operator_ran predicate, results that were already true when the step began, implied progress from resolved targets, preconditions."""
from __future__ import annotations

import json
from pathlib import Path

from app.step_loader import load_steps
from ingestion import targets
from ingestion.evaluator import evaluate_step, implied_state, progress
from shared.step_record import Action, StatePredicate, Step, TargetRef

P = StatePredicate
DEMO = Path(__file__).resolve().parents[1] / "demo" / "data" / "blender_armature_EBgHRd5tJfE.json"


def step(**kw):
    base = dict(id="s01", order=1, goal="g", confidence=1.0)
    base.update(kw)
    return Step(**base)


def test_operator_ran_is_judged_from_the_operator_history_and_only_with_the_add_on():
    s = step(expected_state=[P(kind="operator_ran", target="mesh.loopcut_slide")], verifiable=True)
    seen = {"probe": True, "history": [{"id": "mesh.loopcut_slide", "name": "Loop Cut and Slide"}]}
    assert evaluate_step(s, seen).status == "met"
    assert evaluate_step(s, {"probe": True, "history": [{"id": "transform.translate"}]}).status == "unmet"
    assert evaluate_step(s, {"probe": True}).status == "unverifiable"                         # no history key: not readable, not "false"
    assert evaluate_step(s, {"history": seen["history"]}).status == "unverifiable"            # no add-on: the screen cannot see it


def test_a_result_that_was_already_true_when_the_step_began_is_not_evidence():
    """Step 9 of the armature tutorial lists node_exists ARMATURE as BOTH its start and its result: it counted as done the moment it began."""
    s = step(start_state=[P(kind="node_exists", target="ARMATURE")], expected_state=[P(kind="node_exists", target="ARMATURE")], verifiable=True)
    now = {"nodes": ["ARMATURE"], "node_counts": {"ARMATURE": 1}}
    assert evaluate_step(s, now).status == "unverifiable"                                       # no entry state: it cannot be told
    assert evaluate_step(s, now, entry={"node_counts": {"ARMATURE": 1}}).status == "unmet"          # seen: nothing was added since the step began
    assert evaluate_step(s, {"nodes": ["ARMATURE"], "node_counts": {"ARMATURE": 2}}, entry={"node_counts": {"ARMATURE": 1}}).status == "met"   # one more: the action happened
    plain = step(expected_state=[P(kind="node_exists", target="ARMATURE")], verifiable=True)    # not true at the start: unchanged behaviour
    assert evaluate_step(plain, now).status == "met"


def test_a_mode_that_is_both_start_and_result_does_not_block_completion():
    s = step(start_state=[P(kind="mode", target="OBJECT")], expected_state=[P(kind="mode", target="OBJECT"), P(kind="selection_type", target="MESH")], verifiable=True)
    assert evaluate_step(s, {"mode": "OBJECT", "selection_types": ["MESH"]}).status == "met"


def _target(**kw):
    return TargetRef(**kw)


def test_implied_state_comes_only_from_exact_targets_and_never_from_menus_or_viewport_items():
    s = step(actions=[
        Action(verb="click", ui_element="Toolbar > Loop Cut", target=_target(kind="tool", label="Loop Cut", id="builtin.loop_cut", mode="EDIT_MESH")),
        Action(verb="press_keys", keys=["Ctrl", "P"], target=_target(kind="keys", label="Ctrl+P", operator="object.parent_set")),
        Action(verb="open_menu", ui_element="Add > Mesh > Cube", target=_target(kind="menu", label="Cube", path=["Add", "Mesh", "Cube"])),
        Action(verb="drag", ui_element="Z Scale Handle", target=_target(kind="viewport", label="Z Scale Handle")),
        Action(verb="press_keys", keys=["A"], target=_target(kind="keys", label="A", candidates=["mesh.select_all", "object.select_all"], confidence=0.5)),
    ])
    got = [(p.kind, p.target) for p in implied_state(s)]
    assert got == [("active_tool", "builtin.loop_cut"), ("operator_ran", "object.parent_set")]


def test_progress_tells_not_done_from_cannot_tell_and_never_completes_a_step():
    s = step(start_state=[P(kind="mode", target="EDIT_MESH")], actions=[
        Action(verb="click", ui_element="Toolbar > Loop Cut", target=_target(kind="tool", label="Loop Cut", id="builtin.loop_cut", mode="EDIT_MESH")),
        Action(verb="press_keys", keys=["Ctrl", "R"], target=_target(kind="keys", label="Ctrl+R", operator="mesh.loopcut_slide"))])
    wrong_mode = progress(s, {"mode": "OBJECT", "active_tool": "builtin.select_box"})
    assert not wrong_mode.ready and [p.target for p in wrong_mode.preconditions_unmet] == ["EDIT_MESH"]
    assert [p.target for p in wrong_mode.pending] == ["builtin.loop_cut"] and [p.target for p in wrong_mode.unobservable] == ["mesh.loopcut_slide"]
    in_progress = progress(s, {"mode": "EDIT_MESH", "active_tool": "builtin.loop_cut", "probe": True, "history": []})
    assert in_progress.ready and [p.target for p in in_progress.done] == ["builtin.loop_cut"] and [p.target for p in in_progress.pending] == ["mesh.loopcut_slide"]
    nothing = progress(s, {})
    assert nothing.ready and len(nothing.preconditions_unobservable) == 1 and len(nothing.unobservable) == 2    # unknown is not "wrong"
    assert evaluate_step(s, {"mode": "EDIT_MESH", "active_tool": "builtin.loop_cut"}).status == "unverifiable"     # implied progress is not an expected state: the step is not completed by it


def test_on_the_demo_tutorial_the_loop_cut_step_is_ready_only_in_edit_mesh_and_done_when_the_tool_is_active():
    sl = load_steps(json.loads(DEMO.read_text(encoding="utf-8")))
    s6 = targets.resolve_steplist(sl)[0].steps[5]
    assert s6.id == "s06"
    assert not progress(s6, {"mode": "OBJECT"}).ready
    p = progress(s6, {"mode": "EDIT_MESH", "active_tool": "builtin.select_box"})
    assert p.ready and [x.target for x in p.pending] == ["builtin.loop_cut"]
    assert evaluate_step(s6, {"mode": "EDIT_MESH", "active_tool": "builtin.loop_cut"}).status == "met"       # the step's own expected_state, unchanged
