"""The look of the whole app: claymorphism. Soft, puffy shapes that look moulded from clay: a light edge on the top left, a soft shadow on the bottom right,
pill-shaped buttons that squash when pressed, round "clay ball" icons, and warm cream surfaces (see docs/design.md and docs/design/option-8-clay/demo.html).

What a style sheet can do lives here (gradients, bevelled edges, rounded corners); what it cannot do (soft outer shadows, hover animation, floating shapes)
is done in app/ui/bento.py and app/ui/backdrop.py. Colours come from PALETTES so a screen never hard-codes one.

`build_style(theme)` returns the sheet for "light" or "dark" (the Profile screen's Theme setting); `STYLE` is the light sheet. Tiles are `QFrame#tile` with an
optional `variant` property (soft, mint, amber, slate, accent, hero). tests/test_app_bento.py checks the contrast of every text and background pair.
"""
from __future__ import annotations

THEMES = ("light", "dark")

PALETTES = {
    "light": dict(canvas="#efe6dc", tile="#f7efe6", tile_hi="#fffaf3", border="#e3d3c3", hi="#ffffff", lo="#d8c5b3", shadow="#50785a3c",
                  text="#4a3a33", muted="#6a5850",
                  accent="#b8431a", accent_hi="#d95a22", accent_hover="#a23a15", accent_soft="#ffe6d2", accent_text="#ffffff", accent_hint="rgba(255, 255, 255, 220)",
                  mint="#d4f1f8", mint_hi="#9be6fb", amber="#fde4bb", slate="#ebe0d4", kicker="#0d5a73", selected_hi="#ffc88a",
                  hero="#f5a23c", hero_hi="#ffc88a", hero_lo="#ee8f20", hero_text="#4a2700",
                  teal="#3fc0dc", teal_hi="#9be6fb", teal_lo="#1f8fab", teal_text="#0d4a5f",
                  ok="#1f7a54", warn="#8f5200", danger="#b3261e", danger_soft="#fbe1dc",
                  field="#eee2d5", field_border="#d9c7b6", selected="#ffe2c4", disabled="#aa9c90", disabled_bg="#ebe1d6"),
    "dark": dict(canvas="#2a211c", tile="#3a2e27", tile_hi="#463830", border="#50413a", hi="#5c4a40", lo="#1f1814", shadow="#80000000",
                 text="#f6ece2", muted="#cdbcae",
                 accent="#ff9a62", accent_hi="#ffb68a", accent_hover="#ffb07f", accent_soft="#55382a", accent_text="#3a1500", accent_hint="rgba(58, 21, 0, 210)",
                 mint="#1f4a55", mint_hi="#2e6573", amber="#5a4020", slate="#46372f", kicker="#7fd8ee", selected_hi="#8a5a38",
                 hero="#e8962c", hero_hi="#f7b25a", hero_lo="#d28018", hero_text="#2f1a00",
                 teal="#3fc0dc", teal_hi="#9be6fb", teal_lo="#1f8fab", teal_text="#0d4a5f",
                 ok="#7fe0b0", warn="#f5b94f", danger="#ff9a8c", danger_soft="#5a2a26",
                 field="#30261f", field_border="#5b4a40", selected="#6b4430", disabled="#8a7a6f", disabled_bg="#3a3029"),
}

# The on-screen highlight over the application window (vision/overlay.py reads these). A bright orchid: it is not the orange of Blender and Houdini,
# the green of Maya's selection or Maya's blue, so it is never mistaken for the application's own highlight, and it shows on a grey window.
HIGHLIGHT_RGB = (236, 140, 196)

# one raised, clay-like surface: light top-left edge, darker bottom-right edge, a soft gradient fill
_RAISED = "border: 2px solid @hi@;"

