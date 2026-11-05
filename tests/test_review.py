import pytest

from ingestion import cli
from ingestion.rigging_text import rigging_to_steplist
from ingestion.router import route
from ingestion.service import Service
from ingestion.workflows import ReviewedWorkflowStore, edit_steps, entries, promote, text_key

TEXT = "Create joints down the arm\nCreate an IK handle on the leg\nBind skin to the skeleton"


@pytest.fixture
def draft():
    return rigging_to_steplist(TEXT, "maya")[0]


# ---------------------------------------------------------------- edit_steps (unit)
def test_edit_changes_goal_removes_and_moves_without_touching_the_input(draft):
    new = edit_steps(draft, goals={1: "Create 5 joints down the left arm"}, remove={3})
    assert [s.goal for s in new.steps] == ["Create 5 joints down the left arm", "Create an IK handle on the leg"]
    assert [s.order for s in new.steps] == [1, 2] and len(draft.steps) == 3 and draft.steps[0].goal == "Create joints down the arm"
    moved = edit_steps(draft, moves=[(3, 1)])
    assert [s.id for s in moved.steps] == ["s03", "s01", "s02"] and [s.order for s in moved.steps] == [1, 2, 3]       # ids stay, order is renumbered


@pytest.mark.parametrize("kw,needle", [({"remove": {9}}, "no step 9"), ({"goals": {1: "  "}}, "empty"), ({"remove": {1, 2, 3}}, "no steps"),
                                       ({"moves": [(1, 7)]}, "cannot move")])
def test_bad_edits_are_refused_with_a_reason(draft, kw, needle):
    with pytest.raises(ValueError, match=needle):
        edit_steps(draft, **kw)


def test_a_step_cannot_be_moved_before_what_it_depends_on(draft):
    draft.steps[1].depends_on = ["s01"]
    with pytest.raises(ValueError, match="depends on"):
        edit_steps(draft, moves=[(2, 1)])
    assert edit_steps(draft, remove={1}).steps[0].depends_on == []                 # removing the dependency drops the link


# ---------------------------------------------------------------- promote and the store (unit + router integration)
def test_promote_needs_a_name_marks_steps_reviewed_and_is_then_served(tmp_path, draft):
    store = ReviewedWorkflowStore(tmp_path)
    with pytest.raises(ValueError, match="name"):
        promote(store, text_key(TEXT), draft, reviewed_by=" ")
    assert not any(tmp_path.iterdir()) and all(s.review_status == "drafted_automatically" for s in draft.steps)          # nothing stored, input unchanged
    promote(store, text_key(TEXT), draft, reviewed_by="Ayesha", min_version="2024")
    [row] = entries(store)
    assert row["reviewed_by"] == "Ayesha" and row["steps"] == 3 and row["app"] == "maya"
    hit = route(TEXT, app="maya", version="2025", store=store)
    assert hit.route == "reviewed_workflow" and all(s.review_status == "reviewed" and s.provenance == "reviewed_workflow" for s in hit.steps.steps)
    assert route(TEXT, app="maya", version="2022", store=store).route == "rigging_text"          # older than the reviewer declared: not claimed
    assert route(TEXT, app="maya", store=store).route == "rigging_text"                         # version unknown: not claimed


# ---------------------------------------------------------------- CLI end to end
def test_cli_review_flow_from_ask_to_a_served_workflow(tmp_path, capsys):
    store, f = str(tmp_path / "rev"), tmp_path / "draft.json"
    cli.main(["ask", "--app", "maya", "--no-kb", TEXT.replace("\n", "\n")])
    f.write_text(capsys.readouterr().out, encoding="utf-8")                                      # what `ask ... > draft.json` does
    assert cli.main(["review", "show", str(f)]) == 0 and "[drafted_automatically] Create joints down the arm" in capsys.readouterr().out
    assert cli.main(["review", "edit", str(f), "--set-goal", "1=Create 5 joints down the arm", "--remove", "3"]) == 0
    capsys.readouterr()
    assert cli.main(["review", "--store", store, "promote", str(f), "--by", "Ayesha", "--request", TEXT, "--min-version", "2024"]) == 0
    assert "promoted 2 steps" in capsys.readouterr().out
    assert cli.main(["review", "--store", store, "list"]) == 0 and "by Ayesha" in capsys.readouterr().out
    b = route(TEXT, app="maya", version="2025", store=ReviewedWorkflowStore(store))
    assert b.route == "reviewed_workflow" and [s.goal for s in b.steps.steps][0] == "Create 5 joints down the arm"


def test_cli_review_errors_are_one_line_with_exit_2(tmp_path, capsys):
    f = tmp_path / "d.json"
    f.write_text(rigging_to_steplist(TEXT, "maya")[0].model_dump_json(), encoding="utf-8")
    for argv in (["review", "edit", str(f), "--remove", "9"], ["review", "edit", str(f), "--move", "1-2"],
                 ["review", "--store", str(tmp_path / "s"), "promote", str(f), "--by", "A"], ["review", "show", str(tmp_path / "missing.json")]):
        assert cli.main(argv) == 2
        err = capsys.readouterr().err
        assert err.startswith("error:") and "Traceback" not in err
    assert not (tmp_path / "s").exists()                                                       # a refused promotion creates nothing


# ---------------------------------------------------------------- the chat service uses the store
def test_chat_service_serves_a_promoted_workflow(tmp_path, monkeypatch):
    import ingestion.service as svc
    store = ReviewedWorkflowStore(tmp_path)
    promote(store, text_key(TEXT), rigging_to_steplist(TEXT, "maya")[0], reviewed_by="Ayesha", min_version="2024")
    monkeypatch.setattr(svc, "DEFAULT_STORE", tmp_path)
    steps = tmp_path / "steps.txt"
    steps.write_text(TEXT, encoding="utf-8")
    s = Service.open(version="2025", use_kb=True)
    assert s.store is not None
    s.message("/app maya")
    s.message(f'/load steps "{steps}"')
    assert all(x.review_status == "reviewed" and x.provenance == "reviewed_workflow" for x in s.session.steps.steps)


def test_application_versions_other_than_blenders_parse():
    from ingestion.catalog import parse_version
    assert parse_version("4.2") == (4, 2) and parse_version("2025") == (2025, 0) and parse_version("20.5.410") == (20, 5) and parse_version("latest") is None
