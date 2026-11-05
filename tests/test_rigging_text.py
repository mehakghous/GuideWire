import json

import pytest

from ingestion import cli
from ingestion.rigging_text import clauses_of, looks_like_rigging, rigging_to_steplist
from ingestion.router import route
from ingestion.service import Service

MAYA = "1. Create joints down the arm\n2. Mirror joint across YZ\n3. Create an IK handle on the leg\n4. Bind skin to the skeleton\n5. Review the arcs"
HOUDINI = "1. Add a Rig Doctor to check the skeleton\n2. Add a Bone Deform"


def test_clauses_come_one_per_line_without_numbering():
    assert clauses_of(MAYA)[:2] == ["Create joints down the arm", "Mirror joint across YZ"]
    assert clauses_of("- one thing\n- another thing") == ["one thing", "another thing"]


def test_maya_steps_get_features_nodes_craft_and_are_valid():
    sl, res = rigging_to_steplist(MAYA, "maya")
    assert sl.app == "maya" and [s.feature_id for s in sl.steps] == ["SKEL-01", "SKEL-04", "IKFK-02", "SKIN-01", "CLNP-04"]
    assert [p.target for p in sl.steps[0].expected_state] == ["joint"] and [p.target for p in sl.steps[2].expected_state] == ["ikHandle"]
    assert sl.steps[0].verifiable and not any("derived" in f for f in sl.steps[0].flags)      # stated in the text: not derived
    assert [p.target for p in sl.steps[3].expected_state] == ["skinCluster"] and any("derived from the knowledge base" in f for f in sl.steps[3].flags)   # "bind skin": from the documented effect, labelled
    assert not sl.steps[1].verifiable and not sl.steps[4].verifiable                  # a mirror and a review claim nothing a program could check
    assert sl.steps[4].kind == "craft" and any("not graded" in f for f in sl.steps[4].flags)
    assert all(s.goal and s.evidence == [s.goal] and s.review_status == "drafted_automatically" for s in sl.steps)     # user's wording kept, labelled as drafted
    assert len(res.assumptions) == 1 and "assume you already did" in res.assumptions[0] and "PREP-05" in res.assumptions[0]       # one line, not one per feature


def test_unmatched_clauses_stay_as_flagged_steps_and_are_counted():
    sl, res = rigging_to_steplist("Create joints\nSubscribe to my channel", "maya")
    assert len(sl.steps) == 2 and res.unmatched == ["Subscribe to my channel"]
    assert any("not matched" in f for f in sl.steps[1].flags) and any("1 of 2" in c for c in res.caveats)


def test_houdini_nodes_are_named_by_the_profile_and_one_line_is_refused():
    sl, _ = rigging_to_steplist(HOUDINI, "houdini")
    assert {p.target for p in sl.steps[0].expected_state} >= {"Rig Doctor"} and [p.target for p in sl.steps[1].expected_state] == ["Bone Deform"]
    with pytest.raises(ValueError, match="at least two"):
        rigging_to_steplist("Create joints", "maya")


def test_a_feature_the_app_lacks_is_reported_not_hidden():
    sl, res = rigging_to_steplist("Create a joint chain\nRetarget the animation to the new character", "blender")
    assert not any(s.feature_id == "LAYR-06" for s in sl.steps) or any("no tool in blender" in c for c in res.caveats)


def test_router_sends_maya_procedures_here_and_leaves_blender_modelling_alone():
    b = route(MAYA, app="maya")
    assert b.route == "rigging_text" and b.kind == "procedure" and b.steps.app == "maya"
    assert route("how do I bind skin?", app="maya").route == "clarify"                         # a question is not a procedure
    assert route("1. Add a cube\n2. Press Tab\n3. Extrude").route == "text_parser"             # Blender modelling: the old route, unchanged
    assert not looks_like_rigging("1. Add a cube\n2. Press Tab", "blender")


def test_cli_ask_with_app_prints_the_step_list(capsys):
    assert cli.main(["ask", "--app", "maya", "--no-kb", "Create joints down the arm\nCreate an IK handle on the leg"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["route"] == "rigging_text" and [s["feature_id"] for s in d["steps"]["steps"]] == ["SKEL-01", "IKFK-02"]


def test_chat_flow_app_command_load_observe_verify_and_restart(tmp_path):
    f, sess = tmp_path / "steps.txt", tmp_path / "s.json"
    f.write_text("Create joints down the arm\nCreate an IK handle on the leg\n", encoding="utf-8")
    s = Service.open(sess, use_kb=False)
    assert "unknown application" in s.message("/app unity")["text"]
    s.message("/app maya")
    out = s.message(f'/load steps "{f}"')
    assert s.session.app == "maya" and "Loaded 2 steps" in out["text"]
    s.message("/observe nodes=joint")
    v = s.session.verify(s.session.current_step)
    assert v.outcome == "met"                                                                  # a joint exists, so "create joints" is met
    s.session.complete()
    s.message("/state")                                                                        # any service call saves the session
    assert s.session.verify(s.session.current_step).outcome == "unmet"                         # no ikHandle reported yet
    again = Service.open(sess, use_kb=False)                                                   # restart: app, steps and position survive
    assert again.session.app == "maya" and again.session.current == "s02" and again.state()["app"] == "maya"


def test_old_session_files_without_an_app_still_open(tmp_path):
    s = Service.open(tmp_path / "s.json", use_kb=False)
    s.message("/version 4.2")
    d = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    d.pop("app")
    (tmp_path / "s.json").write_text(json.dumps(d), encoding="utf-8")
    assert Service.open(tmp_path / "s.json", use_kb=False).session.app == "blender"
