"""Main window: a stack of screens (Login, Home, Step Review, Session) and the navigation between them."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from .. import demo_content
from ..accounts import Accounts, User
from ..ask import Asker
from ..db import Database
from ..session_engine import EngineError, SessionEngine
from ..step_editor import StepEditor
from .ask_screen import AskScreen
from .find_screen import FindScreen
from .screens import HistoryScreen, HomeScreen, LoginScreen, NewTutorialScreen, ProfileScreen, SessionScreen, StepReviewScreen
from .style import STYLE


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "shared" / "examples"


class MainWindow(QMainWindow):
    def __init__(self, db: Database, video_provider_factory=None, ask_model_factory=None, sync: bool = False, discover=None, vision=None):
        """`video_provider_factory` (the AI for video links) and `ask_model_factory` (the AI for questions) and `discover` (the YouTube tutorial search: (goal, app) -> DiscoveryResult) are given by `main()`; tests and any run without them stay offline. `vision` is the screen-guidance service (observe only); None means sessions run without it."""
        super().__init__()
        self.setWindowTitle("GuideWire")
        self.resize(1000, 680)
        self.db = db
        self.accounts = Accounts(db)
        self.user: User | None = None
        self.login = LoginScreen(self.accounts)
        self.home = HomeScreen()
        self.review = StepReviewScreen()
        self.session = SessionScreen()
        self.session.vision = vision                # None = sessions run without screen guidance
        self.history = HistoryScreen()
        self.new_tutorial = NewTutorialScreen()
        self.profile = ProfileScreen(self.accounts)
        self.ask_screen = AskScreen(Asker(ask_model_factory, discover=discover), sync=sync)
        self.find_screen = FindScreen(sync=sync)
        self.find_screen.finder = discover
        self.ask_screen.load_tutorial = self._tutorial_for_ask
        if video_provider_factory is not None:
            from ..pipeline import video_steps
            self.new_tutorial.video_runner = lambda url, app, status: video_steps(url, app, provider_factory=video_provider_factory, on_status=status)
        self.new_tutorial.sync = sync
        self.stack = QStackedWidget()
        for screen in (self.login, self.home, self.review, self.session, self.history, self.profile, self.new_tutorial, self.ask_screen, self.find_screen):
            self.stack.addWidget(screen)
        self.setCentralWidget(self.stack)
        self.login.logged_in.connect(self.on_logged_in)
        self.home.logout.connect(self.on_logout)
        self.home.open_review.connect(self.open_review)
        self.home.import_sample.connect(self.import_sample)
        self.review.saved.connect(lambda _tid: self.show_home())
        self.home.open_session.connect(self.open_session)
        self.review.back.connect(self.show_home)
        self.session.back.connect(self.show_home)
        self.history.back.connect(self.show_home)
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
        self.stack.setCurrentWidget(self.login)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.session.stop_guidance()                # never leave the highlight on screen after the app closes
        super().closeEvent(event)

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

    def on_logged_in(self, user: User) -> None:
        self.user = user
        self.show_home()

    def on_logout(self) -> None:
        self.user = None
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


def _make_vision():
    """The real screen-vision service on Windows (observe only); nothing elsewhere, so sessions simply run by hand."""
    if sys.platform != "win32":
        return None
    from vision.service import VisionService
    return VisionService("Blender")


def main() -> int:
    from ..ask import default_model_factory
    from ..discovery import find_tutorials
    from ..pipeline import default_video_provider
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow(Database(), video_provider_factory=default_video_provider, ask_model_factory=default_model_factory, discover=find_tutorials, vision=_make_vision())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
