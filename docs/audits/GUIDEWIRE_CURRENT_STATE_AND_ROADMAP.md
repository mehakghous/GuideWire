# GuideWire: current state, audit findings and roadmap

Audit date 2026-10-11. Branch `ayesha/ingestion-foundation` (HEAD `a348464`), working tree with about 56 uncommitted paths (nothing was committed, reverted or deleted by this audit). Scope: the ingestion subsystem, which is the only part of GuideWire that exists in this repository (see 2.1).

**Labels.** **[V]** verified by running it in this audit (command given). **[S]** read in the source. **[H]** hypothesis, not tested. **[AW]** expectations written by the assistant (a regression measure, not independent accuracy). **[LIVE]** a real external call made in this audit.

---

## 1. Executive summary

1. **There is no product surface yet.** `app/` and `vision/` contain only `.gitkeep`. The only way to use GuideWire is a command-line tool (`python -m ingestion.cli`). Nothing in the repository can show steps to a user, observe Blender, mark progress, or hold a conversation. [V]
2. **The ingestion engine itself is real, offline-first and well tested.** A deterministic router answers or declines without any model call (36 of 39 corpus requests need none); a catalog of **14** Blender operations plus a local index of **284** manual pages back the answers; transcripts become narrated, evidence-quoted, timestamped steps; written instructions keep the user's wording and get validated. [V]
3. **Conversation (follow-ups) now exists in code but is not reachable by a user.** `ingestion/session.py` and `ingestion/followup.py` resolve 14 kinds of follow-up against a current step and never mark a step done because it was asked about. The only callers are tests and an evaluation script. No CLI command, API or UI exposes them. [V, S]
4. **Hard ceiling: coverage.** Everything deterministic is limited to the 14 catalog operations (plus experimental manual mappings). Any other instruction becomes a flagged, unvalidated step. A large share of real tutorial content is therefore either unrecognised or only passed through. [S]
5. **No observation of Blender.** No add-on, no screen capture; "observed state" is a dictionary nobody supplies. Claims such as "this option is missing" or "step verified" cannot be grounded in anything except what the user says. [S]
6. **The Gemini experiment could not be completed today.** It was resumed under its original protocol with a new no-retry switch. The three completed cells were reused from cache (after fixing a real cache-key bug the audit found); the three missing cells each got one attempt and each returned HTTP 503 ("high demand"). Experiment status: **3 of 6 cells complete, unchanged**; no conclusion can be drawn beyond the earlier directional results. [V, LIVE]
7. **Test suite: 378 pass, 3 strict expected-failures, 2 live tests deselected; stable and order-independent.** A defect-injection probe caught 18 of 18 injected defects after this audit's additions (13 of 18 before). The suite still cannot show that generated instructions are *good*: almost all expectations are written by the same author as the rules. [V]
8. **Biggest risks, in order:** (a) no way for a user to reach any of this; (b) no observation of Blender; (c) catalog coverage; (d) no independent labelled data to measure quality; (e) the model path is barely evaluated (one video, three completed runs, and the last attempt hit an overloaded service).

---

## 2. Feature inventory with verified status

### 2.1 What exists, and where it is reachable

