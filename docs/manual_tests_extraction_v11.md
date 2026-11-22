# Manual tests: step extraction v12 and in-step guidance (22 Nov 2026)

Needs `GEMINI_API_KEY` in `.env` (each video costs about $0.06). Start the app with `python -m app.ui.main_window` and sign in. Tutorials saved before this change keep their old steps: make them again from the link.

| # | Do this | Expect |
|---|---|---|
| 0 | New Tutorial → paste `https://www.youtube.com/watch?v=PctSMB-RGsM`, Application **blender** → Create steps, then Save. | About 18–25 steps, each with 1–3 how-to lines. Separate steps for: add the single-bone armature; switch to Edit Mode; turn on In Front; switch to Pose Mode; each parenting. |
| 0a | Start a session on it with Blender open and guidance on, in an empty scene in Object Mode. Do step 1 (Shift+A > Armature > Single Bone). | The step completes and the guide moves to step 2 (Edit Mode). It does not keep pointing at Add > Armature. |
| 0b | Make a tutorial whose first step holds several parts (for example paste the v11-era steps, or use one saved before this change). Do its first part. | The guide moves on to the next part (for example "Edit Mode"); it never says "Switch to Object Mode first" after you changed mode as part of the step. |
| 0c | In that session, go through steps 2–14 (Edit Mode, In Front, …, Bone Constraints tab, Axes). | Each step that names a mode, a Properties tab, a panel field, a sidebar field (Item > Roll) or a toolbar tool gets a highlight box on that element, or a hint pointing to its tab or panel. None of them only says "Looking for it" while the element is in view. |
| 1 | New Tutorial → paste `https://www.youtube.com/watch?v=TmhC35PqZvQ`, Application **maya** → Create steps. Wait 1–2 minutes. | About 8–12 steps, in the tutorial's order (joint tool, joint chain, naming, mirroring, IK handles). No invented steps. |
| 2 | On the review screen, click the mirror step. | **Why** says what mirroring achieves. How-to lines include YZ, Search For "left", Replace With "right". **Watch out** mentions the wrong mirror plane and that the instructor undid it and chose YZ. |
| 3 | Click each step in turn. | Every Watch out line is about something that step does. No "Multi IK Segments", "Stash Input" or other warnings unrelated to it. |
| 4 | Save, then Start session and Start. | The current step shows **Why** first, then How to do it, How you can tell it worked, then Watch out. |
| 5 | New Tutorial → `https://www.youtube.com/watch?v=xWnI7is6e7Q`, Application **houdini** → Create steps. | About 8–12 steps following the node network (Skeleton, Pack Folder, AutoRig Component, Configure Controls, Add Character, Animate, Merge, Attribute Wrangle, pattern update). The words **Target Pattern** and **Component Source** appear nowhere. |
| 6 | In that Houdini tutorial, open the Configure Controls step. | If a how-to line says "adjust …" or "a custom …" without a value, Notes contains "a value may be missing: … check the video before using this step". |
| 7 | In the Blender tutorial from row 0, read the steps. | Exact values appear (R 90, Roll 90, Head/Tail 1.0, Keep Offset), and a "Clear Transform > All" step is there. |
| 8 | Open a tutorial saved **before** this change (Home → an older tutorial → Review steps). | It opens and works as before, with no Why line (the field is empty for old steps). |
| 9 | Paste written instructions (one per line) in New Tutorial → Create steps. | Same behaviour as before: written text does not use the video prompt. |
