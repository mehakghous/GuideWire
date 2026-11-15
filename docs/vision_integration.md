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

## What the session screen does now (added with the timer)
- **Watch my screen** switch (on by default, shown only when the vision bridge is available): while a step is active and the screen is shown, a timer looks at the application every half second.
- The look (OCR) runs on a worker thread so the window never freezes; the judging (the database) stays on the main thread. A look that finishes after you pressed Done is thrown away.
- A line under the buttons says in words what GuideWire sees ("Watching the screen.", "Open Blender in front so GuideWire can see it.", "Several places on the screen match; open the menu and it will narrow down.", or what is missing).
- The highlight is Umaima's click-through overlay (`vision/overlay.py`), drawn over the application window; it is hidden from screen capture so OCR never reads it back, and it is closed with the window.
- If GuideWire's own window overlaps the application's, a warning appears with **Move GuideWire to the side** (a strip at the right of the screen, never narrower than its content).
- Done, Skip and Previous step always work by hand; vision can only complete a step the application shows finished.

## Automated tests (no screen, no Windows, no OCR: a fake vision service and a fake overlay)
- `tests/test_app_vision_bridge.py`: the bridge on a real session engine. `tests/test_app_vision_ui.py`: the timer, the message, the highlight, the step advancing in the window, a stale look ignored, the covering warning, a broken overlay.
- Run them: `python -m pytest tests/test_app_vision_bridge.py tests/test_app_vision_ui.py -q`, and everything with `python -m pytest -q`.

## Test it by hand (needs Windows, Blender 5.2 and about 15 minutes)
Do these in order; each says what it proves. Stop at the first that fails and note which.

**Setup (once).** From `C:\dev\GuideWire` with the venv active: (every command below must be run in that same window: a plain `python` outside the venv has none of the packages, and fails with `No module named 'pydantic'`)
```powershell
pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections
python scripts/demo_check.py
```
The line `[ok] the app's screen guidance (vision bridge) can load the vision service and the Windows OCR` must appear. Open **Blender 5.2** with the default layout, English, 1920x1080 at 150% scaling if you can (that is what vision was checked on).

| # | Do | You should see | It proves |
|---|---|---|---|
| M1 | Without Blender open: `python scripts/vision_check.py --seconds 5` | `no_window ... Open Blender in front so GuideWire can see it.` and no crash | missing application is reported, not fatal |
| M2 | Open Blender in front, run `python scripts/vision_check.py --seconds 30` | `watching ... highlight=x,y wxh` once "Add" is visible; the rectangle sits where the Add menu is | the bridge reads the real screen and finds the step's UI path |
| M3 | Same run: click **Add > Mesh > Cylinder** slowly | the highlight moves from Add to Mesh to Cylinder; a cylinder appears; the line shows `advanced=YES` if the step's state was seen (see M4) | live guidance and the check (this is what Umaima's demo does, through the bridge) |
| M4 | `python scripts/vision_check.py --step s05 --seconds 40` and do that step in Blender | `verdict=met ... advanced=YES` when the application shows it done; `verdict=unverifiable` for steps with no checkable state, which never advance | a step is completed only when seen done |
| M5 | `python scripts/vision_check.py --overlay --seconds 30` | a transparent box over Blender; **click through it**: the click reaches Blender; the box never takes focus | the overlay is click-through |
| M6 | Move and resize the Blender window during `--overlay` | the box follows a move; after a resize it is redrawn at the right place | the overlay tracks the window |
| M7 | `python -m app.ui.main_window`, log in, **Add demo tutorials**, open the Blender armature tutorial, **Start session**, press Done until step 2 | under the buttons: the **Watch my screen** switch and a status line that changes with what is on screen | the timer and status line work in the real app |
| M8 | In that session, drag GuideWire over the Blender window | within a second a warning appears: "GuideWire is covering part of the application..." and **Move GuideWire to the side**; click it: GuideWire becomes a strip at the right edge | the covering check and the fix |
| M9a | While a step is highlighted, look at the instruction box (below or beside Blender) and press its **Done**, **Skip** and the **x** | Done and Skip move the session; the x closes the box for this step; the next step shows it again; the checkbox **Show the instruction box next to the application** turns it off for good | the instruction box |
| M9b | Open the Add menu in Blender, then Mesh | the label under the highlight reads "Click Add, then Mesh > Cylinder", then "Click Mesh, then Cylinder", then "Click Cylinder"; the highlight is on that word each time | the highlight follows the menus |
| M9 | Untick **Watch my screen** | the highlight disappears, the status line clears, no more looking; **Done** still works | the learner can switch it off and still use the app |
| M10 | Close Blender in the middle of a session | the line says to open Blender in front; nothing crashes; the session keeps its place | the application going away is handled |
| M11 | Press **Done** while a step is highlighted, then watch the next step | the highlight goes to the next step's path; no double advance | a manual Done and the timer do not fight |
| M12 | In a PowerShell window without the OCR packages (a fresh venv) start the app and open a session | one line naming the missing packages and the pip command; the session works by hand | missing packages are explained |

