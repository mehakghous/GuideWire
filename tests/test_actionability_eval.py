"""The rubric itself, and the measured before/after on the real Maya Part 9 response (R5). Numbers here are what the rubric returned on 2026-10-16; the rubric measures structure, not truth."""
from ingestion.eval.actionability import load_rubric, ordering_violations, score, score_step
from ingestion.validate import sanitize_and_annotate
from ingestion.profiles import get_profile
from shared.step_record import Action, HowTo, Step, StepList
from tests.test_instructions import after, before

RUBRIC = load_rubric("tests/fixtures/rubrics/maya_fkik_leg.json")


def test_a_bare_goal_scores_zero_and_a_full_step_scores_high():
    bare = score_step(Step(id="s1", order=1, goal="Orient the joints"))
    assert bare == {"actionability": 0, "ui_specificity": 0, "verification": 0, "grounding": 0, "timestamps": 0, "feature_tag": 0}
    full = score_step(Step(
        id="s1", order=1, goal="Orient the joints", feature_id="ORNT-02", evidence=["Skeleton > Orient Joint"], video_start_s=10, video_end_s=40,
        actions=[Action(verb="open_menu", ui_element="Skeleton > Orient Joint"), Action(verb="set_value", ui_element="Primary Axis", value="X")],
        how_to=[HowTo(text="Open Skeleton > Orient Joint.", support="shown", evidence="menu"), HowTo(text="Set Primary Axis to X.", support="shown", evidence="dialog")],
        check=[HowTo(text="The axes line up.", support="shown", evidence="viewport")]))
    assert full == {"actionability": 2, "ui_specificity": 2, "verification": 2, "grounding": 2, "timestamps": 2, "feature_tag": 2}


def test_a_claim_without_evidence_costs_grounding_and_catalog_checks_count_only_half():
    s = score_step(Step(id="s1", order=1, goal="g", evidence=["x"], how_to=[HowTo(text="Do it.", support="shown")], check=[HowTo(text="Looks right.", support="catalog")]))
    assert s["grounding"] == 1 and s["verification"] == 1


def test_ordering_flags_a_step_that_comes_before_a_prerequisite_the_list_also_teaches():
    st = lambda i, f: Step(id=f"s{i}", order=i, goal="g", feature_id=f)
    bad = StepList(source_type="written", app="maya", steps=[st(1, "SKIN-01"), st(2, "SKEL-01")])
    assert any("SKIN-01" in v and "SKEL-01" in v for v in ordering_violations(bad))
    assert ordering_violations(StepList(source_type="written", app="maya", steps=[st(1, "SKEL-01"), st(2, "SKIN-01")])) == []


def test_before_and_after_on_the_real_maya_response():
    b = before()
    sanitize_and_annotate(b, get_profile("maya"), 1151)
    rb, ra = score(b, RUBRIC), score(after(), RUBRIC)
    assert (rb.overall, ra.overall) == (43.8, 62.5)
    assert rb.per_criterion["actionability"] == 0 and ra.per_criterion["actionability"] == 50
    assert rb.per_criterion["verification"] == 0 and ra.per_criterion["verification"] == 50
    assert rb.per_criterion["ui_specificity"] == 0 and ra.per_criterion["ui_specificity"] == 50
    assert ra.per_criterion["timestamps"] == 0                                    # the composer cannot invent times: only a new model run can supply them
    assert rb.completeness == ra.completeness == 100.0                            # the topics were all there already; what was missing was the how
    assert len(ra.reference_found) == 1 and "select the root joint first" in ra.reference_missing     # the quality example's finer detail is NOT in the source evidence, and is not made up


def test_the_ordering_finding_on_the_real_run_is_reported_as_possible_not_certain():
    assert any("possible order issue" in v and "CNST-04" in v for v in score(after(), RUBRIC).violations)


def test_cli_score_and_instructions_work_on_a_saved_step_list(tmp_path, capsys):
    from ingestion import cli
    f = tmp_path / "steps.json"
    f.write_text(before().model_dump_json(), encoding="utf-8")
    assert cli.main(["score", str(f), "--rubric", "tests/fixtures/rubrics/maya_fkik_leg.json"]) == 0
    first = capsys.readouterr().out
    assert "actionability" in first and "overall" in first
    assert cli.main(["instructions", str(f)]) == 0 and "gained instructions" in capsys.readouterr().out
    assert cli.main(["score", str(f)]) == 0
    assert cli.main(["review", "show", str(f)]) == 0
    shown = capsys.readouterr().out
    assert "[shown] Open Skeleton > Orient Joint." in shown and "[catalog] Check that" in shown
