# Rigging plan for Maya, Houdini and Blender (realigned roadmap, 2026-10-22)

Status: PROPOSAL for review. This replaces the milestone order in `docs/ingestion-technical-plan.md` section 9 (M3 to M6) and `docs/ingestion-rigging-plan.md` for planning purposes; those documents stay as the record of what was built. Nothing here is implemented except what section 1 lists as done. Evidence for every number is in `docs/rigging_audit_2026-10-22.md` and `docs/rigging_matrix.md`.

## 0. What changed and why

| Before | Now |
|---|---|
| Blender modelling first; rigging added around it | **Rigging is the main focus in all three applications, side by side, feature by feature** |
| Demo (Nov 22) = one Blender written input and one video | Demo = **one YouTube rigging video per application turned into steps**, with the end state checked in the real application where the predicate allows |
| Applications other than Blender had no way to be tested | Blender 5.2.2 and Houdini 22.0.466 are installed and checked headlessly (`verification/`); Maya arrives 2026-10-23 |
| Cost control only inside the Blender-only experiment runner | The main path (`cli video`, gateway `/v1/extract`) gets a ledger, cache and ceilings (`docs/rigging_real_runs_and_budget.md`) |
| Progress tracked as milestones | Progress tracked by the feature x application matrix (`python scripts/build_rigging_matrix.py`) |

**The most important flow is: YouTube video to good step extraction.** Everything below is ordered by what makes that flow more correct, cheaper to test, or checkable. "Good" is defined in phase 1 so it can be measured.

## 1. Where the main flow stands today (evidence: audit and repository)

- Done and tested offline: contract 0.10, prompt v2 to v6, schema-constrained extraction with bounded retries, validator, instruction composer, scene-chain check on all routes, rigging knowledge base (23 entries), tutorial discovery.
- Real model runs: 2 Blender modelling videos (R1, R4) and 2 Maya runs of one video (R5 raw v4, R6 v6). **No Houdini and no Blender rigging run exists.** R6: 15 steps, 5 of 15 with a checkable end state, 6 of 15 after derived states.
- Never measured: step recall and precision against a human reading of the video; timestamp accuracy; feature-tag accuracy on model output; behaviour on Houdini (the Houdini prompt never ran).
- Gaps found in this audit: `cli video` and the gateway have **no dollar cap, no content cache**; `experiment.cell_key` hashes the Blender system prompt only, so the app is not part of the cache key; default model is `gemini-3.6-flash` while the pricing page now lists 3.8 Flash and 4 Argon.

## 2. Phases

Dates assume the Nov 22 demo and are proposals. Phases overlap; the matrix says what is next.

### Phase 0: foundations (Oct 22 to Oct 26)
Goals: spend safely, test in real applications, one agreed contract.
- Cost controls on the main path: new `ingestion/budget.py` (content-hash cache, ledger with per-run and per-day ceilings, cost log, key and model tiers), wired into `cli video` and the gateway; fix `cell_key` to include the app and the real system prompt. Prices updated in `experiment.PRICES`.
- Commit the verification harness (`verification/`, tests) and the matrix tooling (`scripts/build_rigging_matrix.py`).
- Run the harness against real Maya the day it is installed: `tests/test_verification.py::test_maya_real_scene` and fix `verification/snapshot_maya.py` (never run so far).
- Regenerate the vocabularies from the real applications (the Blender and the Maya/Houdini profiles are "written from memory"): `scripts/dump_blender_vocab.py` (exists, never run) plus equivalents for Maya node types and Houdini node types.
- Tests that prove it: ceilings abort a fake batch (no network); a cached cell is not re-called; the cache key changes with the app; harness tests pass on Blender and Houdini, and on Maya once installed.
- Out of scope: any prompt change, any new feature.

### Phase 1: measure extraction (Oct 26 to Nov 8)
Goals: a number for "good step extraction", per application.
- Run the 14-video batch (`docs/rigging_real_runs_and_budget.md`) after "go": 5 Maya + 1 control, 4 Houdini, 4 Blender.
- Human gold for at least 6 of those videos (2 per application): you (or a labeller) write the steps you see, using `docs/labelling_guide.md`, one file per video under `eval_data/gold/`. Labels must come from people.
- Extend `ingestion/eval/` with per-application metrics: step recall and precision (matched on feature id plus time overlap), feature-tag accuracy, timestamp error, share of steps with a checkable end state, share with how-to and check lines, flags per step.
- Prompt v7 only if the numbers show a specific failure; compare on cheap model first.
- Tests that prove it: the metric functions on hand-made pairs (offline); the baseline table saved in `docs/` with its run ids.
- Out of scope: claims of accuracy from author-written expectations; more than one repeat per video.

