# Typed targets, the Blender interface catalog, shortcuts, state-aware checks (Part B)

Part A made GuideWire able to SEE Blender's interface (add-on snapshot v2, interface model, one screen reader). Part B teaches it what a tutorial's words MEAN there, so that Part C can point at the real
control instead of matching words against pixels. Nothing in Part B changes what the learner sees yet: it is the knowledge layer Part C uses.

## What was added
| Piece | Where | What it does |
|---|---|---|
| Interface catalog | `knowledge/app_vocab/blender_ui.json`, made by `scripts/dump_ui_catalog.py` (`verification/uicatalog_blender.py` runs inside Blender) | Blender 5.2.2's own tools per mode (id, label, operator, cell order), operators with their properties, panels with their Properties tab, menus, Properties tabs, interaction modes, and the default keymap rows. 964 KB. The dump opens a Blender window for a few seconds because the editor keymaps are not loaded in background mode |
| Schema 0.13 | `shared/step_record.py` | `Action.target` (a `TargetRef`: kind tool / menu / mode / property / operator_panel / context_menu / viewport / keys, with ids, mode, tab, panel, operator, candidates, confidence) and the predicate kind `operator_ran`. Additive: old files load, and an older app ignores the new field |
| Resolver | `ingestion/targets.py` | `Action.ui_element` / keys -> `TargetRef`, deterministic and offline, looked up in the catalog. Ambiguity keeps `candidates` and lowers `confidence`; anything that matches nothing stays unresolved |
| Where it runs | `app/session_engine.py` | on every session load, so tutorials saved before this change get targets too. The stored steps are not touched; `load_steps` is unchanged |
| Shortcuts | `shared/shortcuts.py` | keys per operator and mode, valid only in the keymaps of that mode; reverse lookup (what does Ctrl+P do in Object Mode); the learner's own keymap (from the add-on) wins; `advise()` decides whether to show one |
| State-aware checks | `ingestion/evaluator.py` | `operator_ran`; a result that was already true when the step began is not evidence (`entry` state); `implied_state` / `progress`: where the learner is in a step, separating "not true" from "cannot tell" |

## Results on the demo tutorials (`python scripts/resolve_targets.py`)
66 of 70 actions with text resolved over the two Blender tutorials (30 and 40 actions). The four that did not, and why: `Bone` (also a Properties tab name, so ambiguous), `Add IK > To Active Bone`, `Sidebar > Transform > Roll`
(the sidebar is not in the catalog) and `Pose Mode > Bone Constraint properties > Add Bone Constraint > Copy Location`. 14 resolved ones are marked uncertain (confidence below 0.8): viewport items such as handles and joints
(they have no text on screen, so they stay "words only"), key sequences, and Properties paths whose panel Blender draws generically.

Bugs the first run exposed, now fixed and covered by tests: "Edit Mode" resolved to `EDIT_GPENCIL` (the last enum with that name); Loop Cut and Slide > Number of Cuts was not found (it is a property of `mesh.loopcut`, one part of a macro operator);
"Set Parent To" is the title of the Ctrl+P popup, not an operator name Blender lists (resolved through the operator the key press started); `Properties:Object > ...` (tab after a colon); `R 9 0 Enter` is a sequence, not a chord.

## Shortcut rules (`shortcuts.advise`)
1. A shortcut that does not leave Blender in the state the step expects is never shown. `Ctrl+R` runs Loop Cut and Slide but does not make the Loop Cut TOOL active, so for a step whose check is `active_tool = builtin.loop_cut` it is not advised (the old guidance said "press Ctrl+R" there, and the step could then never be seen done). `S` scales but does not select the Scale tool and its handles.
2. It is shown when the target cannot be reached on screen (hidden or scrolled out of the toolbar), or when the tutorial itself uses that key.
3. Otherwise the highlighted control is the guidance.
Versions: the keys come from Blender 5.2.2; another version gets a note saying so. A custom keymap read by the add-on replaces the default one.

## Limits
- Not visible in the app yet: the guidance still uses the old text matching until Part C wires targets in.
- Blender Guru's tutorial material was NOT studied. The shortcut source is Blender's own default keymap (authoritative); a tutorial's own keys come from its steps (`press_keys`). No hand-made shortcut table exists.
- The catalog is Blender 5.2.2 only. Other versions need `scripts/dump_ui_catalog.py` run on them.
- Panels Blender draws generically (constraint panels, the Tool tab, the sidebar) are not in the catalog; paths into them resolve only as far as their tab.
- `operator_ran` needs the add-on's operator history, which was not verified with real clicks (Part A found no way to inject real input). It is used as evidence of progress only, never as an expected state, so a history that turns out to be incomplete cannot complete or block a step.
- The entry-state rule (step 9) needs the bridge to pass the state observed when the step began; that is Part C. Until then such a step is simply not completed automatically (the learner presses Done).

# How to test Parts A and B by hand (Windows, Blender 5.2, about 20 minutes)
Use the project's venv: open PowerShell in `C:\dev\GuideWire`, run `.\venv\Scripts\Activate.ps1`. Every command below runs in that window. Use a Blender you started yourself and leave nothing covering it.

## Setup (once)
1. In Blender: Edit > Preferences > Add-ons > (menu at the top right) Install from Disk > choose `C:\dev\GuideWire\vision\blender_addon\guidewire_probe.py`. If an older GuideWire Probe is listed, remove it first and restart Blender. Tick the checkbox so it is enabled. It must say version 0.2.0.
2. Leave Blender open on the default scene, in front.

