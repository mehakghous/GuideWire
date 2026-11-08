# Real runs and the Gemini budget (proposal, 2026-10-22). NO live Gemini call has been made for this document.

## 1. What the existing real runs cover [V: read the fixtures]

| Run | App | Video | Prompt / model | Content |
|---|---|---|---|---|
| R1, R4 | Blender (modelling, not rigging) | `34FBeC9mktE`, 188 s | v1/v2, flash-lite and 3.6 flash | 2 and 4 steps, validated output |
| R5 | Maya | `dc3iRo0hb3g`, 1151 s ("Maya Character Rigging Part 9") | v4, 3.6 flash, 108,268 prompt tokens | raw response, no feature ids |
| R6 | Maya | same video | v6, 3.6 flash | 15 steps, 8 distinct feature ids, 5/15 checkable end states |

Houdini: none. Blender rigging: none. Rigging features seen live: CNST-01, CTRL-01, CTRL-04, IKFK-06, ORNT-02, SKEL-01, SKEL-03, TEST-02 (Maya only).

## 2. Proposed batch: 14 runs

Real IDs and durations exist for the Maya rows (live YouTube metadata call of 2026-10-15, saved in `runs/cache/discovery_9b4f99eb_1792090122.json`); I cannot invent IDs for Houdini and Blender: web search returned SideFX and course pages but no YouTube links, so those rows are **to be resolved with `find --live`** (YouTube Data API, free quota, 201 units each) before any Gemini call. Durations in brackets are planning assumptions (15 min), **not measured**.

| # | App | Input | Duration | Features it should exercise | Why |
|---|---|---|---|---|---|
| 1 | Maya | `8LwHLR4S1jI` Character rigging for beginners in Maya 2024 (MH Tutorials) | 703 s | SKEL, ORNT, IKFK, SKIN | whole rig, current version; also one of three transcripts already hand-labelled |
| 2 | Maya | `wugi1I6Zelo` Autodesk Maya, How to create an IK/FK Rig (Juzz 3D World) | 726 s | IKFK-06, CTRL-04, CNST | IK/FK switch; labelled transcript exists |
| 3 | Maya | `r0aFUjBb-Yo` Rigging for Beginners: IK Legs in Maya (Academic Phoenix Plus) | 1040 s | IKFK-02..05 (pole vector) | IK legs; labelled transcript exists; 2019 (version drift test) |
| 4 | Maya | `VhhKA6U8_vQ` Maya Character Rigging Part 10, leg FK controls (Sang Sang) | 520 s | CTRL-01..03 | same series as R6, tests consistency across parts |
| 5 | Maya | `c538zkwxgTQ` Quick Rigging and Skinning a character for beginners (Maya Learning Channel) | 549 s | SKIN-01..03 | skinning, an area R6 did not cover |
| 6 | Maya | `dc3iRo0hb3g` Part 9 again, stronger model | 1151 s | as R6 | control: same video, model comparison against R6 |
| 7 to 10 | Houdini | resolve with `find --live --app houdini` using: "rig a character with KineFX and skin it", "APEX autorig biped", "Houdini rig doctor and skeleton cleanup", "KineFX IK and FK controls" | [900 s each] | SKEL-01, SKIN-01..02 (capture), CTRL-08 (autorig), IKFK-02 | candidates to check on the SideFX channel: the KineFX "Fur Dude" lessons, "KineFX rigging with APEX" (about 1 h 53 min, too long: use a chapter), "Create a robot rig using APEX" (about 1.5 h, chapter only) |
| 11 to 14 | Blender | resolve with `find --live --app blender`: "set up IK on a leg", "weight painting armature deform", "bone constraints control rig", "mirror bones symmetrize" | [900 s each] | IKFK-02, SKIN-01..03, SKEL-04, CNST | covers the entries already in the knowledge base (ik_constraint, armature_deform_parent, symmetrize, bone_roll) |

Selection rules for Houdini and Blender rows: 8 to 25 minutes, English, public and embeddable, recorded for the current or previous major version (Houdini 20 to 22, Blender 4 to 5), a single task, not an auto-rig or add-on sales video, not a series part unless the series is the point. Resolve them with the `find` commands above and read the titles; then check captions with `--verify-captions 3` (about 150 units).

Balance: Maya 6, Houdini 4, Blender 4 (Maya has a head start; Houdini and Blender are the gap). Features: skeleton, orientation, IK/FK, controls, constraints, skinning at least twice each across the batch.

Each run is saved: raw response, validated step list, usage, run id, to `runs/` (git-ignored) and, once reviewed, a trimmed fixture to `tests/fixtures/real_runs/` with a README line (no caption text).

## 3. Pricing (checked 2026-10-22 on https://ai.google.dev/gemini-api/docs/pricing, "last updated 2026-10-19") [V]

USD per 1M tokens, standard tier, input / output (output includes thinking):

