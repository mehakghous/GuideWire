"""Maya support: the interface model parsed from a REAL Maya 2027.3 probe state (tests/fixtures/vision/maya_2027_state.json, captured with the frame next to it),
finding tools / shelf buttons / menus, the probe's interface snapshot against a fake Maya, and the service and app bridge routing Maya through them."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from shared.grounding import Rect
from vision.mayaui import MayaUi

FIX = Path(__file__).parent / "fixtures" / "vision"
WINDOW_AT_CAPTURE = Rect(190, 56, 1540, 853)        # the Win32 window rect when the frame was captured (the client area is the probe's "window")
CLIENT_AT_CAPTURE = Rect(192, 101, 1536, 806)


@pytest.fixture(scope="module")
def state():
    return json.loads((FIX / "maya_2027_state.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ui(state):
    parsed = MayaUi.parse(state)
    assert parsed is not None
    return parsed


def test_the_real_state_parses_into_tools_shelf_menus_and_regions(ui):
    assert [t.name for t in ui.tools] == ["selectTool", "lassoTool", "paintSelectTool", "moveTool", "rotateTool", "scaleTool"]
    assert ui.active_tool is not None and ui.active_tool.name == "selectTool" and ui.active_tool.context == "selectSuperContext"
    assert ui.shelf_tab == "Polygons" and len(ui.shelf) >= 30 and all(b.title for b in ui.shelf)       # separators are dropped
    assert {"File", "Edit", "Create", "Select", "Mesh", "Edit Mesh"} <= {label for label, _ in ui.menubar}
    assert ui.menu_set is not None and ui.menu_set[:2] == ("Modeling", "modelingMenuSet")
    assert {"toolbox", "shelf", "viewport", "outliner", "channelbox", "timeslider"} <= set(ui.regions)
    assert MayaUi.parse({}) is None and MayaUi.parse({"interface": {}}) is None and MayaUi.parse(None) is None


@pytest.mark.parametrize("query, kind, name", [
    ("Move Tool", "tool", "Move Tool"), ("Toolbox > Rotate", "tool", "Rotate Tool"), ("scale", "tool", "Scale Tool"),
    ("Lasso Tool", "tool", "Lasso Tool"), ("select tool", "tool", "Select Tool"), ("Paint Selection", "tool", "Paint Selection Tool"),
    ("Select", "menu", "Select"), ("Select Tool", "tool", "Select Tool"),                     # a bare "Select" is the menu; "Select Tool" is the tool
    ("Shelf > Polygon Cube", "shelf", "Polygon Cube"), ("Polygon Sphere", "shelf", "Polygon Sphere"),
    ("File", "menu", "File"), ("Mesh", "menu", "Mesh"), ("Rigging menu set", "menu_set", "Modeling"),
])
def test_names_resolve_to_the_right_control(ui, query, kind, name):
    hit = ui.find(query)
    assert hit is not None and hit.kind == kind and hit.name == name and hit.complete


def test_a_menu_path_returns_its_top_menu_as_the_first_step(ui):
    hit = ui.find("Create > Polygon Primitives > Cube")
    assert hit is not None and hit.kind == "menu" and hit.name == "Create" and not hit.complete
    mesh = ui.find("Mesh > Combine")                                    # the real "Mesh" menu, not the "Mesh" inside "Edit Mesh"
    assert mesh is not None and mesh.name == "Mesh" and mesh.rect.w < 70
    assert ui.find("flatten the horizon") is None and ui.find("Toolbox > Teleport") is None and ui.find("") is None


def test_the_move_tool_rectangle_is_the_buttons_own_rectangle(ui):
    r = ui.find("Move Tool").rect
    assert (r.x, r.y, r.w, r.h) == (198, 474, 54, 54)
    assert ui.find("Move Tool").active is False and ui.find("Select Tool").active is True


def test_a_snapshot_of_a_different_window_is_refused(ui):
    assert ui.valid_for(CLIENT_AT_CAPTURE) and ui.valid_for(Rect(193, 102, 1537, 805))
    assert not ui.valid_for(Rect(0, 0, 1920, 1008)) and not ui.valid_for(Rect(300, 101, 1536, 806)) and not ui.valid_for(None)


def test_the_probe_rectangles_match_where_the_screen_text_really_is():
    """Real frame + real probe state: OCR of 'File', 'Create', 'Select' sits on the probe's menu-bar rectangles (checked to a pixel live; 4 px here)."""
    pytest.importorskip("winrt.windows.media.ocr")
    cv2 = pytest.importorskip("cv2")
    from vision.locate import locate
    from vision.ocr import OcrUnavailable, read_text
    img = cv2.imread(str(FIX / "maya_2027_default.png"))
    assert img is not None and img.shape[:2] == (853, 1540)
    try:
        words = read_text(img, 1.5)
    except OcrUnavailable:
        pytest.skip("no OCR language pack")
    ui = MayaUi.parse(json.loads((FIX / "maya_2027_state.json").read_text(encoding="utf-8")))
    assert ui is not None
    for label in ("File", "Create", "Select"):
        hit, probe = locate(words, label), ui.find(label)
        assert hit is not None and probe is not None
        ox, oy = WINDOW_AT_CAPTURE.x + hit.rect.x + hit.rect.w / 2, WINDOW_AT_CAPTURE.y + hit.rect.y + hit.rect.h / 2
        px, py = probe.rect.x + probe.rect.w / 2, probe.rect.y + probe.rect.h / 2
        assert abs(ox - px) <= 4 and abs(oy - py) <= 4, (label, (ox, oy), (px, py))


