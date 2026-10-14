import pytest

from ingestion.evaluator import evaluate_step
from ingestion.profiles import BLENDER
from ingestion.validate import ValidationFailure, check_structure, sanitize_and_annotate
from shared.step_record import Action, StatePredicate as P, Step, StepList


def sl(*steps):
    return StepList(source_type="written", app="blender", steps=list(steps))


def step(i=1, **kw):
    return Step(id=f"s{i:02d}", order=i, goal=kw.pop("goal", "g"), **kw)


def test_sanitize_canonicalises_and_drops_unknown():
    s = step(expected_state=[P(kind="mode", target="edit mesh"), P(kind="mode", target="WIBBLE"),
                             P(kind="active_tool", target="BUILTIN.MOVE")], confidence=1.0)
    out = sanitize_and_annotate(sl(s), BLENDER).steps[0]
    assert [p.target for p in out.expected_state] == ["EDIT_MESH", "builtin.move"]
    assert out.verifiable and out.confidence < 1.0
    assert any("WIBBLE" in f for f in out.flags)


def test_all_predicates_dropped_makes_unverifiable():
    s = step(expected_state=[P(kind="workspace", target="Nonexistent")])
    out = sanitize_and_annotate(sl(s), BLENDER).steps[0]
    assert out.verifiable is False


def test_ui_name_check():
    ok = step(actions=[Action(verb="open_menu", ui_element="Add > Mesh > Cube")], confidence=1.0,
              support="demonstrated", evidence=["seen on screen"], visual_evidence="Add menu open")
    bad = step(2, actions=[Action(verb="click", ui_element="Magic Wand Deluxe")], confidence=1.0)
    out = sanitize_and_annotate(sl(ok, bad), BLENDER)
    assert out.steps[0].flags == [] and out.steps[0].confidence == 0.9  # capped by support, not 1.0
    assert out.steps[1].confidence < 1.0 and "Magic Wand Deluxe" in out.steps[1].flags[0]


def test_ui_name_tolerates_small_typos_and_case():
    s = step(actions=[Action(verb="click", ui_element="extrude regoin")], confidence=1.0)
    assert sanitize_and_annotate(sl(s), BLENDER).steps[0].flags == []


def test_structure_errors():
    with pytest.raises(ValidationFailure):
        check_structure(sl())
    with pytest.raises(ValidationFailure):
        check_structure(sl(step(1), step(3)))
    with pytest.raises(ValidationFailure):
        check_structure(sl(step(1, video_start_s=500)), video_duration_s=100)
    with pytest.raises(ValidationFailure):
        check_structure(sl(step(1, video_start_s=50), step(2, video_start_s=10)))
    check_structure(sl(step(1, video_start_s=10), step(2, video_start_s=50)), video_duration_s=100)


OBS = {"mode": "EDIT_MESH", "active_tool": "builtin.move", "selection_types": ["MESH"],
       "properties": {"x": 2.0}}


def test_evaluator_statuses():
    met = step(expected_state=[P(kind="mode", target="EDIT_MESH"), P(kind="selection_type", target="MESH")])
    assert evaluate_step(met, OBS).status == "met"
    unmet = step(expected_state=[P(kind="mode", target="OBJECT")])
    v = evaluate_step(unmet, OBS)
    assert v.status == "unmet" and v.unmet[0].target == "OBJECT"
    assert evaluate_step(step(), OBS).status == "unverifiable"


def test_evaluator_missing_observation_is_not_failure():
    s = step(expected_state=[P(kind="workspace", target="Shading")])
    v = evaluate_step(s, OBS)  # workspace not observed
    assert v.status == "unverifiable" and len(v.unobservable) == 1
    mixed = step(expected_state=[P(kind="workspace", target="Shading"), P(kind="mode", target="EDIT_MESH")])
    v2 = evaluate_step(mixed, OBS)
    assert v2.status == "met" and len(v2.unobservable) == 1


def test_evaluator_unmet_beats_missing():
    s = step(expected_state=[P(kind="workspace", target="Shading"), P(kind="mode", target="OBJECT")])
    assert evaluate_step(s, OBS).status == "unmet"


def test_evaluator_property_and_none_selection():
    s = step(expected_state=[P(kind="property_equals", target="x", value=2.00001)])
    assert evaluate_step(s, OBS).status == "met"
    s2 = step(expected_state=[P(kind="selection_type", target="NONE")])
    assert evaluate_step(s2, {"selection_types": []}).status == "met"
    assert evaluate_step(s2, OBS).status == "unmet"


def test_feature_id_must_be_in_the_catalog_and_gaps_in_the_app_are_flagged():
    from ingestion.profiles import BLENDER
    from ingestion.validate import find_errors, sanitize_and_annotate
    ok = StepList(source_type="written", app="blender", steps=[Step(id="s1", order=1, goal="Create a joint chain", feature_id="SKEL-01")])
    assert find_errors(ok) == []
    bad = StepList(source_type="written", app="blender", steps=[Step(id="s1", order=1, goal="x", feature_id="ZZZZ-99")])
    assert [i.code for i in find_errors(bad)] == ["UNKNOWN_FEATURE"]
    lost = StepList(source_type="written", app="blender", steps=[Step(id="s1", order=1, goal="Retarget the walk", feature_id="LAYR-06")])
    step = sanitize_and_annotate(lost, BLENDER).steps[0]
    assert any("LAYR-06" in f and "no tool" in f for f in step.flags) and step.confidence < 0.5
    with pytest.raises(ValueError):
        Step(id="s1", order=1, goal="x", feature_id="skel-1")        # wrong shape is refused by the schema itself


def test_a_step_teaching_a_craft_feature_is_craft_and_never_verifiable():
    from ingestion.profiles import BLENDER
    from ingestion.validate import sanitize_and_annotate
    sl = StepList(source_type="written", app="blender", steps=[
        Step(id="s1", order=1, goal="Review the arcs", feature_id="CLNP-04", expected_state=[P(kind="mode", target="POSE")])])
    step = sanitize_and_annotate(sl, BLENDER).steps[0]
    assert step.kind == "craft" and not step.verifiable and any("not graded" in f for f in step.flags)
    assert evaluate_step(step, {"mode": "POSE"}).status == "unverifiable"
