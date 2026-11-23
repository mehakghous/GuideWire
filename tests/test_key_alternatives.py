"""The other way to do what a step does with the keyboard (reported 2026-11-22: a step that says "Shift+A" should also show the Add menu). The routes come from Blender's own menus
(knowledge/app_vocab/blender_menus.json, written by `scripts/dump_ui_catalog.py --menus`); nothing is guessed, and a key with no menu equivalent says nothing."""
from __future__ import annotations

import pytest

from app import key_alternatives as ka
from app import step_state as ss
from ingestion import targets
from shared import menu_routes as mr
from shared.step_record import Action, StatePredicate, Step
from vision import grounders as g
from vision.verify import gate


# ---- the routes
@pytest.mark.skipif(not mr.available(), reason="knowledge/app_vocab/blender_menus.json is missing: run scripts/dump_ui_catalog.py --menus")
class TestRoutesFromBlender:
    def test_shift_a_is_the_add_menu_in_object_mode_and_in_edit_mesh(self):
        assert mr.alternative_for_keys(["Shift", "A"], "wm.call_menu", "OBJECT") == ("OBJECT", ("Add",))
        assert mr.alternative_for_keys(["Shift", "A"], "wm.call_menu", "EDIT_MESH") == ("EDIT_MESH", ("Add",))      # the header says "Add"; the menu class is called "Mesh"

    def test_the_route_follows_the_mode(self):
        assert mr.routes_for("object.parent_clear", "OBJECT")[0] == ("Object", "Parent", "Clear Parent")
        assert mr.routes_for("armature.parent_clear", "EDIT_ARMATURE")[0][:2] == ("Armature", "Parent")
        assert mr.routes_for("armature.extrude_move", "OBJECT") == []                                              # an Edit Mode operator has no route in Object Mode, and gets none

    def test_pose_mode_ik(self):
        assert mr.routes_for("pose.ik_add", "POSE")[0] == ("Pose", "Inverse Kinematics", "Add IK to Bone")

    def test_no_route_is_made_up(self):
        assert mr.alternative_for_keys(["Return"], "screen.region_toggle", "OBJECT") is None
        assert mr.alternative_for_keys(["Shift", "A"], "wm.call_menu", "SCULPT") is None                           # a mode whose header menus were not dumped
        assert mr.alternative_for_keys(["Shift", "A"], None) is None

    def test_without_a_mode_the_first_mode_that_has_a_route_is_used(self):
        assert mr.alternative_for_keys(["Alt", "P"], "armature.parent_clear")[0] == "EDIT_ARMATURE"


def test_build_routes_flattens_inline_menus_uses_the_header_text_and_survives_a_cycle():
    raw = {"menus": {"A_MT_add": {"label": "Mesh", "items": [{"menu": "A_MT_sub", "text": "Armature"}, {"inline": "A_MT_inl"}]},
                     "A_MT_sub": {"label": "Armature", "items": [{"op": "object.armature_add", "text": "Single Bone"}, {"menu": "A_MT_add", "text": "Loop"}]},
                     "A_MT_inl": {"label": "x", "items": [{"op": "object.text_add", "text": "Text"}]}},
           "headers": {"OBJECT": [{"id": "A_MT_add", "text": "Add"}]}}
    out = mr.build_routes(raw)["modes"]["OBJECT"]
    assert out["ops"]["object.armature_add"] == [["Add", "Armature", "Single Bone"]]
    assert out["ops"]["object.text_add"] == [["Add", "Text"]]                  # the inline menu sits at the level of the menu that includes it
    assert out["menus"]["A_MT_add"] == ["Add"] and out["menus"]["A_MT_sub"] == ["Add", "Armature"]


def test_build_routes_keeps_the_shortest_few():
    items = [{"menu": f"M{i}", "text": f"S{i}"} for i in range(5)]
    menus = {"R": {"label": "R", "items": items}, **{f"M{i}": {"label": f"S{i}", "items": [{"op": "x.y", "text": "Do"}]} for i in range(5)}}
    assert len(mr.build_routes({"menus": menus, "headers": {"OBJECT": [{"id": "R", "text": "R"}]}})["modes"]["OBJECT"]["ops"]["x.y"]) == mr.MAX_ROUTES


# ---- steps
def _step(*actions, start=None, expect=None):
    s = Step(id="s01", order=1, goal="g", actions=list(actions), start_state=[StatePredicate(kind="mode", target=start)] if start else [],
             expected_state=[StatePredicate(kind="mode", target=expect)] if expect else [])
    return targets.resolve_steps([s])[0]


KEYS = lambda *k: Action(verb="press_keys", keys=list(k))      # noqa: E731


def test_shift_a_shows_the_add_menu():
    alts = ka.alternatives_of(_step(KEYS("Shift", "A"), start="OBJECT"))
    assert [(a.keys, a.route, a.text) for a in alts] == [("Shift+A", ("Add",), "use the Add menu in the 3D view header")]
    assert alts[0].target.kind == "menu" and alts[0].target.path == ["Add"]            # the guide can look for it on screen like any other menu


