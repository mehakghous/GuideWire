# Why highlighting got worse, what was wrong, how it was checked (23 Nov 2026)

Reported on the Blender leg IK video (`PctSMB-RGsM`, 25 steps in the learner's saved tutorial): step 1 only highlighted Add when an armature already existed; step 3 never reached In Front; "Look for" turned into "Find" while reading; step 4 and 5 had no way without the keyboard; step 13 no Axes; steps 17, 18, 22, 24 nothing on Clear Parent, Keep Offset, Copy Location, Head/Tail, Object > Parent > With Automatic Weights.

## It is not the headings

A highlight is built from each step's `actions` (what element, which keys), not from the heading. The headings are never searched for on screen. The cause is in the actions v12 writes (and, for the pop-ups and menus, in the grounders). Reading the saved tutorial's actions step by step, then running the real guidance against a real Blender 5.2 (below), found six separate causes:

1. **Menu items written without their menu.** Step 1's action is `Armature > Single Bone`. The grounder looks for the FIRST name in the 3D view's header, and "Armature" is not in the header in Object mode (only after an armature exists, in Edit Mode, is there an Armature menu). So Add was never found. v10 wrote `Add > Mesh > Cylinder`.
   *Fix:* `ingestion/targets.py` completes such a path from the header menus Blender itself reports (`knowledge/app_vocab/blender_menus.json`): `Armature > Single Bone` becomes `Add > Armature` (Blender 5.2's Add > Armature adds the single bone).
2. **A field named on its own after its panel.** v12 writes `Properties > Object Properties > Viewport Display` and then, as a second action, `In Front`. The second had no path, so it became "a thing in the 3D view" (nothing to find), and the first (the panel header) could never be seen as done. So In Front, Axes, Head/Tail, Copy Location were never reached.
   *Fix:* the resolver carries the Properties tab and panel a step opened to the field named right after it (and to the next step, no further). `app/step_state.py` joins a tab or panel header and its field into one thing to find, which the property grounder already walks: tab icon, panel header, field.
3. **Only the first part of a step was ever pointed at.** The guide points at the first part not yet done, and a menu or panel part can never be seen done. A later part that is already on screen (a pop-up is open) was never reached.
   *Fix:* when the first part is not on screen, the guide points at a later pop-up or menu choice of the step that is. Other kinds are not skipped to: a Houdini parameter pane can be on screen long before the step gets to it (a test caught this).
4. **The Object menu looked ambiguous.** In Object Mode the header reads "Object Mode … View Select Add Object". A path starting at the Object menu found "Object" twice (the mode dropdown and the menu) and was dropped as a guess, so step 24's Object > Parent > Armature Deform > With Automatic Weights was never pointed at. (Seen on screen: nothing was drawn.)
   *Fix:* `vision/locate.py` ignores an "Object" that is followed by "Mode" on the same row.
5. **A pop-up titled with its own first choice.** Alt+P in Edit Mode opens a pop-up titled "Clear Parent" whose first choice is "Clear Parent", and a tooltip beside it repeats the words. Three hits were ambiguous and nothing was pointed at.
   *Fix:* `vision/grounders.py` takes the lower of the two in one column as the choice and ignores the tooltip further away. Keep Offset (one hit) already worked once the pop-up was open.
6. **Several keys in one step had no menu route shown.** A step with G, R and S has three other ways; the guide only pointed when there was exactly one. Now the first one that is on screen is pointed at (here Armature > Transform > Move), and the sentence still names them all.

Also: the notes "Look for X in the Object tab" and "Find X in the Viewport Display panel" were two phrasings of the same instruction that flipped while the screen was being read. All are now "Find …".

## How it was checked

`scripts/live_guidance_walk.py` starts a real Blender 5.2, builds a leg mesh and an armature, puts Blender in the state each step needs (mode, armature present or not, Properties tab open, the pop-up open for the steps that use one), and asks the app's own `VisionBridge` what it would draw. It runs the same steps for v10, v12, v12 split into finer steps, and the learner's saved tutorial. `GW_SHOTS=saved` keeps a screenshot of every rectangle so it can be looked at.

Steps with something the guide can find, and how many got a rectangle on at least one of the screens (the step's start, the Properties tab open, the pop-up open):

| | Before today's fixes | After |
|---|---|---|
| Saved tutorial (the learner's) | 14 of 20 | 20 of 21 |
| v12 as extracted | 14 of 21 | 21 of 22 |
| v12 split into finer steps | 16 of 24 | 25 of 27 |
| v10 | 16 of 21 | 22 of 22 |

(The "before" column for the split list used the older split, 28 steps instead of 33.)

At the screen a learner sees when the step starts (nothing opened yet), the saved tutorial went from 13 of 20 to 16 of 21; the rest of the gain is the Properties tab and pop-ups that open during the step.

Rectangles looked at on screen (saved tutorial): step 1 Add; step 3 the Viewport Display header on the Object tab; step 24 the Object menu; step 13 the Data tab icon; steps 8, 9 and 17 Clear Parent in its pop-up.

**Not covered.** Only the first screen of each state is tested: a menu opened by the learner, an expanded panel, the Add Bone Constraint list. Step 11 (Shift+I, To Active Bone) is still words only. Step 12's field "Pole Target Target" is a garbled name from the model and cannot be found by its words. Blender 5.2 only, one window size, one scene. I did not try a real learner's hands.

## Inside menus and panels (second check, same day)

The first check looked at the screen at the start of each step. This one follows the guide's own highlights the way a learner would: `scripts/live_follow_walk.py` looks, clicks the middle of the rectangle the guide drew (on a throw-away Blender it builds itself, and never on the last element of a step), looks again, and repeats. It found three more problems, all fixed, and each is now checked by a screenshot:

7. **Menu items that are also part of longer ones.** With the Armature menu open, "Extrude" is also the first word of "Extrude to Cursor"; with Object > Parent open, "Parent" is a word of "Clear Parent" and "Make Parent without Inverse". The ties made the guide draw nothing inside the menu (steps 5 and 24). A label with another word right beside it on the same row is now treated as part of a longer label.
8. **Submenus that open upward.** The Parent submenu is long, so "Armature Deform" and "With Automatic Weights" sit far above the Parent item. The guide only looked for the next part at or below the parent and stopped at Parent. A submenu to the right of its item is now followed up or down.
9. **A panel opened at the bottom edge of the editor.** After the learner opened Viewport Display it sat on the last row with nothing under it, and the guide kept saying "Click Viewport Display to open it". It now says to scroll down, and once scrolled, points at In Front or Axes.

Result, following the highlights in Blender 5.2 (steps of the saved tutorial): steps 1, 3, 5, 13, 21, 22 and 24 all reach the last element (Add > Armature; Viewport Display, scroll, In Front; Armature > Extrude; Data tab, Viewport Display, scroll, Axes; Bone Constraint tab, Add Bone Constraint; Bone Constraint tab, Head/Tail; Object > Parent > Armature Deform > With Automatic Weights). Before these three fixes steps 3, 5, 13 and 24 stopped part way.

The harness sets up its own scene: a constraint with a bone target exists so Head/Tail is on screen. In your own Blender those fields appear only after the earlier steps have been done.

```powershell
python scripts/live_follow_walk.py
```

## Run it

```powershell
python scripts/live_guidance_walk.py --only saved
```

It brings Blender to the front and moves the mouse to the middle of the 3D view (no clicks) for about 3 minutes. The tutorial it reads is local tutorial 41 (`GW_SAVED_TUTORIAL=<id>` for another).
