# Rigging audit, 2026-10-22: schema history, discovery, knowledge base, application checks

**Update, same day:** sections 3 and 4 below describe the repository in the morning. Since then Maya 2027 was installed and checked, the knowledge base grew from 23 to 45 entries and every application's derived states were verified in the real application; see `docs/ingestion-technical-plan.md` sections 30 and 31 and `docs/rigging_matrix.md` for current numbers.

Labels: **[V]** verified (ran it, or read the code/history in this audit). **[U]** unverified or a guess, said so.
Branch `ayesha/chain-all-routes-v2`. Nothing outside new files was modified.

## 1. Schema history 0.1 to 0.10 (`shared/step_record.py`)

The surviving git history is re-committed (cherry-picked and rebased), so only some versions exist as a commit. The one-line meanings come from the changelog comment that sits on `SCHEMA_VERSION` today **[V: read]**; the commit that carried each version is given where git shows it.

| Version | What changed | Evidence |
|---|---|---|
| 0.1 | First draft of the contract: `Step`, `StepList`, `StatePredicate` with a closed list of kinds; `app` was a free string ("blender", "unity", "davinci_resolve") | **[U]** no commit holds 0.1. The module docstring still says "v0.1, DRAFT" and the fixtures README says the first live runs (R1, R4) used "schema 0.1". Exact fields are a guess. |
| 0.2 | additive: `Step.support`, `model_confidence`, `StepList.warnings`, `video_duration_s`, `prompt_version` | changelog comment **[V]**; the first commit `a348464` is already 0.3 |
| 0.3 | additive: `support` may be "both"; `Step.visual_evidence` | `a348464` (2026-10-10) is at 0.3 **[V]** |
| 0.4 | additive: `provenance`, `source_refs`, `assumptions`; source types transcript, catalog, manual | changelog only **[U]** which commit |
| 0.5 | additive: provenance `doc_reference`; `AnswerBundle` trust, recommendations, pointers, conflicts | changelog only **[U]** which commit |
| 0.6 | additive: `Step.depends_on`, `Step.verification` (`StepVerification`); `AnswerBundle.request`, `source_section` | `8c3151e` is at 0.6 **[V]** |
| 0.7 | `app` may be blender, maya or houdini (type `AppName`); `Step.kind` mechanics or craft | commit message of `cc67c6f` / `0730f16` "schema 0.7 (maya/houdini apps, step kind)" **[V]** |
| 0.8 | `Step.feature_id` (catalog id such as SKEL-01) | changelog and `docs/ingestion-rigging-plan.md` part 2 **[V]**; no commit stops at 0.8 (the next surviving commit is already 0.9) |
| 0.9 | new predicate kind `node_exists` (a node of a type exists: Maya joints, Houdini SOPs) | `13ac7f1` message "(schema 0.9)" **[V]** |
| 0.10 | additive: `Step.how_to`, `check` (HowTo lines labelled shown / said / catalog), `Step.result` | `3a84236` / `ab6da4e` messages **[V]** |

