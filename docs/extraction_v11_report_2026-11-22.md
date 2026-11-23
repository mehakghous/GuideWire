# Tutorial step extraction: what was wrong, what changed, how it was checked (22 Nov 2026)

> **Update, same day: the app now uses v12, not v11.**
>
> Tried in the app, v11's steps were too big: "each step is so many mini steps". The screenshot showed one step with move, rotate, scale and three extrudes. On Blender leg IK, the guide then stuck on "Add > Armature" inside such a step.
>
> **v12** is v11 with only the step-size rules changed. Its accuracy rules, its "why" and its use of both sources are word for word v11's. The new rules: one operation with one visible result per step, in 1–3 how-to lines; a mode switch is a step of its own; each item that gets its own name or value is its own step; only selecting and opening menus are folded in.
>
> Same 6 tutorials, three repeats ($1.23, 20 paid calls including retries):
>
> | | Steps | Words found | Step support | Copied names | With a why |
> |---|---|---|---|---|---|
> | Before (v10) | 17.7 | 73% | 88% | 1.6 / video | 0% |
> | v11 | 6.8 | 84% | 98% | 0 | 100% |
> | **v12** | **12.5** (Blender 18.2, Maya 9.7, Houdini 9.7) | 78% | **98%** | **0** | **100%** |
>
> Read by hand: the Blender leg-IK tutorial gives 25 steps in the earlier division, with v11's accuracy (R 90, Roll 90, Head/Tail 1.0, Keep Offset, real bone names). "Pose > Clear Transform > All", which v11 dropped, is back. Still missing: Pole Angle 0 as an action.
>
> **The guide stuck inside a step** was a separate bug (`app/step_state.py`), which smaller steps make rarer but do not remove:
> - an "Add" menu could never count as done;
> - a mode key (Tab) was never something the guide could point to;
> - the step's starting-mode requirement sent the learner back once they had changed mode as part of the step.
>
> All three are fixed and covered by tests in `tests/test_step_state.py`. The guide now goes Add > Armature → Edit Mode → In Front.
>
> **Highlighting was worse with v12, and this is now fixed.** v11 and v12 no longer give the model the list of Blender's menu names. Their steps wrote UI names in short forms that `ingestion/targets.py` did not know: "Edit Mode", "Mode", "Move", "Properties > Bone Constraints", "Viewport Display > In Front", "Item > Roll", "Toolbar > Scale Tool", "… Panel > Number of Cuts", "Armature Context Menu > …", "Clear Parent" after Alt+P. Unresolved names fall back to searching the screen for the words. The resolver now accepts those forms. A single word that is also a tab name ("Bone") is still not guessed.
>
> On the recorded Blender runs:
>
> | | UI names resolved | Steps the guide can point at | Steps with only a weak text guess |
> |---|---|---|---|
> | v10 (before) | 65–91% | 72–80% | 0–3% |
> | v12, before the fix | 71–90% | 69–85% | 9–42% |
> | **v12, after the fix** | **93–96%** | **83–88%** | **3–6%** |
>
> The new in-step guidance rule removed no highlight at the start of any of the 95 v12 steps that have targets. Targets are resolved every time a session loads, so tutorials already saved benefit without extracting again. Not checked in a real Blender here.
>
> The v11 report below stands as the record of what was wrong and what v11 fixed.

## Houdini (22 Nov 2026, after v12): prompt v13, the gap pass and a parameter-label check

**What was wrong.** Almost all of Houdini's weakness is on the APEX FK tutorial (`xWnI7is6e7Q`): v12 misses 13 of its 51 core labelled actions in every run, against 2 of 17 on the APEX IK tutorial. Reading the runs showed:
- **Steps too big.** v12's Houdini rule ("a node is usually one step") bundles several settings.
- **A stretch skipped.** 3:40–4:55 (F for Modify mode, moving skeleton points, merging chains) is left out or reduced to one vague step.
- **Labels and values misread.** No run of any prompt ever reads Control Group, Use Color or the 4.1 offset. Most runs write **Target Pattern**, which Houdini 22 does not have on any node in its parameter list.

**Correction to the v11 report.** "Target Pattern" is not only copied from the v10-hou prompt: v12 and v13 write it with no such name in their prompts, and in `visual_evidence` the model says it sees it. "Component Source" is a real parameter of APEX AutoRig Component, so it was not a leak.

