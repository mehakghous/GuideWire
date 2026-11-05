import json

from ingestion import cli
from ingestion.feature_report import feature_report
from shared.step_record import Step, StepList


def sl(app, *steps):
    return StepList(source_type="written", app=app, steps=[Step(id=f"s{i}", order=i, **kw) for i, kw in enumerate(steps, 1)])


def test_tagged_step_reports_its_feature_and_the_prerequisites_nothing_covers():
    r = feature_report(sl("maya", {"goal": "Bind the mesh", "feature_id": "SKIN-01"}))
    assert r.tagged == {"SKIN-01": ["s1"]}
    assert r.missing_prerequisites["SKIN-01"][:1] == ["PREP-01"]          # teaching order: the very first prerequisite comes first
    assert {"PREP-05", "SKEL-01", "ORNT-02"} <= set(r.missing_prerequisites["SKIN-01"])


def test_a_covered_prerequisite_is_not_reported_missing():
    steps = [{"goal": g, "feature_id": f} for g, f in [
        ("units", "PREP-01"), ("import", "PREP-02"), ("rest pose", "PREP-05"), ("joints", "SKEL-01"), ("place", "SKEL-02"),
        ("name", "SKEL-03"), ("orient", "ORNT-02"), ("hierarchy", "ORNT-01"), ("bind", "SKIN-01")]]
    r = feature_report(sl("blender", *steps))
    assert "SKIN-01" not in r.missing_prerequisites


def test_untagged_steps_are_guessed_and_kept_apart_or_left_unmatched():
    r = feature_report(sl("maya", {"goal": "Create an IK handle on the leg"}, {"goal": "Subscribe to my channel"}))
    assert r.suggested == {"IKFK-02": ["s1"]} and r.tagged == {} and r.unmatched == ["s2"]


def test_unknown_craft_and_unsupported_are_called_out():
    r = feature_report(sl("blender", {"goal": "x", "feature_id": "ZZZZ-99"}, {"goal": "review arcs", "feature_id": "CLNP-04"},
                          {"goal": "retarget", "feature_id": "LAYR-06"}))
    assert r.unknown == ["ZZZZ-99"] and r.craft == ["CLNP-04"] and r.unsupported == ["LAYR-06"]
    text = r.render()
    assert "UNKNOWN feature id ZZZZ-99" in text and "not graded" in text and "no tool in blender" in text


def test_cli_accepts_a_step_list_or_an_answer_bundle(tmp_path, capsys):
    steps = sl("houdini", {"goal": "Add a skeleton", "feature_id": "SKEL-01"})
    plain, bundle = tmp_path / "a.json", tmp_path / "b.json"
    plain.write_text(steps.model_dump_json(), encoding="utf-8")
    bundle.write_text(json.dumps({"kind": "procedure", "steps": json.loads(steps.model_dump_json())}), encoding="utf-8")
    for f in (plain, bundle):
        assert cli.main(["features", str(f)]) == 0
        assert "teaches SKEL-01" in capsys.readouterr().out
    assert cli.main(["features", str(tmp_path / "missing.json")]) == 2          # one-line error, not a traceback
