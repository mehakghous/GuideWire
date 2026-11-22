"""Exact menu paths: the resolver on the real Blender 5.2 dump, the step and answer hooks, and the
Maya/Houdini walkers against fake applications (neither is installed here)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ingestion.menu_steps import add_menu_paths, menu_lines
from shared import menu_paths
from shared.menu_paths import best_menu_path, find_menu_paths
from shared.step_record import Action, HowTo, Step, StepList
from shared.step_record import StatePredicate as P

sys.path.insert(0, str(Path(__file__).parents[1] / "vision" / "menus"))
import walkers  # noqa: E402


def _top(app, query, mode=None):
    hits = find_menu_paths(app, query, mode, limit=1)
    return hits[0] if hits else None


# ------------------------------------------------------------------------------- Blender (real dump)
@pytest.mark.parametrize("query, mode, path, keys", [
    ("how do I add a cube", None, "Add > Mesh > Cube", None),
    ("join the objects", None, "Object > Join", "Ctrl+J"),
    ("bevel the edges", "EDIT_MESH", "Edge > Bevel Edges", "Ctrl+B"),
    ("extrude faces", "EDIT_MESH", "Face > Extrude Faces", "E"),
    ("delete the object", None, "Object > Delete", "X"),
    ("apply the scale", None, "Object > Apply > Scale", None),
    ("save as", None, "File > Save As...", "Ctrl+Shift+S"),
    ("export as fbx", None, "File > Export > FBX (.fbx)", None),
])
def test_blender_questions_resolve_to_the_exact_dropdown_item(query, mode, path, keys):
    hit = _top("blender", query, mode)
    assert hit is not None and hit.text == path and hit.keys == keys


def test_every_path_exists_in_the_dump_and_unknown_asks_find_nothing():
    assert find_menu_paths("blender", "flatten the horizon") == []
    assert find_menu_paths("blender", "") == [] and find_menu_paths("zbrush", "add a cube") == []
    labels = {e.path for e in menu_paths.load_menus("blender")}
    for q in ("add a monkey", "duplicate the object", "merge by distance"):
        for h in find_menu_paths("blender", q):
            assert h.path in labels                                  # never an invented path


def test_edit_mode_items_say_what_to_do_first():
    hit = _top("blender", "bevel edges", "EDIT_MESH")
    assert hit.needs and "Edit Mode" in hit.needs
    assert _top("blender", "join objects").needs is None
    assert "3D Viewport header" in hit.describe() and "Ctrl+B" in hit.describe()


def test_ambiguous_requests_are_not_decided_for_the_learner():
    assert best_menu_path("blender", "make a sphere") is None                          # UV Sphere or Ico Sphere: not chosen for them
    assert best_menu_path("blender", "add a cube").text == "Add > Mesh > Cube"
    lines = menu_lines("blender", "how do I make a sphere")
    assert lines and lines[0].startswith("Where (pick the one you mean)")
    assert "UV Sphere" in lines[0] and "Ico Sphere" in lines[0]
    assert menu_lines("blender", "how do I add a cube") == ["Where: Add > Mesh > Cube  (3D Viewport header; Object Mode)"]


def test_definition_questions_get_no_menu_line():
    assert menu_lines("blender", "what is a vertex") == []
    assert menu_lines("blender", "why does extrude not work") == []
    assert menu_lines("blender", "What's the difference between UV and Ico sphere") == []


# ------------------------------------------------------------------------------- step enrichment
def _step(goal, i=1, **kw):
    return Step(id=f"s{i:02d}", order=i, goal=goal, **kw)


def test_steps_gain_the_exact_menu_path_only_when_it_is_clear():
    sl = StepList(source_type="written", app="blender", steps=[
        _step("Add a cube to the scene", 1),
        _step("Bevel the edges", 2, start_state=[P(kind="mode", target="EDIT_MESH")]),
        _step("Make a sphere", 3),                                   # several equally good: left alone
        _step("Flatten the horizon", 4),                             # no menu: left alone
    ])
    assert add_menu_paths(sl) == 2
    first, second, third, fourth = sl.steps
    assert first.actions[-1] == Action(verb="open_menu", ui_element="Add > Mesh > Cube")
    assert first.how_to[-1].support == "catalog" and first.how_to[-1].text.startswith("Menu: Add > Mesh > Cube")
    assert "Shortcut: Ctrl+B" in second.how_to[-1].text and any("Edit Mode" in a for a in second.assumptions)
    assert not third.how_to and not fourth.how_to
    assert add_menu_paths(sl) == 0                                   # idempotent


def test_steps_with_a_full_path_are_not_touched():
    st = _step("Add a cube", actions=[Action(verb="open_menu", ui_element="Add > Mesh > Cube")])
    sl = StepList(source_type="written", app="blender", steps=[st])
    assert add_menu_paths(sl) == 0 and not st.how_to
    st2 = _step("Add a cube", how_to=[HowTo(text="Menu: Add > Mesh > Cube", support="catalog")])
    assert add_menu_paths(StepList(source_type="written", app="blender", steps=[st2])) == 0
    st3 = _step("Orient the joints", how_to=[HowTo(text="Open Skeleton > Orient Joint.", support="shown", evidence="Skeleton > Orient Joint")])
    assert add_menu_paths(StepList(source_type="written", app="maya", steps=[st3])) == 0 and len(st3.how_to) == 1   # model-written path stays alone


def test_the_chat_service_appends_the_exact_path_to_answers():
    from ingestion.service import Service
    svc = Service.open(use_kb=False)
    out = svc.message("how do I add a cube")["text"]
    assert "Where: Add > Mesh > Cube" in out
    assert "Where:" not in svc.message("what is a vertex")["text"]
    assert "Where:" not in svc.command("/help")["text"]


# ------------------------------------------------------------------------------- Maya (real dump from Maya 2027.3)
@pytest.mark.parametrize("query, path, needs", [
    ("add a cube", "Create > Polygon Primitives > Cube", None),
    ("create a sphere", "Create > Polygon Primitives > Sphere", None),
    ("save the scene as", "File > Save Scene As...", None),
    ("create joints", "Skeleton > Create Joints", "Rigging"),
    ("bind skin", "Skin > Bind Skin", "Rigging"),
    ("create an ik handle", "Skeleton > Create IK Handle", "Rigging"),
    ("combine objects", "Mesh > Combine", "Modeling"),
    ("set a keyframe", "Key > Set Key", "Animation"),
    ("batch render", "Render > Batch Render", "Rendering"),
])
def test_maya_questions_resolve_to_real_menu_items_and_the_menu_set_to_switch_to(query, path, needs):
    hit = _top("maya", query)
    assert hit is not None and hit.text == path and hit.where == "Maya main menu bar"
    assert (needs in hit.needs) if needs else hit.needs is None


def test_maya_paths_that_exist_in_several_menu_sets_are_listed_once():
    hit = _top("maya", "parent constraint")
    assert hit.text == "Constrain > Parent" and len(hit.modes) >= 2 and "menu sets" not in hit.describe().split("(")[0]
    assert find_menu_paths("maya", "flatten the horizon") == []


# ------------------------------------------------------------------------------- Maya / Houdini (synthetic)
def _write(tmp_path, monkeypatch, app, groups):
    (tmp_path / f"{app}_menus.json").write_text(json.dumps({"app": app, "groups": groups}), encoding="utf-8")
    monkeypatch.setattr(menu_paths, "MENU_DIR", tmp_path)
    menu_paths.load_menus.cache_clear()


def test_groups_from_other_applications_resolve_and_say_where(tmp_path, monkeypatch):
    try:
        _write(tmp_path, monkeypatch, "maya", [
            {"id": "modelingMenuSet", "label": "Modeling menu set", "where": "Maya main menu bar", "needs": "Switch to Modeling first.",
             "tree": [{"label": "Create", "children": [{"label": "Polygon Primitives", "children": [{"label": "Cube", "op": "polyCube"}]}]}]},
            {"id": "riggingMenuSet", "label": "Rigging menu set", "where": "Maya main menu bar", "needs": "Switch to Rigging first.",
             "tree": [{"label": "Skeleton", "children": [{"label": "Create Joints", "op": "JointTool"}]}]}])
        hit = _top("maya", "add a cube")
        assert hit.text == "Create > Polygon Primitives > Cube" and hit.where == "Maya main menu bar"
        assert hit.needs == "Switch to Modeling first." and "Modeling menu set" in hit.describe()
        rig = _top("maya", "create joints")
        assert rig.text == "Skeleton > Create Joints" and rig.needs == "Switch to Rigging first."
        assert find_menu_paths("houdini", "add a box") == []         # no dump for Houdini yet: nothing invented
    finally:
        monkeypatch.undo()
        menu_paths.load_menus.cache_clear()


class _FakeMaya:
    """Common set: File (New, divider, Open Scene, option box), Create > Polygon Primitives (built on demand) > Cube.
    Modeling set: Mesh. Rigging set: Skeleton."""

    def __init__(self):
        self.items = {"mFile": ["iNew", "iDiv", "iOpen", "iOpt"], "mCreate": ["iPoly"], "iPoly": [], "mMesh": ["iCombine"], "mSkel": ["iJoints"],
                      "mHotbox": []}
        self.labels = {"mFile": "&File", "mCreate": "Create", "mMesh": "Mesh", "mSkel": "Skeleton", "mHotbox": "Hotbox North 1",
                       "iNew": "New", "iOpen": "Open Scene...", "iPoly": "Polygon Primitives", "iCube": "Cube", "iOpt": "opt",
                       "iCombine": "Combine", "iJoints": "Create Joints"}
        self.menus = {"mFile", "mCreate", "mMesh", "mSkel", "mHotbox"}
        self.sets = {"commonMenuSet": ["mFile", "mCreate", "mHotbox"], "modelingMenuSet": ["mMesh"], "riggingMenuSet": ["mSkel", "mGone"]}

    def menu(self, name, **k):
        if k.get("exists"):
            return name in self.menus
        if k.get("itemArray"):
            return self.items.get(name, [])
        if k.get("label"):
            return self.labels[name]
        if k.get("postMenuCommand"):
            return ""

    def menuItem(self, name, **k):
        if k.get("divider"):
            return name == "iDiv"
        if k.get("optionBox"):
            return name == "iOpt"
        if k.get("label"):
            return self.labels[name]
        if k.get("subMenu"):
            return name == "iPoly"
        if k.get("itemArray"):
            return self.items.get(name, [])
        if k.get("postMenuCommand"):
            return "buildPoly" if name == "iPoly" else ""
        if k.get("command"):
            return {"iNew": "NewScene", "iOpen": "OpenScene", "iCube": "polyCube", "iCombine": "CombinePolygons", "iJoints": "JointTool"}.get(name, "")

    def menuSet(self, *a, **k):
        if k.get("allMenuSets"):
            return list(self.sets)
        if k.get("menuArray"):
            return self.sets[a[0]]
        if k.get("label"):
            return {"commonMenuSet": "Common", "modelingMenuSet": "Modeling", "riggingMenuSet": "Rigging"}[a[0]]


def test_maya_walker_reads_each_menu_set_builds_menus_on_demand_and_skips_dividers_and_option_boxes():
    cmds = _FakeMaya()
    mel = NS(eval=lambda cmd: (cmds.items.__setitem__("iPoly", ["iCube"]) if cmd == "buildPoly" else None))
    groups = walkers.maya_groups(cmds, mel)
    assert [g["id"] for g in groups] == ["commonMenuSet", "modelingMenuSet", "riggingMenuSet"]
    common, modeling, rigging = groups
    assert [t["label"] for t in common["tree"]] == ["File", "Create"]                              # hotbox dropped, "&" removed
    assert "needs" not in common and common["label"] == "all menu sets"
    assert [c["label"] for c in common["tree"][0]["children"]] == ["New", "Open Scene..."]        # no divider, no option box
    assert common["tree"][1]["children"][0] == {"label": "Polygon Primitives", "children": [{"label": "Cube", "op": "polyCube"}]}
    assert [t["label"] for t in modeling["tree"]] == ["Mesh"] and [t["label"] for t in rigging["tree"]] == ["Skeleton"]   # a missing menu is skipped
    assert rigging["needs"] == "Switch the menu set (top-left dropdown) to Rigging first."


HOUDINI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mainMenu><menuBar>
  <subMenu id="file_menu"><label>&amp;File</label>
    <scriptItem id="h.new"><label>New</label></scriptItem>
    <separatorItem/>
    <subMenu id="import_menu"><label>Import</label><scriptItem id="h.import_geo"><label>Geometry...</label></scriptItem></subMenu>
  </subMenu>
  <subMenu id="render_menu"><label>Render</label><actionItem id="h.render"><label>Create Render Node</label></actionItem></subMenu>
</menuBar></mainMenu>"""


