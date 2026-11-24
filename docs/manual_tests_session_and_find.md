# Manual tests: session screen, highlights, Find a tutorial (21 Nov 2026)

Automated tests cover the logic; these check what only a real screen shows. Use the project venv (`.\venv\Scripts\Activate.ps1`), start the app with `python -m app.ui.main_window`, register or log in, click **Add demo tutorials**, and have Blender open with the GuideWire Probe add-on enabled (for the highlight tests). Note Blender's version: the interface catalog was dumped from 5.2.2.

## Session screen

| # | Do | You should see |
|---|---|---|
| S1 | Open **How to Rig a Leg with Inverse Kinematics in Blender**, press nothing | Page title is `Session: <tutorial title>` and wraps. A **Before you start** box says a leg mesh must already be in the scene (and, for tutorials that never use it, that the default cube can be deleted). The step tile says "Check what this tutorial assumes, then press Start." |
| S2 | Press Start | The box disappears. A **Before you start** button appears in "Your move"; clicking it brings the box back. |
| S3 | Look at the right-hand **All steps** list | All 36 steps are there, goals wrapped in full. Step 1 has an orange pill with `▶` and the word **Now**. |
| S4 | Press Done, then Skip | Step 1 gets `✓ Done`, step 2 gets `↷ Skipped`, the pill moves to step 3 and the list scrolls to keep it in view. |
| S5 | Click step 1 in the list | The step tile says "Looking at step 1, not your current step" with its how-to lines and "You marked this step done". The current step and session do not move. Row 1 has a dashed outline. |
| S6 | Press **Back to my step**, then click step 2 and press **Go to this step** | First: back on your step. Second: the session moves to step 2 (steps from 2 on are to-do again) and says "Moved to step 2." |
| S7 | Look at any step's text | Only "How to do it" and "How you can tell it worked" (and, when GuideWire cannot check it, one sentence saying so). **No "Notes"**, no "derived from the knowledge base". |
| S8 | Shrink the window to its smallest size (900 wide) | Nothing is cut off. The steps list moves below the other tiles. If a font is very wide a sideways scroll bar appears. |

## Pause and going back (needs Blender open and "Watch my screen" ticked)

| # | Do | You should see |
|---|---|---|
| P1 | Get to a step you have already done in Blender, for example step 18 "Switch to Pose Mode" while Blender IS in Pose Mode. Press **Pause** | Button says **Resume**, status says "Paused on step 18...", the highlight disappears, the step stays put however long you wait. |
| P2 | Press **Resume** | It looks at once, sees the step done and moves on. |
| P3 | From step 19 with Blender still in Pose Mode, press **Previous step** | You land on step 18 and STAY there (paused, with a message). Before this change it jumped straight back to 19. |
| P4 | Press **Done** or **Skip** while paused | The pause ends and the session moves on. |
| P5 | Minimize GuideWire (the small guide box stays). In the box press **Pause** | Same as P1; the box's button reads Resume. Minimize the box to its tab: Pause is hidden there, the tab stays small. |

## Highlights (Blender with the add-on)

| # | Do | You should see |
|---|---|---|
| H1 | Step 25 (bone Roll), Edit Mode on the armature, sidebar CLOSED | An orchid highlight on the right edge of the 3D view and the words "Open the sidebar (press N with the mouse over the 3D view)... then Transform > Roll". |
| H2 | Press N, open the **Item** tab, make sure **Transform** is open | The **Roll** field is highlighted. Collapse Transform: the highlight moves to the Transform header ("Click Transform to open it"). |
| H3 | Step 33 (Head/Tail), Pose Mode, Bone Constraints tab with ONE Copy Location constraint | The **Head/Tail** slider is highlighted, even if the constraint has been renamed. |
| H4 | Add a second constraint that also has a Head/Tail slider | No highlight (two places match) and the words explain; not a guess. |
| H5 | Step 33 can never finish by itself (the tutorial data expects a Copy Rotation constraint) | Press **Done** by hand. This is a known data problem, not a bug in the new code. |

## Before you start check

| # | Do | You should see |
|---|---|---|
| B1 | Delete everything in Blender's scene (A, X, Delete), start a session on the leg tutorial and press Start | The "Before you start" box returns with "GuideWire did not see this in your scene: A leg mesh already in the scene". You can carry on. |
| B2 | Do it again with a mesh in the scene | No warning. |

## Find a tutorial

| # | Do | You should see |
|---|---|---|
| F1 | Search "rig a leg with IK" in Maya, click Back, open Find again | The goal, application and the same three cards are still there. |
| F2 | Close the app, start it, log in, open Find | Your last search is back (words, application, results). |
| F3 | Make two or three searches, then click entries in **History** | Each opens with its results at once, no "Searching..." and no quota spent; the message starts "Saved search." |
| F4 | **Remove from history** on one, then **Clear history** | The entry disappears; then the empty-state text shows. Log out and in as another account: its History is empty. |
| F5 | Read a card | Title, channel / length / year and ONE plain sentence about what the video seems to cover. No "Uploaded 2026-08, 0 year(s) ago", no "Judged from metadata". Long text wraps; the list and the page scroll. |
| F6 | Click **Open in browser** and **Turn this video into steps** | The video opens; New Tutorial opens with the link filled in. |

## Why nothing was found (Find AND Ask GuideWire)

| # | Do | You should see |
|---|---|---|
| N1 | Close the app, rename `YOUTUBE_API_KEY` to `YOUTUBE_API_KEY_OFF` in `.env`, start, search a goal the small built-in list does not cover (for example "rig a leg with IK" in Blender) | "No YouTube search key is set on this computer (YOUTUBE_API_KEY in the .env file), so only GuideWire's small built-in list was searched..." In Ask GuideWire, "recommend a tutorial for rigging a leg with IK" gives the same sentence. Put the name back afterwards. |
| N2 | Turn Wi-Fi off, search | "GuideWire could not reach the YouTube search just now (...)". |
| N3 | With the key and internet on, search normally | Three suggestions (this works; it was checked live on five goals). "I found no tutorial that matches that well" now appears ONLY when a working search found nothing. |
