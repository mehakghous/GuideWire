import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from app.db import Database  # noqa: E402
from app.ui.bento import ActionTile, Tile, header, page_grid  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.style import HIGHLIGHT_RGB, PALETTES, STYLE, THEMES, build_style, contrast, current_palette, set_theme  # noqa: E402
from vision.overlay import HIGHLIGHT_RGB as OVERLAY_RGB  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow(Database(":memory:"))
    yield w
    w.close()
    w.db.close()
    qapp.setStyleSheet("")
    set_theme("light")


def _login(w, name="Mehak"):
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.name.setText(name)
    w.login.do_register()


# ---------------------------------------------------------------- the style sheet
@pytest.mark.parametrize("theme", THEMES)
def test_every_colour_token_is_filled_in(theme):
    sheet = build_style(theme)
    assert "@" not in sheet and PALETTES[theme]["canvas"] in sheet and PALETTES[theme]["accent"] in sheet


def test_dark_differs_from_light_and_unknown_falls_back_to_light():
    assert build_style("dark") != build_style("light")
    assert build_style("neon") == build_style("light") == STYLE


def test_the_palettes_define_the_same_colours():
    assert set(PALETTES["light"]) == set(PALETTES["dark"])


def test_every_tile_variant_has_a_rule():
    for variant in ("soft", "mint", "amber", "slate", "accent", "hero"):
        assert f'QFrame#tile[variant="{variant}"]' in STYLE


# ---------------------------------------------------------------- building blocks
def test_a_tile_has_a_body_a_title_and_a_variant(qapp):
    t = Tile("Steps", "A hint", variant="mint")
    assert t.objectName() == "tile" and t.property("variant") == "mint" and t.title_label.text() == "Steps"
    assert t.body.count() == 2


def test_an_action_tile_is_a_real_button_that_keeps_its_title(qapp):
    t = ActionTile("Find a tutorial", "Say what you want to learn", "soft")
    clicked = []
    t.clicked.connect(lambda: clicked.append(1))
    t.click()
    assert isinstance(t, QPushButton) and t.text() == "Find a tutorial" and clicked == [1]
    assert t.title_label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)       # a click on the text reaches the button
    assert t.hint_label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_an_action_tile_can_change_its_texts_and_be_disabled(qapp):
    t = ActionTile("A", "b")
    t.set_texts("Review steps", "Check them")
    assert t.text() == "Review steps" and t.title_label.text() == "Review steps" and t.hint_label.text() == "Check them"
    t.setEnabled(False)
    assert not t.isEnabled()


def test_a_header_holds_the_title_and_the_back_button(qapp):
    back = QPushButton("Back")
    h = header("History", "Past sessions", back=back)
    labels = [lab.text() for lab in h.findChildren(QLabel)]
    assert "History" in labels and "Past sessions" in labels and back.parent() is not None


def test_page_grid_marks_the_widget_as_a_page(qapp):
    from PyQt6.QtWidgets import QWidget
    w = QWidget()
    grid = page_grid(w)
    assert w.objectName() == "page" and grid.spacing() > 0 and grid.contentsMargins().left() > 0


# ---------------------------------------------------------------- the screens
def test_the_home_screen_counts_tutorials_and_escapes_the_name(win):
    _login(win, name="<b>Bold</b> & co")
    assert "&lt;b&gt;Bold&lt;/b&gt;" in win.home.greeting.text() and "<b>Bold</b>" not in win.home.greeting.text()
    assert win.home.count.text() == "0"
    win.add_demo_tutorials()
    win.show_home()
    assert int(win.home.count.text()) >= 1


def test_the_home_actions_are_whole_tile_buttons(win):
    for b in (win.home.find_button, win.home.ask_button, win.home.new_button, win.home.demo_button, win.home.sample_button,
              win.home.history_button, win.home.profile_button, win.home.logout_button):
        assert isinstance(b, ActionTile) and b.text()
    assert win.home.session_button.objectName() == "primary"


def test_the_session_screen_shows_a_progress_bar(win):
    _login(win)
    win.import_sample()
    win.review.save_button.click()
    win.home.tutorials.setCurrentRow(0)
    win.home.session_button.click()
    s = win.session
    s.start_button.click()
    assert s.progress_bar.maximum() == 4 and s.progress_bar.value() == 0
    s.done_button.click()
    assert s.progress_bar.value() == 1 and "1 of 4" in s.progress.text()


@pytest.mark.parametrize("theme", THEMES)
def test_every_screen_renders_in_both_themes(win, qapp, theme):
    qapp.setStyleSheet(build_style(theme))
    _login(win)
    for i in range(win.stack.count()):
        screen = win.stack.widget(i)
        win.stack.setCurrentWidget(screen)
        win.resize(1000, 680)
        assert not screen.grab().isNull()


# ---------------------------------------------------------------- the Theme setting now does something
def test_choosing_dark_in_the_profile_changes_the_look_and_logging_out_restores_light(win, qapp):
    _login(win)
    assert PALETTES["light"]["canvas"] in qapp.styleSheet()
    win.home.profile_button.click()
    win.profile.theme.setCurrentText("dark")
    win.profile.save_button.click()
    assert PALETTES["dark"]["canvas"] in qapp.styleSheet()
    win.on_logout()
    assert PALETTES["light"]["canvas"] in qapp.styleSheet()