**What changed:**
- **Prompt v13** (`ingestion/extract.py`). It is v12 with the Houdini block rewritten: creating and connecting a node is one step; each parameter change, viewport-state key (F, Enter) and placed or moved element is its own step, with the exact label and value. For Blender and Maya it is v12 word for word. v11 and v12 are verified unchanged.
- **Gap pass** (`fill_gaps`, `--fill-gaps`). Every uncovered stretch of 25 s or more inside the tutorial gets one look at just that clip. The model may answer that nothing happens there; that answer is accepted without a retry. Added steps are flagged, repeats are dropped, and a failed call keeps the first pass.
- **Parameter-label check** (`ingestion/houdini_parms.py`, in the validator for Houdini). A label a step says it sets is checked against Houdini 22.0.466's own parameters for the nodes the step names. An unknown label is flagged for review. It never judges a node the list does not cover (Attribute Wrangle, Merge…), nor APEX AutoRig Component, whose parameters come from the chosen component. On all 618 recorded Houdini steps it flags 36. Read by hand, nearly all are real mislabels ("Folder Name 1" where Houdini says Name, "Target Pattern" where it says Control Group).

**Results.** Both Houdini tutorials, three repeats each, `gemini-3.6-flash`, about $0.60:

| | FK tutorial: steps | FK: words found | IK tutorial: steps | IK: words found | Step support (both) |
|---|---|---|---|---|---|
| v12 | 9.3 (8–11) | 58% | 10.0 | 73% | 93–100% |
| v13 | 12.0 (11–14) | 52% | 11.0 | 77% | 89–98% |
| v13 + gap pass | 12.3 (11–15) | 54% | 11.0 | 77% | 89–98% |

What the FK runs contain (out of 3):

| | Merge stage covered | F / Modify mode | Control Group, Use Color, 4.1 | "Target Pattern" |
|---|---|---|---|---|
| v12 | 2 | 0 | 0 | 2 |
| v13 | 3 | 0 | 0 | 3 |
| v13 + gap pass | 3 | 1 | 0 | 3 |

**Reading.**
- **v13 gives Houdini the step size the other applications have** and covers the merge stage more reliably. The word-overlap numbers do not move beyond the run-to-run spread, so it is not shown to be more accurate.
- **The gap pass found something in 1 of 6 stretches it looked at.** That was the F / Modify-mode stretch, the main omission. It costs one call per stretch.
- **The labels are a reading limit, not a prompt problem.** The check is what keeps them from passing silently.

**Not measured:** a held-out Houdini tutorial; whether a second, clip-level pass given the node's real parameter list would correct the labels (the next thing to try).

**Label repair (22 Nov 2026, `ingestion/label_repair.py`).** Each Houdini step whose label Houdini does not have on that node gets one look at its own clip, given that node's real parameter list. A correction is accepted only when all of these hold:
- it is an exact label from the list;
- the model says it saw it, with evidence;
- when the step gives a value, the clip's value for that parameter is the same value.

Otherwise the flag stays, with the reason. A correction replaces only the label words, and the step gets a note saying what changed and where to check.

Tried on all 30 flagged labels of the recorded v10-hou, v10-houpreds, v12 and v13 Houdini runs (`scripts/repair_labels_eval.py`):
- **First version, no value check ($0.20):** 23 corrected, 7 kept. One correction was clearly wrong: "Target Controls" (set to `point.*`) became Shape Override, a different parameter changed in the same clip.
- **With the value check ($0.21):** 16 corrected, 14 kept.
  - "Target Pattern" → **Group** 7 times (where `point*` is typed), "Target Points" → **Control Group** once.
  - Pack Folder labels → **Name** 6 times.
  - "Configuration 1 target" → Name.
  - "Folder Name" → Parent Folder (value matched, unconfirmed).
  - The wrong correction above is now kept.

Read against the labels, no accepted correction contradicts them. Two caveats:
- Houdini lists both **Group** and **Control Group** on APEX Configure Controls, and the model chose each at different times. The labeller wrote "Control Group".
- In 2 cases the value check found the step's **value** wrong as well: the clip shows "joint" where the step says `jnt_*`. The labels agree ("change the Control Group from point to joint"). Those steps stay flagged. Correcting values is a possible next step.

