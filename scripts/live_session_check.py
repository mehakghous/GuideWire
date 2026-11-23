"""Live check of a whole tutorial session on REAL Blender: the real vision bridge and session engine watch the real screen and probe while the harness inside
Blender makes the learner's changes. Covers the "already true at the start" rule, Previous step and Resume.

    1. blender --factory-startup --python scripts/blender_test_harness.py     (Blender in front, nothing covering it)
    2. python scripts/live_session_check.py
"""
import ctypes, os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path

from app import vision_bridge as vb
from app.db import Database
from app.session_engine import SessionEngine
from app.step_editor import StepEditor
from vision import winplatform as w
from vision.service import VisionService

w.enable_dpi_awareness()
u = ctypes.windll.user32
RUN = os.path.join(os.environ["TEMP"], "blenderrun")
win = [x for x in w.list_windows() if "Blender" in x.title and "Unsaved" in x.title][0]
R = win.rect
n_act = [0]


def front():
    u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0); u.ShowWindow(win.hwnd, 9); u.SetForegroundWindow(win.hwnd)


def wiggle(i):
    u.SetCursorPos(R.x + 760 + (i % 5) * 25, R.y + 620 + (i % 3) * 20)        # over the 3D viewport, away from buttons: keeps Blender's timers running


def wake(seconds):
    t_end = time.time() + seconds
    k = 0
    while time.time() < t_end:                       # input events keep Blender redrawing and running its timers, as a person at the keyboard does
        wiggle(int(time.time() * 5) + k); k += 1; time.sleep(0.2)


def act(label, code):
    n_act[0] += 1
    name = f"t{time.time_ns()}.py"                  # unique every time: the harness cannot rename onto an old file
    p = os.path.join(RUN, name)
    open(p, "w", encoding="utf-8").write(code)
    for i in range(60):
        wiggle(i)
        time.sleep(0.25)
        if os.path.exists(p + ".out"):
            res = open(p + ".out", encoding="utf-8").read()
            print(f"      [learner] {label}: {res[:90]}")
            return
    print(f"      [learner] {label}: NO RESULT")


OVERRIDE = "with bpy.context.temp_override(**view3d_override()):\n    "
DELETE = OVERRIDE + "bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()\n"
ADD_CUBE = OVERRIDE + "bpy.ops.mesh.primitive_cube_add()\n"
EDIT = OVERRIDE + "bpy.ops.object.mode_set(mode='EDIT')\n"
OBJECT = OVERRIDE + "bpy.ops.object.mode_set(mode='OBJECT')\n"
EXTRUDE_TOOL = OVERRIDE + "bpy.ops.wm.tool_set_by_id(name='builtin.extrude_region')\n"
SELECT_TOOL = OVERRIDE + "bpy.ops.wm.tool_set_by_id(name='builtin.select_box')\n"

db = Database(":memory:")
uid = db.add_user("a@x.com", b"h")
tid = StepEditor.from_json_file(Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "shared" / "examples" / "blender_cube_extrude.json").save(db, uid)
eng = SessionEngine.create(db, uid, tid)
eng.start()
bridge = vb.VisionBridge(vb.default_service_factory)
screen_only = VisionService(use_probe=False)
tick_no = [0]
log = []


def watch(label, ticks=3, expect=None):
    """Tick the bridge a few times and print one line per tick."""
    print(f"\n--- {label}")
    last = None
    for _ in range(ticks):
        front(); wiggle(tick_no[0])
        t0 = time.perf_counter()
        step_before = eng.current_step().id if eng.current_step() else "done"
        tk = bridge.tick(eng)
        dt = (time.perf_counter() - t0) * 1000
        tick_no[0] += 1
        step_after = eng.current_step().id if eng.current_step() else "done"
        print(f"   tick {tick_no[0]:2}: step {step_before}->{step_after}  state={tk.state:9} verdict={str(tk.verdict):10} advanced={tk.advanced!s:5} rect={tk.rect}  {dt:4.0f} ms")
        if tk.message and tk.message != "Watching the screen." and tk.message != last:
            print(f"            message: {tk.message}")
            last = tk.message
        log.append((label, step_before, step_after, tk.verdict, tk.advanced))
        wake(1.1)
    return log[-1]


def screen_mode(label):
    screen_only._reader.reset()
    o = screen_only.observe()
    print(f"      screen-only reading ({label}): mode={o.get('mode')} tool={o.get('active_tool') or o.get('active_tool_candidates', '')[:2]}")


print("TUTORIAL: Add a cube and extrude  (4 steps)")
for i, s in enumerate([r for _, r in eng.steps], 1):
    print(f"  s{i:02}: {s.goal}  | expects {[ (p.kind, p.target) for p in s.expected_state]}")

# ----------------------------------------------------------------------------------------- step 1
screen_mode("default scene")
watch("STEP 1 'Add a cube': Blender already has a selected cube at the start (already true)")
act("delete the cube", DELETE)
watch("STEP 1: the learner deleted the cube (not done yet)")
act("add a cube (Add > Mesh > Cube)", ADD_CUBE)
watch("STEP 1: the learner added a cube (the screen sees it happen)")
# ----------------------------------------------------------------------------------------- step 2
watch("STEP 2 'Enter Edit Mode': still in Object Mode")
screen_mode("object mode")
act("enter Edit Mode (Tab)", EDIT)
screen_mode("edit mode")
watch("STEP 2: the learner entered Edit Mode")
# ----------------------------------------------------------------------------------------- previous step
print("\n=== PRESS 'PREVIOUS STEP' (the learner goes back to redo step 2) ===")
eng.back()
print(f"   engine now on {eng.current_step().id}; statuses {eng.statuses()}")
watch("PREVIOUS: Edit Mode is still on, so the old state still holds (must NOT bounce forward)", ticks=3)
act("leave Edit Mode", OBJECT)
watch("PREVIOUS: the learner leaves Edit Mode (screen sees it undone)", ticks=2)
act("enter Edit Mode again", EDIT)
watch("PREVIOUS: the learner enters Edit Mode again (now it counts)", ticks=3)
# ----------------------------------------------------------------------------------------- step 3
watch("STEP 3 'Choose the Extrude Region tool': Select Box is active", ticks=2)
act("choose Extrude Region in the toolbar", EXTRUDE_TOOL)
watch("STEP 3: the learner chose the tool", ticks=3)
# ----------------------------------------------------------------------------------------- resume
print("\n=== RESUME: close GuideWire and open it again (new bridge, session loaded from the database) ===")
eng.back()                                              # back to step 3 so a resume happens on a step whose state ALREADY holds
act("(extrude tool is still the active tool)", "pass\n")
resumed = SessionEngine.load(db, uid, eng.session_id)
bridge2 = vb.VisionBridge(vb.default_service_factory)
print(f"   resumed on {resumed.current_step().id}; statuses {resumed.statuses()}")
for i in range(3):
    front(); wiggle(i)
    tk = bridge2.tick(resumed)
    print(f"   resume tick {i+1}: step {resumed.current_step().id}  verdict={tk.verdict} advanced={tk.advanced}  msg={tk.message[:70]!r}")
    wake(1.1)
print("\nFINAL statuses (original session):", eng.statuses())
adv = [x for x in log if x[4]]
print("steps completed by the screen:", [(a[1], "->", a[2]) for a in adv])