| Capability | Entry point | Status | Evidence |
|---|---|---|---|
| Question routing (how-to, concept, shortcut, troubleshooting, vague, unsupported) | `cli ask` → `router.route` | **Implemented, verified; limited to the catalog + manual index** | CLI runs below; class accuracy 93.8% dev / 90.7% held-out (author labels) |
| Local manual index (284 pages, SQLite FTS5) | `cli ask` (needs `knowledge/kb.sqlite`, git-ignored build artefact) | Implemented; **absent on a fresh clone until built** | [S] `ingestion/kb/*`; 4 tests skip without it |
| Written instructions → steps | `cli ask "<instructions>"` | Implemented, verified; catalog-limited | negation, conditionals, key+description merge, wrong-shortcut and menu flags tested |
| Transcript (SRT/VTT/timed text) → narrated steps | `cli transcript FILE` | Implemented, verified; **dev-video recall 0.55 / precision 0.81** (optimistic; tuned on it) | `transcript_eval` |
| Key-press narration → one step per key | same | **New today**, tested | `hit tab, then 1 …, then g …` → 3 steps |
| Manual step list validation | `cli validate FILE` | Implemented, verified | |
| YouTube URL → steps | `cli ask URL` returns *"needs a transcript or a model"*; `cli video URL` calls Gemini | **Two disjoint paths**: the router never produces steps from a URL; the model path is CLI-only and quota-bound | [V] |
| Captions for one video | `cli captions VIDEO` | Opt-in, third-party, undocumented endpoint (terms risk) | §77 of the plan |
| Caption **tracks** (creator/auto) via official API | `cli find … --verify-captions N`, `api.caption_tracks` | **New today, verified live**: works with a plain API key, about 50 quota units per call | [LIVE] returned `asr` for a video whose platform flag is false |
| Tutorial discovery over a curated index | `cli ask "find a tutorial …"`, `cli find` | Implemented; **index = 8 reviewed entries**; 67 unreviewed candidates in a separate file | [V] |
| Ranking (relevance, version, level-from-title, length, source, verified captions, stated tie-breaks) | `tutorials.discover` | **Reworked today**, tested (19 tests) | |
| Playlist expansion | `cli playlist URL` | **Verified live** on your playlist: 12 videos in order, 0 unavailable, 2 quota units | [LIVE] |
| Selected tutorial → ingestion (local transcript → cache → optional injected fetch; section slicing; provenance) | `handoff.plan_ingestion` | Implemented, tested; **not reachable from any CLI command** (only `answer_kb` uses its URL helpers) | [S] |
| Follow-up conversation (session, 14 intents, step status, pause/resume, verification) | `followup.respond` | Implemented, tested; **not reachable by a user** | grep: no importer outside tests/eval |
| Reviewed-workflow store / `promote()` | code only | **Empty** (`knowledge/reviewed` does not exist); no review/edit UI | [V] |
| Screen/grounding arithmetic | `shared/grounding.py` | Implemented, tested; **imported by nothing** | [S] |
| Blender add-on / state observation | – | **Does not exist**; `scripts/dump_blender_vocab.py` was never run (Blender not installed) | [S] |
| Desktop UI, screen capture | `app/`, `vision/` | **Do not exist** (empty) | [V] |
| Gemini video / written extraction | `cli video`, `cli written` | Implemented; evaluated on one video | §2.5 |
| Training-example schema + leakage-safe split | `ingestion/training/*` | Implemented as a proposal; nothing uses it | |

### 2.2 Declared but unused

`requirements.txt` lists `PyQt6`, `opencv-python`, `mss`, `bcrypt`; no file imports any of them. [V by grep] They look like teammates' placeholders; `bcrypt` has no stated purpose.

### 2.3 Schema fields never populated by the deterministic routes [S, heuristic grep]

`Step.version_dependent`, `Step.common_mistakes`, `Step.visual_evidence` are filled only by the model path. Consequence: the follow-up answers "will this work in my version?" and "I made a mistake" cannot draw on them for catalog steps. `AnswerBundle.needs`, `TutorialRecommendation.captions_available/level_claim` have no consumer (the UI does not exist).

### 2.4 Provenance and evidence through the pipeline [V]

Steps carry `provenance`, `source_refs`, `evidence`, `support`, `assumptions`, `flags`, `video_start_s/end_s`. Transcript steps keep verbatim quotes and times; catalog steps carry `catalog:<op>@main`; manual-derived steps carry `SourceRef` with licence and read date. After `Session.load` the tutorial identity (title/link/recorded version) is kept **only if** the source is a `tutorial_video` reference (a defect where a cited manual page was mistaken for the tutorial was found and fixed in this work).

### 2.5 The model path

Prompt v2 (baseline) and v3 (candidate) video extraction with schema validation, evidence checks and a controlled experiment runner (cached cells, notional-cost ledger, hard stops). Evaluated on **one** video (188 s) against an assistant-read reference. See section 6.

---

## 3. Application execution: what a user can actually do today

The CLI is the only surface. Each row is a real subprocess run (`scratchpad/cli_scen.py`, 17 commands). All offline except where noted. Latency is wall time including Python start-up.

