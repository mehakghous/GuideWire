"""Houdini guidance without Houdini: the resolver (step words -> node, parm, pane), the three Houdini grounders behind the real gate, the guide moving through a create-select-set step, and the
bridge drawing a box. The snapshot uses the numbers measured in a real Houdini 22.0.466 window (docs/houdini_grounding.md)."""
from __future__ import annotations

import pytest

from app import step_state as ss
from app import vision_bridge as vb
from ingestion import targets_houdini as th
from shared.grounding import CaptureGeometry, Rect
from shared.step_record import Action, HowTo, StatePredicate, Step, TargetRef
from vision import grounders as g
from vision.ocr import Word
from vision.verify import gate

pytestmark = pytest.mark.skipif(not th._types()[0], reason="knowledge/app_vocab/houdini.json is missing")

SNAP = {"v": 1, "dpr": 1.0,
        "panes": [{"type": "SceneViewer", "rect": [33, 197, 865, 433], "state": "sopview"}, {"type": "Parm", "rect": [932, 165, 433, 201]},
                  {"type": "NetworkEditor", "rect": [932, 395, 433, 235]}],
        "network": {"path": "/obj/gw_test", "rect": [932, 395, 433, 235],
                    "nodes": [{"name": "skeleton1", "type": "kinefx::skeleton", "label": "Skeleton", "rect": [1110, 445, 87, 22], "selected": False},
                              {"name": "packfolder1", "type": "packfolder", "label": "Pack Folder", "rect": [1110, 532, 87, 21], "selected": True}]},
        "parm": {"node": "/obj/gw_test/packfolder1", "type": "packfolder", "label": "Pack Folder", "rect": [932, 165, 433, 201],
                 "labels": ["Parent Folder", "Replace Method", "Pack Output", "Only Pack Unpacked", "Ignore Empty Inputs", "Reload Names", "Names", "Use Input #", "Name", "Type"]},
        "viewer": {"state": "sopview", "rect": [33, 197, 865, 433]}}
# words as Windows OCR read them in the real capture (frame = window at 0,0, so frame pixels = screen pixels)
WORDS = [Word("Parent", Rect(1005, 207, 40, 14), 1), Word("Folder", Rect(1048, 207, 40, 14), 1), Word("Replace", Rect(992, 232, 50, 14), 2), Word("Method", Rect(1045, 232, 30, 14), 2),
         Word("Pack", Rect(1107, 254, 30, 14), 3), Word("Output", Rect(1140, 254, 40, 14), 3)]


def ctx(snap=SNAP, words=WORDS):
    return g.GroundContext(None, None, CaptureGeometry(Rect(0, 0, 1366, 728), 1366, 728), None, list(words), houdini=snap)


# ---- resolver
def test_resolver_turns_the_usual_houdini_actions_into_targets():
    a = th.resolve_action
    t = a(Action(verb="select", ui_element="packfolder1"))
    assert (t.kind, t.id, t.label, t.path) == ("node", "packfolder", "Pack Folder", ["packfolder1"])
    assert a(Action(verb="press_keys", keys=["Tab"])).id == "NetworkEditor" and a(Action(verb="press_keys", keys=["F"])).id == "SceneViewer"
    assert a(Action(verb="open_menu", ui_element="Network View > Tab Menu")).keys == ["Tab"]
    assert a(Action(verb="click", ui_element="Scene View")).id == "SceneViewer"
    node = TargetRef(kind="node", label="Pack Folder", id="packfolder")
    p = a(Action(verb="set_value", ui_element="Replace Method", value="Add and Replace"), node)
    assert (p.kind, p.prop, p.panel) == ("parm", "Replace Method", "Pack Folder")
    assert a(Action(verb="click", ui_element="+ Add Visualizer")) is None                       # nothing it can point at


def test_the_node_a_parameter_belongs_to_comes_from_the_step_or_is_carried_from_the_one_before():
    s1 = Step(id="s01", order=1, goal="Select the Pack Folder node", actions=[Action(verb="select", ui_element="packfolder1")])
    s2 = Step(id="s02", order=2, goal="Set the method", actions=[Action(verb="set_value", ui_element="Replace Method", value="Add and Replace")])
    r1, r2 = th.resolve_steps([s1, s2])
    assert r2.actions[0].target.panel == "Pack Folder"


# ---- grounders, through the real gate
def test_a_node_is_its_tile():
    gr = gate(g.ground_target(ctx(), TargetRef(kind="node", label="Pack Folder", id="packfolder", path=["packfolder1"])))
    assert gr.ok and gr.result.rect == Rect(1110, 532, 87, 21)


def test_a_node_out_of_view_or_twice_in_view_gets_no_box():
    assert not gate(g.ground_target(ctx(), TargetRef(kind="node", label="Rig Doctor", id="kinefx::rigdoctor"))).ok
    two = {**SNAP, "network": {**SNAP["network"], "nodes": [dict(n, label="Skeleton", selected=False) for n in SNAP["network"]["nodes"]]}}
    r = g.ground_target(ctx(two), TargetRef(kind="node", label="Skeleton"))
    assert r.state == g.AMBIGUOUS and not gate(r).ok


def test_tab_points_at_the_network_editor_as_a_region_with_the_key_in_words():
    r = gate(g.ground_target(ctx(), TargetRef(kind="pane", label="network editor", id="NetworkEditor", keys=["Tab"])))
    assert r.ok and r.result.rect == Rect(932, 395, 433, 235) and r.result.note == "Press Tab with the mouse over the network editor."


