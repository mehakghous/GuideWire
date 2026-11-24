# Demo checklist: the screen-guidance part (Umaima)

Run on the branch `umaima/demo-integration` (main + Maya + the false-completion fix + the display matrix). Checked on 2026-11-24 on real Blender 5.2.3 and Maya 2027.3.

## Before you start (5 minutes)
1. `python scripts/demo_check.py` ends with READY.
2. Blender 5.2: open it, **close the splash screen** (click anywhere outside it), keep the default Layout workspace, Object Mode, window not covered. The splash hides the viewport and the header.
3. Windows: screen lock and sleep off for the demo (a locked PC makes the screen reader see the lock screen). Do not change Windows display scaling during the demo.
4. Start the app: `python -m app.ui.main_window`. Create an account, **Add demo tutorials**, open the Blender cube tutorial, **Start session**, keep **Watch my screen** on.
5. Minimize GuideWire (the small guide box stays on screen) so it does not cover Blender.

## What to show, in order
| Show | What to say | Known limit |
|---|---|---|
| Step 1 "Add > Mesh > Cube": the amber box lands on **Add** in the 3D view header | It reads the screen and Blender's own add-on. It only observes; you do every click | The default scene already has a cube, so step 1 says "already looks done, press Done" instead of completing. This is on purpose: true before the step began is not evidence |
| Delete the cube, then Add > Mesh > Cube | The step completes by itself, because the screen saw it go from not-done to done | |
| Step 2 Edit Mode: press Tab | Completes when the mode really changes (read from the header and the add-on) | |
| **Previous step** then **Resume** | It does not complete the step again just because Edit Mode is still on | |
| Step 3 choose the Extrude Region tool: the box lands on the toolbar cell | The toolbar has no text, so the cell is found from pixels and Blender's tool list | If the toolbar is scrolled so the tool is hidden it says which way to scroll |
| Maya (only if Maya is open with the probe running): Toolbox > Move Tool, Shelf > Polygon Cube, Create menu | Maya reports where its own tool box, shelf and menu bar are, so the box is exact (within 1 px of the screen text) | Needs the probe started (see below). Attribute Editor and Channel Box are not highlighted yet |

## Start the Maya probe (it does not start by itself yet)
Maya must be started with a small MEL file that registers the probe; overriding `MAYA_SCRIPT_PATH` stops Maya from starting. `vision/probes/maya_probe.py` `register()` is what it calls (`sys.path` needs the repo and `vision/probes`). Without the probe Maya steps are followed by hand.

## Be honest about
- Measured on one laptop (1920x1080 at 150%): 10 window and scale conditions, no rectangle on the wrong tool, but 3 wrong "scroll the toolbar" hints and many first-look "not found" results (`docs/display-matrix.md`). Real Windows scaling at 100/125%, a second monitor and a non-English UI are not tested.
- Houdini: Ayesha's probe and grounders are merged, but not run live here (no Houdini licence on this PC).
- Maya typed targets, the Attribute Editor and the Channel Box are not done; a one-word step like "Select" finds nothing.
- Setup that installs the probes, the watching/paused indicator with a tray icon, and a 60-minute performance run are not done.
