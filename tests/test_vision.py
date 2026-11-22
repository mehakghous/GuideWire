"""Offline tests for vision/: window flags, capture maths, region detection, overlay marks.

Region tests run on synthetic frames shaped like Blender's default layout; they prove the
algorithm, not real-Blender accuracy (that needs recorded frames, see vision/regions.py).
"""
import sys

import pytest

from shared.grounding import GroundingResult, Rect, to_screen
from vision import winplatform
from vision.capture import downscale_size
from vision.overlay import highlight_mark, pointer_mark, to_local, visible_marks

np = pytest.importorskip("numpy")

from vision.capture import Frame  # noqa: E402
from vision.regions import default_layout, detect_layout, region_at  # noqa: E402

GAP = 20


def blender_like(w=1920, h=1080) -> "np.ndarray":
    """Dark gaps between flat areas laid out like Blender's default workspace."""
    img = np.full((h, w, 3), GAP, dtype=np.uint8)

    def fill(x, y, fw, fh, v):
        img[y:y + fh, x:x + fw] = v

    fill(0, 0, w, 60, 50)                 # top bar
    fill(0, 64, 1560, 776, 70)            # viewport
    fill(0, 844, 1560, 208, 45)           # timeline
    fill(1564, 64, w - 1564, 316, 40)     # outliner
    fill(1564, 384, w - 1564, 668, 55)    # properties
    fill(0, 1056, w, h - 1056, 48)        # status bar
    return img


def test_downscale_keeps_aspect_and_never_upscales():
    assert downscale_size(1920, 1080, 1280) == (1280, 720)
    assert downscale_size(800, 600, 1280) == (800, 600)


def test_frame_geometry_round_trips_through_grounding():
    f = Frame(np.zeros((720, 1280, 3), dtype=np.uint8), Rect(100, 50, 1920, 1080))
    r = to_screen(f.geometry, 640, 360)
    assert (r.status, r.x, r.y) == ("ok", 100 + 960, 50 + 540)


def test_click_through_flags_include_transparent_and_no_activate():
    s = winplatform.apply_style_flags(0)
    for flag in (winplatform.WS_EX_TRANSPARENT, winplatform.WS_EX_NOACTIVATE,
                 winplatform.WS_EX_LAYERED, winplatform.WS_EX_TOPMOST):
        assert s & flag


@pytest.mark.skipif(sys.platform == "win32", reason="off-Windows behaviour")
def test_windows_calls_refuse_elsewhere():
    with pytest.raises(winplatform.PlatformUnavailable):
        winplatform.find_window()


def test_detects_default_blender_layout():
    layout = detect_layout(blender_like())
    assert layout.confidence == 1.0
    assert {r.name for r in layout.regions} >= {
        "topbar", "viewport", "outliner", "properties", "timeline", "statusbar"}
    vp = layout.get("viewport")
    assert abs(vp.w - 1560) <= 8 and abs(vp.h - 776) <= 8
    assert region_at(layout, 1700, 100) == "outliner"
    assert region_at(layout, 1700, 600) == "properties"
    assert region_at(layout, 300, 900) == "timeline"
    assert region_at(layout, 300, 400) == "viewport"


def test_scales_with_display_scaling():
    big = np.repeat(np.repeat(blender_like(), 2, axis=0), 2, axis=1)   # 3840x2160, gaps 8px
    layout = detect_layout(big)
    assert layout.confidence == 1.0
    assert abs(layout.get("viewport").w - 3120) <= 16


def test_uniform_image_is_not_split():
    layout = detect_layout(np.full((1080, 1920, 3), 70, dtype=np.uint8))
    assert len(layout.regions) == 1 and layout.confidence < 0.5


def test_default_layout_fallback_is_low_confidence_but_complete():
    layout = default_layout(1920, 1080)
    assert layout.confidence == 0.0 and layout.get("viewport") is not None


