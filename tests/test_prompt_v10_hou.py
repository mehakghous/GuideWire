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


def test_houpreds_is_v10_plus_the_state_kinds_plus_the_houdini_rule_and_changes_nothing_else():
    from ingestion.extract import _schema
    for app in ("maya", "blender"):                                                                         # no Houdini rule outside Houdini: the same text as v10-preds
        assert build_system_prompt(get_profile(app), "v10-houpreds") == build_system_prompt(get_profile(app), "v10-preds")
    v10, hou, preds, both = (build_system_prompt(get_profile("houdini"), v) for v in ("v10", "v10-hou", "v10-preds", "v10-houpreds"))
    assert both.startswith(v10) and "HOUDINI NODE NETWORK" in both and "EXPECTED STATE FOR MORE STEPS" in both
    assert both == v10 + preds[len(v10):] + hou[len(v10):]                                                  # exactly the two added blocks, in a fixed order
    assert "name_exists" not in hou and "HOUDINI NODE NETWORK" not in preds                                  # the two older variants are untouched
    assert len(_schema("v10-houpreds")["$defs"]["DraftPredicateExt"]["properties"]["kind"]["enum"]) == 10 and len(_schema("v10-hou")["$defs"]["DraftPredicate"]["properties"]["kind"]["enum"]) == 7
