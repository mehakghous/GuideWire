"""Blender shortcut knowledge (shared/shortcuts.py) against the dumped default keymap, and the catalog itself (tests/ also guard the dump's shape)."""
from __future__ import annotations

import json

import pytest

from shared import shortcuts as sc


def test_a_key_is_valid_only_in_the_modes_whose_keymap_has_it():
    assert [s.display for s in sc.shortcuts_for("mesh.loopcut_slide", "EDIT_MESH")] == ["Ctrl R"]
    assert sc.shortcuts_for("mesh.loopcut_slide", "OBJECT") == []                # Ctrl+R in Object Mode is something else: not offered for Loop Cut
    assert sc.shortcuts_for("mesh.loopcut_slide", "POSE") == []
    parent = sc.shortcuts_for("object.parent_set", "OBJECT")
    assert parent and parent[0].keys == ("ctrl", "p") and parent[0].keymap == "Object Mode" and parent[0].modes == frozenset({"OBJECT"})


def test_the_same_key_means_different_operators_in_different_modes():
    assert sc.operator_for_keys(["Ctrl", "P"], "OBJECT") == ["object.parent_set"]
    assert "object.parent_set" not in sc.operator_for_keys(["Ctrl", "P"], "EDIT_MESH")
    assert sc.operator_for_keys("Tab", "OBJECT") == ["object.mode_set"]
    assert sc.operator_for_keys(["A"], "EDIT_MESH") == ["mesh.select_all"]
    assert sc.operator_for_keys(["S"], "EDIT_MESH") == ["transform.resize"]


def test_key_names_are_normalized_so_tutorial_spellings_match():
    assert sc.canonical(["P", "Ctrl"]) == sc.canonical("Ctrl+P") == sc.canonical("control p") == ("ctrl", "p")
    assert sc.canonical(["Shift", "Ctrl", "Z"]) == ("ctrl", "shift", "z")
    assert sc.canonical(["Del"]) == sc.canonical(["Delete"]) and sc.canonical("Escape") == ("esc",)


def test_clicks_and_drags_are_not_keys_to_press():
    assert all("mouse" not in s.display.lower() for s in sc.shortcuts_for("mesh.loopcut_slide", "EDIT_MESH"))
    assert sc.operator_for_keys(["Left Mouse"], "EDIT_MESH") == []


def test_properties_filter_one_binding_from_another():
    plain = sc.shortcuts_for("object.delete", "OBJECT", props={"use_global": False})
    global_ = sc.shortcuts_for("object.delete", "OBJECT", props={"use_global": True})
    assert {s.display for s in plain} >= {"X", "Delete"} and {s.display for s in global_} >= {"Shift X"} and "X" not in {s.display for s in global_}


def test_the_learners_own_keymap_wins_over_the_default_one():
    user = [{"keymap": "Mesh", "space": "EMPTY", "key": "Alt R", "user": True}, {"keymap": "3D View Tool: Edit Mesh, Loop Cut", "space": "VIEW_3D", "key": "Left Mouse", "user": False}]
    got = sc.shortcuts_for("mesh.loopcut_slide", "EDIT_MESH", user_keys=user)
    assert [(s.display, s.source) for s in got] == [("Alt R", "your keymap")]
    assert sc.shortcuts_for("mesh.loopcut_slide", "EDIT_MESH", user_keys=[]) == []          # the add-on says it has no key: the default is not used
    assert sc.shortcuts_for("mesh.loopcut_slide", "OBJECT", user_keys=user) == []           # and a keymap of another mode still does not apply


def test_most_tools_have_no_key_that_selects_them():
    assert sc.tool_shortcut("builtin.loop_cut", "EDIT_MESH") is None                        # Ctrl+R runs the operator; it does not make Loop Cut the active tool
    assert sc.tool_shortcut("builtin.scale", "EDIT_MESH") is None                           # S scales; it does not pick the Scale tool and its handles


