"""Main window: a stack of screens (Login, Home, Step Review, Session) and the navigation between them."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QHBoxLayout, QMainWindow, QStackedWidget

from .. import demo_content
from ..accounts import Accounts, User
from ..ask import Asker
from ..db import Database
from ..session_engine import EngineError, SessionEngine
from ..step_editor import StepEditor
from ..sync import Report, Result, SyncService
from .ask_screen import AskScreen
from .find_screen import FindScreen
from .backdrop import Backdrop
from .bento import recolour_shadows
from .onboarding import DEFAULTS as PRIVACY_DEFAULTS
from .onboarding import OnboardingScreen, PrivacyScreen
from .sidebar import Sidebar
from .workers import run_call
from .style import THEMES, build_style, set_theme
from .screens import HistoryScreen, HomeScreen, LoginScreen, NewTutorialScreen, ProfileScreen, SessionScreen, StepReviewScreen
from .style import STYLE


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "shared" / "examples"


class MainWindow(QMainWindow):
    def __init__(self, db: Database, video_provider_factory=None, ask_model_factory=None, sync: bool = False, discover=None, vision=None, vision_bridge=None, cloud=None, show_welcome: bool = False):
        """`video_provider_factory` (the AI for video links) and `ask_model_factory` (the AI for questions) and `discover` (the YouTube tutorial search: (goal, app) -> DiscoveryResult) are given by `main()`; tests and any run without them stay offline. `vision_bridge` (app.vision_bridge.VisionBridge) is the screen guidance for sessions; `vision` is the older form, a vision service that is wrapped in a bridge. None of them means sessions run by hand. `cloud` (app.cloud: Supabase) is the online account and sync; None means everything stays on this computer. `show_welcome` shows the first-run welcome after a learner's first login (the real app turns it on; tests leave it off)."""
        super().__init__()
        self.setWindowTitle("GuideWire")
        self.resize(1260, 800)
        self.db = db
        self.accounts = Accounts(db, cloud)
        self.sync_service: SyncService | None = None
        self._sync_inline = sync                  # tests run the sync right here
        self.show_welcome = show_welcome
        self._syncing = False
        self._sync_again = False
        self._last_report: Report | None = None
        self.user: User | None = None
        self.login = LoginScreen(self.accounts)
        self.home = HomeScreen()
        self.review = StepReviewScreen()
        self.session = SessionScreen()
        if vision_bridge is None and vision is not None:
            from ..vision_bridge import VisionBridge
            vision_bridge = VisionBridge(lambda app: vision)
        self.session.sync = sync
        self.session.set_bridge(vision_bridge)      # None = sessions run without screen guidance
        self.history = HistoryScreen()
        self.new_tutorial = NewTutorialScreen()
        self.profile = ProfileScreen(self.accounts)
        self.onboarding = OnboardingScreen()
        self.privacy = PrivacyScreen()
        self.ask_screen = AskScreen(Asker(ask_model_factory, discover=discover), sync=sync)
        self.find_screen = FindScreen(sync=sync)
        self.find_screen.finder = discover
        self.ask_screen.load_tutorial = self._tutorial_for_ask
        self.session.asker = self.ask_screen.asker               # the same answers as the Ask screen, asked from inside a session
        self.session.load_tutorial = self._tutorial_for_ask
        if video_provider_factory is not None:
            from ..pipeline import video_steps
            self.new_tutorial.video_runner = lambda url, app, status: video_steps(url, app, provider_factory=video_provider_factory, on_status=status)
        self.new_tutorial.sync = sync
        self.stack = QStackedWidget()
        for screen in (self.login, self.home, self.review, self.session, self.history, self.profile, self.new_tutorial, self.ask_screen, self.find_screen, self.onboarding, self.privacy):
            self.stack.addWidget(screen)
        self.sidebar = Sidebar()
        self.sidebar.set_companion(vision_bridge is not None)
        self.sidebar.chosen.connect(self.on_nav)
        self.sidebar.logout.connect(self.on_logout)
        self.sidebar.sync_requested.connect(self.request_sync)
        self.sidebar.hide()                       # only once someone is signed in
        shell = Backdrop()
        row = QHBoxLayout(shell)
        row.setContentsMargins(14, 14, 0, 14)
        row.setSpacing(0)
        row.addWidget(self.sidebar)
        row.addWidget(self.stack, 1)
        self.setCentralWidget(shell)
        self.stack.currentChanged.connect(self._sync_sidebar)
        self.stack.currentChanged.connect(self._fade_in)
        self.login.logged_in.connect(self.on_logged_in)
        self.home.logout.connect(self.on_logout)
        self.home.open_review.connect(self.open_review)
        self.home.import_sample.connect(self.import_sample)
        self.review.saved.connect(lambda _tid: self.show_home())
        self.home.open_session.connect(self.open_session)
        self.home.delete_tutorial.connect(self.delete_tutorial)
        self.review.back.connect(self.show_home)
        self.session.back.connect(self.show_home)
        self.history.back.connect(self.show_home)
        self.history.open_session.connect(self.resume_session)
        self.new_tutorial.back.connect(self.show_home)
        self.new_tutorial.created.connect(self.open_editor)
        self.home.new_tutorial.connect(self.open_new_tutorial)
        self.profile.back.connect(self.show_home)
        self.profile.profile_changed.connect(self.on_profile_changed)
        self.home.open_history.connect(self.open_history)
        self.home.open_profile.connect(self.open_profile)
        self.home.ask.connect(lambda: self.open_ask())
        self.home.find.connect(self.open_find)
        self.find_screen.back.connect(self.show_home)
        self.find_screen.make_steps.connect(self.steps_from_video)
        self.home.add_demo.connect(self.add_demo_tutorials)
        self.ask_screen.back.connect(self.show_home)
        self.ask_screen.save_steps.connect(self.save_asked_steps)
        self.session.ask_about.connect(lambda tid: self.open_ask(tid))
        self.onboarding.finished.connect(self.finish_onboarding)
        self.privacy.back.connect(self.show_home)
        self.privacy.changed.connect(self.change_privacy)
        for signal in (self.session.back, self.review.saved, self.new_tutorial.created, self.profile.profile_changed):
            signal.connect(lambda *_a: self.request_sync())       # a moment when something worth keeping has changed
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(60_000)
        self.sync_timer.timeout.connect(self.request_sync)
        self.stack.setCurrentWidget(self.login)
        self.refresh_connection()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.session.pause_if_active()
        self.session.close_guides()                # the screen overlay and the instruction box must not outlive the window
        super().closeEvent(event)

    def on_nav(self, key: str) -> None:
        """A sidebar item was clicked."""
        {"home": self.show_home, "find": self.open_find, "ask": self.open_ask, "import": self.open_new_tutorial,
         "history": self.open_history, "privacy": self.open_privacy, "settings": self.open_profile}[key]()

    def _sync_sidebar(self, _index: int = 0) -> None:
        """Show the panel on every screen except the sign-in, and mark the screen the user is on."""
        screen = self.stack.currentWidget()
        self.sidebar.setVisible(self.user is not None and screen not in (self.login, self.onboarding))
        self.sidebar.set_user(self.user.display_name if self.user else "")
        keys = {self.home: "home", self.find_screen: "find", self.ask_screen: "ask", self.new_tutorial: "import", self.history: "history", self.privacy: "privacy", self.profile: "settings"}
        self.sidebar.set_active(keys.get(screen))

    def _fade_in(self, _index: int = 0) -> None:
        """Each screen eases in. The effect is removed when it ends, so it never costs anything while the screen is in use."""
        screen = self.stack.currentWidget()
        if screen is None or not screen.isVisibleTo(self):
            return
        previous = getattr(screen, "_fade_anim", None)
        if previous is not None:
            previous.stop()                                       # a screen shown again while its last fade runs: that fade must not remove the new one's effect
        gen = getattr(screen, "_fade_gen", 0) + 1
        screen._fade_gen = gen
        fx = QGraphicsOpacityEffect(screen)
        screen.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", screen)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: screen.setGraphicsEffect(None) if getattr(screen, "_fade_gen", 0) == gen else None)
        screen._fade_anim = anim
        anim.start()

    def current_screen(self):
        return self.stack.currentWidget()

    def add_demo_tutorials(self) -> int:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return 0
        added = demo_content.add_demo_tutorials(self.db, self.user.id)
        self.show_home()
        return added

    def open_find(self) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.find_screen.reset()
        self.stack.setCurrentWidget(self.find_screen)

    def steps_from_video(self, url: str, app: str) -> None:
        """A suggested video was chosen: open New tutorial with its link filled in (the user still clicks Create steps)."""
        self.open_new_tutorial()
        self.new_tutorial.prefill(url, app)

    def open_ask(self, tutorial_id: int | None = None) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        rows = [(r["id"], r["title"]) for r in self.db.list_tutorials(self.user.id)]
        self.ask_screen.set_tutorials(rows, select=tutorial_id)          # from Home: a general question; from a session: that tutorial
        self.stack.setCurrentWidget(self.ask_screen)

    def _tutorial_for_ask(self, tutorial_id: int):
        """(steps, title, video url) of one of this user's tutorials, for the Ask screen."""
        from shared.step_record import StepList
        row = next(r for r in self.db.list_tutorials(self.user.id) if r["id"] == tutorial_id)
        steps = StepList(source_type=row["source_type"], app=row["app"], title=row["title"], steps=[s for _, s in self.db.get_steps(tutorial_id)])
        return steps, row["title"], row["source_url"]

    def save_asked_steps(self, steps, title: str) -> None:
        """The user saved the steps an answer gave: they become one of their tutorials."""
        if self.user is None:
            return
        have = {r["title"] for r in self.db.list_tutorials(self.user.id)}
        final, n = title, 2
        while final in have:
            final, n = f"{title} ({n})", n + 1
        self.db.save_tutorial(self.user.id, final, steps, source_type="manual")
        self.ask_screen.saved(final)

    def apply_theme(self) -> None:
        """Show the signed-in user's chosen theme (light or dark); the light one when nobody is signed in."""
        app = QApplication.instance()
        if app is None:
            return
        theme = self.accounts.preferences(self.user.id).get("theme") if self.user else "light"
        theme = set_theme(theme if theme in THEMES else "light")
        app.setStyleSheet(build_style(theme))
        recolour_shadows()                                         # the soft shadows are not in the style sheet
        self.centralWidget().update()

    def on_logged_in(self, user: User) -> None:
        self.user = user
        self.sync_service = SyncService(self.db, self.accounts.cloud, user.id) if self.accounts.online_enabled else None
        self._last_report = None
        self.apply_theme()
        self._apply_privacy()
        self.sync_timer.start() if self.sync_service else self.sync_timer.stop()
        if self._prefs().get("onboarded") or not self.show_welcome:
            self.show_home()
        else:
            self.onboarding.load(self._prefs(), self.accounts.online_enabled)
            self.stack.setCurrentWidget(self.onboarding)               # the welcome, once
        self.request_sync()

    def on_logout(self) -> None:
        self.session.pause_if_active()
        self.sync_timer.stop()
        self.sync_service = None
        self.accounts.sign_out()
        self.user = None
        self.apply_theme()
        self.stack.setCurrentWidget(self.login)
        self.login.show_reset(False)
        self.refresh_connection()

    # ---- privacy choices and the welcome
    def _prefs(self) -> dict:
        return self.accounts.preferences(self.user.id) if self.user else {}

    def _apply_privacy(self) -> None:
        """Make the features obey the learner's choices: the AI model, and (in open_session) the screen highlight."""
        prefs = {**PRIVACY_DEFAULTS, **self._prefs()}
        self.new_tutorial.ai_allowed = self.session.ai_allowed = bool(prefs["ai"])
        model_ok = self.ask_screen.asker.model_available and bool(prefs["ai"])
        self.ask_screen.use_model.setEnabled(model_ok)
        self.ask_screen.use_model.setChecked(model_ok)
        if not prefs["ai"]:
            self.ask_screen.use_model.setToolTip("The AI model is turned off in Privacy.")

    def finish_onboarding(self, choices: dict) -> None:
        if self.user is None:
            return
        self.accounts.set_preferences(self.user.id, **choices)
        self._apply_privacy()
        self.request_sync()
        self.show_home()

    def change_privacy(self, changed: dict) -> None:
        if self.user is None:
            return
        self.accounts.set_preferences(self.user.id, **changed)
        self._apply_privacy()
        self.request_sync()

    def open_privacy(self) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.privacy.load(self._prefs(), self.accounts.online_enabled)
        self.stack.setCurrentWidget(self.privacy)

    # ---- connection status and sync (the database is only touched here, on the window's thread; the internet part runs on a worker)
    def _can_sync(self) -> bool:
        return bool(self.sync_service and self.accounts.cloud_session and self._prefs().get("sync", True))

    def request_sync(self) -> None:
        if not self._can_sync():
            self.refresh_connection()
            return
        if self._syncing:
            self._sync_again = True
            return
        svc, session = self.sync_service, self.accounts.cloud_session
        self._syncing = True
        plan = svc.plan()
        self.refresh_connection()
        run_call(self, lambda _status: svc.network(session, plan), lambda res, svc=svc, plan=plan: self._sync_done(svc, plan, res), sync=self._sync_inline)

    def _sync_done(self, svc: SyncService, plan, result) -> None:
        self._syncing = False
        if svc is not self.sync_service:                       # the learner logged out meanwhile: nothing to apply
            return
        if isinstance(result, Exception):
            result = Result(error=f"Sync failed ({type(result).__name__}).")
        if result.session is not None:
            self.accounts.cloud_session = result.session
        self._last_report = svc.finish(plan, result)
        if self._last_report.signed_out:
            self.accounts.cloud_session = None
        if self._last_report.pulled and self.stack.currentWidget() is self.home:
            self.show_home()                                  # tutorials that arrived from another computer
        self.refresh_connection()
        if self._sync_again:
            self._sync_again = False
            self.request_sync()

    def refresh_connection(self) -> None:
        """The sidebar's Connection card: whether the work is saved only here, offline, syncing or online."""
        a, n = self.accounts, (self.sync_service.pending if self.sync_service else 0)
        waiting = f"{n} change{'s' if n != 1 else ''} waiting to sync." if n else "Everything is saved online."
        r = self._last_report
        if not a.online_enabled:
            card = ("Saved on this computer", "The online service is not set up, so nothing leaves this computer.", False, "ok")
        elif self.user is None:
            card = ("Online sync", "Log in to sync your tutorials and progress.", False, "ok")
        elif a.cloud_session is None and a.offline_login:
            card = ("Offline", "You logged in without a connection. Your work is saved here; log in again when online to sync it.", False, "offline")
        elif not self._prefs().get("sync", True):
            card = ("Online sync is off", "Your work stays on this computer. Turn it on in Privacy.", False, "ok")
        elif r is not None and r.signed_out or a.cloud_session is None:
            card = ("Sign-in expired", "Log out and log in again to keep syncing. Your work is saved here.", False, "problem")
        elif self._syncing:
            card = ("Syncing...", "", False, "busy")
        elif r is not None and r.offline:
            card = ("Offline", f"{n} change{'s' if n != 1 else ''} will sync when you are back online." if n else "Will sync when you are back online.", True, "offline")
        elif r is not None and r.error:
            card = ("Sync problem", r.error, True, "problem")
        else:
            card = ("Online", waiting, True, "ok")
        self.sidebar.set_connection(*card)

    def show_home(self) -> None:
        if self.user is None:                      # never show user data without a login
            self.stack.setCurrentWidget(self.login)
            return
        rows = [(r["id"], r["title"]) for r in self.db.list_tutorials(self.user.id)]
        self.home.show_user(self.user, rows, self.db.open_session_tutorials(self.user.id))
        self.stack.setCurrentWidget(self.home)

    def on_profile_changed(self, user: User) -> None:
        self.user = user
        self.apply_theme()

    def open_new_tutorial(self) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.new_tutorial.reset()
        self.stack.setCurrentWidget(self.new_tutorial)

    def open_editor(self, editor: StepEditor) -> None:
        """Review freshly generated steps; they are saved only when the user saves."""
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.review.load(editor, self.db, self.user.id)
        self.stack.setCurrentWidget(self.review)

    def open_history(self) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.history.load(self.db.session_history(self.user.id))
        self.stack.setCurrentWidget(self.history)

    def open_profile(self) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.profile.load(self.user)
        self.stack.setCurrentWidget(self.profile)

    def open_review(self, tutorial_id: int) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.review.load(StepEditor.from_db(self.db, self.user.id, tutorial_id), self.db, self.user.id)
        self.stack.setCurrentWidget(self.review)

    def import_sample(self, path: str | Path | None = None) -> None:
        """Open a hand-written sample step file in the editor (stands in for the real pipeline output). It is saved only when the user saves."""
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        path = Path(path) if path else sorted(SAMPLE_DIR.glob("*.json"))[0]
        self.review.load(StepEditor.from_json_file(path), self.db, self.user.id)
        self.stack.setCurrentWidget(self.review)

    def delete_tutorial(self, tutorial_id: int) -> None:
        """Home: the learner confirmed. The tutorial goes with its sessions; the online copy hears about it at the next sync."""
        if self.user is None:
            return
        self.db.delete_tutorial(self.user.id, tutorial_id)
        self.show_home()
        self.request_sync()

    def resume_session(self, session_id: int) -> None:
        """History: continue a session exactly where it stopped."""
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        try:
            engine = SessionEngine.load(self.db, self.user.id, session_id)
        except EngineError:
            return
        self.session.load(engine, guidance=bool(self.accounts.preferences(self.user.id).get("overlay", True)))
        self.stack.setCurrentWidget(self.session)

    def open_session(self, tutorial_id: int) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        try:
            engine = SessionEngine.resume_or_create(self.db, self.user.id, tutorial_id)      # coming back continues; Start over is the only way to begin again
        except EngineError:
            self.show_home()
            return
        self.session.load(engine, guidance=bool(self.accounts.preferences(self.user.id).get("overlay", True)))
        self.stack.setCurrentWidget(self.session)


def _make_bridge():
    """The real screen guidance on Windows: the vision bridge over the real vision service (observe only). Nothing elsewhere, so sessions simply run by hand."""
    if sys.platform != "win32":
        return None
    from ..vision_bridge import VisionBridge, default_service_factory
    return VisionBridge(default_service_factory)


def main() -> int:
    from ..cloud import SupabaseCloud
    from ..ask import default_model_factory
    from ..discovery import default_fit_provider, find_tutorials
    from ..pipeline import default_video_provider
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow(Database(), cloud=SupabaseCloud.from_env(), show_welcome=True, video_provider_factory=default_video_provider, ask_model_factory=default_model_factory, discover=lambda goal, app: find_tutorials(goal, app, fit_provider=default_fit_provider), vision_bridge=_make_bridge())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
