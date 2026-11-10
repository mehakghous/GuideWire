import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from app.db import Database  # noqa: E402
from app.ui.bento import ActionTile, Tile, header, page_grid  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.style import PALETTES, STYLE, THEMES, build_style  # noqa: E402


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
    for variant in ("soft", "mint", "amber", "lilac", "accent"):
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