# ---------------------------------------------------------------------------------- the probe's snapshot, against a fake Maya
sys.path.insert(0, str(Path(__file__).parents[1] / "vision" / "probes"))
import maya_probe  # noqa: E402


class _FakeApi:
    def main_rect(self):
        return {"x": 100, "y": 50, "w": 800, "h": 600}

    def control_rect(self, name):
        return {"ToolBox": {"x": 100, "y": 150, "w": 60, "h": 400}, "Shelf": {"x": 100, "y": 90, "w": 800, "h": 60},
                "modelPanel4": {"x": 300, "y": 200, "w": 400, "h": 300},
                "shelfButton1": {"x": 120, "y": 100, "w": 50, "h": 50}, "separator2": {"x": 170, "y": 100, "w": 10, "h": 50}}.get(name)

    def toolbox(self):
        return [{"name": "moveTool", "tip": "Move Tool", "rect": {"x": 104, "y": 300, "w": 50, "h": 50}, "checked": True},
                {"name": "scaleTool", "tip": "Scale Tool", "rect": {"x": 104, "y": 360, "w": 50, "h": 50}, "checked": False}]

    def menubar(self):
        return [{"label": "File", "rect": {"x": 140, "y": 52, "w": 40, "h": 30}}]

    def combo(self, object_name):
        return ("Rigging", {"x": 110, "y": 100, "w": 120, "h": 28}) if object_name == "menuMode" else None


def _fake_cmds():
    def shelf_button(name, exists=False, q=False, annotation=False, label=False):
        if exists:
            return True
        if name != "shelfButton1":
            return ""
        return "Polygon Cube: Create a polygonal cube" if annotation else "Polygon Cube"
    return NS(getPanel=lambda type: ["modelPanel4"] if type == "modelPanel" else [],
              menuSet=lambda q=True, currentMenuSet=True: "riggingMenuSet",
              shelfTabLayout=lambda name, q=True, selectTab=True: "Polygons",
              shelfLayout=lambda tab, q=True, childArray=True: ["shelfButton1", "separator2"],
              shelfButton=shelf_button)


