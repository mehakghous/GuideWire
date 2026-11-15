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
