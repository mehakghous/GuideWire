"""Add-on snapshot v2: the interface block, the tool list, keymap lookup, revisions and expiring requests.

Fake `bpy` here; the same functions were also run in a real Blender 5.2.2 window (see docs/vision-research.md, section 4), which is where the shapes come from.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ADDON = Path(__file__).parents[1] / "vision" / "blender_addon" / "guidewire_probe.py"
TABS_MESSAGE = "bpy_struct: item.attr = val: enum \"%s\" not found in ('TOOL', 'RENDER', 'OBJECT', 'DATA')"


def _addon():
    spec = importlib.util.spec_from_file_location("guidewire_probe_ui", ADDON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _region(kind, x, y, w, h, scroll=None):
    view = NS(region_to_view=lambda px, py: (0.0, (1.0 - scroll) if py else (-548.0 - scroll))) if scroll is not None else None
    return NS(type=kind, x=x, y=y, width=w, height=h, view2d=view)


class _Props:
    def __init__(self, message):
        self.message = message

    context = property(lambda self: "OBJECT")

    @context.setter
    def context(self, value):
        raise TypeError(self.message % value)


def _fake_ui_bpy(sidebar=False, scroll=0.0, tabs_message=TABS_MESSAGE):
    regions = [_region("HEADER", 2, 645, 1119, 26), _region("TOOLS", 2, 71, 56, 548, scroll=scroll),
               _region("UI", 841, 71, 280 if sidebar else 1, 548 if sidebar else 1), _region("HUD", 58, 71, 1, 1), _region("WINDOW", 2, 71, 1119, 600)]
    a3 = NS(type="VIEW_3D", x=2, y=71, width=1119, height=600, regions=regions, spaces=NS(active=NS(show_region_toolbar=True, show_region_ui=sidebar)))
    ap = NS(type="PROPERTIES", x=1124, y=23, width=240, height=527, regions=[_region("NAVIGATION_BAR", 1124, 23, 29, 501)], spaces=NS(active=_Props(tabs_message)))
    win = NS(width=1366, height=697, x=0, y=40, screen=NS(areas=[a3, ap]))
    return NS(context=NS(window=win, window_manager=NS(windows=[win]), preferences=NS(system=NS(ui_scale=1.0, pixel_size=1.0, dpi=72))))


def test_ui_snapshot_lists_visible_regions_only_and_the_toolbar_scroll():
    probe = _addon()
    ui = probe.ui_snapshot(_fake_ui_bpy(sidebar=False, scroll=0.0))
    assert ui["window"] == {"width": 1366, "height": 697}
    v3 = next(a for a in ui["areas"] if a["type"] == "VIEW_3D")
    types = [r["type"] for r in v3["regions"]]
    assert "UI" not in types and "HUD" not in types and "TOOLS" in types               # Blender keeps a hidden region at 1x1: not listed
    assert v3["sidebar_shown"] is False and v3["has_hud"] is False
    tools = next(r for r in v3["regions"] if r["type"] == "TOOLS")
    assert (tools["view_top"], tools["view_bottom"]) == (1.0, -548.0)
    scrolled = probe.ui_snapshot(_fake_ui_bpy(sidebar=True, scroll=223.0))
    v3s = next(a for a in scrolled["areas"] if a["type"] == "VIEW_3D")
    assert "UI" in [r["type"] for r in v3s["regions"]] and v3s["sidebar_shown"] is True
    assert next(r for r in v3s["regions"] if r["type"] == "TOOLS")["view_top"] == -222.0   # scrolled down by 223


def test_properties_tabs_come_from_the_error_message_and_a_different_message_gives_none():
    probe = _addon()
    props = next(a for a in probe.ui_snapshot(_fake_ui_bpy())["areas"] if a["type"] == "PROPERTIES")
    assert props["tabs"] == ["TOOL", "RENDER", "OBJECT", "DATA"] and props["context"] == "OBJECT"
    odd = probe.ui_snapshot(_fake_ui_bpy(tabs_message="something else entirely %s"))   # another Blender phrases it differently: no tabs, no crash
    assert "tabs" not in next(a for a in odd["areas"] if a["type"] == "PROPERTIES")


def _tool(idname, label):
    return NS(idname=idname, label=label)


def test_tool_list_keeps_groups_and_separators_and_survives_a_missing_module(monkeypatch):
    probe = _addon()
    box = _tool("builtin.select_box", "Select Box")
    items = [(_tool("builtin.select", "Tweak"), box), None, _tool("builtin.loop_cut", "Loop Cut"), None]

    class Helper:
        @staticmethod
        def _tool_class_from_space_type(_t):
            return NS(tools_from_context=lambda ctx: iter(items))
    monkeypatch.setitem(sys.modules, "bl_ui", NS())
    monkeypatch.setitem(sys.modules, "bl_ui.space_toolsystem_common", NS(ToolSelectPanelHelper=Helper))
    got = probe.tool_list(NS(context=NS()))
    assert got == [{"group": [{"id": "builtin.select", "label": "Tweak"}, {"id": "builtin.select_box", "label": "Select Box"}]}, {"separator": True},
                   {"group": [{"id": "builtin.loop_cut", "label": "Loop Cut"}]}, {"separator": True}]
    monkeypatch.setitem(sys.modules, "bl_ui", None)                                       # the import fails: None, not an exception
    monkeypatch.delitem(sys.modules, "bl_ui.space_toolsystem_common")
    assert probe.tool_list(NS(context=NS())) is None


def _kmi(idname, key, **props):
    return NS(idname=idname, active=True, to_string=lambda: key, is_user_modified=False, properties=NS(**props))


def _keymap_bpy(items):
    return NS(context=NS(window_manager=NS(keyconfigs=NS(user=NS(keymaps=[NS(name="Mesh", space_type="EMPTY", keymap_items=items)])))))


def test_key_lookup_filters_by_operator_and_properties_and_is_cached(monkeypatch):
    probe = _addon()
    wanted = ["mesh.loopcut_slide", "wm.tool_set_by_id|name=builtin.select_box", "wm.tool_set_by_id|name=builtin.loop_cut"]
    items = [_kmi("mesh.loopcut_slide", "Ctrl R"), _kmi("wm.tool_set_by_id", "T", name="builtin.move"), _kmi("wm.tool_set_by_id", "W", name="builtin.select_box")]
    got = probe.key_lookup(_keymap_bpy(items), wanted)
    assert [k["key"] for k in got["mesh.loopcut_slide"]] == ["Ctrl R"]
    assert [k["key"] for k in got["wm.tool_set_by_id|name=builtin.select_box"]] == ["W"]
    assert got["wm.tool_set_by_id|name=builtin.loop_cut"] == []                            # a tool with no key of its own says so: Loop Cut is reached with Ctrl R, which runs the operator
    assert probe.key_lookup(_keymap_bpy([]), wanted) is got                                # the same request within the TTL is not recomputed
    monkeypatch.setattr(probe.time, "monotonic", lambda: probe._keys_cache["at"] + probe.KEYS_TTL + 1)
    assert probe.key_lookup(_keymap_bpy([]), wanted)["mesh.loopcut_slide"] == []           # after the TTL the keymap is read again


def test_key_lookup_reports_a_keymap_the_learner_changed():
    probe = _addon()
    changed = _kmi("mesh.loopcut_slide", "Alt R")
    changed.is_user_modified = True
    got = probe.key_lookup(_keymap_bpy([changed]), ["mesh.loopcut_slide"])
    assert got["mesh.loopcut_slide"][0]["key"] == "Alt R" and got["mesh.loopcut_slide"][0]["user"] is True


def test_revisions_change_only_when_the_content_changes():
    r = _addon().Revisions()
    a = r.bump("ui", {"w": 1})
    assert r.bump("ui", {"w": 1}) == a and r.bump("scene", {"w": 1}) == 1                  # same content: same number; one counter per part
    assert r.bump("ui", {"w": 2}) == a + 1
    assert r.bump("ui", {"w": 1}) == a + 2                                                 # a change back is still a change


def test_requested_paths_expire_when_nobody_asks_again():
    probe = _addon()
    probe._wanted["properties"].update({"old": 100.0, "fresh": 125.0})
    probe._wanted["keys"].update({"mesh.loopcut_slide": 90.0})
    probe.expire_wanted(130.0)                                                             # TTL 30 s: 100 is exactly at the edge and stays, 90 goes
    assert set(probe._wanted["properties"]) == {"old", "fresh"} and probe._wanted["keys"] == {}
    probe.expire_wanted(131.0)
    assert set(probe._wanted["properties"]) == {"fresh"}


def test_gather_adds_snapshot_v2_and_a_missing_part_leaves_the_rest():
    probe = _addon()
    bpy = _fake_ui_bpy()
    bpy.context.mode = "EDIT_MESH"
    bpy.context.workspace = NS(name="Layout", tools=NS(from_space_view3d_mode=lambda *a, **k: NS(idname="builtin.select_box")))
    bpy.context.selected_objects, bpy.context.active_object = [], None
    bpy.data = NS(objects=[], armatures=[])
    bpy.app = NS(version_string="5.2.2 LTS")
    state = probe.gather(bpy)
    assert state["snapshot_version"] == 2 and state["blender_version"] == "5.2.2 LTS" and isinstance(state["pid"], int)
    assert state["ui"]["window"]["width"] == 1366 and "tools" not in state                # no bl_ui here: the tool list is skipped, nothing else is lost
    assert state["active_tool"] == "builtin.select_box" and state["mode"] == "EDIT_MESH"
    rev = (state["ui_rev"], state["scene_rev"])
    again = probe.gather(bpy)
    assert (again["ui_rev"], again["scene_rev"]) == rev                                    # nothing changed: the same numbers
    bpy.context.window.screen.areas[0].spaces.active.show_region_ui = True
    bpy.context.window.screen.areas[0].regions[2].width = 280
    bpy.context.window.screen.areas[0].regions[2].height = 548
    after = probe.gather(bpy)
    assert after["ui_rev"] == rev[0] + 1 and after["scene_rev"] == rev[1]                  # the sidebar opened: the interface revision moved, the scene one did not


def test_client_sends_keys_and_the_add_on_records_them(tmp_path):
    import json
    import threading
    from http.server import HTTPServer

    from vision.probe_client import read_probe
    probe = _addon()
    probe._state.clear()
    probe._state.update({"mode": "OBJECT", "snapshot_version": 2})
    server = HTTPServer(("127.0.0.1", 0), probe._make_handler("tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info = tmp_path / "probe.json"
    info.write_text(json.dumps({"v": 1, "port": server.server_address[1], "token": "tok"}))
    state = read_probe(info_path=str(info), keys=["mesh.loopcut_slide", "wm.tool_set_by_id|name=builtin.move"])
    server.shutdown()
    assert state["snapshot_version"] == 2                                                  # a v2 state passes through the client unchanged
    assert set(probe._wanted["keys"]) == {"mesh.loopcut_slide", "wm.tool_set_by_id|name=builtin.move"}