### Phase 2: close knowledge gaps, driven by the matrix (Nov 1 to Nov 15)
Goals: every P0 feature has at least one cited entry in each application where it is supported; Houdini stops being the weakest.
- `knowledge/rigging_knowledge.json`: P0/P1 gaps first (matrix section "Gaps that matter most": Blender 47, Maya 32, Houdini 48 of 54 P0/P1 features lack an entry). Houdini first: Skeleton SOP, Orient Joints, Skeleton Mirror, IK Chains / Full Body IK, Rig Doctor, Configure Controls, Character Blend Shapes; then Blender controls and constraints; then Maya preparation and weights.
- Give `prerequisites` a tier and a source (currently untiered strings in all 23 entries).
- Add `effects` (derived node states) for Houdini and Blender features, using node and constraint types confirmed in the real applications.
- Tests that prove it: `tests/test_rigging_knowledge.py` (cited sources, tiers, unknown ids rejected); matrix totals rise; `tests/test_scene_chain.py` effects name only types the profile knows.
- Out of scope: animation stage (ANIM, CURV, LAYR, LOCO, MOCP), Reddit and Stack Exchange mining, retargeting.

### Phase 3: close the loop in real applications (Nov 8 to Nov 22)
Goals: for the MVP rigging features, build a scene, run the steps' predicates, see met/unmet in the real application.
- Feature fixtures: for each MVP feature with a derived state, one build script per application next to `tests/fixtures/verification/` plus a test through `verification.runner`.
- Per-step replay (state after each step) is out of scope for the harness today (it checks the end state); decide whether the demo needs it.
- Predicate kinds `name_exists`, `attribute_exists`, `node_count`: **blocked on Mehak and Umaima** (`docs/proposal-predicate-kinds.md`); the harness gets the three checkers the day they agree.
- Demo (Nov 22): per application, one real video, steps, the matrix row for its features, and the harness result on a prepared scene. Limits stated on the slide.
- Out of scope: any vision, overlay or UI work.

### Phase 4: after the demo (Dec onward)
Segmented long videos (chapters), two-pass extraction, captions combined with video, animation features, Rigify and APEX depth, reviewed-workflow promotion with named reviewers, FYP-2 evaluation. Re-plan from the Phase 1 numbers.

## 3. Risks to the plan
- **Model overload (503) and prices.** Extraction depends on Gemini capacity; a billing key may help but that is unverified. Prices double on 2026-12-01 (4 Argon) and 2027-01-01 (3.8 Flash): run reported batches before then.
- **No gold, no accuracy claim.** Until Phase 1 gold exists, every quality number is "author-written expectations" and must be labelled so.
- **Houdini Apprentice licence** is non-commercial; fine for the project, to be stated.
- **Maya** is untested code until it is installed.

## 4. What the vision and app owners need from my contract (not their plan)
For Mehak (app, session engine) and Umaima (vision, overlay). Only what the ingestion output promises or asks of them:
1. **The contract they consume:** `shared/step_record.py` schema 0.10 (PR stack #7 to #12 carries `app: blender|maya|houdini`; `main` still says Blender only, which conflicts). Please confirm the wide list.
2. **Predicate meaning:** `expected_state` is a conjunction of the closed kinds; `node_exists` targets are application node/object type names (Maya `ikHandle`, Houdini labels like `Rig Doctor`, Blender object or constraint types such as `ARMATURE`, `IK`). `verifiable=false` means "guide, do not grade".
3. **Unknown kinds:** the app should treat a kind it cannot read as "not checkable", never as failure (needed for the 0.11 proposal).
4. **Honesty fields to display:** `support` (narrated vs demonstrated), `provenance`, `flags`, `how_to[].support` (shown / said / catalog). Steps are drafted, not reviewed, unless `review_status` says so.
5. **Observed state shape:** `verification/checker.py` documents the snapshot the harness uses (`mode`, `selection_types`, `node_types`, `properties`). If the add-on or vision side reports state, a compatible shape lets the same checker run on live state. Their decision whether to adopt it.
6. **Decisions requested:** approve or change the three proposed predicate kinds; confirm `StepVerification.observed_source` values (today `addon`, `user_report`, `screenshot`, `test_fixture`; headless reads of a saved scene fit none exactly).
