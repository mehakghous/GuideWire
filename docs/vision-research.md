# Vision research notes (Umaim, FYP-1)

Covers three written deliverables: what can be detected in each application, the feasibility checks, and the
literature behind the approach. Status labels: **Tested** = run on real data in this project; **Designed** =
reasoned from documentation, not run; **Unverified** = a claim to check before it is relied on.

## 1. Detectable operations and UI elements

How things are detected: **screen** = OCR text and pixel rules (`vision/`), **probe** = read-only code inside the
application (`vision/blender_addon`, `vision/probes`). The screen sees what is drawn; the probe sees scene state.

### Blender 5.2.3 (Tested: Object Mode, 1920x1080 at 150% scaling, default theme, English)
| Thing | Source | Notes |
|---|---|---|
| Areas: viewport, outliner, properties, timeline, top bar, status bar | screen | gap-colour region split; full confidence on the real frame |
| Menu bar and open menu items (File, Edit, Add, Object, ...) | screen (OCR) | the deepest visible part of a path such as `Add > Mesh > Cube`; closed submenus are not visible |
| Left toolbar tools | screen (pixels) + `toolbars.json` | 10 cells in Object Mode, named from Blender's own tool list; a cell holding several tools reports the group |
| Interaction mode, workspace | screen (OCR, tab colour) or probe | Edit Mode needs the object type, so the screen leaves it out; the probe gives it |
| Active tool, selection types, active object | probe | exact (`builtin.select_box` seen live) |
| Node types and counts, object and bone names | probe | `ARMATURE`, `BONE`, `CONSTRAINT_IK`, `MODIFIER_*` as in `verification/collect_blender.py` |
| Property values and attribute existence | probe | for paths the active step asks for; attribute/index access only |
| What the learner just did | probe (`window_manager.operators`) | Designed: not checked live, Blender records only operators run from its own interface |
| Other modes' toolbars (Edit, Sculpt, Paint, Pose...) | `toolbars.json` | Designed: tool lists dumped from Blender, never matched against a real capture |
| Header and panel icons, sliders, node-editor wires | none | not detected |

### Maya 2027 (Designed: not installed on the development machine)
| Thing | Source | Notes |
|---|---|---|
| Menu bar, menu items, Script Editor, Attribute Editor labels, Channel Box names | screen (OCR) | same text pipeline; layout naming not built (`apps.py` marks it unvalidated) |
| Shelf buttons, tool-box icons | none yet | icon-only; a toolbar-style cell detector could be adapted once real frames exist |
| Outliner and Node Editor / Hypergraph regions | screen (region split, OCR labels) | node boxes carry text labels; connections are not read |
| Node types, counts, names, selection, current tool, attribute values | probe (`maya.cmds`) | prototype in `vision/probes/maya_probe.py`, tested against a fake `cmds` only |
| What the learner just did | probe (Script Editor echo) | prototype; points Maya's history log at a temp file and switches it off on unregister |

### Houdini 22.0.466 Apprentice (Designed: not installed on the development machine)
| Thing | Source | Notes |
|---|---|---|
| Menus, parameter labels, node labels in the network editor | screen (OCR) | node names are readable text; wires are not |
| Network editor, parameter pane, scene viewer, timeline regions | screen (region split) | naming not built |
| Node types by name and label, node names, selection, viewer state, parameter values | probe (`hou`) | prototype in `vision/probes/houdini_probe.py`, tested against a fake `hou` only |
| What the learner just did | probe (`hou.undos.undoLabels()`) | prototype |

## 2. Feasibility checks

