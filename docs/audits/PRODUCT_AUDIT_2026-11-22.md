# GuideWire product quality audit, gap analysis and roadmap (22 Nov 2026)

Branch `ayesha/session-find-chat`, HEAD `8451493`. No product code was changed for this audit. The only new file is this report. Scratch reproduction scripts live outside the repository.

**Evidence labels.** **[V]** verified by running something in this audit (a script, the test suite, or the real app rendered on screen). **[S]** read in the source and traced through the callers, but not run. **[D]** taken from the project's own documents (evaluation report, `docs/later.md`, the SRS/SDS comparison) and not re-measured. **[N]** could not be verified here (needs Blender, Maya or Houdini running, a real Windows display session, API keys or real users).

**How the UI was inspected.** The real `MainWindow` was rendered offscreen at 1366×768 (in-memory database, system fonts, no network, no vision bridge). A learner account was registered, the demo tutorials were added, and every screen was opened in turn: login, home, review, session (start, Done, Previous), Find, Ask, History, Progress, Achievements, Profile, New tutorial. Screen guidance inside a real Blender was **not** exercised [N]. The guidance logic was tested through the project's own fake vision service, driving the real session engine and vision bridge.

---

## 0. Executive summary

GuideWire has a serious, well-tested engine and an honest design philosophy (observe only, never guess, say what is blocking). It is **not yet a product a stranger could install and trust**. The biggest problems, in order:

1. **The session state machine produces false completions.** Three issues were reproduced:
   - Going back with Previous and pressing Resume completes the step again on the first look.
   - The vision bridge remembers each step's starting state by step id (`s01`, `s02`…) across *different sessions and tutorials*. A new session can therefore complete a step the learner never did.
   - Any mode, tool, selection or property step whose result already holds when it begins completes instantly, with no action. ([V], §2 S-1 to S-3)

   A tutor that marks work done that was not done undermines the whole value proposition.
2. **Jumping back to a skipped step erases the "done" status of every step after it.** [V]
3. **Guidance is Blender-only in practice.** Maya and Houdini sessions show the guidance UI, then tell the learner to "Open Maya in front so GuideWire can see it" even when Maya *is* in front: the profile is marked not validated, so vision returns no context [S]. There is no highlighting and no verification for either. **Decided 22 Nov 2026:** Maya and Houdini guidance is in scope now (G-7).
4. **There is no tutorial video experience.** The embedded player exists in code but is not wired into any screen, and it crashed Qt WebEngine on the development machine [D]. Step timestamps are generated, but nothing in the UI shows or uses them [S].
5. **Generated steps are too coarse to follow.** About 8 steps for 25 to 62 real actions, 24% one-to-one recall, and only 39% of actions covered on one Houdini video. The evidence comes from one labeller and 6 videos [D].
6. **Accounts and data exist only on one computer.** This is a local SQLite login, so there is no forgotten-password path, no staying signed in, no second device, and no backup. The login and register screens share one form. The database path is relative to the working directory, so launching from elsewhere silently shows an empty account [S]. **Decided 22 Nov 2026:** move to a hosted database (Supabase Auth + Postgres with row-level security), keeping a local cache. See §2a.
7. **It cannot be shipped as is.** There is no installer and no in-app Blender add-on setup. Provider API keys must be pasted into a `.env` file on the learner's computer (the AI Gateway exists but is not connected). There is no logging or crash report, no first-run disclosure of screen capture, and placeholder pages ("Work in progress", Achievements, Learning Paths) plus developer buttons ("Add demo tutorials", "Import sample steps") are in the main navigation [V].
8. **Asking a question during a session takes you out of the session.** The chat does not know the current step or what is on screen, and the only way back is History → Continue [S].

What is genuinely good and should be preserved:
- the confidence gate in `vision/verify.py` (no rectangle unless confident; two independent signals for toolbar cells; ambiguity draws nothing);
- screen capture never leaves the machine;
- the Blender probe binds to 127.0.0.1 and uses a per-session token;
- bcrypt with constant-time unknown-email handling;
- the per-user filtering in the data layer;
- the "a question never completes a step" rule;
- the honest evaluation culture in `docs/`.

---

## 1. Deliverable 1: current feature inventory

| Feature | Current implementation | Status | Problems |
|---|---|---|---|
| Register / log in | `app/accounts.py`, `LoginScreen`; bcrypt, email regex, 8–72-byte passwords, same error for unknown email and wrong password | Implemented but needs improvement | One form for both actions (Name field shown at login); no password confirmation; no show-password; Enter only works from the password field; no loading state [V/S] |
| Stay signed in / session persistence | None: sign in on every launch [S][D] | Not implemented | SRS FR-002 keyring token is still planned (`docs/later.md`); planned as a Supabase refresh token in keyring (§2a) |
| Password recovery / reset | Change password in Profile (needs the old password) | Not implemented (recovery) | Forgotten password = locked out of all local data; impossible without a server; planned with Supabase Auth (§2a) |
| Hosted database / multi-device / backup | None: one local SQLite file [S] | Not implemented | Planned in SRS/SDS; decided 22 Nov 2026 (§2a) |
| Logout | Sidebar → `on_logout`; clears Find state | Implemented but needs improvement | Ask screen and review editor are reset only when next opened; no confirmation if a session is active [S] |
| Duplicate accounts | `UNIQUE COLLATE NOCASE` email | Fully implemented and verified | – [V] |
| Data isolation per user | Queries filter by `user_id`; `SessionEngine` checks the owner | Implemented but needs improvement | Several DB methods (`get_session`, `get_steps`, `session_steps`, `chat_messages`, `set_step_status`) trust the caller; correct today, fragile later [S] |
| Data location | `local_data/guidewire.sqlite`, **relative to the current directory** [S] | Broken or unreliable | Launching from another folder creates a fresh empty DB: the learner's tutorials appear lost |
| Schema migrations | `CREATE TABLE IF NOT EXISTS` only [S] | Not implemented | Adding a column later breaks existing user databases |
| Home dashboard | Hero "your next tutorial", tiles, tutorial list [V] | Implemented but needs improvement | Developer tiles visible; "Start session" always creates a *new* session instead of continuing; no delete or rename of tutorials |
| New tutorial from text / transcript | `app/pipeline.request_steps` → offline router | Implemented but needs improvement | Catalog-limited outside rigging; error text exposes exception class names [S] |
| New tutorial from YouTube link | `video_steps` → Gemini 3.6 Flash with budget guard, ≤ 25 min, public videos only | Implemented but needs improvement | Needs `GEMINI_API_KEY` in a local `.env`; 1–2 minute wait with no cancel; if the learner navigates away, the result yanks them into the editor [S]; coarse steps [D] |
| Step review / editing | `StepReviewScreen` + `StepEditor`: edit goal text, reorder, delete, add, save | Partially implemented | Only the **goal** is editable; how-to, check lines, expected state, timestamps and app cannot be edited; no "drafted / reviewed" label (deferred in `later.md`); long title runs under the Back/Save buttons [V] |
| Session engine | `app/session_engine.py`: not_started → active → finished; done / skipped / pending with who set it; persisted after each change | Implemented but needs improvement | No paused state in the model; `jump_to` back wipes later statuses [V]; cannot reopen a finished session |
| Previous step | `engine.back()` + UI pause | Broken or unreliable | Resume → the step is completed again on the first look [V] |
| Pause / Resume (main screen) | UI flag `SessionScreen.paused`; stops looks, highlight and completion | Implemented but needs improvement | Text labels, not ⏸ / ▶ icons; disabled whenever guidance is not watching; not persisted [S][V] |
| Pause / Resume (floating guide) | `InstructionPanel.pause_button` | Partially implemented | The panel exists only while watching Blender, so Maya, Houdini and manual sessions have no floating guide at all [S] |
| Floating guide minimize / close / restore | Drag, resize, minimize to a tab, close for this step | Implemented but needs improvement | Once closed it only returns on the next step or via "Minimize GuideWire" [S] |
| Automatic step verification (Blender) | `evaluator.evaluate_step` + vision bridge + Blender probe | Broken or unreliable | False completions S-1, S-2, S-3 [V]; real-Blender accuracy [N] |
| Overlay highlight (Blender) | Grounders + gate + `GroundCache`; click-through overlay; window follow | Implemented but needs improvement | Gate design is sound [S]; real accuracy, DPI and multi-monitor behaviour [N]; live suite exists (`scripts/vision_live_suite.py`) |
| Maya / Houdini guidance | Profiles `validated=False`; probe files exist | Not implemented (UI suggests otherwise) | Misleading "Open Maya in front" message; the watch checkbox is shown checked [S] |
| Embedded video + timestamp sync | `app/ui/player.py` (YouTube IFrame via WebEngine), not used by any screen | Not implemented | Player never seen playing; WebEngine crash on the dev PC [D]; timestamps never shown [S] |
| Ask GuideWire chat | `app/ask.py`, `chat_context.py`, `ingestion/service.py`; saved conversations; rules + optional model | Implemented but needs improvement | Regex intent routing; no current-step or screen context; no citations list; leaving a session to ask breaks flow [S] |
| Find a tutorial | `app/discovery.py` live YouTube search + local index, cached a day, saved history | Implemented but needs improvement | Judged from title, channel and length only (says so); no difficulty or duration filters; needs a YouTube key [S] |
| History | Sessions list with Start again / Continue / Review [V] | Implemented but needs improvement | Every "Start" adds a row; unfinished sessions accumulate; no abandon or delete |
| Progress | Counts only, page labelled "Work in progress" [V] | Partially implemented | Counts include duplicate restarts; no per-tutorial view; no struggle tracking |
| Learning Paths, Achievements | Placeholder pages in navigation [V] | Not implemented | Look unfinished; Achievements risks the "artificial mastery" the brief rules out |
| Prerequisites ("Before you start") | `app/prerequisites.py`; checked once against the scene | Implemented but needs improvement | Only checked when the probe reports nodes [S] |
| Shortcut advice | `shared/shortcuts.py` uses the learner's own keymap | Implemented but needs improvement | Blender only [S] |
| Version staleness warning | Versions are known, nothing compares them [D] | Not implemented | – |
| Consent / capture disclosure | None [D] | Not implemented | Deferred in `later.md` |
| AI Gateway | FastAPI, bearer tokens, rate limits, idempotency | Partially implemented | Not used by the app; in-memory state, one worker [D] |
| Packaging / installer / add-on install | `python -m app.ui.main_window`; add-on installed by hand | Not implemented | – [S] |
| Logging / diagnostics | Almost none in the app; 43 `except Exception` blocks in `app/` [S] | Not implemented | Silent fallbacks; no crash log |
| Theme / profile | Display name, theme, guidance on/off, change password | Implemented but needs improvement | Export and delete of data deferred |
| Accessibility / keyboard | Not checked [D] | Cannot verify | No focus-order or screen-reader work seen |

