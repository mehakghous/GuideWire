# Evaluation and improvement report: step extraction, tutorial signals, question answering (2026-11-09)

Every number below was RUN on the repository as it stands in this branch, unless it sits under a heading that says PROPOSED. **Verified** = measured here. **Reading** = a judgement a person made from the output. **Proposed** = not built and not measured.

Method limits that apply to everything: 6 tutorials (2 Blender, 2 Maya, 2 Houdini), one human labeller (Ayesha; no second labeller, so how much people differ is unknown), one run per video, the cheap model `gemini-3.5-flash-lite`. The stronger model was at capacity (HTTP 503/504) every time it was tried, so no result here says anything about it. Gold = the labeller's own sheets in `eval_data/labels/`, converted by `scripts/labels_to_gold.py`.

## 1. Extraction accuracy evaluation

### 1.1 What was measured
Gold = the labeller's list of every action in the video (25 to 62 per video). The older score matched one step to one gold action, which caps recall at the step count when a step covers several small actions, so two scores are reported (`ingestion/eval/phase1.py`):

* **One-to-one recall / precision** (the strict, old method): a step may match only one gold action.
* **Span-and-words recall** (`text_recall_core`): a core gold action counts as found when it starts inside some step's time span (plus 5 s) AND the step's text (goal, result, how-to lines, UI names) contains at least half of the action's words. **Step support** = share of steps with at least one gold action inside the span whose words the step contains (a step with none is invented, mistimed or about something the labeller did not list).

These are word-overlap measures, not a judge of meaning. They were checked at word thresholds 0.34, 0.5 and 0.67 and time tolerances 3, 5 and 10 s (9 settings): the comparison of v7 and v9 on words found and step support points the same way at all nine (v7 at least as high).

### 1.2 Baseline (prompt v7) against the human labels, 6 videos
| Video | Steps | Gold actions | Words found in span | Step support | One-to-one recall |
|---|---|---|---|---|---|
| Blender armature (4:27) | 11 | 25 | 92 % | 100 % | 44 % |
| Blender leg IK (6:26) | 13 | 61 | 86 % | 100 % | 27 % |
| Maya quick rig (3:10) | 6 | 37 | 81 % | 100 % | 23 % |
| Maya leg IK (6:32) | 4 | 48 | 81 % | 100 % | 8 % |
| Houdini APEX FK (6:37) | 7 | 62 | 39 % | 100 % | 8 % |
| Houdini APEX IK (6:17) | 9 | 25 | 59 % | 100 % | 35 % |
| **Mean** | 8.3 | | **73 %** | **100 %** | **24 %** |

Reading: every v7 step corresponds to something the labeller listed (nothing invented), but a v7 step swallows several actions: 4 to 13 steps for 25 to 62 actions, and in Houdini whole stretches of the video have no step (for example 221 to 295 s of one video).

### 1.3 Which kinds of action are missed (`ingestion/eval/small_actions.py`, 204 core actions)
Kinds are read from the labeller's words with patterns, and an action can have several kinds, so the figures are a sorting aid. v7, share found with the right words:

| Kind | Actions | v7 found | v9 found |
|---|---|---|---|
| selection | 52 | 90 % | 83 % |
| mode change | 16 | 75 % | 81 % |
| toggle or checkbox | 9 | 56 % | 67 % |
| tool selection | 17 | 65 % | 53 % |
| typed value or setting | 19 | 63 % | 63 % |
| naming | 13 | 62 % | 54 % |
| dropdown or option choice | 8 | 88 % | 75 % |
| keyboard shortcut | 3 | 33 % | 67 % |
| panel, tab or window | 5 | 100 % | 100 % |
| create or add | 43 | 74 % | 74 % |
| connect, parent or constrain | 21 | 86 % | 91 % |
| all "small" kinds | | 77 % | 73 % |
| all "major" kinds | | 78 % | 80 % |

Reading: small actions are not missed more than big ones overall (77 % against 78 %). The weak spots are toggles and checkboxes, naming, typed values, and tool selection (Maya 46 %), and the samples are small (3 to 19 per kind), so these are leads to check, not findings.

### 1.4 Prompts v8 and v9 (new, opt-in; v7 untouched and still the default)
The user's priority is atomic steps with nothing merged or skipped. v7 itself asks the model to group repeats and skip incidental changes, so two prompts were tried (`ingestion/extract.py`, tests in `tests/test_prompt_v8_v9.py`):

* **v8** = v7 + "ATOMIC STEPS": one step per independent operation however small (mode change, selection, tool, checkbox, dropdown, value, name, panel, shortcut, connection), never merge, do not skip an unmentioned operation that is visible, each step gets its own times.
* **v9** = v8 + "COVERAGE": no stretch of about 15 s with visible operations left without a step; reach the last operation.

Developed on three videos (Blender armature, Maya quick rig, Houdini IK), then run once on the other three (held out). Mean over all six:

| | steps | one-to-one recall | one-to-one precision | words found in span | time inside a span | step support | timestamp accuracy | video covered |
|---|---|---|---|---|---|---|---|---|
| v7 | 8.3 | 24 % | 87 % | 73 % | 87 % | 100 % | 86 % | 55 % |
| v8 | 21.3 | 51 % | 85 % | 61 % | 79 % | 83 % | 96 % | 37 % |
| **v9** | 19.8 | **47 %** | 85 % | 69 % | 91 % | 90 % | 94 % | 45 % |

Held-out three only: one-to-one recall v7 14 %, v8 51 %, v9 47 %; words found v7 69 %, v8 62 %, v9 65 %. So the gain is not an artefact of tuning on the development set.

Reading: v9 roughly doubles the number of separately recovered actions and keeps one-to-one precision, but it is **not better on every measure**: step support falls from 100 % to 90 % (some small steps are mistimed or unmatched) and span-and-words recall falls slightly. **By application:** Blender one-to-one recall 35 % to 64 %, Maya 16 % to 52 %, Houdini 22 % to 26 %, and Houdini precision falls from 73 % to 66 % (step support 100 % to 79 %). Houdini does not benefit from v9; the cheap model is the likely limit but that was not tested.

**Decision recorded:** v9 is available as `--prompt-version v9` for detailed, beginner-level step lists on Blender and Maya; v7 stays the default; nothing is promoted for Houdini.

### 1.5 Looking for a setting between v7 and v9, and the 90 % target (cheap model)
The target set on 2026-11-09 is every extraction measure above 90 %, with a stronger model once billing is added. Two more settings were run on the cheap model, plus short clips:

* **v10** = v9 + "ONLY OPERATIONS": no step for inspecting, checking, explaining, preparing or planning, no repeated step for the same moment.
* **Windows** (`--window-s 60`): the video is shown to the model in overlapping 60 s clips (`...#t=start,end`), times are shifted back, overlaps are de-duplicated. A test showed the model's times are counted from the start of its clip. New: `extract_from_video_windows`, `video_windows`, `merge_window_steps`, the `--window-s` option, and `scripts/compare_prompts.py` to run any mix of settings.

Mean over the six labelled videos (one run each):

| Setting | steps | one-to-one recall | one-to-one precision | words found in span | time inside a span | step support | timestamp accuracy |
|---|---|---|---|---|---|---|---|
| v7 | 8.3 | 24 % | 87 % | 73 % | 87 % | 100 % | 86 % |
| v9 | 19.8 | 47 % | 85 % | 69 % | 91 % | 90 % | 94 % |
| v10 | 19.0 | 49 % | 94 % | 66 % | 86 % | 86 % | 94 % |
| v9 in 60 s clips | 27.5 | 54 % | 71 % | 69 % | 93 % | 74 % | 91 % |

Reading: no setting is above 90 % on every measure, and none is a clean "between v7 and v9". The measures that can pass 90 % do so at different settings: one-to-one precision 94 % (v10), step support 100 % (v7), time inside a span 93 % (clips), timestamp accuracy 94 % (v9 and v10). The two recall measures stay far away at every setting: words found at most 73 % (v7), one-to-one recall at most 54 % (clips). Of the single-pass settings v10 is the most balanced (best one-to-one recall and precision of the atomic prompts, 49 % and 94 %) but it gives up step support (86 %) and words found (66 %) against v7; clips raise recall and lower precision (many extra steps, a quarter of them matching nothing the labeller listed). Houdini is the weak application at every setting (words found 29 to 59 %).

Honesty about this table: each cell is one run per video with a model that is not deterministic (temperature 0.2), and run-to-run spread was not measured, so differences of a few points are not evidence. The first v10 run used a prompt that was missing the per-application node examples because of a bug caught by a test (`test_v10_is_v9_plus_the_only_operations_rule`); the row above is the corrected rerun. A failure seen on the way (the model listing steps out of time order twice on one Maya video, which failed the whole video) is now handled by sorting by the model's own start times as a last resort, flagged on the steps that moved, and only when that is the only violation (`tests/test_video_windows.py`).

Two reasons the 90 % target cannot be judged from these numbers alone:
1. **The gold is coarser than the output in places.** Looking at the steps that matched nothing in a 60 s-clip run, many are real operations the labeller did not list as separate rows ("Select the FK node in the network editor", "Name the new node FK"), so precision and support are lower bounds for fine-grained output. Several gold rows are not operations at all ("Keep the default skeleton point names unchanged", "Locate the Rotation promotion group parameter"), which caps recall below 100 % for any prompt.
2. **The model is the cheap one.** The weakest results (Houdini: words found 40 to 59 %) look like model limits, not prompt limits; the stronger model was never reachable.

No further tuning on these six videos is advised: each prompt change was judged on them, so more changes would fit these videos, not videos in general. The next step is to run `scripts/compare_prompts.py --tier report --versions v7,v9,v10 --windows 0,60` the day the stronger model is available, and decide a default from that table (cost per setting is shown by `--dry-run`).

### 1.6 Does the knowledge base help extraction? (menu and option block, outline block)
Prompts v6 and later already carry a block of menu paths and option names taken from the knowledge base (`_knowledge_notes`), and v7 and later the application's real node names. A measured test, v10 on the six videos, cheap model, one run each:

* **v10-nokb**: the menu and option block removed.
* **v10** (current): the menu and option block.
* **v10-outline** (new, experiment): the menu block plus, for each topic of the application, the typical order of operations from the knowledge base ("Skeleton: create joints -> name them -> ..."), with the rule "use only to remember small operations and look for them; write only what the video shows". Selected with `--prompt-version v10-nokb` or `v10-outline`; v10 is unchanged.

