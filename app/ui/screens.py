"""Screens of the main window. Each screen is a QWidget that emits signals; MainWindow decides what happens next.

Login and Home work. Step Review and Session are placeholders for now (the editor and the session engine are built in later steps).
"""
from __future__ import annotations

import html
from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..accounts import AccountError, Accounts, User
from ..db import Database
from ..guidance import GuidanceController
from ..pipeline import _YOUTUBE, APPS, request_steps
from ..session_engine import ACTIVE, FINISHED, NOT_STARTED, EngineError, SessionEngine
from ..step_checks import checkability
from ..step_editor import EditError, StepEditor
from .bento import ActionTile, Tile, header, page_grid, tidy_list
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
        self.message.setObjectName("error")
        self.login_button.setObjectName("primary")
        grid = page_grid(self)
        brand = Tile(variant="accent", padding=28)
        name = QLabel("GuideWire")
        name.setObjectName("brand")
        tagline = QLabel("Learn Blender, Maya and Houdini one step at a time, right on your own screen.")
        tagline.setObjectName("tileHint")
        tagline.setWordWrap(True)
        brand.body.addWidget(name)
        brand.body.addWidget(tagline)
        brand.body.addStretch()
        for line in ("It watches your window and points at the next step.", "You do every action yourself.", "It checks whether the step worked."):
            chip = QLabel(line)
            chip.setObjectName("tileHint")
            chip.setWordWrap(True)
            brand.body.addWidget(chip)
        form_tile = Tile("Log in or create an account")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Email", self.email)
        form.addRow("Password", self.password)
        form.addRow("Name", self.name)
        form_tile.body.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.register_button)
        form_tile.body.addLayout(buttons)
        form_tile.body.addWidget(self.message)
        form_tile.body.addStretch()
        grid.setRowStretch(0, 1)
        grid.addWidget(brand, 1, 0)
        grid.addWidget(form_tile, 1, 1)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 5)
        grid.setColumnStretch(1, 4)

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
        self.greeting.setObjectName("pageTitle")
        self.greeting.setTextFormat(Qt.TextFormat.RichText)
        self.tutorials = QListWidget()
        tidy_list(self.tutorials)
        self.review_button = QPushButton("Review steps")
        self.session_button = QPushButton("Start session")
        self.session_button.setObjectName("primary")
        self.sample_button = ActionTile("Import sample steps", "A small Blender example to try the editor", "lilac", bottom=True)
        self.new_button = ActionTile("New from text or video link", "Paste instructions or a YouTube link", "mint")
        self.new_button.clicked.connect(self.new_tutorial.emit)
        self.find_button = ActionTile("Find a tutorial", "Say what you want to learn", "soft")
        self.find_button.clicked.connect(self.find.emit)
        self.ask_button = ActionTile("Ask GuideWire", "Questions about any step or tool", "accent")
        self.ask_button.clicked.connect(self.ask.emit)
        self.demo_button = ActionTile("Add demo tutorials", "Six video tutorials and three starter plans", "amber", bottom=True)
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
        self.history_button = ActionTile("History", "Your past sessions", "", min_height=76)
        self.profile_button = ActionTile("Profile", "Name, theme and password", "", min_height=76)
        self.logout_button = ActionTile("Log out", "See you next time", "", min_height=76)
        self.history_button.clicked.connect(self.open_history.emit)
        self.profile_button.clicked.connect(self.open_profile.emit)
        self.sample_button.clicked.connect(self.import_sample.emit)
        self.review_button.clicked.connect(lambda: self._emit(self.open_review))
        self.session_button.clicked.connect(lambda: self._emit(self.open_session))
        self.logout_button.clicked.connect(self.logout.emit)
        self.count = QLabel("0")
        self.count.setObjectName("big")
        grid = page_grid(self)
        welcome = Tile(variant="soft", padding=20)
        welcome.body.addWidget(self.greeting)
        sub = QLabel("What would you like to learn today?")
        sub.setObjectName("tileHint")
        welcome.body.addWidget(sub)
        stat = Tile(variant="lilac", padding=20)
        stat.body.addWidget(self.count)
        caption = QLabel("tutorials saved")
        caption.setObjectName("tileHint")
        stat.body.addWidget(caption)
        mine = Tile("Your tutorials")
        mine.body.addWidget(self.empty, 1)
        mine.body.addWidget(self.tutorials, 1)
        foot = QHBoxLayout()
        foot.addStretch()
        foot.addWidget(self.review_button)
        foot.addWidget(self.session_button)
        mine.body.addLayout(foot)
        grid.addWidget(welcome, 0, 0, 1, 2)
        grid.addWidget(stat, 0, 2)
        grid.addWidget(self.find_button, 1, 0)
        grid.addWidget(self.ask_button, 1, 1)
        grid.addWidget(self.new_button, 1, 2)
        grid.addWidget(mine, 2, 0, 2, 2)
        grid.addWidget(self.demo_button, 2, 2)
        grid.addWidget(self.sample_button, 3, 2)
        grid.addWidget(self.history_button, 4, 0)
        grid.addWidget(self.profile_button, 4, 1)
        grid.addWidget(self.logout_button, 4, 2)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        grid.setRowStretch(2, 2)
        grid.setRowStretch(3, 2)

    def show_user(self, user: User, tutorials: list[tuple[int, str]]) -> None:
        self.greeting.setText(f"Welcome, {html.escape(user.display_name or user.email)}")
        self.count.setText(str(len(tutorials)))
        self.tutorials.clear()
        for tid, title in tutorials:
            self.tutorials.addItem(f"{title}")
            self.tutorials.item(self.tutorials.count() - 1).setData(0x0100, tid)   # Qt.ItemDataRole.UserRole
            self.tutorials.item(self.tutorials.count() - 1).setToolTip(title)
        self.empty.setVisible(not tutorials)
        self.review_button.setEnabled(bool(tutorials))
        self.session_button.setEnabled(bool(tutorials))
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
    """The steps found for a tutorial: the user checks them, edits, reorders, deletes or adds, then saves. All rules live in StepEditor."""
    back = pyqtSignal()
    saved = pyqtSignal(int)            # tutorial id

    TAGS = {"manual": "  [you confirm]", "partial": "  [partly checked]", "checkable": ""}
    BADGE_COLOURS = {"checkable": "#1b7a3d", "partial": "#a35f00", "manual": "#5b6677"}

    def __init__(self):
        super().__init__()
        self.editor: StepEditor | None = None
        self.db: Database | None = None
        self.user_id: int | None = None
        self.confirm_discard = self._ask_discard       # replaced in tests so no dialog opens
        self.hint = QLabel("Check the steps GuideWire found. Edit, reorder, delete or add steps, then press Save.")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.title = QLabel("")
        self.title.setObjectName("pageTitle")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.list = QListWidget()
        tidy_list(self.list)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.detail = QLabel("")
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail.setObjectName("detail")
        self.edit_button = QPushButton("Edit step")
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("danger")
        self.add_button = QPushButton("Add step")
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.back_button = QPushButton("Back")
        self.edit_button.clicked.connect(self.edit_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.delete_button.clicked.connect(self.delete_selected)
        self.add_button.clicked.connect(self.add_step)
        self.save_button.clicked.connect(self.save)
        self.back_button.clicked.connect(self._leave)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_selected())
        self.list.currentRowChanged.connect(lambda _: self.show_detail())
        grid = page_grid(self)
        head = Tile(variant="soft", padding=16)
        top = QHBoxLayout()
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(self.title)
        texts.addWidget(self.hint)
        top.addLayout(texts, 1)
        top.addWidget(self.back_button)
        top.addWidget(self.save_button)
        head.body.addLayout(top)
        steps_tile = Tile("Steps")
        steps_tile.body.addWidget(self.list, 1)
        row = QHBoxLayout()
        for b in (self.add_button, self.edit_button, self.up_button, self.down_button):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.delete_button)
        steps_tile.body.addLayout(row)
        steps_tile.body.addWidget(self.status)
        card = Tile("This step")
        card.setMinimumWidth(320)
        card.body.addWidget(self.detail)
        card.body.addStretch()
        grid.addWidget(head, 0, 0, 1, 2)
        grid.addWidget(steps_tile, 1, 0)
        grid.addWidget(card, 1, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

    # ---- leaving without saving
    def _ask_discard(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText("You have changes that are not saved. Leave without saving them?")
        leave = box.addButton("Leave without saving", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is leave

    def _leave(self) -> None:
        if self.editor is not None and self.editor.dirty and not self.confirm_discard():
            return
        self.back.emit()

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
        self.title.setText(html.escape(self.editor.title))
        self.list.clear()
        for s in self.editor.steps.steps:
            self.list.addItem(f"{s.order}. {s.goal}" + self.TAGS[checkability(s).level])
            self.list.item(self.list.count() - 1).setData(0x0100, s.id)     # Qt.ItemDataRole.UserRole
            self.list.item(self.list.count() - 1).setToolTip(s.goal)
        if self.editor.steps.steps:
            ids = [s.id for s in self.editor.steps.steps]
            self.list.setCurrentRow(ids.index(select) if select in ids else 0)
        self.show_detail()

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return None if item is None else str(item.data(0x0100))

    @staticmethod
    def _bullets(title: str, items: list[str]) -> str:
        if not items:
            return ""
        return f"<p><b>{title}</b></p><ul style='margin-left:8px; -qt-list-indent:0;'>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"

    def show_detail(self) -> None:
        """The selected step in plain words: what it is, whether GuideWire can check it and why, how to do it, how to tell it worked, and any notes."""
        sid = self.selected_id()
        if self.editor is None or sid is None:
            self.detail.setText("<p>Select a step to see how GuideWire will handle it.</p>")
            return
        step = self.editor.steps.steps[self.editor._index(sid)]
        check = checkability(step)
        parts = [f"<p style='font-size:12pt'><b>Step {step.order}</b>&nbsp; {html.escape(step.goal)}</p>",
                 f"<p><b style='color:{self.BADGE_COLOURS[check.level]}'>{html.escape(check.badge)}.</b> {html.escape(check.text)}</p>"]
        if step.group:
            members = [s for s in self.editor.steps.steps if s.group_id == step.group_id]
            parts.append(f"<p>Part of: {html.escape(step.group)} (step {members.index(step) + 1} of {len(members)} in this group)</p>")
        parts.append(self._bullets("How to do it", [h.text for h in step.how_to]))
        parts.append(self._bullets("How you can tell it worked", [h.text for h in step.check]))
        parts.append(self._bullets("Notes", step.flags))
        self.detail.setText("".join(parts))

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
        text, ok = QInputDialog.getText(self, "Edit step", "What should this step say?", text=current)
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
        text, ok = QInputDialog.getText(self, "Add step", "Describe the step, for example: Press Tab to enter Edit Mode")
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
        self.title = QLabel("Session")
        self.title.setObjectName("pageTitle")
        self.progress = QLabel("")
        self.progress.setObjectName("tileTitle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.step_text = QLabel("")
        self.step_text.setWordWrap(True)
        self.step_text.setTextFormat(Qt.TextFormat.RichText)
        self.step_text.setObjectName("big")
        self.step_text.setStyleSheet("font-size: 18pt; font-weight: 600;")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel("")
        self.guide_hint = QLabel("")
        self.guide_hint.setWordWrap(True)
        self.guide_hint.setObjectName("hint")
        self.status.setObjectName("error")
        self.vision = None                          # set by MainWindow: a vision service, or None for a session without screen guidance
        self.guide: GuidanceController | None = None
        self.guide_enabled = True                   # the user's preference, and switched off for the session if vision cannot work here
        self.guide_interval_ms = 1500
        self.executor: ThreadPoolExecutor | None = None
        self.overlay_factory = _default_overlay
        self._overlay = None
        self._pending: Future | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self.start_button = QPushButton("Start")
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("primary")
        self.skip_button = QPushButton("Skip")
        self.prev_button = QPushButton("Previous step")
        self.back_button = QPushButton("Back")
        self.ask_button = QPushButton("Ask about this tutorial")
        self.ask_button.clicked.connect(lambda: self.tutorial_id is not None and self.ask_about.emit(self.tutorial_id))
        self.start_button.clicked.connect(lambda: self._do(self.engine.start))
        self.done_button.clicked.connect(lambda: self._do(self.engine.complete))
        self.skip_button.clicked.connect(lambda: self._do(self.engine.skip))
        self.prev_button.clicked.connect(lambda: self._do(self.engine.back))
        self.back_button.clicked.connect(self._leave)
        grid = page_grid(self)
        head = Tile(variant="soft", padding=16)
        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(self.back_button)
        head.body.addLayout(top)
        step_tile = Tile(variant="accent", padding=24)
        step_tile.body.addWidget(self.step_text)
        step_tile.body.addWidget(self.detail, 1)
        progress_tile = Tile("Progress", variant="mint")
        progress_tile.body.addWidget(self.progress)
        progress_tile.body.addWidget(self.progress_bar)
        progress_tile.body.addStretch()
        controls = Tile("Your move")
        row1 = QHBoxLayout()
        row1.addWidget(self.start_button)
        row1.addWidget(self.done_button)
        row2 = QHBoxLayout()
        row2.addWidget(self.prev_button)
        row2.addWidget(self.skip_button)
        controls.body.addLayout(row1)
        controls.body.addLayout(row2)
        controls.body.addWidget(self.ask_button)
        controls.body.addStretch()
        guide = Tile("On your screen", variant="lilac")
        about_guide = QLabel("When screen guidance is on, the highlight and automatic step checks are explained here.")
        about_guide.setObjectName("tileHint")
        about_guide.setWordWrap(True)
        guide.body.addWidget(about_guide)
        guide.body.addWidget(self.guide_hint)
        guide.body.addWidget(self.status)
        guide.body.addStretch()
        grid.addWidget(head, 0, 0, 1, 3)
        grid.addWidget(step_tile, 1, 0, 2, 2)
        grid.addWidget(progress_tile, 1, 2)
        grid.addWidget(controls, 2, 2)
        grid.addWidget(guide, 3, 0, 1, 3)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
        for col in range(3):
            grid.setColumnStretch(col, 1)

    @property
    def tutorial_id(self) -> int | None:
        return None if self.engine is None else self.engine.db.get_session(self.engine.session_id)["tutorial_id"]

    def load(self, engine: SessionEngine, *, guidance: bool = True) -> None:
        self.stop_guidance()
        self.engine = engine
        self.guide = GuidanceController(engine, self.vision)
        self.guide_enabled = guidance
        self.status.setText("")
        self.guide_hint.setText("" if guidance or self.vision is None else "Screen guidance is off in your profile.")
        self.refresh()

    # ---- screen guidance (observe only; see app/guidance.py)
    def _guiding(self) -> bool:
        return bool(self.guide and self.guide.available and self.guide_enabled and self.engine and self.engine.state == ACTIVE)

    def _leave(self) -> None:
        self.stop_guidance()
        self.back.emit()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.stop_guidance()
        super().hideEvent(event)

    def stop_guidance(self) -> None:
        self._timer.stop()
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        self._clear_overlay()

    def _clear_overlay(self) -> None:
        if self._overlay is not None:
            try:
                self._overlay.set_marks([])
                self._overlay.hide()
            except Exception:
                pass

    def _show_marks(self, marks: list) -> None:
        if not marks:
            self._clear_overlay()
            return
        if self._overlay is None:
            self._overlay = self.overlay_factory()
        self._overlay.set_marks(marks)
        self._overlay.show()

    def tick(self) -> None:
        """One guidance step: apply a finished reading, or start the next one. Vision runs on a worker thread; the engine is only touched here."""
        if not self._guiding():
            self.stop_guidance()
            return
        if self._pending is not None:
            if not self._pending.done():
                return
            snap, self._pending = self._pending.result(), None
            out = self.guide.apply(snap)
            self.guide_hint.setText(out.hint)
            if out.stop:
                self.guide_enabled = False
                self.stop_guidance()
                return
            if out.advanced:
                self._clear_overlay()
                self.refresh()
                return
            try:
                self._show_marks(out.marks)
            except Exception as e:                                 # an overlay problem must never break the session
                self.guide_hint.setText(f"Screen guidance stopped: {e}")
                self.guide_enabled = False
                self.stop_guidance()
            return
        cur = self.guide.current()
        if cur is None:
            return
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1)
        self._pending = self.executor.submit(self.guide.compute, *cur)

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
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
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
            check = checkability(step)
            if check.level != "checkable":
                lines.append(f"{check.full} Press Done when you have finished it.")
            self.detail.setText("\n".join(lines))
        self.start_button.setEnabled(e.state == NOT_STARTED)
        self.done_button.setEnabled(e.state == ACTIVE)
        self.skip_button.setEnabled(e.state == ACTIVE)
        self.prev_button.setEnabled(e.state == ACTIVE and (e.position or 1) > 1)
        if self._guiding():
            self._pending = None                                   # a reading of the previous step is useless now
            if not self._timer.isActive():
                self._timer.start(self.guide_interval_ms)
        else:
            self.stop_guidance()
            if e.state != ACTIVE:
                self.guide_hint.setText("" if self.guide_enabled or self.vision is None else self.guide_hint.text())


def _default_overlay():
    """The real overlay: transparent, click-through, follows the Blender window, hidden from screen capture so OCR never reads its own marks."""
    from vision import winplatform
    from vision.overlay import make_overlay_window
    overlay = make_overlay_window()
    overlay.hide_from_capture = True
    overlay.follow(lambda: (lambda w: w.rect if w else None)(winplatform.find_window("Blender")))
    overlay.show_click_through()
    return overlay


class HistoryScreen(QWidget):
    """The user's past and current sessions, newest first."""
    back = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.list = QListWidget()
        tidy_list(self.list)
        self.empty = QLabel("")
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back.emit)
        self.empty.setObjectName("empty")
        grid = page_grid(self)
        grid.addWidget(header("History", "Every session you have started, newest first.", back=self.back_button), 0, 0)
        box = Tile("Sessions")
        box.body.addWidget(self.empty)
        box.body.addWidget(self.list, 1)
        grid.addWidget(box, 1, 0)
        grid.setRowStretch(1, 1)

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
        self.save_button.setObjectName("primary")
        grid = page_grid(self)
        grid.addWidget(header("Profile", "Your name, how the app looks, and your password.", back=self.back_button), 0, 0, 1, 2)
        me = Tile("About you")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Email", self.email)
        form.addRow("Display name", self.name)
        form.addRow("Theme", self.theme)
        form.addRow("", self.overlay)
        me.body.addLayout(form)
        me.body.addWidget(self.save_button)
        self.message.setObjectName("hint")
        me.body.addWidget(self.message)
        pw_tile = Tile("Change password", variant="soft")
        pw = QFormLayout()
        pw.setSpacing(10)
        pw.addRow("Current password", self.old_password)
        pw.addRow("New password", self.new_password)
        pw_tile.body.addLayout(pw)
        pw_tile.body.addStretch()
        pw_tile.body.addWidget(self.password_button)
        grid.addWidget(me, 1, 0)
        grid.addWidget(pw_tile, 1, 1)
        grid.setRowStretch(2, 1)                  # spare height goes below the tiles instead of stretching them
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

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
        self.message.setObjectName("hint")
        self.notes.setObjectName("hint")
        self.create_button.setObjectName("primary")
        grid = page_grid(self)
        grid.addWidget(header("New tutorial", "Turn instructions, a transcript or a YouTube link into steps you can review.", back=self.back_button), 0, 0, 1, 2)
        details = Tile("Details")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Title", self.title)
        form.addRow("Application", self.app)
        details.body.addLayout(form)
        details.body.addStretch()
        tips = Tile("What you can paste", variant="mint")
        for line in ("One instruction per line", "A timed transcript (SRT, VTT)", "A YouTube link to a tutorial"):
            tip = QLabel("\u2022 " + line)
            tip.setObjectName("tileHint")
            tips.body.addWidget(tip)
        tips.body.addStretch()
        paste = Tile("The tutorial")
        paste.body.addWidget(self.text, 1)
        result = Tile(variant="soft", padding=14)
        result.body.addWidget(self.message)
        result.body.addWidget(self.notes)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.create_button)
        result.body.addLayout(actions)
        grid.addWidget(details, 1, 0)
        grid.addWidget(tips, 1, 1)
        grid.addWidget(paste, 2, 0, 1, 2)
        grid.addWidget(result, 3, 0, 1, 2)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

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