---

## 2. Deliverable 2: comprehensive gap analysis

Each gap gives: **Now**, what currently happens; **Should**, what a mature product does; **Why**, why the current behaviour is insufficient; **Change**, what needs to change; **Deps**, dependencies and affected components; **Test**, how to test the fix; **P**, priority. The type is one of *Bug*, *Missing*, *UX*, or *Arch* (architectural limitation).

### A. Session state and verification (the core loop)

**S-1 Previous → Resume re-completes the step** · Bug · **P0** [V]
- **Now:** `back()` makes step N−1 pending and the UI pauses. The bridge's `_entries[step.id]` still holds the state from when the step *first* began (before the learner did it). On Resume, the first look sees the result is present, sees it was absent "at entry", and completes the step. Reproduced: `1c first look after Previous advanced: True`. Pausing only delays the bug.
- **Should:** Returning to a step re-baselines it. The step is completed only by a *new* change, or the learner is told "This step already looks done: keep it, or redo it?".
- **Why:** The learner cannot study or redo a step. It snaps forward, which is exactly the complaint in the brief.
- **Change:** Re-record the entry state whenever a step becomes active, through `back`, `jump_to`, a session load or Resume. Simplest form: the bridge gets `begin_step(step_id)`, called from the session screen on every step change, which drops `_entries[step_id]`. Also add a "Looks done already: Keep as done / Redo" affordance.
- **Deps:** `app/vision_bridge.py`, `app/ui/screens.py` (`_on_step_change`, `_previous`, `_goto_viewed`, `set_paused`).
- **Test:** Unit test with `FakeService`: complete s02, back, tick ⇒ not advanced; then change the observed state ⇒ advanced. Manual test in Blender: enter Edit Mode, Previous, Resume ⇒ stays on the step.

**S-2 Step-start state leaks across sessions and tutorials** · Bug · **P0** [V]
- **Now:** One `VisionBridge` lives for the whole app. `_entries` is keyed by step id only and is cleared only by `reset()`, which no screen calls. Step ids are `s01`, `s02`… in every tutorial. Reproduced: a new session's `s01` (bone already in the scene, learner did nothing) completed, `True`; the same case with a reset bridge gave `False`.
- **Should:** Entry state belongs to (session id, step id) and starts fresh with each session.
- **Why:** False completions on "Start again", and on any second tutorial in one app run.
- **Change:** Key `_entries` (and `_rechecked`) by `(session_id, step_id)`, or call `bridge.reset()` in `SessionScreen.load`.
- **Deps:** `vision_bridge.py`, `SessionScreen.load`.
- **Test:** The reproduction script becomes a regression test.

**S-3 Results already true at step start count as done for most predicate kinds** · Bug/design · **P0** [V]
- **Now:** `evaluator._held_at_entry` covers only `node_exists` / `node_count`. A mode, active-tool, selection or property step whose result already holds completes instantly. Reproduced: session at "Enter Edit Mode" with Blender already in Edit Mode, completed on the first look. Several steps can cascade this way while the learner reads.
- **Should:** Apply the "already true at entry is not evidence" rule to every predicate kind. Show such a step as "Already done in your scene: press Done to confirm" instead of advancing silently.
- **Why:** A false "GuideWire saw this step done" is the single fastest way to lose trust.
- **Change:** Extend `ENTRY_KEYS` (mode, active_tool, selection, property values) and `_held_at_entry`, then decide per kind whether an unchanged result is "met already, confirm" rather than "done".
- **Deps:** `ingestion/evaluator.py`, `app/vision_bridge.py`, the UI for confirmation.
- **Test:** Table-driven tests per predicate kind, covering (true at entry, unchanged) and (false at entry, then true).

**S-4 Jumping back erases later progress** · Design flaw (intended, and tested as intended) · **P0** [V]
- **Now:** `jump_to(pos)` with `pos < cur` sets *every* step from `pos` to `cur` to pending. Reproduced: `['skipped','done','done','pending']` → jump to 1 → all pending. `tests/test_app_session_engine.py::test_jump_back_makes_the_steps_from_there_pending_again` asserts this behaviour, so changing it means changing that test on purpose.
- **Should:** Going to an earlier step changes only that step. Done and skipped statuses elsewhere stay. "Next" goes to the next *unfinished* step.
- **Why:** Progress no longer reflects what happened. "Skip, then come back" destroys work.
- **Change:** Separate the *cursor* from the *statuses*. `jump_to` moves the cursor; only the target step becomes pending (and only if the learner chooses to redo it). After finishing a revisited step, return to the first pending step.
- **Deps:** `session_engine.py`, `screens.py` (`_goto_viewed`), History counts.
- **Test:** Engine unit tests for skip → return → done keeping the others; progress count unchanged by navigation.

**S-5 No paused state in the model; pause is UI-only** · Arch (small) · **P1** [S]
- **Now:** `paused` is a field on the widget. It is not persisted, and the floating panel mirrors it. The panel is hidden whenever guidance is not watching.
- **Should:** `paused` belongs to the session, shared by the main screen and the floating guide, and survives a restart. Pause works (and the floating guide exists) for manual sessions too.
- **Why:** The requirement is consistent state across both surfaces. Today Maya, Houdini and manual sessions have no pause and no floating guide.
- **Change:** Add a `paused` column (or state value) to `session`, plus `pause()` / `resume()` on the engine. The panel shows whenever a session is active, not only while watching.
- **Deps:** `db.py` (needs migrations, see D-3), `session_engine.py`, `screens.py`, `screen_guide.py`.
- **Test:** Engine tests; restart test (load session ⇒ still paused); UI test that both surfaces show the same state.

**S-6 Pause / Resume use words, not the standard icons** · UX · **P1** [S]
- **Now:** "Pause" / "Resume" text on both surfaces.
- **Should:** ⏸ (two vertical bars) and ▶ with a tooltip and an accessible name, plus a visible "Paused" badge on both surfaces.
- **Change:** Use the Qt standard icons `SP_MediaPause` and `SP_MediaPlay`, or bundled SVGs; keep the text in the accessible name.
- **Test:** UI test that the icon matches the state; screen-reader name check.