| Variant | steps | one-to-one recall | one-to-one precision | words found in span | time inside a span | step support | timestamp accuracy |
|---|---|---|---|---|---|---|---|
| v10-nokb | 16.3 | 43 % | 87 % | 56 % | 71 % | 90 % | 99 % |
| v10 (menu and option block) | 19.0 | 49 % | 94 % | 66 % | 86 % | 86 % | 94 % |
| v10-outline | 21.0 | 51 % | 83 % | 67 % | 87 % | 82 % | 96 % |

Reading: taking the menu and option block out costs about 10 points of words found and 15 of time coverage, and 6 points of recall, which is the largest effect seen in any comparison here, so the knowledge base is doing real work in extraction (the model spells nodes and menu items as the application does and finds the operation they name). The outline block adds a little recall (51 % against 49 %, Houdini IK video 59 % against 41 %) but costs precision (94 % to 83 %) and step support (86 % to 82 %, Houdini IK 50 %): the pattern of a model copying a typical sequence instead of only watching. So the outline is not adopted; the menu and option block stays. Caveats: six videos, one run each, run-to-run spread unmeasured, so only the nokb-against-v10 gap is large enough to take seriously.

What this means for the knowledge base work: more entries WITH menu paths and official option names help extraction directly (Houdini first, 25 entries today). Outlines should be used after extraction, to check for steps that are missing or out of order, not inside the prompt. The knowledge base does not help with timing, coverage gaps or granularity; those come from the model and the clip handling.

### 1.7 Not measured, and why
* **Order accuracy.** Step order follows time by construction and the validator flagged no order errors in any run, but order was not scored against the human order (it needs gold with an explicit dependency order).
* **Visual versus narrated support.** The labeller marked almost every action `both` (or, in one sheet, `said`), so a comparison against the model's `support` field has no variation to measure.
* **Actions never shown or said.** The model cannot be scored on actions the labeller also did not list.
* **The stronger model, repeat runs, and agreement between two labellers.**

### 1.8 Prompt v10 on `gemini-3.6-flash` (run 2026-11-09 evening, outputs in `runs/compare/gemini-3.6-flash/`)
Six labelled videos, one run each, `scripts/compare_prompts.py --model gemini-3.6-flash --versions v10 --windows 0,60`. Cost of this run from the cost log: about 0.74 USD for 31 calls (an earlier 3.6 Flash run on 8 Nov cost 0.446 USD for six calls).

One pass, all six videos:
| Model | steps | one-to-one recall | one-to-one precision | words found in span | time inside a span | step support | timestamp accuracy | checkable end state |
|---|---|---|---|---|---|---|---|---|
| cheap model (3.5 Flash-Lite), v10 | 19.0 | 49 % | 94 % | 66 % | 86 % | 86 % | 94 % | not recorded |
| **3.6 Flash, v10, one pass** | 17.8 | 41 % | 79 % | 76 % | 93 % | 92 % | 97 % | 54 % |

This reproduces the figures the labeller reported from the earlier run (41 / 79 / 76 / 93 / 92 / 97). Reading: the stronger model finds more of the right words and times and has fewer unsupported steps, but writes fewer, coarser steps, so the strict one-to-one scores fall. Only 54 % of its steps carry a checkable end state.

60 s clips: **incomplete.** Four of the six videos failed with HTTP 429 RESOURCE_EXHAUSTED (Gemini quota or billing), so only the Blender armature and Maya quick rig videos have clip results. On those same two videos:
| Setting | steps | one-to-one recall | one-to-one precision | words found | time inside a span | step support | timestamp accuracy |
|---|---|---|---|---|---|---|---|
| 3.6 Flash, one pass | 15.5 | 53 % | 93 % | 88 % | 100 % | 100 % | 100 % |
| 3.6 Flash, 60 s clips | 24.5 | 65 % | 80 % | 88 % | 100 % | 90 % | 94.5 % |

Reading, with n = 2 (a lead, not evidence): clips give about 9 more steps and 12 points more one-to-one recall, at a cost of 13 points of precision and 10 of step support; words found did not change. The same trade-off was seen with the cheap model (section 1.5). The four failed videos, including both Houdini videos, still need the run repeated once quota is available (the cost guard caches finished calls, so a repeat only pays for the missing ones). A second attempt the same evening failed on the same four videos.

### 1.9 Matching by meaning instead of shared words (new, opt-in; `ingestion/eval/meaning.py`, tests `tests/test_meaning_match.py`)
The words check misses synonyms ("log in" against "sign into the account"), so words found and step support were lower bounds. `--meaning iterate|report` (on `python -m ingestion.eval.phase1` and `scripts/compare_prompts.py`) now asks a model, in text only, once per video: for each of the labeller's actions it lists the steps whose time span contains the action and the model says which of them do that action. The time rule is unchanged, a step covering several actions is credited for each, and a step the model names that was not a candidate is ignored. Strict one-to-one recall and precision still use words. Default is still words.

3.6 Flash v10 one pass, six videos, judged by `gemini-3.5-flash-lite` (cost about 0.03 USD, cached):
| Video | words found, shared words | words found, meaning | step support, shared words | step support, meaning |
|---|---|---|---|---|
| Blender armature | 92 % | 100 % | 100 % | 100 % |
| Blender leg IK | 84 % | 92 % | 83 % | 96 % |
| Houdini APEX IK | 65 % | 82 % | 100 % | 100 % |
| Houdini APEX FK | 49 % | 86 % | 75 % | 100 % |
| Maya quick rig | 85 % | 85 % | 100 % | 100 % |
| Maya leg IK | 83 % | 83 % | 96 % | 87 % |
| **Mean** | **76 %** | **88 %** | **92 %** | **97 %** |

Reading: most of the gap is Houdini, where the model's step wording differs from the labeller's. **Treat the meaning numbers as an upper-leaning estimate.** A spot check of 10 of the 29 new Houdini matches (matched by meaning, not by words) found about 4 clearly right ("Create an Auto Rig Component node" and "Add an APEX AutoRig Component node"), about 4 plausible but loose, and 2 wrong ("Apply the FK component configuration" matched to "Test FK handles in viewport"). The judge is the cheap model, one run, not checked by a person. The stronger judge tier (`--meaning report`) returned HTTP 503 when tried, so it was not compared. Before quoting a meaning number, either rerun with the stronger judge or have a person check a sample of matched pairs. A bug found on the way: the model first returned whole "STEP s01: text" lines instead of ids, which scored zero on five of six videos; the parser now reads both, and a test pins it.

### 1.10 Overlay readiness and prompt `v10-preds` (run 2026-11-09 night; `ingestion/eval/phase1.py`, `ingestion/extract.py`, `tests/test_prompt_v10_preds.py`)
Two new structure numbers: **has-target** (share of steps with a named UI element or keys, so the overlay has something to point at) and **guidable** (share of mechanics steps with a target AND a checkable end state, so they can be highlighted and auto-completed).

Baseline, v10 on 3.6 Flash (six videos): has-target 100 %, guidable 54 %. Mechanics steps with an end state: Blender 25 of 38, Houdini 12 of 26, Maya 16 of 37. The model was offered seven kinds of state and used only mode, node_exists, active_tool, panel_open, workspace and selection_type; it never produced name_exists, attribute_exists, node_count or property_equals, so renames, option toggles and parameter edits had no end state.

`v10-preds` = v10 plus a block teaching name_exists (every rename), attribute_exists, node_count, and property_equals for a toggle or value; only this version sees the wider schema, older prompts are unchanged. Same six videos, 3.6 Flash, one run each, words found and support judged by meaning (cheap judge):

| | steps | one-to-one recall | one-to-one precision | words found (meaning) | step support (meaning) | time inside a span | timestamp accuracy | guidable |
|---|---|---|---|---|---|---|---|---|
| v10 | 17.8 | 41 % | 79 % | 88 % | 97 % | 93 % | 97 % | 54 % |
| v10-preds | 18.5 | 42 % | 76 % | 90 % | 99.5 % | 93 % | 97 % | 56 % |

Kinds produced by v10-preds: name_exists 8, property_equals 6, attribute_exists 1, node_count 1 (v10: none of these). Mechanics steps with an end state: 63 of 111 (57 %) against 53 of 101 (52 %); Maya 43 % to 56 %, Houdini 46 % to 52 %, Blender 66 % to 59 %.

Reading: **the model does use the new kinds and almost every rename now has an end state, but overall guidable rose only about 2 points, which is within what one run per video can move.** Blender wrote 54 mechanics steps in this run against 38 in the v10 run, so run-to-run spread is large and the comparison is a lead, not proof. Of the 48 mechanics steps still without a state, many are genuinely stateless (move or rotate a bone, open a shelf tab, maximise a panel, mirror guides), some could have used node_exists, property_equals or attribute_exists ("Add an APEX Add Character node", "Assign the Pole Target bone in the IK constraint settings") and were not given one, and connections have no kind at all. So **the realistic ceiling for guidable is below 100 % and probably nearer 70 %**, and the remaining gain would come from a second pass that fills states for steps the first pass left empty (from the step text and the knowledge base, checked against the node vocabulary), not from more prompt wording. Vision has not confirmed it can read the three newer kinds from a screenshot (architecture note, section 5).

### 1.11 Display groups: atomic steps for the overlay, grouped steps for the learner (plan item A1; `ingestion/grouping.py`, `tests/test_grouping.py`, schema 0.12)
Extraction keeps writing atomic steps (what the overlay points at and completion detection checks). Schema 0.12 adds two optional fields on a step, `group_id` ("g03") and `group` (a short label); consecutive steps with the same id form one display group. `StepList.groups` returns (id, label, steps) for every group and treats an ungrouped step as its own group, so a screen can always walk that one list; `StepList.group_problems` checks the rules. Steps are never merged, reordered or rewritten.

`python -m ingestion.cli group steps.json -o grouped.json` makes one text-only model call (no video; cost-guarded, cached) that decides where groups start and end and names them. Code checks the answer before use: every step in exactly one group, in order, each group a run of consecutive steps, label at most 80 characters, at most 12 steps a group. A rule-breaking answer is sent back once with the problem; after a second failure the list stays ungrouped with a warning (no guess), and a provider outage or budget stop keeps the steps and says so.