def test_a_parameter_is_its_row_in_the_parameter_pane():
    r = gate(g.ground_target(ctx(), TargetRef(kind="parm", label="Replace Method", prop="Replace Method", id="packfolder", panel="Pack Folder")))
    assert r.ok and r.result.rect.x == 992 and r.result.rect.y == 230 and r.result.rect.x + r.result.rect.w == 932 + 433 - 4


def test_a_parameter_of_another_node_first_points_at_that_node():
    shows_skeleton = {**SNAP, "parm": {**SNAP["parm"], "node": "/obj/gw_test/skeleton1", "label": "Skeleton", "type": "kinefx::skeleton"}}
    r = g.ground_target(ctx(shows_skeleton), TargetRef(kind="parm", label="Replace Method", prop="Replace Method", panel="Pack Folder"))
    assert r.state == g.WRONG and r.rect == Rect(1110, 532, 87, 21) and "Select the Pack Folder node first" in r.note


def test_a_label_the_node_does_not_have_or_that_is_not_read_never_gets_a_guessed_box():
    r = g.ground_target(ctx(), TargetRef(kind="parm", label="Target Pattern", prop="Target Pattern", panel="Pack Folder"))
    assert r.state == g.WORDS and r.rect is None
    r = gate(g.ground_target(ctx(words=[]), TargetRef(kind="parm", label="Reload Names", prop="Reload Names", panel="Pack Folder")))
    assert r.result.state == g.NOT_OPEN and r.result.rect == Rect(932, 165, 433, 201) and "scroll it or open the folder" in r.result.note       # the pane as a region, not a field
    twice = WORDS + [Word("Replace", Rect(992, 300, 50, 14), 9), Word("Method", Rect(1045, 300, 30, 14), 9)]
    assert not gate(g.ground_target(ctx(words=twice), TargetRef(kind="parm", label="Replace Method", prop="Replace Method", panel="Pack Folder"))).ok


def test_words_outside_the_parameter_pane_do_not_count():
    outside = [Word("Replace", Rect(100, 300, 50, 14), 1), Word("Method", Rect(153, 300, 30, 14), 1)]
    r = g.ground_target(ctx(words=outside), TargetRef(kind="parm", label="Replace Method", prop="Replace Method", panel="Pack Folder"))
    assert r.state == g.NOT_OPEN


# ---- the guide through one step: Tab (create), select, set
def _step():
    s = Step(id="s03", order=3, goal="Add a Pack Folder node and set its method",
             actions=[Action(verb="press_keys", keys=["Tab"]), Action(verb="select", ui_element="packfolder1"), Action(verb="set_value", ui_element="Replace Method", value="Add and Replace")],
             how_to=[HowTo(text="Press Tab in the network editor and add a Pack Folder.", support="shown", evidence="x")],
             expected_state=[StatePredicate(kind="node_exists", target="packfolder")])
    return th.resolve_steps([s])[0]


def _ground(c):
    return lambda ref: gate(g.ground_target(c, ref))


def test_the_guide_goes_tab_then_the_node_then_the_parameter():
    step = _step()
    empty = {"node_counts": {}, "nodes": []}
    none_selected = {**SNAP, "network": {**SNAP["network"], "nodes": [dict(n, selected=False) for n in SNAP["network"]["nodes"]]}}
    st = ss.assess(step, {**empty, "ui": none_selected}, _ground(ctx(none_selected)), empty)
    assert st.target.kind == "pane" and "Press Tab with the mouse over the network editor" in st.hint
    made = {"node_counts": {"packfolder": 1}, "nodes": ["packfolder"], "ui": none_selected}
    st = ss.assess(step, made, _ground(ctx(none_selected)), empty)
    assert st.target.kind == "node" and st.show_rect and st.grounded.rect == Rect(1110, 532, 87, 21)
    st = ss.assess(step, {**made, "ui": SNAP}, _ground(ctx()), empty)                              # packfolder1 now selected
    assert st.target.kind == "parm" and st.phase == "visible" and st.grounded.rect.y == 230


# ---- the bridge draws it
class HoudiniService:
    def __init__(self, observed, c):
        self.observed, self.c = observed, c

    def look(self, properties=None, attributes=None, keys=None):
        return dict(self.observed), self.c

    def reset(self):
        pass


def test_the_bridge_draws_the_node_box_from_the_houdini_snapshot(tmp_path):
    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    from shared.step_record import StepList
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    s = Step(id="s01", order=1, goal="Select the Pack Folder node", actions=[Action(verb="select", ui_element="packfolder1")])
    tid = StepEditor(StepList(source_type="manual", app="houdini", steps=[s]), title="t").save(db, uid)
    eng = SessionEngine.create(db, uid, tid)
    eng.start()
    none_selected = {**SNAP, "network": {**SNAP["network"], "nodes": [dict(n, selected=False) for n in SNAP["network"]["nodes"]]}}
    bridge = vb.VisionBridge(lambda app: HoudiniService({"node_counts": {}, "nodes": [], "ui": none_selected, "ui_rev": 1}, ctx(none_selected)),
                             window_finder=lambda app: (0, 0, 1366, 728))
    tick = bridge.tick(eng, "houdini")
    assert tick.rect == (1110, 532, 87, 21) and tick.phase == "visible"
    db.close()