**S-7 Done / Skip / Previous / Pause transitions are not specified in one place** · UX/Arch · **P1** [S]
- **Now:** The rules are spread across `_advance`, `_previous`, `_goto_viewed` and `set_paused`. Previous pauses only while watching. Done on the last step finishes with no confirmation and no undo.
- **Should:** One written transition table (the one in Deliverable 5 is a proposal), enforced by the engine and covered by tests. "Undo last Done" stays available for a few seconds. A finished session can be reopened.
- **Test:** Property-style test over random command sequences: the invariants are no step marked done without Done or a verified change, and exactly one current step while active.

**S-8 Starting a tutorial always creates a new session** · UX/Bug · **P1** [S][V]
- **Now:** Home "Start session" and History "Start again" call `SessionEngine.create`. Unfinished sessions are never closed and pile up in History. Progress counts restarts as separate sessions.
- **Should:** "Continue" is the default when an unfinished session exists. "Start over" asks for confirmation and archives the old session.
- **Test:** Start a tutorial, leave, start again ⇒ "Continue or start over?". History shows one live session per tutorial.

**S-9 Asking a question leaves the session** · UX · **P1** [S]
- **Now:** "Ask about this tutorial" switches to the Ask screen with only the tutorial id. Back goes Home. To return to the session you go through History → Continue. Leaving the session screen stops guidance (`hideEvent`).
- **Should:** A question box inside the session (and in the floating guide) that knows the current step, previous steps and the last observed state, answered in place.
- **Deps:** `ask.py` (add a step position and observed state to `Service`), `screens.py`, `ingestion/followup.py` (already understands step context).
- **Test:** "Why do I need this?" asked on step 4 cites step 4's goal and check. The session cursor is unchanged afterwards.

**S-10 Finished sessions have no summary and cannot be reopened** · Missing · **P2** [S]
- **Now:** "Session finished. Well done!" is all the learner gets; nothing can be revisited in place.
- **Should:** A summary listing steps done, skipped and verified by GuideWire, with time taken. "Redo a step" reopens it. Skipped steps are offered.

**S-11 Who completed a step is stored but not shown** · UX · **P2** [S]
- **Now:** `status_by` ("user" / "observed") is saved; the step list shows only done / skipped / pending.
- **Should:** A distinct mark for "checked by GuideWire" against "you marked it", and a per-step badge for "GuideWire can check this" against "press Done" (already computed by `checkability`).

### B. Guidance, overlay and multi-application support

**G-1 Maya and Houdini sessions show misleading guidance** · Bug · **P0** [S]
- **Now:** `VisionService.look` returns `ctx=None` when `profile.validated` is False. The bridge turns that into "Open Maya in front so GuideWire can see it", even when Maya is in front. The "Watch my screen" checkbox is shown and checked.
- **Should:** Before the session starts, tell the learner plainly: "Screen checking is available for Blender only. In Maya or Houdini you follow the steps and press Done." Hide the watch control and keep the floating guide (S-5).
- **Change:** A capability lookup per app (`vision/apps.py`: `validated`, `toolbar`, probe present) drives the session UI. `GUIDED_APPS` exists in the dead `app/guidance.py`; move that idea into the bridge.
- **Test:** Session on a Maya tutorial ⇒ no watch checkbox; the explanatory line is shown; no "Open Maya" message.

**G-2 Real-world overlay accuracy is unmeasured outside the developer's setup** · Missing (evidence) · **P1** [N][D]
- **Now:** The live suite runs against Blender 5.2 at the pinned 1920×1080 default layout. DPI scaling, multiple monitors, non-default layouts, maximised or full-screen windows, other Blender versions and themes are not covered by any recorded result.
- **Should:** A published matrix: precision (no wrong highlight) and coverage (a highlight when one was possible) per condition.
- **Change:** Extend `scripts/vision_live_suite.py` with scaling (100/125/150%), two monitors, window resize and move, full screen, a custom layout and a non-English UI. Record the results in `docs/`.
- **Test:** Acceptance: 0 wrong highlights across the matrix; coverage reported, not assumed.

**G-3 No in-app setup for the Blender add-on** · Missing · **P1** [S]
- **Now:** The probe add-on must be installed by hand. When it is absent, guidance quietly degrades to OCR.
- **Should:** A setup screen that detects Blender installs, installs or enables the add-on (the learner confirms), and shows a "Connected to Blender 5.2" status. This is evaluated as file installation only, not control of the application.
- **Test:** Fresh machine: the guided setup reaches "connected" without reading docs.

**G-4 No status indicator that GuideWire is watching** · UX · **P1** [S]
- **Now:** The status line is inside the session page. When minimised, only the floating box shows a hint.
- **Should:** An always-visible "watching / paused / off" indicator: the floating guide's header plus a tray icon. One click pauses.

**G-5 A closed floating guide is hard to get back** · UX · **P2** [S]
- **Now:** Closing hides it "for this step". The only restore is the next step or the "Minimize GuideWire" button.
- **Should:** A "Show guide" control on the session screen and a hotkey. Closing asks "Hide for this step / turn off".

**G-6 The dead `app/guidance.py` would highlight ambiguous matches** · Arch hygiene · **P3** [S]
- **Now:** It is unused, but `_pointing` draws a highlight when `g.ambiguous`, contradicting the gate.
- **Change:** Delete it or align it with the gate, so nobody rewires the wrong controller.

**G-7 Maya and Houdini guidance and verification** · Missing · **P0, decided 22 Nov 2026: Maya and Houdini are in scope now, not later** [S][D]

**Licences are a blocker to clear on day one.** Houdini Apprentice is free but must be licensed on each computer; this machine reports "No licenses could be found" (see §9). Maya needs an Autodesk education licence. Without them nobody can build or test against the real applications.

What can be detected per application today:

| | Blender | Maya | Houdini |
|---|---|---|---|
| Window lookup | Yes, by exe | Title only | Title only |
| Live state probe | Add-on (HTTP, token): mode, tool, selection, properties, keymap, UI regions | `probe_maya.py` / `maya_probe.py` prototype | `houdini_probe.py` prototype; no licence here to test |
| UI catalogue for grounding | Dumped from 5.2.2 | Vocabulary only | Vocabulary only |
| Toolbar / icon grounding | Built | No | No |
| Headless verification | `verification/` (snapshot, checker) | Scripts exist | Scripts exist |

**Shared:** the step schema, evaluator, gate, overlay, session engine, chat and discovery. **Per application:** the window and probe connection, the UI catalogue, the grounders (menus differ: Maya shelves and marking menus; Houdini network editor, radial menus, parameter panes) and the terminology map.

**Plan, in two stages, both started now:**
1. **Verification (first).** Finish the Maya and Houdini probes so the evaluator can check node, joint, attribute and constraint existence. Houdini's node-based rigging suits this well. Window lookup by program name for both. Steps resolve against a Maya and a Houdini catalogue, as `ingestion/targets.py` does for Blender.
2. **On-screen highlighting.** Maya: main menus, shelf tabs and buttons, the Attribute Editor and Channel Box. Houdini: main menus, the network editor's Tab menu, parameter panes and shelf tools. Both go through the existing gate, so an element that is not found with confidence gets words only. This is the larger piece of work; Blender's grounders took several iterations.

**Acceptance:** in a real Maya 2027 and Houdini 22 session, steps with checkable results complete only after the learner's change (the S-1 to S-3 rules apply), and 0 wrong highlights across the G-2 matrix.

### C. Tutorial video and timestamps

**V-1 No embedded video in the session** · Missing · **P1** [S][D]
- **Now:** `player.py` is built but not placed in any screen. Qt WebEngine closed the program on the development PC with Qt 6.11 and 6.12. The `requirements.txt` pins Qt to 6.11 because of it.
- **Should:** The video sits beside the steps. Clicking a step seeks to its start; the current step is highlighted as the video plays; play, pause, seek, volume and speed are available. There is an "Open in browser at this time" fallback.
- **Change:** Spike on 2–3 other machines to separate a driver problem from a Qt problem. Fallback: the out-of-process player already started in commit `5f003d2`, or a `youtube.com/watch?v=…&t=Ns` browser deep link per step (cheap, works today). Check that the YouTube IFrame player accepts the claimed origin `https://guidewire.local/`.
- **Deps:** PyQt6-WebEngine, `screens.py` layout (the earlier `SessionScreen` lives in commit `f97a013`).
- **Test:** On 3 machines: the video plays; clicking step 5 seeks to within 1 s of `video_start_s`; no crash in a 30-minute session.

