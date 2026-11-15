# Joining the step pipeline to the vision part

The app (Mehak), the steps (Ayesha) and vision (Umaima) meet in one place: the session. Vision only observes; it never clicks or types.

## What exists
| Piece | Where | What it gives |
|---|---|---|
| Steps with a UI path and an expected state | `shared/step_record.py`, `ingestion/` | `Action.ui_element` ("Add > Armature > Single Bone") and `Step.expected_state` predicates |
| Judging a step against an observed state | `ingestion/evaluator.py`, `app/session_engine.py` (`check`, `auto_check`) | completes a step only when every predicate is seen to hold; unobservable never advances |
| Where to point and what state the app is in | `vision/service.py` (`VisionService.ground`, `.observe`) | a screen rectangle; the dict the evaluator reads |
| **The bridge (new)** | `app/vision_bridge.py` | one `tick(engine)` per look: asks `ground` for the step's UI path and `observe` for its state, calls `auto_check`, returns a `Tick` (state, message, rectangle to highlight, advanced) |

## What the bridge guarantees (tested in `tests/test_app_vision_bridge.py`, with a fake vision service)
- it never raises: no vision installed, missing OCR packages, not Windows, application window not found, a capture error are all states with a plain message;
- a step advances only through `SessionEngine.auto_check` (every predicate met, none unobservable); `auto_advance=False` reports the verdict without moving;
- an ambiguous match points at nothing; a missing window asks the learner to bring the application forward;
- the application (blender, maya, houdini) is read from the tutorial.

## What is still to do
1. **Session screen** (Mehak's file): a `QTimer` that calls `bridge.tick(engine)` about twice a second, shows `Tick.message`, and draws or clears the overlay from `Tick.rect` (Umaima's `vision/overlay.py`); agree the change with her first.
2. **Overlay inside the app's event loop**: `vision.guide.run_guide` owns its own Qt loop; the app needs the overlay as a widget it controls.
3. **Run it for real**: install the Windows OCR packages (`pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections`), open Blender 5.2 at the default layout, and try the Blender armature demo tutorial step "Add > Armature > Single Bone".
4. **Data**: on the six demo tutorials 61 of 111 steps have a UI path and 63 have an expected state, 39 both; the path text must match what is on screen.
5. **Maya and Houdini**: their probes are prototypes never run inside those applications, so the first working demo is Blender.
