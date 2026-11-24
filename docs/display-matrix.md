# Display matrix (audit G-2), Blender 5.2

Measured with `scripts/vision_live_suite.py` on a real Blender window. Ground truth does not come from the code under test: Blender draws the active tool's cell in blue, so its real position is known. Run on 2026-11-23 on one Intel UHD 620 laptop, a single 1920x1080 display at Windows scaling 150%, Blender 5.2.

| Condition | Passed | Failed | Wrong guidance | Not found (coverage) |
|---|---|---|---|---|
| small window 1000x600 | 57 | 6 | 0 | 5 |
| wide window 1840x960 | 41 | 13 | 0 | 11 |
| moved window (300,120) | 50 | 8 | 1 | 6 |
| maximized | 60 | 2 | 0 | 1 |
| full screen (-W) | 48 | 8 | 0 | 5 |
| borderless 1600x900 (-w) | 58 | 5 | 0 | 3 |
| Resolution Scale 1.0 | 60 | 2 | 0 | 1 |
| Resolution Scale 1.25 | 57 | 3 | 0 | 2 |
| Resolution Scale 1.5 | 52 | 6 | 2 | 2 |
| Resolution Scale 2.0 | 56 | 3 | 0 | 2 |

Columns: *Wrong guidance* = the grounder said the tool was scrolled out of the toolbar while its cell was visible (it points at the toolbar region, not at another tool). *Not found* = the grounder said it could not locate the target and showed no rectangle, or the header text was not read. **No run pointed a rectangle at the wrong tool** (no `visible` result that missed the blue cell).

## What this does and does not show
- Acceptance "0 wrong highlights": met for rectangles on tools in this matrix, **not met for guidance**: 3 runs said "scroll the toolbar" for a tool that was in view (moved window 1, Resolution Scale 1.5 twice). They all happen when the toolbar is scrolled to its bottom and the visible cells do not match the tool list; open item.
- Coverage is not 100%: the first scenario of most runs ("Loop Cut, toolbar at the top") is often answered "unknown" because the toolbar has not stopped moving yet (the app's settle rule), and header words (the mode dropdown, Add) are sometimes not read. A person would see the highlight half a second later; the suite judges the first look.
- One run (small window) shows Loop Cut with confidence 0.5, which the gate refuses to show. Safe, but a gap.
- Run-to-run variation is real: the same layout (Resolution Scale 1.0) gave 60/62 here and passed 64/64 in an earlier clean run. Treat one run per condition as indicative.
- Earlier runs on this machine were invalid because the PC had locked (the capture was the lock screen). The suite should refuse to run when it cannot see Blender in front; not done yet.

## Not covered
- Real Windows scaling at 100% and 125% (needs a system setting change, left to the person running the test): Blender's own Resolution Scale stands in for it.
- A second monitor, a non-English UI, other Blender versions and themes, and a custom layout (workspaces other than Layout). Maya and Houdini: not run.

## Reproduce
`python scripts/vision_live_suite.py --size 1000x600`, `--display maximized|fullscreen|borderless`, `--pos 300,120`, `--ui-scale 1.5`. Keep the PC unlocked and nothing over Blender.
