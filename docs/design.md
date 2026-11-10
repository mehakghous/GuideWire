# Design rules

GuideWire is used next to **Blender, Maya and Houdini**, so its look is chosen to sit beside all three without being mistaken for any of them.

## Layout: bento
Every screen is a grid of rounded tiles of different sizes on a soft canvas (`app/ui/bento.py`: `Tile`, `ActionTile`, `header`, `page_grid`). A screen only arranges widgets in tiles; its logic lives elsewhere. Tile variants: plain, `soft`, `mint`, `amber`, `slate`, `accent` (a solid block, used sparingly) and `hero` (calm tinted fill with an accent outline, for the one thing the learner is looking at, such as the current step).

## Colour
| Role | Light | Dark | Why |
|---|---|---|---|
| Signature accent: **iris** (violet) | `#5b47e8` | `#9684ff` | None of the three applications uses violet. Blender and Houdini use orange; Maya highlights the active object in green and has a blue UI. |
| On-screen highlight | `#b388ff` | `#b388ff` | The same iris family, brighter so it stands out on a grey application window. One colour always means "GuideWire". (`HIGHLIGHT_RGB`, shared by `app/ui/style.py` and `vision/overlay.py`.) |
| Neutrals | cool light greys | graphite greys (`#1b1b1b` canvas, `#272727` tile) | Like the applications' own windows, so the app feels at home beside them. |
| Status colours | green `ok`, amber `warn`, grey `muted` | same, lighter | Only as small labels: Checkable, Partly checkable, You confirm. Never the main colour. |

Rules that follow from this:
1. **Do not use orange, yellow or green as the main colour.** They are the applications' own colours, and yellow or orange would blur with the highlight.
2. Text on the accent is **white in light mode and near-black in dark mode** (`accent_text`); white on the dark-mode accent would be too faint.
3. Colours chosen in code must come from `current_palette()`, never a fixed hex value, or they break in the other theme.

## Themes
Light and dark live in `app/ui/style.py` (`PALETTES`). The Profile "Theme" setting switches them; logging out returns to light.

## Readability is tested
`tests/test_app_bento.py` checks the contrast of every text and background pair in both themes (7:1 for main text, 4.5:1 for muted text, button text and status colours), that the accent stays clear of the applications' colours, and that the highlight is visible on grey windows. Change a colour, run the tests, and they say if it became unreadable.
