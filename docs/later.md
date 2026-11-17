# Later: things decided to leave for now

Kept so they can be picked up again. Each says what it is, why it is not done now, and where it is described. Last updated 17 Nov 2026.

## Left out on purpose for now (decided 17 Nov 2026)

| Item | Why it is waiting | Where it is described |
|---|---|---|
| Consent notice at registration (screen capture and sharing), recorded with version, learner and time | Not needed for the phase 1 build. | SRS FR-001, NFR-029; SDS Section 5.5.1 Sign in and register |
| Confirmation prompt (uncertain element or action, step mismatch with two readings, recovery to the last good state, confirm a substituted element) | Not needed now. Today, when guidance is unsure it draws no box and says what is blocking it. | SRS FR-048 to FR-050, FR-053, NFR-011, NFR-015; SDS SD-10, Figure 38 |
| Profile preferences: target applications, level, warnings, prompts, showing confidence | Skipped for now. | SRS FR-004, FR-005 |
| Export and delete a learner's data | Skipped for now. | SRS NFR-034; SDS Profile screen |
| "Drafted automatically" / "reviewed" label and the confidence value on each step in the review screen | Decided not to show them. The editor already marks edited steps as reviewed in the data. | SRS FR-028, NFR-014 |

## Planned (not built yet; stays in the documents as planned)

| Item | Note |
|---|---|
| Managed backend (cloud database with row-level security, backend sign-in) | Phase 1 uses a local SQLite file behind the same repository idea. The backend comes later. |
| Token kept in the Windows credential store (stay signed in) | Today the learner signs in each time. |
| Staleness warning before a session (tutorial version against installed version) | Both versions are available; nothing compares them yet. |
| Mastery estimate by knowledge tracing, and the list of practised operations on the dashboard | Progress page shows counts only. |
| Automatic replacement of a moved or renamed interface element | The grounders report not found, hidden or scrolled out, but do not look for an equivalent. |
| Connect the desktop app to the AI Gateway (keys off the learner's machine) | The gateway and a client exist; the app calls the providers directly with local keys today. |
| Maya and Houdini guidance (interface catalogue, live checks of the highlight) | In progress. Blender is the checked application. |
| Documentation references listed with every answer; question box answers inside the session | Answers are given in Ask GuideWire. |
| Keyboard access to every action, status shown by icon and word everywhere | Not yet checked screen by screen. |
| Learning Paths, Achievements and the charts of the Progress page | Placeholder pages marked Work in progress. |

## Put back for now, to do again (18 Nov 2026)

| Item | Note |
|---|---|
| The new session screen: tutorial video on the left with Replay, Pause and Skip step, the steps list with a status word on each step, a question box, and the current step below | Built and tested, then put back to the earlier session screen because it did not work well enough yet. The code is in git history (commit f97a013, `SessionScreen` in app/ui/screens.py) and its tests were removed. Redo it once the video works. |
| The embedded YouTube player | Built (app/ui/player.py) but never seen playing: Qt WebEngine closes the whole program when it shows a web view on the development computer, with Qt 6.11 and 6.12 and every Chromium flag tried. To do: find out why (graphics driver, Windows setting, or a different Qt build), try another computer, and check that YouTube allows playback inside the app (the page claims the address https://guidewire.local/). |
| Pin the Qt and WebEngine versions in requirements.txt | They are pinned to 6.11 for the player; revisit if the player is dropped. |
| Find a tutorial: goals that are not rigging now search YouTube when the small local list has no match, instead of saying nothing matches | Done 18 Nov 2026; check the wording once the live search is tried with a real key. |

## Ideas

| Idea | Note |
|---|---|
| A screenshot flow: the learner shares a screenshot, GuideWire finds the element or the problem in it, and the result is compared with the current live-screen guidance | Would be a new requirement (new ID, new version of the SRS, supervisor sign-off) and a new gateway operation. |
| A general interface understanding for any Blender feature (find any element, navigate through hidden menus, panels and editors, refuse to guess) | Brief written on 17 Nov 2026; start by inspecting the current mapping and proposing the design before building. |
| Per-step screenshots in the SDS GUI section after every UI change | Figures 32 to 40. |

## Removed from scope (17 Nov 2026)

| Item | Note |
|---|---|
| Combining several tutorials into one workflow (F10, UC-LRN-12, FR-031 to FR-033, SD-06) | Removed from the SRS and SDS. The IDs are retired and not reused. |
