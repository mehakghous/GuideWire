# Grounding, verification and step state (Part C)

Parts A and B made GuideWire able to SEE Blender's interface and to know what a tutorial's words MEAN there. Part C connects them: it finds the thing on screen, checks that it really is that thing, and tells the
learner the one next move, in the phase they are actually in.

## The flow of one look (every 0.5 s while a session is watching)
```
add-on (probe)  --ui_rev, scene_rev, regions, tool list, scroll, keys-->  \
screen capture (33 ms) --> SceneReader (OCR only what changed)  ---------> GroundContext
                                                                              |
step.actions[].target (resolved when the session loads)  --> needs_of(step) --+--> grounders (per kind)
                                                                              |        |
                                                  gate (verify.py): two signals, a confidence bar, one re-read
                                                                              |
progress(step, observed) (preconditions, what is already done) ---> assess() ---> StepState(phase, status, hint, rect?)
                                                                              |
                                              SessionEngine.auto_check(observed, entry): the ONLY thing that completes a step
```
| Module | Does |
|---|---|
| `vision/toolbar_align.py` | which toolbar cells are on screen: the detected cells' positions are fitted to the add-on's ordered tool list; the add-on's scroll distance chooses the place, the pixels must fit the list there, and a picture that disagrees with the scroll is refused |
| `vision/grounders.py` | one grounder per target kind. Each answers `visible`, `offscreen` (with direction), `container_hidden`, `wrong_context`, `not_open`, `not_found`, `ambiguous`, `unknown` or `words_only`, with the evidence it rests on. Rectangles are screen pixels |
| `vision/verify.py` | the gate: a pointer needs a confident, consistent result, and two agreeing signals for a toolbar cell; a result that is nearly good earns ONE fresh read of the whole window, then falls back to words. `GroundCache` keeps a result while nothing it depends on changed |
| `app/step_state.py` | the five facts kept apart: instruction shown, target located, target visible AND verified, action performed, action verified. Phases: `blocked` (a precondition is unmet: switch mode first), `hidden` (scrolled out, toolbar hidden, wrong tab, other mode), `locating`, `visible`, `acting` |
| `app/vision_bridge.py` | the scheduler: capture every look (cheap), OCR only what changed, locate again only when the add-on's revisions, the window or the screen's words changed; remembers the state when each step began (`entry`) |
| `app/guidance.py` | now only the hands: keys and the animated mouse/keyboard events. The word lists that guessed what to point at (`SCENE_WORDS`, `REDO_PANELS`, `TOOL_KEYS`) and `plan_for`/`describe` are gone |

## What was wrong, and is now fixed (each reproduced on a real Blender 5.2.2 window first)
| Problem | Cause | Fix |
|---|---|---|
| Loop Cut highlighted three cells too low when the toolbar was scrolled | cells were paired with the tool list from the TOP of the screen | alignment with the list and the add-on's scroll distance; the tool is placed by its index in Blender's own list |
| A tool below the visible part was pointed at, or the learner was told to "scroll" with no hint | the old list assumed every cell was on screen | `offscreen` with direction and how many cells away; the highlight is the toolbar region to scroll; the pointer appears the moment the cell is in view |
| `Add` matched the "Add Cylinder" panel; in Edit Mode `Mesh` next to `Add` was taken for its submenu | text search of the whole window | the first part of a menu path is searched only in the headers Blender reported, and its item must lie below it |
| cell width 1 on some real frames (no cells found) | the column that won sat on the cell's edge | the cell's left edge is found before its width is measured (found by the live suite) |
| a pointer in a place Blender had not finished drawing | Blender scrolls smoothly: the picture lags the add-on for about a second | no pointer until the interface has been unchanged for 1.2 s |
| the previous step's hint and highlight stayed under the new step | state was updated per tick, not per step | one guide per step: everything is cleared in the same call that shows the new goal; a stale look starts the new step's look at once |
| step 9 completed the moment it began | its result was also its start state | an existence result that was already true needs a count that went UP since the step began |
| a pulsing circle at guessed places | `region_rect` guesses | removed: only real controls and Blender-reported regions are highlighted |

