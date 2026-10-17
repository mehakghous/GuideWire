# Ingestion plan for rigging and animation (Blender, Maya, Houdini)

Source: GuideWire_Rigging_Animation_Feature_Matrix.xlsx v0.1 (145 features, 22 categories, 51 in the MVP). Loaded by `ingestion/features.py`.

| Part | What | Done when |
|---|---|---|
| 1 | Feature catalog: matrix to `knowledge/rigging_features.json`, loader with dependencies and per-app support | Counts match the spec (145, P0 16, P1 38, P2 58, P3 33, MVP 51); no dependency cycles. **Done.** |
| 2 | Tag each step with the feature it teaches: `Step.feature_id` (schema 0.8), set by the extractor and checked against the catalog | A step with an unknown feature id is rejected by the validator. **Done** (validator and schema only; the extractor sets it in part 5, with the prompt). |
| 3 | Maya and Houdini app profiles (modes, tools, panels, node/menu names) so validation accepts them; Houdini steps can name nodes | `get_profile("maya")` and `("houdini")` work; a Houdini step may expect a node, not a mode. **Done** (`ingestion/profiles.py`, `node_exists` predicate, schema 0.9). |
| 4 | Mechanics versus craft driven by the catalog: features whose acceptance criteria are not measurable (CLNP-04, LOCO feel) become `kind=craft` | The tagger sets `kind` from the feature, not only from the model. **Done** (`CRAFT_FEATURES` in `ingestion/features.py` is a PROPOSED list of 4; confirm it). |
| 5 | Rigging prompt (v4) with the feature list for the app, plus rigging gold labels from your tutorials | Recall and precision per feature category on held-out tutorials. **Prompt done** (v4, `feature_id` in the model schema). Gold labels wait for your tutorials. |
| 6 | Cross-app terms (XAPP-06): one glossary mapping "bone", "joint", "bind skin", "IK handle" across apps | Each MVP feature has one term per app. **Done** (`ingestion/terms.py`: concept words plus `suggest_feature`, not wired into the validator). |
| 7 | Version-drift notes (Blender 4 to 5 bone collections, Houdini 20 to 22 APEX) on steps | Step `version_dependent` filled from the catalog. **Done** (`VERSION_NOTES` in `ingestion/features.py`, 11 notes the matrix states). |

Order follows the matrix phases: Phase 1 (scene, skeleton, posing) first, then the rest.


## Milestone 2: prerequisite report (Implemented, verified by tests; no application integration)

`python -m ingestion.cli features steps.json` reads a step list (or an answer bundle holding one) and prints which catalog features it teaches
(`feature_id`, else a labelled guess from `terms.suggest_feature`), which are craft or unsupported in the app, and which prerequisites no step covers.
Code: `ingestion/feature_report.py`. Tests: `tests/test_feature_report.py`.

| Criterion | Status |
|---|---|
| A tagged step reports its feature and uncovered prerequisites in teaching order | Verified (test) |
| Covered prerequisites are not reported missing | Verified (test) |
| Guesses stay separate from tags and never change a step | Verified (test) |
| Unknown, craft and unsupported features are called out | Verified (test) |
| Works for Blender, Maya and Houdini step lists | Verified on step lists only; no application is installed here |
| Missing file gives a one-line error | Verified (test) |

Known limits: the guess is deliberately cautious, so many steps stay "unmatched" until the model sets `feature_id` (prompt v4) or a person does.
Fixed on the way: `--prompt-version v4` was missing from the extraction CLI choices.


## Milestone 3: written rigging procedures for Maya, Houdini and Blender (Implemented, verified by tests; no application integration)

`python -m ingestion.cli ask --app maya "Create joints down the arm\nCreate an IK handle on the leg\nBind skin to the skeleton"` returns a validated
step list (route `rigging_text`) with feature ids, `node_exists` expectations for created nodes, craft marking, and the prerequisites it assumes.
In chat: `/app maya`, `/load steps FILE`, `/observe nodes=joint`; the session file keeps the app. Code: `ingestion/rigging_text.py`, `router.route(app=)`,
`Session.app`, `Service /app`. Tests: `tests/test_rigging_text.py` (9).