**V-2 Timestamps are never shown, and their reliability is not communicated** · Missing · **P1** [S][D]
- **Now:** Steps carry `video_start_s` / `video_end_s` from the video model (and from transcript cues for pasted transcripts). The evaluation measured timestamp accuracy on 6 videos only.
- **Should:** Show "02:14–02:31" on each step with a seek link. Show *no* time for steps whose times are missing or flagged, rather than an invented one.
- **Change:** Show stored times only. Add a per-step `timing_source` (model, captions, manual). Optionally cross-check model times against caption cue times when captions exist (the official API lists tracks; downloading caption text needs the unofficial endpoint, a terms risk already noted in GW-060).
- **Test:** For 6 labelled videos, the share of steps whose start lies inside the gold action span ± 5 s; target ≥ 85% before times are shown as clickable.

**V-3 No transcript segment per step** · Missing · **P2** [S]
- **Now:** Steps have `evidence` quotes on the model path; these are not shown in the session.
- **Should:** A "What the instructor says" fold-out per step, from evidence quotes or caption cues inside the step's span.

### D. Tutorial ingestion and instruction quality

**I-1 Steps are too coarse** · Quality · **P0** for the primary workflow [D]
- **Now:** The default prompt v7 gives a mean of 8.3 steps for 25–62 labelled actions; one-to-one recall is 24%; the Houdini APEX FK video has 39% of actions covered by step words. v8 and v9 (atomic steps, coverage) exist as opt-in prompts with mixed results.
- **Should:** One verifiable action per step, or a step with explicit numbered sub-actions each with its own check. Recall is measured on held-out videos labelled by someone other than the prompt author.
- **Why:** A learner cannot follow a step that hides five clicks, and verification cannot check it.
- **Change:** Keep v7 as the default until v8 or v9 wins on held-out data. Add a deterministic post-pass that splits `how_to` lines into sub-actions where the schema already supports groups (`group_id`). Grow the labelled set: a second labeller and ≥ 10 videos per app.
- **Test:** Held-out recall ≥ 80% (span-and-words) with step support ≥ 95%. Report per app.

**I-2 What is said, done, needed and checkable are not separated for the learner** · Arch (schema exists) · **P2** [S]
- **Now:** The schema has `evidence` (said), `visual_evidence` (shown), `actions` (to do) and `expected_state` (checkable), but the session shows goal, how-to and check only.
- **Should:** Show "Instructor shows but does not say" and "GuideWire can / cannot check this" explicitly.

**I-3 Review can only edit the goal text** · Missing · **P1** [S][V]
- **Now:** `StepEditor` offers `edit_goal`, `move`, `delete` and `add`. How-to lines, checks, expected state, timestamps and the application are fixed. Edited steps are marked reviewed in the data but not shown.
- **Should:** Edit every learner-visible field, preview how the step will look in a session, mark a step "wrong / unclear" with a reason (a feedback loop for I-1), and show "drafted automatically / reviewed by you".
- **Note:** The scope decision in `docs/later.md` ("decided not to show" the drafted/reviewed label) conflicts with the brief. **Flagged, not changed.**

**I-4 Video processing blocks without cancel, and its result can yank the learner** · UX/Bug · **P1** [S]
- **Now:** `NewTutorialScreen.create` runs 1–2 minutes with no cancel. On completion `created` is emitted and the main window opens the editor even if the learner has gone elsewhere.
- **Should:** A background job with progress, cancel, and a notification "Steps ready: Review". It never navigates on its own.

**I-5 Errors show Python exception names** · UX · **P1** [S]
- **Now:** Examples: "That did not work (TypeError: …)" and "could not be read right now (ReadTimeout)".
- **Should:** One plain sentence, a next action, and a "details" disclosure. The raw error goes to a log (see H-1).

**I-6 Incorrect terminology and outdated UI references are only partly caught** · Quality · **P2** [S][D]
- **Now:** Vocabulary checks against dumped app vocabularies (`knowledge/app_vocab/*.json`) flag unknown names. Blender targets are resolved against the 5.2.2 catalogue; Maya and Houdini are vocabulary only.
- **Should:** Every UI name in a step is either resolved against the installed version's catalogue or flagged "not found in your version".

### E. AI assistance

**A-1 The chat has no session or screen context** · Missing · **P1** [S] (see S-9)

**A-2 Intent handling is regex-heavy and brittle with real phrasing** · Quality · **P2** [S][D]
- **Now:** `chat_context.py` and `followup.py` route on patterns. The earlier held-out set was assistant-written.
- **Should:** Measured on real learner questions; an unknown intent falls back to the model with the tutorial and step as context, with a refusal when there is no grounding.
- **Test:** 100 real questions from pilot users, labelled for usefulness and correctness by two people.

**A-3 Answers do not list sources** · Missing · **P2** [D]
- **Should:** Every answer shows "From: this tutorial step 4 / Blender manual: Armatures › Bones (CC-BY-SA)", and says "I'm not sure" when nothing was retrieved. The licence question (GW-061) must be settled before distribution.

**A-4 No "mistake recovery" or "alternative method" reasoning grounded in state** · Missing · **P3** [S]
- **Should:** "I'm in Object Mode but the step says Edit Mode" is answered from the observed state. "I used Ctrl+R instead" is recognised as the same result when the expected state is met; the evaluator already judges by state, not by clicks.

### F. Accounts, data and reliability

**D-1 No password recovery, because accounts exist only on one computer** · Arch · **P0** [S]
- **Now:** Accounts live in a local SQLite file with no server and no verified email. A forgotten password makes all of that learner's data unreachable. A second computer starts from nothing, and a lost laptop loses all progress.
- **Should:** Accounts are hosted, with verified email, password reset, refresh tokens and sign-out everywhere.
- **Why:** None of these can be built without a server. This is the root cause of D-1, D-4 and H-2.
- **Change:** Move authentication to **Supabase Auth**, which the SRS already planned (SDS 3.1, 5.1, 5.6; SRS SI-13). See §2a for the full data architecture. Retire hand-rolled bcrypt for new accounts, and add a one-time "move my local data to my account" import for existing local profiles.
- **Deps:** `app/accounts.py`, `LoginScreen`, `ProfileScreen`, the gateway (H-2), and a hosted Supabase project (an operational responsibility).
- **Test:** Register ⇒ verification email; sign in on two computers ⇒ same tutorials; reset password by email; revoke a session ⇒ the other computer is signed out at its next request.
- **Decision recorded (22 Nov 2026):** a hosted database with a local cache, not local-only. This settles the scope question previously flagged here.

**D-2 The local database path depends on the working directory** · Bug · **P0** [S]
- **Now:** `DEFAULT_PATH = Path("local_data/guidewire.sqlite")`, relative to wherever the app was started.
- **Should:** The local cache lives at `%LOCALAPPDATA%\GuideWire\<user id>\cache.sqlite` (the probe already uses that folder), one file per signed-in account. Before the backend move is finished, an existing repository-relative database is moved there once.
- **Why it still matters:** Even with a hosted database, the local cache and anything not yet synced must not "disappear" when the app is launched from another folder.
- **Test:** Launch from two different directories ⇒ same account and data.

**D-3 No schema migrations** · Arch · **P1** [S]
- **Change:** A `schema_version` table and ordered migration functions; a backup before migrating.

**D-4 No staying signed in, and no token handling** · Missing · **P1** [D]
- **Change:** Store the Supabase **refresh token** in Windows Credential Manager through `keyring`, as SRS FR-002 designed; never in a file. Make "Remember me" opt-in. When a token expires or is revoked, return to sign-in *without* losing an open session: its progress waits in the local outbox (§2a) until the learner signs back in.
- **Test:** Restart ⇒ still signed in; revoke on the server ⇒ signed out on the next request, and no progress is lost.

**D-5 Login and registration UX** · UX · **P1** [V]
- **Change:** Separate "Sign in" and "Create account" views; confirm password; show password; inline validation; Enter submits from any field; caps-lock warning; focus on the first invalid field.

**H-1 No logging, crash handling or diagnostics** · Missing · **P0** for release [S]
- **Now:** 43 broad `except Exception` blocks in `app/`, most silent. There is no log file and no `sys.excepthook`.
- **Should:** A rotating log in `%LOCALAPPDATA%\GuideWire\logs` (no screen content, no keys); a crash dialog offering to open the log folder; "Copy diagnostics" in Settings.

