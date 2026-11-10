# GuideWire architecture (one page)

GuideWire only **observes** the learner's application window; the learner performs every action. Three components talk through one shared contract, `shared/step_record.py` (schema 0.10).

```
 tutorial (YouTube link, written steps, transcript, question)
        |
        v
 [ingestion + AI gateway]  Ayesha        -- StepList / AnswerBundle (JSON) -->  [app]  Mehak
        ^                                                                       |  review, save, session engine
        | model calls (keys live only here)                                     |
                                                                                |  asks "is step N done?"
 [vision]  Umaima  <-- screenshot + step's expected_state / ui_element ---------+
        |
        +-- observed state (dict) and screen location (Rect) ---------------->  [app]  -> overlay highlight
```

## 1. What Ayesha's code sends in (ingestion -> app)

- A **`StepList`** (`shared/step_record.py`): an ordered list of `Step` records. A step has a goal, actions, `start_state` / `expected_state` (a list of `StatePredicate`: `kind`, `target`, `value`), a `kind` (mechanics or craft), how-to and check lines for the learner, evidence and confidence. `verifiable` is derived: true only when a mechanics step has an expected state.
- An **`AnswerBundle`** (`shared/answer.py`) for questions and follow-ups, which can carry a `StepList`.
- Reaches the app as JSON, produced by `python -m ingestion.cli ...` or the AI gateway (`gateway/app.py`, `POST /v1/extract`, `/v1/answer`). Until the app calls the gateway, the app reads step files (`shared/examples/*.json`).
- **Contract rule:** the app never fails on a predicate kind it does not know. `app/step_loader.py` drops it, keeps the step and marks it "not checkable"; the learner confirms it by hand. This lets the contract grow (for example `name_exists`, `attribute_exists`, `node_count`, proposed for schema 0.11) without breaking an older app.

## 2. What Umaima's code returns (vision -> app)

- **Observed state**: a plain dict the evaluator reads, for example `{"mode": "EDIT_MESH", "active_tool": "builtin.move", "selection_types": ["MESH"], "open_panels": [...], "nodes": [...], "properties": {...}}`. A key that is absent means "not observable", which is different from "observed and wrong".
- **Screen location** of a step's target: a `Rect` (x, y, w, h in physical screen pixels) wrapped in a `GroundingResult` whose status is `ok`, `none`, `out_of_bounds`, `outside_target` or `bad_geometry` (`shared/grounding.py`, a proposal Umaima still has to accept). The app draws the overlay only for `ok`.
- The app passes `observed` to `ingestion/evaluator.py` (`evaluate_step`), which returns `met`, `unmet` or `unverifiable` per step.

## 3. What the session engine stores (app)

`app/db.py` (SQLite, file in `local_data/`, never committed):

| Table | Holds |
|---|---|
| `user` | email (unique, case-insensitive), display name, bcrypt password hash |
| `preferences` | one JSON blob per user |
| `tutorial` | title, application, source type and URL, owned by one user |
| `step` | one `Step` record as JSON plus its position, so a schema change needs no table change |
| `session` | one run of a tutorial: state (`not_started`, `active`, `finished`), current position, start and finish times |
| `session_step` | per step: `pending`, `done` or `skipped`, and who said so (`user` or `observed`) |

`app/session_engine.py` is the state machine: `not_started` -> `active (step N)` -> `finished`. `complete`, `skip` and `back` are only valid while active. `auto_check(observed)` completes a step only when every part of its expected state is observed to hold; craft steps, steps with nothing to check and steps with unknown predicate kinds are never auto-completed. Progress is written after every change, so a session survives closing the app.

## 4. App layers

`app/ui/*` (PyQt6 screens: Login, Home, New tutorial, Step Review, Session, History, Profile) call plain Python modules that need no display and are tested directly: `app/accounts.py` (bcrypt registration and login), `app/step_editor.py` and `app/step_validation.py` (edit, reorder, delete, add, save), `app/session_engine.py`, `app/db.py`, `app/step_loader.py`, `app/step_checks.py` (what can really be checked), `app/pipeline.py` (offline ingestion) and `app/guidance.py` (screen guidance).

The look is a bento grid: every screen is a grid of rounded tiles of different sizes on a soft canvas, with one accent colour for the main action. `app/ui/style.py` holds the light and dark palettes (the Profile "Theme" setting switches them) and `app/ui/bento.py` the tile building blocks (`Tile`, `ActionTile`, `header`, `page_grid`). Screens only arrange widgets in tiles; their logic is unchanged.

## 5. Screen guidance in a session

`app/guidance.py` connects the session engine to `vision.service.VisionService`. While a session is active (Blender only, Windows only, and only if the user has not turned the overlay off in their profile), the Session screen asks vision on a worker thread every 1.5 seconds:

1. `observe()` gives the state dict. If it satisfies the active step's expected state, `SessionEngine.auto_check` completes the step (marked "observed"). Craft steps, steps with nothing to check and kinds the app cannot read are never completed this way.
2. `ground(ui_element)` for the step's first named UI element gives the rectangle for a highlight; the overlay draws it. If the learner presses Done first, the late reading is dropped.

Vision only observes. If it cannot work (not Windows, OCR missing, Blender not open) the session carries on by hand and says why; a missing component switches guidance off for that session. The SQLite engine is only touched on the UI thread; the worker thread only calls vision.

## 6. Open items

- Only Blender has vision; Maya and Houdini adapters are not started.
- `name_exists`, `attribute_exists` and `node_count` (schema 0.11) are checked by the verification harness against saved scenes, but the app cannot read them live, so those steps are manual in the app.
- Display groups (schema 0.12) are not handled by the step editor yet.
