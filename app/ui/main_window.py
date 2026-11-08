"""Main window: a stack of screens (Login, Home, Step Review, Session) and the navigation between them."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from ..accounts import Accounts, User
from ..db import Database
from ..step_editor import StepEditor
from .screens import HomeScreen, LoginScreen, SessionScreen, StepReviewScreen


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
        self.stack = QStackedWidget()
        for screen in (self.login, self.home, self.review, self.session):
            self.stack.addWidget(screen)
        self.setCentralWidget(self.stack)
        self.login.logged_in.connect(self.on_logged_in)
        self.home.logout.connect(self.on_logout)
        self.home.open_review.connect(self.open_review)
        self.home.import_sample.connect(self.import_sample)
        self.review.saved.connect(lambda _tid: self.show_home())
        self.home.open_session.connect(lambda tid: self.go(self.session, tid))
        self.review.back.connect(self.show_home)
        self.session.back.connect(self.show_home)
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

    def go(self, screen, tutorial_id: int) -> None:
        if self.user is None:
            self.stack.setCurrentWidget(self.login)
            return
        screen.load(tutorial_id)
        self.stack.setCurrentWidget(screen)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(Database())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
