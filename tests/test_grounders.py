"""The grounders and the gate: is the target visible, scrolled out, hidden, in another mode, ambiguous? Frames are drawn with the toolbar laid out as measured on a real Blender window
(tests/vision_fakes.py); the add-on's snapshot comes from the real tool list of the catalog. The same functions are exercised on a live Blender window by scripts/vision_check.py and scripts/vision_uicheck.py."""
from __future__ import annotations

import pytest

pytest.importorskip("cv2")
import vision_fakes as vf  # noqa: E402

from shared.grounding import Rect  # noqa: E402
from shared.step_record import TargetRef  # noqa: E402
from vision import grounders as g  # noqa: E402
from vision.toolbar_align import MARGIN, PITCH, SEPARATOR_EXTRA, sep_flags  # noqa: E402
from vision.verify import GroundCache, gate  # noqa: E402

LOOP_CUT = TargetRef(kind="tool", label="Loop Cut", id="builtin.loop_cut", mode="EDIT_MESH")
FLAGS = None


def expected_top(index, scroll):
    from shared import shortcuts
    flags = sep_flags(["separator" in r for r in shortcuts.catalog()["tools"]["EDIT_MESH"]])
    return 78 + MARGIN + index * PITCH + sum(flags[:index]) * SEPARATOR_EXTRA - scroll          # 78 = the toolbar region's top in the frame


def ctx_for(scroll=0.0, mode="EDIT_MESH", active="builtin.select_box", **kw):
    state, px = vf.tool_world(mode, scroll, active, **kw)
    return vf.make_context([], state, mode, pixels=px), state


# ---------------------------------------------------------------- the toolbar
def test_loop_cut_is_found_where_it_is_when_the_toolbar_is_not_scrolled():
    ctx, _ = ctx_for(0)
    r = g.ground_tool(ctx, LOOP_CUT)
    assert r.state == g.VISIBLE and r.confidence >= 0.9 and len(r.evidence) >= 3
    assert abs(r.rect.y - expected_top(12, 0)) <= 3 and r.rect.x == vf.CELL_X and 30 <= r.rect.h <= 36
    gated = gate(r)
    assert gated.ok and gated.result.rect == r.rect


def test_the_highlight_follows_the_cell_when_the_toolbar_is_scrolled_it_does_not_stay_at_the_old_slot():
    """The old pairing named cell 12 of the screen: with 159 px scrolled that is a different tool, three cells below the real Loop Cut."""
    still, _ = ctx_for(0)
    moved, _ = ctx_for(159)
    a, b = g.ground_tool(still, LOOP_CUT), g.ground_tool(moved, LOOP_CUT)
    assert a.state == b.state == g.VISIBLE
    assert abs((a.rect.y - b.rect.y) - 159) <= 3                       # it moved up by exactly the scroll
    assert abs(b.rect.y - expected_top(12, 159)) <= 3


def test_a_tool_below_the_visible_part_says_scroll_down_and_points_at_the_toolbar_not_at_a_cell():
    ctx, _ = ctx_for(0)
    rip = TargetRef(kind="tool", label="Rip Region", id="builtin.rip_region", mode="EDIT_MESH")
    r = g.ground_tool(ctx, rip)
    assert r.state == g.OFFSCREEN and r.direction == "down" and "scroll the toolbar down" in r.note and "Rip Region" in r.note
    assert r.rect == Rect(2, 78, 56, 548)                              # the region to scroll (screen pixels), never a guessed cell
    assert gate(r).ok                                                  # a region hint from what Blender reported is allowed


def test_once_scrolled_into_view_the_same_tool_is_found_and_the_message_changes():
    rip = TargetRef(kind="tool", label="Rip Region", id="builtin.rip_region", mode="EDIT_MESH")
    before, after = g.ground_tool(ctx_for(0)[0], rip), g.ground_tool(ctx_for(223)[0], rip)
    assert (before.state, after.state) == (g.OFFSCREEN, g.VISIBLE) and after.note == "Click Rip Region in the toolbar."


def test_a_tool_scrolled_off_the_top_says_scroll_up():
    select = TargetRef(kind="tool", label="Tweak", id="builtin.select", mode="EDIT_MESH")
    r = g.ground_tool(ctx_for(223)[0], select)
    assert r.state == g.OFFSCREEN and r.direction == "up" and "scroll the toolbar up" in r.note


def test_a_tool_that_belongs_to_another_mode_is_wrong_context_and_says_which():
    ctx, _ = ctx_for(0, mode="OBJECT", active="builtin.select_box")
    r = g.ground_tool(ctx, LOOP_CUT)
    assert r.state == g.WRONG and "Edit Mode" in r.note and "Object Mode" in r.note and r.rect is None


