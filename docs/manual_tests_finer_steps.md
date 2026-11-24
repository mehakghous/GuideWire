# Finer steps: what changed, how it was measured, manual tests (23 Nov 2026)

## Why

Before 22 Nov the app extracted videos with prompt v10 (Blender and Maya `v10-preds`, Houdini `v10-hou`): about 18 small steps per tutorial. From 22 Nov it uses v12 (Houdini v13), whose steps are bigger (about 12 per tutorial) but whose wording is more accurate. The aim here is the earlier division with the current wording.

The earlier division cannot be had by asking for it again without changing the wording, so it is made from the current steps: each how-to line becomes its own step, unchanged.

## What changed

A step from a video carries 1 to 3 how-to lines. Now they are separate steps (`ingestion/split.py`, called from `app/pipeline.py`). **No words are new.**

| Part of the original step | Where it goes |
|---|---|
| Goal | The display group label of its parts (cut at 80 characters if longer) |
| How-to lines | One per part; a part's heading is its first line, word for word |
| Why, Watch out, alternatives, version notes, start state | The first part |
| Result, check, expected state (what GuideWire verifies) | The last part |
| Actions | Shared out by order and by the words each line names, never backwards; text typed into a search box stays with the key press before it |
| Times | The original range on every part. No per-line time exists and none is invented |
| `depends_on` | Follows the original step's last part. Ids and orders are renumbered |

**A part must have something the guide can point at.** The first version made every line a step and lost highlights: the parts that were a bare key press, a drag, or a click in the 3D view had nothing to highlight. A part with nothing findable is now joined to the part before it (or after it, at the start of a step), as extra how-to lines. "Findable" is decided by the same resolver the session uses (Blender and Houdini: a tool, menu, mode, property, node, parameter or pane; a key press or a viewport click is not). Maya has no screen guidance yet, so any action counts there. A step with fewer than two parts is left as it is. No model call.

The model is no longer asked to group the steps afterwards when the split has already given them groups. Turn the split off with `video_steps(..., split=False)`.

**Small guide:** the how-to lines ("Details") now start open, because they are easier to follow than the heading. A step that is one line is not shown twice (as heading and as detail). Folding the details is remembered while you stay in the session.

## How it was measured (saved runs, 6 tutorials, 3 repeats, labels by hand)

Mean steps per tutorial:

| | v10 (before 22 Nov) | v12 / v13 as extracted | v12 / v13 split (now) |
|---|---|---|---|
| Blender | 19.8 | 18.2 | **22.8** |
| Maya | 17.5 | 9.7 | **18.2** |
| Houdini | 15.7 | 11.5 (v13) | **20.7** |

Steps with something for the guide to find, after the resolver (the measure that went wrong the first time):

| | v10 | v12 / v13 as extracted | split (now) |
|---|---|---|---|
| Blender | 76% | 85% | **88%** |
| Houdini | 100% | 97% | **99%** |
| Maya | 55% | 73% | 53% (no screen guidance exists for Maya, so it does not show) |

Accuracy against the labels (earlier score; the group label counted as part of each step's text, because the learner sees both):

| | Words found, before → after | Steps that match a labelled action, before → after |
|---|---|---|
| Blender | 91% → 91% | 97% → 98% |
| Maya | 79% → 74% | 99% → 94% |
| Houdini (v13) | 64% → 62% | 93% → 77% |

**Reading.**
- The division is now at or a little finer than v10 for Blender and Houdini, and level with it for Maya.
- Highlightable steps are no lower than before the split in Blender and Houdini.
- Houdini's "matching" falls because many parts are preparation ("Press Tab, place the node") that no labelled action names. I have not checked each of them against the video.
- Only the saved extractions were measured. Nothing was tried in a real Blender, Maya or Houdini session.
- The mapping of actions to lines is a heuristic. It was read by hand on two runs. A typed value can land one part early or late.

## Manual tests

Test database: `python scripts/seed_finer_steps_test.py`, then `$env:GUIDEWIRE_DB = "local_data/finer_steps_test.sqlite"; python -m app.ui.main_window`. Login: `local_data/finer_steps_test_login.txt`. Each tutorial exists as "(before)" and "(finer steps)".

1. **Finer steps appear.** Open "Blender armature (finer steps)". Expected: 20 steps instead of 15. Select one in the review screen: "Part of: <original goal> (step 2 of 3 in this group)".
2. **No new words.** Compare three step headings with their "How to do it" lines. Expected: the heading is the first line, word for word.
3. **Why shows once.** In a group, "Why" is on the first step only; "How you can tell it worked" on the last only.
4. **Guidance.** Start a session with Blender open. Expected: nearly every part highlights something (a menu, tool, mode, field); key-press-only steps are said in words. Write down any step that highlights the wrong thing, or that you think should have highlighted and did not, with its number.
5. **Small guide.** Expected: the "Details" lines are open under the heading; a step that is a single line does not repeat itself; if you fold Details, it stays folded when the hint changes.
6. **Completion.** Only the last part of a group completes by itself; the earlier parts finish with Done.
7. **Compare.** Open the "(before)" copy of the same tutorial and compare how easy it is to follow.
8. **Houdini and Maya.** Open the finer Houdini and Maya tutorials. Expected: Houdini steps highlight nodes and parameters; Maya shows words only.

## Tests

`tests/test_split.py` (12 tests) covers: lines word for word, untouched short steps, why and notes first, check and expected state last, `verifiable` recomputed, times kept, actions in order and kept once, `depends_on` and renumbering, long labels, round trip, a line with no action joins the one before, a step with no action stays whole, and a key-press part in Blender joins its neighbour. `tests/test_app_flow.py` has the pipeline test. `tests/test_app_vision_ui.py` has the small-guide test.