def test_a_saved_dark_theme_is_applied_at_the_next_login(win, qapp):
    _login(win)
    win.accounts.set_preferences(win.user.id, theme="dark")
    win.on_logout()
    win.login.email.setText("a@x.com")
    win.login.password.setText("correct horse")
    win.login.do_login()
    assert PALETTES["dark"]["canvas"] in qapp.styleSheet()


def test_a_bad_saved_theme_falls_back_to_light(win, qapp):
    _login(win)
    win.accounts.set_preferences(win.user.id, theme="neon")
    win.apply_theme()
    assert PALETTES["light"]["canvas"] in qapp.styleSheet()


def test_review_and_start_session_are_disabled_until_there_is_a_tutorial(win):
    _login(win)
    assert not win.home.review_button.isEnabled() and not win.home.session_button.isEnabled()
    win.add_demo_tutorials()
    win.show_home()
    assert win.home.review_button.isEnabled() and win.home.session_button.isEnabled()


# ---------------------------------------------------------------- the palette: readable, and not the colours of Blender, Maya or Houdini
# (foreground, background, minimum contrast ratio). 4.5 is the AA level for normal text; 7 is used where text is the main content.
READABLE = [
    ("text", "tile", 7.0), ("text", "canvas", 7.0), ("muted", "tile", 4.5), ("muted", "canvas", 4.5),
    ("text", "accent_soft", 7.0), ("muted", "accent_soft", 4.5), ("text", "mint", 7.0), ("muted", "mint", 4.5),
    ("text", "amber", 7.0), ("muted", "amber", 4.5), ("text", "slate", 7.0), ("muted", "slate", 4.5),
    ("accent_text", "accent", 4.5), ("accent_text", "accent_hover", 4.5),
    ("accent", "tile", 4.5), ("accent", "accent_soft", 4.5), ("ok", "tile", 4.5), ("warn", "tile", 4.5),
    ("danger", "field", 4.5), ("danger", "tile", 4.5), ("text", "selected", 7.0), ("text", "field", 7.0),
]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg,bg,need", READABLE)
def test_every_text_and_background_pair_is_readable(theme, fg, bg, need):
    p = PALETTES[theme]
    assert contrast(p[fg], p[bg]) >= need, f"{theme}: {fg} {p[fg]} on {bg} {p[bg]} is only {contrast(p[fg], p[bg]):.1f}:1"


def _hue(hex_colour):
    import colorsys
    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


@pytest.mark.parametrize("theme", THEMES)
def test_the_accent_is_not_a_colour_the_dcc_applications_use(theme):
    """Blender and Houdini use orange (about 25 degrees), Maya highlights in green (about 140) and has a blue UI (about 215). The accent keeps clear of all of them."""
    hue = _hue(PALETTES[theme]["accent"])
    for taken in (25, 50, 140, 215):
        assert min(abs(hue - taken), 360 - abs(hue - taken)) >= 25, f"{theme} accent hue {hue:.0f} is too close to {taken}"


def test_the_on_screen_highlight_is_the_signature_colour_and_clear_of_the_applications():
    assert HIGHLIGHT_RGB == OVERLAY_RGB
    hue = _hue("#%02x%02x%02x" % HIGHLIGHT_RGB)
    for taken in (25, 50, 140, 215):
        assert min(abs(hue - taken), 360 - abs(hue - taken)) >= 25
    assert abs(hue - _hue(PALETTES["light"]["accent"])) < 25            # same family as the app's accent: one colour means GuideWire


def test_the_highlight_is_visible_on_a_grey_application_window():
    for window_grey in ("#2b2b2b", "#3c3c3c", "#4a4a4a"):
        assert contrast("#%02x%02x%02x" % HIGHLIGHT_RGB, window_grey) >= 3.0


def test_the_light_and_dark_sheets_use_the_right_text_on_the_accent():
    assert f"color: {PALETTES['light']['accent_text']}" in build_style("light")
    assert f"color: {PALETTES['dark']['accent_text']}" in build_style("dark")
    assert PALETTES["light"]["accent_text"] != PALETTES["dark"]["accent_text"]


# ---------------------------------------------------------------- colours chosen in code follow the theme
def test_set_theme_and_current_palette_follow_each_other():
    assert set_theme("dark") == "dark" and current_palette() is PALETTES["dark"]
    assert set_theme("neon") == "light" and current_palette() is PALETTES["light"]


def test_the_step_badge_colours_come_from_the_current_theme(win, qapp):
    _login(win)
    win.import_sample()
    html_light = win.review.detail.text()
    assert PALETTES["light"]["ok"] in html_light
    win.accounts.set_preferences(win.user.id, theme="dark")
    win.apply_theme()
    win.review.show_detail()
    assert PALETTES["dark"]["ok"] in win.review.detail.text() and PALETTES["light"]["ok"] not in win.review.detail.text()


def test_the_ask_conversation_follows_the_theme(win, qapp):
    _login(win)
    win.accounts.set_preferences(win.user.id, theme="dark")
    win.apply_theme()
    win.ask_screen._append("You", "hello")
    win.ask_screen._append("GuideWire", "hi")
    page = win.ask_screen.transcript.toHtml()
    assert PALETTES["dark"]["accent"].lstrip("#") in page.lower() and "#222" not in page.lower() and "#1f4e79" not in page.lower()