def test_a_hidden_toolbar_is_reported_not_pointed_at():
    ctx, _ = ctx_for(0, toolbar_shown=False)
    r = g.ground_tool(ctx, LOOP_CUT)
    assert r.state == g.HIDDEN and "toolbar is hidden" in r.note


def test_a_cell_the_detector_missed_is_still_placed_correctly_from_the_cells_around_it():
    state, _ = vf.tool_world("EDIT_MESH", 0, "builtin.select_box")
    px = vf.toolbar_pixels(state, 0, 0, hover_missing=12)              # the hovered cell is lighter: not found (the detector fills the gap in)
    r = g.ground_tool(vf.make_context([], state, "EDIT_MESH", pixels=px), LOOP_CUT)
    assert r.state == g.VISIBLE and abs(r.rect.y - expected_top(12, 0)) <= 4 and gate(r).ok


def test_for_a_moment_after_the_interface_changes_the_toolbar_is_not_pointed_at():
    """Blender scrolls smoothly: for about a second the picture lags what the add-on reports, and a cell could be one place off. No pointer until it has stopped moving."""
    state, px = vf.tool_world("EDIT_MESH", 159, "builtin.select_box")
    ctx = vf.make_context([], state, "EDIT_MESH", pixels=px)
    ctx.settled = False
    r = g.ground_tool(ctx, LOOP_CUT)
    assert r.state == g.UNKNOWN and "still moving" in r.evidence[0] and not gate(r).ok and r.rect is not None     # the toolbar region only
    ctx.settled = True
    assert g.ground_tool(ctx, LOOP_CUT).state == g.VISIBLE


def test_the_blue_cell_disagreeing_with_the_alignment_blocks_the_pointer():
    state, _ = vf.tool_world("EDIT_MESH", 0, "builtin.select_box")
    px = vf.toolbar_pixels(state, 0, 3)                                # blue at the 4th cell, but the add-on says select_box (the 1st) is active
    r = g.ground_tool(vf.make_context([], state, "EDIT_MESH", pixels=px), LOOP_CUT)
    assert r.state == g.UNKNOWN and "NOT where the alignment puts the active tool" in " ".join(r.evidence) and not gate(r).ok


def test_the_blue_cell_agreeing_adds_evidence():
    r = g.ground_tool(ctx_for(0, active="builtin.loop_cut")[0], LOOP_CUT)
    assert any("blue (active) cell is the active tool's" in e for e in r.evidence)


def test_without_the_add_on_a_possibly_scrolled_toolbar_is_never_pointed_at():
    state, px = vf.tool_world("EDIT_MESH", 159, "builtin.select_box")
    ctx = vf.make_context([], None, "EDIT_MESH", pixels=px)
    ctx.layout = type("L", (), {"get": lambda self, n: Rect(2, 78, 1119, 600) if n == "viewport" else None})()
    r = g.ground_tool(ctx, LOOP_CUT)
    assert r.state == g.UNKNOWN and "scrolled" in " ".join(r.evidence) and "Pick Loop Cut in the toolbar" in r.note and not gate(r).ok


# ---------------------------------------------------------------- text controls
def test_the_add_menu_is_looked_for_in_the_header_so_a_panel_called_add_cylinder_cannot_be_mistaken_for_it():
    words = [vf.word("Add", 250, 20, 40, 16, 1), vf.word("Add", 20, 950, 40, 16, 2), vf.word("Cylinder", 70, 950, 80, 16, 2)]       # the "Add Cylinder" panel at the bottom left
    r = g.ground_menu(vf.make_context(words), TargetRef(kind="menu", label="Cylinder", path=["Add", "Mesh", "Cylinder"]))
    assert r.state == g.VISIBLE and r.rect == Rect(250, 20, 40, 16) and r.matched == "Add" and r.note == "Click Add, then Mesh > Cylinder"
    only_panel = g.ground_menu(vf.make_context(words[1:]), TargetRef(kind="menu", label="Cylinder", path=["Add", "Mesh", "Cylinder"]))
    assert only_panel.state == g.NOT_FOUND and only_panel.note == "Open: Add > Mesh > Cylinder"


def test_a_menu_path_advances_as_the_menus_open():
    ref = TargetRef(kind="menu", label="Cylinder", path=["Add", "Mesh", "Cylinder"])
    opened = [vf.word("Add", 250, 20, 40, 16, 1), vf.word("Mesh", 252, 60, 40, 16, 5)]
    r = g.ground_menu(vf.make_context(opened), ref)
    assert (r.matched, r.complete, r.note) == ("Mesh", False, "Click Mesh, then Cylinder")
    last = opened + [vf.word("Cylinder", 330, 62, 70, 16, 6)]
    r = g.ground_menu(vf.make_context(last), ref)
    assert (r.matched, r.complete, r.note) == ("Cylinder", True, "Click Cylinder")


