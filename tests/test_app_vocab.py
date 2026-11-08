"""The application profiles are checked against the names the REAL installs report (knowledge/app_vocab/*.json, written by scripts/dump_app_vocab.py
from Blender 5.2.2, Maya 2027 and Houdini 22.0.466). Offline: the JSON is committed, no application is started.
If a profile name is not in the install, a tutorial step would be told to use a name the application does not have."""
import json
from pathlib import Path

import pytest

from ingestion.extract import NODE_EXAMPLES, build_system_prompt, default_prompt_version
from ingestion.profiles import PROFILES, get_profile, norm

DIR = Path(__file__).parent.parent / "knowledge" / "app_vocab"


def vocab(app):
    p = DIR / f"{app}.json"
    if not p.exists():
        pytest.skip(f"{p.name} not generated (python scripts/dump_app_vocab.py {app})")
    return json.loads(p.read_text(encoding="utf-8"))


def test_blender_profile_matches_the_install():
    v = vocab("blender")
    assert PROFILES["blender"].nodes <= set(v["node_types"])                      # object, bone, constraint and modifier identifiers
    assert PROFILES["blender"].modes <= set(v["context_modes"])                   # what bpy.context.mode returns
    assert PROFILES["blender"].workspaces == set(v["workspaces"])
    assert {"CONSTRAINT_IK", "MODIFIER_ARMATURE", "ARMATURE", "BONE"} <= PROFILES["blender"].nodes


def test_maya_profile_nodes_exist_in_the_install():
    v = vocab("maya")
    missing = PROFILES["maya"].nodes - set(v["node_types"])
    assert missing <= {"HIKCharacterNode"}, missing        # HumanIK's node exists once the mayaHIK plug-in is loaded (checked by hand 2026-10-22: loadPlugin('mayaHIK'))


def test_houdini_profile_nodes_are_labels_the_install_shows():
    v = vocab("houdini")
    labels = {norm(d) for entries in v["node_types_by_category"].values() for _, d in entries}
    assert not [n for n in PROFILES["houdini"].nodes if norm(n) not in labels]
    assert PROFILES["houdini"].workspaces <= set(v["desktops"])
    # the labels the recalled list had wrong must not come back
    for wrong in ("Animation from Skeleton", "Configure Controls", "FBX Character Output", "GLTF Character Output", "Motion Clips", "Ragdoll"):
        assert wrong not in PROFILES["houdini"].nodes


def test_real_names_widen_the_validator_vocabulary():
    assert get_profile("blender").has_ui_name("Armature")                         # a menu/dropdown name from the install
    assert get_profile("blender").has_ui_name("Weight Paint")
    assert get_profile("houdini").has_ui_name("Rig Doctor") and get_profile("houdini").has_ui_name("Joint Capture Biharmonic")


def test_v7_gives_each_application_its_own_node_examples_and_older_prompts_are_unchanged():
    for app, must, mustnt in (("houdini", "Rig Doctor, Joint Deform", "ikHandle"), ("blender", "CONSTRAINT_COPY_ROTATION", "skinCluster"), ("maya", "skinCluster", "CONSTRAINT_COPY_ROTATION")):
        p7 = build_system_prompt(get_profile(app), "v7")
        assert must in p7 and mustnt not in p7.split("expected_state: when a step creates")[1].split("add\n")[0]
        assert "node_exists:" in p7                                               # every application now has a node vocabulary line
    p6 = build_system_prompt(get_profile("houdini"), "v6")
    assert "for example joint, ikHandle, skinCluster" in p6                       # v6 stays as recorded
    assert "node_exists:" not in build_system_prompt(get_profile("blender"), "v6")


def test_default_prompt_follows_the_application():
    assert default_prompt_version("maya") == default_prompt_version("houdini") == "v7"
    assert default_prompt_version("blender") == "v2" and default_prompt_version("blender", rigging=True) == "v7"
    assert set(NODE_EXAMPLES) == set(PROFILES)