_TEMPLATE = """
* { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; color: @text@; }
QMainWindow, QWidget#shell { background: @canvas@; }
QStackedWidget, QWidget#page { background: transparent; }
QLabel { background: transparent; }

/* ---- tiles: soft clay slabs */
QFrame#tile { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @tile@); @raised@ border-radius: 28px; }
QFrame#tile[variant="soft"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @accent_soft@); }
QFrame#tile[variant="mint"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @mint_hi@, stop:1 @mint@); }
QFrame#tile[variant="amber"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @amber@); }
QFrame#tile[variant="slate"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @slate@); }
QFrame#tile[variant="accent"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @accent_hi@, stop:1 @accent@); }
QFrame#tile[variant="hero"] { background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1, stop:0 @hero_hi@, stop:0.55 @hero@, stop:1 @hero_lo@); border-radius: 34px; }
QFrame#tile[variant="accent"] QLabel { color: @accent_text@; }
QFrame#tile[variant="accent"] QLabel#tileHint { color: @accent_hint@; }
QFrame#tile[variant="hero"] QLabel, QFrame#tile[variant="hero"] QLabel#tileHint { color: @hero_text@; }
QFrame#tile[variant="hero"] QLabel#pill { color: @accent@; background: @tile_hi@; }
QFrame#tile[variant="mint"] QLabel#tileHint, QFrame#tile[variant="amber"] QLabel#tileHint { color: @muted@; }
QFrame#inset { background: @field@; border: 2px solid @lo@; border-radius: 22px; }
QLabel#tileTitle { font-size: 12.5pt; font-weight: 700; }
QLabel#tileHint, QLabel#hint { color: @muted@; font-size: 9.5pt; }
QLabel#big { font-size: 26pt; font-weight: 700; }
QLabel#pageTitle { font-size: 22pt; font-weight: 800; }
QLabel#kicker { color: @kicker@; font-size: 11pt; font-weight: 700; }
QLabel#brand { font-size: 28pt; font-weight: 800; }
QLabel#empty { color: @muted@; font-size: 10.5pt; }
QLabel#error { color: @danger@; }
QLabel#pill { background: @tile_hi@; color: @accent@; border: 1px solid @lo@; border-radius: 10px; padding: 2px 12px; font-weight: 700; font-size: 9.5pt; }

/* ---- buttons: pills with a light edge on the top left and a shaded edge on the bottom right */
QPushButton { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @tile_hi@, stop:1 @field@); @raised@ border-radius: 16px; padding: 7px 18px; font-weight: 600; min-height: 20px; }
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @hi@, stop:1 @accent_soft@); }
QPushButton:pressed { padding-top: 10px; padding-bottom: 4px; border: 2px solid @lo@; }
QPushButton:disabled { color: @disabled@; background: @disabled_bg@; border: 2px solid @border@; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @accent_hi@, stop:1 @accent@); border: 2px solid @accent_hi@; color: @accent_text@; font-weight: 700; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @accent_hi@, stop:1 @accent_hover@); }
QPushButton#primary:pressed { padding-top: 10px; padding-bottom: 4px; }
QPushButton#primary:disabled { background: @disabled_bg@; color: @disabled@; border: 2px solid @border@; }
QPushButton#teal { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @teal_hi@, stop:1 @teal@); border: 2px solid @teal_hi@; color: @teal_text@; font-weight: 700; }
QPushButton#danger { color: @danger@; }
QPushButton#danger:hover { background: @danger_soft@; }

/* an action tile is a whole tile that is also a button (its labels sit on top; the button's own text is hidden) */
QPushButton#action { @raised@ background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @tile@); border-radius: 28px; padding: 0; text-align: left; color: transparent; }
QPushButton#action:hover { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @hi@, stop:1 @accent_soft@); }
QPushButton#action:pressed { padding: 0; border: 2px solid @lo@; }
QPushButton#action:disabled { background: @disabled_bg@; }
QPushButton#action[variant="accent"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @accent_hi@, stop:1 @accent@); border-color: @accent_hi@; }
QPushButton#action[variant="accent"]:hover { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @accent_hi@, stop:1 @accent_hover@); }
QPushButton#action[variant="soft"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @accent_soft@); }
QPushButton#action[variant="mint"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @mint_hi@, stop:1 @mint@); }
QPushButton#action[variant="amber"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @amber@); }
QPushButton#action[variant="slate"] { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @slate@); }
QPushButton#action[variant="accent"] QLabel { color: @accent_text@; }
QPushButton#action[variant="accent"] QLabel#tileHint { color: @accent_hint@; }

/* ---- inputs and lists: inputs are pressed into the clay, list rows are little raised pills */
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox { background: @field@; border: 2px solid @lo@; border-radius: 18px; padding: 7px 12px; selection-background-color: @accent@; selection-color: @accent_text@; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: @accent@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @tile@; border: 1px solid @border@; selection-background-color: @selected@; selection-color: @text@; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 10px 16px; margin: 3px 2px; border-radius: 20px; border: 2px solid @hi@; background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @tile@); }
QListWidget::item:hover { background: @accent_soft@; }
QListWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @selected_hi@, stop:1 @selected@); color: @text@; }
QTextBrowser { background: transparent; border: none; padding: 0; }
QCheckBox { spacing: 8px; }
QProgressBar { background: @field_border@; border: 2px solid @lo@; border-radius: 10px; max-height: 20px; min-height: 20px; text-align: center; color: transparent; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @teal_hi@, stop:1 @teal@); border-radius: 7px; margin: 1px; }
QSplitter::handle { background: transparent; width: 10px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @field_border@; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: @field_border@; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ---- sidebar: one tall clay panel */
QFrame#sidebar { background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1, stop:0 @tile_hi@, stop:1 @tile@); @raised@ border-radius: 32px; }
QLabel#sideLogo { font-size: 17pt; font-weight: 800; }
QLabel#sideSmall { color: @teal_text@; font-size: 9pt; font-weight: 600; }
QLabel#sideStatus { color: @teal_text@; font-weight: 700; }
QLabel#sideUser { font-weight: 700; padding-left: 6px; }
QFrame#sideCard { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @teal_hi@, stop:1 @teal@); border: 2px solid @hi@; border-radius: 22px; }
QPushButton#navItem { background: transparent; border: none; border-radius: 20px; color: @muted@; text-align: left; padding: 10px 16px; font-weight: 600; }
QPushButton#navItem:hover { background: @accent_soft@; color: @text@; }
QPushButton#navItem[on="true"] { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @accent_hi@, stop:1 @accent@); border: 2px solid @accent_hi@; color: @accent_text@; font-weight: 700; }
QPushButton#navLogout { background: transparent; border: none; color: @accent@; text-align: left; padding: 6px 6px; font-weight: 700; }
QPushButton#navLogout:hover { color: @accent_hover@; }
/* ---- chat: bubbles, chips, the composer */
QFrame#bubbleUser { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @accent_hi@, stop:1 @accent@); border-radius: 22px; border-bottom-right-radius: 6px; border: 2px solid @accent_hi@; }
QFrame#bubbleUser QLabel { color: @accent_text@; }
QFrame#bubbleBot { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @tile@); border-radius: 22px; border-bottom-left-radius: 6px; border: 2px solid @hi@; }
QFrame#stepsCard { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @mint_hi@, stop:1 @mint@); border-radius: 22px; border: 2px solid @hi@; }
QFrame#stepsCard QLabel { color: @teal_text@; }
QLabel#who { font-size: 9pt; font-weight: 700; color: @muted@; }
QLabel#greet { font-size: 22pt; font-weight: 800; }
QPushButton#chip { background: @field@; border: 2px solid @field_border@; border-radius: 15px; padding: 3px 12px; font-size: 9.5pt; font-weight: 600; min-height: 18px; color: @text@; }
QPushButton#chip:hover { background: @accent_soft@; }
QPushButton#chip:checked { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @accent_hi@, stop:1 @accent@); border-color: @accent_hi@; color: @accent_text@; }
QPushButton#chip:disabled { color: @disabled@; background: @disabled_bg@; }
QToolButton#picker { background: transparent; border: 2px solid transparent; border-radius: 14px; padding: 4px 10px; font-size: 9.5pt; font-weight: 600; color: @muted@; }
QToolButton#picker:hover, QToolButton#picker:pressed { background: @accent_soft@; color: @text@; }
QToolButton#picker::menu-indicator { image: none; width: 0; }
QMenu { background: @tile_hi@; border: 2px solid @hi@; border-radius: 14px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 10px; }
QMenu::item:selected { background: @selected@; color: @text@; }
QPushButton#suggest { background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @tile_hi@, stop:1 @tile@); border: 2px solid @hi@; border-radius: 20px; padding: 12px 16px; text-align: left; font-weight: 600; }
QPushButton#suggest:hover { background: @accent_soft@; }
QFrame#composer { background: @field@; border: 2px solid @field_border@; border-radius: 26px; }
QFrame#composer:focus-within { border-color: @accent@; }
QPlainTextEdit#composerEdit { background: transparent; border: none; padding: 6px 8px; }
QPushButton#send { background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 @accent_hi@, stop:1 @accent@); border: 2px solid @accent_hi@; border-radius: 20px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0; color: @accent_text@; font-size: 14pt; font-weight: 800; }
QPushButton#send:disabled { background: @disabled_bg@; color: @disabled@; border: 2px solid @border@; }
QScrollArea#chatScroll, QScrollArea#pageScroll { background: transparent; border: none; }
QScrollArea#chatScroll > QWidget > QWidget, QScrollArea#pageScroll > QWidget > QWidget { background: transparent; }
QListWidget#chatList::item { padding: 8px 12px; border-radius: 16px; }
QPushButton#linkButton { background: transparent; border: none; color: @accent@; font-weight: 700; padding: 2px 6px; min-height: 0; }
QPushButton#linkButton:hover { color: @accent_hover@; background: transparent; }
QToolTip { background: @tile@; color: @text@; border: 1px solid @border@; padding: 4px; }
"""

_current = "light"


def build_style(theme: str = "light") -> str:
    palette = PALETTES.get(theme, PALETTES["light"])
    sheet = _TEMPLATE.replace("@raised@", _RAISED)
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
