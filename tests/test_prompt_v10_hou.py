"""Prompt v10-hou: v10 plus a Houdini node-network rule, for Houdini only. The other applications get exactly the v10 text."""
from ingestion.extract import PROMPT_VERSIONS, build_system_prompt
from ingestion.profiles import get_profile


def test_hou_is_listed_and_adds_one_block_for_houdini_only():
    assert "v10-hou" in PROMPT_VERSIONS
    v10, hou = build_system_prompt(get_profile("houdini"), "v10"), build_system_prompt(get_profile("houdini"), "v10-hou")
    assert hou.startswith(v10) and hou != v10
    for must in ("HOUDINI NODE NETWORK", "each connection between two nodes", "one step per parameter", "Do not fold several parameters"):
        assert must in hou and must not in v10


def test_other_applications_get_exactly_the_v10_text():
    for app in ("maya", "blender"):
        assert build_system_prompt(get_profile(app), "v10-hou") == build_system_prompt(get_profile(app), "v10")
