"""What the learner is told for each kind of step (app/guidance.py), checked on the 18-step Blender armature tutorial, and how the bridge uses it with a fake service."""
from dataclasses import dataclass
from pathlib import Path

import pytest

from app import vision_bridge as vb
from app.guidance import describe, keys_of, plan_for
from shared.grounding import GroundingResult, Rect

DEMO = Path("demo/data/blender_armature_EBgHRd5tJfE.json")


def steps():
    from shared.step_record import StepList
    return {s.id: s for s in StepList.model_validate_json(DEMO.read_text(encoding="utf-8")).steps}


@pytest.fixture(scope="module")
def S():
    return steps()


def test_a_step_that_says_to_press_keys_gets_the_keys_in_order_and_a_place_to_point_at(S):
    p = plan_for(S["s01"])
    assert p.keys == ("A", "Delete") and p.region == "viewport" and not p.targets
    assert describe(p, None, step=S["s01"]) == "Press A then Delete with the mouse over the 3D viewport"
    assert plan_for(S["s04"]).keys == ("S",)


def test_the_mode_selector_is_a_mode_target_and_the_start_mode_is_kept_for_the_toolbar(S):
    p = plan_for(S["s03"])
    assert p.targets[0].kind == "mode" and p.mode_hint == "OBJECT"
    assert plan_for(S["s05"]).mode_hint == "EDIT_MESH"


def test_toolbar_tools_are_tool_targets_and_say_where_the_tool_is_and_its_key_when_it_cannot_be_seen(S):
    p = plan_for(S["s06"])
    assert p.targets[0].kind == "tool" and p.region == "toolbar"
    text = describe(p, None, step=S["s06"])
    assert "Loop Cut" in text and "Ctrl+R" in text and "scroll" in text
    s05 = plan_for(S["s05"])
    assert "Z Scale Handle" in describe(s05, s05.targets[0], matched="Scale", complete=True, step=S["s05"])


def test_a_panel_that_only_exists_after_an_action_points_at_the_bottom_left_of_the_viewport(S):
    p = plan_for(S["s07"])
    assert p.anchor == "bottom-left" and "bottom-left" in describe(p, None, step=S["s07"])


def test_the_properties_step_says_which_tab_to_open(S):
    p = plan_for(S["s10"])
    assert p.region == "properties" and p.anchor == "tabs"
    assert "Object Data" in describe(p, None, step=S["s10"]) and "In Front" in describe(p, None, step=S["s10"])


def test_blender_5_adds_a_single_bone_directly_so_add_armature_says_so(S):
    p = plan_for(S["s09"])
    text = describe(p, p.targets[0], matched="Armature", complete=True, step=S["s09"])
    assert "single bone" in text.lower()


def test_a_key_press_followed_by_a_menu_item_says_both(S):
    assert describe(plan_for(S["s16"]), None, step=S["s16"]).endswith("then choose Set Parent To > With Automatic Weights")


def test_things_in_the_3d_viewport_are_scene_items_not_text_to_find(S):
    p = plan_for(S["s12"])
    assert p.scene_items and not p.targets and p.region == "viewport"


def test_keys_are_only_read_from_press_phrases():
    class H:
        def __init__(self, text):
            self.text = text

    class St:
        how_to = [H("Press Ctrl+P to parent"), H("Then press Delete and press Tab"), H("Click Add")]
    assert keys_of(St()) == ("Ctrl+P", "Delete", "Tab")


# ---- the bridge with a fake service
@dataclass
class G:
    grounding: GroundingResult
    rect: Rect | None = None
    complete: bool = False
    ambiguous: bool = False
    matched: str = ""


class Svc:
    def __init__(self, texts=(), region=Rect(500, 300, 80, 80)):
        self.texts, self.region = set(texts), region
        self.asked = []

    takes_hints = True

    def ground(self, name, mode_hint=None, prefer_toolbar=False):
        self.asked.append((name, prefer_toolbar, mode_hint))
        if name in self.texts:
            return G(GroundingResult("ok", 10, 10), Rect(5, 5, 40, 12), True, matched=name.split(">")[-1].strip())
        return G(GroundingResult("none", reason="not on screen"))

    def region_rect(self, name, anchor="center"):
        return self.region

    def observe(self, properties=None, attributes=None):
        return {}


def test_nothing_to_find_points_at_the_region_with_a_pulsing_pointer_and_the_keys(S):
    look = vb.VisionBridge(lambda app: Svc(), window_finder=lambda a: (0, 0, 1000, 700)).look(S["s01"], "blender")
    assert look.pointer and look.rect == (500, 300, 80, 80) and look.keys == ("A", "Delete") and look.hint.startswith("Press A then Delete")


def test_the_mode_dropdown_is_found_by_the_mode_it_shows_and_the_item_once_it_is_open(S):
    bridge = vb.VisionBridge(lambda app: Svc(["Object Mode"]), window_finder=lambda a: (0, 0, 1000, 700))
    look = bridge.look(S["s03"], "blender")
    assert look.rect == (5, 5, 40, 12) and not look.complete and "mode dropdown" in look.hint
    opened = vb.VisionBridge(lambda app: Svc(["Edit Mode"]), window_finder=lambda a: (0, 0, 1000, 700)).look(S["s03"], "blender")
    assert opened.complete and opened.hint == "Click Edit Mode"


def test_a_tool_is_looked_up_in_the_toolbar_of_the_steps_own_mode(S):
    svc = Svc()
    vb.VisionBridge(lambda app: svc, window_finder=lambda a: (0, 0, 1000, 700)).look(S["s05"], "blender")
    assert ("Toolbar > Scale", True, "EDIT_MESH") in svc.asked


def test_the_mouse_and_keyboard_events_of_a_step_come_from_its_actions_in_order(S):
    from app.guidance import inputs_for
    assert inputs_for(S["s01"]) == (("keys", "A"), ("keys", "Delete"))
    assert inputs_for(S["s02"]) == (("click", "left"), ("click", "hover"), ("click", "left"))      # Add, hover Mesh (the submenu opens), Cylinder
    assert inputs_for(S["s05"]) == (("click", "left"), ("drag", "left"))
    assert inputs_for(S["s07"])[-1] == ("type", "10")
    assert inputs_for(S["s14"])[:2] == (("click", "right"), ("click", "left"))                    # the context menu is a right click
    assert ("keys", "Ctrl+P") in inputs_for(S["s16"])
    assert plan_for(S["s16"]).keys == ("Ctrl+P",)
