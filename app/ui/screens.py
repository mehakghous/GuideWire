"""Screens of the main window. Each screen is a QWidget that emits signals; MainWindow decides what happens next.

Login and Home work. Step Review and Session are placeholders for now (the editor and the session engine are built in later steps).
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget

from ..accounts import AccountError, Accounts, User


class LoginScreen(QWidget):
    logged_in = pyqtSignal(object)    # User

    def __init__(self, accounts: Accounts):
        super().__init__()
        self.accounts = accounts
        self.email = QLineEdit()
        self.email.setPlaceholderText("Email")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Display name (for registering)")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.login_button = QPushButton("Log in")
        self.register_button = QPushButton("Create account")
        self.login_button.clicked.connect(self.do_login)
        self.register_button.clicked.connect(self.do_register)
        self.password.returnPressed.connect(self.do_login)
        form = QFormLayout()
        form.addRow("Email", self.email)
        form.addRow("Password", self.password)
        form.addRow("Name", self.name)
        buttons = QHBoxLayout()
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.register_button)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>GuideWire</h2>"))
        root.addLayout(form)
        root.addLayout(buttons)
        root.addWidget(self.message)
        root.addStretch()

    def _run(self, action) -> None:
        try:
            user = action()
        except AccountError as e:
            self.message.setText(str(e))
            return
        self.message.setText("")
        self.password.clear()
        self.logged_in.emit(user)

    def do_login(self) -> None:
        self._run(lambda: self.accounts.login(self.email.text(), self.password.text()))

    def do_register(self) -> None:
        self._run(lambda: self.accounts.register(self.email.text(), self.password.text(), self.name.text()))


class HomeScreen(QWidget):
    open_review = pyqtSignal(int)      # tutorial id
    open_session = pyqtSignal(int)     # tutorial id
    logout = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.greeting = QLabel("")
        self.tutorials = QListWidget()
        self.review_button = QPushButton("Review steps")
        self.session_button = QPushButton("Start session")
        self.logout_button = QPushButton("Log out")
        self.review_button.clicked.connect(lambda: self._emit(self.open_review))
        self.session_button.clicked.connect(lambda: self._emit(self.open_session))
        self.logout_button.clicked.connect(self.logout.emit)
        row = QHBoxLayout()
        row.addWidget(self.review_button)
        row.addWidget(self.session_button)
        row.addStretch()
        row.addWidget(self.logout_button)
        root = QVBoxLayout(self)
        root.addWidget(self.greeting)
        root.addWidget(QLabel("Your tutorials"))
        root.addWidget(self.tutorials)
        root.addLayout(row)

    def show_user(self, user: User, tutorials: list[tuple[int, str]]) -> None:
        self.greeting.setText(f"<h2>Welcome, {user.display_name or user.email}</h2>")
        self.tutorials.clear()
        for tid, title in tutorials:
            self.tutorials.addItem(f"{title}")
            self.tutorials.item(self.tutorials.count() - 1).setData(0x0100, tid)   # Qt.ItemDataRole.UserRole

    def selected_tutorial(self) -> int | None:
        item = self.tutorials.currentItem()
        return None if item is None else int(item.data(0x0100))

    def _emit(self, signal) -> None:
        tid = self.selected_tutorial()
        if tid is not None:
            signal.emit(tid)


class _Placeholder(QWidget):
    back = pyqtSignal()

    def __init__(self, title: str, text: str):
        super().__init__()
        self.title = QLabel(f"<h2>{title}</h2>")
        self.body = QLabel(text)
        self.body.setWordWrap(True)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back.emit)
        root = QVBoxLayout(self)
        root.addWidget(self.title)
        root.addWidget(self.body)
        root.addStretch()
        root.addWidget(self.back_button)


class StepReviewScreen(_Placeholder):
    def __init__(self):
        super().__init__("Step review", "The step editor (edit, reorder, delete, add, save) is built in a later step.")
        self.tutorial_id: int | None = None

    def load(self, tutorial_id: int) -> None:
        self.tutorial_id = tutorial_id


class SessionScreen(_Placeholder):
    def __init__(self):
        super().__init__("Session", "The guided session (step by step, with the overlay) is built in a later step.")
        self.tutorial_id: int | None = None

    def load(self, tutorial_id: int) -> None:
        self.tutorial_id = tutorial_id