def test_houdini_menu_xml_is_parsed_into_a_tree():
    tree = walkers.parse_houdini_menu_xml(HOUDINI_XML)
    assert [t["label"] for t in tree] == ["File", "Render"]
    assert [c["label"] for c in tree[0]["children"]] == ["New", "Import"]
    assert tree[0]["children"][1]["children"] == [{"label": "Geometry...", "op": "h.import_geo"}]


def test_houdini_groups_include_the_main_menu_and_tab_menu_names():
    def t(name, desc, hidden=False):
        return NS(name=lambda: name, description=lambda: desc, hidden=lambda: hidden, deprecated=lambda: False)
    hou = NS(findFile=lambda n: "menu.xml" if n == "MainMenuCommon.xml" else None,
             nodeTypeCategories=lambda: {"Sop": NS(nodeTypes=lambda: {"box": t("box", "Box"), "xform": t("xform", "Transform"), "old": t("old", "Old", True)})})
    groups = walkers.houdini_groups(hou, read_file=lambda p: HOUDINI_XML)
    assert [g["id"] for g in groups] == ["MAIN", "TAB_SOP"]
    assert [i["label"] for i in groups[1]["tree"]] == ["Box", "Transform"]                      # hidden types dropped, sorted
    assert groups[1]["needs"].startswith("Open a Sop network")
