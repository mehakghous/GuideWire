"""The window with an online account: logging in, the Connection card, background sync, forgot password, the welcome and the Privacy switches."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.cloud import CloudAuthError, CloudSession, CloudUnavailable  # noqa: E402
from app.db import Database  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


class FakeOnline:
    """Accounts and the sync table in one fake."""
    configured = True

    def __init__(self):
        self.users, self.rows, self.clock, self.online, self.codes = {}, {}, 0, True, {}

    def _need(self):
        if not self.online:
            raise CloudUnavailable("offline")

    def _session(self, email):
        return CloudSession(self.users[email][1], email, "Ann", "AT", "RT")

    def sign_up(self, email, password, display_name):
        self._need()
        if email in self.users:
            raise CloudAuthError("An account with this email already exists.")
        self.users[email] = [password, f"uuid-{len(self.users) + 1}"]
        return self._session(email)

    def sign_in(self, email, password):
        self._need()
        if email not in self.users or self.users[email][0] != password:
            raise CloudAuthError("Incorrect email or password.")
        return self._session(email)

    def request_reset(self, email):
        self._need()
        self.codes[email] = "246810"

    def finish_reset(self, email, code, new_password):
        self._need()
        if self.codes.get(email) != code.strip():
            raise CloudAuthError("That code is wrong or has expired. Ask for a new one.")
        self.users[email][0] = new_password
        return self._session(email)

    def change_password(self, session, new_password):
        self._need()

    def refresh(self, session):
        return session

    def push_items(self, session, items):
        self._need()
        for i in items:
            self.clock += 1
            self.rows[(session.user_id, i["kind"], i["id"])] = {**i, "synced_at": f"2026-11-23T10:00:{self.clock:02d}+00:00"}

    def fetch_items(self, session, since):
        self._need()
        return [dict(r) for k, r in sorted(self.rows.items(), key=lambda kv: kv[1]["synced_at"]) if k[0] == session.user_id and (since is None or r["synced_at"] > since)]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cloud():
    return FakeOnline()


def make_window(cloud=None, **kw):
    return MainWindow(Database(":memory:"), sync=True, cloud=cloud, **kw)


@pytest.fixture
def win(qapp, cloud):
    w = make_window(cloud)
    yield w
    w.close()
    w.db.close()


def register(w, email="a@x.com", pw="correct horse"):
    w.login.email.setText(email)
    w.login.password.setText(pw)
    w.login.name.setText("Ann")
    w.login.do_register()


def card(w):
    return w.sidebar.conn_status.text(), w.sidebar.conn_hint.text(), w.sidebar.conn_card.property("kind")


# ---------------------------------------------------------------- the Connection card
def test_without_the_online_service_the_card_says_everything_is_local(qapp):
    w = make_window()
    register(w)
    assert card(w)[0] == "Saved on this computer" and not w.sidebar.sync_button.isVisibleTo(w.sidebar) and w.sync_service is None and not w.sync_timer.isActive()
    assert not w.login.forgot_button.isVisibleTo(w.login)                # no reset without the service
    w.close()


def test_logging_in_online_syncs_and_the_card_says_online(win, cloud):
    register(win)
    win.add_demo_tutorials()
    win.request_sync()
    status, hint, kind = card(win)
    assert (status, kind) == ("Online", "ok") and "Everything is saved online" in hint and win.sync_timer.isActive()
    assert any(k[1] == "tutorial" for k in cloud.rows) and win.sync_service.pending == 0


def test_going_offline_keeps_the_work_and_the_card_says_what_waits(win, cloud):
    register(win)
    cloud.online = False
    win.add_demo_tutorials()
    win.request_sync()
    status, hint, kind = card(win)
    assert (status, kind) == ("Offline", "offline") and "will sync when you are back online" in hint and win.sync_service.pending > 0
    cloud.online = True
    win.request_sync()
    assert card(win)[0] == "Online" and win.sync_service.pending == 0 and cloud.rows


def test_logging_in_with_no_connection_works_on_the_local_copy_and_says_so(qapp, cloud):
    w = make_window(cloud)
    register(w)
    w.on_logout()
    cloud.online = False
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.do_login()
    assert w.user is not None and card(w)[0] == "Offline" and "log in again when online" in card(w)[1]
    w.close()


def test_tutorials_from_another_computer_appear_on_home_after_a_sync(qapp, cloud):
    a = make_window(cloud)
    register(a)
    a.add_demo_tutorials()
    a.request_sync()
    b = make_window(cloud)                                              # the same account on a second computer
    b.login.email.setText("a@x.com")
    b.login.password.setText("correct horse")
    b.login.do_login()
    assert b.home.tutorials.count() == a.home.tutorials.count() > 0
    a.close()
    b.close()


def test_an_expired_sign_in_is_reported_and_logging_out_clears_the_card(win, cloud):
    register(win)

    class Dead(FakeOnline):
        def push_items(self, session, items):
            raise CloudAuthError("expired")

        def refresh(self, session):
            raise CloudAuthError("gone")
    win.accounts.cloud = win.sync_service.cloud = cloud_dead = Dead()
    win.add_demo_tutorials()
    win.request_sync()
    assert card(win)[0] == "Sign-in expired" and card(win)[2] == "problem" and cloud_dead
    win.on_logout()
    assert win.sync_service is None and not win.sync_timer.isActive() and win.accounts.cloud_session is None


# ---------------------------------------------------------------- forgot password
def test_forgot_password_sends_a_code_then_sets_the_new_password_and_signs_in(qapp, cloud):
    w = make_window(cloud)
    register(w)
    w.on_logout()
    login = w.login
    assert login.forgot_button.isVisibleTo(login)
    login.forgot_button.click()
    assert login.reset_mode and login.set_password_button.isVisibleTo(login) and not login.login_button.isVisibleTo(login)
    login.email.setText("a@x.com")
    login.send_code_button.click()
    assert "code is on its way" in login.notice.text() and cloud.codes["a@x.com"] == "246810"
    login.reset_code.setText("000000")
    login.reset_password.setText("brand new password")
    login.set_password_button.click()
    assert "wrong or has expired" in login.message.text() and w.user is None
    login.reset_code.setText("246810")
    login.set_password_button.click()
    assert w.user is not None and cloud.users["a@x.com"][0] == "brand new password" and not login.reset_mode
    w.close()


def test_the_reset_message_is_the_same_for_a_known_and_an_unknown_email(qapp, cloud):
    w = make_window(cloud)
    w.login.forgot_button.click()
    w.login.email.setText("nobody@x.com")
    w.login.send_code_button.click()
    assert "code is on its way" in w.login.notice.text()
    w.close()


def test_back_to_log_in_restores_the_form(qapp, cloud):
    w = make_window(cloud)
    w.login.forgot_button.click()
    w.login.cancel_reset_button.click()
    assert not w.login.reset_mode and w.login.login_button.isVisibleTo(w.login) and w.login.password.isVisibleTo(w.login)
    w.close()


# ---------------------------------------------------------------- the welcome and Privacy
def test_the_welcome_shows_once_after_the_first_login_and_stores_the_choices(qapp, cloud):
    w = make_window(cloud, show_welcome=True)
    register(w)
    assert w.current_screen() is w.onboarding and not w.sidebar.isVisibleTo(w)
    w.onboarding.ai_box.setChecked(False)
    w.onboarding.start_button.click()
    prefs = w.accounts.preferences(w.user.id)
    assert w.current_screen() is w.home and prefs["onboarded"] is True and prefs["ai"] is False and prefs["sync"] is True and prefs["overlay"] is True
    w.on_logout()
    w.login.email.setText("a@x.com")
    w.login.password.setText("correct horse")
    w.login.do_login()
    assert w.current_screen() is w.home                                    # not shown a second time
    w.close()


def test_without_the_online_service_the_sync_choice_is_off_and_explained(qapp):
    w = make_window(None, show_welcome=True)
    register(w)
    assert not w.onboarding.sync_box.isEnabled() and not w.onboarding.sync_box.isChecked() and "not set up" in w.onboarding.sync_box.toolTip()
    w.close()


def test_the_privacy_screen_explains_and_saves_each_switch_at_once(win):
    register(win)
    win.sidebar.buttons["privacy"].click()
    assert win.current_screen() is win.privacy and win.sidebar.buttons["privacy"].property("on") is True
    win.privacy.ai_box.setChecked(False)
    win.privacy.overlay_box.setChecked(False)
    prefs = win.accounts.preferences(win.user.id)
    assert prefs["ai"] is False and prefs["overlay"] is False
    text = " ".join(lab.text() for lab in win.privacy.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "nothing from your screen is sent online" in text and "bcrypt" in text and "Deleting an online account is not in the app yet" in text


def test_turning_the_ai_off_blocks_video_links_and_the_ask_model(win):
    register(win)
    win.change_privacy({"ai": False})
    assert not win.new_tutorial.ai_allowed and not win.ask_screen.use_model.isChecked() and not win.ask_screen.use_model.isEnabled()
    win.new_tutorial.video_runner = lambda *a: pytest.fail("the AI must not be called")
    win.new_tutorial.text.setPlainText("https://www.youtube.com/watch?v=abcdefghijk")
    win.new_tutorial.create()
    assert "turned off in Privacy" in win.new_tutorial.message.text()
    win.change_privacy({"ai": True})
    assert win.new_tutorial.ai_allowed


def test_turning_sync_off_stops_sending_and_the_card_says_so(win, cloud):
    register(win)
    win.change_privacy({"sync": False})
    cloud.rows.clear()
    win.add_demo_tutorials()
    win.request_sync()
    assert card(win)[0] == "Online sync is off" and cloud.rows == {}
    win.change_privacy({"sync": True})
    assert cloud.rows and card(win)[0] == "Online"


def test_the_overlay_choice_is_what_a_session_uses(win):
    register(win)
    win.add_demo_tutorials()
    win.change_privacy({"overlay": False})
    win.open_session(win.db.list_tutorials(win.user.id)[0]["id"])
    assert not win.session.watch_box.isChecked()