def test_pointer_only_for_ok_grounding():
    ok = to_screen(Frame(np.zeros((100, 100, 3), dtype=np.uint8), Rect(0, 0, 100, 100)).geometry, 50, 50)
    assert pointer_mark(ok).rect.contains(50, 50)
    assert pointer_mark(GroundingResult("none")) is None
    assert pointer_mark(GroundingResult("out_of_bounds")) is None


def test_marks_are_localised_and_offscreen_marks_dropped():
    origin = Rect(1000, 500, 800, 600)
    inside = highlight_mark(Rect(1100, 600, 50, 20), "Extrude")
    outside = highlight_mark(Rect(0, 0, 50, 20))
    assert to_local(inside, origin).rect.x == 1100 - 4 - 1000
    assert visible_marks([inside, outside], origin) == [to_local(inside, origin)]


def test_real_blender_5_2_default_layout():
    cv2 = pytest.importorskip("cv2")
    img = cv2.imread("tests/fixtures/vision/blender_5_2_default_1920x1008.png")
    layout = detect_layout(img)
    assert layout.confidence == 1.0
    assert region_at(layout, 800, 400) == "viewport"
    assert region_at(layout, 1750, 150) == "outliner"
    assert region_at(layout, 1750, 500) == "properties"
    assert region_at(layout, 800, 940) == "timeline"
    assert region_at(layout, 800, 995) == "statusbar"
    assert region_at(layout, 800, 50) == "topbar"


def test_window_change_classification():
    from vision.tracker import classify
    a = Rect(100, 100, 800, 600)
    assert classify(None, None).kind == "same"
    assert classify(None, a).kind == "found"
    assert classify(a, None).kind == "lost"
    assert classify(a, a).kind == "same"
    moved = classify(a, Rect(150, 90, 800, 600))
    assert (moved.kind, moved.dx, moved.dy) == ("moved", 50, -10)
    assert classify(a, Rect(100, 100, 900, 600)).kind == "resized"


def test_shift_mark_follows_a_window_move():
    from vision.overlay import shift_mark
    m = highlight_mark(Rect(200, 200, 50, 20), "Extrude")
    s = shift_mark(m, 30, -5)
    assert (s.rect.x, s.rect.y, s.rect.w, s.rect.h, s.label) == (m.rect.x + 30, m.rect.y - 5, m.rect.w, m.rect.h, "Extrude")


# --- locate / observe: pure text logic on hand-made OCR words ---
from vision.locate import locate, parse_path  # noqa: E402
from vision.observe import observe_mode  # noqa: E402
from vision.ocr import Word  # noqa: E402


def _w(text, x, y, line, w=40, h=12):
    return Word(text, Rect(x, y, w, h), line)


def test_parse_path():
    assert parse_path("Add > Mesh > Cube") == ["Add", "Mesh", "Cube"]
    assert parse_path("Object") == ["Object"]


def test_locate_walks_down_a_menu_path():
    closed = [_w("Add", 380, 80, 0), _w("Cube", 218, 190, 1)]       # menu closed; "Cube" is the Outliner object
    r = locate(closed, "Add > Mesh > Cube")
    assert (r.matched, r.depth, r.complete) == ("Add", 0, False)
    assert r.rect.x == 380                                           # not the unrelated Cube

    opened = closed + [_w("Mesh", 420, 120, 2), _w("Plane", 520, 150, 3)]
    assert locate(opened, "Add > Mesh > Cube").matched == "Mesh"
    full = opened + [_w("Cube", 530, 120, 4)]
    r = locate(full, "Add > Mesh > Cube")
    assert (r.matched, r.complete, r.rect.x) == ("Cube", True, 530)


def test_locate_matches_multiword_and_tolerates_ocr_noise():
    words = [_w("Edit", 90, 40, 0), _w("Mode", 140, 40, 0)]
    assert locate(words, "Edit Mode").rect.w == 90
    assert locate([_w("Extrudc", 10, 10, 0)], "Extrude") is not None   # one wrong letter
    assert locate([_w("Cylinder", 10, 10, 0)], "Extrude") is None


