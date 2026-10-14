# Ingestion plan for rigging and animation (Blender, Maya, Houdini)

Source: GuideWire_Rigging_Animation_Feature_Matrix.xlsx v0.1 (145 features, 22 categories, 51 in the MVP). Loaded by `ingestion/features.py`.

| Part | What | Done when |
|---|---|---|
| 1 | Feature catalog: matrix to `knowledge/rigging_features.json`, loader with dependencies and per-app support | Counts match the spec (145, P0 16, P1 38, P2 58, P3 33, MVP 51); no dependency cycles. **Done.** |
| 2 | Tag each step with the feature it teaches: `Step.feature_id` (schema 0.8), set by the extractor and checked against the catalog | A step with an unknown feature id is rejected by the validator. **Done** (validator and schema only; the extractor sets it in part 5, with the prompt). |
| 3 | Maya and Houdini app profiles (modes, tools, panels, node/menu names) so validation accepts them; Houdini steps can name nodes | `get_profile("maya")` and `("houdini")` work; a Houdini step may expect a node, not a mode. |
| 4 | Mechanics versus craft driven by the catalog: features whose acceptance criteria are not measurable (CLNP-04, LOCO feel) become `kind=craft` | The tagger sets `kind` from the feature, not only from the model. |
| 5 | Rigging prompt (v4) with the feature list for the app, plus rigging gold labels from your tutorials | Recall and precision per feature category on held-out tutorials. |
| 6 | Cross-app terms (XAPP-06): one glossary mapping "bone", "joint", "bind skin", "IK handle" across apps | Each MVP feature has one term per app. |
| 7 | Version-drift notes (Blender 4 to 5 bone collections, Houdini 20 to 22 APEX) on steps | Step `version_dependent` filled from the catalog. |

Order follows the matrix phases: Phase 1 (scene, skeleton, posing) first, then the rest.