def test_a_shortcut_that_would_not_leave_the_state_the_step_expects_is_never_advised():
    a = sc.advise(tool_id="builtin.loop_cut", operator="mesh.loopcut_slide", mode="EDIT_MESH", visibility="offscreen", expects_tool="builtin.loop_cut")
    assert not a.show and a.shortcut is None and "does not make" in a.reason
    # the same target, but the step only needs the operator to run (no tool check): now Ctrl+R is a fair way around a hidden tool
    b = sc.advise(tool_id="builtin.loop_cut", operator="mesh.loopcut_slide", mode="EDIT_MESH", visibility="offscreen")
    assert b.show and b.shortcut.display == "Ctrl R"


def test_a_shortcut_is_shown_when_the_target_is_out_of_reach_or_the_tutorial_uses_it_and_not_otherwise():
    kw = dict(operator="transform.resize", mode="EDIT_MESH")
    assert not sc.advise(**kw, visibility="visible").show                                    # the control is on screen: highlight it
    assert sc.advise(**kw, visibility="visible", tutorial_uses_keys=True).show
    assert sc.advise(**kw, visibility="offscreen").show and sc.advise(**kw, visibility="container_hidden").show
    assert not sc.advise(operator="mesh.loopcut_slide", mode="OBJECT", visibility="offscreen").show      # no key in this mode


def test_a_different_blender_version_is_said_not_hidden():
    note = sc.advise(operator="transform.resize", mode="EDIT_MESH", tutorial_uses_keys=True, app_version="4.2.1 LTS").version_note
    assert "5.2" in note and "4.2" in note
    assert sc.advise(operator="transform.resize", mode="EDIT_MESH", tutorial_uses_keys=True, app_version="5.2.0").version_note == ""


# ---- the catalog these rely on
@pytest.fixture(scope="module")
def catalog():
    return sc._catalog()


def test_the_catalog_names_its_blender_version_and_has_every_part(catalog):
    assert catalog["version"].startswith("5.2") and catalog["app"] == "blender"
    for part in ("tools", "operators", "panels", "menus", "tabs", "keymap", "modes"):
        assert catalog[part], part


def test_every_keymap_in_the_dump_is_one_the_mode_table_knows(catalog):
    """If Blender adds a keymap family to the dump, it must be decided where it applies: this test fails instead of the key silently applying everywhere or nowhere."""
    known = set(sc.KEYMAP_MODES) | set(sc.ANY_MODE_KEYMAPS) | {"Property Editor", "Outliner", "Armature Edit"}
    assert {r["keymap"] for r in catalog["keymap"]} <= known


def test_loop_cut_is_where_the_resolver_and_the_guidance_expect_it(catalog):
    edit = [t for row in catalog["tools"]["EDIT_MESH"] for t in row.get("group", [])]
    loop = next(t for t in edit if t["id"] == "builtin.loop_cut")
    assert loop["label"] == "Loop Cut" and loop["operator"] == "mesh.loopcut_slide"
    assert not any(t["id"] == "builtin.loop_cut" for row in catalog["tools"]["OBJECT"] for t in row.get("group", []))
    cells = [row for row in catalog["tools"]["EDIT_MESH"] if "group" in row]
    assert len(cells) == 21 and any(t["id"] == "builtin.loop_cut" for t in cells[12]["group"])       # 21 cells; Loop Cut is the 13th (the old static list agreed: index 12 of 21)


def test_the_old_static_toolbar_list_agrees_with_the_catalog(catalog):
    """vision/toolbars.json (retired in Part C) and the new catalog came from the same Blender; if they ever differ, something is wrong with one dump."""
    old = json.loads((sc.CATALOG.parent.parent.parent / "vision" / "toolbars.json").read_text(encoding="utf-8"))
    for mode in ("OBJECT", "EDIT_MESH", "POSE", "EDIT_ARMATURE"):
        ids_old = [[t["id"] for t in g] for g in old[mode]]
        ids_new = [[t["id"] for t in row["group"]] for row in catalog["tools"][mode] if "group" in row]
        assert ids_old == ids_new, mode
