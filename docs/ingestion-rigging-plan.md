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
