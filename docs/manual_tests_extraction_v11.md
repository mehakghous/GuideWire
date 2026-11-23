# Manual tests: step extraction v12 and in-step guidance (22 Nov 2026)

Needs `GEMINI_API_KEY` in `.env` (each video costs about $0.06). Start the app with `python -m app.ui.main_window` and sign in. Tutorials saved before this change keep their old steps: make them again from the link.

| # | Do this | Expect |
|---|---|---|
| 0 | New Tutorial → paste `https://www.youtube.com/watch?v=PctSMB-RGsM`, Application **blender** → Create steps, then Save. | About 18–25 steps, each with 1–3 how-to lines. Separate steps for: add the single-bone armature; switch to Edit Mode; turn on In Front; switch to Pose Mode; each parenting. |
| 0a | Start a session on it with Blender open and guidance on, in an empty scene in Object Mode. Do step 1 (Shift+A > Armature > Single Bone). | The step completes and the guide moves to step 2 (Edit Mode). It does not keep pointing at Add > Armature. |
| 0b | Make a tutorial whose first step holds several parts (for example paste the v11-era steps, or use one saved before this change). Do its first part. | The guide moves on to the next part (for example "Edit Mode"); it never says "Switch to Object Mode first" after you changed mode as part of the step. |
| 0c | In that session, go through steps 2–14 (Edit Mode, In Front, …, Bone Constraints tab, Axes). | Each step that names a mode, a Properties tab, a panel field, a sidebar field (Item > Roll) or a toolbar tool gets a highlight box on that element, or a hint pointing to its tab or panel. None of them only says "Looking for it" while the element is in view. |
| 0d | On the Blender leg-IK tutorial, open step 1 ("Press Shift+A …") before starting. | The step details have a block **Without the keyboard**: "Shift+A: use the Add menu in the 3D view header". |
| 0e | Start the session in an empty scene (Object Mode) and read step 1's guide box. | It says the key **and** "Without the keyboard: use the Add menu in the 3D view header"; the **Add** menu in the 3D view header gets the highlight box. Choosing it by mouse, or pressing Shift+A, both work and the step completes the same way. |
| 0f | Step 2 ("Switch to Edit Mode", key Tab). | Details: "Tab: choose Edit Mode in the mode dropdown at the top left of the 3D view". The dropdown is highlighted. Once you are in Edit Mode that line disappears. |
| 0g | In Edit Mode, the step with Alt+P (unparent) and the step with E (extrude). | Alt+P: "use Armature > Parent > Clear". E: "use Armature > Extrude". In Object Mode the same Alt+P step would say Object > Parent > Clear Parent instead. |
| 0h | A step whose keys are only a typed value or Enter (for example "R 90 Return"). | No alternative is shown for the Enter key; the step says only what it said before (plus the Rotate route for R). |
| 1 | New Tutorial → paste `https://www.youtube.com/watch?v=TmhC35PqZvQ`, Application **maya** → Create steps. Wait 1–2 minutes. | About 8–12 steps, in the tutorial's order (joint tool, joint chain, naming, mirroring, IK handles). No invented steps. |
| 2 | On the review screen, click the mirror step. | **Why** says what mirroring achieves. How-to lines include YZ, Search For "left", Replace With "right". **Watch out** mentions the wrong mirror plane and that the instructor undid it and chose YZ. |
| 3 | Click each step in turn. | Every Watch out line is about something that step does. No "Multi IK Segments", "Stash Input" or other warnings unrelated to it. |
| 4 | Save, then Start session and Start. | The current step shows **Why** first, then How to do it, How you can tell it worked, then Watch out. |
| 5 | New Tutorial → `https://www.youtube.com/watch?v=xWnI7is6e7Q`, Application **houdini** → Create steps. | While it works the message says "Taking a second look at the parts of the video without steps…". About 11–15 steps following the node network (Box, Skeleton, Pack Folder, AutoRig Component with Component FK as its own step, Configure Controls, Add Character, Animate, Merge, Attribute Wrangle, pattern update). The note on the review screen says prompt **v13**. |
| 5a | In that tutorial, open each step on the review screen. | A step that sets a label Houdini 22 does not have on that node (for example "Target Pattern" on APEX Configure Controls, or "Folder Name" on Pack Folder) has a note: "'…' is not a parameter of … in Houdini 22.0.466: check the label in the video". A step that adds an Attribute Wrangle or works on APEX AutoRig Component never has such a note. |
| 5b | If a step is flagged "found by a second look at m:ss to m:ss", watch that part of the video. | The step really happens there (for example pressing F for Modify mode around 4:00). |
| 5c | If a step has a note "label corrected by a second look at m:ss to m:ss: 'X' is 'Y' on <node>", watch that part of the video. | The parameter pane shows **Y** where the instructor types the step's value (for example Group or Control Group holding `point*` on APEX Configure Controls), and the step's how-to now says Y. |
| 5d | If a step still has "a second look … could not correct 'X'", read its reason. | The reason says why: the clip did not show it, or the clip shows another value (for example "joint" where the step says `jnt_*`). Check that step against the video by hand. |
| 6 | In that Houdini tutorial, open the Configure Controls step. | If a how-to line says "adjust …" or "a custom …" without a value, Notes contains "a value may be missing: … check the video before using this step". |
| 7 | In the Blender tutorial from row 0, read the steps. | Exact values appear (R 90, Roll 90, Head/Tail 1.0, Keep Offset), and a "Clear Transform > All" step is there. |
| 8 | Open a tutorial saved **before** this change (Home → an older tutorial → Review steps). | It opens and works as before, with no Why line (the field is empty for old steps). |
| 9 | Paste written instructions (one per line) in New Tutorial → Create steps. | Same behaviour as before: written text does not use the video prompt. |

## Houdini highlighting (23 Nov 2026)

Start Houdini, then in its Python Shell: `import sys; sys.path.append(r"C:\dev\GuideWire\vision\probes"); import houdini_probe; houdini_probe.register()`. Then in GuideWire start a session on a Houdini tutorial (for example the APEX FK one from row 5).

| # | Do this | Expect |
|---|---|---|
| H1 | On a step that adds a node ("Press Tab … add a Pack Folder"), with the network editor visible. | A box around the network editor and "Press Tab with the mouse over the network editor." |
| H2 | Add the node. | The guide moves on: the next part (selecting it, or its parameter) is pointed at. It does not keep asking for Tab. |
| H3 | On a step that selects a node by name (for example packfolder1). | A box exactly on that node's tile in the network editor. |
| H4 | On a step that sets a parameter, with that node selected. | A box on that parameter's row in the parameter pane (label to the right edge). |
| H5 | Same step, but select a different node first. | No box on a parameter. The guide says to select the step's node first and points at it when it is in view. |
| H6 | A step whose parameter label the node does not have (flagged on the Review screen). | No box; only words. |
| H7 | Run `python scripts/houdini_live_check.py runs/houdini_live` with a Pack Folder selected. | It prints a decision per target, and `runs/houdini_live/houdini_live.png` shows boxes only on the right places. |
