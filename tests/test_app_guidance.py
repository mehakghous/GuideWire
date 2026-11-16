"""What the learner's hands do in each kind of step (app/guidance.py: keys and the animated mouse and keyboard events), and what each step needs found on screen (app/step_state.needs_of), checked on the 18-step
Blender armature tutorial. What to POINT at is no longer decided here from words in the text: the resolver turns them into typed targets (tests/test_targets.py) and the grounders find them (tests/test_grounders.py)."""
import json
from pathlib import Path

import pytest

import app.guidance as guidance
from app.guidance import inputs_for, keys_of
from app.step_loader import load_steps
from app.step_state import needs_of
from ingestion import targets

DEMO = Path("demo/data/blender_armature_EBgHRd5tJfE.json")


@pytest.fixture(scope="module")
def S():
    sl = targets.resolve_steplist(load_steps(json.loads(DEMO.read_text(encoding="utf-8"))))[0]
    return {s.id: s for s in sl.steps}


def test_a_step_that_says_to_press_keys_gets_the_keys_in_order(S):
    assert keys_of(S["s01"]) == ("A", "Delete") and keys_of(S["s04"]) == ("S",) and keys_of(S["s16"]) == ("Ctrl+P",)


def test_keys_are_only_read_from_press_phrases():
    class H:
        def __init__(self, text):
            self.text = text

    class St:
        how_to = [H("Press Ctrl+P to parent"), H("Then press Delete and press Tab"), H("Click Add")]
    assert keys_of(St()) == ("Ctrl+P", "Delete", "Tab")


def test_the_mouse_and_keyboard_events_of_a_step_come_from_its_actions_in_order(S):
    assert inputs_for(S["s01"]) == (("keys", "A"), ("keys", "Delete"))
    assert inputs_for(S["s02"]) == (("click", "left"), ("click", "hover"), ("click", "left"))      # Add, hover Mesh (the submenu opens), Cylinder
    assert inputs_for(S["s05"]) == (("click", "left"), ("drag", "left"))
    assert inputs_for(S["s07"])[-1] == ("type", "10")
    assert inputs_for(S["s14"])[:2] == (("click", "right"), ("click", "left"))                    # the context menu is a right click
    assert ("keys", "Ctrl+P") in inputs_for(S["s16"])


def test_what_each_kind_of_step_needs_found_on_screen_comes_from_its_resolved_targets(S):
    kinds = {sid: [t.kind for t in needs_of(s)] for sid, s in S.items()}
    assert kinds["s01"] == [] and kinds["s04"] == []                                              # keys only: nothing to find
    assert kinds["s02"] == ["menu"]
    assert kinds["s03"] == ["mode"] and kinds["s08"] == ["mode"]
    assert kinds["s05"] == ["tool"] and kinds["s06"] == ["tool"] and kinds["s18"] == ["tool"]      # "Z Scale Handle" and the like are viewport things: words only
    assert kinds["s07"] == ["operator_panel"] and kinds["s14"] == ["context_menu", "operator_panel"]
    assert kinds["s10"] == ["property"]
    assert kinds["s16"] == ["operator_panel"]                                                     # Set Parent To > With Automatic Weights: a choice in the Ctrl+P popup


def test_an_action_the_resolver_could_not_resolve_is_looked_for_by_its_words_and_nothing_else_is():
    from shared.step_record import Action, Step
    step = Step(id="s01", order=1, goal="g", actions=[Action(verb="open_menu", ui_element="Pose Mode > Bone Constraint properties > Add Bone Constraint > Copy Location"), Action(verb="select", ui_element="Z Move Handle")])
    got = needs_of(step)
    assert [t.kind for t in got] == ["menu"] and got[0].path[-1] == "Copy Location"            # "Z Move Handle" is one word that is not a menu: something in the 3D view


def test_the_hand_written_lists_that_guessed_what_to_point_at_are_gone():
    for name in ("SCENE_WORDS", "REDO_PANELS", "TOOL_KEYS", "plan_for", "describe", "Plan"):
        assert not hasattr(guidance, name), name