Run on the six 3.6 Flash v10-preds step lists with `gemini-3.5-flash-lite`: all six were grouped validly (one needed the retry). **111 steps became 46 groups** (Blender armature 18 to 8, Blender leg IK 36 to 16, Maya quick rig 16 to 5, Maya leg IK 16 to 5, Houdini FK 10 to 8, Houdini IK 15 to 4), total cost about 0.006 USD. Example (Maya leg IK): "Prepare to draw the leg joints (2 steps)", "Draw the leg joint chain (2)", "Rename the leg joints (6)", "Mirror the leg joint chain (3)", "Add the IK handles (3)". Reading: groups follow the tutorial's goals well where steps are fine-grained, and compress little where the steps are already coarse (Houdini FK: 10 steps, 8 groups). **Not measured:** whether a beginner finds the groups easier to follow than the flat list (that needs the user study), and group quality was read by one person, not scored against a labelled grouping. The labeller's sheets have no group column, so there is no gold for this.

Contract note for the app: the fields are additive (an app that ignores them still works), the schema version is now 0.12, and `docs/architecture.md` still says 0.10. The unused-kind test `test_app_step_loader` still fails for the reason in plan item E1.

### 1.12 Run-to-run spread (plan item A5) and the outline check (plan item A4)
**Spread.** `scripts/compare_prompts.py --repeats 3` asks the model again for repeats 2 and up and reports the mean and range. Gemini quota ran out part-way (HTTP 429, and 503 capacity errors), so only three of the six runs finished all six videos: v10 repeat 1, v10 repeat 2 and v10-preds repeat 1. Repeat 3 of v10 finished 4 videos, v10-preds repeats 2 and 3 finished 1 each; the script now leaves incomplete repeats out of the mean (before, it averaged them in, which gave a misleading 77 % guidable for v10-preds). Cost of the attempt from the cost log: about 0.80 USD for 36 calls, 12 of them errors.

The same prompt (v10) on the same six videos, run twice:
| Measure | repeat 1 | repeat 2 | gap |
|---|---|---|---|
| words found (meaning) | 88 % | 81 % | 7 points |
| guidable | 54 % | 47 % | 7 points |
| step support (meaning) | 97 % | 94 % | 3 points |
| one-to-one recall | 41 % | 42 % | 0.5 point |
| one-to-one precision | 79 % | 81 % | 2 points |
Per video the swings are larger: guidable on Maya quick rig was 53 % then 24 %, on Maya leg IK 36 % then 63 %, and the number of steps on Blender leg IK went 24, 28, then 36 with v10-preds. **Reading: differences of about 7 points on words found and guidable, and 3 on support, cannot be told from luck with one run per video.** That includes the earlier results: v10-preds (guidable 56 %) against v10 (54 % and 47 %) is inside the spread, so v10-preds is not shown to help, and the 76 to 88 % jump from meaning matching is a scoring change, not a run-to-run effect. One-to-one recall and precision were steadier (within 2 points). Any prompt change must be judged with several runs; the next Houdini test should use three repeats on the two Houdini videos only (about 12 paid calls, roughly 1 USD at the 3.6 Flash prices seen here), after quota is available.

**Correction to the spread table (found later the same night).** `--fresh` asks the model again but writes the answer into the same cache slot as the first run, so repeats 2 and 3 overwrote repeat 1: after the re-run, the repeat-1 files for the videos where a later repeat finished held the LATER answer (for example Blender leg IK went from 24 steps to 34, equal to repeat 3). The numbers in the table above were computed from the files as they were before that happened and are what was observed, but the original repeat 1 cannot be regenerated, so the table is not reproducible from disk. Fixed: `GW_REPEAT=n` (set by `compare_prompts.py` for repeats 2 and up) now enters the cache key (`ingestion/budget.py`, test in `tests/test_budget.py`), so each repeat has its own slot and repeat 1 keeps its old key. The spread conclusion (differences of about 7 points on words found and guidable are within run-to-run change) rests on repeat 2 against the lost repeat 1 and on the per-video swings seen at the time; it should be re-measured under the fixed keys before it is quoted.

**Houdini prompt `v10-hou` (A3): built, NOT measured.** Prompt v10 plus a Houdini node-network rule (a step per node created, per connection, per parameter with its exact value, per flag, per viewport state change; Houdini only, the other applications get the v10 text exactly; `tests/test_prompt_v10_hou.py`). The measurement (`compare_prompts.py --versions v10,v10-hou --apps houdini --repeats 3`, about 10 paid calls) failed on every call with HTTP 429 RESOURCE_EXHAUSTED: the Gemini quota for `gemini-3.6-flash` was used up by the earlier runs. No Houdini result exists yet.

**Outline check (A4).** `ingestion/outline_check.py` (tests in `tests/test_outline_check.py`, not wired into the CLI or extraction) compares a step list with the knowledge base's ordered outlines and returns hints "possibly missing" and "possibly out of order". On the six v10-preds step lists it raised 5 hints for 111 steps (4 missing, 1 order) and none of the 4 missing items is an action the labeller listed, so it found nothing a reviewer would have wanted. The outlines are too generic for these videos. Conclusion: not adopted; kept as a tested module only.

### 1.13 Complete repeats on `gemini-3.6-flash`: A5 (spread) and A3 (Houdini prompt), run 2026-11-10
Billing was added, so the runs that had failed on quota were made. Each setting was run 3 times on the labelled videos; every repeat has its own cache slot (`GW_REPEAT`, section 1.12), so no repeat overwrote another and all runs finished all their videos. Words found and support are judged by meaning (`gemini-3.5-flash-lite` as the judge); the cost of the A3 and A5 runs together was about 2.5 USD (35 paid calls).

**A5, six videos, one pass, three repeats (mean, with lowest to highest in brackets):**
| | steps | one-to-one recall | one-to-one precision | words found | time inside a span | step support | timestamp accuracy | guidable |
|---|---|---|---|---|---|---|---|---|
| v10 | 16.2 | 37 % (34-40) | 79 % (78-81) | 86 % (81-88) | 91 % (89-94) | 97 % (96-98) | 97 % (95-98) | 54 % (53-58) |
| v10-preds | 16.9 | 41 % (39-43) | 79 % (76-83) | 88 % (88-89) | 94 % (93-94) | 96 % (93-100) | 99 % (96-100) | **61 % (58-64)** |

**Reading.** Run-to-run spread of the same prompt over six videos is about 3 to 7 points depending on the measure (words found 7, recall 6, guidable 5, precision 3). **The only difference larger than that spread is `guidable`: v10-preds was higher than v10 in all three repeats (+6 points on average, ranges 58-64 against 53-58),** so teaching the 0.11 state kinds gives a small but consistent gain in steps that can be pointed at and auto-checked. Recall (41 against 37), words found and time inside a span are higher for v10-preds too, but their ranges overlap, so they are not shown. The earlier "7 points of luck" table (section 1.12) came from runs that had overwritten each other; the clean spread is a little smaller.

**A3, Houdini only (two videos), v10 against `v10-hou`:**
| | steps | one-to-one recall | one-to-one precision | words found | time inside a span | step support | guidable |
|---|---|---|---|---|---|---|---|
| v10 | 13.7 | 26 % (23-28) | 63 % (55-70) | 76 % (72-81) | 84 % (77-87) | 96 % (92-100) | 50 % (43-60) |
| v10-hou | 15.7 | **33 % (32-33)** | 62 % (48-76) | **84 % (77-95)** | 91 % (88-96) | 94 % (88-100) | 53 % (46-60) |