def test_two_equally_good_places_are_ambiguous_and_not_pointed_at():
    words = [vf.word("Add", 250, 20, 40, 16, 1), vf.word("Add", 600, 20, 40, 16, 1)]
    r = g.ground_menu(vf.make_context(words), TargetRef(kind="menu", label="Add", path=["Add"]))
    assert r.state == g.AMBIGUOUS and r.rect is None and not gate(r).ok and not gate(r).recheck


def test_the_mode_dropdown_is_found_by_the_mode_it_shows_and_its_item_once_it_is_open():
    ref = TargetRef(kind="mode", label="Edit Mode", id="EDIT", mode="EDIT_MESH")
    closed = vf.make_context(vf.phrase("Object Mode", 60, 20, 16, 1), None, "OBJECT")
    r = g.ground_mode(closed, ref)
    assert r.state == g.VISIBLE and not r.complete and r.rect == Rect(60, 20, 86, 16) and "then Edit Mode" in r.note
    opened = vf.make_context(vf.phrase("Object Mode", 60, 20, 16, 1) + vf.phrase("Edit Mode", 62, 70, 16, 4), None, "OBJECT")
    r = g.ground_mode(opened, ref)
    assert r.complete and r.rect == Rect(62, 70, 70, 16) and r.note == "Click Edit Mode."
    assert g.ground_mode(vf.make_context([], None, "OBJECT"), ref).state == g.NOT_FOUND


def test_a_properties_field_needs_the_right_tab_then_its_panel_then_its_label():
    ref = TargetRef(kind="property", label="In Front", tab="DATA", panel="Viewport Display", prop="In Front", path=["Data", "Viewport Display", "In Front"])
    wrong = vf.make_context([], vf.tool_state("OBJECT", context="OBJECT"), "OBJECT")
    r = g.ground_property(wrong, ref)
    assert r.state == g.WRONG and "Open the Data tab" in r.note and r.rect is not None and "open tab is OBJECT" in r.evidence[0]
    missing = g.ground_property(vf.make_context([], vf.tool_state("OBJECT", context="OBJECT", tabs=["TOOL", "OBJECT"]), "OBJECT"), ref)
    assert missing.state == g.WRONG and "not available" in missing.note
    state = vf.tool_state("OBJECT", context="DATA")
    both = vf.make_context(vf.phrase("Viewport Display", 1200, 300, 16, 3) + vf.phrase("In Front", 1170, 340, 16, 4), state, "OBJECT")
    r = g.ground_property(both, ref)
    assert r.state == g.VISIBLE and r.complete and "header" in r.evidence[0] and r.confidence >= 0.9
    assert r.rect.x < 1170 and r.rect.x + r.rect.w >= 1232 and r.rect.y == 340                     # the label AND the tick box in front of it, not only the words
    header_only = g.ground_property(vf.make_context(vf.phrase("Viewport Display", 1200, 300, 16, 3), state, "OBJECT"), ref)
    assert header_only.state == g.OFFSCREEN and "Click Viewport Display to open it" in header_only.note          # nothing under it: closed
    closed = g.ground_property(vf.make_context(vf.phrase("Viewport Display", 1200, 300, 16, 3) + vf.phrase("Inverse Kinematics", 1200, 330, 16, 4), state, "OBJECT"), ref)
    assert closed.state == g.OFFSCREEN and "Click Viewport Display to open it" in closed.note and closed.rect == header_only.rect        # the next thing is another panel's header: closed
    opened = g.ground_property(vf.make_context(vf.phrase("Viewport Display", 1200, 300, 16, 3) + vf.phrase("Display As", 1200, 330, 16, 4), state, "OBJECT"), ref)
    assert opened.state == g.OFFSCREEN and opened.direction == "down" and "Scroll down" in opened.note             # its own content follows: open, the field is below what is in view
    nothing = g.ground_property(vf.make_context([], state, "OBJECT"), ref)
    assert nothing.state == g.OFFSCREEN and "Scroll the Properties editor" in nothing.note


def test_a_redo_panel_exists_only_after_the_action_and_is_found_where_blender_reports_it():
    ref = TargetRef(kind="operator_panel", label="Number of Cuts", operator="mesh.loopcut_slide", prop="number_cuts")
    before = g.ground_operator_panel(vf.make_context([], vf.tool_state("EDIT_MESH"), "EDIT_MESH"), ref)
    assert before.state == g.NOT_OPEN and "Do the action first" in before.note and before.rect is None
    state = vf.tool_state("EDIT_MESH", hud=True)
    region_only = g.ground_operator_panel(vf.make_context([], state, "EDIT_MESH"), ref)
    assert region_only.state == g.VISIBLE and region_only.confidence == 0.75 and region_only.rect == Rect(58, 506, 300, 120)
    with_label = g.ground_operator_panel(vf.make_context(vf.phrase("Number of Cuts", 70, 560, 16, 2), state, "EDIT_MESH"), ref)
    assert with_label.rect == Rect(70, 560, 108, 16) and with_label.complete


