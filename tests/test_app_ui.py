# ---------------------------------------------------------------- new tutorial from text
def _new(w):
    _login(w)
    w.home.new_button.click()
    return w.new_tutorial


def test_new_from_text_opens_the_editor_and_saves_nothing_until_saved(win):
    n = _new(win)
    assert win.current_screen() is n
    n.title.setText("My cube")
    n.text.setPlainText("Press Tab to enter Edit Mode\nSelect the cube\nMove it with G")
    n.create_button.click()
    assert win.current_screen() is win.review and win.review.list.count() >= 2 and "My cube" in win.review.title.text()
    win.review.back_button.click()
    assert win.home.tutorials.count() == 0
    win.home.new_button.click()
    n.text.setPlainText("Press Tab to enter Edit Mode")
    n.create_button.click()
    win.review.save_button.click()
    assert win.home.tutorials.count() == 1 and win.home.tutorials.item(0).text() == "Untitled tutorial"


def test_new_from_text_shows_a_message_when_no_steps(win):
    n = _new(win)
    n.text.setPlainText("what is a vertex group?")
    n.create_button.click()
    assert win.current_screen() is n and n.message.text()


def test_youtube_link_shows_the_gateway_message(win):
    n = _new(win)
    n.text.setPlainText("https://youtu.be/abc123")
    n.create_button.click()
    assert win.current_screen() is n and "AI gateway" in n.message.text()


def test_new_tutorial_needs_a_login_and_reset_clears_the_form(win):
    win.open_new_tutorial()
    assert win.current_screen() is win.login
    n = _new(win)
    n.text.setPlainText("junk")
    n.back_button.click()
    win.home.new_button.click()
    assert n.text.toPlainText() == "" and n.message.text() == ""


# ---------------------------------------------------------------- step validation in the editor
def test_junk_step_is_refused_and_a_manual_step_is_marked(win):
    r = _open_sample(win)
    r.apply_add("ss")
    assert "too short" in r.status.text() and r.list.count() == 4
    r.list.setCurrentRow(0)
    r.apply_add("Save the file")
    assert r.list.currentItem().text().endswith("[manual]")
    assert "Manual step" in r.detail.text() and "not recognised" in r.detail.text()


def test_recognised_step_is_checkable_and_not_marked_manual(win):
    r = _open_sample(win)
    r.list.setCurrentRow(0)
    r.apply_add("Press Tab to enter Edit Mode")
    assert "[manual]" not in r.list.currentItem().text() and "check this step automatically" in r.detail.text()


def test_duplicate_step_is_refused_on_add_and_on_edit(win):
    r = _open_sample(win)
    r.apply_add("add a cube to the scene.")
    assert "already in the list" in r.status.text() and r.list.count() == 4
    r.apply_edit("s02", "Add a cube to the scene")
    assert "already in the list" in r.status.text()