def test_the_probe_builds_its_interface_snapshot_from_the_widgets():
    snap = maya_probe.interface_snapshot(_FakeApi(), _fake_cmds())
    assert snap["window"]["w"] == 800 and snap["regions"]["toolbox"]["h"] == 400 and snap["regions"]["viewport"]["x"] == 300
    assert snap["toolbox"][0] == {"name": "moveTool", "tip": "Move Tool", "rect": {"x": 104, "y": 300, "w": 50, "h": 50}, "checked": True, "context": "moveSuperContext"}
    assert snap["menu_set"] == {"label": "Rigging", "id": "riggingMenuSet", "rect": {"x": 110, "y": 100, "w": 120, "h": 28}}
    assert snap["shelf"]["tab"] == "Polygons" and snap["shelf"]["buttons"][0]["annotation"].startswith("Polygon Cube:")
    parsed = MayaUi.parse({"interface": snap})
    assert parsed is not None and parsed.find("Polygon Cube") is not None and parsed.find("Move Tool").active


def test_a_failing_interface_does_not_spoil_the_rest_of_the_state():
    class Broken(_FakeApi):
        def main_rect(self):
            raise RuntimeError("no window")
    cmds = NS(ls=lambda **k: [], nodeType=lambda n: "", listRelatives=lambda *a, **k: [], currentCtx=lambda: "selectSuperContext")
    state = maya_probe.gather(cmds, api=Broken())
    assert "interface" not in state and "RuntimeError" in state["interface_error"] and state["active_tool"] == "selectSuperContext"


# ---------------------------------------------------------------------------------- the service and the app bridge route Maya through it
def _patched_service(monkeypatch, state, client=CLIENT_AT_CAPTURE, factory=False):
    from shared.grounding import CaptureGeometry
    from vision import service as svc_mod
    from vision import winplatform
    np = pytest.importorskip("numpy")
    win = NS(rect=WINDOW_AT_CAPTURE, hwnd=1)
    frame = NS(pixels=np.zeros((853, 1540, 3), np.uint8), geometry=CaptureGeometry(WINDOW_AT_CAPTURE, 1540, 853), region=WINDOW_AT_CAPTURE)
    monkeypatch.setattr(svc_mod.VisionService, "_scene", lambda self: (win, frame, frame.pixels, [], None))
    monkeypatch.setattr(winplatform, "client_rect", lambda hwnd: client)
    monkeypatch.setattr(winplatform, "find_window", lambda *a, **k: win)
    monkeypatch.setattr("vision.probe_client.read_probe", lambda **k: state)
    if factory:
        from app.vision_bridge import default_service_factory
        return default_service_factory("maya")
    return svc_mod.VisionService(app="maya")


@pytest.mark.parametrize("factory", [False, True])
def test_the_service_points_at_maya_tools_menus_and_shelf_buttons(monkeypatch, state, factory):
    svc = _patched_service(monkeypatch, state, factory=factory)       # factory=True: the app's own LiveService, which must not fall back to Blender's lookup
    g = svc.ground("Toolbox > Move Tool")
    assert g.grounding.status == "ok" and g.complete and (g.rect.x, g.rect.y, g.rect.w, g.rect.h) == (198, 474, 54, 54) and g.matched == "Move Tool"
    assert g.grounding.x == 198 + 27 and g.grounding.y == 474 + 27
    menu = svc.ground("Create > Polygon Primitives > Cube")
    assert menu.grounding.status == "ok" and not menu.complete and menu.matched == "Create"
    assert svc.ground("Shelf > Polygon Cube").matched == "Polygon Cube"
    assert svc.ground("flatten the horizon").grounding.status == "none"
    assert svc.region_rect("viewport") == Rect(662, 294, 640, 418) and svc.region_rect("toolbar") == Rect(194, 293, 62, 420)


def test_a_moved_or_resized_maya_window_gets_no_highlight_from_an_old_snapshot(monkeypatch, state):
    svc = _patched_service(monkeypatch, state, client=Rect(500, 300, 1200, 700))      # the learner resized Maya after the probe looked
    assert svc.ground("Toolbox > Move Tool").grounding.status == "none"
    assert svc.region_rect("viewport") is None


def test_maya_is_observed_from_its_probe_only(monkeypatch, state):
    svc = _patched_service(monkeypatch, state)
    obs = svc.observe()
    assert obs["active_tool"] == state["active_tool"] and obs["probe"] is True and "mode" not in obs and "workspace" not in obs
