# Second round on the Blender leg IK video: the issues in plain words, their causes, the fixes (24 Nov 2026)

Reported while following the saved tutorial for `PctSMB-RGsM` in the app. Each item says what you saw, why it happened (checked, not guessed), what was changed, and what is still open.

## A. The guide (highlights and text)

**1. Step 4 stays on Move instead of going on to Rotate and Scale.**
Why: one step held three operations (G, R, S). The guide can only point at one thing at a time and cannot see that a key press has been done (a move happens and is over), so it kept pointing at the first way (Armature > Transform > Move). Behind it, the step splitter had joined the R and S lines to the G line because a bare key press "has nothing to point at", although each of these keys has a menu way the guide does point at.
Fix: a key press that has a menu or dropdown way (G, R, S, E, Tab) now counts as something to point at, so G, R and S become three steps and each highlights its own menu item (Move, Rotate, Scale). New tutorials only: a tutorial already saved keeps its old division.

**2. Steps 6 and 7 do not say which way to extrude (backwards, forwards, left, right).**
Why: the instructor drags the bone out along an axis and says "back" or "in front"; the steps only said "press E, then Y". The extraction prompt had no rule to write a direction.
Fix: prompt v14 asks for directions the way the learner sees them and the amount when shown. On this video the steps now say "drag straight out backwards" (ankle) and "in front of the knee" (knee).

**3. Hovering Clear Parent shows a definition, and the words inside it were highlighted too.**
Why: the tooltip ends in the words "...their parents: Clear Parent". The guide looked for "Clear Parent" anywhere on screen and could not tell the choice from the end of a sentence.
Fix: a match that has another word right beside it on the same row is part of a longer sentence, not a choice, and is ignored (the same rule that made the Armature and Parent menus work).

**4. The text under the heading changes while you read (step 10).**
Why: the screen read flickers (a word missed on one look), and every look rewrote the message and hint: "Click the mode dropdown, then Pose Mode", "Open it first", "Looking for it".
Fix: a change to a different state must be seen on two looks in a row before it replaces what is shown. A step finished, a window missing and the first look are shown at once.

## B. How the steps are divided

**5. Steps 17 and 18: one says "Shift-select the IK foot controller bone", the next "press Ctrl+P on it".**
Why: the splitter cut after a selection line. A selection belongs to the action after it.
Fix: a line that only selects things now starts the part that follows. A line that only opens the Mode selector stays with the line that chooses.

## C. What the steps say (the extraction prompt)

All of these came from rules in the v11/v12 prompt itself, not from the model drifting:

**6. Nothing for 2:11 to 2:36 (move the controller, the knee twists, Clear Transform > All).**
Why: v12 said "no steps for looking at or checking something", "do not write steps for the mistake", and "a test goes in the check lines". The instructor's demonstration of the problem, and the reset after it, matched those rules and were dropped.
Fix: v14 has a TRY, SEE, FIX rule: a deliberate try that shows a problem is a step whose why says what is wrong and what fixes it; a reset or clear is a step.
Now: "Test IK motion and observe knee twisting behavior" (2:11), "Reset pose transforms" with Pose > Clear Transform > All (2:28), and the same pattern at 4:04 and 4:39 (the foot does not follow, then the fix).

**7. The whys are hard to understand and not about what is on screen.**
Why: v12 asked for one sentence "to ...". The model wrote a template.
Fix: v14 asks for one to three plain sentences in the context of the example on screen, with the instructor's conditions, and a plain definition of a term at the first step that uses it.
Now: for example "Visualizing bone axes allows checking whether the local X-axis points directly toward the pole target" and "Testing demonstrates that the leg IK works, but shows why a pole target is needed to fix knee twisting".

**8. "Controller bone" is used without being explained.** Partly fixed: the first controller step says what the bone is for ("serve as the inverse kinematics controller handle"). It is a short definition, not a lesson, and only as good as what the instructor says.

**9. Mac key names ("Press Command then Command+P", "(or Option+P)").**
Why: seen in the new v14 output (the model copied the Mac equivalents). The guide then looked for keys that do not exist on a Windows keyboard.
Fix: v14 asks for Windows key names, and every v14 extraction converts Command to Ctrl and Option to Alt and drops "(or ... Mac key)" asides.

## What is still open

- **The roll angle "90, or -90 depending on the setup" (3:45):** v14 writes the 90 but not the condition. The prompt asks for it; the model did not include it on this video.
- **Setting the pole bone twice (2:42 to 2:48):** not captured; v14 writes it once.
- **Your saved tutorial** keeps the old steps. Make it again from the link (about $0.06 to $0.12) to get v14; the test database already has the v14 version.
- **Maya and Houdini** still use v12 and v13. v14 was tried on the two Blender videos only.
- **"Hold Ctrl (or Shift) and select"** (step 38): the model's own mistake; Shift is the right key.
- **Step 11 (To Active Bone) and step 27 (Pole Angle field):** words only in my test scene.

