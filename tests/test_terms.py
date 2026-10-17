import pytest

from ingestion.features import load_catalog
from ingestion.terms import CONCEPTS, suggest_feature, term


def test_each_concept_has_a_word_for_every_app():
    assert all(set(v) == {"blender", "maya", "houdini"} for v in CONCEPTS.values())
    assert term("joint", "blender") == "bone" and term("joint", "maya") == "joint"


@pytest.mark.parametrize("text,app,expected", [
    ("Create an IK handle on the leg", "maya", "IKFK-02"),
    ("Bind skin to the skeleton", "maya", "SKIN-01"),
    ("Set a keyframe on the wrist control", "blender", "ANIM-01"),
    ("Create joints", "maya", "SKEL-01"),
])
def test_clear_wording_finds_its_feature(text, app, expected):
    assert suggest_feature(text, app) == expected


@pytest.mark.parametrize("text", ["Click the thing", "Subscribe to my channel", "and then we continue", ""])
def test_vague_or_unrelated_wording_gets_no_suggestion(text):
    assert suggest_feature(text, "blender") is None


def test_suggestions_are_real_catalog_ids_and_never_a_feature_the_app_lacks():
    cat = load_catalog()
    for text in ("Retarget the animation to the new character", "Create a joint chain", "Bake the animation"):
        fid = suggest_feature(text, "blender")
        assert fid is None or (fid in cat and cat.get(fid).support_code("blender") != "U")
    with pytest.raises(ValueError):
        suggest_feature("x", "unity")
