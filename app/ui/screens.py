"""Screens of the main window. Each screen is a QWidget that emits signals; MainWindow decides what happens next.

Login and Home work. Step Review and Session are placeholders for now (the editor and the session engine are built in later steps).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..accounts import AccountError, Accounts, User
from ..db import Database
from ..pipeline import _YOUTUBE, APPS, request_steps
from ..session_engine import ACTIVE, FINISHED, NOT_STARTED, EngineError, SessionEngine
from ..step_editor import EditError, StepEditor
from .workers import run_call


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
    new_tutorial = pyqtSignal()
    ask = pyqtSignal()
    find = pyqtSignal()
    add_demo = pyqtSignal()
    open_history = pyqtSignal()
    open_profile = pyqtSignal()
    logout = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.greeting = QLabel("")
        self.tutorials = QListWidget()
        self.review_button = QPushButton("Review steps")
        self.session_button = QPushButton("Start session")
        self.sample_button = QPushButton("Import sample steps")
        self.new_button = QPushButton("New from text or video link")
        self.new_button.clicked.connect(self.new_tutorial.emit)
        self.find_button = QPushButton("Find a tutorial")
        self.find_button.clicked.connect(self.find.emit)
        self.ask_button = QPushButton("Ask GuideWire")
        self.ask_button.setObjectName("primary")
        self.ask_button.clicked.connect(self.ask.emit)
        self.demo_button = QPushButton("Add demo tutorials")
        self.demo_button.clicked.connect(self.add_demo.emit)
        self.empty = QLabel("")
        self.empty.setObjectName("empty")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty.setText(
            "<b>You have no tutorials yet.</b><br><br>"
            "&bull; <b>Add demo tutorials</b>: six real video tutorials (Blender, Maya, Houdini) and three starter plans, ready to review and run.<br>"
            "&bull; <b>Find a tutorial</b>: say what you want to learn and get up to three suggested videos.<br>"
            "&bull; <b>Ask GuideWire</b>: ask <i>where do I start rigging in Maya?</i> and save the steps it gives you.<br>"
            "&bull; <b>New from text or video link</b>: paste instructions, or a YouTube link, and the AI turns it into steps.")
        self.history_button = QPushButton("History")
        self.profile_button = QPushButton("Profile")
        self.logout_button = QPushButton("Log out")
        self.history_button.clicked.connect(self.open_history.emit)
        self.profile_button.clicked.connect(self.open_profile.emit)
        self.sample_button.clicked.connect(self.import_sample.emit)
        self.review_button.clicked.connect(lambda: self._emit(self.open_review))
        self.session_button.clicked.connect(lambda: self._emit(self.open_session))
        self.logout_button.clicked.connect(self.logout.emit)
        row = QHBoxLayout()
        row.addWidget(self.find_button)
        row.addWidget(self.ask_button)
        row.addWidget(self.new_button)
        row.addWidget(self.demo_button)
        row.addWidget(self.sample_button)
        row.addStretch()
        row2 = QHBoxLayout()
        row2.addWidget(self.review_button)
        row2.addWidget(self.session_button)
        row2.addWidget(self.history_button)
        row2.addWidget(self.profile_button)
        row2.addStretch()
        row2.addWidget(self.logout_button)
        root = QVBoxLayout(self)
        root.addWidget(self.greeting)
        root.addLayout(row)
        root.addWidget(QLabel("Your tutorials"))
        root.addWidget(self.empty, 1)
        root.addWidget(self.tutorials, 1)
        root.addLayout(row2)

    def show_user(self, user: User, tutorials: list[tuple[int, str]]) -> None:
        self.greeting.setText(f"<h2>Welcome, {user.display_name or user.email}</h2>")
        self.tutorials.clear()
        for tid, title in tutorials:
            self.tutorials.addItem(f"{title}")
            self.tutorials.item(self.tutorials.count() - 1).setData(0x0100, tid)   # Qt.ItemDataRole.UserRole
        self.empty.setVisible(not tutorials)
        self.tutorials.setVisible(bool(tutorials))
        if tutorials:
            self.tutorials.setCurrentRow(0)                                  # something is always selected, so Review and Start session just work

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
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
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
        self.list.currentRowChanged.connect(lambda _: self.show_detail())
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
        root.addWidget(self.detail)
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
            self.list.addItem(f"{s.order}. {s.goal}" + ("  [manual]" if not s.verifiable else ""))
            self.list.item(self.list.count() - 1).setData(0x0100, s.id)     # Qt.ItemDataRole.UserRole
        if self.editor.steps.steps:
            ids = [s.id for s in self.editor.steps.steps]
            self.list.setCurrentRow(ids.index(select) if select in ids else 0)
        self.show_detail()

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return None if item is None else str(item.data(0x0100))

    def show_detail(self) -> None:
        """Say why the selected step is manual, or what GuideWire will check, and show its warnings."""
        sid = self.selected_id()
        if self.editor is None or sid is None:
            self.detail.setText("")
            return
        step = self.editor.steps.steps[self.editor._index(sid)]
        lines = ["GuideWire can check this step automatically." if step.verifiable else "Manual step: GuideWire cannot check it, you confirm it yourself."]
        if step.group:
            members = [s for s in self.editor.steps.steps if s.group_id == step.group_id]
            lines.insert(0, f"Part of: {step.group} (step {members.index(step) + 1} of {len(members)} in this group)")
        lines.extend(f"Note: {f}" for f in step.flags)
        self.detail.setText("\n".join(lines))

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


class SessionScreen(QWidget):
    """Shows the active step with Done / Skip / Back. All state and rules live in SessionEngine."""
    back = pyqtSignal()
    ask_about = pyqtSignal(int)        # tutorial id

    def __init__(self):
        super().__init__()
        self.engine: SessionEngine | None = None
        self.title = QLabel("<h2>Session</h2>")
        self.progress = QLabel("")
        self.step_text = QLabel("")
        self.step_text.setWordWrap(True)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.status = QLabel("")
        self.start_button = QPushButton("Start")
        self.done_button = QPushButton("Done")
        self.skip_button = QPushButton("Skip")
        self.prev_button = QPushButton("Previous step")
        self.back_button = QPushButton("Back")
        self.ask_button = QPushButton("Ask about this tutorial")
        self.ask_button.clicked.connect(lambda: self.tutorial_id is not None and self.ask_about.emit(self.tutorial_id))
        self.start_button.clicked.connect(lambda: self._do(self.engine.start))
        self.done_button.clicked.connect(lambda: self._do(self.engine.complete))
        self.skip_button.clicked.connect(lambda: self._do(self.engine.skip))
        self.prev_button.clicked.connect(lambda: self._do(self.engine.back))
        self.back_button.clicked.connect(self.back.emit)
        row = QHBoxLayout()
        for b in (self.start_button, self.prev_button, self.skip_button, self.done_button):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.ask_button)
        root = QVBoxLayout(self)
        root.addWidget(self.title)
        root.addWidget(self.progress)
        root.addWidget(self.step_text)
        root.addWidget(self.detail)
        root.addLayout(row)
        root.addWidget(self.status)
        root.addStretch()
        root.addWidget(self.back_button)

    @property
    def tutorial_id(self) -> int | None:
        return None if self.engine is None else self.engine.db.get_session(self.engine.session_id)["tutorial_id"]

    def load(self, engine: SessionEngine) -> None:
        self.engine = engine
        self.status.setText("")
        self.refresh()

    def _do(self, action) -> None:
        try:
            action()
        except EngineError as e:
            self.status.setText(str(e))
        else:
            self.status.setText("")
        self.refresh()

    def refresh(self) -> None:
        e = self.engine
        assert e is not None
        done, total = e.progress()
        self.progress.setText(f"{done} of {total} steps done")
        step = e.current_step()
        if e.state == NOT_STARTED:
            self.step_text.setText("Press Start to begin.")
            self.detail.setText("")
        elif e.state == FINISHED:
            self.step_text.setText("Session finished. Well done!")
            self.detail.setText("")
        else:
            self.step_text.setText(f"<b>Step {e.position}:</b> {step.goal}")
            lines = [h.text for h in step.how_to]
            if not step.verifiable:
                lines.append("(GuideWire cannot check this step automatically: tell it when you are done.)")
            self.detail.setText("\n".join(lines))
        self.start_button.setEnabled(e.state == NOT_STARTED)
        self.done_button.setEnabled(e.state == ACTIVE)
        self.skip_button.setEnabled(e.state == ACTIVE)
        self.prev_button.setEnabled(e.state == ACTIVE and (e.position or 1) > 1)

class HistoryScreen(QWidget):
    """The user's past and current sessions, newest first."""
    back = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.list = QListWidget()
        self.empty = QLabel("")
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back.emit)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>History</h2>"))
        root.addWidget(self.empty)
        root.addWidget(self.list)
        root.addWidget(self.back_button)

    @staticmethod
    def describe(row: dict) -> str:
        state = {"not_started": "not started", "active": "in progress", "finished": "finished"}.get(row["state"], row["state"])
        when = (row["finished_at"] or row["started_at"] or "")[:16].replace("T", " ")
        return f"{row['title']} - {state} - {row['dealt']}/{row['total']} steps" + (f" - {when}" if when else "")

    def load(self, rows: list[dict]) -> None:
        self.list.clear()
        self.empty.setText("" if rows else "No sessions yet. Start one from Home.")
        for r in rows:
            self.list.addItem(self.describe(r))