The app runs the repair for Houdini videos after the gap pass, only when a step is flagged.

**Decision (22 Nov 2026).** The app now uses **v13 with the gap pass for Houdini videos** (`RECOMMENDED_VIDEO_PROMPT`, `GAP_PASS_APPS` in `ingestion/extract.py`; `app/pipeline.py`). The reasons are the step size and the recovered Modify-mode stretch, not a measured accuracy gain. Blender and Maya stay on v12. The gateway and the command line use v13 for Houdini as well; the command line runs the gap pass only with `--fill-gaps`.

**Goal.** Steps that accurately reflect what the tutorial shows and explains. Each step is a meaningful operation the learner performs, not every click, built from both the screen (what, where, values) and the narration (why). Quality over quantity.

**Result in one line.** Prompt v11 replaces v10-preds and v10-hou for every video:
- **Steps:** 17.7 → 6.8 per tutorial.
- **Setup-only steps** ("switch to Pose Mode", "select X"): 16% → 0%.
- **Names copied from the prompt instead of read from the screen:** 4.8 per Houdini video → 0.
- **Steps that match something the instructor did:** 88% → 98%.
- **Labelled core actions found in a step:** 73% → 84%.
- **Steps with the instructor's reason:** 0% → 100%.

The same 6 real tutorials, labelled by hand, were run three times with each prompt. Houdini is still the weakest application, and some exact values in Houdini's parameter pane are not read by either prompt (§5).

## 1. How the pipeline used the video and the narration (before)

- **Input.** The app sends the public YouTube link to Gemini (`ingestion/providers/gemini.py`, `FileData(file_uri=…)`). The model therefore hears the narration and sees the picture together, at Gemini's default sampling of 1 frame per second. Visual and spoken information were **not** processed separately.
- **No transcript.** No transcript is fetched in the product path (`extract_from_video` accepts user-supplied cues but `app/pipeline.py` passes none).
- **Timestamps** come from the model and are checked against the video length (`check_structure`).
- **After the model:**
  - `compose_instructions` fills how-to and check lines and attaches documented pitfalls from the knowledge base;
  - `derive_state` and `sanitize_and_annotate` validate the expected states and flag problems;
  - an optional second call groups steps for display.
- **Prompt.** The app used **v10-preds** (Blender, Maya) and **v10-hou** (Houdini). Both are v3 with blocks added over time: v5 "actionable", v6 knowledge, v8 "atomic", v9 "coverage", v10 "no padding", plus the predicate or Houdini rules.

## 2. What was wrong

Found by reading the recorded runs (`runs/compare/gemini-3.6-flash/`) step by step against the human labels (`eval_data/gold/`).

1. **The prompt demanded micro-steps, and its rules contradicted each other.**
   - v3: "one step per distinct operation". v5: "split a compound action". v8: "ONE step per independent operation the learner performs, however small … many dozens of them". v9: "do not leave a stretch of more than about 15 seconds without a step". v10: "never pad".
   - Results: 24% of Blender and Maya steps were only a mode switch, a selection or opening something; the Blender leg-IK run had 7 steps of the form "Switch to Edit/Pose/Object Mode"; renaming five Maya joints became five steps.
   - The coverage rule also pushed the model to fill gaps. In one Houdini run it invented "Create additional Skeleton nodes", which the instructor does not do.
2. **Example names in the prompt were copied into the steps.**
   - The Houdini rules gave the examples *"set Component Source to FK Transform"* and *"type jnt_\* in Target Pattern"*. "Target Pattern" appears 19–46 times in runs with those rules and **0 times** without them. The instructor never shows it: he uses the **Control Group** field and the **Component** dropdown set to **FK**.
   - The learner was told to look for fields that do not exist, about 4.8 such names per Houdini video.
3. **There was nowhere to put the why.** The narration was used only as "evidence". The step record had no field for the instructor's reason (why the pole target is unparented, why mirroring needs "left"→"right"), so that teaching was lost.
4. **Instructors' on-screen mistakes were lost.** In the Maya leg video the instructor mirrors across the wrong plane, undoes it, and picks YZ. The steps went straight to YZ and the lesson disappeared.
5. **Irrelevant documented pitfalls were attached to steps.**
   - `compose_instructions` added *every* knowledge-base pitfall for a step's feature tag. A step that only adds an FK node got a warning about the "Multi IK Segments" field; a renaming step got "Stash Input" warnings.
   - These were stored in `common_mistakes`, which is now shown to learners as "Watch out".
