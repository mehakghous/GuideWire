"""Prompts v8 (atomic steps) and v9 (v8 plus coverage) are opt-in; v7 stays exactly as the earlier live runs saw it and stays the default for Maya and Houdini."""
import pytest

from ingestion.extract import PROMPT_VERSIONS, build_system_prompt, default_prompt_version, video_prompt
from ingestion.profiles import get_profile

APPS = ("blender", "maya", "houdini")


def test_the_video_default_is_the_measured_choice_and_written_text_keeps_the_older_default():
    from ingestion.extract import recommended_video_prompt_version as rec
    assert rec("houdini") == "v10-hou" and rec("maya") == "v10-preds" and rec("blender", rigging=True) == "v10-preds"
    assert rec("blender") == "v2"                                                                  # measured on rigging videos only: a plain Blender video keeps the modelling baseline
    assert default_prompt_version("maya") == default_prompt_version("houdini") == "v7"                # text extraction is not video: unchanged
    assert all(rec(a, r) in PROMPT_VERSIONS for a in ("blender", "maya", "houdini") for r in (False, True))


def test_the_cli_uses_the_recommended_prompt_for_a_video_and_the_old_default_for_written_text(capsys, tmp_path):
    import json

    from ingestion.cli import main
    url = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    for app, want in (("houdini", "v10-hou"), ("maya", "v10-preds")):
        assert main(["video", url, "--app", app, "--duration", "100", "--dry-run", "--no-metadata"]) == 0
        assert json.loads(capsys.readouterr().out)["prompt_version"] == want
    assert main(["video", url, "--app", "houdini", "--duration", "100", "--dry-run", "--no-metadata", "--prompt-version", "v7"]) == 0      # an explicit choice still wins
    assert json.loads(capsys.readouterr().out)["prompt_version"] == "v7"


def test_versions_and_defaults_are_unchanged():
    assert PROMPT_VERSIONS[-8:] == ("v8", "v9", "v10", "v10-nokb", "v10-outline", "v10-preds", "v10-hou", "v10-houpreds")
    assert default_prompt_version("maya") == default_prompt_version("houdini") == "v7"
    assert default_prompt_version("blender") == "v2" and default_prompt_version("blender", rigging=True) == "v7"


@pytest.mark.parametrize("app", APPS)
def test_v7_has_neither_new_block_v8_has_atomic_only_v9_has_both(app):
    p7, p8, p9 = (build_system_prompt(get_profile(app), v) for v in ("v7", "v8", "v9"))
    assert "ATOMIC STEPS" not in p7 and "COVERAGE." not in p7
    assert "ATOMIC STEPS" in p8 and "COVERAGE." not in p8
    assert "ATOMIC STEPS" in p9 and "COVERAGE." in p9
    assert p8.startswith(p7) and p9.startswith(p8)            # the new blocks are appended, so they win over the earlier grouping rules


@pytest.mark.parametrize("app", APPS)
def test_v8_and_v9_keep_the_per_application_node_examples_of_v7(app):
    assert get_profile(app).name in build_system_prompt(get_profile(app), "v9")
    assert build_system_prompt(get_profile(app), "v8").count("node_exists") == build_system_prompt(get_profile(app), "v7").count("node_exists")


def test_the_video_request_is_the_same_for_v7_v8_and_v9():
    assert video_prompt("v8", 300.0, None) == video_prompt("v7", 300.0, None) == video_prompt("v9", 300.0, None)


@pytest.mark.parametrize("app", APPS)
def test_v10_is_v9_plus_the_only_operations_rule(app):
    p9, p10 = build_system_prompt(get_profile(app), "v9"), build_system_prompt(get_profile(app), "v10")
    assert p10.startswith(p9) and "ONLY OPERATIONS" in p10 and "ONLY OPERATIONS" not in p9


@pytest.mark.parametrize("app", APPS)
def test_the_knowledge_block_variants_of_v10(app):
    base, none, outline = (build_system_prompt(get_profile(app), v) for v in ("v10", "v10-nokb", "v10-outline"))
    assert "Menu locations and option names reported" in base and "Menu locations and option names reported" not in none
    assert len(none) < len(base) < len(outline)
    assert "Typical order of operations" in outline and "Typical order of operations" not in base and "ONLY OPERATIONS" in outline
    assert "write ONLY what the video shows" in outline
    assert video_prompt("v10-nokb", 100.0) == video_prompt("v10", 100.0) == video_prompt("v10-outline", 100.0)


def test_unknown_knowledge_block_variants_are_refused():
    for bad in ("v9-nokb", "v10-everything", "v7-outline"):
        with pytest.raises(ValueError):
            build_system_prompt(get_profile("maya"), bad)