**H-2 Keys on the learner's machine; gateway unused** · Arch/Security · **P0** for distribution [D][S]
- **Now:** `GEMINI_API_KEY` and `YOUTUBE_API_KEY` are read from `.env` by `app/pipeline.py`, `app/ask.py` and `app/discovery.py`.
- **Should:** The app calls the gateway with the learner's Supabase access token. The gateway verifies it (signature, expiry, audience) instead of reading `GATEWAY_TOKENS`, and takes the user id from the token for rate limits and the daily cost cap. Counters and the idempotency store move to Postgres (or Redis) so the gateway can run more than one worker. Provider keys exist only on the gateway host.
- **Deps:** D-1 (accounts must exist first); `gateway/app.py`; `ingestion/gateway_client.py`, which exists but is unused; `app/pipeline.py`, `app/ask.py` and `app/discovery.py` switch to the client.
- **Test:** A search of the shipped app's files finds no provider key. An expired token gets 401 and the app signs in again. Two gateway workers enforce one shared daily cap.

**H-3 Network and AI failures** · UX · **P1** [S]
- **Now:** Most failures return a sentence, which is good. Offline or no-key states are discovered only when an action fails.
- **Should:** A connection and "AI available" indicator. Offline mode is stated up front ("Find a tutorial needs the internet").

**H-4 Packaging** · Missing · **P0** for release [S]
- **Should:** A signed Windows installer (PyInstaller or Briefcase), per-user data folder, an uninstall that keeps or removes data on request, and the add-on bundled.

### G. UX and interface

**U-1 Unfinished surfaces in primary navigation** · UX · **P1** [V]
- **Now:** Progress is labelled "Work in progress", Learning Paths and Achievements are placeholders, and "Add demo tutorials" / "Import sample steps" are on Home.
- **Change:** Hide placeholders behind a developer flag; move demo and sample actions to Settings → Developer.

**U-2 Layout clipping at 1366×768** · Bug · **P1** [V]
- **Now:** In the session hero tile, the "How to do it" text is cut mid-sentence. The review screen title runs under the Back and Save buttons.
- **Change:** Make the step detail scrollable inside the tile, elide titles with a tooltip, and test at 1366×768 and 125% scaling.

**U-3 Inconsistent navigation affordances** · UX · **P2** [V]
- **Now:** "Back" is a red text link on Ask and a pill button elsewhere. The sidebar and in-page Back both exist.
- **Change:** One header component everywhere.

**U-4 Tutorial management** · Missing · **P1** [S]
- **Now:** There is no delete, rename, duplicate or search of saved tutorials (`db.delete_tutorial` exists but is unused).

**U-5 First-run onboarding** · Missing · **P1** [S]
- **Should:** First launch covers what GuideWire observes (consent, see M-1), connecting Blender, and choosing the application, then lands on "Find a tutorial".

**U-6 Accessibility and keyboard** · Cannot verify · **P2**
- **Should:** Tab order on every screen, accessible names on icon buttons, status conveyed by text plus icon (NFR-042), and contrast checked on the clay palette (light-on-orange text in hero tiles needs measuring).

### H. Discovery and progress

**R-1 Discovery is metadata-only and has no filters** · Quality · **P2** [S]
- **Now:** It is honest about this ("judged from title, channel and length").
- **Should:** Filters for application, version, length and level; de-duplicated results; "why recommended"; side-by-side comparison of two candidates; captions availability (already computable).

**R-2 Progress is counts only and is inflated by restarts** · Missing · **P2** [V]
- **Should:** A per-tutorial timeline; steps skipped or redone most; time per step. No mastery scores (consistent with the brief and the removal of pyBKT).

### I. Privacy and trust

**M-1 No disclosure or consent for screen observation** · Missing · **P0** for release [D]
- **Now:** Capture is limited to the application's window and stays on the machine [S], which is a strength nobody is told about.
- **Should:** A first-run screen stating what is captured (the application window only), how often (every 0.4–1.5 s while watching), that it never leaves the computer, and that the AI sees only the YouTube link and your questions. A visible watching indicator (G-4) and a single pause hotkey.

**M-2 Data export and delete** · Missing · **P2** [D] (deferred in `later.md`)

**M-3 Third-party caption endpoint (terms risk)** · Decision · **P2** [D]: keep it opt-in and dev-only, as today.

### J. Performance

**P-1 Unmeasured on lower-spec machines and in long sessions** · Missing (evidence) · **P2** [N]
- **Now:** The design is careful: change-driven looks, cache, below-normal priority, idle pacing.
- **Should:** A recorded 60-minute session: GuideWire CPU < 5% average, memory growth < 50 MB, look latency p95 < 300 ms, on a 4-core, 8 GB machine.

---

## 2a. Target data architecture: hosted database with a local cache (proposal, decided 22 Nov 2026)

This is a design proposal for review. Nothing here is built yet.

**Principle.** The server holds the truth about accounts and the learner's work. The computer keeps a working copy so a session never stops because the internet did. What GuideWire *sees on the screen* never leaves the computer.

### Where each kind of data lives

| Data | Home | Local copy | Notes |
|---|---|---|---|
| Account, email, password, sessions and tokens | Supabase Auth | Refresh token in Windows Credential Manager | Replaces `app/accounts.py` bcrypt |
| Profile and preferences (display name, theme, guidance on/off) | Postgres `profile` | Cached | |
| Tutorials and their steps | Postgres `tutorial`, `step` | Cached; works offline | Steps stay one JSON record per row (`shared/step_record.py`), as today |
| Session progress (cursor, paused, per-step status and who set it) | Postgres `session`, `session_step` | **Written locally first**, then synced | Must survive dropped connections and crashes |
| Chat conversations and messages | Postgres `conversation`, `chat_message` | Recent ones cached | Disclosed at first run: these leave the machine |
| Saved searches | Postgres `find_search` | Cached | |
| Discovery results cache, thumbnails | Local only | – | Shared and disposable; no reason to sync |
| Screen captures, OCR text, probe state, entry snapshots | **Local only, in memory** | – | Never stored, never sent (privacy promise M-1) |
| Gateway counters, rate limits, idempotency keys | Postgres (service role) or Redis | – | Lets the gateway run more than one worker |
| Provider keys (Gemini, YouTube) | Gateway host only | – | Never on the learner's computer |

### Tables (Postgres)

They mirror today's SQLite schema so the `Database` interface and screens barely change.

```sql
-- auth.users is Supabase's own table; everything else references it
create table profile (
  user_id      uuid primary key references auth.users on delete cascade,
  display_name text not null default '',
  preferences  jsonb not null default '{}',
  created_at   timestamptz not null default now()
);
create table tutorial (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users on delete cascade,
  title       text not null,
  app         text not null check (app in ('blender','maya','houdini')),
  source_type text not null default 'manual',
  source_url  text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz                       -- soft delete, so a sync can carry deletions
);
create table step (
  id          uuid primary key default gen_random_uuid(),
  tutorial_id uuid not null references tutorial on delete cascade,
  position    int  not null,
  record      jsonb not null,                   -- the shared Step record
  unique (tutorial_id, position) deferrable initially deferred   -- reordering in one transaction
);
create table session (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users on delete cascade,
  tutorial_id uuid not null references tutorial on delete cascade,
  state       text not null default 'not_started' check (state in ('not_started','active','finished','archived')),
  paused      boolean not null default false,  -- S-5: pause lives in the session, not the widget
  current_pos int,
  started_at  timestamptz, finished_at timestamptz,
  updated_at  timestamptz not null default now()
);
create table session_step (
  session_id uuid not null references session on delete cascade,
  step_id    uuid not null references step on delete cascade,
  status     text not null default 'pending' check (status in ('pending','done','skipped')),
  status_by  text check (status_by in ('user','observed')),
  updated_at timestamptz not null default now(),
  primary key (session_id, step_id)
);
-- conversation, chat_message, find_search: same columns as today, with user_id uuid and updated_at
```

**Ids are UUIDs, not auto-increment integers.** The computer creates rows while offline, so ids must never collide when the rows reach the server.

### Row-level security (each learner sees only their own rows)

Row-level security is enforced by the database, so a bug in a query cannot leak another learner's data. That is the fragility noted in the inventory today: several methods currently trust their caller.

```sql
alter table tutorial enable row level security;
create policy own_tutorials on tutorial for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table step enable row level security;
create policy own_steps on step for all
  using (exists (select 1 from tutorial t where t.id = tutorial_id and t.user_id = auth.uid()))
  with check (exists (select 1 from tutorial t where t.id = tutorial_id and t.user_id = auth.uid()));

-- session, conversation, find_search, profile: same pattern as tutorial
-- session_step, chat_message: same pattern as step, through their parent row
```

The desktop app uses only the public (anon) key plus the learner's own token. The service-role key exists only on the gateway host.

### Sync rules (kept deliberately simple)