| Scenario through the real entry point | Result | Time |
|---|---|---|
| `ask "How do I join two objects?" --version 2.80` | procedure, 2 steps, 1 prerequisite question, 0 model calls | 0.8 s |
| `ask` concept ("difference between Object and Edit Mode") | concept answer, no steps | 0.75 s |
| `ask "Why didn't that work?"` (no session exists) | clarification question, no steps | 0.8 s |
| `ask "Find a tutorial for selecting and moving objects" --version 2.80` | 2 recommendations from the curated index | 0.75 s |
| `ask "<youtube url> turn this into steps"` | `needs_model`: explains it needs a transcript or a model; no steps | 0.86 s |
| `ask "<vimeo url> …"` | `unsupported`, nothing fetched | 0.8 s |
| `ask "Press Tab …. Select two vertices. Press G …"` | 3 steps, assumption question | 0.74 s |
| `ask "   "` (empty) | clarification | 0.79 s |
| `transcript tests/corpus/transcript_synthetic.vtt` | 10 narrated steps | 0.63 s |
| `validate shared/examples/…json` | accepted, 4 steps | 0.62 s |
| `find "rigging a character" --candidates` | 3 results with notes | 0.69 s |
| `transcript no_such_file.vtt` | **raw `FileNotFoundError` traceback**, exit 1 | – |
| `transcript README.md` | **raw `ValueError` traceback**, exit 1 | – |
| `validate pytest.ini` | **raw `JSONDecodeError` traceback**, exit 1 | – |
| `playlist https://example.com/x` | clean error, exit 2 | – |
| `playlist <real playlist>` **[LIVE]** | 12 videos, order kept, 2 units | – |

**The multi-turn user journeys you listed cannot be run through a product**: there is no command that holds a session. They were exercised through the evaluation harness (section 5), which calls the same code a future UI would call. Not testable here: desktop UI, Blender integration, real screen state, user review/editing of generated steps, real users.

---

## 4. Test suite audit

| Item | Result [V] |
|---|---|
| `pytest -q` | **378 passed, 2 deselected (live), 3 xfailed (strict)** in about 17 s |
| Distinct test functions | 277 (381 items including parametrisation and expected-failures) (the 39-case corpus is 39 items) |
| Stability | identical results on repeat, each file alone, reverse file order, and from another working directory |
| Skips | none in this checkout; **4 tests depend on git-ignored data** (`knowledge/kb.sqlite`, `local_data/`) and would skip silently on another clone |
| CI | **none** (`.github` absent) |
| Linters / types / coverage | **none installed** (`pip list` shows only pytest). `compileall` is clean. A hand-rolled AST scan found 6 files with unused imports (cosmetic) |
| Defect-injection probe | 18 plausible defects, one at a time: **13/18 caught by the suite as it stood, 18/18 now** (`runs/results/mutation_probe*.txt`). One survivor was a genuine old gap (section end boundary) |

**Where the suite is weak.** (1) Almost every expectation about *quality* is written by the author of the rules ([AW]): the suite proves they behave as intended, not that they are right. (2) The model path is tested with a scripted fake provider that cannot produce the odd outputs a real model gives; real-response fixtures exist for two runs only. (3) No test crosses UI → backend (no UI). (4) `test_no_socket_is_needed` covers 12 of 39 corpus cases. (5) A vacuous test (`test_interrupted_cells…`, assertions ending `or accepted`) was found and strengthened. (6) Tests can pass while steps are factually wrong, e.g. a wrong catalog entry would be reproduced faithfully (the catalog was cross-checked against the manual for 5 of 14 entries only).

**Confirmed gaps recorded as strict expected-failures (3 left):** transcript route has no mode-prerequisite chain; version-specific narration is not flagged; one spoken sentence with several actions gets spurious overlap warnings. (Two earlier ones were fixed on request: terse key narration and "Shift+A, add a cube".)

---

## 5. Follow-up conversation evaluation

Implementation: structured `Session` (procedure, tutorial identity, per-step status with who said so, current step, active flag, version, last observed state, 6 short turn notes) and a rule-based resolver. Details and the intent table are in plan §115.

| Result [V] | Dev set (23 turns, tuned on) | Held-out set (32 turns, 14 conversations, hash-frozen before the code) |
|---|---|---|
| Intent accuracy | 23/23 | **32/32** (first look) |
| Context resolution (session / standalone / clarify) | 23/23 | **31/32** at first look; 32/32 after the fix |
| State correctness | 23/23 | 31/32 first look; 32/32 after |
| False completions (a question that ended with a step done) | 0 | 0 (and 0 in 1,200 random-conversation turns) |
| Cross-tutorial contamination | 0 | 0 |

**Limits.** Both sets are assistant-written; patterns and sets share an author, so real phrasing will miss. The one first-look miss was a real bug ("Go back to the undo part" treated as a new request), fixed, so later numbers are not clean. "Response usefulness" and "recovery quality" were not measured (they need human judgement).