| Model | Now | Later | Notes |
|---|---|---|---|
| Gemini 3.5 Flash-Lite | 0.30 / 2.50 | same | free tier available; batch 0.15 / 1.25 |
| Gemini 3.6 Flash (previous generation) | 0.75 / 3.75 | 1.50 / 7.50 from 2027-01-01 | current default in this repo |
| Gemini 3.8 Flash (current) | 0.75 / 3.75 | 1.50 / 7.50 from 2027-01-01 | free tier available; implicit cache 0.075 |
| Gemini 4 Argon (flagship) | 2 / 10 | 4 / 20 from 2026-12-01 | no free tier |

The page also lists a batch price at half the standard price (usable for non-urgent reported runs). `experiment.PRICES` currently knows only 3.6 Flash, 3.8 Flash and 3.5 Flash-Lite; **4 Argon is missing and an unknown model falls back to the 3.6 Flash price, which would under-count it**.

## 4. Estimated cost of the batch [calculation, not measurement]

Assumptions: video 94 tokens per second (measured on 3.6 Flash, low media resolution; other models unmeasured), 3,000 fixed prompt tokens per run, output including thinking 4,000 to 6,000 tokens per run (measured 2,830 and 3,927 on 19 minutes), 14 runs, 11,889 seconds (198 minutes) of video in total, 1.16M input tokens.

| Model | 4k output/run | 6k output/run | with 30 % retries (6k) |
|---|---|---|---|
| 3.5 Flash-Lite | 0.49 | 0.56 | 0.73 |
| 3.8 Flash, 2026 price | 1.08 | 1.18 | **1.54** |
| 3.8 Flash, 2027 price | 2.16 | 2.37 | 3.08 |
| 4 Argon, now | 2.88 | 3.16 | 4.11 |
| 4 Argon, from 2026-12-01 | 5.76 | 6.32 | 8.21 |

Recommended plan: iterate on 3.5 Flash-Lite (about 0.6 USD for the whole batch), report with 3.8 Flash (about 1.2 to 1.5 USD), and run only the six Maya + control rows on 4 Argon if wanted (about 1.0 to 1.5 USD). Note the existing `HARD_CAP_USD = 3.00`: a full Argon batch would exceed it and needs your approval to raise. Failed 503 calls cost nothing; a rejected-then-retried answer costs twice.

## 5. Cost controls to build (step 8; nothing built yet)

What exists [V]: `experiment.py` has a cache keyed on the inputs, a ledger with call, video-second and dollar limits, `preflight_cost`, a hard cap of 3.00 USD and a stop after consecutive 503s. What is missing: all of it is outside the main path (`cli video` and the gateway call the provider directly), the cache key hashes the Blender system prompt for every app, the ledger is cumulative (no per-day ceiling), there is no token ceiling, no dev/test key separation, no model tiers.

Design (`ingestion/budget.py`, used by `cli video`, the batch runner and the gateway):
1. **Content-hash cache.** Key = hash(model, system prompt text actually sent, user prompt, video id, duration, media resolution, schema tag, app, temperature, repeat). Stored under `runs/cache/`; a hit costs 0 and is logged as a hit. Keeps the existing "only complete cells are cached" rule.
2. **Ceilings that abort the batch.** Per run: max USD, max input and output tokens, max calls. Per day: max USD and tokens in a ledger file keyed by date (UTC). Checked before each call with the preflight estimate and after each call with the real usage. Hitting a ceiling raises `StopExperiment` and writes why; the batch stops, completed cells stay cached.
3. **Cost log.** One JSON line per call (time, run id, model, key label, video id, prompt/output/thinking tokens, USD, cache hit, status). Never the key, never caption text.
4. **Keys by environment variable, never committed:** `GEMINI_API_KEY` stays the default; add `GEMINI_API_KEY_DEV` (iteration, low ceiling) and `GEMINI_API_KEY_TEST` (reported runs). A `--key dev|test` flag picks one; the log records only the label. `.env.example` gets the names without values.
5. **Model tiers.** `--tier iterate` = 3.5 Flash-Lite, `--tier report` = 3.8 Flash, `--tier strong` = 4 Argon; the prices table gets all four models and the 2026-12-01 / 2027-01-01 switches. Unknown model = refuse, instead of assuming a price.
6. **Dry run.** `--dry-run` prints per row: model, key label, estimated input tokens (from duration), output ceiling, estimated and worst-case USD, cache hit or miss, and the batch total against each ceiling; calls nothing.
7. **Google Cloud billing budget with an alert** on the project that owns the keys (not code; set by you).
8. Tests: cache hit does not call the provider (fake provider); changing the app or prompt changes the key; ceilings abort at the right call; unknown model refused; dry run makes zero provider calls; the log contains no key text (a canary key string is asserted absent).

## 6. What I need from you before any call
1. Say "go" explicitly, with the model tier and the maximum USD for the batch.
2. Approve resolving the Houdini and Blender rows with `find --live` (YouTube Data API, about 201 units per query, free quota).
3. Confirm the key plan (dev and test keys) and that Gemini billing is on.