def test_locate_flags_ambiguity_and_missing():
    words = [_w("Object", 100, 80, 0), _w("Object", 430, 80, 0)]
    assert locate(words, "Object").alternatives == 1
    assert locate(words, "Bevel") is None
    assert locate(words, "") is None


def test_observe_mode_reads_header_and_leaves_edit_mode_unknown():
    header = Rect(0, 60, 800, 60)
    obj = [_w("Object", 100, 80, 0), _w("Mode", 150, 80, 0)]
    assert observe_mode(obj, header) == "OBJECT"
    edit = [_w("Edit", 100, 80, 0), _w("Mode", 150, 80, 0)]
    assert observe_mode(edit, header) is None                         # object type unknown: do not guess
    assert observe_mode(edit, header, edit_object_type="mesh") == "EDIT_MESH"
    assert observe_mode(edit, Rect(0, 500, 800, 60)) is None          # outside the header


def test_real_frame_ocr_end_to_end():
    pytest.importorskip("winrt.windows.media.ocr")
    cv2 = pytest.importorskip("cv2")
    from vision.observe import observe_blender
    from vision.ocr import OcrUnavailable, read_text
    img = cv2.imread("tests/fixtures/vision/blender_5_2_default_1920x1008.png")
    try:
        words = read_text(img)
    except OcrUnavailable:
        pytest.skip("no OCR language pack")
    layout = detect_layout(img)
    obs = observe_blender(words, img, layout)
    assert obs["mode"] == "OBJECT" and obs["workspace"] == "Layout"
    assert "builtin.select_box" in obs["active_tool_candidates"] and "active_tool" not in obs   # a group, not one tool
    assert locate(words, "Add > Mesh > Cube").matched == "Add"
    assert locate(words, "Modeling").rect.y < 80


def test_guide_text_shows_hidden_steps():
    from vision.guide import guide_marks, hint_text
    from vision.locate import Located
    path = ["File", "Import", "Collada"]
    assert hint_text(path, None) == "Open: File > Import > Collada"
    top = Located(Rect(10, 5, 30, 12), "File", 0, 3, 1.0)
    assert hint_text(path, top) == "Click File, then Import > Collada"
    last = Located(Rect(10, 5, 30, 12), "Collada", 2, 3, 1.0)
    assert hint_text(path, last) == "Click Collada"
    marks = guide_marks(Rect(100, 200, 800, 600), "File > Import > Collada", top)
    assert marks[0].rect.x < 110 + 1 and marks[0].rect.x > 100 and marks[0].label == ""
    assert guide_marks(Rect(0, 0, 10, 10), "File", None) == []


