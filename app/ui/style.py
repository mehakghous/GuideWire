"""The look of the whole app: a bento grid. Content sits in rounded tiles of different sizes on a soft canvas; one signature colour marks the main action.

The palette is chosen for a tool used NEXT TO Blender, Maya and Houdini (see docs/design.md):
  * the signature colour is IRIS (violet, hue ~250). None of the three applications uses it: Blender and Houdini use orange, Maya highlights the
    active object in green and has a blue UI. The on-screen highlight (vision/overlay.py) uses the same iris, so that colour always means "GuideWire".
  * the neutrals are graphite greys, like the applications' own windows, so the app feels at home beside them;
  * green, amber and grey appear only as small status colours (checkable / partly checked / you confirm), never as the main colour.

Plain Qt style sheets, nothing to install. `build_style(theme)` returns the sheet for "light" or "dark" (the Profile screen's Theme setting);
`STYLE` is the light sheet. Tiles are `QFrame#tile` with an optional `variant` property (accent, hero, soft, mint, amber, slate); see app/ui/bento.py.
tests/test_app_bento.py checks the contrast of every text and background pair, so a palette edit cannot make the app unreadable.
"""
from __future__ import annotations

THEMES = ("light", "dark")

PALETTES = {
    "light": dict(canvas="#edeef2", tile="#ffffff", border="#dfe2e9", text="#1b1e27", muted="#5f6675",
                  accent="#5b47e8", accent_hover="#4a37cf", accent_soft="#ece9fd", accent_text="#ffffff", accent_hint="rgba(255, 255, 255, 205)",
                  mint="#e3f5ea", amber="#fdf1dc", slate="#e8ebf2", ok="#17794f", warn="#9a5b00",
                  danger="#b3261e", danger_soft="#fdecea", field="#f4f5f9", field_border="#d5d9e3", selected="#e7e3fd",
                  disabled="#a0a7b6", disabled_bg="#eef0f5"),
    "dark": dict(canvas="#1b1b1b", tile="#272727", border="#3a3a3a", text="#f2f2f2", muted="#a0a0a0",
                 accent="#9684ff", accent_hover="#aa9bff", accent_soft="#2a2749", accent_text="#14121f", accent_hint="rgba(20, 18, 31, 200)",
                 mint="#1f3a2e", amber="#3d3322", slate="#303136", ok="#4fd1a0", warn="#f2b84b",
                 danger="#ff8a7a", danger_soft="#3a2220", field="#202020", field_border="#444444", selected="#322e58",
                 disabled="#6b6b6b", disabled_bg="#222222"),
}

# The on-screen highlight over the application window (vision/overlay.py reads these). A brighter iris than the accent so it stands out on a grey window.
HIGHLIGHT_RGB = (179, 136, 255)