| Check | Finding | Status |
|---|---|---|
| `bpy` state access | Works: node counts, names, property reads and the active tool were read from a real Blender 5.2.3 window, headless and in the GUI | **Tested** |
| Blender idle behaviour | An idle, unfocused Blender runs its Python timers only about every 10 s; with mouse activity they run every 0.5 s | **Tested** |
| Capture, layout, OCR cost on a student-class laptop | Intel i7-8650U, 15.9 GB RAM, UHD 620 (no discrete GPU), one 1920x1008 Blender window. Median over 4–8 runs: capture 89 ms, layout 225 ms, toolbar 66 ms, full-frame OCR 957 ms (earlier, quieter run: about 510 ms), OCR of a changed 500x400 area 133 ms. One machine, one resolution: not a general result | **Tested** |
| Vision grounding on dense editors | Text paths work on Blender's dense UI; not tried on Maya's or Houdini's node graphs | Designed |
| Maya education terms | Autodesk's education plan gives eligible students free access, renewed yearly while eligible, for educational use only; commercial work needs a commercial subscription. Sources disagree on age and eligibility, so check the official page for the region | **Unverified** (secondary sources) |
| Houdini Apprentice terms | SideFX: non-commercial projects only, may not be used in the same pipeline as commercial Houdini; scenes save as `.hipnc`, assets `.hdanc`, USD as `.usdnc`; opening such files in a commercial build downgrades them to non-commercial; renders other than `.picnc` are watermarked | Checked against SideFX pages (see sources) |
| Apprentice export formats | One third-party post says FBX export works; a SideFX forum post about the Indie tier says FBX and Alembic were removed. Unresolved: matters for the FBX/USD oracle comparison | **Unverified** |
| Apprentice render size | SideFX FAQ says 1920x1080; a blog says 1280x720. Trust SideFX; irrelevant to our read-only use | Unverified |
| `maya.cmds` state access from a probe | `maya.utils.executeInMainThreadWithResult` runs a callable on Maya's main thread and blocks the caller until idle; it needs idle events, so it does not work in batch (`mayapy`) mode. Forum reports of lock-ups when calls are nested or in tight loops. The probe therefore only works in an interactive Maya session | Designed (documentation, not run) |
| `hou` state access from a probe | `hdefereval.executeInMainThreadWithResult` is the equivalent; no official SideFX reference found, one forum report of a freeze. Needs a first test in a real session | **Unverified** |
| FBX / USD oracle normalisation | `verification/oracle.py` normalises units, up axis (Z-up Blender, Y-up Maya and Houdini) and frame rate, and is tested on synthetic scenes; no real exported files compared yet | Tested (synthetic only) |

## 3. Literature behind the approach

Cited from memory of well-known work; **check each reference and add page numbers before submission**.

- **Pixel- and text-based GUI element detection.** Sikuli (Yeh et al., UIST 2009) automated GUIs from screenshots
  with image matching. UIED (Xie et al., 2020) combines classical vision with deep text detection for GUI
  elements. Screen Recognition (Wu et al., CHI 2021) detects UI elements on mobile screens with a trained model.
  Datasets such as Rico (Deka et al., UIST 2017) support this, but they cover mobile apps, not desktop 3D tools.
- **Model-based screen parsing and grounding.** OmniParser (Microsoft, 2024) turns a screenshot into
  structured elements for a language model; SeeClick (2024) and CogAgent (2023) train models to output click
  coordinates; Set-of-Mark prompting (2023) overlays numbered marks to help models name regions. These need a
  model call (and a network) per screen and return coordinates that can be slightly off, which is why
  `shared/grounding.py` refuses points outside the target window rather than clamping them.
- **Why this project uses OCR plus rules plus a probe.** The product must observe only, keep data on the
  machine except through the AI gateway, run on student laptops without a GPU, and answer within seconds.
  Windows' built-in OCR costs no download and no network. The menu text a tutorial names is exactly what OCR
  reads well; icon-only controls need pixel rules (toolbar cells) or the probe. Model-based grounding remains
  an option for dense editors (Maya, Houdini node graphs) where text and rules fall short, behind the same
  `GroundingResult` contract.
- **Prior art in the repository.** The grounding contract adapts the Clicky reference app (MIT licence); see
  `shared/grounding.py`.