| Criterion | Status |
|---|---|
| Clauses become steps keeping the user's wording, labelled drafted automatically | Verified (unit) |
| Features are tagged only on a clear match; the rest stay flagged and are counted | Verified (unit) |
| "Create <known node>" expects that node; other steps claim nothing verifiable | Verified (unit) |
| Craft steps are not graded; prerequisites the text skips are listed | Verified (unit) |
| Router sends Maya/Houdini procedures here, questions get a clarification, Blender modelling text is unchanged | Verified (router test plus the 493 existing tests) |
| CLI `ask --app` works | Verified (CLI test, manual run) |
| Chat: `/app`, load, observe nodes, verify met/unmet, restart keeps app and position; old sessions open | Verified (service test) |
| Works inside real Maya / Houdini | Blocked: neither is installed here; nothing reads a live scene |


## Milestone 4: review and promote (GW-012) (Implemented, verified by tests; the store is empty)

`python -m ingestion.cli review show|edit|promote|list`, see technical plan section 18. Tests: `tests/test_review.py` (11).

| Criterion | Status |
|---|---|
| A reviewer can see steps and flags, change goals, remove and reorder steps | Verified (unit, CLI) |
| Bad edits (unknown step, empty goal, no steps left, move before a dependency) are refused with a reason; input untouched | Verified (unit) |
| Promotion needs a named person, marks steps reviewed only then, and a refused promotion stores nothing | Verified (unit, CLI) |
| A promoted workflow is served by `ask`/`chat` only for a known version inside its range | Verified (router, service) |
| Works for Blender catalog text and for Maya/Houdini rigging text | Verified for rigging text; the catalog path is covered by the existing reviewed-workflow tests |
| Real reviewed workflows exist | Not done: needs a human reviewer |


## Milestone 5: transcript prerequisite chain, GW-003 (Implemented, verified by tests)

Criteria: xfail becomes a pass (Verified); a transcript that enters Edit Mode first is not flagged (Verified); one that went back to Object Mode is flagged
(Verified); no step is added or removed (by construction; the existing recall and corpus tests still pass). Details: technical plan section 19.


## Milestone 6: version cues in transcripts, GW-004 (Implemented, verified by tests)

Criteria: xfail becomes a pass (Verified); the user's own version and plain narration are not flagged (Verified); "used to / older versions" wording is flagged (Verified).


## Milestone 7: overlap noise, GW-005 (Implemented, verified by tests)

Criteria: xfail becomes a pass (Verified); real overlap between separate passages is still flagged (Verified). Known follow-up: wrong-shortcut flags on multi-step sentences (technical plan section 21).


## Milestone 8: passage ranking, GW-023 (Implemented, verified by tests)

Criteria: right paragraph for 20 synthetic questions, 20/20 against 0/20 for the lead (Verified, synthetic); lead kept when it already answers (Verified); excerpt verbatim, length-limited, source is the page (Verified);
sensible on the real 294-page index (spot-checked by hand, 3 questions). Independent gold questions: Not done (GW-041).


## Milestone 9: rigging goal to ranked tutorials (Implemented, verified with injected search; not yet run live)

`python -m ingestion.cli find --app maya "rig a biped character in Maya 2024" [--live]`. Tests: `tests/test_rigging_discovery.py` (12).