## Part A
| # | Do | You should see |
|---|---|---|
| A1 | `python -c "from vision.probe_client import read_probe as r; s=r(); print(s['snapshot_version'], s['ui_rev'], len(s['tools']), s['ui']['window'], s['pid'])"` | `2`, a number, `14` (Object Mode toolbar entries), the window size such as `{'width': 1366, 'height': 697}`, and Blender's process id. If it prints `None`: the add-on is not enabled or Blender was just started (wait 2 seconds) |
| A1b | In Blender, hover the 3D view and press Tab (Edit Mode). Run the same command | tool count `25`, and `ui_rev` higher than before |
| A1c | Press N in the 3D view (sidebar). Run again | `ui_rev` higher again. Press N again: higher once more. Doing nothing and running twice gives the SAME number |
| A2 | `python scripts/vision_uicheck.py --out ui_check.png` | `PASS mapping valid` and `PASS toolbar: N cells found in the pixels, N inside the toolbar region`. Open `ui_check.png`: cyan boxes are the areas, green the regions, red the toolbar cells; they must sit on the real areas, not 31 pixels off |
| A2b | Scroll the toolbar (mouse wheel over the left tool strip) so some tools disappear at the top; open the sidebar; run A2 again | still two PASS lines; the red cells are the tools that remain visible |
| A2c | Drag Blender's window edge to resize it, run A2 again at once, then again after 2 seconds | the first run may print `FAIL mapping NOT valid` (the add-on has not refreshed yet: that is the safety working); after a moment both PASS |
| A3 | Open a browser tab titled "... Blender" (for example blender.org) next to Blender. `python -c "from vision import winplatform as w; w.enable_dpi_awareness(); x=w.find_window('Blender',('blender',)); print(x.title)"` | the Blender title (`... - Blender 5.2.2 LTS`), not the browser |
| A3b | End Blender in Task Manager (not File > Quit), then `python -c "from vision.probe_client import probe_info; print(probe_info('blender'))"` | `None`. Restart Blender: a dict again |
| A4 | `python scripts/vision_bench.py --front --json after.json` (it brings Blender forward) | `probe_running: true` and the stage times; compare them with the baseline table in `docs/vision-research.md` (an unchanged-screen look in the app should now cost about 50 ms, a full read about 0.4 s) |
| A4b | `python scripts/vision_check.py --seconds 60`, then open Add > Mesh in Blender and close it, orbit the 3D view | the printed line keeps updating; while only orbiting it should not re-read the screen constantly |
| A5 | `python -m pytest tests/test_vision_scene.py tests/test_vision_uimodel.py tests/test_vision_window.py tests/test_vision_probe_ui.py -q` | all pass |

## Part B
| # | Do | You should see |
|---|---|---|
| B1 | `python scripts/resolve_targets.py --show` | `blender_armature_...: 29/30`, `blender_leg_ik_...: 37/40`, `TOTAL 66/70 resolved`. In the list: `s06 'Toolbar > Loop Cut' -> tool id=builtin.loop_cut mode=EDIT_MESH`; `s03 'Mode selector > Edit Mode' -> mode id=EDIT mode=EDIT_MESH`; `s11 ... mode=EDIT_ARMATURE`; `s14 'Subdivide > Number of Cuts' -> operator_panel op=armature.subdivide prop=number_cuts`; `s16 'Set Parent To > With Automatic Weights' -> operator_panel op=object.parent_set id=ARMATURE_AUTO` |
| B2 | `python -c "from shared import shortcuts as s; print(s.shortcuts_for('mesh.loopcut_slide','EDIT_MESH')); print(s.shortcuts_for('mesh.loopcut_slide','OBJECT')); print(s.operator_for_keys(['Ctrl','P'],'OBJECT'))"` | `Ctrl R` (keymap Mesh); `[]` (not valid in Object Mode); `['object.parent_set']` |
| B3 | `python -c "from shared import shortcuts as s; a=s.advise(tool_id='builtin.loop_cut', operator='mesh.loopcut_slide', mode='EDIT_MESH', visibility='offscreen', expects_tool='builtin.loop_cut'); print(a.show, a.reason)"` | `False` and a reason saying Ctrl R does not make Loop Cut the active tool. Change `expects_tool=...` to `expects_tool=None`: `True`, "not reachable on screen right now", shortcut Ctrl R |
| B4 | Your own keymap: in Blender Edit > Preferences > Keymap, search "Loop Cut and Slide" in Mesh, set it to Alt R. Then `python -c "import time; from vision.probe_client import read_probe as r; r(keys=['mesh.loopcut_slide']); time.sleep(2.5); print(r(keys=['mesh.loopcut_slide'])['keys'])"` | the list shows `Alt R` with `'user': True`. (The first call only asks; Blender answers on its next timer.) Put the binding back with the Restore button |
| B5 | Catalog is Blender's: `python scripts/dump_ui_catalog.py` (a Blender window opens for a few seconds and closes) then `git status knowledge/app_vocab/blender_ui.json` | prints the version and counts; the file shows no change (same Blender, same data) |
| B6 | Step 9 no longer completes on arrival. In Blender add an armature first (Add > Armature). Start the app (`python -m app.ui.main_window`), log in, Add demo tutorials, open the Blender armature tutorial, Start session, press Done until step 9 ("Add > Armature") | the status line does not say "GuideWire saw this step done" by itself; you finish it with Done. Before Part B it advanced the moment the step began |
| B7 | `python -m pytest tests/test_targets.py tests/test_shortcuts.py tests/test_evaluator_progress.py -q` and then `python -m pytest -q` | all pass (the whole suite takes about 4 minutes) |

What to write down if something fails: the exact command, its output, the Blender version, and whether the add-on shows version 0.2.0.
