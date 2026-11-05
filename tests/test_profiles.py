from ingestion.evaluator import evaluate_step
from ingestion.extract import build_system_prompt
from ingestion.profiles import BLENDER, HOUDINI, MAYA, get_profile
from ingestion.validate import sanitize_and_annotate
from shared.step_record import Step, StepList, StatePredicate as P


def test_all_three_apps_have_profiles():
    assert [get_profile(a).name for a in ("blender", "maya", "houdini")] == ["blender", "maya", "houdini"]


def test_node_exists_is_judged_from_observed_nodes_and_unobservable_without_them():
    step = Step(id="s1", order=1, goal="Add a Rig Doctor", expected_state=[P(kind="node_exists", target="Rig Doctor")])
    assert evaluate_step(step, {"nodes": ["Skeleton", "Rig Doctor"]}).status == "met"
    assert evaluate_step(step, {"nodes": ["Skeleton"]}).status == "unmet"
    assert evaluate_step(step, {"mode": "SELECT"}).status == "unverifiable"          # no node list reported: not assumed either way


def test_node_names_are_checked_against_the_app_profile():
    sl = StepList(source_type="written", app="houdini", steps=[
        Step(id="s1", order=1, goal="Add nodes", expected_state=[P(kind="node_exists", target="rig doctor"), P(kind="node_exists", target="Flux Capacitor")])])
    step = sanitize_and_annotate(sl, HOUDINI).steps[0]
    assert [p.target for p in step.expected_state] == ["Rig Doctor"]                  # canonical spelling; the unknown node is dropped and flagged
    assert any("Flux Capacitor" in f for f in step.flags)


def test_blender_prompt_is_unchanged_and_other_apps_list_their_nodes():
    assert "node_exists" not in build_system_prompt(BLENDER, "v2")                    # frozen baseline prompt stays byte-for-byte as it was
    assert "node_exists" in build_system_prompt(MAYA, "v2") and "ikHandle" in build_system_prompt(MAYA, "v2")


def test_v4_prompt_lists_only_features_the_app_can_do_and_leaves_older_versions_alone():
    from ingestion.extract import PROMPT_VERSIONS
    assert "v4" in PROMPT_VERSIONS
    maya, blender = build_system_prompt(MAYA, "v4"), build_system_prompt(get_profile("blender"), "v4")
    assert "SKEL-01" in maya and "feature_id" in maya and "LAYR-06: Retarget" in maya        # Maya has HumanIK retargeting
    assert "LAYR-06: Retarget" not in blender                                                 # Blender has none (U): not offered
    assert "feature_id" not in build_system_prompt(MAYA, "v3")


def test_feature_id_from_the_model_reaches_the_step_list():
    from ingestion.extract import extract_from_text
    from ingestion.providers.fake import ScriptedProvider
    step = {"goal": "Create a joint chain", "confidence": 0.9, "support": "narrated", "evidence": ["make joints"], "feature_id": "SKEL-01"}
    sl = extract_from_text(ScriptedProvider([{"steps": [step]}]), "make joints", app="maya")
    assert sl.app == "maya" and sl.steps[0].feature_id == "SKEL-01"