def test_tab_shows_the_mode_dropdown_and_nothing_once_the_learner_is_in_that_mode():
    s = _step(KEYS("Tab"), start="OBJECT", expect="EDIT_ARMATURE")
    alt = ka.alternatives_of(s, "OBJECT")[0]
    assert alt.route == ("Mode selector", "Edit Mode") and alt.text == "choose Edit Mode in the mode dropdown at the top left of the 3D view" and alt.target.kind == "mode"
    assert ka.alternatives_of(s, "EDIT_ARMATURE") == []


def test_a_key_without_a_menu_equivalent_says_nothing():
    assert ka.alternatives_of(_step(KEYS("Return"), start="OBJECT")) == []
    assert ka.alternatives_of(_step(Action(verb="click", ui_element="Add > Armature > Single Bone"))) == []      # no key, nothing to translate


def test_the_mode_carries_over_from_the_steps_before():
    raw_a = Step(id="s01", order=1, goal="g", actions=[KEYS("Tab")], start_state=[StatePredicate(kind="mode", target="OBJECT")], expected_state=[StatePredicate(kind="mode", target="EDIT_ARMATURE")])
    raw_b = Step(id="s02", order=2, goal="g", actions=[KEYS("Alt", "P")])           # does not say where it starts
    a, b = targets.resolve_steps([raw_a, raw_b])                                     # resolved together, as a session does: the mode carries over, so Alt+P is the armature operator
    assert ka.mode_for([a, b], 1) == "EDIT_ARMATURE"
    assert ka.alternatives_of(b, ka.mode_for([a, b], 1))[0].route[0] == "Armature"
    assert ka.alternatives_of(b, "OBJECT") == []                        # the key was resolved to the armature operator, which has no route in Object Mode: nothing is said rather than another mode's route


def test_the_hint_names_two_and_points_to_the_details_for_the_rest():
    alts = ka.alternatives_of(_step(KEYS("G"), KEYS("R"), KEYS("S"), start="EDIT_ARMATURE"))
    assert len(alts) == 3
    text = ka.sentence(alts)
    assert "for G" in text and "for R" in text and "for S" not in text and "the others are in the step details" in text
    assert ka.sentence([]) == "" and ka.sentence(alts[:1]).startswith("Without the keyboard: use ")


# ---- in the guide
def _ground_found(label="Add"):
    def ground(ref):
        return gate(g.Grounded(ref.kind, g.VISIBLE, (10, 20, 30, 40) and __import__("shared.grounding", fromlist=["Rect"]).Rect(10, 20, 30, 40), 0.95, ("a header", "the word was read"), f"Click {label}.", label=label, complete=True))
    return ground


def _not_found(ref):
    return gate(g.Grounded(ref.kind, g.NOT_FOUND, None, 0.0, ("not found",), f"Open: {ref.label}"))


def test_a_keys_only_step_points_at_the_other_way_when_the_screen_shows_it():
    step = _step(KEYS("Shift", "A"), start="OBJECT")
    st = ss.assess(step, {"mode": "OBJECT", "node_counts": {}, "nodes": []}, _ground_found("Add"))
    assert st.phase == "acting" and st.show_rect and st.target.path == ["Add"]
    assert "Press Shift+A" in st.hint and "Without the keyboard: use the Add menu in the 3D view header." in st.hint and st.alternative


def test_when_the_other_way_is_not_found_the_words_still_say_it_and_nothing_is_drawn():
    step = _step(KEYS("Shift", "A"), start="OBJECT")
    st = ss.assess(step, {"mode": "OBJECT", "node_counts": {}, "nodes": []}, _not_found)
    assert not st.show_rect and "use the Add menu in the 3D view header" in st.hint


def test_two_keys_two_other_ways_are_words_only_no_guess_about_which_to_point_at():
    step = _step(KEYS("G"), KEYS("R"), start="EDIT_ARMATURE")
    st = ss.assess(step, {"mode": "EDIT_ARMATURE"}, _ground_found("Armature"))
    assert not st.show_rect and "for G" in st.hint


def test_a_step_that_already_points_at_a_menu_also_names_the_key_that_opens_it():
    step = _step(KEYS("Shift", "A"), Action(verb="open_menu", ui_element="Add > Armature > Single Bone"), start="OBJECT")
    empty = {"mode": "OBJECT", "node_counts": {}, "nodes": []}
    st = ss.assess(step, empty, _not_found, empty)
    assert st.target.kind == "menu" and "Or press Shift+A with the mouse over the 3D view." in st.hint


def test_nothing_is_added_to_a_step_without_keys():
    step = _step(Action(verb="open_menu", ui_element="Add > Armature > Single Bone"), start="OBJECT")
    st = ss.assess(step, {"mode": "OBJECT", "node_counts": {}, "nodes": []}, _not_found)
    assert st.alternative == "" and "Without the keyboard" not in st.hint and "Or press" not in st.hint


# ---- on the session screen
def test_the_step_details_list_every_other_way():
    pytest.importorskip("PyQt6")
    from app.ui.screens import SessionScreen
    text = SessionScreen._detail_for(_step(KEYS("Shift", "A"), KEYS("Tab"), start="OBJECT", expect="EDIT_ARMATURE"), False, "OBJECT")
    assert "Without the keyboard\n• Shift+A: use the Add menu in the 3D view header\n• Tab: choose Edit Mode in the mode dropdown" in text
    assert "Without the keyboard" not in SessionScreen._detail_for(_step(Action(verb="click", ui_element="In Front")))