def test_a_popup_choice_and_a_context_menu_item_are_read_from_the_screen_or_not_open():
    choice = TargetRef(kind="operator_panel", label="With Automatic Weights", operator="object.parent_set", prop="type", id="ARMATURE_AUTO")
    assert g.ground_operator_panel(vf.make_context([]), choice).state == g.NOT_OPEN
    r = g.ground_operator_panel(vf.make_context(vf.phrase("With Automatic Weights", 400, 300, 16, 8)), choice)
    assert r.state == g.VISIBLE and r.complete
    item = TargetRef(kind="context_menu", label="Subdivide", operator="armature.subdivide")
    assert g.ground_context_menu(vf.make_context([]), item).state == g.NOT_OPEN
    twice = [vf.word("Subdivide", 400, 300, 80, 16, 8), vf.word("Subdivide", 900, 700, 80, 16, 9)]
    assert g.ground_context_menu(vf.make_context(twice), item).state == g.AMBIGUOUS


def test_keys_and_viewport_things_have_nothing_on_screen_to_find():
    for kind in ("keys", "viewport"):
        r = g.ground_target(vf.make_context([]), TargetRef(kind=kind, label="Z Scale Handle"))
        assert r.state == g.WORDS and r.rect is None and not gate(r).ok


# ---------------------------------------------------------------- the gate and the cache
def test_the_gate_wants_two_independent_signals_for_a_toolbar_cell_and_a_confident_result():
    one = g.Grounded("tool", g.VISIBLE, Rect(1, 1, 30, 30), 0.99, ("a single signal",))
    assert not gate(one).ok and "2 agreeing signals" in gate(one).reason and gate(one).result.rect is None
    weak = g.Grounded("menu", g.VISIBLE, Rect(1, 1, 30, 30), 0.6, ("text read",))
    assert not gate(weak).ok and gate(weak).recheck                    # nearly: one fresh read before words
    hopeless = g.Grounded("menu", g.VISIBLE, Rect(1, 1, 30, 30), 0.2, ("text read",))
    assert not gate(hopeless).ok and not gate(hopeless).recheck
    good = g.Grounded("menu", g.VISIBLE, Rect(1, 1, 30, 30), 0.9, ("text read",))
    assert gate(good).ok


def test_a_region_hint_is_allowed_with_less_but_not_a_vague_one():
    assert gate(g.Grounded("tool", g.OFFSCREEN, Rect(0, 0, 50, 500), 0.95, ("x",), "scroll", direction="down")).ok
    assert not gate(g.Grounded("property", g.OFFSCREEN, Rect(0, 0, 50, 500), 0.3, ("x",))).ok
    assert gate(g.Grounded("tool", g.HIDDEN, Rect(0, 0, 50, 500), 0.2, ("x",))).ok            # "the toolbar is hidden" is Blender's own report: certain whatever the score


def test_the_cache_keeps_a_result_only_while_nothing_it_depends_on_changed():
    cache = GroundCache()
    r = gate(g.Grounded("menu", g.VISIBLE, Rect(1, 1, 30, 30), 0.9, ("t",)))
    assert cache.lookup("k", (1, 1)) is None
    cache.put("k", (1, 1), r)
    assert cache.lookup("k", (1, 1)) is r and cache.hits == 1
    assert cache.lookup("k", (2, 1)) is None                           # the interface revision moved: forgotten
    assert cache.lookup("k", (1, 1)) is None                           # and not resurrected when the old epoch comes back
    cache.put("k", (2, 1), r)
    cache.forget()
    assert cache.lookup("k", (2, 1)) is None


def test_a_neighbour_in_the_same_header_row_is_another_menu_not_an_item_of_the_first():
    """Seen live in Edit Mode: the header reads `View Select Add Mesh Vertex ...`, and 'Mesh' next to 'Add' was taken for the submenu of Add > Mesh > Cylinder."""
    words = [vf.word("Add", 250, 20, 40, 16, 1), vf.word("Mesh", 300, 20, 44, 16, 1)]
    r = g.ground_menu(vf.make_context(words), TargetRef(kind="menu", label="Cylinder", path=["Add", "Mesh", "Cylinder"]))
    assert r.matched == "Add" and r.note == "Click Add, then Mesh > Cylinder"
    dropdown = words + [vf.word("Mesh", 252, 60, 44, 16, 5)]                              # once the Add menu is open, its Mesh item is below the header
    assert g.ground_menu(vf.make_context(dropdown), TargetRef(kind="menu", label="Cylinder", path=["Add", "Mesh", "Cylinder"])).matched == "Mesh"