1. **Write locally first.** Every change goes into the local cache and an **outbox** table in one SQLite transaction. The screen updates immediately.
2. **Push the outbox** in order whenever online, with retries and back-off. Each change carries a client-generated id, so a retry is never applied twice.
3. **Conflicts:**
   - *Session progress:* merged **per step** by the latest `updated_at`; the cursor follows the most recently active device.
   - *Tutorials and steps:* last write wins for the whole tutorial. Editing the same tutorial on two computers at once is rare, so the overwritten version is kept as a copy titled "(conflict copy)" instead of being silently lost.
   - *Deletions:* carried as `deleted_at`, and purged after 30 days.
4. **Pull** changes since the last sync on sign-in and every few minutes. A Supabase realtime subscription is optional, not needed for version 1.
5. **Offline.** Sessions, review and editing all work. Find, Ask with the AI, and turning a video into steps say "needs the internet" up front (H-3).

### Migration path (each step ships on its own)

| Step | What | Fixes | Risk |
|---|---|---|---|
| 0 | Local database moved to `%LOCALAPPDATA%`; schema version and migrations added | D-2, D-3 | Low |
| 1 | Supabase Auth for sign-in, register, reset and verify; refresh token in keyring; the gateway verifies tokens; the app uses the gateway for AI and YouTube | D-1, D-4, D-5, H-2 | Medium (new service) |
| 2 | User data tables in Postgres with RLS. `Database` gets a remote implementation behind the same methods; on first sign-in, "Move my local data to my account" uploads the old SQLite contents (with consent) | Multi-device, backups, isolation enforced by the database | Medium |
| 3 | Local cache plus outbox sync, so sessions continue offline | Resilience | Highest; can follow later if the deadline is tight (steps 1–2 alone are a sound product, with online-only sessions) |

### Costs and risks to accept

- **Internet needed to sign in.** The first sign-in needs a connection. After that, a cached token allows offline sessions only if step 3 is built.
- **Data leaves the machine.** Tutorial titles, steps and chat text are now stored on a server. The first-run disclosure (M-1) and the privacy note must say so, and that screen content still never leaves the computer.
- **Cost: the Free plan is enough for the project, and Pro is not needed.** Checked 22 Nov 2026: Supabase's pricing page confirms 2 active projects and pausing after a week of inactivity. Third-party summaries also list 500 MB database, 50,000 monthly active users, 1 GB file storage and 5 GB egress; re-check those on supabase.com/pricing. Pro (about $25 a month) adds no pausing, backups and 8 GB.
- **Free-plan catches to plan for:**
  - **Pausing:** the project pauses after a week with no traffic, and the app cannot sign anyone in until it is restored by hand. Restore it, or use it, before every demo and evaluation.
  - **No backups:** export the database regularly (`pg_dump`).
  - **Sign-in emails:** the built-in sender is rate-limited and meant for testing; configure a free SMTP provider before real users.
- **Free alternatives if a hosted service is not wanted:** self-hosted Supabase (open source, on a team computer or university server), or Postgres from another free host with sign-in built into the gateway. Both cost no money but more work and upkeep. The design above does not change.
- **Operations.** Key rotation and keeping the project alive become someone's job (the owner named in §10).
- **Tests.** `Database(":memory:")` stays as the offline test double. Add a small set of integration tests against a local Supabase (`supabase start`) for the RLS policies, including one that a second user's token reads 0 rows.

### Acceptance criteria (added to §5)

- With user B's token, every table returns 0 of user A's rows (automated test against the RLS policies).
- Sign in on a second computer ⇒ identical tutorials and session progress within 30 s.
- Kill the network mid-session, complete 5 steps, reconnect ⇒ all 5 statuses reach the server once, with no duplicates (step 3 only).
- No provider key, and no service-role key, anywhere in the installed application.

---

## 3. Deliverable 3: prioritised roadmap

### P0: Critical (wrong results, data loss, or cannot be shipped)

| # | Item | Why P0 | Incremental or architectural |
|---|---|---|---|
| 1 | S-1, S-2, S-3: no false completions (re-baseline on every step entry, key by session, apply the entry rule to all predicate kinds) | The product marks work done that was not done | Incremental (bridge + evaluator) |
| 2 | S-4: navigation never erases statuses | Progress becomes false | Incremental (engine) |
| 3 | G-1: honest capability per app (Maya and Houdini manual, said up front) | Current message is wrong and blocks nothing usefully | Incremental |
| 4 | D-2 + D-3: local database in `%LOCALAPPDATA%`, with migrations (§2a step 0) | Apparent total data loss; prerequisite for the backend move | Incremental |
| 5 | I-1: step granularity measured on held-out labels, with a split or sub-action pass | Learners cannot follow 5-action steps | Research + incremental |
| 6 | H-1: logging and crash handling | Failures are invisible to you and to users | Incremental |
| 7 | D-1 + D-4 + H-2: Supabase Auth, keyring token, gateway verifies tokens and holds the keys (§2a step 1) | A forgotten password loses everything; keys on learners' machines | **Architectural** (new hosted service; the gateway and client already exist) |
| 8 | User data in Postgres with RLS, plus one-time import of local data (§2a step 2) | Single-machine data with no backup; isolation enforced only in code | **Architectural**, behind the existing `Database` interface |
| 9 | H-4 + M-1: installer, capture and data disclosure | Release blockers: install and trust | Packaging is new; disclosure is incremental |
| 10 | G-7: Maya and Houdini verification, then highlighting | Two of the three advertised applications have no guidance | Verification is incremental (probes exist); highlighting is substantial per-application work |

Offline sync (§2a step 3) is **P1**. Steps 1–2 alone give a sound, online-only product.

### P1: Essential (a coherent, reliable product)

S-5 paused state in the engine and floating guide for every session · S-6 icons · S-7 one transition table with tests, undo of Done · S-8 continue rather than duplicate sessions · S-9 / A-1 in-session questions with step and screen context · G-2 real-world overlay matrix · G-3 add-on setup and connection status · G-4 watching indicator · V-1 embedded video (or per-step deep links as an interim) · V-2 show timestamps honestly · I-3 full step editing and the reviewed label (scope flag) · I-4 background processing with cancel · I-5 plain error messages · D-3 migrations · D-4 stay signed in · D-5 login UX · H-3 connection state · U-1 hide unfinished pages · U-2 layout clipping · U-4 tutorial management · U-5 onboarding.

These are P1 because each is either a visible inconsistency in the main loop or a basic expectation of desktop software whose absence makes the product feel unfinished. None of them corrupts data.

### P2: Important (usability, accuracy, quality)

S-10 session summary and reopen · S-11 show who completed a step · G-5 guide restore · V-3 transcript per step · I-2 said / done / checkable shown · I-6 version-aware terminology · A-2 real-question evaluation · A-3 sources on answers · U-3 consistent headers · U-6 accessibility · R-1 discovery filters and comparison · R-2 honest progress views · M-2 export and delete · M-3 caption terms · P-1 performance measurements.

### P3: Advanced (after the core is stable)

A-4 state-grounded recovery and alternative methods · version staleness warning with "this menu moved" substitution (FR-051–053) · a screenshot-question flow (`later.md` idea, needs an SRS change) · learning paths built from completed tutorials (no mastery claims) · G-6 delete the dead controller.

**Suggested order:**
1. Items 1, 2, 4 and 6: small and independent, about a week together.
2. Item 3 and the S-5 to S-8 session polish, as one PR.
3. Items 7 and 8, the backend. Its schema should include `session.paused` from the start, so S-5 does not need a second migration.
4. V-1 and V-2, the video.
5. Item 9, the release blockers.

I-1 needs labels and runs in parallel from day one.

---

## 4. Deliverable 4: end-to-end journey audit

| # | Stage | What happens today | Problems |
|---|---|---|---|
| 1 | Open GuideWire | `python -m app.ui.main_window` from the repository folder | No installer or shortcut; if started from another folder, an empty database (D-2); no first-run explanation (U-5, M-1) |
| 2 | Sign in | Combined form, local accounts only [V] | Name field shown at login; no recovery; sign in every launch; no "remember me"; no second device (D-1, D-4, D-5, §2a) |
| 3 | Discover | Find a tutorial: live YouTube search (needs a key) or local list; or ask the chat | No filters or comparison; offline or no-key discovered only on failure (R-1, H-3) |
| 4 | Select | "Make steps" pre-fills New tutorial; the learner still presses Create | One extra screen and click; app choice must match the video |
| 5 | Extract | Gemini watches the video, 1–2 min, ≤ 25 min videos | No cancel; can yank navigation; coarse steps; keys local (I-1, I-4, H-2) |
| 6 | Review | List + goal editing [V] | Most fields not editable; no reviewed/drafted label; title clipping (I-3, U-2) |
| 7 | Start session | Always a new session [S] | Duplicates; Maya and Houdini show misleading guidance (S-8, G-1) |
| 8 | Video + instructions | No video; timestamps hidden | The headline experience is missing (V-1, V-2) |
| 9 | Detection and verification | Blender: gate is sound; completions can be false | S-1, S-2, S-3; real accuracy unmeasured (G-2) |
| 10 | Pause / skip / retry / revisit | Pause works while watching; Previous re-completes on Resume; jump back wipes statuses | S-1, S-4, S-5, S-6, S-7 |
| 11 | Ask for help | Leaves the session; chat lacks step and screen context | S-9, A-1, A-3 |
| 12 | Complete | "Well done!" with no summary | S-10 |
| 13 | Progress saved | Statuses saved after every change (good); pause not saved; counts inflated | S-5, R-2 |
| 14 | Return later | History → "Continue where I left off" works [S]; Home "Start session" starts over silently | S-8 |

