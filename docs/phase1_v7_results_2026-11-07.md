# Phase 1 first results: prompt v7 on real videos (2026-11-07)

Everything here was RUN. Nothing is an accuracy claim: no human gold exists for these videos, so the numbers describe the shape of the output, not its correctness.

## What was run

Model `gemini-3.5-flash-lite` (tier `iterate`), prompt v7 (Blender with `--rigging`), through the cost guard. Saved in `runs/phase1/` (git-ignored). Total spend about 0.27 USD (cost log: `runs/budget/cost_log.jsonl`).

| App | Video | Length | Steps | Checkable end state | Video covered | Notes |
|---|---|---|---|---|---|---|
| Maya | `8LwHLR4S1jI` beginners, Quick Rig | 703 s | 11 | 45 % | 21 % | list-level warning: steps may be missing |
| Maya | `wugi1I6Zelo` IK/FK rig | 726 s | 17 | 33 % | 79 % | |
| Maya | `r0aFUjBb-Yo` IK legs | 1040 s | 26 | 71 % | 63 % | needed a second paid call (a retry) |
| Maya | `VhhKA6U8_vQ` Part 10, leg FK controls | 520 s | **1** (2 on a repeat) | | 3 % | extraction failed to cover the video |
| Maya | `c538zkwxgTQ` quick rig and skin | 549 s | 20 | 11 % | 31 % | |
| Houdini | `HHXHbDH7c6A` KineFX, start rigging | 815 s | 8 | 40 % | 91 % | first Houdini run ever |
| Blender | `PctSMB-RGsM` leg IK | 386 s | 13 | 62 % | 60 % | first Blender rigging run ever |

Per application (mean of runs): Maya 75 steps over 5 runs, 52 % checkable, 1.5 flags per step; Houdini 40 % checkable; Blender 62 % checkable. Every step in every run has how-to and check lines and a time; 91 % to 100 % have a feature id.

## What v7 fixed

* Each application got its own node names: Maya `joint`, `skinCluster`, `ikHandle`; Blender `ARMATURE`, `BONE`, `CONSTRAINT_IK`, `MODIFIER_ARMATURE`; Houdini labels (`Skeleton`). None of v6's "joint, ikHandle, skinCluster in a Houdini prompt" mix-up appeared.
* Houdini and Blender produced valid, mostly sensible step lists on the first try (no run existed before).

## What v7 did not fix (found in these runs)

1. **Houdini node names.** The model wrote "Bone Capture Biharmonic", "Bone Deform", "Rig Pose" in steps and the validator removed them from `expected_state` (not in the vocabulary), leaving 3 of 8 steps with no checkable state. The install's labels are `Joint Capture Biharmonic`, `Joint Deform`, `Rig Pose` is listed but was removed as `RigPose` (spaces dropped). So the model must be told to copy the label exactly as the network editor shows it, with spaces.
2. **Houdini step 1** says the rubber toy geometry is a `Transform` node: wrong.
3. **Coverage.** Maya runs cover only 21 % to 79 % of the video. One video returned 1 or 2 steps for 520 s. The cheap model summarises; the stronger model could not be tried because it was overloaded (503/504 on every attempt, nothing charged).
4. **A pre-condition guess.** Maya step 1 expects `selection_type=MESH` before the model is loaded.
5. **Blender step 11** "parent the knee controller" is tagged ORNT-01; plausible but unverified.

These are failures to FIX in a later prompt (v8), cheap model first, once gold exists to measure the fix. v7 was not changed (the plan says change a prompt only when numbers show a specific failure; items 1 and 3 are that, but without gold the fix cannot be measured).

## What is NOT measured

Recall, precision, timestamp accuracy and feature-tag accuracy: they need a human gold file per video (`eval_data/gold/<video id>.gold.json`, written from `docs/labelling_guide.md`). The existing label sheets in `eval_data/labels/` are all empty (`python -m ingestion.eval.heldout` reports "the sheet has no rows" for all 12), and none of them is a rigging video except `EBgHRd5tJfE` (Blender armature). The report command is ready:

    python -m ingestion.eval.phase1 runs/phase1/*_v7_lite.json

It prints structure numbers per run and per application and fills the accuracy fields the day a gold file exists (tests: `tests/test_phase1_eval.py`).

## Not run

The 3.8 Flash ("report") model repeat of three videos, and the remaining Houdini and Blender videos of the 14-run batch: the model was at capacity. Retry later (`--tier report`); the cache means a finished call is never paid twice.