| Criterion | Status |
|---|---|
| Goal gives app, version, stages, a dependency-ordered plan, assumed prerequisites | Verified (unit) |
| No application named: ask, spend nothing | Verified (unit) |
| At most 2 searches; quota counted; duplicate videos looked up once | Verified (unit) |
| Other-application, unembeddable and unrelated videos are excluded with a reason; best match first; older versions penalised not removed | Verified (unit, fake search) |
| `--live` uses the Data API and reports the cost; API errors are one line | Verified with the API stubbed |
| Real YouTube results are sensible for a real goal | Run twice live on 2026-10-15 (402 units) and read by hand; four ranking faults fixed (technical plan 23.1). Judged from titles only; whether they teach it is unknown |
| Length judged against the goal, not fixed | Verified (unit tests; real results re-ranked by replay) |
| Chat integration (`/find`, `/load video`) | Not done |


Tests added after the live runs (18 in total in `tests/test_rigging_discovery.py`): query without filler, auto-rig penalty and the exception, series note, stage credit, area wording, save and replay without quota.


## Milestone 10: first video extraction (live) and multi-application transcripts

| Criterion | Status |
|---|---|
| One real rigging video to steps through Gemini with prompt v4 | Done once (technical plan 24.1): 10 steps, valid feature ids, no times, no expected state |
| Prompt fixes for times and `node_exists` | Written; not yet re-tested live (needs a second paid call) |
| Prerequisites reported once, not once per feature | Verified (unit) |
| Transcript to steps for Maya, Houdini, Blender rigging; CLI and chat; old Blender behaviour unchanged | Verified (`tests/test_rigging_transcript.py`, 9 tests, full suite 552 passed) |
| Transcript route run on a real rigging transcript | Not done: needs a transcript (yours, or the opt-in captions adapter) |


## Milestone 11: better discovery and actionable steps (implemented, verified offline; prompt v5 not run live)

| Criterion | Status |
|---|---|
| Diagnosis of the Maya run traced to code | Done (technical plan 25.1) |
| Recency as a configurable, explainable signal that never beats relevance on its own | Verified (`tests/test_discovery_quality.py`) |
| Upload date distinguished from recording date and software version; missing dates neutral | Verified |
| Plain-language requests without specialist terms; narrow stays narrow; one question when ambiguous | Verified (everyday phrasings and technical ones) |
| Steps carry how-to lines, checks and results with support labels and evidence | Verified (`tests/test_instructions.py`) |
| Before/after quality measurement | Done on the real response: 43.8 -> 62.5 (rubric, structure only) |
| Prompt v5 produces actionable steps from a real video | NOT measured: needs one paid call (about 0.09 USD at today's price) |
| Bounded retry with jitter; overload, quota and invalid distinguished | Verified (`tests/test_provider_retry.py`) |
| Instructions validated inside Maya | Not done: Maya is not installed here |


## Milestone 12: rigging knowledge base, real-speech transcripts, v5 live result (implemented; measured offline)

| Criterion | Status |
|---|---|
| Real beginner questions, terminology, mistakes and expert fixes captured as structured, sourced, tiered knowledge | Done for Maya (17 entries) and Blender (4); Houdini, Reddit and Stack Exchange NOT covered |
| Refuses to load knowledge that cites an unknown source or claims official without one | Verified (mutation tests) |
| Used by tagging, request understanding, troubleshooting, composed steps, validator vocabulary, prompt v6, transcript reader | Verified (unit and integration tests) |
| Transcript reader on REAL speech | Precision 42.3% -> 63.6%, recall 21.2% -> 53.8% on 52 labelled moments (one labeller; biased last pass) |
| Plain-language requests | 9/16 -> 16/16 on a development set written after the knowledge base (upper bound) |
| Real symptom wording finds the right answer | 9/9, with unrelated, wrong-app and Houdini text returning nothing |
| Prompt v5 on a real video | Run once (0.096 USD): the model ignored the new optional fields; they are now required (MODEL_SCHEMA_TAG 0.8); NOT re-run |
| Prompt v6 (documented names) on a real video | Written and tested offline; NOT run live |
| Cost estimate | `docs/cost-estimate.md` (rule of thumb 0.005 USD per video minute in 2026, 0.01 from 2027) |
| Instructions validated inside Maya or Blender | Not done |