## Results on a real Blender (scripts/vision_live_suite.py; last runs: 64 checks 0 failed at 1366x700; 61 of 63 at 1366x520, the 2 being one OCR read that missed the header words)
Ground truth that the code under test does not use: the driver makes a tool the ACTIVE tool, Blender draws its cell in blue, and the rectangle the grounder gives must sit on that blue cell. Measured: 100% overlap in
every scenario where the cell is in view (toolbar at the start, scrolled 2 and 6 steps, sidebar open); a tool scrolled out is reported out of view with the direction (never pointed at); a hidden toolbar and a tool of another
mode are reported as such; the mode dropdown and the Add menu are found inside the 3D view's header; with a 520 px window Loop Cut is below the visible tools and the step says "scroll the toolbar down" (3 cells away, then 1).
A look on a still screen costs a median 64 ms at 1366x700 (max 105) and 117 ms at 1366x520, and every target is reused from the cache (10 of 10); a look that has to read the window (first look, resize) costs 300-500 ms. Before Part C the same still look took about 133 ms because the add-on was read twice and the screen was re-read for what the add-on already says.
Observed flake: in one run one OCR read missed the header words ("Object Mode", "Add"), so the mode dropdown and the Add menu were not found in that look: the result is words only, never a wrong box, and the next look (0.5 s later) reads them again.

## Limits (known, stated)
- The scroll distance chooses the toolbar place, so a picture that lags by MORE than half a cell (17 px) would be mis-indexed; the 1.2 s settle rule and the shape check guard it, but both were tested on Blender 5.2.2 only.
- Properties tabs: the add-on lists the tabs but not where their icons are, so a wrong tab highlights the column of icons and the words say which tab. A collapsed panel cannot be told from a scrolled-out label (Blender does not say).
- The sidebar, constraint panels and the Tool tab are not in the catalog: paths into them resolve only as far as their tab and are found by text.
- Without the add-on the toolbar is pointed at only when every tool of the mode is visible (nothing can be scrolled off); otherwise the words say where to look.
- Pointer for a gizmo handle, a joint or a bone is not attempted: the screen never names them (words only).
- 150% display scaling, two monitors, non-English Blender and other themes are not tested (the manual tests below cover them).
- `operator_ran` (the operator history) was still not verified with real clicks.
- No step of the demo tutorials shows a shortcut yet: the only tool steps need the TOOL active, and `Ctrl+R` would not make it so (the rule from Part B). The learner's own-keymap path is unit tested, not exercised on screen.

# Manual tests (Windows, Blender 5.2): what only a person can check
The automatic checks above were run by me on a throw-away Blender with no real mouse or keyboard input. These need a human, and each one tries to BREAK something. Use the project's venv for commands;
for everything that says "app", run `python -m app.ui.main_window`, log in, Add demo tutorials, open **Blender armature** and press Start. Write down the step number, what you did and what the status line / guide box / highlight showed.

Setup: Blender with the GuideWire Probe add-on 0.2.0 enabled (Edit > Preferences > Add-ons). Keep Blender in front and uncovered; GuideWire's own window may overlap (it is masked) but note it.

