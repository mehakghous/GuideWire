"""'Go back to X' when several steps match: jump to the most recent matching part before the learner's step instead of asking, and ask only when there is nothing earlier."""
from ingestion.followup import respond
from ingestion.session import Session
from shared.step_record import Step, StepList


def _session(current):
    goals = ["Create the hip joint", "Rename the hip joint", "Rename the knee joint", "Rename the ankle joint", "Create an IK handle", "Add a pole vector", "Rename the control curves", "Bind the skin"]
    sl = StepList(source_type="youtube", app="maya", title="Leg rig", steps=[Step(id=f"s{i:02d}", order=i, goal=g) for i, g in enumerate(goals, 1)])
    s = Session(app="maya")
    s.load(sl, tutorial={"id": "x", "title": "Leg rig", "source_type": "youtube"})
    s.goto(current)
    return s


def test_it_goes_to_the_start_of_the_latest_matching_run_before_the_current_step():
    s = _session("s06")
    r = respond(s, "go back to renaming the joints")
    assert s.current == "s02" and r.bundle.kind != "clarification"                                     # s02 to s04 are the run; s07 is later and is not "back"
    text = r.bundle.explanations[0].text
    assert "3 steps in a row, s02 to s04" in text and "Back at s02" in text


def test_a_later_matching_step_is_not_a_place_to_go_back_to():
    s = _session("s05")
    respond(s, "go back to renaming")
    assert s.current == "s02"


def test_with_nothing_earlier_it_still_asks_and_lists_the_best_matches():
    s = _session("s01")
    r = respond(s, "go back to renaming the joints")
    assert r.bundle.kind == "clarification" and "Which step do you mean?" in r.bundle.clarification and s.current == "s01"


def test_a_clear_winner_and_a_step_number_work_as_before():
    s = _session("s08")
    respond(s, "go back to the pole vector part")
    assert s.current == "s06"
    respond(s, "go back to step 3")
    assert s.current == "s03"