## Sources checked for section 2
- SideFX, [Houdini Apprentice](https://www.sidefx.com/products/houdini-apprentice/) and [Apprentice FAQs](https://www.sidefx.com/faq/apprentice/)
- SideFX, [What are the restrictions of Houdini Apprentice?](https://www.sidefx.com/faq/question/435/)
- Autodesk Education plan: [Autodesk education software overview](https://www.autodesk.com/education/edu-software/overview), plus university help pages that summarise it
- Autodesk Maya help, [Python and threading](https://help.autodesk.com/cloudhelp/2017/ENU/Maya/files/GUID-9B5AECBB-B212-4C92-959A-22599760E91A.htm) (an older version; confirm for Maya 2027)

## 4. Part A spike (2026-11-16): what Blender's Python API and Windows really give us
Measured on Blender 5.2.2 LTS, Windows 10 (19045), a 1366x697 window at 96 dpi (100% scaling in this session; 150% not rechecked), English, default theme. Scripts used are not kept; `scripts/vision_bench.py` is.

| Question | Result | Consequence |
|---|---|---|
| Do Blender's region rectangles match the screen? | `window.width/height` equal the Win32 CLIENT size (1366x697). The client origin on screen was (0, 31); the rectangle vision captures (DWM frame) was (-1, 0, 1368x729): it includes the 31 px title bar and a 1 px border. Region rectangles are in window pixels with the origin at the BOTTOM-left | every Blender-side coordinate needs the client origin and a y flip (A2); using the frame rectangle directly is off by 31 px |
| Toolbar scroll | `region.view2d.region_to_view(0, height)` is readable: it went 1 -> -222 after six scroll steps; region size 56x548 | scroll position and "is tool N visible" can be computed, not guessed |
| Ordered tool list for the mode | `ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D").tools_from_context(context)` gives groups and separators live (25 entries in Edit Mesh); `builtin.loop_cut` has label, keymap `3D View Tool: Edit Mesh, Loop Cut`, operator `mesh.loopcut_slide` | `toolbars.json` can be replaced by the live list. Private module (`bl_ui`), so wrap in try/except |
| Toolbar layout depends on width | Blender's own `_layout_generator_detect_from_region` chooses one or two columns and text or icons by region width (`space_toolsystem_common.py`) | the slot of a tool must be computed from the same rule, not assumed |
| Visible Properties tabs | `space.context` is a dynamic enum: assigning an invalid value raises a TypeError that lists the tabs available now. Hacky; the static `enum_items` lists all 20 | readable in principle, in order; needs a guarded helper |
| Redo panel (Loop Cut and Slide, Subdivide) | a `HUD` region exists in the 3D view's region list (1x1 when no panel). Operators run from a script did not enlarge it | **not verified** with real clicks |
| Operator history from real clicks | `window_manager.operators` stayed empty after script-run operators. My attempts to inject real input failed (Blender ignores posted window messages; sent mouse/keys did not reach the viewport) | **not verified**: needs a person in the live check (Part C) |
| Panel collapsed state | the region object has no panel list (`active_panel_category`, `alignment`, `view2d`, size) | not readable: use pixels |
| Keymap | `window_manager.keyconfigs.user.keymaps` items readable with context and `is_user_modified`; Loop Cut = Ctrl R in keymap "Mesh"; Object Mode: S, Ctrl P, Shift A, Tab; `keyconfigs.find_item_from_operator` exists | shortcuts can come from the user's own keymap |
| Capture the window itself | `PrintWindow` returned a frame that differs strongly from the screen grab (mean abs. difference 187/255) | **not adopted**; keep the screen grab |
| Hide our overlay from capture | `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` succeeds on a plain Qt window but FAILS (error 8) on the translucent overlay, with or without the click-through flags | the cause is the translucent (layered) overlay style, not the Windows build. The guide box is not translucent and probably succeeds: unchecked |
| Window lookup by title | with a browser tab titled "Get Involved - Blender" open, `find_window("Blender")` matched the browser (and, when Blender was minimized, only the browser). Fixed in A3: the window must also belong to `blender.exe` | live-confirmed bug, fixed |

### Baseline latency (before Part A; median of 8 runs, ms)
Blender in front with its splash screen still open, 1368x729 frame, Intel laptop (same machine as section 2, quieter):
| find_window | windows_above | grab | mask | detect_layout | find_cells | OCR full frame | OCR 500x400 area | probe read |
|---|---|---|---|---|---|---|---|---|
| 2.6 | 0.2 | 33 | 1.0 | 56 | 8.5 | 370 | 85 | 0.1 (no add-on running) |

A look that has to read the whole screen costs about 0.5 s, a small changed area about 0.15 s, and a probe read is free by comparison: the lever is reading less often, not reading faster. `detect_layout` reported confidence 0.17 and found 1 toolbar cell on this frame (splash open): a frame the area-splitting guess fails on. Re-run `python scripts/vision_bench.py --front` (only against a Blender you started yourself) after each part for the "after" numbers.

### Part A results (same machine and window as the baseline above)
| Check | Before | After |
|---|---|---|
| Layout of the window | `detect_layout` (pixel gaps): confidence 0.17 on a plain Layout frame; toolbar cells found 11 to 14, of which the cells inside the toolbar region Blender reports: not checkable | from the add-on: confidence 1.0, six areas named, `vision_uicheck` PASS: window size, client origin and frame agree; 14 of 14 toolbar cells found in the pixels sit inside the reported toolbar region (sidebar open, toolbar scrolled, Edit Mode) |
| Look on an unchanged screen | whole-screen mean compare, a read when anything moved more than the mean threshold; at most 5 s stale | median 53 ms (capture 33 ms + compare), 11 of 12 looks read nothing; layout detection no longer runs (50 ms saved per full read) |
| Menu or panel opens (small area) | missed by the mean compare (stale up to 5 s) in `VisionService`, read in the app's copy | read by the one shared reader, area only (about 60-120 ms) |
| Toggled checkbox (12 px, +40 grey) | missed (2 cells of 3 needed on a 192x108 thumbnail) | seen (about 9 cells on 384x216), unit test |
| Orbiting the 3D view | whole-window read per look | ignored while more than 35% of the viewport changed; a menu opening over it is still read (unit tests) |
| Which Blender | title match: a Chrome tab titled "Get Involved - Blender" could be taken for it | program and, with the add-on, process id |
| Old toolbar lookup with the toolbar scrolled (reproduced, NOT fixed in Part A) | `locate_tool("Loop Cut")` names visible cell 12 of 14, but 3 cells were scrolled off, so the highlight lands about 3 cells below the real Loop Cut (true index 12 of 21 in all) | fixed in Part C with the live tool list and the reported scroll |

Not verified in Part A: the redo-panel (HUD) region size and `window_manager.operators` after real clicks (no way to inject real input into Blender found), 150% display scaling, a second monitor, and `mypy` locally (the PyQt6 stubs installed here do not parse under this mypy; CI is unchanged by this part).

## 5. Part C measurements: how Blender lays out the toolbar (5.2.2, default theme, UI scale 1.0)
Measured on a real window with the toolbar read from pixels and the add-on's scroll distance (`vision/toolbar_align.py` uses them as priors only; the pitch is re-measured from the cells every time):
| What | Measured |
|---|---|
| Cell height | 33-34 px, 37 px wide, 1 px between neighbours |
| Pitch (top of one cell to the top of the next) | 34.5 px (34 and 35 alternate) |
| Across a separator | 41 px, i.e. 6.5 px extra |
| Margin above the first cell | 9 px |
| One mouse-wheel step over the toolbar | 40 px of scroll (view_top 1 -> -39 -> -79 -> ...) |
| Smooth scrolling | the picture lags the add-on's `view_top` for about a second after a scroll: a frame taken at that moment shows cells in between positions. The alignment compares the pixels with the scroll distance and refuses (confidence 0.5) when they disagree |
| Edit Mesh separators | after cells 2, 6, 8 and 9 (flags at index 1, 5, 7, 8) |