## Evidence

- v14 on both Blender videos (cost guard, $0.18 in total): words found 93%, steps matching a labelled action 97% (v12: 91% and 98%); this video 25 steps (v12) to 34 steps, then 49 after the split. v10 had 30.
- Real Blender 5.2 walk (`scripts/live_guidance_walk.py --only v14split`): 48 of 49 steps get a rectangle on some screen (one run had a start-up glitch that lost the first two states; the repeat did not). Your saved tutorial still gets 20 of 21, popups included.
- Tests: 390 pass in the related suites (split, v14, grounders, step state, targets, key alternatives, prompts, Houdini, app flow, UI, gateway prompt).

## Third round (24 Nov, evening): the wrong bone at 4:31, the roll angle, the redo panel

**Step "parent the toe bone" (4:31): checked in the video itself.** I opened the video and stepped through 4:25 to 4:40. When he says "we can do the same thing with this bone", the highlighted (selected) bone is the free bone at the left of the leg, the knee controller; the Make Parent pop-up for Keep Offset opens next to the ankle controller. It is the other controller, not a toe bone. The model had named it from the layout of the rig.

*Tried first, and it did not work:* asking the model, with the clip of the step and the list of bones already made, which bone is selected. It answered "the toe bone" with a confident description of where it sits, and in another try "part of the leg chain" while describing a different minute of the video. The selected bone is a few orange pixels in a low-resolution screen recording; a second look cannot be trusted more than the first.

*What is done instead:* when all the instructor says is "do the same thing with this bone" (or "the other one") and the step names a body part he never said (`inferred_names`, `ingestion/validate.py`), the step is rewritten as what he said: the same operation on the OTHER bone of the same kind, the one not used in the previous step (`ingestion/identify.py`). The model's reason for the invented bone is replaced, and a note says where in the video to look. On the recorded runs of this video it fires on exactly this step (6 of 6 runs, including the v10 run) and on no other step. The prompt also asks for this wording from the start. The parent (the ankle controller) is left as the model wrote it, because the video agrees.

**The roll angle.** The model wrote "90 (or -90 depending on initial setup)". His rule is that the bone's X axis must point at the knee controller (the pole target), and the roll is 90 or -90, whichever makes it point there. v14 now asks for a value that depends on the setup together with the test that chooses it, and for the why to say what it has to achieve. One run gives: "Set Roll to 90 (or check if X axis points at pole target; use -90 if it points away)", with a why that says the X axes must point at the pole target. The wording varies between runs and is not always this clear.

**Clear Parent highlighted in the settings panel at the bottom left.** After the choice is made, Blender keeps its name in that panel. Matches inside it are no longer taken for the pop-up. Checked in real Blender: with the pop-up open the choice is highlighted; after Clear Parent has really run, nothing is.

**The test harness** was wrong in one way that mattered: a pop-up left open by one screen stayed open on the next and spoiled it (some earlier screenshots show it). The driver now closes it between screens.

**Still open:** setting the pole bone twice (2:42 to 2:48) is not captured; the first controller bone is only described by its job; Maya and Houdini are not on v14; extraction varies run to run (19 to 24 steps for this video in the last runs, 41 to 49 after the split), so I would repeat any prompt change three times before trusting it.


## Fourth round (24 Nov, night): "setting the pole bone twice", and v14 on all three applications, three runs each

**What happens at 2:41 to 2:56 (read in the video).** In the IK constraint panel he fills the Pole Target field with the eyedropper and picks the Armature object. Only then does a second field, Bone, appear under it, and he says "then I can select one more time this bone": a second eyedropper pick, of the knee controller. After the second pick the leg turns ("but as you can see it rotates the foot all the way around"), which the next steps fix.

**Why it was missing.** A setting that takes two choices (an object, then which bone or channel of it) was folded into one line. The prompt told the model to keep a step to 1 to 3 how-to lines and never to split one operation, and nothing told it that a second field appears after the first, or that "one more time" is a second choice. The narration is only "this bone" twice, so the model had no wording of its own to copy. This is not about bones: it is any panel whose second field depends on the first (an object then a bone, a target then a channel, a type then its options).

**Generic fix.** v14 has a rule for settings that take two choices: one how-to line per choice, in order, each field named as the screen labels it, and a line saying that the second field appears after the first (4 lines allowed for such a step). The rule names no tutorial, bone or app.

**Result, three runs of the leg IK video:** one run writes it fully ("use the Pole Target eyedropper to select the Armature object, then set the Bone field to the front knee controller bone"); one names the second field but as one line ("under Pole Target > Bone"); one writes a different step layout in which the pole target step is not recognisable. So it is better, not reliable: about one run in three.

