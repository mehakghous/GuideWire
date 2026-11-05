"""Transcripts for rigging/animation tutorials in Maya, Houdini and Blender (rules only, no model)."""
import json

from ingestion import cli
from ingestion.router import route
from ingestion.service import Service

MAYA = """00:02 okay so in this video we are going to rig the leg of our character
00:08 first let's create a joint chain going down the leg in the side view
00:15 now go to skeleton and orient joint so the x axis points down the bone
00:24 next we create an IK handle from the hip to the ankle
00:33 then we add an attribute to the control called fk ik switch
00:41 and that's pretty much it, thanks for watching, see you in the next one"""

HOUDINI = """00:03 alright first we add a skeleton node and draw the joints
00:12 then add a rig doctor to check the skeleton
00:20 and finally we add a bone deform to bind the mesh"""


def test_maya_transcript_becomes_timed_narrated_steps_with_features_and_nodes():
    b = route(MAYA, input_type="transcript", app="maya", duration_s=60)
    sl = b.steps
    assert b.route == "transcript_parser" and sl.app == "maya" and sl.source_type == "transcript"
    feats = [s.feature_id for s in sl.steps]
    assert feats[:3] == ["SKEL-01", "ORNT-02", "IKFK-02"] and "CTRL-04" in feats
    assert all(s.support == "narrated" and s.provenance == "transcript_rules" and s.evidence and s.video_start_s is not None for s in sl.steps)
    assert [p.target for p in sl.steps[0].expected_state] == ["joint"] and [p.target for p in sl.steps[2].expected_state] == ["ikHandle"]
    assert not any(s.goal.lower().startswith("okay so in this video") for s in sl.steps)                # the intro and the sign-off are not steps
    assert len(b.assumptions) == 1 and "PREP-05" in b.assumptions[0]


def test_houdini_transcript_names_nodes_from_the_profile():
    sl = route(HOUDINI, input_type="transcript", app="houdini", duration_s=40).steps
    assert sl.app == "houdini"
    nodes = {p.target for s in sl.steps for p in s.expected_state}
    assert {"Skeleton", "Rig Doctor", "Bone Deform"} <= nodes


def test_chatter_and_talk_about_a_feature_without_an_instruction_are_not_steps():
    b = route("00:02 thanks for watching and see you next time\n00:09 ik is a way of posing a limb from its end point", input_type="transcript", app="maya", duration_s=20)
    assert b.steps is None and b.kind == "unsupported"


def test_blender_modelling_talk_does_not_become_rigging_steps():
    b = route("00:02 edit mode is where you change the shape of the mesh and object mode is where you move whole objects", input_type="transcript", app="blender", duration_s=20)
    assert b.steps is None                                                                           # no rigging vocabulary: nothing is guessed


def test_blender_modelling_transcripts_still_use_the_modelling_catalog():
    b = route("00:02 press tab to go into edit mode and select a vertex", input_type="transcript", app="blender", duration_s=20)
    assert b.steps is not None and b.steps.steps[0].provenance == "transcript_rules" and b.steps.steps[0].goal.startswith("Enter Edit Mode")


def test_a_blender_rigging_transcript_falls_back_to_the_rigging_reader():
    t = "00:02 now we create a bone chain for the arm\n00:10 and then we bind the mesh to the armature with automatic weights"
    sl = route(t, input_type="transcript", app="blender", duration_s=30).steps
    assert sl is not None and sl.app == "blender" and [s.feature_id for s in sl.steps][0] == "SKEL-01"


def test_neighbouring_units_about_one_feature_are_one_step_and_other_versions_are_flagged():
    t = ("00:02 first let's create a joint chain for the leg\n00:08 we keep creating joints down to the toe\n"
         "00:30 in maya 2019 you would orient the joints a different way, now we orient the joints with the orient joint option")
    sl = route(t, input_type="transcript", app="maya", version="2024", duration_s=60).steps
    assert [s.feature_id for s in sl.steps].count("SKEL-01") == 1 and sl.steps[0].video_end_s >= 8
    assert any("version cue" in f and "2019" in f for s in sl.steps for f in s.flags)


def test_cli_transcript_takes_an_app(tmp_path, capsys):
    f = tmp_path / "t.txt"
    f.write_text(MAYA, encoding="utf-8")
    assert cli.main(["transcript", str(f), "--app", "maya", "--duration", "60"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["steps"]["app"] == "maya" and d["steps"]["steps"][0]["feature_id"] == "SKEL-01"


def test_chat_loads_a_transcript_for_the_chosen_app_and_keeps_it_through_a_restart(tmp_path):
    f, sess = tmp_path / "t.txt", tmp_path / "s.json"
    f.write_text(MAYA, encoding="utf-8")
    s = Service.open(sess, use_kb=False)
    s.message("/app maya")
    out = s.message(f'/load transcript "{f}" 60')
    assert s.session.app == "maya" and "Loaded" in out["text"] and s.session.steps.steps[0].feature_id == "SKEL-01"
    assert Service.open(sess, use_kb=False).session.steps.steps[0].feature_id == "SKEL-01"