6. **Vague lines passed silently.** "Adjust shape scale/offset to enlarge control shapes" appears where the instructor typed a value. No check caught it.

## 3. What changed

All changes are targeted. Earlier prompt versions are frozen and unchanged, so every earlier measurement still describes what it measured.

| File | Change |
|---|---|
| `ingestion/extract.py` | **Prompt v11**, a single rewritten prompt (not more blocks on top of v10). It says: use the screen for what, where and values, and the narration for why; a step is one meaningful operation, decision or milestone, with its clicks, keys and values in `how_to`; fold mode switches, selections and opening things into the step they serve; group settings on one node or dialog, and repeats over several items; start a new step at a checkable result or a change of purpose; never split or merge to change the count; keep the order and exact names; never invent; an on-screen mistake becomes `common_mistakes`, not steps; a demonstration of the result goes in `check`. **Every example is a `<placeholder>`.** The documentation menu list is not included. v11 is now the recommended prompt for every video, Blender non-rigging videos included. |
| `ingestion/extract.py` | `why` added to the v11 model schema and made required (the model skips optional fields), with null allowed when no reason is given. Older versions' schemas and cache keys are unchanged. |
| `shared/step_record.py` | `Step.why` (schema **0.15**, additive). |
| `ingestion/instructions.py` | A documented pitfall is attached only when it concerns the step: at least two distinctive words in common with what the step says (`concerns_step`). On the v11 runs, 58 attached pitfalls became 41; every irrelevant Houdini one was removed, and the relevant ones stayed (knee flip on IK steps, selection order on parenting, pole placement). |
| `ingestion/validate.py` | `vague_value` flag: a how-to line that adjusts, tweaks or picks a "custom" value without giving one is flagged for review. It flags 6 of 1,005 real lines, all genuinely missing a value. |
| `app/ui/screens.py` | Session and review screens show **Why** before the how-to lines and **Watch out** (`common_mistakes`) after them. |
| `scripts/score_meaningful.py` | Scorer for meaningful steps (below). |
| Tests | `tests/test_prompt_v11.py` (no copyable examples in any v11 prompt; no atomic or coverage rules; `why` required for v11 only; older schemas untouched; why and mistakes survive parsing; the pitfall filter; the vague-value flag) and `tests/test_app_step_detail_why.py`. Tests that pinned the old recommendation and the schema version were updated on purpose. |

## 4. How it was validated

**Tutorials.** The 6 real YouTube tutorials that have human labels:

| Application | Video id | Tutorial | Length |
|---|---|---|---|
| Blender | `EBgHRd5tJfE` | Armature | 4:27 |
| Blender | `PctSMB-RGsM` | Leg IK | 6:26 |
| Maya | `8RqfDcoP0jI` | Quick Rig | 3:10 |
| Maya | `TmhC35PqZvQ` | Leg IK | 6:32 |
| Houdini | `LJeap3wpyJA` | APEX IK | 6:17 |
| Houdini | `xWnI7is6e7Q` | APEX FK | 6:37 |

Each tutorial has 25–62 labelled actions. Every run used `gemini-3.6-flash` through the cost guard. v11 was run **three times** per video (18 extractions, all valid). The baseline is the three recorded repeats of the prompts the app used. One labeller wrote the labels; there is no second labeller for these six.

**Measures** (`scripts/score_meaningful.py`; the labels list small actions, so one good step covers several):
- **words found:** labelled core actions that fall inside a step's time span and whose words the step contains. Longer steps find words more easily, so this is read together with the others.
- **step support:** steps that match at least one labelled action.
- **setup-only:** steps that only switch mode or view, select, or open something.
- **copied names:** prompt example names found in the steps but absent from the labels.

**Mean of 3 runs per video:**

