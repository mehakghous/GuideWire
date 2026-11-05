# Proposal: three new `PredicateKind` values (contract change, schema 0.10 -> 0.11)

From: Ayesha (ingestion). To: Mehak (app), Umaima (vision). Status: PROPOSAL, nothing implemented. `shared/step_record.py` says a `PredicateKind` change is a contract change that the other owners must agree to first.

## 1. Why

A step can only be marked "done" by the app if its `expected_state` can be read from the application or the screen. Today the kinds are `mode`, `active_tool`, `workspace`, `selection_type`, `panel_open`, `property_equals`, `node_exists`.
In the real v6 run (Maya Character Rigging Part 9, 15 mechanics steps, `tests/fixtures/real_runs/R6_maya_part9_v6.json`) only **5 steps** have an end state that is checkable and not already true at the start. After deriving node states from the knowledge base (`ingestion/scene_chain.py`, `python -m ingestion.cli chain`) it is **6 of 15 (40%)**.
The other 9 cannot be expressed. `node_exists` names a node TYPE, so "a second joint chain", "a renamed joint" and "a new attribute" look identical before and after.

## 2. The 9 steps that stay unverifiable, and what each needs

| Step | What the learner does | Why `node_exists` fails | Needs |
|---|---|---|---|
| s02, s10 | Rename the joints / the switch control | The type is unchanged, only the name | `name_exists` |
| s11 | Add the custom attribute `FK_IK_Switch` | No node is created | `attribute_exists` |
| s04, s05, s07 | Duplicate the joint chain (twice); second parent constraint | A `joint` / `parentConstraint` already exists, so the validator flags "expected state already holds" | a count (`node_count`) |
| s09 | Freeze transforms | Values change, no node | `property_equals` already exists, but needs a target object; not a new kind |
| s14 | Create a `reverse` node | `reverse` is missing from the Maya node list | vocabulary only (add to `profiles.py`), no contract change |
| s03, s15 | Orient the joints; test the switch | Orientation / behaviour, not a state a program reads reliably | stays unverifiable (craft-like); no change proposed |

So **6 of the 9** (s02, s04, s05, s07, s10, s11) are fixed by the three new kinds, 2 by existing means, and 2 stay out of scope. Expected result on this video: about 12 of 15 (80%) with the new kinds alone, an estimate, not a measurement.

## 3. The proposal

| Kind | `target` | `value` | Example | Where a person can see it |
|---|---|---|---|---|
| `name_exists` | node/object name | none | `left_hip_IK_jnt` | Outliner |
| `attribute_exists` | `object.attribute` | none | `l_switch_GEO.FK_IK_Switch` | Channel Box / Attribute Editor |
| `node_count` | node type | expected count (number) | `joint` = 9 | Outliner (counting rows), or the app's scene query |

Rules to add to the validator: `value` is required for `node_count` and forbidden for the other two (as `property_equals` already works); `name_exists` and `attribute_exists` targets are not checked against the node vocabulary because they are the learner's own names.
Count semantics: "at least N" is safer than "exactly N" (a learner may have extra nodes). Proposed: `node_count` means at least.

## 4. What each owner would have to do

- **Ayesha (ingestion):** bump `SCHEMA_VERSION` to 0.11; extend the validator; add the kinds to the model-facing schema, which changes `MODEL_SCHEMA_TAG` and the pinned fingerprint in `tests/test_experiment.py`; teach the prompt; derive them from the knowledge base where a feature always implies them; update the rubric. About 1.5 days. No paid call is needed to build it; one live run (about 0.10 USD) to confirm the model uses them.
- **Mehak (app):** the step display and the session engine must accept the new kinds. An old app that meets an unknown kind should treat the step as "not checkable", not fail. Please confirm that is how the session engine behaves today.
- **Umaima (vision):** can the grounding layer answer these from a screenshot? Names and attribute rows are visible text (Outliner, Channel Box); counts need the row count. If a kind cannot be answered reliably from the screen, say so now and we drop or change it before building.

## 5. Risks and open questions

- Names are the learner's own. A tutorial says `left_hip_IK_jnt`; a learner may type `L_hip_IK`. Options: match loosely, or accept a "name contains" check. Not decided.
- Counts depend on the learner's scene having no extras, hence "at least".
- Blender and Houdini have no node-type vocabulary for Blender today; these three kinds are app-neutral, but only Maya is measured here.
- Nothing was tested in a running Maya; the table in section 2 is from the saved run and my reading of it.

## 6. Decision needed

Mehak and Umaima: approve, change or reject each of the three kinds. Without agreement from both, ingestion stays on the current seven kinds and the figure stays at 40% on this video.
