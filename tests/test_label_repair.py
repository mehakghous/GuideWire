"""The second look at a Houdini step whose parameter label the node does not have (2026-11-22): the step's clip, the node's real parameter list, one question. Only an exact label from the list,
said to be seen, with evidence, is accepted; anything else keeps the flag."""
import pytest

from ingestion import houdini_parms as hp
from ingestion.label_repair import SCHEMA, repair_labels, repair_step
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import Action, HowTo, Step, StepList

pytestmark = pytest.mark.skipif(not hp.version(), reason="knowledge/app_vocab/houdini.json is missing")
URL = "https://www.youtube.com/watch?v=AAAAAAAAAAA"


def _step():
    return Step(id="s09", order=9, goal="Configure controls on APEX Configure Controls", video_start_s=184.0, video_end_s=197.0,
                how_to=[HowTo(text="Set Target Pattern to point* on configurecontrols1.", support="shown", evidence="x")],
                actions=[Action(verb="set_value", ui_element="Target Pattern", value="point*")],
                flags=["'Target Pattern' is not a parameter of APEX Configure Controls in Houdini 22.0.466: check the label in the video (the tutorial may use another Houdini version)"])


def test_a_label_seen_in_the_clip_replaces_the_wrong_one_and_keeps_the_value():
    st = _step()
    p = ScriptedProvider([{"seen": True, "label": "Control Group", "value": "point*", "evidence": "the field labelled Control Group holds point*"}])
    (r,) = repair_step(p, st, URL, 400)
    assert r.label == "Control Group" and r.node == "APEX Configure Controls"
    assert st.how_to[0].text == "Set Control Group to point* on configurecontrols1." and st.actions[0].ui_element == "Control Group" and st.actions[0].value == "point*"
    assert not any("is not a parameter" in f for f in st.flags) and any(f.startswith("label corrected by a second look at 03:01 to 03:20: 'Target Pattern' is 'Control Group'") for f in st.flags)
    assert p.calls[0]["video_url"] == URL + "#t=181,200"
    assert "- Control Group" in p.calls[0]["prompt"] and "Target Pattern" in p.calls[0]["prompt"]       # the real list is offered, and the wrong label named


@pytest.mark.parametrize("answer, why", [
    ({"seen": False, "label": "", "value": "", "evidence": "the parameter pane is not visible"}, "did not show"),
    ({"seen": True, "label": "Target Points", "value": "point*", "evidence": "a field"}, "not a label of that node"),          # not in the node's list: never accepted
    ({"seen": True, "label": "Control Group", "value": "point*", "evidence": ""}, "no evidence"),
    ({"seen": True, "label": "Shape Override", "value": "box", "evidence": "the shape menu set to box"}, "not 'point*' as the step says"),       # another parameter changed in the same clip (the first real run did this)
])
def test_anything_less_than_a_seen_exact_label_keeps_the_flag(answer, why):
    st = _step()
    (r,) = repair_step(ScriptedProvider([answer]), st, URL, 400)
    assert r.label is None and why in r.reason
    assert "Target Pattern" in st.how_to[0].text and any("is not a parameter" in f for f in st.flags) and any("could not correct 'Target Pattern'" in f for f in st.flags)


def test_a_failed_call_keeps_the_step():
    st = _step()
    (r,) = repair_step(ScriptedProvider([RuntimeError("quota")]), st, URL, 400)
    assert r.label is None and "could not be made" in r.reason and "Target Pattern" in st.how_to[0].text


def test_case_of_the_answer_does_not_matter_but_the_list_spelling_is_used():
    st = _step()
    repair_step(ScriptedProvider([{"seen": True, "label": "control group", "value": "point.*", "evidence": "seen"}]), st, URL, 400)
    assert "Control Group" in st.how_to[0].text


def test_only_houdini_and_only_flagged_steps_cost_a_call():
    ok = Step(id="s01", order=1, goal="Set the shape on APEX Configure Controls", video_start_s=1.0, video_end_s=5.0,
              how_to=[HowTo(text="Set Shape Override to box.", support="shown", evidence="x")])
    p = ScriptedProvider([])
    assert repair_labels(p, StepList(source_type="youtube", app="houdini", steps=[ok]), "AAAAAAAAAAA") == [] and p.calls == []
    assert repair_labels(p, StepList(source_type="youtube", app="maya", steps=[_step()]), "AAAAAAAAAAA") == [] and p.calls == []


def test_the_schema_is_plain_json():
    assert SCHEMA["properties"]["label"]["type"] == "string" and set(SCHEMA["required"]) == {"seen", "label", "value", "evidence"}


def test_a_step_without_a_value_does_not_need_one():
    st = Step(id="s04", order=4, goal="Pack the skeleton on Pack Folder", video_start_s=40.0, video_end_s=58.0,
              how_to=[HowTo(text="Open the Folder Name parameter.", support="shown", evidence="x")])
    (r,) = repair_step(ScriptedProvider([{"seen": True, "label": "Name", "value": "base", "evidence": "the Name field"}]), st, URL, 400)
    assert r.label == "Name" and st.how_to[0].text == "Open the Name parameter."
