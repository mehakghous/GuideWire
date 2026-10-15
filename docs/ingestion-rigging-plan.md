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
