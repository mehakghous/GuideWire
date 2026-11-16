"""Resolving a step's words into typed targets against the Blender interface catalog (knowledge/app_vocab/blender_ui.json, dumped from Blender 5.2.2).

The expectations below are facts of that catalog, checked in a real Blender when it was dumped (see tests/test_ui_catalog.py), not guesses.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.step_loader import load_steps
from ingestion import targets
from shared.step_record import Action, Step, StepList

DEMO = Path(__file__).resolve().parents[1] / "demo" / "data"


@pytest.fixture(scope="module")
def cat():
    c = targets.load_catalog()
    assert c is not None, "knowledge/app_vocab/blender_ui.json is missing: run scripts/dump_ui_catalog.py"
    return c


def act(ui=None, verb="click", keys=(), mode=None, cat=None, ctx=None):
    return targets.resolve_action(Action(verb=verb, ui_element=ui, keys=list(keys)), mode, cat, ctx)


def test_a_toolbar_tool_is_found_in_the_toolbar_of_the_steps_own_mode(cat):
    t = act("Toolbar > Loop Cut", mode="EDIT_MESH", cat=cat)
    assert (t.kind, t.id, t.mode, t.confidence) == ("tool", "builtin.loop_cut", "EDIT_MESH", 1.0)
    assert act("Toolbar > Rotate", mode="POSE", cat=cat).mode == "POSE"


def test_a_tool_that_does_not_exist_in_the_steps_mode_is_found_elsewhere_with_less_confidence_never_silently(cat):
    t = act("Toolbar > Loop Cut", mode="OBJECT", cat=cat)                 # Object Mode has no Loop Cut: the learner is in the wrong mode, or the step is
    assert t.id == "builtin.loop_cut" and t.mode == "EDIT_MESH" and t.confidence == 0.6
    assert act("Toolbar > Teleport", mode="OBJECT", cat=cat) is None      # nothing like it: unresolved, not invented


def test_the_mode_selector_resolves_to_the_general_mode_not_the_last_one_with_that_name(cat):
    assert act("Mode selector > Edit Mode", cat=cat).id == "EDIT"         # "Edit Mode" is also the name of EDIT_GPENCIL: the general one wins
    assert act("Mode selector > Pose Mode", cat=cat).id == "POSE"


def test_a_property_path_names_its_tab_and_panel_from_the_catalog(cat):
    t = act("Properties > Data > Viewport Display > In Front", cat=cat)
    assert (t.kind, t.tab, t.panel, t.prop, t.confidence) == ("property", "DATA", "Viewport Display", "In Front", 1.0) and "DATA_PT_display" in t.candidates
    colon = act("Properties:Object > Viewport Display > In Front", cat=cat)   # the tab after a colon, as another tutorial wrote it
    assert colon.tab == "OBJECT"
    odd = act("Properties > Data > Teleport Settings > Speed", cat=cat)
    assert odd.tab == "DATA" and odd.confidence == 0.5                    # the tab is known, the panel is not: half sure, and it says so


def test_an_operators_redo_panel_resolves_its_property_even_through_a_macro_operator(cat):
    sub = act("Subdivide > Number of Cuts", verb="set_value", mode="EDIT_ARMATURE", cat=cat)
    assert (sub.kind, sub.operator, sub.prop) == ("operator_panel", "armature.subdivide", "number_cuts")        # "Subdivide" exists for mesh, armature, curve...: the mode picks one
    loop = act("Loop Cut and Slide > Number of Cuts", verb="set_value", mode="EDIT_MESH", cat=cat)
    assert (loop.operator, loop.prop) == ("mesh.loopcut_slide", "number_cuts")                                  # the property lives on mesh.loopcut, one of the macro's parts


def test_a_choice_in_a_popup_is_looked_up_in_the_operator_the_key_press_started(cat):
    keys = act(keys=["Ctrl", "P"], verb="press_keys", mode="OBJECT", cat=cat)
    assert keys.operator == "object.parent_set"
    choice = act("Set Parent To > With Automatic Weights", mode="OBJECT", cat=cat, ctx=keys.operator)           # the popup's title is not an operator name Blender lists
    assert (choice.kind, choice.operator, choice.prop, choice.id) == ("operator_panel", "object.parent_set", "type", "ARMATURE_AUTO")
    assert act("Set Parent To > With Automatic Weights", mode="OBJECT", cat=cat) is None                        # without that context it stays unresolved


def test_keys_resolve_to_what_they_do_in_the_steps_mode_and_a_key_sequence_is_less_certain(cat):
    assert act(keys=["Tab"], verb="press_keys", mode="OBJECT", cat=cat).operator == "object.mode_set"
    assert act(keys=["S"], verb="press_keys", mode="EDIT_MESH", cat=cat).operator == "transform.resize"
    seq = act(keys=["R", "9", "0", "Return"], verb="press_keys", mode="OBJECT", cat=cat)
    assert seq.operator == "transform.rotate" and seq.confidence == 0.7     # R starts it; the rest is typed numbers
    unknown = act(keys=["A"], verb="press_keys", cat=cat)                   # no mode known: A means different things in several modes
    assert unknown.operator is None and len(unknown.candidates) > 1 and unknown.confidence == 0.5


def test_a_menu_path_keeps_its_words_and_the_confidence_drops_for_names_blender_does_not_list(cat):
    t = act("Add > Mesh > Cylinder", verb="open_menu", cat=cat)
    assert (t.kind, t.path) == ("menu", ["Add", "Mesh", "Cylinder"]) and t.confidence == 1.0
    assert act("Add > Mesh > Hoverboard", verb="open_menu", cat=cat).confidence < 1.0


def test_things_in_the_viewport_stay_viewport_items_and_unknown_words_stay_unresolved(cat):
    assert act("Z Scale Handle", verb="drag", cat=cat).kind == "viewport"
    assert act("Bone", verb="select", cat=cat) is None                      # also a Properties tab name: ambiguous, so not guessed
    assert act(None, cat=cat) is None and act("Toolbar", cat=cat) is None   # a container with nothing after it


def test_the_demo_tutorial_resolves_most_actions_and_every_resolved_target_is_in_the_catalog(cat):
    sl = load_steps(json.loads((DEMO / "blender_armature_EBgHRd5tJfE.json").read_text(encoding="utf-8")))
    out, report = targets.resolve_steplist(sl, cat)
    assert report.with_text == 30 and report.resolved >= 29
    by_step = {s.id: [a.target for a in s.actions if a.target] for s in out.steps}
    assert by_step["s06"][0].id == "builtin.loop_cut" and by_step["s06"][0].mode == "EDIT_MESH"
    assert by_step["s03"][0].id == "EDIT" and by_step["s03"][0].mode == "EDIT_MESH"      # the step's own check says which edit mode
    assert by_step["s11"][0].mode == "EDIT_ARMATURE"
    for t in (t for ts in by_step.values() for t in ts):
        if t.kind == "tool":
            assert t.id in cat.tool_ids
        if t.operator:
            assert t.operator in cat.ops
        if t.kind == "mode":
            assert t.id in cat.modes.values()


def test_the_mode_a_step_starts_in_is_carried_from_the_steps_before_it(cat):
    st = lambda i, start, exp, a: Step(id=i, order=int(i[1:]), goal="g", actions=[a], start_state=start, expected_state=exp)       # noqa: E731
    from shared.step_record import StatePredicate as P
    steps = [st("s01", [P(kind="mode", target="OBJECT")], [P(kind="mode", target="EDIT_MESH")], Action(verb="press_keys", keys=["Tab"])),
             st("s02", [], [], Action(verb="press_keys", keys=["Ctrl", "R"]))]           # no start_state: it is in Edit Mode because step 1 put it there
    out = targets.resolve_steps(steps, cat)
    assert out[1].actions[0].target.operator == "mesh.loopcut_slide" and out[1].actions[0].target.confidence == 1.0


def test_resolution_never_changes_the_steps_words_and_old_data_still_loads(cat):
    d = json.loads((DEMO / "blender_armature_EBgHRd5tJfE.json").read_text(encoding="utf-8"))
    sl = load_steps(d)
    out, _ = targets.resolve_steplist(sl, cat)
    for a, b in zip(sl.steps, out.steps, strict=True):
        assert [x.ui_element for x in a.actions] == [x.ui_element for x in b.actions] and a.goal == b.goal and a.expected_state == b.expected_state
    assert StepList.model_validate(json.loads(out.model_dump_json())).steps[5].actions[0].target.id == "builtin.loop_cut"   # survives a save and a load
    assert all(a.target is None for s in sl.steps for a in s.actions)                    # the loader itself is unchanged
    other = sl.model_copy(update={"app": "maya"})
    assert targets.resolve_steplist(other, cat)[0] is other                              # the catalog is Blender's: other applications untouched


def test_without_the_catalog_nothing_is_resolved_and_nothing_fails(monkeypatch):
    monkeypatch.setattr(targets, "load_catalog", lambda: None)
    s = Step(id="s01", order=1, goal="g", actions=[Action(verb="click", ui_element="Toolbar > Loop Cut")])
    assert targets.resolve_step(s) is s


def test_the_resolved_target_is_never_part_of_the_schema_a_model_is_asked_to_fill():
    """A model must not write `target` (it is resolved from the catalog), and adding it to the model-facing schema would also change every prompt and cache key (tests/test_experiment.py pins the schema)."""
    schema = json.dumps(Action.model_json_schema())
    assert "target" not in Action.model_json_schema()["properties"] and "TargetRef" not in schema
    assert Action.model_validate({"verb": "click", "target": {"kind": "tool", "label": "Loop Cut", "id": "builtin.loop_cut"}}).target.id == "builtin.loop_cut"      # but it loads and saves