**Reading.** The Houdini node-network rule raises one-to-one recall from 26 % to 33 % with no repeat overlapping (its lowest, 32, is above v10's highest, 28), and words found by about 8 points (the ranges overlap), without losing precision or support. A real but modest gain: **Houdini remains the weakest application** (about 33 % recall, 84 % words found, about 50 % guidable). Two videos, so a lead for those two, not a result for Houdini in general. Not tested: `v10-hou` together with the 0.11 state kinds.

**Houdini, the Houdini rule together with the state kinds (`v10-houpreds`, same two videos, 3 repeats, 6 paid calls, about 0.45 USD):**
| | steps | one-to-one recall | one-to-one precision | words found | time inside a span | step support | guidable |
|---|---|---|---|---|---|---|---|
| v10 | 13.7 | 26 % (23-28) | 63 % (55-70) | 76 % (72-81) | 84 % (77-87) | 96 % (92-100) | 50 % (43-60) |
| v10-hou | 15.7 | 33 % (32-33) | 62 % (48-76) | 84 % (77-95) | 91 % (88-96) | 94 % (88-100) | 53 % (46-60) |
| v10-houpreds | 17.2 | 33 % (29-40) | 67 % (64-70) | 84 % (77-88) | 91 % (88-97) | 95 % (90-97) | 51 % (43-66) |

**Reading: the combination is not better than the Houdini rule alone.** Recall (33 %), words found (84 %) and time coverage are the same as `v10-hou`; precision is 5 points higher but its range sits inside `v10-hou`'s; `guidable` did not rise (51 % against 53 %). On Houdini the model almost never used the new state kinds (across the six runs: node_exists in every run, name_exists 4 times, property_equals once, node_count once), so there was little for them to add, and the number of steps jumped between repeats of the same video (16 to 31 on the Houdini IK video). Conclusion for Houdini: use `v10-hou`; the state kinds help on the six-video set (section above) because of Maya and Blender renames and toggles, not Houdini parameters. Two videos, so a lead.

**Defaults wired (2026-11-10).** For extraction from a VIDEO the default prompt is now chosen by these measurements (`recommended_video_prompt_version` in `ingestion/extract.py`): **Houdini `v10-hou`**, **Maya `v10-preds`**, **Blender `v10-preds` with `--rigging`** (the Blender measurements were on rigging videos), and a Blender video that is not about rigging keeps the modelling baseline `v2`. Used by `python -m ingestion.cli video` and the gateway's `/v1/extract` for a YouTube URL; an explicit `--prompt-version` still wins. Written text is not video and keeps `default_prompt_version` (v7 for Maya and Houdini, v2 for Blender). Effect on cost: the new prompts are a little longer, and the dry-run worst case for a 6-minute Houdini video is about 0.09 USD. Tests: `tests/test_prompt_v8_v9.py` (the choice, and the CLI picking it) and `tests/test_budget.py` (its Houdini dry-run now expects `v10-hou`).

**Gemini 4 Carbon, tried and set aside (2026-11-10).** The key can call `gemini-4-carbon` ("our most capable reasoning model" on Google's pages) and `gemini-4-argon`; both are priced at 2 USD in and 10 USD out per million tokens until 2026-11-30 (then 4 and 20), thinking billed as output (prices now in `ingestion/experiment.py`, test in `tests/test_budget.py`). One live run on the Houdini FK video: 31 steps against 11 from 3.6 Flash, one-to-one recall 65 % against 35 % and words found 88 % against 77 %, but one-to-one precision 36 % against 55 %, step support 65 % against 100 % and guidable 39 % against 55 %. Four finished Carbon calls cost 1.37 USD in total (0.18 to 0.66 each, mean 0.34, about 3 to 5 times 3.6 Flash), and **the cost guard's worst-case estimate (0.25 USD per video) was too low for it** (one call cost 0.66) because thinking is billed as output. Decision: stay on 3.6 Flash, because for an overlay that points at one control per step, many unsupported extra steps are worse than a few missing ones. One video, one run each: a lead, not a verdict on Carbon.

## 2. Tutorial quality and YouTube signals: dropped from the plan (decision 2026-11-09)

Views, likes and comments were collected for 12 videos and looked at. Result, in short: popularity did not predict how well a video can be extracted (an 82-view video scored the same as a 49,000-view one), like ratios barely differ between videos (1.2 % to 2.9 %), and dislike counts do not exist in the API since 2021. The project decided these signals will not be used, so there is no proposal and no plan item for them. The small helpers added for the look (`video_statistics` and `top_comments` in `ingestion/youtube/api.py`, `scripts/youtube_signals.py`, `tests/test_youtube_signals.py`) are not used by anything else and can be deleted without effect.

## 3. Realistic question-answering evaluation

### 3.1 What the answering layer is (verified from `ingestion/router.py`, `answer_kb.py`, `followup.py`, `gateway/app.py`)
The rule-based layer (before section 3.4) is a router, a Blender catalog and Blender manual index, a rigging knowledge base (45 entries), and follow-up resolution against a loaded step list. **In that layer no model is called and there is no model fallback** (`fallback_required` is returned to the caller; section 3.4 adds the model path). So "the system's own Houdini, Maya and Blender knowledge" means those local sources. A model-backed answer path, grounded on the knowledge base, does not exist; whether one would be better was not tested.

### 3.2 The suite (`tests/fixtures/qa_suite/questions.json`, harness `ingestion/eval/qa_suite.py`, tests `tests/test_qa_suite.py`)
48 questions: 10 each for Blender, Maya, Houdini without a video (30), and 6 per application with a loaded extracted step list (18). Tags cover spelling mistakes (`wat is the diffrence`), grammar, incomplete questions (`all my joints are at the origin`), wrong terminology (`ik handel`, `houdni`, `rp solver`), mode confusion (`i pressed tab and nothing happens`), missing options, timestamps, follow-ups (`ok whats next`, `go back to the pole target part`), and questions the tutorial cannot answer (`what render settings did he use`, `what houdini version is this`). Each has an expected behaviour, required and forbidden words, and a reference answer written from the application documentation, not by the system. The replies were all read and graded by a reviewer (`grades_2026-11-09.json`): **C** correct and useful, **P** partly, **N** no answer given (an honest clarifying question, a pointer, or the fixed deflection), **W** wrong or misleading. This is one reader's judgement, not a second labeller.

### 3.3 Results
| | Questions | C | P | N | W | Useful rate (C + P/2) |
|---|---|---|---|---|---|---|
| All | 48 | 8 | 4 | 32 | 4 | **21 %** (wrong 8 %) |
| No video | 30 | 3 | 2 | 25 | 0 | 13 % |
| With the tutorial loaded | 18 | 5 | 2 | 7 | 4 | 33 % |
| Blender | 16 | 4 | 3 | 8 | 1 | 34 % |
| Maya | 16 | 3 | 0 | 10 | 3 | 19 % |
| Houdini | 16 | 1 | 1 | 14 | 0 | 9 % |

**What works:** troubleshooting from the knowledge base (Blender automatic-weights failure, Maya flipping knee: correct, sourced, with steps); timestamp questions (`what is he doing at 2:10` named the right step three times out of three, with the quoted words); "what next" after "i did that"; joining objects; and honesty: no reply invented a fact, no forbidden claim appeared, and several said "the source does not say why this step is needed, so I will not guess".

**Defects found (each reproduced):**
1. **Maya and Houdini questions get a fixed deflection.** Outside the troubleshooting phrases, every question, concept, how-to or shortcut, gets "For maya I can turn a pasted procedure into steps. Put each step on its own line (at least two)." (24 of the 32 N replies). `router.py` sends every non-Blender message to the procedure parser.
2. **Wrong-step answers.** `why do we clear the parent of the knee controller` and `why did he change the solver to rp` were answered about the CURRENT step (s01, "create armature" or "select the Animation menu set") with "the source does not say why this step is needed". Honest wording, wrong step.
3. **Wrong application in the wording.** In a Maya session, `i dont see the mirror joint options box` got "Which Blender version are you using?".
4. **Wrong candidates.** `go back to renaming the joints` listed four create-joint steps and none of the six renaming steps; the Blender and Houdini versions of "go back" listed the right candidates.
5. **Spelling breaks Blender concepts.** `wat is the diffrence between object mode and edit mode` asked "which operation do you mean"; the same question spelled correctly gets a concept answer. `how do i make the skeleton symmetrical` found nothing; `symmetrize bones` works.
6. **Short follow-ups.** `next?` after `i did that` lost the session (fixed deflection); `ok then what` worked.
7. **Out-of-tutorial questions.** `what render settings did he use at the end` pointed to the manual's Render Settings page instead of saying it is not in the tutorial; `does this work in maya 2024` did not mention the tutorial is for Maya 2017.
8. **Knowledge not reached.** `my knee wont bend when i use ik` was declined ("nothing matches", best page `Spline IK`) although the knowledge base has IK bending causes; the answer to `how do i add ik to a leg bone` was the generic constraint page without Pose Mode or chain length.
9. **Garbled manual text.** `how do i extrude a bone` printed "Armature > Extrude (E); None (Shift-E)", a parsing artefact for "Extrude Forked".

### 3.4 The model-backed answering pipeline (built after the results above, same suite)
Decision: question answering should call a model and may use the knowledge base. `ingestion/answer_model.py` does that. For each question that does not change the learner's progress it sends a model (a) the 4 best-matching knowledge-base entries for the application (menu paths, options, facts, mistakes, symptom-to-fix, each with its trust tier), (b) for Blender the best manual passages, (c) the loaded tutorial's steps with ids and times and the current step, (d) the last few learner messages, under rules that say: read typos and wrong terms as a beginner meant them; use the context first and cite it; label general knowledge as such; never invent a menu path or value; never say the tutorial said what its steps do not show; say "not in the tutorial" and "not sure"; ask one question only when the answer would differ. Done, skip, go back, next and timestamp questions stay rule-based, because they change or read the session and the model must not (a test pins that). A provider outage or budget stop falls back to the rule-based answer and says so. Every call goes through the cost guard. Tests: `tests/test_answer_model.py` (10, scripted provider).

Two rule-based fixes were made along the way: `next?` alone is now recognised, and `go back to ...` ranks steps by how many asked words their goal has (before: the first four steps in the tutorial that shared any word).

Result on the same 48 questions with `gemini-3.5-flash-lite` (`python -m ingestion.eval.qa_suite --model-tier iterate`; replies graded in `grades_model_2026-11-09.json`, one reader, not independent):

| | Questions | C | P | W | N | Useful rate |
|---|---|---|---|---|---|---|
| Rule-based layer (section 3.3) | 48 | 8 | 4 | 4 | 32 | 21 % |
| **Model-backed pipeline** | 48 | **39** | 9 | **0** | 0 | **91 %** |
| Blender | 16 | 14 | 2 | 0 | 0 | 94 % |
| Maya | 16 | 13 | 3 | 0 | 0 | 91 % |
| Houdini | 16 | 12 | 4 | 0 | 0 | 88 % |
| No video / with the tutorial | 30 / 18 | 25 / 14 | 5 / 4 | 0 | 0 | 92 % / 89 % |

Cost: 40 text calls, about 0.03 USD in total (about 1,700 tokens each). Speed was not measured.

What it does well: it answers Maya and Houdini how-to and concept questions (IK handle, orient joint, Joint Capture Biharmonic then Joint Deform, Skeleton Mirror, IK Chains), reads through the typos in the suite, gives one real clarifying question for the vague question, says "the tutorial steps do not mention the version" and "they show no render settings", and labels general knowledge ("Part of this answer is general knowledge, not from GuideWire's sources").

What it still gets wrong or only partly right (the 9 P grades): two replies repeat official-tier knowledge-base statements that look wrong or imprecise and were not confirmed (APEX described as "the rigging engine underneath" KineFX; joint translation unchanged by freeze), and one points to the wrong thing for "show joint names"; a "why did he do this" question got a plausible reason labelled general knowledge instead of "the tutorial does not say"; "does this work in Maya 2024" says the steps work the same in 2024, which nothing supports; and three "go back to ..." questions tie between several steps and ask instead of choosing.

Limits: the 48 questions were written before the pipeline, but their failures shaped its prompt, so they are now a development set and 91 % is optimistic. A fresh set, graded by a second person, is needed before it is quoted as a result. The model path is reachable through `Service` (an `answerer` argument), the gateway (`POST /v1/answer` with `"model": true`, an optional brief `tutorial` of at most 120 steps and the last three messages; one capped, cost-guarded call; progress questions stay rule-based; `tests/test_gateway_answer_model.py`) and the terminal (`python -m ingestion.cli chat --model-tier iterate`; `tests/test_chat_model_flag.py`).

**Would completing the matrix help?** Yes, for answering and, in one specific way, for extraction. Each knowledge-base entry is context the model can cite instead of guessing: it raises the share of answers that are grounded and lets a wrong statement be fixed once (the two doubtful statements above were each repeated by the model because the knowledge base said them), and a wrong entry now has more reach, so entries need a confirming source. For extraction, entries with menu paths and official option names measurably help (section 1.6: removing that block from the prompt cost about 10 points of words found), while outline-style entries put into the prompt did not help (same section) and are better used afterwards to check extracted steps. The matrix percentage itself is a count of artefacts, not an accuracy measure, and the knowledge base does not fix timing, coverage gaps or granularity.

### 3.5 Beginner and first-steps questions, a fresh set (plan item B3; `tests/fixtures/qa_suite/questions_beginner.json`, grades in `grades_beginner_2026-11-09.json`)
36 questions, 12 per application, written BEFORE any change aimed at them, so unlike the 48 they are held out from the pipeline's development: where to start, what to do before rigging, make a skeleton, attach the mesh, a stretched character, IK on a leg, controls, FK versus IK, mirroring, which tutorial first, a flipping knee, and "i made the skeleton whats next". Several are typed with a level ("im new to ...", "im a beginner") or with typos. The frequencies are assumptions until the user study. Asked with no tutorial loaded, through the model path (`gemini-3.5-flash-lite`, one run, about 0.03 USD) and, for comparison, the rules only. Graded by one reader who is not independent (the same author as the pipeline's tests) and who also wrote the reference answers from the application manuals, so read it as a first look.

| | Questions | C | P | N | W | Useful rate |
|---|---|---|---|---|---|---|
| Rules only (automatic sort) | 36 | | | | | 5 of 36 passed the automatic checks; 9 answered, 24 asked a question or deflected, 3 declined |
| **Model path** | 36 | **25** | **11** | 0 | 0 | **85 %** |
| Blender | 12 | 9 | 3 | 0 | 0 | 88 % |
| Maya | 12 | 9 | 3 | 0 | 0 | 88 % |
| Houdini | 12 | 7 | 5 | 0 | 0 | 79 % |

On the 48-question development set the same pipeline scored 91 %; 85 % on fresh questions is the more honest figure (36 questions: a few questions move it by several points). No reply was graded wrong, and none invented a video or a link.

**One defect found and fixed.** "i made the skeleton, whats next" got the fixed deflection ("For maya I can turn a pasted procedure into steps...") in all three applications, because "what's next" is a progress command and was kept in the rules even with NO tutorial loaded. Progress commands (done, skip, back, next, a timestamp) now go to the rules only when a tutorial is loaded (`changes_progress` in `ingestion/answer_model.py`, used by the service and the gateway; two tests). After the fix the three replies are sensible (Blender: parent the mesh; Maya: rename the joints and check the parenting, which skips orienting and binding; Houdini: orient or mirror, which skips binding), so they are graded C, P, P.

**What the partly right replies show.** (1) The three "which tutorial should i watch first" replies are honest and name no video, but only give generic advice; they do not ask for a goal or level and do not use tutorial discovery. (2) Several answers are short single-topic answers where a beginner asked for an order of steps ("where do i start" gets "add an armature, place bones, parent the mesh" without the clean-up before it). (3) Two Houdini details (a "Joint Capture Paint" node, behaviour of the Twist Name parameter) were not checked in the installed application and are only as good as the knowledge base. (4) Every answer is text: none of them can drive the overlay (plan item B2).

### 3.6 The starter plan: "where do I start" answered with steps (plan item B2; `ingestion/starter_plan.py`, `tests/test_starter_plan.py`)
A question such as "where do i start rigging in maya", "what should i do before rigging" or "i made the skeleton whats next", asked with no tutorial loaded, is now answered with a STEP LIST built from the knowledge base, with no model call and no cost (proposal lines 82 and 235: a question with no active workflow is routed to a labelled draft). For each topic of the application, in the proposal's stage order (rig preparation, skeleton, controls and constraints, skinning), the knowledge base's outline items become steps, the menu path becomes the step's UI element (brackets such as "(options box)" removed so the overlay looks for the real name), the entry's prerequisite and check notes become how-to and check lines, and the nodes the topic makes become the expected state. Each topic is one display group (schema 0.12). Size: Blender 9 steps in 7 groups, Maya 21 in 12, Houdini 20 in 8; every list validates, has no group problems and no unknown-menu-name flags.

It is labelled a draft everywhere: source type `goal_draft`, provenance `catalog_template`, review status `drafted_automatically`, how-to lines labelled `catalog` (guidance, not shown in a video), and the answer says "Drafted from GuideWire's knowledge base, not from a tutorial: it is the usual order, and a tutorial may do it differently" and "The knowledge base does not yet cover scene units and importing or creating the mesh" (PREP-01 and PREP-02 are not written for any application). Where the knowledge base has nothing (what to do before rigging in Houdini) there is no plan and the model answers. The plan is reachable through the chat service (`/load last` loads it as a session to follow), and through the gateway `POST /v1/answer` with or without `model: true` (no charge); the answer is an ordinary answer bundle whose `steps` the overlay can use.

Two design choices: (1) the application must be CHOSEN, not defaulted: the session's default is "blender", which is not the user's choice, so the service asks "Which application do you use?" and the next message naming one completes the question (an explicit `/app`, or a caller that knows the application, as the gateway's `app` field does, is used directly); (2) the order follows the proposal's stages, so IK and controls come before skinning; many tutorials bind the mesh earlier, and the answer says it is the usual order only.

Effect on the 36 beginner questions (same questions as section 3.5; nothing else changed): 7 are now answered by the plan (nb01, nm01, nh01 "where to start", nm02 "before rigging", and the three "whats next" questions); the other 29 still go to the model. The plan replies were graded C (a full ordered list with menu paths that matches the reference; "before rigging" in Maya gives the clean-up step and the units gap, as the model reply did), which moves the totals to **27 C, 9 P, 0 N, 0 W: 88 % useful** (Blender 88 %, Maya 92 %, Houdini 83 %). Treat the rise from 85 % as small: same single non-independent grader, 36 questions, and the plan answers are deterministic knowledge-base text I graded after writing them.

**Limits.** The plan is only as complete and correct as the 12, 23 and 10 knowledge-base entries behind it (Blender has no entry for naming bones or for a weight-painting step, Houdini none for before-rigging), a few outline items are sentences from tutorials and community notes (tier shown on each how-to line), and the expected states derived from the knowledge base are flagged on each step as not read from a tutorial. Nobody has followed a plan in the app yet; whether a beginner finds it easier is for the user study.

### 3.7 Steps on request, the video recheck, and OpenAI (plan items B1, B2 follow-up and B4)
**Steps on request.** The starter-plan detector of section 3.6 was keyword-based: of 12 phrasings tested ("give me steps to implement ik", "walk me through making a skeleton", "teach me rigging from scratch", "what's the first thing i should do", ...) it caught 2. Now (1) explicit phrases ("give me the steps", "step by step", "walk me through", "teach me ... from scratch", "the whole rig") return either the starter plan or just the matching topic (`topic_bundle`: topics whose own names cover the question's words; "x" and "make a cake" return nothing); (2) the answer model has a new `wants_steps` flag in its normal call, set by meaning when the learner explicitly asks for steps however it is worded, together with the knowledge-base topics it used; the STEPS are built only from those topics (`plan_from_entries`), never written by the model, and the model can only choose among the topics it was offered. Everything else keeps its text answer. Limits: topic matching is still by words against topic names (a paraphrase with none of them misses), and the `wants_steps` route was tested with a scripted model, not yet measured on real paraphrases (`tests/test_starter_plan.py`).

**Video recheck (B1; `ingestion/video_recheck.py`, `tests/test_video_recheck.py`).** When the model says the steps do not contain the answer to a question about the tutorial (`in_tutorial = "no"`), the video model is asked about a clip of at most 120 s around the right moment (a time in the question, the step the model named, the best-matching step, or the step the learner is on). Found: the clip's answer and the clip range. Not found: the first answer plus "I also checked the video around 1:25 to 3:25 and it is not shown there"; the recheck may not guess; any error keeps the first answer. Opt-in (`--recheck`, or the gateway `tutorial.video_url`). First live run, 48 development questions, cheap model: 4 of the 18 tutorial questions triggered it (5 clip calls, 0.0125 USD in total): two correct "not shown" results ("what render settings did he use" at the end of a Blender video, and the Houdini version), one "not shown" appended to an answer that still claims Maya 2017 steps work in 2024 (the old unsupported claim is NOT fixed), and one FOUND answer for "why did he change the solver to rp" in the Maya leg IK video. **A time check against the human labels found the model's "at about 4:08" was wrong: the labelled solver change is at 4:46 to 4:51**, although the clip (4:04 to 6:04) did contain it; the model's own times are therefore not shown, only the clip range. Whether the found explanation is what the instructor actually said was not checked (nobody watched it).

**OpenAI (B4; `ingestion/providers/openai_provider.py`, `tests/test_openai_provider.py`).** Prices from OpenAI's own pages, read 2026-11-09, after its 30 July 2026 cut: GPT-5.6 Luna 0.20 USD in and 1.20 out per million tokens, Terra 2.00 and 12.00 (hidden reasoning tokens are billed as output and counted). Text only (OpenAI cannot be given a YouTube URL), strict structured outputs, the same cost guard, cache and ceilings as Gemini, the key never in an error or a log. The key was checked with one tiny call to each model.

### 3.8 An independent grader: the 88 % does not survive (plan item B4)
The first grader (the author of the pipeline's tests, who also wrote the reference answers) gave the 36 beginner replies 88 % useful. `ingestion/eval/qa_judge.py` asks `gpt-5.6-terra`, a different model family, to grade each reply against the same reference with the same four grades (C correct, P partly, N no answer, W wrong). Results are in `tests/fixtures/qa_suite/judge_terra_beginner_2026-11-09.json`.

| Replies by | Graded by | C | P | N | W | Useful |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite + starter plan | first grader | 27 | 9 | 0 | 0 | 88 % |
| gemini-3.5-flash-lite + starter plan | **Terra** | 17 | 14 | 0 | 5 | **67 %** |
| gpt-5.6-luna + starter plan | Terra | 15 | 17 | 1 | 3 | 65 % |

The two graders agree on 19 of 36 questions (53 %); Terra is stricter on 14 and more lenient on 3. By application, Terra: Blender 71 % (Gemini replies), Maya 67 %, Houdini 62 %. **Reading: 88 % was optimistic; an independent grader puts it near two thirds, and the truth is between the two until a person settles the 17 disagreements** (listed with Terra's reason in the fixture and in `against_first_grader`). Several of Terra's objections are real and point at the knowledge base, not the model: the Blender starter plan starts at "add a bone" with no step that adds the armature object itself (the knowledge base has only the prerequisite note "an armature object exists"); one Maya answer named the menu "Skin > Paint Weights" instead of "Paint Skin Weights"; and the Houdini answers skip the order "Joint Capture then Joint Deform". Others are judgement calls: Terra calls the plan's order "IK before binding" misleading (that is the proposal's stage order, section 3.6), and one objection depends on my reference's selection order for Maya's Bind Skin, which was not checked in the application. Terra also shares my references, so an error in a reference is shared, and a model grader has its own biases.

**Correction to the grader, and where the usefulness is lost.** The grader first showed Terra only the first 1,800 characters of a reply, and the starter-plan replies run up to 4,100, so four reasons said "cut off". The limit is now 8,000 and the Gemini replies were graded again: overall 67 % became **68 %** (17 C, 15 P, 4 W); the truncation was a small part of the gap. By route (Terra, full replies): the **model's answers 74 % useful (29 questions: 17 C, 9 P, 3 W)** and the **starter plan only 43 % (7 questions: 6 P, 1 W)**. So the route built to help beginners most is, by this grader, the weakest. The reasons Terra gives for the plan replies: too long and confusing (a numbered list of 20 steps with long outline sentences and "derived from the knowledge base" flags printed in the text), IK and autorig placed before binding the mesh, no step that adds the armature (Blender), and Joint Capture then Joint Deform missing early (Houdini). Reasons for all 19 non-C replies, counted by keyword and overlapping: leaves out a step or detail 14, order 8, says something wrong or unverified 6, vague or too long or cut off 4.

**Gemini against OpenAI as the answerer:** graded by the same grader the two are indistinguishable (67 % against 65 %; 6 of 36 replies differ in grade, in both directions), so switching to Luna buys no quality; the cost is similar (Luna 29 answers 0.02 USD, about 0.0007 each). Total OpenAI spend for this section: 0.20 USD of the 5 USD credit (Luna answers 0.02, Terra grading 0.18).

### 3.9 Raising usefulness step by step (graded by Terra after each change; same 36 beginner questions)
Four changes, each followed by a full re-run and an independent grading (`ingestion/eval/qa_judge.py`, `gpt-5.6-terra`, replies shown in full). Useful = C + P/2.

| After | Overall | Model's answers (29) | Starter plan (7) | What changed |
|---|---|---|---|---|
| Baseline (full replies shown to the grader) | 68 % | 74 % | 43 % | |
| 1a. Plan text as a stage list, beginner order | 68 % | 74 % | 43 % | text 4,000 characters to about 12 lines; bind before IK; **no effect on the grade**: Terra then missed details the short text hid, and the stage names came from a generic catalog ("clear history" in Blender) |
| 1b. App-specific stage names with the key action | 68 % | | 50 % | for example "Bind the geometry (Joint Capture, then Joint Deform)" |
| 2. Knowledge base: "Add > Single Bone" instead of "Add Bone"; a Blender "test by posing" stage; honest notes | 71 % | 71 % | **71 %** | the manual's menu wording (read verbatim from the official page); the notes say an armature object must exist (no sourced step to create one) and that the Skeleton, Skin and Constrain menus are in Maya's Rigging menu set (F3) |
| 3. Three answer rules: copy menu names exactly from the entries; how-to answers as 3 to 6 numbered steps; no tutorial recommended from memory, ask goal and level | **76 % and 79 %** (two runs) | **78 % and 81 %** | 71 % | wrong grades fell from 4 to 2 and 1; all three "which tutorial first" questions now ask about goal and level and are graded correct; "Skin > Paint Skin Weights Tool" is now copied exactly |

Net: about 68 % to 76 to 79 % on this grader in four changes, for about 1 USD of OpenAI and Gemini calls. **Caveats, in order of weight:** (1) these 36 questions are now a DEVELOPMENT set: rule 12 and the menu-name rule were written after reading the failing replies of exactly these questions, so the gain is partly fitted to them and a fresh question set graded the same way is needed before the number is quoted; (2) one grader (a model, sharing my references), one run per setting except step 3, and run-to-run change of the model's answers is a few points (the model route read 74 % and 71 % on two runs of the same prompt); (3) the plan route is 7 questions, so each question is 14 points of it.

**What was NOT fixed, and why.** (a) Terra says "armature in Edit Mode" and the Blender plan skip creating the armature object (it names Add > Armature > Single Bone): two agents could not find an official Blender page that states that path, so nothing unsourced was added to the knowledge base; the plan says an armature object must exist first. (b) Three objections conflict with statements in the knowledge base that were not checked in the applications: Houdini "slightly posed bones before capture" (Terra: should be a neutral pose), the IK Chains parameter names (Root Name, Mid Name, Tip Name, Goal Name), and the selection order for Maya's Bind Skin (the reference says mesh then root joint, one answer said the reverse). These need a person with the application or the manual open. (c) Scene units, importing the mesh and a neutral pose (PREP-01 and PREP-02) are still unwritten.

**Step 4, for a person.** `scripts/review_sheet.py make` wrote `eval_data/review/beginner_review.csv`: the 36 current replies with the question, the reference and Terra's grade and reason in the LAST columns, and empty `human_grade` and `human_note` columns. Grading it takes about an hour; `scripts/review_sheet.py check <file>` then reports whether the person agrees more with Terra or with the first grader, which says whose numbers to trust and which references are wrong (`tests/test_review_sheet.py`).

### 3.10 A real test of the video recheck, with the human labels as ground truth (`ingestion/eval/recheck_eval.py`, `tests/test_recheck_eval.py`; run 2026-11-10)
The recheck (section 3.7) was tested on actions the extracted steps MISSED: 64 labelled core actions across the six videos (steps from the 3.6 Flash v10 one-pass runs); a spread of up to 5 per video, 27 in all, each asked WITH a time ("how does he do this: <the labelled action>? around 2:10", the labelled time rounded to 10 s) and WITHOUT one, so the clip has to be chosen from the steps alone. Controls: 36 UNANSWERABLE questions (the background music, the instructor's email, a course price; asked at the start and around the middle of each video; the right outcome is "not shown"), and 18 DECOYS (real actions from the other labelled video of the same application that share no words with this video's actions). The clip model was `gemini-3.5-flash-lite`; whether a found answer matches the labelled action was judged by `gpt-5.6-terra` (text only). The whole evaluation cost about 0.9 USD of Gemini calls.

| | First clip only | With a sweep of up to 3 more parts of the video |
|---|---|---|
| With a time in the question (27) | 27 found; 24 correct, 2 partly, 1 wrong | the same (the first clip always held the moment) |
| Without a time (27) | clip held the moment 14 times; 19 found: **18 correct, 1 partly, 0 wrong** | 26 found: **22 correct, 2 partly, 2 wrong**; 37 clips asked instead of 27 |
| Unanswerable (36) | **36 said "not shown", 0 invented** | **36 said "not shown", 0 invented** (120 clips asked) |
| Decoys (18) | 17 said "not shown", 1 answered | 16 said "not shown", 2 answered |

Reading: **with a time the recheck is accurate (89 % fully correct, 96 % correct or partly), and with no time the first guess was the wrong part of the video about half the time (14 of 27 clips held the moment), which the sweep mostly repairs (found 70 % to 96 %, fully correct 67 % to 81 %) at the price of two wrong answers and about three times as many clips on questions that cannot be answered.** Not one of the 36 unanswerable questions got an answer, with or without the sweep, so on this sample the clip model did not invent answers when asked about things that are not there. The sweep is therefore on wherever the recheck is on (the gateway and `chat --recheck` use 3 extra parts; `ModelAnswerer.recheck_sweep`). Caveats: the questions repeat the labelled action's words, so a model could echo them; the decoys are the check, and the one decoy that was answered in both settings ("use the wildcard to include all points in the rig", Houdini FK video) is plausibly something that really happens in that video (the labels of the sibling video and the knowledge base both mention it) and needs a person to look; the judge is a model; 27 questions; one labeller's misses; the clip model was the cheap one.

### 3.11 A fresh held-out set, and what it showed (`tests/fixtures/qa_suite/questions_heldout.json`; run 2026-11-10)
30 new questions (10 per application) written before any run on them, different from the beginner set: naming and orientation, bone roll, FK/IK switches, mirroring weights, concepts (freeze transformations, pole vector, Rig Doctor, APEX AutoRig), "give me the steps" and "walk me through" requests in new wording, two beginner starts and one tutorial request per application. Run once through the final pipeline, graded by Terra only (no person yet).

| | Questions | C | P | W | Useful |
|---|---|---|---|---|---|
| **All, blind run** | 30 | 16 | 12 | 2 | **73 %** |
| Model's answers | 24 | 14 | 8 | 2 | 75 % |
| Steps routes (starter plan, topic steps) | 6 | 2 | 4 | 0 | 67 % |
| Blender / Maya / Houdini | 10 each | | | | 80 % / 70 % / 70 % |
| Tutorial requests (3) | 3 | 3 | 0 | 0 | 100 % (all ask the goal and level, none names a video) |
| "Give me the steps" requests (6) | 6 | 0 | 5 | 1 | 42 % |

**Reading: about 73 % on questions the answer rules were not tuned on, against 76 to 79 % on the development set: the gain from section 3.9 mostly held, a little smaller, as expected.** The weak spot is the requests for steps (5 of 6 only partly right: they omit a detail, such as the selection order or the joint chain a beginner needs). The two wrong answers: Maya "parent a control to a joint" gave the selection order backwards, and Houdini "capture weights look wrong near the shoulder" repeated claims (angled bones, avoiding NURBS) the grader did not accept. Two flaws of my own were exposed and fixed: (1) before the model run, looking at what the deterministic steps route returned for these questions showed it answering "build a leg with ik" with the steps for MIRRORING joints, because a knowledge-base phrase "build one leg and mirror it" shared two request words; request words (build, use, add, apply, start, begin, can, could, would, should, does, work) no longer choose a topic; **I saw that output on the held-out wording, so the steps route is not blind on this set**; (2) the blind run then showed that topic steps were returned as a single stage line ("Bind the geometry (3 steps)") with none of the instructions, because I had shortened the text for the broad "where do I start" plan and applied it to topic requests too; topic steps are now written out under the stage name and only whole-rig plans stay as stage lines. Re-run after fix 2, **which is not blind**: 17 C, 11 P, 2 W, **75 %** (one question improved). The 73 % is the honest figure.

**Other answering fixes made (plan item 5), measured only by tests and by reading replies, not scored:** "go back to X" with several matching steps now jumps to the start of the most recent matching run before the learner's step ("go back to renaming the joints" goes to the first of the six renaming steps and says the run is s02 to s07) and asks only when there is nothing earlier (`tests/test_goback_ties.py`); the answer model must not say that steps from one version work the same in another (the Maya 2017 tutorial reply for "does this work in maya 2024" now says menus and tools can differ and to check the release notes) and must say so when the steps give no reason for a "why did he" question.

**Knowledge-base gap not filled.** The step that creates the Blender armature object (Add > Armature) could not be sourced: the manual page the knowledge base cites (Adding Bones) covers adding bones in Edit Mode only, the Structure and Introduction pages could not be read through their navigation, and the manual's raw source files returned HTTP 404. Nothing unsourced was added; the plan says an armature object must exist first.

### 3.12 Tutorial discovery: a fit check on the top three suggestions (plan item D2; `ingestion/fit_check.py`, `scripts/fit_check_eval.py`, tests `tests/test_fit_check.py`; run 2026-11-14)

**Problem.** Discovery ranks videos from their title, channel, length and chapters only. A title cannot show that a "Maya leg rig" is really about another application, or that a video is aimed at a different level.

**What was built.** After the title ranking, a model watches the first 120 seconds of each of the top three suggestions and answers four things: which application the clip shows (blender, maya, houdini, other, unclear), whether the clip is about what the person asked for (yes, partly, no, unclear), the level it teaches at, and one sentence on what the video is about. The answer is used three ways. It adds a plain-words note to the suggestion ("Checked the first 2 min of the video: it shows Houdini, not Blender"). It nudges the title score (yes +1.0, no -2.5; a clear wrong application -4.0 and the video is left out of the list). It never replaces the title ranking. A failed call (no key, budget stop, quota, a private video) leaves the suggestion as it was and says "Not checked against the video itself". In the app it runs only on live YouTube results, behind the cost guard, with the result kept for a day with the rest of the search.

**Thumbnails: dropped by rule, not by a test.** The plan says GuideWire does not download or store YouTube video, audio or frames and keeps only text (`docs/compliance/google_youtube_questions.md`, lines 18 and 19). Reading a thumbnail would mean fetching an image from YouTube ourselves, so no thumbnail is fetched. The video is passed to the Gemini API by its public link with a clip window, the same way extraction does it. The proposal file itself is not in the repository, so the rule was taken from the compliance notes; if the proposal says something different, this should be rechecked.

**Cost.** At the measured 96 tokens per second a 120 s clip is about 11,500 input tokens, about 0.35 cent on `gemini-3.5-flash-lite` ($0.30 per million input tokens). Three clips are about 1 cent per search, on top of the 200 units of free YouTube search quota. The test below made 18 real calls for $0.0635 in total, 0.35 cent each, which matches the input estimate (18 clips of about 11,500 tokens is about 6.2 cents; the answers are short).

**Test (the only ground truth available: the six demo tutorials).** Nobody has labelled real search results as right or wrong, so the test uses the six videos whose content is known (two Blender, two Houdini, two Maya). Each has a goal that describes it. For each goal three candidates are built in the worst order a title ranking could produce, with title-score gaps of 0.4 (the live top-three gaps seen were 0.37 and 0.02, so a larger gap would make the test harder than real use): a video in another application (9.0), a video in the same application about something else (8.6), and the video the goal describes (8.2). 18 clips, `gemini-3.5-flash-lite`, results in `eval_data/fit_check_results.json`.

| Question | Result (6 goals) |
|---|---|
| The video in another application is flagged as showing a different application | 6 of 6 |
| The right video is kept (not called a wrong application, not called "no") | 6 of 6 |
| The same-application video about something else is marked "partly" or "no" | 5 of 6 |
| The right video ends first after the check (before the check it was last every time) | 4 of 6 |

**The two misses, read one by one.** (1) The Blender beginner-armature goal: the other Blender video is also a beginner armature tutorial, and the model said "yes" to both, so this is a real tie, not an error. (2) The Maya goal "set up a leg with IK handles": the first two minutes of that video only place the joints, and the model said "partly" (it wrote that the IK handles are not in the clip yet). A clip from the start cannot see what comes later in the video.

**What this does and does not show.** It shows that the check can tell a known right video from known wrong ones, and that the one mistake a learner cannot recover from (the wrong application) was caught every time in this set. It does not show an improvement in hit rate on real search results: that needs labelled searches. Six goals, one run, one model; the ranking nudge is a judgement (with a first run that used 1.0 title gaps the right video tied instead of winning in all 6 goals, 0 of 6 first, so the nudge only helps when the title scores are close, which they usually are). Because the check reads only the start, a video that introduces its topic late can be rated "partly" unfairly; the note says what the clip showed so the person can judge.

**Reproduce:** `python scripts/fit_check_eval.py --dry-run` lists the 18 calls and the estimated cost without spending; without `--dry-run` it runs them (cached, so a repeat is free).

## 4. Application-specific improvement recommendations
All items are PROPOSED unless marked. Each cites what the labelled runs showed.

### Blender
* **Verified now:** best recall (v9 64 % one-to-one, 85 % words-in-span); misses are menu openings (`Open add menu`, `Right click to open context menu`), "return to Pose Mode to inspect" mode switches, and reasoning steps about the bone X axis and roll.
* Use the header **mode dropdown label** (Object, Edit, Pose, Weight Paint) as the signal for every mode step and ask the model to emit a step whenever the label changes between frames; the harness can then check `mode` (it already reads `bpy.context.mode`).
* Keep Blender nodes as bones, `CONSTRAINT_*` and `MODIFIER_*` (done in v7) and teach the model the **Bone Constraints tab** and **Armature properties** locations, because learners lose them (comment evidence and QA `vb03`).
* Add bone-name steps (rename bones, `.L`/`.R`) to the prompt's examples; naming was found 54 to 62 % of the time.

### Maya
* **Verified now:** misses are **undo steps** (`Undo the incorrectly created joints`), **tool activation from a shelf or menu** (`Select the IK Handle tool`, `Activate the Move tool`) and typed names; toggles in the options box (0 of 3).
* Add to the prompt the Maya habits that make small actions invisible: **hotkeys W/E/R/Q and Y (repeat last tool)**, the **menu set switch (F2 to F5)**, **options boxes with Reset Settings**, the **Channel Box** (renames and values), the **Outliner**, and the **spacebar view maximise**; one step each.
* Treat **undo and redo as steps when the instructor does them on purpose** (the labeller listed them; the model skips them).
* The knowledge base has 35 Maya entries, so answers for Maya are the best available once the routing defect (3.3 item 1) is fixed.

### Houdini
* **Verified now:** weakest (words-in-span 48 %; precision 66 % with v9). Misses are **parameter-level edits** (promotion groups set to `*`, naming the skeleton or component, applying a configuration), **viewport state keys** (`Press F to enter Modify mode`, Enter or Esc to start and stop a Skeleton tool), and **node connections** (`connect Scene Add Character after Configure Controls`).
* The video is a node graph, so steps need the **node and the input it connects to**, the **flag set** (display, bypass), and the **parameter and its value**, none of which is a predicate today. The new `attribute_exists` and `node_count` kinds (schema 0.11) fit parameters and counts; a connection predicate is not defined and would need the owners' agreement.
* Prompt: define "one step per node created, one per connection, one per parameter changed, one per viewport state change" explicitly for Houdini, and give the Tab-menu node-creation flow as the standard way a node appears.
* Houdini needs the stronger model or time-window chunking before v9 is considered (precision fell); the stronger model was not available to test.

### All three (extraction)
* Time-window chunking for long videos (extract per 60 to 120 s window and merge); the Gemini API documents video clipping offsets (not verified here, and `providers/gemini.py` was not checked for support); not built.
* Count order, how-to detail and checkable end state per run (done for the last two in `phase1.py`).

## 5. Feature matrix and remaining work

### 5.1 Calculation (verified from `docs/rigging_matrix.csv`, 145 features)
The matrix lists, for each rigging feature and application, five things: a knowledge-base entry (K), a researched parser phrase (P, counting only `kb-phrase`; `name` matches are an upper bound and are excluded), a derived node state (d), a check performed in the real application (R), and a saved live Gemini run (L). A pair counts only if the catalog marks the feature as supported in that application.

Completion = for each supported (feature, application) pair, the share of these five that exist, averaged over pairs.

| Set | Pairs | K | P | d | R | L | **Completion** |
|---|---|---|---|---|---|---|---|
| All 145 features | 434 | 18.2 % | 9.9 % | 4.6 % | 4.6 % | 1.8 % | **7.8 %** |
| MVP (51 features) | 153 | 39.9 % | 24.8 % | 12.4 % | 12.4 % | 3.9 % | **18.7 %** |
| P0 (16) | 48 | 47.9 % | 35.4 % | 18.8 % | 18.8 % | 6.2 % | **25.4 %** |
| P0 and P1 (54) | 162 | 38.9 % | 24.1 % | 11.7 % | 11.7 % | 4.3 % | **18.1 %** |

By application (all features supported): knowledge-base entries Blender 19, Maya 35, Houdini 25; derived states and real-application checks 5, 7, 8; saved live runs 0, 8, 0. **Headline: about 19 % of the MVP matrix is complete by this calculation (25 % of P0).** The numbers do not include the live runs made today, since they are not saved as fixtures.

What the percentage does NOT capture: the matrix counts artefacts per feature, not quality. The working components below are not features and are not in it. It is a measure of verified per-feature depth, which is low by design: most of the 145 features are P2 and P3.

### 5.2 Status of components (verified against code and tests)
| Capability | Status |
|---|---|
| Shared step contract 0.11, validator, instruction composer, scene-chain order check | Complete, tested offline |
| Video extraction (prompts v2 to v9), retries, cost guard, cache, dry run | Complete; 27 paid calls and about 0.79 USD since 2026-11-07 (plus free re-validations from the cache); v8 and v9 new |
| AI gateway (extract, answer, YouTube metadata and search) | Complete, tested with a fake provider; never run live in this review |
| Verification harness (end-state check in real Blender, Maya, Houdini) | Checks 7 of the 10 predicate kinds in a saved scene (node_exists, name_exists, attribute_exists, node_count, property_equals, selection_type, and mode where the application reports one); active_tool, workspace and panel_open are reported as cannot-check; **end state only, no per-step replay** |
| Per-feature recipes proving derived states | 20 claims proven (Blender 5, Maya 7, Houdini 8) |
| Rigging knowledge base | 45 entries; P0 gaps PREP-01 and PREP-02 in all apps; animation stage (ANIM, CURV, LAYR, LOCO, MOCP) not started |
| Tutorial discovery | Complete; no engagement or comment signals (Section 2) |
| Human-labelled evaluation | 6 videos labelled (2 per application); the older 10-video Blender set has blank sheets except the Blender armature video (labelled) and one 3-action sheet |
| Question answering | Blender catalog and manual index; follow-ups work with defects (3.3); Maya and Houdini mostly deflect |
| Vision (screen capture, overlay) and app (UI, accounts, session engine) | `vision/` and `app/` are empty in this repository; owned by teammates |

### 5.3 Application-specific gaps
* **Blender:** no saved live run in the matrix; 5 of 144 supported features have a derived state; QA coverage is the best of the three but only for the catalog operations.
* **Maya:** most content (35 entries) but the QA route deflects how-to and concept questions; 8 features seen in a live run (one video).
* **Houdini:** weakest extraction (Section 1); 25 entries; question answering almost entirely deflects.

## 6. Prioritised implementation plan (what remains; updated 2026-11-09 after the decisions below)
Decisions: more gold labelling is paused (no time); YouTube signals are dropped; question answering is model-backed; the goal for extraction is above 90 % on every measure, to be tried on a stronger model after billing is added.

| # | Item | Why | Effort |
|---|---|---|---|
| 1 | **IN PROGRESS (2026-11-09 evening):** v10 on `gemini-3.6-flash`, one pass and 60 s clips, run with `scripts/compare_prompts.py --model gemini-3.6-flash --versions v10 --windows 0,60` (new `--model` option; outputs in `runs/compare/gemini-3.6-flash/`). Record the table in section 1.8; pick the default per application from it; add a Houdini-specific prompt (node, connection, parameter, viewport state) if Houdini is still far behind. A first 3.6 Flash run on 8 Nov cost 0.446 USD (cost log) but its outputs were not saved, so its accuracy table cannot be re-checked | The only way to see whether 90 % is reachable | half a day plus about 1 to 2 USD |
| 2 | Decide what "above 90 %" means for each measure and fix the ones the gold cannot measure (a labeller-granularity note, or a short human review of steps that match no gold row) | Recall measures are capped by the gold itself (section 1.5) | 1 day, no labelling |
| 3 | Add a fresh question set, graded by a second person, before quoting any answering number (the model answerer is already wired into the gateway and `chat`) | The 91 % is on a development set | 1 day |
| 4a | Add knowledge-base entries with menu paths and official option names, Houdini first, and re-run the section 1.6 comparison; use outlines to check extracted steps after the fact, not in the prompt | Removing the menu block cost about 10 points of words found | 2 to 3 days |
| 4 | Confirm or correct knowledge-base statements the model now repeats (APEX versus KineFX; freeze on joints), starting with every official-tier statement from a summarised fetch; then fill P0 gaps (PREP-01, PREP-02) with a source each | A wrong entry now reaches users through the model | 2 to 3 days |
| 5 | Answering details: choose instead of asking when "go back" ties between consecutive steps; say "the tutorial does not give a reason" for why-questions; no promise that old steps work in a newer version | The 9 partly right replies | 1 day |
| 6 | Teach the extraction prompt the 0.11 predicate kinds with a measured live run (changes `MODEL_SCHEMA_TAG` and every cache key) | In the contract and the harness, never produced | 1 day |
| 7 | Per-step replay in the harness (state after each step) | The harness checks the end state only | 2 to 3 days |
| 8 | Demo preparation (**Nov 12**, moved from Nov 22 on 2026-11-10, so two days from then): one video per application with steps, matrix row, harness result. Scope for two days, from what runs today: (1) a written instruction and the starter plan turned into a step list (no model call); (2) one Blender tutorial's saved extraction (a live extraction needs Gemini quota, which was exhausted on 2026-11-09, so use saved outputs); (3) a few questions with and without a tutorial through the model path; (4) Umaima's `python -m vision.demo` highlighting Blender's panels; (5) Mehak's app opening the step list, the review editor and the session screen (done, skip, back). NOT ready, to be said on the slide: automatic completion from the screen, highlighting a named button or menu item (vision finds panels, not controls), and any overlay for Maya or Houdini | Plan Phase 3 | 2 days: all of it |
| 9 | Paused: more gold (6 to 10 videos, a second labeller, explicit order); needed before any claim of accuracy beyond these six videos | The evidence base is six videos and one labeller | days of labelling |

### 6.1 Additions of 2026-11-09 (evening), merged into the plan above
Each item says which numbered item it extends. Basis for each is the proposal (line numbers of the .docx text) or a measured result in this report; nothing here is measured unless it says so.

**Track A, step extraction (Ayesha's core part)**
| # | Item | Extends | Why (basis) |
|---|---|---|---|
| A1 | Two-level steps: keep every atomic step for the overlay and completion detection, add an optional display group so the learner sees "Rename the bones" instead of 12 rows. Additive field, so the app keeps working (architecture note, contract rule); agree the field name with Mehak first | 1, 2 | Proposal: one highlighted element per step; automatic progression only for visually distinguishable single actions (proposal line 437). Strict one-to-one scores punish grouping (section 1.1), so grouping is a display choice, not an extraction target |
| A2 | Success measure for the overlay: share of steps that have a UI element to point at AND a checkable end state (`checkable_end_state` already exists in `phase1.py`), reported beside the word-overlap numbers | 2 | Word overlap is a proxy; the overlay needs a target and a check |
| A3 | Houdini prompt: one step per node created, per connection, per parameter changed, per viewport state change | 1, 4a | Houdini is the weakest at every setting (section 1.5) |
| A4 | After extraction, use knowledge-base outlines to flag steps that look missing or out of order (not inside the prompt) | 4a | The outline-in-prompt variant lowered precision (section 1.6) |
| A5 | Run each chosen setting 3 times on the six videos and report the spread | 2 | Run-to-run spread was never measured (section 1.5) |

**Track B, question answering**
| # | Item | Extends | Why (basis) |
|---|---|---|---|
| B1 | Second pass for tutorial questions: if the extracted steps do not answer, find the nearest time, send the video URL and a short clip window (`#t=start,end`, already in `providers/gemini.py`) with the question, answer with the timestamp; only if the clip does not show it say "I checked about 2:10 to 3:00 and it is not shown". Goes through the cost guard and cache. Cost per clip is an estimate, to be measured | 3, 5 | Today the model sees step text only (`answer_model.py` rule 4) and says "not in the tutorial"; that rule exists because it invented reasons (section 3.4), so the recheck must keep the right to say "not shown" |
| B2 | "Where do I start" with no video: build a short starter plan from the knowledge base and return it as a step list (an `AnswerBundle` can carry a `StepList`, architecture note section 1), labelled "drafted from GuideWire's knowledge base", so the overlay can highlight it. Text answer stays the default; the step route is on request | 4 | Proposal: a question is routed to discovery or a labelled unsourced draft when no workflow is active (proposal lines 82 and 235); the answer schema today has no steps (`answer_model.py:46-58`) |
| B3 | New question set: 12 "most asked" beginner questions per application (where to start, what before rigging, skeleton, skinning, IK, controls, FK versus IK, mirror, which tutorial first, flipping knee, what next), plus typed questions that state a level ("I am a beginner"). Levels exist only as typed words in questions for now; no profile field | 3 | None of the 48 current questions asks where to start. Real frequencies come from the user study (proposal line 351), so these are assumptions until then |
| B4 | OpenAI key (5 USD credit): add a provider adapter behind `providers/base.py`, a price entry for the chosen model, and use it behind the same cost guard. Two uses: (1) as an answering model to compare against Gemini on the new question set; (2) as an independent grader of replies, since the 48 questions were graded by one reader. Keys stay only in the gateway `.env`; never commit it | 3 | The cost guard needs a price for every model (`ingestion/experiment.py`). The existing Gemini cost was about 0.03 USD for 40 answers (section 3.4), so credit goes furthest on short, cached, capped calls |

**Track C, knowledge base**
| # | Item | Extends | Why (basis) |
|---|---|---|---|
| C1 | Audit all 45 entries against the matrix: list entries without menu paths, without an official source, with an unconfirmed official-tier statement; fill P0 gaps PREP-01 and PREP-02 first (they are the "where to start" content), then the animation stage that is not started; Houdini first | 4, 4a | Removing the menu block cost about 10 points of words found (section 1.6); a wrong entry now reaches users through the model (section 3.4) |

**Track D, tutorial discovery**
| # | Item | Extends | Why (basis) |
|---|---|---|---|
| D1 | Auto-rig titles: no penalty for a beginner or "quick" goal, a small penalty only when the goal says learn how rigs work; always add the note "teaches the tool, not how a rig is built". Replaces the flat -1.0 at `rigging_discovery.py:314`. Level read from the request words only | none | The penalty was for extraction convenience, not usefulness to a beginner |
| D2 | **Done 2026-11-14 (section 3.12), thumbnails dropped by rule.** Fit check on the top 3 results (a model watches a short part of each) and, only if a test shows it helps top-three hit rate, thumbnails. Check the proposal's rule that GuideWire does not download or cache YouTube content (line 388) before fetching images | none | Proposal names a video model for the discovery fit check (line 389); thumbnails are a weak, unmeasured signal |

**Track E, housekeeping**
| # | Item | Why |
|---|---|---|
| E1 | Fix `tests/test_app_step_loader.py::test_unknown_kind...`: it uses `node_count` as an unknown kind, but schema 0.11 makes it known. Change the example to a made-up kind, and tell Mehak (her file). Update her architecture note ("schema 0.10", "proposed for 0.11") | 1 failing test after the merge of main |
| E2 | Merge `main` into each stacked branch, push, open pull requests in order | Stack: extraction, scoring, answering, report |

**Order of work (recommended):** A1 results, then A1/A2 changes, E1 at any time; B3 and C1 in parallel (they feed each other); D1 (small); B2 after C1; B1 after B3 shows how many questions need it; B4 once B3 exists, so the 5 USD is spent on a measured comparison; A3 and A5 when the credit plan is clear; D2 last.

### Files added or changed in this review (all uncommitted)
Extraction: `ingestion/extract.py` (prompts v8, v9, v10; clip extraction `extract_from_video_windows`; last-resort time sort), `ingestion/providers/gemini.py` (clip offsets via `#t=start,end`), `ingestion/cli.py` (`--window-s`), `ingestion/validate.py` (coverage warnings as a function; vocabulary matching), `scripts/compare_prompts.py`.
Scoring: `ingestion/eval/phase1.py`, `ingestion/eval/small_actions.py`, `scripts/labels_to_gold.py`, labels and gold under `eval_data/`.
Answering: `ingestion/answer_model.py`, `ingestion/service.py` (`answerer`), `ingestion/followup.py` (`next?`, ranked "go back"), `shared/answer.py` (route `model`, additive), `ingestion/eval/qa_suite.py`, fixtures and both grade files in `tests/fixtures/qa_suite/`.
Unused helpers from the dropped YouTube look: `ingestion/youtube/api.py` additions, `scripts/youtube_signals.py`.
Tests added: `test_prompt_v8_v9.py`, `test_video_windows.py`, `test_answer_model.py`, `test_qa_suite.py`, `test_phase1_eval.py`, `test_node_name_matching.py`, `test_youtube_signals.py`.
