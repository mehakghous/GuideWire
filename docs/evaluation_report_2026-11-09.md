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
| 1 | When billing is on: run `scripts/compare_prompts.py --tier report --versions v7,v9,v10 --windows 0,60`; pick the default per application from the table; add a Houdini-specific prompt (node, connection, parameter, viewport state) if Houdini is still far behind | The only way to see whether 90 % is reachable | half a day plus about 3 USD |
| 2 | Decide what "above 90 %" means for each measure and fix the ones the gold cannot measure (a labeller-granularity note, or a short human review of steps that match no gold row) | Recall measures are capped by the gold itself (section 1.5) | 1 day, no labelling |
| 3 | Add a fresh question set, graded by a second person, before quoting any answering number (the model answerer is already wired into the gateway and `chat`) | The 91 % is on a development set | 1 day |
| 4a | Add knowledge-base entries with menu paths and official option names, Houdini first, and re-run the section 1.6 comparison; use outlines to check extracted steps after the fact, not in the prompt | Removing the menu block cost about 10 points of words found | 2 to 3 days |
| 4 | Confirm or correct knowledge-base statements the model now repeats (APEX versus KineFX; freeze on joints), starting with every official-tier statement from a summarised fetch; then fill P0 gaps (PREP-01, PREP-02) with a source each | A wrong entry now reaches users through the model | 2 to 3 days |
| 5 | Answering details: choose instead of asking when "go back" ties between consecutive steps; say "the tutorial does not give a reason" for why-questions; no promise that old steps work in a newer version | The 9 partly right replies | 1 day |
| 6 | Teach the extraction prompt the 0.11 predicate kinds with a measured live run (changes `MODEL_SCHEMA_TAG` and every cache key) | In the contract and the harness, never produced | 1 day |
| 7 | Per-step replay in the harness (state after each step) | The harness checks the end state only | 2 to 3 days |
| 8 | Demo preparation (Nov 22): one video per application with steps, matrix row, harness result | Plan Phase 3 | 2 days |
| 9 | Paused: more gold (6 to 10 videos, a second labeller, explicit order); needed before any claim of accuracy beyond these six videos | The evidence base is six videos and one labeller | days of labelling |

### Files added or changed in this review (all uncommitted)
Extraction: `ingestion/extract.py` (prompts v8, v9, v10; clip extraction `extract_from_video_windows`; last-resort time sort), `ingestion/providers/gemini.py` (clip offsets via `#t=start,end`), `ingestion/cli.py` (`--window-s`), `ingestion/validate.py` (coverage warnings as a function; vocabulary matching), `scripts/compare_prompts.py`.
Scoring: `ingestion/eval/phase1.py`, `ingestion/eval/small_actions.py`, `scripts/labels_to_gold.py`, labels and gold under `eval_data/`.
Answering: `ingestion/answer_model.py`, `ingestion/service.py` (`answerer`), `ingestion/followup.py` (`next?`, ranked "go back"), `shared/answer.py` (route `model`, additive), `ingestion/eval/qa_suite.py`, fixtures and both grade files in `tests/fixtures/qa_suite/`.
Unused helpers from the dropped YouTube look: `ingestion/youtube/api.py` additions, `scripts/youtube_signals.py`.
Tests added: `test_prompt_v8_v9.py`, `test_video_windows.py`, `test_answer_model.py`, `test_qa_suite.py`, `test_phase1_eval.py`, `test_node_name_matching.py`, `test_youtube_signals.py`.
