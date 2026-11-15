# Design rules

GuideWire is used next to **Blender, Maya and Houdini**, so its look is chosen to sit beside all three without being mistaken for any of them.

## Layout: bento
Every screen is a grid of rounded tiles of different sizes on a soft canvas (`app/ui/bento.py`: `Tile`, `ActionTile`, `header`, `page_grid`). A screen only arranges widgets in tiles; its logic lives elsewhere. Tile variants: plain, `soft`, `mint`, `amber`, `slate`, `accent` (a solid block, used sparingly) and `hero` (calm tinted fill with an accent outline, for the one thing the learner is looking at, such as the current step).

## Colour: plum and olive
Taken from the mockups in `docs/design` (branch `design/ui-options`, option 1: Alabaster Gleam, Plum Wine and Olive Drab).
| Role | Light | Dark | Use |
|---|---|---|---|
| Paper (canvas) / tile | `#f3efe4` / `#faf8f2` | `#2a171f` / `#3b232d` | Warm alabaster in light, deep wine in dark |
| Plum accent | `#5a3a47` | `#d3a9ba` | Main buttons, the current step, selection |
| Olive | `#5f6334` (tile `#dcdfb8`) | `#b9be78` (tile `#3b3d1e`) | Status "Checkable", secondary tiles, sidebar dot |
| Sidebar | `#3b232d` | `#1f0f15` | The navigation panel on the left of every screen |
| On-screen highlight | `#ec8cc4` | same | A bright orchid from the plum family, so it reads on a grey application window (`HIGHLIGHT_RGB`, shared with `vision/overlay.py`) |

Rules:
1. Orange (Blender, Houdini), Maya green and blue are the applications' own colours: the accent and the highlight stay at least 25 degrees of hue away from them (tested).
2. Text on the accent uses `accent_text` (cream in light, near-black in dark).
3. Colours chosen in code come from `current_palette()`, never a fixed hex value.

## Navigation
`app/ui/sidebar.py`: a plum panel (Home, Find a Tutorial, Ask GuideWire, New Tutorial, History, Settings, a Companion status card, the signed-in name and Log Out). Shown on every screen except sign-in.

## Themes
Light and dark live in `app/ui/style.py` (`PALETTES`). The Profile "Theme" setting switches them; logging out returns to light.

## Readability is tested
`tests/test_app_bento.py` checks the contrast of every text and background pair in both themes (7:1 for main text, 4.5:1 for muted text, button text and status colours), that the accent stays clear of the applications' colours, and that the highlight is visible on grey windows. Change a colour, run the tests, and they say if it became unreadable.