| | Steps | Words found | Step support | Setup-only steps | Copied names / video | With a why |
|---|---|---|---|---|---|---|
| Blender, before | 19.8 | 87% | 95% | 24% | 0 | 0% |
| Blender, v11 | 7.3 | **94%** | **100%** | **0%** | 0 | 100% |
| Maya, before | 17.5 | 77% | 93% | 24% | 0 | 0% |
| Maya, v11 | 5.3 | **90%** | **100%** | **0%** | 0 | 100% |
| Houdini, before (v10-hou) | 15.7 | 56% | 77% | 1% | 4.8 | 0% |
| Houdini, v11 | 7.8 | **69%** | **94%** | 0% | **0** | 100% |
| **All, before** | 17.7 | 73% | 88% | 16% | 1.6 | 0% |
| **All, v11** | **6.8** | **84%** | **98%** | **0%** | **0** | **100%** |

Run-to-run spread for v11: 6.2–7.5 steps; words found 84–85%; support 94–100%.

**Read by hand against the labels, using your checklist** (one v11 run per video in full; the others spot-checked):

| Check | Finding |
|---|---|
| Every step corresponds to something demonstrated or explained? | Yes in all six. The invented Houdini "create additional Skeleton nodes" step and the "Target Pattern" field are gone. |
| Important actions missing? | **Blender leg IK:** "Pose > Clear Transform > All" (2:29) and setting Pole Angle to 0 as its own action (the lesson is in Watch out). **Houdini FK:** Pack Folder type, the component name "FK", Use Shape Offset with 4.1, Use Color, and the "\*" in the promotion-group fields (§5). **Maya:** none of substance. |
| Unnecessary micro-steps? | None: no mode-switch, selection-only or open-only steps in any run. |
| Related actions grouped logically? | Yes. Maya: build chain, name joints, mirror, IK left, IK right. Blender: armature, leg chain, controller bones, IK, pole and roll, foot setup, bind and test. Houdini: one step per node with its settings. Maya step 1 is long (11 lines) but is one operation. |
| Can a beginner follow without guessing? | Blender and Maya: yes, with exact keys and values (R 90, Roll 90, Head/Tail 1.0, Keep Offset, YZ, "left"→"right"). Houdini: mostly. Vague lines remain where values were not read, and are now flagged for review. |
| Whole tutorial, start to end? | Yes in all six; the last step reaches the tutorial's final stage (bind and test, IK on the second leg, multi-chain FK). |
| Instructor's mistakes? | Captured as warnings with the fix (Maya wrong mirror plane; Blender pole angle vs bone roll; Maya joints placed in Perspective view). |
| Is the why true? | Consistent with what the labels record the instructor saying and doing. Some reasons are generic ("to establish the main deform skeleton") but none contradicts the tutorial. **Not verified word for word:** no transcripts are stored for these six videos. |

**Extra experiment: Houdini at high resolution.** v11 was run with `--media-resolution MEDIA_RESOLUTION_HIGH` on both Houdini videos ($0.19 in total). Token use was unchanged (about 49k), so the API ignores the setting for YouTube links, and the scores were no better. Not adopted.

**Cost.** $1.32 actual in total, on `gemini-3.6-flash` (`runs/budget/cost_log.jsonl`, 23 paid calls): $1.13 for the 18 v11 extractions and their retries, and $0.19 for the resolution experiment.

## 5. Limits and what is still wrong

- **Houdini parameter values.** Neither prompt reads "Control Group", "Use Color" or the 4.1 offset on the FK video, so this is a perception limit of a YouTube link sampled at 1 frame per second. v11 no longer invents a plausible wrong name, but it writes a vaguer line, which is now flagged. Fixing it needs more information per frame (the video's own frames at higher resolution, or the captions) or the learner editing the step. The step editor can only edit the goal today (audit I-3).
- **The model never says "not readable"**, though v11 asks it to. The vague-value flag covers the commonest case; it is a heuristic.
- **Evidence base.** 6 videos, 2 per application, one labeller, one model. The same videos were used to diagnose the problem and to measure the fix, so the numbers are optimistic; a held-out set (audit I-1) is still needed. The word-overlap measures are not a judge of meaning.
- **"Why" is plausible, not proven.** It is checked against the labels, not against the narration's words.
- **Fewer, longer steps change two things downstream.** Each step now has more than one thing to verify, and its time range is wider for the video. A session step completes only when its whole expected state holds, which is the intended behaviour.
