"""Main window: a stack of screens (Login, Home, Step Review, Session) and the navigation between them."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QLayout, QMainWindow, QStackedWidget, QWidget

from .. import demo_content
from ..accounts import Accounts, User
from ..ask import Asker
from ..db import Database
from ..session_engine import EngineError, SessionEngine
from ..step_editor import StepEditor
from .ask_screen import AskScreen
from .find_screen import FindScreen
from .backdrop import Backdrop
from .sidebar import Sidebar
from .style import THEMES, build_style, current_palette, set_theme
from .pages import ProgressScreen, achievements, learning_paths
from .screens import HistoryScreen, HomeScreen, LoginScreen, NewTutorialScreen, ProfileScreen, SessionScreen, StepReviewScreen
from .style import STYLE


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "shared" / "examples"


class MainWindow(QMainWindow):
    def __init__(self, db: Database, video_provider_factory=None, ask_model_factory=None, sync: bool = False, discover=None, vision=None, vision_bridge=None):
        """`video_provider_factory` (the AI for video links) and `ask_model_factory` (the AI for questions) and `discover` (the YouTube tutorial search: (goal, app) -> DiscoveryResult) are given by `main()`; tests and any run without them stay offline. `vision_bridge` (app.vision_bridge.VisionBridge) is the screen guidance for sessions; `vision` is the older form, a vision service that is wrapped in a bridge. None of them means sessions run by hand."""
        super().__init__()
        self.setWindowTitle("GuideWire")
        self.resize(1260, 800)
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)      # a screen's own minimum must not push the window past a small laptop screen (1366x768 leaves ~705 high)
        self.setMinimumSize(900, 560)
        self.db = db
        self.accounts = Accounts(db)
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
        self.progress_page = ProgressScreen()
        self.paths_page = learning_paths()
        self.badges_page = achievements()
        self.new_tutorial = NewTutorialScreen()
        self.profile = ProfileScreen(self.accounts)
        video_runner = None
        if video_provider_factory is not None:
            from ..pipeline import video_steps
            video_runner = lambda url, app, status: video_steps(url, app, provider_factory=video_provider_factory, on_status=status)      # noqa: E731
        self.ask_screen = AskScreen(Asker(ask_model_factory, discover=discover, video_runner=video_runner), sync=sync)
        self.find_screen = FindScreen(sync=sync)
        self.find_screen.finder = discover
        if sync:
            self.find_screen.thumbnail_fetcher = lambda ids: {}                # tests never reach the network
        self.ask_screen.load_tutorial = self._tutorial_for_ask
        self.ask_screen.find_saved = self._saved_for_video
        if video_provider_factory is not None:
            from ..pipeline import video_steps
            self.new_tutorial.video_runner = lambda url, app, status: video_steps(url, app, provider_factory=video_provider_factory, on_status=status)
        self.new_tutorial.sync = sync
        self.stack = QStackedWidget()
        for screen in (self.login, self.home, self.review, self.session, self.history, self.profile, self.new_tutorial, self.ask_screen, self.find_screen, self.progress_page, self.paths_page, self.badges_page):
            self.stack.addWidget(screen)
        self.sidebar = Sidebar()
        self.sidebar.set_companion(vision_bridge is not None)
        self.sidebar.chosen.connect(self.on_nav)
        self.sidebar.logout.connect(self.on_logout)
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
        self.review.back.connect(self.show_home)
        self.session.back.connect(self.show_home)
        self.history.back.connect(self.show_home)
        for page in (self.progress_page, self.paths_page, self.badges_page):
            page.back.connect(self.show_home)
        self.history.start_again.connect(self.open_session)
        self.history.resume.connect(self.resume_session)
        self.history.review.connect(self.open_review)
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
        self.ask_screen.save_and_start.connect(lambda steps, title: self.save_asked_steps(steps, title, start=True))
        self.ask_screen.start_session.connect(self.open_session)
        self.ask_screen.save_guide.connect(self.save_chat_guide)
        self.ask_screen.review_tutorial.connect(self.open_review)
        self.session.ask_about.connect(lambda tid: self.open_ask(tid))
        self.stack.setCurrentWidget(self.login)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.WindowStateChange:
            self.session.set_window_minimized(self.isMinimized())          # a minimized GuideWire keeps watching; its small guide box stays on screen
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.session.close_guides()                 # the highlight and the small guide box must not outlive the window
        super().closeEvent(event)

    def on_nav(self, key: str) -> None:
        """A sidebar item was clicked."""
        {"home": self.show_home, "find": self.open_find, "ask": self.open_ask, "import": self.open_new_tutorial,
         "history": self.open_history, "progress": self.open_progress, "paths": lambda: self._open_page(self.paths_page), "badges": lambda: self._open_page(self.badges_page),
         "settings": self.open_profile}[key]()

    def _sync_sidebar(self, _index: int = 0) -> None:
        """Show the panel on every screen except the sign-in, and mark the screen the user is on."""
        screen = self.stack.currentWidget()
        if screen is not self.session:                                   # left the session: the window may drift and run at normal priority again (a session that is watching turns both off)
            from .bento import set_calm
            set_calm(False)
            try:
                from vision import winplatform
                winplatform.set_background_priority(False)
            except Exception:
                pass
        self.sidebar.setVisible(self.user is not None and screen is not self.login)
        self.sidebar.set_user(self.user.display_name if self.user else "")
        keys = {self.home: "home", self.find_screen: "find", self.ask_screen: "ask", self.new_tutorial: "import", self.history: "history", self.profile: "settings",
                self.progress_page: "progress", self.paths_page: "paths", self.badges_page: "badges"}
        self.sidebar.set_active(keys.get(screen))

    def _fade_in(self, _index: int = 0) -> None:
        """Each screen eases in. The effect is removed when it ends, so it never costs anything while the screen is in use."""
        screen = self.stack.currentWidget()
        if screen is None or not screen.isVisibleTo(self):
            return
        fx = QGraphicsOpacityEffect(screen)
        screen.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", screen)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: screen.setGraphicsEffect(None))
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
        self.find_screen.set_user(self.db, self.user.id)             # the screen is kept as it was left; a different learner starts clean
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
        self.ask_screen.set_user(self.db, self.user.id)
        self.ask_screen.set_tutorials(rows, select=tutorial_id)          # from Home: a new chat; from a session: a new chat about that tutorial
        self.stack.setCurrentWidget(self.ask_screen)

    def _tutorial_for_ask(self, tutorial_id: int):
        """(steps, title, video url) of one of this user's tutorials, for the Ask screen."""
        from shared.step_record import StepList
        row = next(r for r in self.db.list_tutorials(self.user.id) if r["id"] == tutorial_id)
        steps = StepList(source_type=row["source_type"], app=row["app"], title=row["title"], steps=[s for _, s in self.db.get_steps(tutorial_id)])
        return steps, row["title"], row["source_url"]

    def _saved_for_video(self, url: str):
        """(steps, title, tutorial id) of this user's tutorial made from that video, or None. Called on the window's thread (the database belongs to it)."""
        if self.user is None:
            return None
        row = self.db.tutorial_for_video(self.user.id, url)
        if row is None:
            return None
        steps, title, _url = self._tutorial_for_ask(row["id"])
        return steps, title, row["id"]

    def save_chat_guide(self, steps, title: str, url: str) -> None:
        """The chat turned a video into steps: they are saved as one of this user's tutorials (the same ones Home lists), with the video's link, and the chat is told."""
        if self.user is None:
            return
        have = {r["title"] for r in self.db.list_tutorials(self.user.id)}
        final, n = title, 2
        while final in have:
            final, n = f"{title} ({n})", n + 1
        try:
            tid = self.db.save_tutorial(self.user.id, final, steps, source_type=steps.source_type, source_url=url or None)
        except Exception as e:                                                  # the steps are not lost: the chat says it and the card offers to save them again
            self.ask_screen.guide_not_saved(f"{type(e).__name__}")
            return
        self.ask_screen.guide_saved(tid, final)

    def save_asked_steps(self, steps, title: str, start: bool = False) -> None:
        """The user saved the steps an answer gave: they become one of their tutorials (and, with `start`, a session on it opens at once)."""
        if self.user is None:
            return
        have = {r["title"] for r in self.db.list_tutorials(self.user.id)}
        final, n = title, 2
        while final in have:
            final, n = f"{title} ({n})", n + 1
        tid = self.db.save_tutorial(self.user.id, final, steps, source_type="manual")
        self.ask_screen.saved(final, tid)
        if start:
            self.open_session(tid)

    def apply_theme(self) -> None:
        """Show the signed-in user's chosen theme (light or dark); the light one when nobody is signed in."""
        app = QApplication.instance()
        if app is None:
            return
        theme = self.accounts.preferences(self.user.id).get("theme") if self.user else "light"
        theme = set_theme(theme if theme in THEMES else "light")
        app.setStyleSheet(build_style(theme))
        for w in self.findChildren(QWidget):                       # the soft shadows are not in the style sheet: recolour them for the theme
            fx = w.graphicsEffect()
            if isinstance(fx, QGraphicsDropShadowEffect):
                fx.setColor(QColor(current_palette()["shadow"]))
        self.centralWidget().update()

    def on_logged_in(self, user: User) -> None:
        self.user = user
        self.apply_theme()
        self.show_home()

    def on_logout(self) -> None:
        self.user = None
        self.find_screen.user_id = None                                   # the next learner never sees this one's searches
        self.find_screen.reset()
        self.find_screen.goal.clear()
        self.apply_theme()
        self.stack.setCurrentWidget(self.login)

    def show_home(self) -> None:
        if self.user is None:                      # never show user data without a login
            self.stack.setCurrentWidget(self.login)
            return
        rows = [(r["id"], r["title"]) for r in self.db.list_tutorials(self.user.id)]
        self.home.show_user(self.user, rows)
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

    def open_progress(self) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        self.progress_page.show_summary(self.db.progress_summary(self.user.id))
        self.stack.setCurrentWidget(self.progress_page)

    def _open_page(self, page) -> None:
        self.stack.setCurrentWidget(page if self.user is not None else self.login)

    def resume_session(self, session_id: int) -> None:
        """Pick an unfinished session up where it was left."""
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        try:
            engine = SessionEngine.load(self.db, self.user.id, session_id)
        except EngineError:
            self.open_history()
            return
        self.session.load(engine, guidance=bool(self.accounts.preferences(self.user.id).get("overlay", True)))
        self.stack.setCurrentWidget(self.session)

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

    def open_session(self, tutorial_id: int) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        try:
            engine = SessionEngine.create(self.db, self.user.id, tutorial_id)
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
    from ..ask import default_model_factory
    from ..discovery import default_fit_provider, find_tutorials
    from ..pipeline import default_video_provider
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow(Database(), video_provider_factory=default_video_provider, ask_model_factory=default_model_factory, discover=lambda goal, app, limit=3, exclude=(), check=True: find_tutorials(goal, app, limit=limit, exclude=exclude, fit_provider=default_fit_provider if check else None), vision_bridge=_make_bridge())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