What to write down if something fails: the line from `vision_check.py`, whether Blender was in front, the Windows scaling, and the Blender version. A highlight in the wrong place usually means the path text does not match what is on screen (check the step's `ui_element` against the real menu).

## Verified so far against a real Blender 5.2.2 LTS (1366x728 window, default layout, no probe add-on)
| Test | Result |
|---|---|
| M1 no Blender open | `no_window ... Open Blender in front so GuideWire can see it.`, no crash |
| M2 find the step's UI path | "Add > Mesh > Cylinder": the "Add" header at screen 259,56 (22x8), checked on a captured image: the box sits exactly on the word. `observe` read mode `OBJECT` and the select-tool group; `verdict=unverifiable` because that step has no checkable state without the probe |
| M5 overlay is click-through | the overlay window has the transparent, no-activate and topmost styles, and the window found at the highlighted point is Blender, not the overlay |
| Windows OCR on a Qt app | main-thread OCR HANGS when a Qt application exists; on a worker thread it works. Fixed in the script; the session screen already used a worker |
| Session screen end to end (offscreen window, real Blender, real OCR) | the 500 ms timer ran, the status line read "Watching the screen.", the highlight was drawn 13 times in 9 s, the event loop stayed responsive, the step did not move |
| Minimized Blender | reported as "not visible" (vision skips minimized windows): keep Blender open, not minimized, with nothing over it |

| Highlight follows the open menus (second, throw-away Blender; a Blender script opened the Add menu and then the Mesh submenu; no mouse input) | the hint went "Click Add, then Mesh > Cylinder" -> "Click Mesh, then Cylinder" -> "Click Cylinder", and each box sat exactly on the word in a captured frame (checked by eye on two frames) |
| Window resized and moved (same instance) | the old position was dropped and the element found again at its new place within 1.3 s |
| Instruction box | rendered with the step goal, how-to lines, hint, Done, Skip and a close button; placement (below, beside, above, inside) and close-for-this-step are unit tested |

**What was wrong in the first live run (reported by Ayesha):** the highlight stayed on "Add" because VisionService reuses its last screen reading while the whole screen changed by less than a small average, and opening a menu changes only a small part of it (up to 5 s stale). The bridge now reads afresh every tick (about 0.3 s). Also added: a label with the next click on the highlight, the instruction box (closeable, with Done and Skip), and window tracking every 200 ms (a move carries the highlight, a resize clears it and looks again).

Still to do by hand (they need your clicks): M3, M7 (the real window), M8, M9, M10, M11, and a look at the instruction box and the highlight label on your own screen (the overlay and the box are hidden from screen capture on purpose, so I could check coordinates but not see them drawn).

## Second live round: what was wrong when the highlight did not reach Mesh and Cylinder, and what a real click flow showed
Found by running `vision_check.py --overlay` against a throw-away second Blender and then by a simulated learner that clicks Add, hovers Mesh (the submenu opens by itself) and clicks Cylinder, doing only what the highlight said, with the real overlay and instruction box on screen.
1. **The script hung and Ctrl-C did nothing.** The main thread (which owns the overlay window) was blocked waiting for the look; the look's worker thread lists windows to find the application, which asks every window for its title, including our overlay, which could not answer: a deadlock. Fixed: the script waits without blocking Qt, gives up after `--look-timeout` seconds, and Ctrl-C works. (The app was not affected: its main thread keeps handling events while a worker reads the screen.)
2. **Stale words.** VisionService reuses its last reading unless the MEAN change of the whole screen is large, so a menu opening (a small area) did not count. The app now reads only what changed, like Umaima's `guide.py`: nothing changed = no OCR, a small area = OCR of that area merged into the words known, a big change or a moved window = the whole window (`tests/test_app_vision_live_service.py`).
3. **The overlay is NOT hidden from capture on this computer** (Windows 10 build 19045): `SetWindowDisplayAffinity` fails, so anything the overlay draws is read back by the OCR. A label under the highlight ("Click Mesh, then Cylinder") made "Mesh" and "Cylinder" appear twice, which made the match ambiguous and the highlight flicker. The highlight now draws a box only; the words are in the instruction box (a real window, which vision masks if it overlaps Blender). **For Umaima**: `vision/winplatform.exclude_from_capture` returns False here, and `show_click_through` ignores that.
4. **Anything covering Blender blanks that part of the screen for vision**, including the Claude app, a terminal or GuideWire's own window (this is the "Blender in front" rule). On a 1366x768 screen with Blender filling it, the instruction box cannot sit outside Blender and goes into its bottom-right corner (masked, so it hides only the timeline area).
5. **The first click on a fresh Blender dismisses the splash screen** instead of opening the menu.
6. **Duplicated words:** the word "Add" also appears in the "Add Cylinder" panel Blender leaves at the bottom after a cylinder was added, so the first part of the path became ambiguous and the highlight was dropped until the menu opened. A limit of finding things by text (Umaima's `find_target`).
7. **The real flow works:** with a fresh Blender, vision found Add in the header, then Mesh in the dropdown, then Cylinder in the submenu opened by hovering Mesh, and the click added a cylinder.

## Not covered, and why
- **Maya and Houdini**: their probes are prototypes never run inside those applications, so M2 to M6 are for Blender only. The bridge itself is application-neutral (`VisionBridge(...).tick(engine, "maya")`).
- **A second monitor or a different scaling**: not tested.
- **The OCR must run on a worker thread**: found on 2026-11-17 against a real Blender: calling `VisionService.ground` on the main thread of a process that has a Qt application HANGS (the Windows OCR needs a different COM apartment from Qt's). The session screen reads the screen in a worker thread, and `scripts/vision_check.py` does the same; anything new that calls vision must too. Check M7 for freezes.

## What is still to do
1. **Run the manual tests above** on the real Blender and fix what they find.
2. **Data**: on the six demo tutorials 61 of 111 steps have a UI path and 63 have an expected state, 39 both; the path text must match what is on screen.
3. **Maya and Houdini**: run their probes inside the applications (Umaima's side), then repeat M2 to M6.