class ProfileScreen(QWidget):
    """Display name, password change and preferences. Rules live in Accounts."""
    back = pyqtSignal()
    profile_changed = pyqtSignal(object)    # User

    THEMES = ("light", "dark")

    def __init__(self, accounts: Accounts):
        super().__init__()
        self.accounts = accounts
        self.user: User | None = None
        self.email = QLabel("")
        self.name = QLineEdit()
        self.theme = QComboBox()
        self.theme.addItems(self.THEMES)
        self.overlay = QCheckBox("Highlight the target on screen during a session")
        self.save_button = QPushButton("Save profile")
        self.old_password = QLineEdit()
        self.new_password = QLineEdit()
        for e in (self.old_password, self.new_password):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_button = QPushButton("Change password")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.back_button = QPushButton("Back")
        self.save_button.clicked.connect(self.save_profile)
        self.password_button.clicked.connect(self.change_password)
        self.back_button.clicked.connect(self.back.emit)
        form = QFormLayout()
        form.addRow("Email", self.email)
        form.addRow("Display name", self.name)
        form.addRow("Theme", self.theme)
        form.addRow("", self.overlay)
        pw = QFormLayout()
        pw.addRow("Current password", self.old_password)
        pw.addRow("New password", self.new_password)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>Profile</h2>"))
        root.addLayout(form)
        root.addWidget(self.save_button)
        root.addWidget(QLabel("<b>Change password</b>"))
        root.addLayout(pw)
        root.addWidget(self.password_button)
        root.addWidget(self.message)
        root.addStretch()
        root.addWidget(self.back_button)

    def load(self, user: User) -> None:
        self.user = user
        prefs = self.accounts.preferences(user.id)
        self.email.setText(user.email)
        self.name.setText(user.display_name)
        self.theme.setCurrentText(prefs["theme"] if prefs.get("theme") in self.THEMES else "light")
        self.overlay.setChecked(bool(prefs.get("overlay", True)))
        self.old_password.clear()
        self.new_password.clear()
        self.message.setText("")

    def save_profile(self) -> None:
        assert self.user is not None
        self.user = self.accounts.update_profile(self.user.id, self.name.text())
        self.accounts.set_preferences(self.user.id, theme=self.theme.currentText(), overlay=self.overlay.isChecked())
        self.message.setText("Saved")
        self.profile_changed.emit(self.user)

    def change_password(self) -> None:
        assert self.user is not None
        try:
            self.accounts.change_password(self.user.id, self.old_password.text(), self.new_password.text())
        except AccountError as e:
            self.message.setText(str(e))
            return
        self.old_password.clear()
        self.new_password.clear()
        self.message.setText("Password changed")