def test_probe_merge_and_roundtrip(tmp_path):
    import importlib.util
    import json
    import threading
    from http.server import HTTPServer
    from pathlib import Path

    from vision.probe_client import merge_observed, read_probe
    assert merge_observed({"mode": "OBJECT", "workspace": "Layout"}, {"mode": "EDIT_MESH", "active_tool": "builtin.select"}) \
        == {"mode": "EDIT_MESH", "workspace": "Layout", "active_tool": "builtin.select", "probe": True}
    assert merge_observed({"mode": "OBJECT"}, None) == {"mode": "OBJECT"}
    assert read_probe(info_path=str(tmp_path / "missing.json")) is None

    spec = importlib.util.spec_from_file_location(
        "guidewire_probe", Path(__file__).parents[1] / "vision" / "blender_addon" / "guidewire_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe._state.update({"mode": "OBJECT", "selection_types": ["MESH"]})
    server = HTTPServer(("127.0.0.1", 0), probe._make_handler("tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info = tmp_path / "probe.json"
    info.write_text(json.dumps({"v": 1, "port": server.server_address[1], "token": "tok"}))
    assert read_probe(info_path=str(info))["selection_types"] == ["MESH"]
    info.write_text(json.dumps({"v": 1, "port": server.server_address[1], "token": "wrong"}))
    assert read_probe(info_path=str(info)) is None        # wrong token is refused
    server.shutdown()


def test_mask_occluders_and_change_detection():
    np = pytest.importorskip("numpy")
    from vision.capture import mask_occluders
    from vision.guide import box_to_rect, changed_box, merge_words, union_box
    from vision.ocr import Word
    px = np.full((100, 200, 3), 255, np.uint8)
    out = mask_occluders(px, Rect(1000, 500, 200, 100), [Rect(1100, 550, 500, 500), Rect(0, 0, 10, 10)])
    assert out[60, 150].sum() == 0 and out[10, 10].sum() == 765 and px[60, 150].sum() == 765
    a = np.zeros((108, 192), np.uint8)
    b = a.copy()
    assert changed_box(a, b) is None
    b[10:20, 30:60] = 200
    assert changed_box(a, b) == (30, 10, 60, 20) and changed_box(None, a) == (0, 0, 192, 108)
    assert union_box(None, (1, 1, 2, 2)) == (1, 1, 2, 2)
    assert union_box((0, 0, 5, 5), (3, 3, 9, 9)) == (0, 0, 9, 9)
    r = box_to_rect((30, 10, 60, 20), 1920, 1080, pad=0)
    assert (r.x, r.y, r.w, r.h) == (300, 100, 300, 100)
    assert box_to_rect((0, 0, 192, 108), 1920, 1080).w == 1920
    old = [Word("File", Rect(310, 110, 20, 10), 1), Word("Keep", Rect(900, 900, 20, 10), 2)]
    new = [Word("Import", Rect(320, 120, 40, 10), 100001)]
    assert [w.text for w in merge_words(old, new, r)] == ["Keep", "Import"]


def test_click_hits_target():
    from vision.guide import click_hits
    box = Rect(100, 200, 50, 20)
    assert click_hits(box, (120, 210)) and not click_hits(box, (99, 210))
    assert not click_hits(box, (120, 220)) and not click_hits(box, None)


def test_ground_located_maps_to_screen():
    from shared.grounding import CaptureGeometry
    from vision.locate import Located
    from vision.service import ground_located
    win = Rect(100, 50, 1000, 500)
    geo = CaptureGeometry(win, 1000, 500)
    g = ground_located(geo, win, Located(Rect(10, 20, 40, 10), "File", 0, 1, 1.0))
    assert g.grounding.status == "ok" and (g.grounding.x, g.grounding.y) == (130, 75)
    assert g.rect == Rect(110, 70, 40, 10) and g.complete and not g.ambiguous
    assert ground_located(geo, win, None).grounding.status == "none"
    amb = ground_located(geo, win, Located(Rect(10, 20, 40, 10), "Object", 0, 2, 1.0, alternatives=1))
    assert amb.ambiguous and not amb.complete
    half = CaptureGeometry(win, 500, 250)          # frame downscaled 2x: coordinates scale back up
    assert ground_located(half, win, Located(Rect(10, 20, 40, 10), "x", 0, 1, 1.0)).rect == Rect(120, 90, 80, 20)


def _real_frame():
    cv2 = pytest.importorskip("cv2")
    from pathlib import Path
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "vision" / "blender_5_2_default_1920x1008.png"))
    assert img is not None
    return cv2, img


def test_toolbar_cells_active_tool_and_locate_on_real_frame():
    cv2, img = _real_frame()
    from vision.regions import detect_layout
    from vision.toolbar import find_cells, locate_tool, modes_matching, observe_tool, tool_groups
    cells = find_cells(img, detect_layout(img).get("viewport"))
    assert len(cells) == len(tool_groups("OBJECT")) == 10          # matches Blender's own tool list
    assert [i for i, c in enumerate(cells) if c.active] == [0]
    assert "builtin.select_box" in observe_tool(cells, "OBJECT")["active_tool_candidates"]
    move = locate_tool(cells, "OBJECT", "Move")
    assert move is not None and move.y == cells[2].rect.y and locate_tool(cells, "OBJECT", "Extrude Region") is None
    assert modes_matching(cells, "OBJECT")[0] == "OBJECT"
    assert observe_tool(cells[:3] * 8, "OBJECT") == {}              # more cells than tools: say nothing


def test_toolbar_detection_is_scale_independent():
    cv2, img = _real_frame()
    from vision.regions import detect_layout
    from vision.toolbar import find_cells
    big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cells = find_cells(big, detect_layout(big).get("viewport"))
    assert len(cells) == 10 and cells[0].active


def test_cut_off_toolbar_matches_longer_modes():
    from vision.toolbar import Cell, modes_matching, observe_tool
    cells = [Cell(Rect(16, 100 + 50 * i, 58, 47), i == 9) for i in range(10)]   # edit-mode toolbar cut off at 10 cells
    modes = modes_matching(cells, "EDIT_MESH")
    assert modes[0] == "EDIT_MESH" and "OBJECT" in modes
    assert observe_tool(cells, "EDIT_MESH")["active_tool_candidates"][0] == "builtin.extrude_region"


def test_find_target_falls_back_to_toolbar_for_icon_only_tools():
    cv2, img = _real_frame()
    pytest.importorskip("winrt.windows.media.ocr")
    from vision.ocr import read_text
    from vision.service import find_target
    words = read_text(img)
    move = find_target(words, img, "Move")
    assert move is not None and move.rect.x < 100 and move.complete
    assert find_target(words, img, "Toolbar > Add Cube").rect.y > move.rect.y


def test_a_hovered_toolbar_cell_that_is_not_found_does_not_cut_the_column_in_two():
    from vision.toolbar import _longest_chain
    full = [(118 + 36 * i, 151 + 36 * i) for i in range(12)]
    hovered = full[:4] + full[5:]                      # the cell under the mouse is lighter and is not found
    out = _longest_chain(hovered)
    assert len(out) == 12 and out[0] == full[0] and out[4][0] - full[4][0] <= 6
    assert len(_longest_chain(full[:3] + full[6:])) == 6          # three missing cells are not guessed: the longer half wins as before


def test_an_open_mode_dropdown_does_not_change_the_mode_that_is_read():
    """The dropdown's list shows every mode under the button; the current mode is the button (the topmost mode name)."""
    from vision.observe import observe_mode
    from vision.ocr import Word

    def words(*rows):
        out, line = [], 0
        for text, y in rows:
            x = 60
            for part in text.split():
                out.append(Word(part, Rect(x, y, len(part) * 9, 14), line))
                x += len(part) * 9 + 6
            line += 1
        return out
    header = Rect(0, 73, 1575, 60)
    for current, truth in (("Edit Mode", "EDIT_MESH"), ("Object Mode", "OBJECT"), ("Sculpt Mode", "SCULPT")):
        closed = words((current, 80))
        opened = words((current, 80), ("Object Mode", 118), ("Edit Mode", 140), ("Sculpt Mode", 162))
        assert observe_mode(closed, header, "MESH") == observe_mode(opened, header, "MESH") == truth
    assert observe_mode(words(("Edit Mode", 80), ("Object Mode", 118)), header) is None        # Edit Mode without an object type: not observable, never Object Mode
    assert observe_mode(words(("Object Mode", 600)), header) is None                            # outside the header strip


def test_edit_mode_on_a_mesh_is_read_from_the_header_menus_alone():
    from vision.observe import infer_edit_object_type, observe_mode
    from vision.ocr import Word

    def row(*names, y=80):
        out, x = [], 160
        for i, n in enumerate(names):
            out.append(Word(n, Rect(x, y, len(n) * 9, 14), 1))
            x += len(n) * 9 + 18
        return out
    header = Rect(0, 73, 1575, 60)
    edit_header = [Word("Edit", Rect(60, 80, 36, 14), 0), Word("Mode", Rect(100, 80, 36, 14), 0)] + row("View", "Select", "Add", "Mesh", "Vertex", "Edge", "Face", "UV")
    object_header = [Word("Object", Rect(60, 80, 54, 14), 0), Word("Mode", Rect(118, 80, 36, 14), 0)] + row("View", "Select", "Add", "Object")
    assert infer_edit_object_type(edit_header, header) == "MESH" and infer_edit_object_type(object_header, header) is None
    assert observe_mode(edit_header, header, infer_edit_object_type(edit_header, header)) == "EDIT_MESH"
    assert observe_mode(object_header, header, infer_edit_object_type(object_header, header)) == "OBJECT"


def test_the_mode_is_read_from_the_header_row_not_from_a_guessed_layout():
    """A wrong layout (the capture includes the title bar) puts the workspace tabs in the 'header': Texture Paint is a TAB name, not a mode."""
    from vision.observe import header_row, observe_mode
    from vision.ocr import Word

    def at(text, x, y, line=0):
        return Word(text, Rect(x, y, len(text) * 9, 14), line)
    tabs = [at("Layout", 397, 57, 1), at("Texture", 791, 57, 1), at("Paint", 857, 57, 1), at("Shading", 925, 57, 1)]
    header = [at("Edit", 109, 96, 2), at("Mode", 142, 96, 2), at("View", 323, 96, 2), at("Select", 384, 96, 2), at("Add", 455, 96, 2), at("Mesh", 509, 96, 2)]
    dropdown = [at("Object", 109, 130, 3), at("Mode", 160, 130, 3), at("Sculpt", 109, 152, 4), at("Mode", 160, 152, 4)]
    timeline = [at("Playback", 80, 900, 5), at("View", 200, 900, 5), at("Marker", 260, 900, 5)]           # View without Select: not the viewport header
    words = tabs + header + dropdown + timeline
    row = header_row(words)
    assert row is not None and row.y <= 96 <= row.y + row.h and not (row.y <= 57 <= row.y + row.h) and not (row.y <= 130 <= row.y + row.h)
    wrong_layout_strip = Rect(0, 55, 1574, 60)                                       # what a guessed layout gives: covers the tabs
    assert observe_mode(words, wrong_layout_strip, "MESH") == "PAINT_TEXTURE"         # why the strip must not be trusted ...
    assert observe_mode(words, row, "MESH") == "EDIT_MESH"                           # ... and the row is
    assert header_row(tabs + dropdown + timeline) is None


def test_real_edit_mode_frame_is_read_as_edit_mesh_with_a_wrong_default_layout():
    pytest.importorskip("winrt.windows.media.ocr")
    cv2 = pytest.importorskip("cv2")
    from vision.observe import observe_blender
    from vision.ocr import OcrUnavailable, read_text
    from vision.regions import default_layout
    img = cv2.imread("tests/fixtures/vision/blender_5_2_edit_mode_1920x1008.png")
    assert img is not None
    try:
        words = read_text(img, 1.5)
    except OcrUnavailable:
        pytest.skip("no OCR language pack")
    obs = observe_blender(words, img, default_layout(img.shape[1], img.shape[0]))      # the layout guess that failed live (top bar 55 px)
    assert obs.get("mode") == "EDIT_MESH", obs


def test_a_hover_tooltip_over_the_header_does_not_change_the_mode_read_from_a_real_frame():
    """A real Edit Mode capture with Blender's tooltip ("Sets the object interaction mode.") showing under the mode button."""
    pytest.importorskip("winrt.windows.media.ocr")
    cv2 = pytest.importorskip("cv2")
    from vision.observe import observe_blender
    from vision.ocr import OcrUnavailable, read_text
    from vision.regions import default_layout
    img = cv2.imread("tests/fixtures/vision/blender_5_2_edit_mode_tooltip_1920x1008.png")
    assert img is not None
    try:
        words = read_text(img, 1.5)
    except OcrUnavailable:
        pytest.skip("no OCR language pack")
    assert observe_blender(words, img, default_layout(img.shape[1], img.shape[0])).get("mode") == "EDIT_MESH"
