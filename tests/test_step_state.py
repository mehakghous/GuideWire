"""The step state machine: instruction displayed, target located, target visible AND verified, action performed, action verified are different facts. `ground` is a fake; no screen."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import step_state as ss
from app.step_loader import load_steps
from ingestion import targets
from shared.grounding import Rect
from shared.step_record import Action, StatePredicate, Step, TargetRef
from vision import grounders as g
from vision.verify import gate

DEMO = Path(__file__).resolve().parents[1] / "demo" / "data" / "blender_armature_EBgHRd5tJfE.json"
R = Rect(10, 20, 30, 40)


@pytest.fixture(scope="module")
def armature():
    sl = load_steps(json.loads(DEMO.read_text(encoding="utf-8")))
    return {s.id: s for s in targets.resolve_steplist(sl)[0].steps}


def fixed(**by_label):
    """A ground function: the Grounded for a target is looked up by its label; the gate is the real one."""
    asked = []

    def ground(ref):
        asked.append(ref.label)
        return gate(by_label.get(ref.label, g.Grounded(ref.kind, g.NOT_FOUND, None, 0.0, ("not found",), f"Open: {ref.label}")))
    ground.asked = asked
    return ground


def visible_tool(label="Loop Cut"):
    return g.Grounded("tool", g.VISIBLE, R, 0.95, ("gaps match", "scroll agrees", "cell detected"), f"Click {label} in the toolbar.", label=label)


def test_a_found_and_verified_target_is_the_visible_phase_with_a_rectangle(armature):
    st = ss.assess(armature["s06"], {"mode": "EDIT_MESH", "active_tool": "builtin.select_box"}, fixed(**{"Loop Cut": visible_tool()}))
    assert (st.phase, st.show_rect, st.grounded.rect) == ("visible", True, R) and st.status == "Found Loop Cut" and st.hint.startswith("Click Loop Cut")


def test_a_target_the_gate_rejected_is_not_shown_even_though_it_was_found(armature):
    weak = g.Grounded("tool", g.VISIBLE, R, 0.99, ("one signal",), "Click Loop Cut.", label="Loop Cut")
    st = ss.assess(armature["s06"], {"mode": "EDIT_MESH", "active_tool": "builtin.select_box"}, fixed(**{"Loop Cut": weak}))
    assert st.phase == "locating" and not st.show_rect and st.grounded.rect is None


def test_a_tool_scrolled_out_of_the_toolbar_is_the_hidden_phase_and_the_hint_says_how(armature):
    off = g.Grounded("tool", g.OFFSCREEN, Rect(2, 78, 56, 548), 0.95, ("x",), "Loop Cut is below the visible tools (4 cells away): scroll the toolbar down until you see it.", direction="down", label="Loop Cut")
    st = ss.assess(armature["s06"], {"mode": "EDIT_MESH", "active_tool": "builtin.select_box"}, fixed(**{"Loop Cut": off}))
    assert st.phase == "hidden" and st.show_rect and "scroll the toolbar down" in st.hint and st.status == "Cannot reach Loop Cut yet"


def test_the_wrong_mode_blocks_the_step_and_the_next_move_is_to_switch_mode(armature):
    seen = []

    def ground(ref):
        seen.append((ref.kind, ref.mode))
        return gate(g.Grounded("mode", g.VISIBLE, R, 0.95, ("dropdown found by the mode it shows",), "Click the mode dropdown (top left of the 3D view), then Edit Mode.", label=ref.label))
    st = ss.assess(armature["s06"], {"mode": "OBJECT"}, ground)                       # step 6 starts in Edit Mesh
    assert st.phase == "blocked" and "starts in Edit Mode" in st.status and "Switch to Edit Mode first" in st.hint
    assert seen == [("mode", "EDIT_MESH")] and st.show_rect                            # the corrective target is the mode dropdown, not Loop Cut


def test_an_unknown_mode_does_not_block_the_step(armature):
    st = ss.assess(armature["s06"], {}, fixed(**{"Loop Cut": visible_tool()}))        # nothing observed: not "wrong", just not known
    assert st.phase == "visible"


def test_a_target_whose_action_is_already_seen_done_is_skipped_for_the_next_one(armature):
    ground = fixed(**{"Rotate": visible_tool("Rotate")})
    s18 = armature["s18"]                                                              # select Bone, Toolbar > Rotate, drag the rotation gizmo
    st = ss.assess(s18, {"mode": "POSE", "active_tool": "builtin.rotate"}, ground)
    assert "Rotate" not in ground.asked                                                # the tool is already active: not pointed at again
    assert st.progress.done and [p.target for p in st.progress.done] == ["builtin.rotate"]


def test_when_everything_on_screen_is_done_the_rest_is_the_hands_and_the_phase_is_acting(armature):
    s01 = armature["s01"]                                                              # press A, then Delete: nothing to find on screen
    st = ss.assess(s01, {"mode": "OBJECT"}, fixed())
    assert st.phase == "acting" and st.keys == ("A", "Delete") and st.hint == "Press A then Delete with the mouse over the 3D view." and st.grounded is None


def test_a_menu_path_the_resolver_knew_nothing_about_is_still_looked_for_by_its_words():
    step = Step(id="s01", order=1, goal="g", actions=[Action(verb="open_menu", ui_element="Pose > Transform > Clear All")])
    ground = fixed(**{"Clear All": g.Grounded("menu", g.VISIBLE, R, 0.9, ("text read",), "Click Pose, then Transform > Clear All", matched="Pose", label="")})
    st = ss.assess(step, {}, ground)
    assert st.phase == "visible" and ground.asked == ["Clear All"] and st.target.path == ["Pose", "Transform", "Clear All"]


def test_an_ambiguous_target_is_the_locating_phase_with_no_rectangle():
    step = Step(id="s01", order=1, goal="g", actions=[Action(verb="open_menu", ui_element="Add > Mesh")])
    amb = g.Grounded("menu", g.AMBIGUOUS, None, 0.2, ("two matches",), "", ambiguous=True)
    st = ss.assess(step, {}, fixed(Mesh=amb))
    assert st.phase == "locating" and not st.show_rect and st.status.startswith("Several places match")


def test_the_shortcut_is_advised_only_when_the_target_is_out_of_reach_and_it_leaves_the_state_the_step_expects(armature):
    off = g.Grounded("tool", g.OFFSCREEN, Rect(2, 78, 56, 548), 0.95, ("x",), "scroll down", direction="down", label="Loop Cut")
    st = ss.assess(armature["s06"], {"mode": "EDIT_MESH", "active_tool": "builtin.select_box"}, fixed(**{"Loop Cut": off}))
    assert st.shortcut == "" and "Ctrl R" not in st.hint                               # step 6 expects the TOOL active: Ctrl+R would not make it so
    s = Step(id="s06", order=6, goal="Cut a loop", actions=[Action(verb="click", ui_element="Toolbar > Loop Cut", target=TargetRef(kind="tool", label="Loop Cut", id="builtin.loop_cut", mode="EDIT_MESH"))],
             start_state=[StatePredicate(kind="mode", target="EDIT_MESH")])         # same step, but nothing in it needs the tool to be the active one
    st = ss.assess(s, {"mode": "EDIT_MESH"}, fixed(**{"Loop Cut": off}))
    assert st.shortcut == "Ctrl R" and "Or press Ctrl R with the mouse over the 3D view." in st.hint
    visible = ss.assess(s, {"mode": "EDIT_MESH"}, fixed(**{"Loop Cut": visible_tool()}))
    assert visible.shortcut == ""                                                      # the control is on screen: highlight it


def test_the_five_facts_are_not_interchangeable(armature):
    """Located is not visible-and-verified, and neither is done: a step can have its target found and still be unmet."""
    s06 = armature["s06"]
    st = ss.assess(s06, {"mode": "EDIT_MESH", "active_tool": "builtin.select_box"}, fixed(**{"Loop Cut": visible_tool()}))
    assert st.phase == "visible" and st.progress.done == [] and st.progress.pending                 # found, nothing performed yet
    done = ss.assess(s06, {"mode": "EDIT_MESH", "active_tool": "builtin.loop_cut"}, fixed(**{"Loop Cut": visible_tool()}))
    assert done.phase == "acting" and [p.target for p in done.progress.done] == ["builtin.loop_cut"]     # performed; the step is still not "verified": that is SessionEngine.auto_check's call


def test_a_sidebar_step_is_a_target_the_session_can_guide_to():
    from app import step_state
    from shared.step_record import Action, Step, TargetRef
    ref = TargetRef(kind="sidebar", label="Roll", panel="Transform", prop="Roll")
    st = Step(id="s25", order=25, goal="Set bone Roll to 90", actions=[Action(verb="set_value", ui_element="Sidebar > Transform > Roll", target=ref)])
    assert step_state.needs_of(st) == [ref]