**Why the app list widened from Blender to Maya and Houdini.** What the repository records: the rigging and animation feature matrix covers all three applications (`docs/ingestion-rigging-plan.md`, source line "Feature Matrix v0.1, 145 features"), and commit `cc67c6f` widened the list in the same change that added the Maya and Houdini profiles. The matrix is the stated driver. The earlier narrowing to Blender only (PR #4, Mehak, 2026-10-12, now on `main`: `app: Literal["blender"]`, comment "GuideWire is scoped to Blender") was written before the three-application decision and conflicts with it; PR #12 (`app: AppName`) restores the wide list. The reason for the decision itself (course scope, FYP direction) is **[U]**: no document in the repository states it, and I did not read `GuideWire v2 One Blender Workflow, Many Apps.docx` from Downloads.

## 2. Discovery feature (`ingestion/rigging_discovery.py`, `cli find`)

- **What it judges: titles and metadata only [V: read].** Title, chapter titles, channel, duration, licence, upload date, embeddable flag. `covers` means "mentioned in the title", never "taught". Every result says "Judged from metadata only".
- **What it calls [V]:** nothing offline. With `--live`: YouTube Data API `search.list` (100 quota units, at most 2 searches) and `videos.list` (1 unit per 50 videos). No Gemini, no transcript, no video content.
- **What it costs:** 0 USD in any mode. Live is 201 to 402 of the 10,000 daily quota units (a saved live run used 201).
- **Offline run done in this audit [V]:** `find --app maya "rig a biped character in Maya 2024"` printed the goal, a 20-feature plan in teaching order and "No local tutorial covers this and live search was not requested, so there is nothing to recommend yet." That is correct: offline mode does not search; it shows how the goal was understood. The saved live run replayed offline [V] returned 3 results and 15 exclusions.

Commands (all but the last use no network and no quota):

```bash
python -m ingestion.cli find --app maya "rig a biped character in Maya 2024"
python -m ingestion.cli find --app maya "rig a biped character in Maya 2024" --replay runs/cache/discovery_9b4f99eb_1792090122.json
python -m ingestion.cli find --app houdini "rig a character with KineFX and skin it"
python -m ingestion.cli find --app blender "set up IK on a leg and paint weights"
# network, YOUTUBE_API_KEY needed, 201-402 quota units, saves runs/cache/discovery_*.json for later --replay:
python -m ingestion.cli find --app houdini "rig a character with KineFX and skin it" --live
```

**What a bad result looks like** (each one seen in the saved Maya run or guarded by a test):
1. The top result is a part of a series ("Part 9") that touches only 3 of 6 areas you need; the replay's best score was 6.25 for exactly that. A full-rig goal wants a complete tutorial or a stated series.
2. A result about another application (a Blender video for a Maya goal) that is not excluded.
3. An auto-rig or one-click tutorial ranked high for a manual-rig goal.
4. A tutorial from many years ago with no version stated (the replay excluded 2009 to 2011 videos; a 2019/2020 one still ranked first).
5. "touch 0 of N areas" on the top hit (the second Maya result had 0 of 6: ranked by duration/recency, not content).
6. A very short video (under 3 minutes) or a livestream in the list.
7. Nothing found and no explanation: the code always writes a note, so an empty list with no note is a bug.
Because ranking is from titles, a good-looking list proves nothing about what the videos teach. Only extraction (and then a person watching) shows that.

## 3. Knowledge base audit (`knowledge/rigging_knowledge.json`, `ingestion/rigging_knowledge.py`)

**[V]** computed with the loader and raw JSON on 2026-10-22. 23 entries, 36 sources (17 official, 15 community, 4 tutorial).

| | Maya | Blender | Houdini |
|---|---|---|---|
| entries | 17 | 4 | 2 |
| catalog features touched | 29 of 145 | 9 | 10 |
| P0/P1 features supported by the app with no entry | 32 of 54 | 47 of 54 | 48 of 54 |
| troubleshooting items | 3 | 2 | 2 |
| verify (how to check) lines | 13 | 4 | 4 |
| common mistakes | 12 | 3 | 4 |
| derived node states (`effects`, used by the scene-chain check) | 6 features | 0 | 0 |
| sources | 9, all official (Autodesk help 2009 to 2026 versions) | 10: 5 official, 5 community | 5: 3 official (Houdini 22 docs), 2 community (forum) |
| statements by tier | official 30, tutorial 36, community 17, author 10 | official 22, community 5, author 1 | official 29, community 2 |
| statements with no cited source | 3 (orient_joint, paint_skin_weights, quick_rig) | 0 | 0 |

Quality notes **[V]**:
- Every tiered statement except those 3 carries a source id; the loader rejects unknown ids and "official" claims with no official source (tests mutate the file to prove it).
- **`prerequisites` are plain strings with no tier and no source in all 23 entries.** They drive the "Before this" lines, so the least-cited field is the one that tells a learner what to do first. Worth fixing (schema change inside this JSON only).
- Maya's strongest area is skeleton, IK, binding; 36 of its statements are `tutorial` tier (narrator said it) and 10 are `author` (unverified).
- Thinnest by category (zero entries in any app): animation fundamentals, graph editor/curves, motion paths, layers and retargeting, locomotion, secondary motion, mocap, rig testing, cleanup, game rigs, export, automation, cross-application. Blender and Houdini also have none for character preparation; Blender none for controls, constraints, facial; Houdini none for orientation, constraints.

**What is missing for Houdini in particular** (the file's own `_about` says Houdini beyond two entries is not covered):
1. Entries: Skeleton SOP creation and editing (SKEL-01/05), Orient Joints, mirroring (Skeleton Mirror), Rig Doctor, IK Chains / Full Body IK as their own entry (IKFK-02/03), control creation and Configure Controls beyond the AutoRig page, constraints, blend shapes (Character Blend Shapes), animation in the Animate state, Motion Clips, Biped Retarget, FBX/glTF export, ragdoll and secondary motion.
2. No `effects` (derived node states), so the scene-chain check and the new verification harness have nothing to test for Houdini. The profile already names 38 node labels (`ingestion/profiles.py`).
3. No troubleshooting beyond two forum threads; no Reddit, Stack Exchange or SideFX tutorial narration.
4. Version drift: the docs read are Houdini 22; many tutorials are Houdini 18.5 to 19 and a forum reply says those workflows do not always carry over (summary only, not read in full).
5. Nothing checked inside Houdini until this audit: it is now installed (22.0.466) and the harness reads real scenes, but no knowledge-base statement has been tried in it.

## 4. Real applications on this machine (detected 2026-10-22) [V]

| App | Result |
|---|---|
| Blender | 5.2.2 LTS, `C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`, headless `-b`, Python 3.13.13: works |
| Houdini | 22.0.466, `hython.exe` imports `hou`; licence category **Apprentice** (non-commercial; headless works) |
| Maya | **not installed yet**: no Maya folder, no registry key, no `mayapy` on PATH (only Autodesk licensing/installer components exist). Being installed; `snapshot_maya.py` and its test are written but have **never run** |

Harness (`verification/`): `python -m verification detect`; `python -m verification check STEPS.json [--scene FILE]`; tests `tests/test_verification.py` (9 passed, 1 skipped [Maya] in 47 s, including a real Blender scene and a real Houdini scene). It checks `expected_state` of each step against ONE scene, so it tests the END state of a procedure. Supported predicate kinds: `node_exists` (all three), `selection_type` (all), `property_equals` (all; Blender paths are attribute/index access only), `mode` (Blender only). Everything else (`active_tool`, `workspace`, `panel_open`, Maya/Houdini `mode`) is reported `cannot_check`, never "met".