**Your examples.** Why this step / what does this option do / where is the button / shortcut instead / another way / don't see the option / already did that / wrong object / explain previous / Continue / Why? / the other one / different method / my version: all handled (the last three honestly: "the other one" asks which; "wrong object" is answered as *undo* because no richer recovery content exists, see GW-015). **"Question about a step never completes it": verified.** "Never claims to have observed Blender": answers say "I have no view of your Blender state" when none is supplied. **What is missing:** persistence across restarts, pronouns across several earlier turns, correcting the version mid-session, and any way for a user to talk to it.

---

## 6. Gemini experiment

**Protocol (inspected before running).** `ingestion/experiment.py`: arm A = prompt v2 (baseline), arm B = prompt v3 (candidate); same model (`gemini-3.6-flash`), video (`34FBeC9mktE`, 188 s), schema, validation, token cap 16,384 and temperature 0.2; planned 3 repeats per arm; scored against the frozen reference v1 (21 verified steps, assistant-read, not human-verified). Hard cap $3.00 notional; cumulative call/budget ledger; stops on 429; cells cached by a key over every input.

**Status today [LIVE].**

| Cell | Outcome |
|---|---|
| A1, B1, B2 | from cache (valid, from 2026-10-10), **not re-run** |
| A2, A3, B3 | one attempt each (`--no-retry`): **HTTP 503 "model is currently experiencing high demand"** each; no 429 |
| Earlier today (before the fix) | 4 phantom 503s on A1/B1/A2/B2, caused by a cache-key bug (below) |

