"""The toolbar grounder on REAL frames: the left strip of a captured Blender 5.2.2 window and the add-on's snapshot taken at the same moment (saved by scripts/vision_live_suite.py --save-fixtures), in four situations:
the toolbar at the start, scrolled by two steps, scrolled to the end, and with the active tool scrolled out of view. In each, Blender made one tool the ACTIVE tool, so that tool's cell is drawn in blue: the
ground truth of where the tool really is, which the alignment does not use to find it."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from shared.grounding import CaptureGeometry, Rect  # noqa: E402
from shared.step_record import TargetRef  # noqa: E402
from vision import grounders as g  # noqa: E402
from vision import uimodel  # noqa: E402
from vision.grounders import GroundContext  # noqa: E402
from vision.toolbar import find_cells  # noqa: E402
from vision.verify import gate  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "vision_real"
VIEWPORT_GREY = 63                       # the viewport's own grey in the default theme: the detector compares the cells with it


def load(name):
    strip = cv2.imread(str(FIX / f"{name}.png"))
    st = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    cap = st["capture"]
    iw, ih = cap["image"]
    px = np.full((ih, iw, 3), VIEWPORT_GREY, np.uint8)
    px[:, :strip.shape[1]] = strip
    model = uimodel.parse(st)
    mp = uimodel.mapper_for(model, Rect(*cap["client"]), Rect(*cap["frame"]), iw, ih)
    assert mp.valid
    ctx = GroundContext(model, mp, CaptureGeometry(Rect(*cap["frame"]), iw, ih), px, [], None, st["mode"], None, None, True)
    return ctx, st


def blue(ctx):
    tools = ctx.ui.region("VIEW_3D", "TOOLS")
    vp = ctx.ui.region("VIEW_3D", "WINDOW")
    tb = ctx.mapper.to_frame(tools.rect)
    for c in find_cells(ctx.pixels, ctx.mapper.to_frame(vp.rect)):
        if c.active and tb.y - 2 <= c.rect.y and c.rect.y + c.rect.h <= tb.y + tb.h + 2:
            return ctx.frame_to_screen(c.rect)
    return None


def overlap(a, b):
    x0, y0, x1, y1 = max(a.x, b.x), max(a.y, b.y), min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(x1 - x0, 0) * max(y1 - y0, 0)
    return inter / float(a.w * a.h + b.w * b.h - inter) if inter else 0.0


def ref_for(tool_id):
    from shared import shortcuts
    label = next(t["label"] for rows in shortcuts.catalog()["tools"].values() for r in rows for t in r.get("group", []) if t["id"] == tool_id)
    return TargetRef(kind="tool", label=label, id=tool_id, mode="EDIT_MESH")


@pytest.mark.parametrize("name", ["edit_top", "edit_scrolled_2", "edit_scrolled_6_extrude"])
def test_the_active_tools_cell_is_exactly_where_the_grounder_points(name):
    ctx, st = load(name)
    truth = blue(ctx)
    assert truth is not None
    got = g.ground_tool(ctx, ref_for(st["active_tool"]))
    gated = gate(got)
    assert got.state == g.VISIBLE and gated.ok, (got.state, got.evidence)
    assert overlap(got.rect, truth) >= 0.9, (got.rect, truth)
    assert any("fit the tool list" in e for e in got.evidence) and any("scroll distance puts it there" in e for e in got.evidence)


def test_other_tools_are_placed_by_their_index_not_by_the_position_on_screen():
    """Scrolled by two steps (80 px): tools are found at the cell their index in Blender's list says, so Move, Rotate and Scale (consecutive cells) are one pitch apart, whatever their screen slots are."""
    ctx, st = load("edit_scrolled_2")
    move = g.ground_tool(ctx, ref_for("builtin.move"))
    scale = g.ground_tool(ctx, ref_for("builtin.scale"))
    assert move.state == scale.state == g.VISIBLE and gate(move).ok and gate(scale).ok
    rotate = g.ground_tool(ctx, ref_for("builtin.rotate"))
    assert move.rect.y < rotate.rect.y < scale.rect.y
    assert abs((scale.rect.y - move.rect.y) - 69) <= 6                                  # two pitches (34.5 each) from Move to Scale


def test_a_tool_scrolled_out_of_view_is_said_to_be_out_of_view_with_the_direction():
    ctx, st = load("edit_scrolled_6_select_above")                                      # the active tool (Select Box) is above the visible part
    assert blue(ctx) is None
    got = g.ground_tool(ctx, ref_for("builtin.select_box"))
    assert got.state == g.OFFSCREEN and got.direction == "up" and "scroll the toolbar up" in got.note and got.rect is not None
    loop = g.ground_tool(ctx, ref_for("builtin.loop_cut"))
    assert loop.state == g.VISIBLE and gate(loop).ok                                   # and Loop Cut, which IS in view in this frame, is pointed at


def test_on_a_real_frame_the_old_top_down_pairing_names_the_wrong_tool():
    """What the old code did with the same frame: cell N of the screen = tool N of the list. Scrolled by 2 steps, the blue cell is the 11th detected cell, but Loop Cut is tool 13 of the list."""
    ctx, st = load("edit_scrolled_2")
    tb = ctx.mapper.to_frame(ctx.ui.region("VIEW_3D", "TOOLS").rect)
    cells = find_cells(ctx.pixels, ctx.mapper.to_frame(ctx.ui.region("VIEW_3D", "WINDOW").rect))
    inside = [c for c in cells if tb.y <= c.rect.y <= tb.y + tb.h]
    old_index = next(i for i, c in enumerate(inside) if c.active)
    new = g.ground_tool(ctx, ref_for("builtin.loop_cut"))
    rows = [r for r in __import__("shared.shortcuts", fromlist=["x"]).catalog()["tools"]["EDIT_MESH"] if "group" in r]
    true_index = next(i for i, r in enumerate(rows) if any(t["id"] == "builtin.loop_cut" for t in r["group"]))
    assert old_index != true_index and new.state == g.VISIBLE                          # the screen position is not the tool's place in the list
