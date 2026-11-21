"""What a tutorial assumes you already have (app/prerequisites.py): the leg mesh of the leg-rigging tutorial, and no false alarm for the tutorials that build their own model."""
import json
from pathlib import Path

import pytest

from app.demo_content import DATA, manifest
from app.prerequisites import CUBE_TEXT, Prereq, check, prerequisites
from app.step_loader import load_steps
from shared.step_record import Action, Step


def demo(file_part: str):
    m = next(x for x in manifest() if file_part in x["file"])
    return m["title"], load_steps(json.loads((DATA / m["file"]).read_text(encoding="utf-8")))


def step(order, goal, ui=None, assumptions=(), expected=()):
    return Step(id=f"s{order:02d}", order=order, goal=goal, actions=[Action(verb="click", ui_element=ui)] if ui else [], assumptions=list(assumptions), expected_state=list(expected))


def without_cube(items):
    """The prerequisites other than the default-cube offer (which every Blender tutorial that ignores the cube gets)."""
    return [p for p in items if p.text != CUBE_TEXT]


def test_the_leg_tutorial_says_it_starts_with_a_leg_mesh():
    title, sl = demo("blender_leg_ik")
    items = without_cube(prerequisites(sl.steps, sl.app, title))
    assert len(items) == 1 and items[0].text.startswith("A leg mesh already in the scene") and "never makes it" in items[0].text
    assert items[0].needs == ("MESH",)


@pytest.mark.parametrize("name", ["blender_armature", "houdini_apex_fk", "houdini_apex_ik", "maya_leg_ik", "maya_quick_rig"])
def test_tutorials_that_make_their_own_model_or_never_use_one_get_no_warning(name):
    title, sl = demo(name)
    assert without_cube(prerequisites(sl.steps, sl.app, title)) == []


def test_a_blender_tutorial_that_ignores_the_default_cube_offers_to_remove_it_first():
    title, sl = demo("blender_leg_ik")
    items = prerequisites(sl.steps, sl.app, title)
    assert items and items[0].text == CUBE_TEXT and "default cube" in CUBE_TEXT and "Delete" in CUBE_TEXT
    assert items[0].status({"nodes": ["MESH"]}) == "unknown"                                  # never blocks, never a false alarm: the scene's cube cannot be told from other meshes


def test_a_tutorial_whose_own_first_step_deletes_the_default_scene_is_not_told_to_do_it_again():
    title, sl = demo("blender_armature")                                                       # its step 1 is "Delete default scene objects"
    assert prerequisites(sl.steps, sl.app, title) == []


def test_the_cube_is_not_offered_when_the_tutorial_uses_it_or_starts_from_an_empty_scene_or_is_not_blender():
    assert prerequisites([step(1, "Extrude the cube upwards")], "blender") == []
    assert prerequisites([step(1, "Select the top face", "Add > Mesh > Cube")], "blender") == []
    assert prerequisites([step(1, "Delete everything in the scene"), step(2, "Add a single bone armature")], "blender") == []
    assert prerequisites([step(1, "Start a new file"), step(2, "Add a single bone armature")], "blender") == []
    assert prerequisites([step(1, "Create a joint")], "maya") == [] and prerequisites([step(1, "Create a joint")], "houdini") == []
    assert prerequisites([], "blender") == []                                                  # nothing to say about an empty tutorial
    assert [p.text for p in prerequisites([step(1, "Add a single bone armature")], "blender")] == [CUBE_TEXT]


def test_the_cube_offer_comes_first_and_does_not_hide_the_missing_mesh_warning():
    steps = [step(1, "Add a single bone armature"), step(2, "Bind the mesh to the armature")]
    texts = [p.text for p in prerequisites(steps, "blender")]
    assert texts[0] == CUBE_TEXT and texts[1].startswith("A mesh") and len(texts) == 2


def test_a_mesh_that_a_step_adds_is_not_a_prerequisite():
    steps = [step(1, "Add a cube", "Add > Mesh > Cube"), step(2, "Bind mesh to armature with automatic weights")]
    assert prerequisites(steps, "blender") == []


def test_a_mesh_that_is_only_used_is_one_and_the_title_names_it():
    steps = [step(1, "Add a single bone armature"), step(2, "Bind the mesh to the armature")]
    assert without_cube(prerequisites(steps, "blender", "How to Rig a Hand with IK in Blender"))[0].text.startswith("A hand mesh")
    assert without_cube(prerequisites(steps, "blender"))[0].text.startswith("A mesh (the model you want to rig)")
    assert prerequisites(steps, "houdini")[0].text.startswith("A geometry")           # Houdini calls it geometry


def test_what_a_step_says_it_assumes_is_kept_but_the_knowledge_bases_before_this_lines_are_not():
    steps = [step(1, "Do a thing", assumptions=["Before this: An armature exists.", "The scene unit is metres"])]
    assert [p.text for p in without_cube(prerequisites(steps, "blender"))] == ["The scene unit is metres."]


def test_a_check_only_blames_what_the_application_showed_missing():
    p = Prereq("A leg mesh already in the scene.", ("MESH",))
    assert p.status({"nodes": ["ARMATURE"]}) == "unmet" and p.status({"nodes": ["MESH", "ARMATURE"]}) == "met"
    assert p.status({}) == "unknown" and p.status(None) == "unknown" and p.status({"nodes": []}) == "unknown"      # no list: silence, not a warning
    assert Prereq("Anything").status({"nodes": ["ARMATURE"]}) == "unknown"                                          # nothing it could check
    assert check([p, Prereq("Anything")], {"nodes": ["ARMATURE"]}) == [p] and check([p], {}) == []
