# Labelling guide: held-out tutorial references (GW-041)

**Why this exists.** Every evaluation set so far was written by the same author as the rules (or by the assistant), so a good score only shows the rules do what their author intended. These labels are the first measurement that does not depend on the author: a person watches a tutorial and writes down what the learner is told or shown to do. Recall (GW-043) can only be measured against labels like these.

**What you need.** The video (link in `eval_data/labels/ASSIGNMENTS.md`), a spreadsheet or text editor, and about 30–40 minutes per 10 minutes of video. Ten videos, 77 minutes in total: roughly 5 hours for the main annotator; the double-annotated three (16 minutes of video) take about 1.5 hours for the second person.

## The one rule that matters

**Label from the video. Do not run GuideWire on a tutorial before you have labelled it, and do not read the transcript files first.** Seeing the system's steps first makes you label what it found. Watch, then write. (The transcripts in `local_data/labelling/` exist for the evaluation, not for you; read them only if captions help you place a time.)

## What to write down

One row per **action**: something the learner is told to do or is shown doing in Blender. Include actions that are only done on screen and never mentioned.

| Column | Meaning |
|---|---|
| `start` | when the action **begins** (`m:ss`, `h:mm:ss` or seconds). For a spoken instruction, when it is said; for a shown-only action, when it happens |
| `end` | when it ends (optional) |
| `action` | what the learner does, in your own words, one action per row ("Press Tab to enter Edit Mode") |
| `evidence` | **said** = only mentioned in speech; **shown** = only visible on screen (a key overlay, a click, a menu); **both** = said *and* shown |
| `importance` | **core** = the tutorial's result depends on it; **optional** = a tip, an alternative, a shortcut mentioned in passing |
| `keys_or_menu` | the key or menu path if there is one: `Tab`, `Shift + A`, `Add > Mesh > Cube` (optional) |
| `notes` | anything the next reader needs, for example "the instructor corrects himself" |

### Decisions

- **One action per row.** "Press Tab, select a vertex, press G" is three rows.
- **Repeats count.** Pressing Ctrl+Z three separate times at different moments is three rows; holding it down is one.
- **Explanations are not actions.** "Edit Mode lets you change the shape" is not a row. "Press Tab to get into Edit Mode" is.
- **Do not label what you assume.** If the instructor says "now smooth it" and you cannot see how, write the row and say so in `notes`; do not invent a menu path.
- **Things not to do** ("don't press Tab here") are not actions. Alternatives ("you could also use the menu") are **optional** rows.
- **Time accuracy.** Within about 3 seconds is fine; the evaluation allows 5.
- **Different Blender version or interface** from yours: label what the video shows.
- **Unsure whether something counts?** Include it, mark it `optional`, explain in `notes`. Do not agonise: the second annotator exists to measure how much people differ.

## Check as you go

```bash
python -m ingestion.eval.labels eval_data/labels/<video id>.<name>.csv
```

It reports problems with row numbers (unreadable time, missing evidence type, a time past the end of the video) and prints a count when the sheet is valid. It never edits your file.

## The second annotator

Three videos are marked for two people (`<id>.second.csv`). The second person labels **independently** and does not look at the first sheet. Rename the file to their own name (for example `aMGzPiOAqTk.umaima.csv`) and put the name in `annotators` in `eval_data/labels/manifest.json`. The evaluation reports how much the two sheets agree; that agreement is the ceiling for any score a system can meaningfully claim.

## When labels exist

```bash
python -m ingestion.eval.heldout            # pooled and per-video recall, precision, funnel, what is missed and why, annotator agreement
```

Nothing is tuned from the results of this command until a separate set of videos is labelled for final reporting (the same rule as for the question sets: a set used to fix the rules is not an independent test).

## Rules of use

The transcripts are YouTube-derived and stay in `local_data/` (git-ignored); only your sheets (our own words and times) go into the repository. Do not paste a video's captions into a sheet.
