"""The interface model and the window-to-screen-to-frame mapping. Numbers come from a real Blender 5.2.2 window (docs/vision-research.md, section 4):
window 1366x697, Win32 client area at screen (0, 31), captured frame (the DWM frame) at (-1, 0) 1368x729, toolbar region 56x548 at window (2, 71)."""
from __future__ import annotations

from shared.grounding import Rect
from vision import uimodel
from vision.uimodel import FrameMapper

STATE = {
    "snapshot_version": 2, "mode": "EDIT_MESH", "active_tool": "builtin.select_box", "ui_rev": 5, "scene_rev": 2, "blender_version": "5.2.2 LTS", "pid": 4576,
    "ui": {"window": {"width": 1366, "height": 697}, "ui_scale": 1.0, "areas": [
        {"type": "VIEW_3D", "x": 2, "y": 71, "width": 1119, "height": 600, "toolbar_shown": True, "sidebar_shown": False, "has_hud": True,
         "regions": [{"type": "TOOLS", "x": 2, "y": 71, "width": 56, "height": 548, "view_top": 1.0, "view_bottom": -548.0},
                     {"type": "WINDOW", "x": 2, "y": 71, "width": 1119, "height": 600}]},
        {"type": "VIEW_3D", "x": 2, "y": 700, "width": 100, "height": 20, "regions": []},
        {"type": "PROPERTIES", "x": 1124, "y": 23, "width": 240, "height": 527, "context": "OBJECT", "tabs": ["TOOL", "OBJECT", "DATA"],
         "regions": [{"type": "NAVIGATION_BAR", "x": 1124, "y": 23, "width": 29, "height": 501}]}]},
    "tools": [{"group": [{"id": "builtin.select", "label": "Tweak"}, {"id": "builtin.select_box", "label": "Select Box"}]}, {"separator": True}, {"group": [{"id": "builtin.loop_cut", "label": "Loop Cut"}]}],
    "keys": {"mesh.loopcut_slide": [{"key": "Ctrl R"}]},
}
CLIENT, FRAME = Rect(0, 31, 1366, 697), Rect(-1, 0, 1368, 729)


def test_parse_reads_areas_regions_tools_and_counters():
    m = uimodel.parse(STATE)
    assert (m.window_w, m.window_h, m.mode, m.ui_rev, m.scene_rev, m.pid) == (1366, 697, "EDIT_MESH", 5, 2, 4576)
    assert m.area("VIEW_3D").rect == Rect(2, 71, 1119, 600)                    # two 3D views: the largest is "the" viewport
    tools = m.region("VIEW_3D", "TOOLS")
    assert tools.rect == Rect(2, 71, 56, 548) and (tools.view_top, tools.view_bottom) == (1.0, -548.0)
    assert m.area("VIEW_3D").has_hud and m.area("PROPERTIES").tabs == ("TOOL", "OBJECT", "DATA") and m.area("PROPERTIES").context == "OBJECT"
    assert m.tool_cell_ids() == [["builtin.select", "builtin.select_box"], ["builtin.loop_cut"]]   # separators are not cells
    assert m.keys["mesh.loopcut_slide"][0]["key"] == "Ctrl R" and m.area("TIMELINE") is None


def test_parse_gives_none_without_an_interface_block_or_when_malformed():
    assert uimodel.parse(None) is None and uimodel.parse({"mode": "OBJECT"}) is None            # an add-on older than snapshot v2
    assert uimodel.parse({"ui": {"window": {"width": 1}, "areas": [{"type": "X"}]}}) is None    # rectangle missing: never a half-built model
    assert uimodel.parse({"ui": "nope"}) is None


def test_a_window_rectangle_is_flipped_and_moved_to_the_client_origin_on_the_screen():
    mp = FrameMapper(1366, 697, CLIENT, FRAME, 1368, 729)
    assert mp.valid
    # the toolbar: bottom-left origin y=71, height 548 -> top edge 697-(71+548)=78 below the client top; the client starts 31 below the screen top
    assert mp.to_screen(Rect(2, 71, 56, 548)) == Rect(2, 31 + 78, 56, 548)
    # the whole window maps onto the whole client area
    assert mp.to_screen(Rect(0, 0, 1366, 697)) == CLIENT


def test_frame_pixels_include_the_title_bar_and_border_of_the_captured_frame():
    mp = FrameMapper(1366, 697, CLIENT, FRAME, 1368, 729)
    f = mp.to_frame(Rect(0, 0, 1366, 697))
    assert f == Rect(1, 31, 1366, 697)                                         # 1 px border on the left, 31 px title bar on top: using the frame's own origin would be 31 px off
    r = Rect(2, 71, 56, 548)
    assert mp.from_frame(mp.to_frame(r)) == r                                  # the round trip returns the same rectangle


def test_a_scaled_image_maps_with_the_same_proportions():
    mp = FrameMapper(1366, 697, CLIENT, FRAME, 684, 365)                       # the frame was downscaled by half
    f = mp.to_frame(Rect(0, 0, 1366, 697))
    assert abs(f.w - 683) <= 1 and abs(f.h - 348.5) <= 1 and abs(f.x - 0.5) <= 1


def test_a_snapshot_of_another_window_size_is_not_valid():
    assert not FrameMapper(1366, 697, Rect(0, 31, 1500, 697), FRAME, 1368, 729).valid      # the learner resized or the scaling differs: the old rectangles mean nothing
    assert not FrameMapper(1366, 697, Rect(0, 31, 1366, 697), Rect(0, 0, 1366, 700), 1366, 700).valid   # the client area does not fit in the frame
    assert FrameMapper(1366, 697, Rect(0, 31, 1367, 698), FRAME, 1368, 729).valid                      # a pixel of rounding is the same window
    assert not FrameMapper(1366, 697, CLIENT, FRAME, 0, 0).valid


def test_mapper_for_uses_the_models_window_size():
    mp = uimodel.mapper_for(uimodel.parse(STATE), CLIENT, FRAME, 1368, 729)
    assert mp.valid and mp.window_h == 697