Experiment status: **incomplete, 3/6 cells, 0 new results**. The requested rule (stop, don't hammer) was followed: each cell got exactly one attempt; the ledger's 429 flag was cleared only on your statement that the quota had reset, with a backup (`runs/ledger.backup_before_2026-10-11.json`) and a history note.

**Defect found by running it (GW-002, fixed).** `cell_key` included `SCHEMA_VERSION` (the stored contract). Bumping the contract 0.3 → 0.6 silently changed every key, so cached results were treated as missing and re-called. Fix: key on a pinned `MODEL_SCHEMA_TAG` and a test that pins the fingerprint of the schema the model actually sees; a regression test reproduces the real cell key `5e8a8a10dfe13db3`. The recomputation also proved the three cached cells' prompts and settings are unchanged.

**Scored results available (cached cells, re-scored offline today, same scorer):**

| | A (v2) n=1 | B (v3) n=2 |
|---|---|---|
| Accepted / first-attempt valid | 1 / 0 (1 rejected first attempt) | 2 / 2 |
| Demonstrated-step recall, lenient (min–max over runs) | 0.21 | mean 0.53 (0.37–0.68) |
| Precision, lenient | 1.00 | 0.96 |
| Timestamps within tolerance | 0.33 | 0.76 |
| Notional cost per run | $0.039 | $0.025–0.035 |

**What this supports and what it does not.** n = 1 vs 2 on one video with a reference nobody has human-checked; variability between the two B runs (12 steps vs 5; 0.68 vs 0.37 recall) is as large as the A/B gap. **No claim of improvement is supported**; the earlier "worth keeping as a candidate" stands only as a hypothesis. Needed: the three missing cells (when the service recovers), a human-verified reference, and at least a second video.

**One additional [LIVE] data point (single run, development video, not part of the A/B).** Text-only pass on the local transcript (no video): accepted first attempt, 17.1 s, 7,081 tokens, 8 steps; lenient recall 0.55 (same as the rules), strict 0.30 (rules 0.45), precision 1.00 (rules 0.81), timestamps within 3 s 100% (rules 80%), 0 unsupported quotes, 0 false visual claims. One video, 20 reference steps: no ranking. The union of the two methods was not computed.

**API usage today.** Gemini: 8 HTTP requests (1 success, 7 × 503). YouTube Data API: about 1,000 quota units of 10,000 (catalog candidates ~802, refresh 2, playlist 2, caption probe 50, caption-verified search 150).

---

## 7. Confirmed defects (reproducible)

| # | Defect | Reproduce | Status |
|---|---|---|---|
| D1 | Cache key tied to contract version: schema bump invalidated cached experiment cells | bump `SCHEMA_VERSION`, run `experiment run` | **Fixed + regression tests** |
| D2 | `transcript`/`validate` show Python tracebacks for a missing file, non-transcript text or bad JSON | `cli transcript no_such_file.vtt`; `cli validate pytest.ini` | Open (GW-001) |
| D3 | Follow-up code unreachable from any entry point | grep for importers; no CLI command | Open (GW-010) |
| D4 | Platform "captions" flag treated as availability: false for 62/67 live candidates and for a video with an automatic track | `captions.list` on `34FBeC9mktE` returned `asr` while the flag is false | **Fixed** (not scored; verified tracks via API; TRUE kept as "creator captions exist") |
| D5 | Negated/hypothetical/conditional instructions became steps; wrong spoken shortcut unflagged; session used a manual page as "the tutorial"; "go back to the undo part" treated as new request | see tests named in plan §118 | **Fixed** |
| D6 | Terse key narration and `Shift+A, add a cube` | | **Fixed today** |
| D7 | Transcript route does not check mode prerequisites | strict xfail | Open (GW-003) |
| D8 | Curated index still stores the old flag for its 8 entries (`False` for `34FBeC9mktE`, which has an automatic track) | `knowledge/tutorial_index.json` | Open, harmless now that it is not trusted (GW-007) |
| D9 | Ranking ties used to resolve alphabetically; 1-minute videos ranked beside 14-minute ones | | **Fixed** (stated tie-breaks; short-length penalty) |

---

## 8. Unfinished and disconnected work

Verified by grep and execution: follow-up/session, handoff planning, grounding arithmetic, training schema, evaluation harnesses → no product caller. Reviewed-workflow store → empty and unreachable. `AnswerBundle.needs` → written 13 times, read nowhere. Catalog `unverified` lists → stated to users but never closed. Manual-mapping of unmatched transcript clauses → experimental, opt-in, "about half right" on a hand review (§78). Broad `except Exception` appears 10 times; the ones read were deliberate (record-and-stop, "unknown" on failure) and the failure is reported, not swallowed, except `answer_kb._retrieved` which silently returns "unknown". No `TODO/FIXME/NotImplementedError` markers exist. Licensing: manual text is CC-BY-SA; fetched text and the index are git-ignored (verified); the third-party caption adapter relies on an undocumented endpoint (terms risk accepted by the owner, opt-in only). Secrets: `.env`, `runs/`, `local_data/`, `knowledge/cache/` are ignored; neither API key's 14-character prefix occurs in any file of the working tree (excluding `.env`) or anywhere in git history (`git log --all -S`). [V]

---

## 9. Prioritised backlog

Priority: P0 unsafe/unusable core flow; P1 major correctness/reliability on an important workflow; P2 valuable; P3 optional. Effort S ≤ 1 day, M ≤ 1 week, L ≤ 3 weeks, XL more.

### 9.1 Verified bugs and failures

| ID | Cat. | Finding | Evidence | Status | User impact | Root cause | Solution | Pri | Eff | Deps | Verification | Phase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GW-001 | Bug | CLI prints raw tracebacks on bad input | §3 rows D2 | Broken | A first-time user sees a stack trace | No error boundary in `_offline` | Catch `OSError/ValueError/JSONDecodeError`, print one line, exit 2 | P1 | S | – | 3 CLI error tests with exit code and message | Fix now |
| GW-002 | Bug | Experiment cache key tied to contract version | §6 | **Fixed in audit** | Silent re-spend/invalid comparisons | key used `SCHEMA_VERSION` | `MODEL_SCHEMA_TAG` + pinned fingerprint | P1 | S | – | 2 regression tests (done) | Done |
| GW-003 | Bug | Transcript route lacks prerequisite chain | xfail | Partial | Missing-Edit-Mode steps unflagged in tutorials | `text_steps` chain not reused | Run `link_dependencies` + the mode-chain check in `transcript_ingest` | P2 | M | – | xfail → pass; no change in dev-video recall | Next |
| GW-004 | Quality | Version-specific narration not flagged | xfail | Partial | User follows steps for the wrong version | no cue detector | Flag cues containing "in Blender 2.x / used to / old versions" | P2 | S | – | xfail → pass | Next |
| GW-005 | Quality | Overlap-warning noise from one sentence | xfail | Partial | Spurious warnings | validator treats shared span as overlap | Exempt steps sharing a source span | P3 | S | – | xfail → pass | Later |
| GW-006 | Reliability | Gemini 503 overload prevents finishing E1 | §6 | Blocked (external) | Experiment evidence stays tiny | Free-tier capacity, no control | Re-run when healthy; billing is your decision | P2 | S | service/billing | cells A2, A3, B3 accepted | Research first |
| GW-007 | Data | Curated index flags legacy | D8 | Improvement | none now | flag semantics | Replace with verified caption kind for the 8 entries (about 400 units) | P3 | S | quota | entries carry `caption_kind` | Later |

### 9.2 Partially implemented or disconnected

| ID | Cat. | Finding | Evidence | Status | User impact | Root cause | Solution | Pri | Eff | Deps | Verification | Phase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GW-010 | Incomplete | Follow-up/session/handoff unreachable | §3, §8 | Partial | Users cannot ask follow-ups or pick a discovered tutorial | built as library only | A small `ingestion/service.py` facade (JSON in/out: `route`, `load_tutorial`, `follow_up`, `state`) + `cli chat` REPL; session saved to a JSON file | P1 | M | agreed message format with UI owner | scripted conversation via the facade reproduces the held-out set; session survives restart | Fix now |
| GW-011 | Missing | No Blender state observation | §2.1 | Missing | "I don't see the option" / "verified" cannot be grounded | no add-on; Blender not installed | Read-only add-on: mode, selection, active tool, workspace, operator log; stub dict provider for tests | P1 | L | pinned Blender version, install | `observed` populated from real Blender in a recorded session | Next iteration |
| GW-012 | Missing | Reviewed workflows empty; no edit/review path | §2.1 | Partial | No way to edit or approve generated steps | no UI; store never populated | CLI `review` (list/edit/promote) over the existing store; promote the 13 catalog procedures after a human check | P2 | M | GW-010 | promoted procedure is returned by `route` with `reviewed` trust | Next |
| GW-013 | Incomplete | `shared/grounding.py` unused | §8 | Partial | none yet | no capture | Keep; wire when capture exists | P3 | – | UI/capture | – | Later |
| GW-014 | Quality | Declared dependencies unused | §2.2 | Unverified | heavier install | placeholders | Ask owners; move to extras | P3 | S | decision | fresh `pip install` smaller | Later |
| GW-015 | Quality | `common_mistakes/version_dependent` never filled for catalog steps | §2.3 | Partial | weak recovery and version follow-ups | catalog caveats not mapped | Map `Operation.caveats/unverified` into those fields; use them in follow-ups | P2 | S | – | follow-up "I made a mistake / my version" cites them | Next |

### 9.3 Missing functionality

| ID | Cat. | Finding | Evidence | Status | User impact | Root cause | Solution | Pri | Eff | Deps | Verification | Phase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GW-020 | Decision | No permitted way to turn "URL → steps" without a transcript the user brings or the third-party adapter or Gemini | §2.1; API cannot download caption text | Partial | The headline flow needs extra input | platform limits | Decide the default: user transcript → adapter (opt-in) → Gemini; surface it in the UI | P1 | S (decision) | owner | documented flow + tests | Decide |
| GW-021 | Coverage | Catalog = 14 operations | §1 | Partial | Most instructions stay unvalidated | hand-built | Generate candidate entries from manual Reference blocks, human-review in batches of 10; track coverage on real tutorials | P1 | L | GW-041 | share of tutorial steps recognised on held-out transcripts | Next |
| GW-022 | Data | Tutorial index = 8 reviewed + 67 unreviewed candidates | §6/§7 | Partial | Discovery recall is tiny | manual curation | Review the 67 (level/topic/version), promote, repeat per topic; store verified `caption_kind` | P2 | M | reviewer | precision@3 on 20 goals with a second rater | Next |
| GW-023 | Quality | Concept excerpts are the page lead | plan §71 | Partial | Weak "what is X" answers | no passage ranking | Rank chunks by query terms | P2 | S | – | gold-passage hit rate on 20 questions | Next |
| GW-024 | Missing | Session persistence, cross-turn pronouns, version corrections | §5 | Missing | Lost context after restart | in-memory | JSON persistence (GW-010), explicit `set version` follow-up | P2 | S | GW-010 | tests | Next |
| GW-025 | Decision | Schema 0.6 not reviewed by teammates | – | Unverified | contract drift | – | Review and sign off | P1 | S | Mehak, Umaima | sign-off recorded | Decide |

### 9.4 AI output quality and grounding

| ID | Cat. | Finding | Evidence | Status | User impact | Root cause | Solution | Pri | Eff | Deps | Verification | Phase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GW-030 | Research | Video-model route evaluated on 1 video, 3 runs, unverified reference | §6 | Unverified | Unknown reliability | no data, 503/quota | Complete E1; human-verify reference; second video | P1 | M | GW-006, GW-041 | ≥ 3 completed cells per arm on 2 videos | Research first |
| GW-031 | Research | Text-only model vs rules not compared on held-out data | §6 | Unverified | Unknown benefit | no labels | Experiment 0 (10 transcripts, 5 authors, second annotator) | P1 | M | GW-041 | report with disagreement-aware margins | Research first |
| GW-032 | Quality | `confidence` uncalibrated; `support` carries little information in model output | plan §46 | Partial | Misleading ranking of steps | heuristic | Use evidence-based flags, not self-rating, until calibrated on labels | P2 | M | GW-041 | reliability plot on held-out | Later |

### 9.5 Follow-up and context

Covered by GW-010, GW-015, GW-024. Additional: **GW-033 (P2, M)** richer recovery content (what to do when a step fails: documented remedies per operation) and **GW-034 (P3, S)** aging of observed state.

### 9.6 Testing and evaluation

| ID | Cat. | Finding | Pri | Eff | Solution | Verification | Phase |
|---|---|---|---|---|---|---|---|
| GW-040 | Testing | No CI, linting, type checks or coverage | P1 | S | GitHub workflow: pytest, `ruff`, frozen-hash checks; `mypy` on `shared/` | CI green on a clean clone | Fix now |
| GW-041 | Testing | No independent labels: sets are author-written | P1 | M | 10+ transcripts, ≥ 5 authors, second annotator on 25% | agreement reported | Fix now (starts everything else) |
| GW-042 | Testing | Model path tested only with a scripted fake | P2 | S | Record real responses as fixtures (R1, R4 exist) | fixtures replay the real invalid-output cases | Next |
| GW-043 | Testing | 4 tests skip silently without local data; 3 cosmetic weak tests | P3 | S | Report skips explicitly; ship a small fixture index | skip count visible in CI | Later |

### 9.7 Architecture and maintainability

| ID | Finding | Pri | Eff | Solution |
|---|---|---|---|---|
| GW-050 | Intent taxonomy and regexes are spread over `intent.py`, `answer_kb.py`, `followup.py` | P2 | M | One intent module with a single test table; keep the three entry points |
| GW-051 | `answer_extended` is one long function with ordered special cases | P3 | M | Split per pathway once GW-010 stabilises the facade |
| GW-052 | Mixed line endings (CRLF/LF) from tooling on Windows | P3 | S | `.gitattributes` already normalises; add an editorconfig |

### 9.8 Performance, reliability, security, privacy

| ID | Finding | Pri | Eff | Note |
|---|---|---|---|---|
| GW-060 | Caption adapter uses an undocumented endpoint against the platform's terms | P2 | S | Opt-in only (verified); keep, document in UI; prefer user-supplied transcripts |
| GW-061 | Licence: CC-BY-SA excerpts shown in a distributed app | P2 | S | Ask the supervisor before distribution |
| GW-062 | No secrets in the repository or history (verified); key sent as a header; errors redact it | – | – | keep the test |
| GW-063 | Start-up 0.6–0.9 s per CLI call; one test takes 11 s | P3 | S | lazy imports; mark the slow test |

### 9.9 UX and product

**GW-070 (P2, M)** show what is verified vs inferred in the guidance UI (provenance badges). **GW-071 (P2, S)** present discovery results with "captions: creator / automatic / none / not checked" and a one-click verify. **GW-072 (P3, M)** progress tracking view driven by `Session`.

### 9.10 Longer-term research

**GW-080** OCR/small-classifier trial for Blender mode labels on tutorial frames (plan Part X, only after OCR fails); **GW-081** two-pass video analysis for demonstrated-only actions; **GW-082** fine-tuning only if Experiment 0 shows a learnable gap.

---

## 10. Top 10, order, milestones

**Top 10.** GW-010, GW-041, GW-040, GW-011, GW-020, GW-021, GW-001, GW-025, GW-030/031, GW-022.

**First 3–5 tasks (dependency order).** (1) **GW-001** (S, no dependency). (2) **GW-040** CI + lint (S). (3) **GW-041** start independent labels (runs in parallel; blocks 031/030/021). (4) **GW-010** service facade + `chat` REPL + session persistence (M). (5) **GW-025** schema sign-off, then **GW-015**.

**Milestone 1 (about 2 weeks): "a person can use it end to end in a terminal".** Facade + REPL (GW-010, 024), error boundary (001), CI (040), schema sign-off (025), caveats mapped into steps (015), first 10 labelled transcripts (041). Acceptance: a scripted five-turn conversation (load a tutorial, ask why/where/shortcut, report a failure, switch task, resume) passes through the REPL; clean clone passes CI; no tracebacks on bad input.

**Milestone 2 (next): "grounded in Blender".** Add-on state (011), review/promote path (012), catalog expansion in reviewed batches (021), tutorial index review (022), Experiment 0 and the completed E1 (030/031).

**Postpone until there is evidence:** fine-tuning, vision models, embeddings, agents, anything GPU (plan Part X gate); two-pass video analysis; cross-session memory beyond a saved JSON.

**Decisions needed from you.** (a) GW-020: the default route from a URL to steps (own transcript / opt-in adapter / Gemini). (b) GW-025: schema 0.6 review by Mehak and Umaima. (c) Billing for Gemini (GW-006) or accept slow, quota-bound runs. (d) Who reviews the 67 candidates (GW-022) and labels transcripts (GW-041). (e) Pin the Blender version for the add-on (GW-011).

---

## 11. Proposed architecture changes (only where justified)

Keep the current shape: a deterministic router in front, retrieval and validators around, a model only for what rules cannot do. Add **one** thing: a thin service facade (GW-010) that owns the `Session` and exposes four JSON operations (`route`, `load_tutorial`, `follow_up`, `observe`). It is the contract the UI and the add-on talk to; nothing else needs a new service, framework or database. The session is a JSON file. Do not add a vector database, an agent framework or training until the labelled evaluation (GW-041/031) shows a measurable gap.

---

## 12. Commands run, environment, and what could not be tested

```
git status / git branch / git log                          # state before and after
.venv/Scripts/python.exe -m pytest -q                       # 378 passed, 2 deselected, 3 xfailed (x3 runs, per file, reverse order, other cwd)
python -m compileall -q ingestion shared scripts tests      # clean
python scripts/cli_scen.py (17 CLI subprocess runs)         # section 3
python mutate.py (18 injected defects, twice)               # 13/18 then 18/18
python -m ingestion.eval.{kb_eval, offline_report, transcript_eval, followup_eval}   # unchanged / as reported
python -m ingestion.experiment run --video 34FBeC9mktE --arms A,B --repeats 3 --max-calls 28 --no-retry   # [LIVE] 3 missing cells: 503 each
python -m ingestion.experiment score … --tag audit-2026-10-11                        # offline re-score
python -m ingestion.cli playlist <your playlist>            # [LIVE] 12 videos
python -m ingestion.cli find … --candidates --verify-captions 3   # [LIVE] 150 units
python scripts/run_text_model_pass.py … ; python scripts/grow_tutorial_catalog.py …    # [LIVE]
```

Environment: Windows 10, Python venv, 7.9 GB RAM, no GPU, no Blender. **Not tested:** any UI; Blender; real users; screen capture; `cli video` / `cli written` (they call Gemini; only the experiment was authorised); the two live smoke tests; caption **text** download (not possible with an API key); more than one video for any model run.

Raw outputs: `runs/results/` (git-ignored), `eval_data/results/34FBeC9mktE.text-model-pass.20261011.json`, `runs/cache/*.json`, `runs/ledger.json` (+ backup), `knowledge/tutorial_index_candidates.json`.

---

## 13. Facts, hypotheses, recommendations, open questions

**Facts [V].** No UI or capture code exists; ingestion is reachable only by CLI; follow-ups and handoff are not reachable by a user; 378 tests pass and are order-independent; the injected-defect probe caught 18/18; follow-up held-out first look was 31/32; the official API lists caption tracks with a plain key and the platform flag is false for videos that have automatic captions; the experiment cache key bug existed and is fixed; E1 is 3/6 cells and the last attempt hit HTTP 503; keys do not appear in the repository.

**Hypotheses [H].** That rules + model together beat either alone (union not computed); that catalog coverage, not rule quality, is the main recall limiter on real tutorials; that a recorded 10-transcript labelled set would change which of the two paths we prefer; that the add-on will make "missing option" answers materially better.

**Recommendations.** Section 10.

**Open questions.** The five decisions in section 10; whether the supervisor accepts CC-BY-SA excerpts and the opt-in caption adapter in the shipped app; whether the UI team wants the facade as a library call or a local socket.