### v14 against v12 and v13, three runs per application on both labelled videos of each

Mean of three runs, range in brackets. "Words found" and "step support" are the labels-based scores used since the first report. "Why words" is the mean length of the reason. "Demo" counts steps that test, observe or demonstrate; "directions" counts steps that say left, right, up, down, forward, back and the like.

| | Steps (after the split) | Words found | Step support | Why words | Demo steps | Direction steps |
|---|---|---|---|---|---|---|
| Blender v12 | 18.2 (28.0) | 90.9% (88–94) | 97.2% | 11.3 | 3.8 | 8.8 |
| Blender v14 | 20.8 (29.0) | 91.2% (91–92) | 97.5% | 13.9 | 5.0 | 11.5 |
| Maya v12 | 9.7 (16.0) | 78.6% (74–82) | 98.7% | 11.5 | 0.5 | 4.3 |
| Maya v14 | 12.3 (21.0) | **87.7%** (83–91) | 100% | 14.7 | 1.5 | 7.2 |
| Houdini v13 | 11.5 (20.2) | 64.4% (58–70) | 93.2% | 12.5 | 2.5 | 1.7 |
| Houdini v14 | 11.5 (20.5) | **72.2%** (70–76) | 94.4% | 13.7 | 2.7 | 2.7 |

Read by hand: Maya gains steps such as maximising the perspective view before renaming, and a test step; Houdini gains a "test the FK controls" step and fuller reasons. Blender is level on the scores and has more test steps, directions and longer reasons.

Because of this every application now uses v14 (`RECOMMENDED_VIDEO_PROMPT`). The rewrite of "do the same thing with this bone" fired once in the 18 new extractions (the leg IK video, as it should) and nowhere else.

**One thing to watch.** On the Maya leg video the joint names came out as `leftThigh` in 2 of 3 v14 runs and as `left_thigh` in the first (v12: camel case in all 3). One run in three is not enough to say, but exact names are what a learner types.

Cost: about $1.35 for the 18 extractions of this round.

## Fifth round (25 Nov): which prompt made the good tutorial, and the defaults

**What was compared.** The learner found the newest tutorial in the tester account (`blender test 6`, made by the app at 11:30 on 23 Nov) much better than the ones made later, and asked to go back to "v13". It was not v12 or v13: v13 is the Houdini prompt, and Blender used v12 until that morning. The tutorial has a "test IK movement / knee twisting" step and a "Pose > Clear Transform > All" step, which only v14 produces. So it came from v14 as it was at that time, before the rules added afterwards.

**What was done.** The rules added afterwards (what to expect when nothing happens, two choices in one setting, cause and effect, never name a bone the video does not, a value with its test) are now **v15**. **v14** is back to the text it had when the learner liked its output. Nothing is lost: both are selectable (`--prompt-version`).

**Three runs on each of the six labelled videos** (cost about $1.35 each time). Mean of three runs, "words found" and "step support" from the labels:

| | Steps (after split) | Words found | Step support | Test/observe steps |
|---|---|---|---|---|
| Blender v12 | 18.2 (28.0) | 90.9% | 97.2% | 3.8 |
| Blender **v14** | 18.5 (28.3) | **94.2%** | **98.9%** | 4.7 |
| Blender v15 | 20.8 (29.0) | 91.2% | 97.5% | 5.0 |
| Maya v12 | 9.7 (16.0) | 78.6% | 98.7% | 0.5 |
| Maya v14 | 13.5 (23.2) | 81.7% | 90.9% | 1.8 |
| Maya **v15** | 12.3 (21.0) | **87.7%** | **100%** | 1.5 |
| Houdini v13 | 11.5 (20.2) | 64.4% | 93.2% | 2.5 |
| Houdini v14 | 11.5 (20.5) | 67.3% | 90.6% | 2.8 |
| Houdini **v15** | 11.5 (20.5) | **72.2%** | **94.4%** | 2.7 |

So the defaults are now **Blender v14, Maya v15, Houdini v15**, each the best of the three on its own application.

**What the numbers do and do not say.**
- They do not show that the later rules made Blender steps coarser (v14 18.5 against v15 20.8 steps); the leg IK video alone gave 30, 18 and 22 steps in three runs of the same v14 prompt, and 27, 27 and 25 with v15. The same prompt varies that much from run to run.
- Steps that name clearing or removing a parent, and steps that name Keep Offset, are the same in number across v12, v14 and v15 on that video (3 and 1 to 2). The knee controller's parent and keep-offset steps being present or merged in one extraction is therefore mostly luck of the draw, and the good tutorial was one good draw. Nothing here fixes that variation.
- What the labelled scores cannot see is how well each step maps to something the guide can highlight; that was checked on the leg IK video only (48 of 49 steps got a rectangle for v14).
