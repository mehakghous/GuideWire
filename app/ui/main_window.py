"""Main window: a stack of screens (Login, Home, Step Review, Session) and the navigation between them."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from ..accounts import Accounts, User
from ..db import Database
from ..session_engine import EngineError, SessionEngine
from ..step_editor import StepEditor
from .screens import HistoryScreen, HomeScreen, LoginScreen, NewTutorialScreen, ProfileScreen, SessionScreen, StepReviewScreen


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "shared" / "examples"


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.setWindowTitle("GuideWire")
        self.resize(900, 600)
        self.db = db
        self.accounts = Accounts(db)
        self.user: User | None = None
        self.login = LoginScreen(self.accounts)
        self.home = HomeScreen()
        self.review = StepReviewScreen()
        self.session = SessionScreen()
        self.history = HistoryScreen()
        self.new_tutorial = NewTutorialScreen()
        self.profile = ProfileScreen(self.accounts)
        self.stack = QStackedWidget()
        for screen in (self.login, self.home, self.review, self.session, self.history, self.profile, self.new_tutorial):
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
        self.stack.setCurrentWidget(self.login)

    def current_screen(self):
        return self.stack.currentWidget()

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
        self.session.load(engine)
        self.stack.setCurrentWidget(self.session)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(Database())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