class NewTutorialScreen(QWidget):
    """Paste written steps (or a timed transcript); the pipeline turns them into steps to review. Nothing is saved until the user saves in the editor."""
    back = pyqtSignal()
    created = pyqtSignal(object)       # StepEditor

    def __init__(self):
        super().__init__()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Tutorial title")
        self.app = QComboBox()
        self.app.addItems(APPS)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("One instruction per line, e.g.\nPress Tab to enter Edit Mode\nSelect the cube\n\nor paste a timed transcript, or a YouTube link to a rigging tutorial")
        self.video_runner = None      # set by the main window: (url, app, on_status) -> PipelineResult; None = no AI model on this computer
        self.sync = False             # tests run the call inline
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.create_button = QPushButton("Create steps")
        self.back_button = QPushButton("Back")
        self.create_button.clicked.connect(self.create)
        self.back_button.clicked.connect(self.back.emit)
        form = QFormLayout()
        form.addRow("Title", self.title)
        form.addRow("Application", self.app)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>New tutorial</h2>"))
        root.addLayout(form)
        root.addWidget(self.text)
        root.addWidget(self.message)
        root.addWidget(self.notes)
        buttons = QHBoxLayout()
        buttons.addWidget(self.create_button)
        buttons.addStretch()
        buttons.addWidget(self.back_button)
        root.addLayout(buttons)

    def prefill(self, text: str, app: str | None = None) -> None:
        self.text.setPlainText(text)
        if app in APPS:
            self.app.setCurrentText(app)

    def reset(self) -> None:
        self.title.clear()
        self.text.clear()
        self.message.setText("")
        self.notes.setText("")

    def create(self) -> None:
        text, app = self.text.toPlainText(), self.app.currentText()
        link = _YOUTUBE.search(text)
        if link and self.video_runner is not None:
            self.create_button.setEnabled(False)
            self.message.setText("Starting...")
            self.notes.setText("")
            runner = self.video_runner
            run_call(self, lambda status: runner(link.group(0), app, status), self._on_result, on_status=self.message.setText, sync=self.sync)
            return
        self._on_result(request_steps(text, app))

    def _on_result(self, result) -> None:
        self.create_button.setEnabled(True)
        if isinstance(result, Exception):
            self.message.setText(f"That did not work ({type(result).__name__}: {str(result)[:120]}).")
            return
        self.message.setText(result.message)
        self.notes.setText("\n".join(f"Note: {n}" for n in result.notes))
        if result.steps is None:
            return
        title = self.title.text().strip() or result.steps.title or "Untitled tutorial"
        self.created.emit(StepEditor(result.steps, title=title))