| # | Try to break | Do | Pass looks like | A bug looks like |
|---|---|---|---|---|
| M1 | **The Loop Cut scenario with your own hands** | Make the Blender window short (drag the bottom edge up until the toolbar shows about 10 tools). Go to step 6 in the app (press Done to step 5 first, or Skip). Switch Blender to Edit Mode (Tab) | the status line says "Cannot reach Loop Cut yet", the guide box says it is below the visible tools and how many cells away, and a box surrounds the TOOLBAR (not one icon) | a box on one icon while Loop Cut is not visible; no message; the message names the wrong direction |
| M2 | **Scroll until it appears** | In M1, scroll the toolbar with the mouse wheel over it, one notch at a time, slowly then fast | while it moves nothing is pointed at; about a second after it stops the status says "Found Loop Cut" and a box sits exactly on the Loop Cut icon (hover it: the tooltip says Loop Cut). Scrolling back hides the box again | the box lands on the neighbour (Bevel, Knife); the box lags and sits between two icons; it flickers during scrolling |
| M3 | **Click it and the step completes by itself, not before** | Click the Loop Cut tool | the instant Blender shows it active, GuideWire says it saw the step done and moves to step 7. Before the click, hovering over it must not advance anything | advances on hover; advances only after you press Done; stays on step 6 after you picked the tool |
| M4 | **Wrong mode** | On step 6 switch to Object Mode (Tab again) | "This step starts in Edit Mode", the hint says to switch, a box on the mode dropdown. Back in Edit Mode it returns to the Loop Cut guidance by itself | the guidance for the old target stays; no mention of the mode |
| M5 | **Hide the toolbar** | Press T over the 3D view (or View > Toolbar) | the step says the toolbar is hidden and how to show it, with a narrow box at the left edge | a box on a tool that is not there |
| M6 | **Resize while a session runs** | Drag the Blender window edge wider/narrower/shorter, slowly, while on step 6; then maximize | the box follows or clears and re-appears within about 2 seconds; never drawn at the old place after the window stopped | the box stays at the old coordinates; GuideWire freezes; the box is offset by about 30 px (the title bar) |
| M7 | **Open and close panels** | Press N (sidebar), open the timeline bigger, drag the Properties editor wider | highlights stay on the right controls; no stale box over the new layout | boxes shifted or on nothing |
| M8 | **150% display scaling** (Windows Settings > Display > Scale 150%, sign out/in not needed) | repeat M1-M3 | same results. This is the case I could not test | a box off by a fixed factor (1.5x) from the real icon |
| M9 | **Blender's own UI scale** | Blender Preferences > Interface > Resolution Scale 1.4, repeat M2 | same results expected (the add-on reports the scale and the pitch is re-measured from the cells) but untested | wrong icon highlighted, or never found |
| M10 | **Two monitors** | Put Blender on the second monitor, repeat M2 | box on the right icon; guide box appears near Blender | box on the primary monitor |
| M11 | **A different theme / non-English UI** | Preferences > Themes pick a LIGHT theme; or Interface > Language another language, repeat M2 and the Add menu step | untested by me: the cell detector assumes the toolbar cells are darker than the viewport (the default theme), so a light theme should fall back to words ("Look for Loop Cut in the toolbar") with NO box; text menus are not found in another language, also words only | a box on a wrong icon or word. A box on the right icon would be a pleasant surprise: tell me |
| M12 | **Add > Mesh > Cylinder with real clicks** (step 2) | Object Mode. Click Add, hover Mesh, click Cylinder | the box moves Add, then Mesh, then Cylinder, and the hint changes "Click Add, then Mesh > Cylinder" -> "Click Mesh, then Cylinder" -> "Click Cylinder". In Edit Mode the same step must not box the header's Mesh menu | the box jumps to the header's `Mesh` menu; stays on Add |
| M13 | **Redo panel** (step 7, Loop Cut and Slide > Number of Cuts) | Use Loop Cut (Ctrl+R then click twice) | after the cut, a box around the panel at the bottom left of the 3D view and the words about Number of Cuts. Before the cut it says to do the action first | a box at the bottom left before any action |
| M14 | **Properties tab** (step 10, Properties > Data > Viewport Display > In Front) | With an armature selected: first open a different tab, then the Data tab | wrong tab: the icon column is boxed and the words name the Data tab; right tab: the Viewport Display header/label is boxed or the words say to open the panel/scroll | a box on a random icon |
| M15 | **Pop-up choice** (step 16, Ctrl+P) | Select mesh then armature, press Ctrl+P | the pop-up's "With Automatic Weights" entry is boxed; before pressing Ctrl+P the words say the choices appear after the shortcut | box on a word in the viewport |
| M16 | **Rapid navigation** | Press Done, Skip, Back quickly 10 times, including from the small guide box | the status line, hint, keys and box always belong to the step shown; no old hint under a new goal; no duplicate guide boxes | the previous step's hint/keys appear for a moment; two boxes; the app stalls |
| M17 | **Minimize / cover** | Minimize GuideWire (the small guide stays); drag another window over half of Blender; bring it back | the guide keeps working; the covered part is not read (it says to bring Blender forward when most of it is covered). I do NOT know whether the highlight is also drawn over the covering window (the overlay is always on top): note what you see | wrong text read from the covering window; a stuck highlight |
| M18 | **Hover noise** | Move the mouse slowly over the toolbar and over the header menus without clicking | no flicker or jumping of the box (the hovered cell is lighter and used to break detection) | the box jumps to other tools while hovering (this was the old bug) |
| M19 | **No add-on** | Disable the GuideWire Probe add-on, restart Blender, repeat M1 | the toolbar is NOT pointed at unless every tool is visible (words say to scroll); the menu steps still highlight by text | it points at a toolbar cell while scrolled (that is exactly the old bug) |
| M20 | **Long session** | Leave a session watching for 10 minutes while working normally; look at Task Manager | CPU stays low when nothing changes (a look is mostly a screen grab); no memory growth | steady CPU above a few percent while idle, or memory rising |
| M21 | **Blender 5.0 / 4.x** (if you have one) | enable the add-on and repeat M1-M3 | probably works or says it cannot read the toolbar; the shortcut note says the keys come from 5.2.2 | a wrong-icon box |

If a check fails, note: the step, the Blender window size, the Windows scale, the Blender UI scale, whether the add-on was on, and run `python scripts/vision_live_suite.py --save-fixtures fx` right after: it keeps the frame and the add-on's snapshot so the failure can be reproduced without you.

To re-run my checks yourself (about 2.5 minutes, starts its own Blender, simulates no input): `python scripts/vision_live_suite.py` and `python scripts/vision_live_suite.py --size 1366x520`.