---

## 5. Deliverable 5: definition of a sellable product

GuideWire is release-ready when a new user on a clean Windows machine can install it, connect Blender, find a tutorial, follow it with video and on-screen help, and finish. GuideWire must never claim something happened that did not, and must never lose the user's work.

**Measurable acceptance criteria**

| Area | Criterion |
|---|---|
| Install | Clean Windows 10/11 machine to first session in ≤ 10 minutes without reading docs; installer and uninstaller; no `.env` or keys on the learner's machine |
| Accounts | Hosted sign-up with email verification, sign-in, sign-out, stay-signed-in and email reset all work; the same data on two computers within 30 s; data identical whichever way the app is launched; 0 rows of another user readable through the database's RLS (automated test) |
| False completion | **0** auto-completions without a state change caused after step entry, over a scripted suite of ≥ 200 navigation sequences (Previous, jump, restart, second tutorial, already-true results) plus 10 real Blender sessions |
| Navigation integrity | Navigation never changes any step status except the target step; property test over random command sequences passes |
| Pause | Identical paused/active state and icons (⏸ / ▶) on the main screen and floating guide within 100 ms; nothing is captured, highlighted or completed while paused; survives restart |
| Overlay precision | **0** highlights on a wrong element across the scaling, monitor and layout matrix (G-2); highlight coverage reported per condition; when uncertain, words only |
| Overlay latency | Highlight follows a window move within 250 ms; a new look within 500 ms of input (p95) |
| Step quality | Held-out, independently labelled set (≥ 10 videos per supported app): span-and-words recall ≥ 80%, step support ≥ 95%, timestamp start within ± 5 s for ≥ 85% of steps shown with a time |
| Video | Plays embedded (or deep-links reliably) on 3 different machines; clicking a step seeks within 1 s of its start; 0 crashes in 30 minutes |
| Help | ≥ 80% of 100 real in-session questions rated useful and correct by two reviewers; 0 answers that claim to have seen the screen when no state was read; every answer names its source or says it has none |
| Errors | No Python exception text in any user-facing message; every failure in §2 H has a message and a next action; every crash is written to a log |
| Performance | 60-minute session on 4-core / 8 GB: CPU < 5% average, memory growth < 50 MB |
| Trust | First-run disclosure of capture; a visible watching indicator; capture stays local (verified with a network monitor) |
| Scope honesty | Every application listed in the UI states what it supports (guided + verified / manual); no placeholder pages in navigation |

**Proposed transition table (for S-7)**

| From \ command | Done | Skip | Previous | Go to step k | Pause | Resume | Verified change seen |
|---|---|---|---|---|---|---|---|
| Active, step n | n → done, cursor → next pending | n → skipped, cursor → next pending | cursor → n−1 (status kept), re-baseline, pause | cursor → k (statuses kept), re-baseline | paused | – | n → done(observed), cursor → next pending |
| Paused, step n | as Active, then unpaused | as Active, then unpaused | as Active, stays paused | as Active, stays paused | – | active, re-baseline | ignored |
| Finished | – | – | reopen at last step | reopen at k | – | – | ignored |

---

## 6. Scope conflicts and decisions to flag

1. **Drafted / reviewed labels and confidence on steps.** The brief wants trust signals; `docs/later.md` (17 Nov) decided not to show them.
2. **Account model: decided 22 Nov 2026.** Use a hosted database (Supabase Auth + Postgres with row-level security) with a local cache, as the SRS/SDS planned. `docs/later.md` and the SRS/SDS comparison (`docs/srs_sds_vs_code_2026-11-17.md`, which proposed describing the shipped build as local-only) need updating to match. §2a describes the design.
3. **Embedded player.** It was removed from the SRS/SDS on 17 Nov, but the brief makes it central. It needs a decision and a WebEngine spike.
4. **Achievements and Learning Paths.** These risk the "artificial mastery" the brief rules out; proposed hidden until defined without scores.
5. **Maya and Houdini: decided 22 Nov 2026, in scope now.** `docs/later.md` lists them as "in progress" and the SRS/SDS comparison proposed calling them prototypes; both need updating. Until G-7 lands, product copy must not promise guidance in them.
6. **Automated control.** Nothing in the code clicks or types into the user's application, and this audit recommends keeping it that way. The add-on installer (G-3) writes files only, with consent.

## 7. What could not be verified here

- Screen guidance inside a real Blender, Maya or Houdini.
- DPI and multi-monitor behaviour.
- Video playback.
- Live Gemini and YouTube calls (no calls were made).
- Real-user comprehension.
- Performance on low-spec hardware.
- Accessibility with a screen reader.

## 8. Commands run

```
venv/Scripts/python.exe -m pytest -q -rs                      # result: see §9
python <scratchpad>/repro_session.py                          # S-1 (1c True), S-3 (2a True), S-4 (3b all pending)
python <scratchpad>/repro_leak.py                             # S-2: True with shared bridge, False after reset
QT_QPA_FONTDIR=C:/Windows/Fonts python <scratchpad>/shots.py  # offscreen render of 15 screens at 1366x768
```

## 9. Test suite

- **Targeted run:** `tests/test_app_vision_bridge.py`, `test_app_flow.py`, `test_app_accounts.py` and `test_app_session_engine.py`: **62 passed** in 18 s [V]. These pass while S-1 to S-4 exist: no test re-enters a step after Previous, reuses a bridge across sessions, or checks an already-true mode or tool result. `test_jump_back_makes_the_steps_from_there_pending_again` asserts the S-4 behaviour.
- **Full suite (`pytest -q -rs`): 1,578 passed, 2 failed, 1 error, 1 skipped, 2 deselected, in 24 min 23 s** [V]. It was slow, not hung.
  - **One failure is the environment:** `tests/test_verification.py::test_houdini_real_scene` (Houdini reports "No licenses could be found"). This test should *skip* when no licence is available, like the other real-application tests. Re-running that file alone gave 9 passed, 1 failed (the same test).
  - **The other failure and the error were not identified:** only the last lines of output were kept. Re-run with `pytest -q -rfE` to name them.
  - **24 minutes is too long for a pre-commit run.** The real-application tests (Blender, Houdini, Maya runs, up to 300 s each) should be behind a marker that is deselected by default, like the live API tests.

---

## 10. Who does what (revised twice, 22 Nov 2026: Houdini to Ayesha, Maya to Umaima)

The split follows the README's areas:
- **Ayesha:** tutorial understanding, step generation, AI, gateway (`/ingestion`, `/gateway`).
- **Umaima:** screen capture, UI detection, overlay (`/vision`).
- **Mehak:** app UI, **accounts**, session engine (`/app`).

**Changes in this revision:**
- **Maya and Houdini are done now, one person per application, end to end.** Ayesha owns **Houdini** (catalogue, step targets, probe, checking, highlighting). Umaima owns **Maya** (the same list). Blender stays with Umaima's existing vision code, with Ayesha's step targets.
- **Shared rules so the two do not drift apart (agree before either starts):**
  - **Probe protocol:** both applications use `vision/probes/probe_core.py`, with the same connection file and the same state keys.
  - **Target format:** one `TargetRef` extension for nodes, shelves and parameters, used by both.
  - **Confidence check:** both go through `vision/verify.py` unchanged; neither writes a looser rule for their own application.
  - **Same acceptance criteria:** steps complete only after the learner's own change (S-1 to S-3), and 0 wrong highlights across the G-2 matrix.
  - **Review across:** Umaima reviews Ayesha's Houdini vision code (she owns `/vision`); Ayesha reviews Umaima's Maya catalogue and step targets (the step format is hers).
