# Design rules

GuideWire is used next to **Blender, Maya and Houdini**. Its look is **claymorphism**: soft, puffy shapes that look moulded from clay. The mockup is `docs/design/option-8-clay/demo.html` (other explored directions are in `docs/design/option-*`).

## What makes it clay
- **Slabs, not boxes.** Every tile is a rounded slab (28px corners) with a soft gradient, a light rim and a soft warm shadow to the bottom right.
- **Pills.** Buttons, list rows and the navigation are pill shaped. A button squashes when pressed.
- **Clay balls.** Icons are round, glossy balls with a simple white symbol (`ClayBall`, `IconTile` in `app/ui/bento.py`).
- **Pressed in, raised up.** Inputs and the progress groove look pressed into the clay; everything clickable looks raised.
- **One hero per screen.** The amber `HeroTile` slab holds the one thing the learner looks at (the next tutorial on Home, the current step in a Session). Soft balls float in it, and a Session shows the step number as a huge faint watermark.
- **Motion, kept calm.** Shadows grow when you hover (`Lift`), screens ease in, and the floor (`app/ui/backdrop.py`) has a few big soft balls drifting very slowly. Nothing moves in a way that could hide a step.

## Where it lives
| What | Where |
|---|---|
| Palette and style sheet | `app/ui/style.py` (`PALETTES`, `build_style`) |
| Tiles, hero, icon balls, soft shadow, hover lift | `app/ui/bento.py` |
| Navigation panel | `app/ui/sidebar.py` |
| Floor with drifting balls | `app/ui/backdrop.py` |

A style sheet cannot draw soft outer shadows, animate, or paint shapes, so those parts are code. Colours chosen in code must come from `current_palette()`, never a fixed hex value, or they break in the other theme.

## Colour
| Role | Light | Dark |
|---|---|---|
| Canvas / tile | `#efe6dc` / `#f7efe6` (warm cream) | `#2a211c` / `#3a2e27` (warm brown) |
| Main action: vermilion | `#b8431a` (gradient from `#d95a22`) | `#ff9a62` |
| Hero slab: amber | `#f5a23c` | `#e8962c` |
| Teal (secondary tiles, companion card, progress) | `#3fc0dc` | same |
| Status labels | green `ok`, amber `warn`, grey `muted` | lighter versions |

Text is dark brown (`#4a3a33`) on the cream and on the amber slab (`hero_text`); text on the vermilion button is white in light mode and dark brown in dark mode (`accent_text`).

### The highlight drawn over the 3D application
The app itself uses warm clay colours, but the ring drawn over Blender, Maya or Houdini is an **orchid pink** (`HIGHLIGHT_RGB`, shared by `app/ui/style.py` and `vision/overlay.py`). Blender and Houdini select in orange and Maya in green, so an orange or green highlight could be mistaken for the application's own. A test keeps the highlight at least 25 degrees of hue from orange, yellow, green and blue and visible on grey application windows.

## Themes
Light and dark live in `PALETTES`. The Settings screen's Theme choice switches them (soft shadows are recoloured too); logging out returns to light.

## Readability is tested
`tests/test_app_bento.py` checks the contrast of every text and background pair in both themes (7:1 for main text, 4.5:1 for muted text, button text, labels and the whole amber slab gradient). Change a colour, run the tests, and they say if it became unreadable.