_TEMPLATE = """
* { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; color: @text@; }
QMainWindow, QStackedWidget, QWidget#page { background: @canvas@; }
QLabel { background: transparent; }

/* ---- tiles: the bento boxes */
QFrame#tile { background: @tile@; border: 1px solid @border@; border-radius: 20px; }
QFrame#tile[variant="soft"] { background: @accent_soft@; border-color: @accent_soft@; }
QFrame#tile[variant="mint"] { background: @mint@; border-color: @mint@; }
QFrame#tile[variant="amber"] { background: @amber@; border-color: @amber@; }
QFrame#tile[variant="slate"] { background: @slate@; border-color: @slate@; }
QFrame#tile[variant="accent"] { background: @accent@; border-color: @accent@; }
QFrame#tile[variant="hero"] { background: @accent_soft@; border: 2px solid @accent@; }
QFrame#tile[variant="accent"] QLabel { color: @accent_text@; }
QFrame#tile[variant="accent"] QLabel#tileHint { color: @accent_hint@; }
QLabel#tileTitle { font-size: 12.5pt; font-weight: 600; }
QLabel#tileHint, QLabel#hint { color: @muted@; font-size: 9.5pt; }
QLabel#big { font-size: 26pt; font-weight: 700; }
QLabel#pageTitle { font-size: 17pt; font-weight: 700; }
QLabel#brand { font-size: 28pt; font-weight: 700; }
QLabel#empty { color: @muted@; font-size: 10.5pt; }
QLabel#error { color: @danger@; }

/* ---- buttons */
QPushButton { background: @field@; border: 1px solid @field_border@; border-radius: 12px; padding: 8px 16px; }
QPushButton:hover { background: @accent_soft@; border-color: @accent@; }
QPushButton:disabled { color: @disabled@; background: @disabled_bg@; border-color: @border@; }
QPushButton#primary { background: @accent@; border-color: @accent@; color: @accent_text@; font-weight: 600; }
QPushButton#primary:hover { background: @accent_hover@; border-color: @accent_hover@; }
QPushButton#primary:disabled { background: @disabled_bg@; color: @disabled@; border-color: @border@; }
QPushButton#danger { color: @danger@; }
QPushButton#danger:hover { background: @danger_soft@; border-color: @danger@; }

/* an action tile is a whole tile that is also a button (its two labels sit on top; the button's own text is hidden) */
QPushButton#action { background: @tile@; border: 1px solid @border@; border-radius: 20px; padding: 0; text-align: left; color: transparent; }
QPushButton#action:hover { background: @accent_soft@; border-color: @accent@; }
QPushButton#action:disabled { background: @disabled_bg@; }
QPushButton#action[variant="accent"] { background: @accent@; border-color: @accent@; }
QPushButton#action[variant="accent"]:hover { background: @accent_hover@; border-color: @accent_hover@; }
QPushButton#action[variant="soft"] { background: @accent_soft@; border-color: @accent_soft@; }
QPushButton#action[variant="mint"] { background: @mint@; border-color: @mint@; }
QPushButton#action[variant="amber"] { background: @amber@; border-color: @amber@; }
QPushButton#action[variant="slate"] { background: @slate@; border-color: @slate@; }
QPushButton#action[variant="soft"]:hover, QPushButton#action[variant="mint"]:hover, QPushButton#action[variant="amber"]:hover, QPushButton#action[variant="slate"]:hover { border-color: @accent@; }
QPushButton#action[variant="accent"] QLabel { color: @accent_text@; }
QPushButton#action[variant="accent"] QLabel#tileHint { color: @accent_hint@; }

/* ---- inputs and lists */
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox { background: @field@; border: 1px solid @field_border@; border-radius: 12px; padding: 7px 10px; selection-background-color: @accent@; selection-color: @accent_text@; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: @accent@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @tile@; border: 1px solid @border@; selection-background-color: @selected@; selection-color: @text@; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 9px 12px; border-radius: 10px; }
QListWidget::item:hover { background: @field@; }
QListWidget::item:selected { background: @selected@; color: @text@; }
QTextBrowser { background: transparent; border: none; padding: 0; }
QCheckBox { spacing: 8px; }
QProgressBar { background: @field_border@; border: none; border-radius: 6px; max-height: 12px; min-height: 12px; text-align: center; color: transparent; }
QProgressBar::chunk { background: @accent@; border-radius: 6px; }
QSplitter::handle { background: transparent; width: 10px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @field_border@; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: @field_border@; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QToolTip { background: @tile@; color: @text@; border: 1px solid @border@; padding: 4px; }
"""

_current = "light"


def build_style(theme: str = "light") -> str:
    palette = PALETTES.get(theme, PALETTES["light"])
    sheet = _TEMPLATE
    for key, value in palette.items():
        sheet = sheet.replace(f"@{key}@", value)
    return sheet


def set_theme(theme: str) -> str:
    """Remember which theme is showing, so colours chosen in code (not in the sheet) match it. Returns the theme actually used."""
    global _current
    _current = theme if theme in PALETTES else "light"
    return _current


def current_palette() -> dict[str, str]:
    return PALETTES[_current]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours (4.5 is the AA level for normal text, 3.0 for large text and outlines)."""
    def lum(h: str) -> float:
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4   # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


STYLE = build_style("light")
