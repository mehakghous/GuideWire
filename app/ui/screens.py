"""Screens of the main window. Each screen is a QWidget that emits signals; MainWindow decides what happens next.

Login and Home work. Step Review and Session are placeholders for now (the editor and the session engine are built in later steps).
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget

from ..accounts import AccountError, Accounts, User
from ..db import Database
from ..step_editor import EditError, StepEditor


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
    import_sample = pyqtSignal()
    logout = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.greeting = QLabel("")
        self.tutorials = QListWidget()
        self.review_button = QPushButton("Review steps")
        self.session_button = QPushButton("Start session")
        self.sample_button = QPushButton("Import sample steps")
        self.logout_button = QPushButton("Log out")
        self.sample_button.clicked.connect(self.import_sample.emit)
        self.review_button.clicked.connect(lambda: self._emit(self.open_review))
        self.session_button.clicked.connect(lambda: self._emit(self.open_session))
        self.logout_button.clicked.connect(self.logout.emit)
        row = QHBoxLayout()
        row.addWidget(self.review_button)
        row.addWidget(self.session_button)
        row.addWidget(self.sample_button)
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


class StepReviewScreen(QWidget):
    """List of steps the user can edit, reorder, delete and add, then save. All rules live in StepEditor."""
    back = pyqtSignal()
    saved = pyqtSignal(int)            # tutorial id

    def __init__(self):
        super().__init__()
        self.editor: StepEditor | None = None
        self.db: Database | None = None
        self.user_id: int | None = None
        self.title = QLabel("")
        self.list = QListWidget()
        self.status = QLabel("")
        self.edit_button = QPushButton("Edit text")
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        self.delete_button = QPushButton("Delete")
        self.add_button = QPushButton("Add step")
        self.save_button = QPushButton("Save")
        self.back_button = QPushButton("Back")
        self.edit_button.clicked.connect(self.edit_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.delete_button.clicked.connect(self.delete_selected)
        self.add_button.clicked.connect(self.add_step)
        self.save_button.clicked.connect(self.save)
        self.back_button.clicked.connect(self.back.emit)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_selected())
        row = QHBoxLayout()
        for b in (self.edit_button, self.up_button, self.down_button, self.delete_button, self.add_button):
            row.addWidget(b)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status)
        bottom.addStretch()
        bottom.addWidget(self.save_button)
        bottom.addWidget(self.back_button)
        root = QVBoxLayout(self)
        root.addWidget(self.title)
        root.addWidget(self.list)
        root.addLayout(row)
        root.addLayout(bottom)

    # ---- opening
    def load(self, editor: StepEditor, db: Database, user_id: int) -> None:
        self.editor, self.db, self.user_id = editor, db, user_id
        self.status.setText("")
        self.refresh()

    @property
    def tutorial_id(self) -> int | None:
        return None if self.editor is None else self.editor.tutorial_id

    def refresh(self, select: str | None = None) -> None:
        assert self.editor is not None
        self.title.setText(f"<h2>{self.editor.title}</h2>")
        self.list.clear()
        for s in self.editor.steps.steps:
            self.list.addItem(f"{s.order}. {s.goal}")
            self.list.item(self.list.count() - 1).setData(0x0100, s.id)     # Qt.ItemDataRole.UserRole
        if self.editor.steps.steps:
            ids = [s.id for s in self.editor.steps.steps]
            self.list.setCurrentRow(ids.index(select) if select in ids else 0)

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return None if item is None else str(item.data(0x0100))

    def _try(self, action) -> bool:
        try:
            action()
        except EditError as e:
            self.status.setText(str(e))
            return False
        self.status.setText("Unsaved changes" if self.editor and self.editor.dirty else "")
        return True

    # ---- actions (each one is a method so tests can call it without a dialog)
    def apply_edit(self, step_id: str, text: str) -> None:
        if self._try(lambda: self.editor.edit_goal(step_id, text)):
            self.refresh(step_id)

    def edit_selected(self) -> None:
        sid = self.selected_id()
        if sid is None:
            return
        current = self.editor.steps.steps[self.editor._index(sid)].goal
        text, ok = QInputDialog.getText(self, "Edit step", "Step text", text=current)
        if ok:
            self.apply_edit(sid, text)

    def move_selected(self, delta: int) -> None:
        sid = self.selected_id()
        if sid is not None and self._try(lambda: self.editor.move(sid, delta)):
            self.refresh(sid)

    def delete_selected(self) -> None:
        sid = self.selected_id()
        if sid is not None and self._try(lambda: self.editor.delete(sid)):
            self.refresh()

    def apply_add(self, text: str) -> None:
        sid = self.selected_id()
        new: list[str] = []
        if self._try(lambda: new.append(self.editor.add(text, after=sid))):
            self.refresh(new[0])

    def add_step(self) -> None:
        text, ok = QInputDialog.getText(self, "Add step", "Step text")
        if ok:
            self.apply_add(text)

    def save(self) -> None:
        tid: list[int] = []
        if self._try(lambda: tid.append(self.editor.save(self.db, self.user_id))):
            self.status.setText("Saved")
            self.saved.emit(tid[0])


class SessionScreen(_Placeholder):
    def __init__(self):
        super().__init__("Session", "The guided session (step by step, with the overlay) is built in a later step.")
        self.tutorial_id: int | None = None

    def load(self, tutorial_id: int) -> None:
        self.tutorial_id = tutorial_id
