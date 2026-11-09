"""The validator accepts a node name the model wrote without its spaces or with other spacing and case, and still drops one it cannot match.
The cases come from the first live v7 Houdini run (RigPose, BoneDeform, Bone Capture Biharmonic written as the instructor said them)."""
import pytest

from ingestion.profiles import get_profile
from ingestion.validate import _canonical_target
from shared.step_record import StatePredicate


def canon(app, name, kind="node_exists"):
    return _canonical_target(StatePredicate(kind=kind, target=name), get_profile(app))


@pytest.mark.parametrize("written,label", [("RigPose", "Rig Pose"), ("BoneDeform", "Bone Deform"), ("rig doctor", "Rig Doctor"),
                                           ("Skeleton Mirror", "Skeleton Mirror"), ("BoneCaptureBiharmonic", "Bone Capture Biharmonic")])
def test_houdini_labels_written_without_their_spaces_are_restored(written, label):
    assert canon("houdini", written) == label


def test_maya_camel_case_types_match_a_spaced_or_cased_spelling():
    assert canon("maya", "IK Handle") == "ikHandle"
    assert canon("maya", "skin cluster") == "skinCluster"
    assert canon("maya", "ikHandle") == "ikHandle"


def test_a_name_that_matches_nothing_is_still_dropped():
    assert canon("houdini", "Magic Rig Node") is None
    assert canon("maya", "ik") is None                    # not a prefix match: only the same letters and digits count
    assert canon("houdini", "   ") is None


def test_two_candidates_with_the_same_letters_are_not_guessed(monkeypatch):
    from dataclasses import replace
    prof = replace(get_profile("houdini"), nodes=frozenset({"Rig Pose", "RigPose"}))
    assert _canonical_target(StatePredicate(kind="node_exists", target="Rig-Pose"), prof) is None            # exact spelling would win; a third spelling matches both, so it is not guessed

