"""The look of the whole app: a bento grid. Content sits in rounded tiles of different sizes on a soft canvas; one accent colour marks the main action.

Plain Qt style sheets, nothing to install. `build_style(theme)` returns the sheet for "light" or "dark" (the Profile screen's Theme setting);
`STYLE` is the light sheet. Tiles are `QFrame#tile` with an optional `variant` property (accent, soft, mint, amber, lilac); see app/ui/bento.py.
"""
from __future__ import annotations

THEMES = ("light", "dark")

PALETTES = {
    "light": dict(canvas="#eceff4", tile="#ffffff", border="#e0e5ee", text="#1b2230", muted="#667085", accent="#3b6ff5", accent_dark="#2c58cf",
                  accent_soft="#e8eefe", mint="#e3f5ea", amber="#fdf1dc", lilac="#efeafc", danger="#c0362c", danger_soft="#fdecea",
                  field="#f5f7fb", field_border="#d6dce8", selected="#e3ebff", disabled="#a0a9ba", disabled_bg="#eef1f6"),
    "dark": dict(canvas="#11141b", tile="#1b212b", border="#2a3140", text="#e8ecf3", muted="#98a2b3", accent="#5b86ff", accent_dark="#7a9cff",
                 accent_soft="#222c47", mint="#1c382b", amber="#3b3120", lilac="#2c2746", danger="#ff7b70", danger_soft="#3a2220",
                 field="#151a23", field_border="#303848", selected="#2a3552", disabled="#667085", disabled_bg="#1a1f28"),
}

_TEMPLATE = """
* { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; color: @text@; }
QMainWindow, QStackedWidget, QWidget#page { background: @canvas@; }
QLabel { background: transparent; }

/* ---- tiles: the bento boxes */
QFrame#tile { background: @tile@; border: 1px solid @border@; border-radius: 20px; }
QFrame#tile[variant="soft"] { background: @accent_soft@; border-color: @accent_soft@; }
QFrame#tile[variant="mint"] { background: @mint@; border-color: @mint@; }
QFrame#tile[variant="amber"] { background: @amber@; border-color: @amber@; }
QFrame#tile[variant="lilac"] { background: @lilac@; border-color: @lilac@; }
QFrame#tile[variant="accent"] { background: @accent@; border-color: @accent@; }
QFrame#tile[variant="accent"] QLabel { color: #ffffff; }
QFrame#tile[variant="accent"] QLabel#tileHint { color: rgba(255, 255, 255, 190); }
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
QPushButton#primary { background: @accent@; border-color: @accent@; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background: @accent_dark@; border-color: @accent_dark@; }
QPushButton#primary:disabled { background: @disabled_bg@; color: @disabled@; border-color: @border@; }
QPushButton#danger { color: @danger@; }
QPushButton#danger:hover { background: @danger_soft@; border-color: @danger@; }

/* an action tile is a whole tile that is also a button (its two labels sit on top; the button's own text is hidden) */
QPushButton#action { background: @tile@; border: 1px solid @border@; border-radius: 20px; padding: 0; text-align: left; color: transparent; }
QPushButton#action:hover { background: @accent_soft@; border-color: @accent@; }
QPushButton#action:disabled { background: @disabled_bg@; }
QPushButton#action[variant="accent"] { background: @accent@; border-color: @accent@; }
QPushButton#action[variant="accent"]:hover { background: @accent_dark@; border-color: @accent_dark@; }
QPushButton#action[variant="mint"] { background: @mint@; border-color: @mint@; }
QPushButton#action[variant="amber"] { background: @amber@; border-color: @amber@; }
QPushButton#action[variant="lilac"] { background: @lilac@; border-color: @lilac@; }
QPushButton#action[variant="mint"]:hover, QPushButton#action[variant="amber"]:hover, QPushButton#action[variant="lilac"]:hover { border-color: @accent@; }
QPushButton#action[variant="accent"] QLabel { color: #ffffff; }
QPushButton#action[variant="accent"] QLabel#tileHint { color: rgba(255, 255, 255, 190); }

/* ---- inputs and lists */
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox { background: @field@; border: 1px solid @field_border@; border-radius: 12px; padding: 7px 10px; selection-background-color: @accent@; }
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


def build_style(theme: str = "light") -> str:
    palette = PALETTES.get(theme, PALETTES["light"])
    sheet = _TEMPLATE
    for key, value in palette.items():
        sheet = sheet.replace(f"@{key}@", value)
    return sheet


STYLE = build_style("light")