- **The hosted database (Supabase) belongs entirely to Mehak,** because accounts and the database are her area. Ayesha's only link to it is reviewing the small gateway change that accepts Supabase sign-in tokens, because she wrote the gateway.
- **To balance the load,** Ayesha carries Houdini end to end, so logging goes to Umaima and the two small UI items (one header component, accessibility pass) go back to Mehak. Ayesha keeps the evaluator fix, finer steps and the gateway client.

Where the code was written by someone else, that person reviews the change. Git history shows Ayesha wrote `app/vision_bridge.py`, `app/step_state.py`, `app/ui/screen_guide.py`, `app/ui/player.py`, `app/ask.py`, `app/discovery.py` and the grounders.

### Day one, everyone: licences

Get Houdini Apprentice licensed and an Autodesk education licence for Maya on **every** team computer. Nobody can build or test Maya or Houdini guidance without them.

### Ayesha: steps, AI, gateway client, and Houdini end to end

| Order | Item | P | What | Reviewer / hand-off |
|---|---|---|---|---|
| 1 | S-3 | P0 | Apply "already true when the step began is not evidence" to every predicate kind in `ingestion/evaluator.py`; return "already done, confirm" instead of advancing | Umaima (co-wrote the evaluator); Mehak builds the confirm button |
| 2 | G-7 Houdini (checking) | P0 | Houdini catalogue (shelf tools, node types and parameters, menus) dumped from Houdini 22 like the Blender one; a Houdini step-target resolver like `ingestion/targets.py`; finish `vision/probes/houdini_probe.py` (nodes, connections, parameters, selection) so expected states can be checked; window lookup by program name | Umaima (vision, probe protocol) |
| 3 | G-7 Houdini (highlighting) | P0 → continuing | Houdini grounders behind the existing gate: main menus, the network editor's Tab menu, the parameter pane, shelf tools; words only when not confident | Umaima |
| 4 | I-1 | P0 | Finer steps: grow the labelled set (second labeller, ≥ 10 videos per app), compare v7/v8/v9 on held-out videos, sub-action pass | Labels need a second person |
| 5 | H-2 (app side) | P0 | `app/pipeline.py`, `app/ask.py` and `app/discovery.py` call the gateway through `ingestion/gateway_client.py`; no keys in the app | Mehak reviews |
| 6 | Tests | P1 | Real-application tests behind an opt-in marker; Houdini test skips without a licence; name the unidentified failure and error (§9) | – |
| 7 | S-9 / A-1 | P1 | Answers that know the current step, previous steps and the last observed state | Mehak builds the question box |
| 8 | V-1 spike, V-2 | P1 | Why Qt WebEngine crashes (other machines, out-of-process player, origin); fallback per-step `watch?v=…&t=Ns` links; trustworthy times only | Mehak places them in the session screen |
| 9 | I-5 (messages) | P1 | Plain error sentences from the pipeline, chat and discovery | Mehak for the screens |
| 10 | A-2, A-3, I-2, I-6, V-3, R-1, M-3 | P2 | Real-question evaluation; sources on answers; said / shown / checkable data; version-aware terms; transcript per step; discovery filters; caption endpoint stays opt-in | – |
| 11 | A-4 | P3 | Recovery answers grounded in observed state | – |

### Umaima: vision, logging, Maya end to end, installer

| Order | Item | P | What | Reviewer / hand-off |
|---|---|---|---|---|
| 1 | S-1, S-2 | P0 | Vision bridge: re-record a step's starting state whenever it becomes current, keyed by (session, step); reproduction scripts become regression tests | **Ayesha** (wrote the bridge); Mehak calls the "step began" hook |
| 2 | G-1 | P0 | Honest capability per application while Maya and Houdini are being built; no "Open Maya in front" when it is in front | Mehak shows it |
| 3 | G-7 Maya (checking) | P0 | Maya catalogue (menus, shelves, tools, node types, attributes) dumped from Maya 2027; a Maya step-target resolver; finish `vision/probes/maya_probe.py` (nodes, joints, attributes, constraints, selection); window lookup by program name; expected states the probe can check | Ayesha (step format, evaluator) |
| 4 | G-7 Maya (highlighting) | P0 → continuing | Maya grounders behind the existing gate: main menus, shelf tabs and buttons, Attribute Editor, Channel Box; words only when not confident | Ayesha (wrote the Blender grounders) |
| 5 | H-1 | P0 | Logging for the whole app: rotating log in `%LOCALAPPDATA%\GuideWire\logs`, crash dialog, "Copy diagnostics"; never log screen content or keys | Everyone replaces silent `except Exception` in their own area |
| 6 | Review Houdini | P0 | Review Ayesha's Houdini probe and grounders against the shared probe protocol and the gate | – |
| 7 | G-2 | P1 | Live test matrix for all three applications: scaling, two monitors, resize, full screen, custom layout | Ayesha runs the Houdini part |
| 8 | M-1 (facts) | P0 | Exactly what is captured, how often, where it goes; checked with a network monitor | Mehak builds the screen |
| 9 | G-3 + H-4 | P1 / P0 | Setup that detects Blender, Maya and Houdini and installs their add-on or probe (with consent); the Windows installer | Mehak for the setup screen |
| 10 | G-4 (state) | P1 | One "watching / paused / off" state for the whole app, plus a tray icon | Mehak draws it |
| 11 | P-1 | P2 | 60-minute performance measurement in each application | – |
| 12 | G-6 | P3 | Delete the unused `app/guidance.py` | Mehak |

### Mehak: app UI, session engine, accounts and the hosted database

| Order | Item | P | What | Reviewer / hand-off |
|---|---|---|---|---|
| 1 | S-4 | P0 | Navigation moves the cursor only and never changes other steps' statuses; update the test that asserts the old behaviour | Ayesha and Umaima agree |
| 2 | D-2, D-3 (§2a step 0) | P0 | Local database in `%LOCALAPPDATA%\GuideWire\<user>\`; schema version and migrations | – |
| 3 | S-7 + S-5 + S-6 | P1 | One transition table (§5), `paused` saved in the session, ⏸ / ▶ icons on both surfaces, floating guide in every session, "Undo" after Done | Umaima (floating guide) |
| 4 | §2a steps 1–2 + D-1, D-4, D-5 | P0 | **Supabase (Free plan):** create the project, sign-in / register / verify / reset in the app, refresh token in keyring, tables with row-level security, remote `Database` behind the same methods, "Move my local data to my account", and the gateway's token check. **Owns keeping the project alive** (pausing, exports, SMTP) | Ayesha reviews the gateway change only |
| 5 | S-8, U-4 | P1 | "Continue or start over"; delete and rename tutorials | – |
| 6 | U-1, U-2, U-3 | P1 / P2 | Hide placeholder pages and developer buttons; fix clipping at 1366×768; one header component | – |
| 7 | I-3, I-4 | P1 | Edit every step field, "drafted / reviewed" label (**scope flag**, §6); background video processing with cancel | Ayesha |
| 8 | S-9 (UI), V-1 / V-2 (UI) | P1 | Question box in the session and floating guide; video beside the steps with click-to-seek | Ayesha |
| 9 | M-1, U-5, H-3 | P0 / P1 | First-run screen, onboarding, connection and "AI available" indicator | Umaima (facts) |
| 10 | §2a step 3 | P1 | Local outbox and sync, so sessions work offline | Ayesha reviews |
| 11 | S-10, S-11, R-2, U-6, M-2 | P2 | Session summary and reopen; "checked by GuideWire" mark; honest progress; keyboard and screen-reader pass; export and delete of data | – |

### Timing

- **Week 1:**
  - Everyone: licences.
  - Ayesha: S-3, and start the Houdini catalogue dump and probe.
  - Umaima: S-1, S-2, G-1 and H-1, and start the Maya catalogue dump and probe.
  - Mehak: S-4, D-2, D-3, and create the Supabase project.
- **Agree before building:**
  - **The session rules (§5), before Mehak builds S-7.** They decide when Umaima's bridge re-records a step's starting state and when Ayesha's evaluator may complete a step.
  - **The probe protocol and target format,** before either Houdini or Maya work starts (the shared rules at the top of §10). It is the same `TargetRef` Blender uses, extended for nodes, shelves and parameters.
- **Biggest risk:** Ayesha's load. She carries Houdini end to end plus S-3, finer steps and the gateway client. If Houdini highlighting slips, ship Houdini checking first (useful on its own) and keep words-only guidance there until the gate is confident; do not pull Umaima off Maya.
- **Release:** Umaima's installer, Mehak's first-run screen and Supabase setup, and Ayesha's gateway client all have to land before anyone outside the team installs GuideWire.

