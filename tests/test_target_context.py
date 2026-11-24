"""Targets that depend on what came before (2026-11-23): a field named on its own after a Properties tab or panel belongs to it, a menu item written without its menu gets the header menu Blender has for it,
and a tab or panel header followed by its field is one thing to find. Found on the Blender leg IK video, where v12's short action words left most steps with nothing to point at."""
from __future__ import annotations

from app import step_state as ss
from ingestion import targets
from shared.grounding import Rect
from shared.step_record import Action, StatePredicate, Step
from vision import grounders as g
from vision.verify import gate

R = Rect(10, 20, 30, 40)


def step(i: int, actions: list[Action], start: str | None = None, end: str | None = None) -> Step:
    return Step(id=f"s{i:02d}", order=i, goal=f"step {i}", actions=actions,
                start_state=[StatePredicate(kind="mode", target=start)] if start else [], expected_state=[StatePredicate(kind="mode", target=end)] if end else [])


def A(verb, ui=None, keys=None, value=None):
    return Action(verb=verb, ui_element=ui, keys=keys or [], value=value)


def test_a_field_named_on_its_own_after_a_properties_panel_is_a_field_of_that_panel_and_one_need():
    s = step(1, [A("click", "Properties > Object Properties > Viewport Display"), A("set_value", "In Front")], start="EDIT_ARMATURE")
    (r,) = targets.resolve_steps([s])
    field = r.actions[1].target
    assert (field.kind, field.tab, field.panel, field.prop) == ("property", "OBJECT", "Viewport Display", "In Front")
    needs = ss.needs_of(r)
    assert [n.prop for n in needs] == ["In Front"]                  # the panel header and its field are one thing: the field target walks tab -> header -> field itself


def test_a_scene_thing_after_a_properties_tab_is_still_a_thing_in_the_3d_view():
    s = step(1, [A("click", "Properties > Bone Constraint Properties"), A("select", "Foot bone")], start="POSE")
    (r,) = targets.resolve_steps([s])
    assert r.actions[1].target.kind == "viewport"


def test_the_tab_a_step_opened_carries_to_the_step_right_after_it_and_no_further():
    s1 = step(1, [A("click", "Properties > Bone Constraint Properties > Add Bone Constraint")], start="POSE")
    s2 = step(2, [A("set_value", "Head/Tail")], start="POSE")
    s3 = step(3, [A("select", "Pose Mode")], start="POSE")
    s4 = step(4, [A("set_value", "Axes")], start="POSE")
    r1, r2, r3, r4 = targets.resolve_steps([s1, s2, s3, s4])
    assert (r2.actions[0].target.kind, r2.actions[0].target.tab) == ("property", "BONE_CONSTRAINT")
    assert r4.actions[0].target.kind == "viewport"


def test_a_menu_item_written_without_its_menu_gets_the_header_menu_blender_has_for_it():
    s = step(1, [A("press_keys", keys=["Shift", "A"]), A("select", "Armature > Single Bone")], start="OBJECT")
    (r,) = targets.resolve_steps([s])
    t = r.actions[1].target
    assert t.kind == "menu" and t.path[:2] == ["Add", "Armature"]    # Blender 5.2: Add > Armature adds the single bone


def test_a_path_that_already_starts_at_a_header_menu_is_left_alone():
    s = step(1, [A("open_menu", "Object > Parent > Armature Deform > With Automatic Weights")], start="OBJECT")
    (r,) = targets.resolve_steps([s])
    assert r.actions[0].target.path == ["Object", "Parent", "Armature Deform", "With Automatic Weights"]


def test_edit_mode_with_no_more_said_is_the_kind_of_editing_the_tutorial_has_been_doing():
    s1 = step(1, [A("select", "Pose Mode")], start="EDIT_ARMATURE", end="POSE")
    s2 = step(2, [A("select", "Edit Mode")], start="POSE")
    r1, r2 = targets.resolve_steps([s1, s2])
    assert r2.actions[0].target.mode == "EDIT_ARMATURE"


def _ground_by_label(**by_label):
    def ground(ref):
        return gate(by_label.get(ref.label, g.Grounded(ref.kind, g.NOT_FOUND, None, 0.0, ("not found",), f"Open: {ref.label}")))
    return ground


def test_a_later_part_of_the_step_that_is_already_on_screen_is_the_one_pointed_at():
    first = TargetRef_menu("Add")
    second = TargetRef_menu("Copy Location")
    s = Step(id="s01", order=1, goal="g", actions=[A("click", "x"), A("click", "y")])
    ok = g.Grounded("menu", g.VISIBLE, R, 0.95, ("word read", "in a popup", "alone"), "Click Copy Location.", complete=True, label="Copy Location")
    s = s.model_copy(update={"actions": [a.model_copy(update={"target": t}) for a, t in zip(s.actions, (first, second), strict=True)]})
    st = ss.assess(s, {"mode": "POSE"}, _ground_by_label(**{"Copy Location": ok}))
    assert st.target.label == "Copy Location" and st.show_rect


def TargetRef_menu(label):
    from shared.step_record import TargetRef
    return TargetRef(kind="menu", label=label, path=[label])


def test_notes_do_not_flip_between_look_for_and_find():
    import inspect

    from vision import grounders
    assert 'f"Look for ' not in inspect.getsource(grounders)
