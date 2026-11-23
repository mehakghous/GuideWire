"""The bridge between the session and vision: a fake vision service (tests/vision_fakes.py), a real session engine on an in-memory database. No screen, no Windows, no OCR."""
from pathlib import Path

import pytest
import vision_fakes as vf

from app import vision_bridge as vb
from app.db import Database
from app.session_engine import SessionEngine
from app.step_editor import StepEditor

SAMPLE = Path("shared/examples/blender_cube_extrude.json")      # s01 Add > Mesh > Cube, s02 EDIT_MESH, s03 extrude tool, s04 craft
ARMATURE = Path("demo/data/blender_armature_EBgHRd5tJfE.json")
FakeService = vf.FakeService


def _has_cv2() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


needs_cv2 = pytest.mark.skipif(not _has_cv2(), reason="OpenCV is not installed (the toolbar cells are found with it)")


@pytest.fixture
def eng():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(SAMPLE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    yield e
    db.close()


@pytest.fixture
def arm():
    db = Database(":memory:")
    uid = db.add_user("a@x.com", b"h")
    tid = StepEditor.from_json_file(ARMATURE).save(db, uid)
    e = SessionEngine.create(db, uid, tid)
    e.start()
    yield e
    db.close()


def bridge_with(svc, **kw):
    return vb.VisionBridge(lambda app: svc, **kw)


def go_to(engine, n):
    while engine.position < n:
        engine.complete()


def test_the_target_and_the_probe_paths_come_from_the_step(eng):
    from shared.step_record import Action, StatePredicate, Step
    step = Step(id="s9", order=9, goal="Rename the cube", actions=[Action(verb="open_menu", ui_element="  Add > Mesh > Cube  ")],
                expected_state=[StatePredicate(kind="property_equals", target="Cube.location.x", value=2.0), StatePredicate(kind="attribute_exists", target="Cube.my_prop"),
                                StatePredicate(kind="mode", target="EDIT_MESH")])
    assert vb.target_of(step) == "Add > Mesh > Cube"
    assert vb.probe_paths_of(step) == (["Cube.location.x"], ["Cube.my_prop"])


def test_the_probe_is_asked_for_the_keymap_entries_the_steps_tools_and_keys_run(arm):
    go_to(arm, 6)
    assert vb.keys_wanted(arm.current_step()) == ["mesh.loopcut_slide"]            # Toolbar > Loop Cut runs mesh.loopcut_slide: the learner's own key for it is wanted
    svc = FakeService(observed={"mode": "EDIT_MESH"})
    bridge_with(svc).tick(arm)
    assert svc.looks[-1][2] == ["mesh.loopcut_slide"]


def test_the_application_comes_from_the_tutorial(eng):
    assert vb.app_of(eng) == "blender"


def test_no_vision_installed_is_a_state_not_a_crash(eng):
    t = vb.VisionBridge(None).tick(eng)
    assert t.state == "unavailable" and "not set up" in t.message and not t.advanced
    assert not vb.VisionBridge(None).available


def test_a_factory_that_fails_says_why_once_and_does_not_retry(eng):
    calls = []

    def factory(app):
        calls.append(app)
        raise ImportError("No module named 'winrt'")
    b = vb.VisionBridge(factory)
    t = b.tick(eng)
    assert t.state == "unavailable" and "Windows OCR packages" in t.message and "pip install" in t.message
    b.tick(eng)
    assert calls == ["blender"]                                   # not retried every tick
    b.reset()
    b.tick(eng)
    assert calls == ["blender", "blender"]


def test_a_found_menu_root_gives_a_rectangle_a_phase_and_words_and_nothing_advances(eng):
    svc = FakeService(observed={"mode": "OBJECT", "selection_types": []})
    t = bridge_with(svc).tick(eng)
    assert t.state == "watching" and not t.advanced and eng.position == 1
    assert t.phase == "visible" and t.rect == (250, 20, 40, 16) and t.message == "Found Cube" and t.hint == "Click Add, then Mesh > Cube"


def test_what_is_not_on_screen_is_the_locating_phase_with_the_whole_route_in_words(eng):
    t = bridge_with(FakeService(words=[])).tick(eng)
    assert t.rect is None and t.phase == "locating" and t.hint == "Open: Add > Mesh > Cube"


def test_the_step_is_completed_only_when_the_application_shows_it_done(eng):
    eng.complete()                                                  # s01 done by hand; s02 expects EDIT_MESH
    assert eng.current_step().id == "s02"
    svc = FakeService(observed={"mode": "OBJECT"})
    b = bridge_with(svc)
    assert not b.tick(eng).advanced and eng.current_step().id == "s02"
    svc.observed = {"mode": "EDIT_MESH"}
    t = b.tick(eng)
    assert t.advanced and t.state == "done_seen" and t.verdict == "met" and t.phase == "verified" and eng.current_step().id == "s03"
    assert eng.statuses()[1] == "done"


def test_auto_advance_can_be_switched_off_and_the_verdict_is_still_reported(eng):
    eng.complete()
    t = bridge_with(FakeService(observed={"mode": "EDIT_MESH"}), auto_advance=False).tick(eng)
    assert not t.advanced and t.verdict == "met" and eng.current_step().id == "s02"


def test_an_unobservable_step_is_never_advanced(eng):
    eng.complete()
    t = bridge_with(FakeService(observed={})).tick(eng)            # vision could read nothing
    assert not t.advanced and eng.current_step().id == "s02"


def test_an_ambiguous_match_points_at_nothing(eng):
    words = [vf.word("Add", 250, 20, 40, 16, 1), vf.word("Add", 600, 20, 40, 16, 1)]
    t = bridge_with(FakeService(words=words)).tick(eng)
    assert t.rect is None and t.ambiguous and "Several places match" in t.message


def test_a_missing_window_asks_the_learner_to_bring_the_application_forward(eng):
    t = bridge_with(FakeService(found=False)).tick(eng)
    assert t.state == "no_window" and "Open Blender in front" in t.message and not t.advanced


def test_a_vision_failure_during_a_tick_is_reported_and_the_session_is_untouched(eng):
    t = bridge_with(FakeService(boom=RuntimeError("capture failed"))).tick(eng)
    assert t.state == "error" and "RuntimeError" in t.message and "Done" in t.message and eng.position == 1


def test_no_active_step_is_idle(eng):
    while eng.current_step() is not None:
        eng.complete()
    assert bridge_with(FakeService()).tick(eng).state == "idle"


def test_the_real_service_factory_fails_with_words_when_vision_cannot_load(monkeypatch):
    import builtins
    real = builtins.__import__

    def deny(name, *a, **k):
        if name.startswith("vision"):
            raise ImportError("No module named 'winrt.windows.media.ocr'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", deny)
    with pytest.raises(ImportError):
        vb.default_service_factory("blender")
    assert "Windows OCR packages" in vb.explain(ImportError("No module named 'winrt'"))
    assert "Windows only" in vb.explain(OSError("not windows"))


def test_missing_ocr_packages_found_when_the_screen_is_first_read_are_explained_and_not_retried(eng):
    svc = FakeService(boom=ImportError("No module named 'winrt.windows.media.ocr'"))
    b = bridge_with(svc)
    t = b.tick(eng)
    assert t.state == "unavailable" and "Windows OCR packages" in t.message and "pip install" in t.message
    n = len(svc.looks)
    b.tick(eng)
    assert len(svc.looks) == n                                     # remembered: the screen is not read again until reset()


# ---- the toolbar end to end: the add-on's snapshot, a frame with the cells, the real grounders and gate
@needs_cv2
def test_loop_cut_step_points_at_the_tool_when_it_is_in_reach_and_says_scroll_when_it_is_not(arm):
    go_to(arm, 6)
    state, px = vf.tool_world("EDIT_MESH", 0, "builtin.select_box")
    t = bridge_with(FakeService(observed=dict(state), ui_state=state, pixels=px, words=[])).tick(arm)
    assert t.phase == "visible" and t.rect is not None and t.message == "Found Loop Cut" and t.hint.startswith("Click Loop Cut in the toolbar")
    short, px2 = vf.tool_world("EDIT_MESH", 0, "builtin.select_box", tb_h=300)               # a window too short to show it
    t = bridge_with(FakeService(observed=dict(short), ui_state=short, pixels=px2, words=[])).tick(arm)
    assert t.phase == "hidden" and "scroll the toolbar down" in t.hint and t.message == "Cannot reach Loop Cut yet" and t.rect is not None     # the rectangle is the toolbar region to scroll
    assert "Ctrl" not in t.hint                                                                 # step 6 needs the TOOL active: no shortcut that would not select it


def test_in_object_mode_the_loop_cut_step_says_to_switch_mode_first(arm):
    go_to(arm, 6)
    state, px = vf.tool_world("OBJECT", 0, "builtin.select_box")
    words = vf.phrase("Object Mode", 60, 20, 16, 1)
    t = bridge_with(FakeService(observed=dict(state), ui_state=state, pixels=px, words=words)).tick(arm)
    assert t.phase == "blocked" and "starts in Edit Mode" in t.message and t.hint.startswith("Switch to Edit Mode first")


# ---- the scheduler
def test_a_still_screen_costs_one_grounding_not_one_per_look(eng, monkeypatch):
    svc = FakeService(observed={"mode": "OBJECT", "ui_rev": 3, "scene_rev": 1}, epoch=(3, 1, (0, 0, 1920, 1080), 1))
    calls = []
    real = vb.ground_target
    monkeypatch.setattr(vb, "ground_target", lambda ctx, ref: calls.append(ref.label) or real(ctx, ref))
    b = bridge_with(svc)
    for _ in range(5):
        b.tick(eng)
    assert len(calls) == 1 and b.stats.cache_hits == 4 and b.stats.looks == 5                # located once, reused four times
    svc.epoch = (4, 1, (0, 0, 1920, 1080), 1)                                                # the interface changed: located again
    b.tick(eng)
    assert len(calls) == 2


def test_a_nearly_good_result_earns_one_fresh_read_per_state_and_then_falls_back_to_words(arm, monkeypatch):
    from shared.grounding import Rect
    from vision import grounders as g
    go_to(arm, 6)
    state, px = vf.tool_world("EDIT_MESH", 0, "builtin.select_box")
    calls = []

    def nearly(ctx, ref):                                                                     # 0.6: under the bar, over the re-read threshold, however many times it is asked
        calls.append(ref.label)
        return g.Grounded("tool", g.VISIBLE, Rect(10, 10, 30, 30), 0.6, ("one signal", "another"), "Click Loop Cut.", label=ref.label)
    monkeypatch.setattr(vb, "ground_target", nearly)
    svc = FakeService(observed=dict(state), ui_state=state, pixels=px, words=[], epoch=(1, 1, (0, 0, 1366, 697), 1, True))
    b = bridge_with(svc)
    t = b.tick(arm)
    assert svc.resets == 1 and b.stats.rechecks == 1 and len(calls) == 2 and t.rect is None   # asked, re-read the whole window once, asked again: still not good enough, so words and no pointer
    b.tick(arm)
    assert svc.resets == 1                                                                    # not again for the same step and screen state


def test_the_state_when_a_step_began_is_remembered_so_a_result_that_was_already_true_is_not_taken_for_done(arm):
    go_to(arm, 9)                                                                             # Add > Armature, which starts with an armature already in the scene
    svc = FakeService(observed={"probe": True, "mode": "OBJECT", "nodes": ["ARMATURE", "MESH"], "node_counts": {"ARMATURE": 1, "MESH": 1}})
    b = bridge_with(svc)
    assert not b.tick(arm).advanced and arm.current_step().id == "s09"
    assert not b.tick(arm).advanced and arm.current_step().id == "s09"                        # still the same scene: the step did nothing
    svc.observed = {"probe": True, "mode": "OBJECT", "nodes": ["ARMATURE", "MESH"], "node_counts": {"ARMATURE": 2, "MESH": 1}}
    assert b.tick(arm).advanced and arm.current_step().id == "s10"                            # a second armature appeared: that is the action


def test_every_resolved_target_of_the_demo_tutorial_gets_a_state_without_a_crash(arm):
    """Walk all 18 steps with an empty screen: every step produces a phase and words, none raises, none claims a rectangle it has not verified."""
    b = bridge_with(FakeService(observed={}, words=[]))
    seen = []
    while arm.current_step() is not None:
        t = b.tick(arm)
        seen.append((arm.current_step().id, t.phase))
        assert t.state == "watching" and t.hint and t.rect is None
        arm.complete()
    assert len(seen) == 18 and {p for _, p in seen} <= {"locating", "acting", "hidden", "blocked"}


# ---- audit S-1, S-2, S-3, G-1: "already true" is never evidence, on any kind of predicate, in any visit
def test_a_mode_that_was_already_true_when_the_step_started_does_not_complete_it(eng):          # S-3
    eng.complete()                                                  # s02 expects EDIT_MESH
    b = bridge_with(FakeService(observed={"mode": "EDIT_MESH"}))
    t = b.tick(eng)
    assert not t.advanced and eng.current_step().id == "s02" and "already looks done" in t.message
    assert not b.tick(eng).advanced                                 # still true on the next look: still not evidence


def test_a_step_seen_unmet_and_then_met_in_the_same_visit_completes(eng):
    eng.complete()
    svc = FakeService(observed={"mode": "OBJECT"})
    b = bridge_with(svc)
    b.tick(eng)
    svc.observed = {"mode": "EDIT_MESH"}
    assert b.tick(eng).advanced


def test_previous_then_resume_does_not_complete_the_step_again(eng):                            # S-1
    eng.complete()
    svc = FakeService(observed={"mode": "OBJECT"})
    b = bridge_with(svc)
    b.tick(eng)
    svc.observed = {"mode": "EDIT_MESH"}
    assert b.tick(eng).advanced and eng.current_step().id == "s03"
    eng.back()                                                      # Previous: s02 again, and the application is still in Edit Mode
    assert not b.tick(eng).advanced and eng.current_step().id == "s02"
    resumed = SessionEngine.load(eng.db, eng.user_id, eng.session_id)                           # Resume: a new engine on the same session
    assert not b.tick(resumed).advanced and resumed.current_step().id == "s02"


def test_a_jump_back_starts_a_new_visit(eng):
    go_to(eng, 3)
    b = bridge_with(FakeService(observed={"mode": "EDIT_MESH"}))
    eng.jump_to(2)
    assert not b.tick(eng).advanced and eng.current_step().id == "s02"


def test_what_one_session_saw_does_not_leak_into_the_next(eng):                                 # S-2
    eng.complete()
    svc = FakeService(observed={"mode": "OBJECT"})
    b = bridge_with(svc)
    b.tick(eng)
    other = SessionEngine.create(eng.db, eng.user_id, eng.db.get_session(eng.session_id)["tutorial_id"])
    other.start()
    other.complete()
    svc.observed = {"mode": "EDIT_MESH"}
    assert not b.tick(other).advanced                               # the other session never saw the step unmet


def test_maya_and_houdini_are_not_called_out_of_view_when_they_are_simply_not_read(eng):         # G-1
    from vision import apps
    if apps.profile("maya").validated:
        pytest.skip("Maya is read from the screen in this build")
    t = bridge_with(FakeService(found=False)).look(eng.current_step(), "maya")
    assert "Blender only" in t.problem and "in front" not in t.problem and t.problem_state == "unavailable"
