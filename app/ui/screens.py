"""Screens of the main window. Each screen is a QWidget that emits signals; MainWindow decides what happens next.

Login and Home work. Step Review and Session are placeholders for now (the editor and the session engine are built in later steps).
"""
from __future__ import annotations

import html

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QScrollArea, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import key_alternatives
from ..accounts import AccountError, AccountNotice, Accounts, User
from ..db import Database
from ..pipeline import _YOUTUBE, APPS, request_steps
from ..prerequisites import check as unmet_prerequisites
from ..prerequisites import prerequisites
from ..session_engine import ACTIVE, FINISHED, NOT_STARTED, PAUSED, EngineError, SessionEngine
from ..step_checks import checkability
from ..video_link import watch_url
from ..step_editor import EditError, StepEditor
from ..vision_bridge import overlaps
from .screen_guide import InstructionPanel, ScreenGuide, panel_position
from .bento import ActionTile, Head, HeroTile, IconTile, Tile, header, page_grid, pill, tidy_list
from .step_list import StepList
from .style import current_palette
from .workers import run_call



def _open_in_browser(url: str) -> None:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))


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
        self.notice = QLabel("")                                   # something to do next (check your email), not an error
        self.notice.setObjectName("hint")
        self.notice.setWordWrap(True)
        self.forgot_button = QPushButton("Forgot your password?")
        self.forgot_button.setObjectName("navLogout")              # a quiet text button
        self.forgot_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forgot_button.clicked.connect(lambda: self.show_reset(True))
        self.reset_code = QLineEdit()
        self.reset_code.setPlaceholderText("Code from the email")
        self.reset_password = QLineEdit()
        self.reset_password.setPlaceholderText("New password (8 characters or more)")
        self.reset_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.send_code_button = QPushButton("Send me a code")
        self.send_code_button.clicked.connect(self.do_send_code)
        self.set_password_button = QPushButton("Set new password")
        self.set_password_button.setObjectName("primary")
        self.set_password_button.clicked.connect(self.do_set_password)
        self.cancel_reset_button = QPushButton("Back to log in")
        self.cancel_reset_button.clicked.connect(lambda: self.show_reset(False))
        self.reset_mode = False
        self.login_button.setObjectName("primary")
        grid = page_grid(self)
        brand = HeroTile(padding=40)
        name = QLabel("GuideWire")
        name.setObjectName("brand")
        name.setStyleSheet("font-size: 40pt; font-weight: 800;")
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
        form_tile = Head()                                          # no box: the sign-in form sits directly on the page
        form_tile.setMinimumWidth(400)
        form_tile.setMaximumWidth(460)
        form_heading = QLabel("Log in or create an account")
        form_heading.setObjectName("pageTitle")
        form_heading.setWordWrap(True)
        form_tile.body.addWidget(form_heading)
        form_tile.body.addSpacing(14)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)       # each label sits above its box, so nothing is out of line
        form.setVerticalSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)
        for box in (self.email, self.password, self.name, self.reset_code, self.reset_password):
            box.setMinimumHeight(40)
        form.addRow("Email", self.email)
        form.addRow("Password", self.password)
        form.addRow("Name", self.name)
        form.addRow("Code", self.reset_code)
        form.addRow("New password", self.reset_password)
        self.form = form
        form_tile.body.addLayout(form)
        form_tile.body.addSpacing(14)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        for b in (self.login_button, self.register_button, self.send_code_button, self.set_password_button):
            b.setMinimumHeight(42)
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.register_button)
        form_tile.body.addLayout(buttons)
        reset_buttons = QHBoxLayout()
        reset_buttons.setSpacing(12)
        reset_buttons.addWidget(self.send_code_button)
        reset_buttons.addWidget(self.set_password_button)
        form_tile.body.addLayout(reset_buttons)
        form_tile.body.addSpacing(6)
        form_tile.body.addWidget(self.forgot_button, 0, Qt.AlignmentFlag.AlignLeft)
        form_tile.body.addWidget(self.cancel_reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        form_tile.body.addWidget(self.notice)
        form_tile.body.addWidget(self.message)
        self.show_reset(False)
        grid.addWidget(brand, 0, 0)                                  # full height, edge to edge
        grid.addWidget(form_tile, 0, 1, Qt.AlignmentFlag.AlignCenter)
        grid.setRowStretch(0, 1)
        grid.setColumnStretch(0, 5)
        grid.setColumnStretch(1, 4)

    def show_reset(self, on: bool) -> None:
        """Forgotten password: ask for a code by email, then type it with a new password. Only offered when the online service is set up."""
        self.reset_mode = on
        self.message.setText("")
        self.notice.setText("")
        self.form.setRowVisible(self.password, not on)
        self.form.setRowVisible(self.name, not on)
        self.form.setRowVisible(self.reset_code, on)
        self.form.setRowVisible(self.reset_password, on)
        for w in (self.login_button, self.register_button):
            w.setVisible(not on)
        for w in (self.send_code_button, self.set_password_button, self.cancel_reset_button):
            w.setVisible(on)
        self.forgot_button.setVisible(not on and self.accounts.online_enabled)

    def do_send_code(self) -> None:
        try:
            self.accounts.request_password_reset(self.email.text())
        except AccountError as e:
            self.message.setText(str(e))
            return
        self.message.setText("")
        self.notice.setText("If that address has an account, a code is on its way. Type it below with your new password.")     # the same words whether or not it has one

    def do_set_password(self) -> None:
        self._run(lambda: self.accounts.finish_password_reset(self.email.text(), self.reset_code.text(), self.reset_password.text()))

    def _run(self, action) -> None:
        try:
            user = action()
        except AccountNotice as e:
            self.message.setText("")
            self.notice.setText(str(e))
            return
        except AccountError as e:
            self.notice.setText("")
            self.message.setText(str(e))
            return
        self.message.setText("")
        self.notice.setText("")
        self.password.clear()
        self.reset_code.clear()
        self.reset_password.clear()
        self.show_reset(False)
        self.logged_in.emit(user)

    def do_login(self) -> None:
        self._run(lambda: self.accounts.login(self.email.text(), self.password.text()))

    def do_register(self) -> None:
        self._run(lambda: self.accounts.register(self.email.text(), self.password.text(), self.name.text()))


class HomeScreen(QWidget):
    open_review = pyqtSignal(int)      # tutorial id
    open_session = pyqtSignal(int)     # tutorial id
    delete_tutorial = pyqtSignal(int)  # tutorial id (already confirmed)
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
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("danger")
        self.delete_button.setToolTip("Delete the selected tutorial, with its sessions")
        self.confirm_delete = self._ask_delete             # replaced in tests so no dialog opens
        self.delete_button.clicked.connect(self._delete)
        self.sample_button = IconTile("Import sample steps", "A small Blender example to try the editor", "star")
        self.new_button = IconTile("New from text or video link", "Paste instructions or a YouTube link", "plus")
        self.new_button.clicked.connect(self.new_tutorial.emit)
        self.find_button = IconTile("Find a tutorial", "Say what you want to learn", "search")
        self.find_button.clicked.connect(self.find.emit)
        self.ask_button = IconTile("Ask GuideWire", "Questions about any step or tool", "chat")
        self.ask_button.clicked.connect(self.ask.emit)
        self.demo_button = IconTile("Add demo tutorials", "Six video tutorials and three starter plans", "clock")
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
        for b in (self.history_button, self.profile_button, self.logout_button):
            b.hide()                              # these three live in the sidebar now; the buttons stay so the screen's signals keep working
        self.hero_title = QLabel("")
        self.hero_title.setObjectName("big")
        self.hero_title.setWordWrap(True)
        self.hero_title.setStyleSheet("font-size: 19pt; font-weight: 800;")
        self.hero_hint = QLabel("")
        self.hero_hint.setObjectName("tileHint")
        self.hero_hint.setWordWrap(True)
        content = QWidget()                                       # the page scrolls as a whole, so nothing is squeezed on a short window and "Your tutorials" can always be reached
        grid = page_grid(content)
        self.review_button.setMinimumHeight(40)
        self.session_button.setMinimumHeight(40)
        kicker = QLabel("Continue learning")
        kicker.setObjectName("kicker")
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(kicker)
        title_box.addWidget(self.greeting)
        hero = HeroTile(padding=26)
        hero.setMinimumHeight(220)
        hero.body.addWidget(pill("Your next tutorial"), 0, Qt.AlignmentFlag.AlignLeft)
        hero.body.addWidget(self.hero_title)
        hero.body.addWidget(self.hero_hint)
        hero.body.addStretch()
        hero_row = QHBoxLayout()
        hero_row.setSpacing(12)
        hero_row.addWidget(self.session_button)
        hero_row.addWidget(self.review_button)
        hero_row.addStretch()
        hero_row.addWidget(self.delete_button)
        hero.body.addLayout(hero_row)
        stat = Tile(variant="mint", padding=20)
        stat.body.addWidget(self.count)
        caption = QLabel("tutorials saved")
        caption.setObjectName("tileHint")
        stat.body.addWidget(caption)
        stat.body.addStretch()
        mine = Tile("Your tutorials")
        mine.setMinimumHeight(330)
        mine.body.addWidget(self.empty, 1)
        mine.body.addWidget(self.tutorials, 1)
        grid.addLayout(title_box, 0, 0, 1, 5)
        grid.addWidget(hero, 1, 0, 1, 4)
        grid.addWidget(stat, 1, 4)
        for col, tile in enumerate((self.find_button, self.ask_button, self.new_button, self.demo_button, self.sample_button)):
            grid.addWidget(tile, 2, col)
        grid.addWidget(mine, 3, 0, 1, 5)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        grid.setRowStretch(1, 0)
        grid.setRowStretch(3, 1)
        self.tutorials.currentRowChanged.connect(lambda _row: self._show_hero())
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.scroll = scroll

    def _show_hero(self) -> None:
        tid = self.selected_tutorial()
        self.session_button.setText("Continue session" if tid in getattr(self, "in_progress", ()) else "Start session")
        item = self.tutorials.currentItem()
        if item is None:
            self.hero_title.setText("Nothing here yet")
            self.hero_hint.setText("Add the demo tutorials or ask GuideWire for steps, then start your first session.")
        else:
            self.hero_title.setText(item.text())
            self.hero_hint.setText("Start a guided session, or review the steps first.")

    def show_user(self, user: User, tutorials: list[tuple[int, str]], in_progress: frozenset[int] | set[int] = frozenset()) -> None:
        self.in_progress = set(in_progress)
        self.greeting.setText(f"Welcome, {html.escape(user.display_name or user.email)}")
        self.count.setText(str(len(tutorials)))
        self.tutorials.clear()
        for tid, title in tutorials:
            self.tutorials.addItem(f"{title}")
            self.tutorials.item(self.tutorials.count() - 1).setData(0x0100, tid)   # Qt.ItemDataRole.UserRole
            self.tutorials.item(self.tutorials.count() - 1).setToolTip(title)
        self.empty.setVisible(not tutorials)
        self.review_button.setEnabled(bool(tutorials))
        self.delete_button.setEnabled(bool(tutorials))
        self.session_button.setEnabled(bool(tutorials))
        self.tutorials.setVisible(bool(tutorials))
        if tutorials:
            self.tutorials.setCurrentRow(0)                                  # something is always selected, so Review and Start session just work
        self._show_hero()

    def selected_tutorial(self) -> int | None:
        item = self.tutorials.currentItem()
        return None if item is None else int(item.data(0x0100))

    def _ask_delete(self, title: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Delete tutorial")
        box.setText(f"Delete \"{title}\" and every session of it? This cannot be undone.")
        go = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep it", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def _delete(self) -> None:
        tid, item = self.selected_tutorial(), self.tutorials.currentItem()
        if tid is not None and item is not None and self.confirm_delete(item.text()):
            self.delete_tutorial.emit(tid)

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
    BADGE_KEYS = {"checkable": "ok", "partial": "warn", "manual": "muted"}      # palette colours (app/ui/style.py), so they follow the theme

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
        self.undo_button = QPushButton("Undo")
        self.rename_button = QPushButton("Rename")
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.back_button = QPushButton("Back")
        self.edit_button.clicked.connect(self.edit_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.delete_button.clicked.connect(self.delete_selected)
        self.add_button.clicked.connect(self.add_step)
        self.undo_button.clicked.connect(self.undo)
        self.rename_button.clicked.connect(self.rename_tutorial)
        self.save_button.clicked.connect(self.save)
        self.back_button.clicked.connect(self._leave)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_selected())
        self.list.currentRowChanged.connect(lambda _: self.show_detail())
        grid = page_grid(self)
        head = Head()
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
        row2 = QHBoxLayout()
        row2.addWidget(self.undo_button)
        row2.addWidget(self.rename_button)
        row2.addStretch()
        steps_tile.body.addLayout(row2)
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
        self.undo_button.setEnabled(self.editor.can_undo)
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
                 f"<p><b style='color:{current_palette()[self.BADGE_KEYS[check.level]]}'>{html.escape(check.badge)}.</b> {html.escape(check.text)}</p>"]
        if step.group:
            members = [s for s in self.editor.steps.steps if s.group_id == step.group_id]
            parts.append(f"<p>Part of: {html.escape(step.group)} (step {members.index(step) + 1} of {len(members)} in this group)</p>")
        if step.why:
            parts.append(f"<p><b>Why</b> {html.escape(step.why)}</p>")
        parts.append(self._bullets("How to do it", [h.text for h in step.how_to]))
        parts.append(self._bullets("How you can tell it worked", [h.text for h in step.check]))
        parts.append(self._bullets("Watch out", step.common_mistakes))
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

    def undo(self) -> None:
        """Take back the last change (adding, editing, moving, deleting or renaming)."""
        if self.editor is not None and self.editor.undo():
            self.status.setText("Unsaved changes" if self.editor.dirty else "")
            self.refresh(self.selected_id())

    def apply_rename(self, text: str) -> None:
        if self._try(lambda: self.editor.set_title(text)):
            self.refresh(self.selected_id())

    def rename_tutorial(self) -> None:
        if self.editor is None:
            return
        text, ok = QInputDialog.getText(self, "Rename tutorial", "Tutorial title:", text=self.editor.title)
        if ok:
            self.apply_rename(text)

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
    """Shows the active step with Done / Skip / Back, and, while it is watching, guides the learner on the application's own screen. All step state and rules live in SessionEngine; what is on screen comes from
    the vision bridge (app/vision_bridge.py). The layout is the bento one: the step is the hero tile, and everything about the screen guidance is in the "On your screen" tile.

    Guidance in one picture: one look at a time on a worker thread (`poll`), judged on this thread (`_looked`); the highlight, the small guide box and the status line all come from the same `Tick`, and all are cleared
    together when the step changes (`_on_step_change`), so nothing of the previous step stays under the new one.

    The learner is in charge of the pace. PAUSE holds the session on the step: nothing is looked at, highlighted or completed until Resume, so a step can be read and studied (Previous step pauses too, so the step
    you went back to is not completed again the moment it is shown, which it would be whenever the application is already in the state that step ends in). The list of ALL steps shows where you are; clicking a
    step only LOOKS at it (`viewing`), and "Go to this step" is what moves the session."""
    back = pyqtSignal()
    ask_about = pyqtSignal(int)        # tutorial id

    LOOK_ACTIVE_MS = 400               # looking while the learner works
    LOOK_IDLE_MS = 1500                # looking while they read or are away
    IDLE_AFTER_S = 2.0
    PAUSE_TIP = "Hold the session on this step: nothing is checked or highlighted until you press Resume, so you can read the step, look at the application, or go back."

    def __init__(self):
        super().__init__()
        self.engine: SessionEngine | None = None
        self.paused = False                     # the learner holds the session on this step: no looking, no highlight, no automatic completion
        self.viewing: int | None = None         # a step (1-based) the learner is only LOOKING at, not the one they are on
        self.prereqs: list = []                 # what the tutorial assumes you already have (app/prerequisites.py)
        self.prereq_missing: list = []          # the ones the application's own state showed to be missing
        self._prereq_checked = False
        self.title = QLabel("Session")
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)                                          # a long video title wraps; it must never make the page wider than the window
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
        self.status.setObjectName("error")
        self.status.setWordWrap(True)
        # ---- screen guidance (vision observes only; the learner does every action)
        self.bridge = None                      # the vision bridge (app.vision_bridge.VisionBridge); None = no screen guidance on this computer
        self.sync = False                       # tests run the look inline and call poll() themselves
        self.guide = ScreenGuide()
        self._busy = False
        self.timer = QTimer(self)
        self.timer.setInterval(self.LOOK_ACTIVE_MS)
        self.timer.timeout.connect(self.poll)
        self.track_timer = QTimer(self)                  # cheap and fast: follows the application window (a move carries the highlight, a resize asks for a new look)
        self.track_timer.setInterval(200)
        self.track_timer.timeout.connect(self._track)
        self.panel: InstructionPanel | None = None
        self._dismissed_step: str | None = None
        self._last_window = None
        self._last_hint = ""
        self._last_keys: tuple[str, ...] = ()
        self._shown_step: str | None = None              # the step the guide (highlight, box, status line) is showing: everything is cleared together when it changes
        self._app = "blender"
        self._profile_off = False                        # the learner's profile preference switched screen guidance off for sessions
        self._window_minimized = False                   # set by the main window (and by `minimize_to_guide`): asking Qt from hideEvent is not safe while the window is being destroyed
        self.watch_box = QCheckBox("Watch my screen and highlight the next click")
        self.watch_box.setToolTip("GuideWire only looks at the application window: it never clicks, types or moves anything.")
        self.watch_box.setChecked(True)
        self.watch_box.setVisible(False)
        self.watch_box.toggled.connect(lambda _on: self._sync_timer())
        self.panel_box = QCheckBox("Show the small guide box next to the application")
        self.panel_box.setChecked(True)
        self.panel_box.setVisible(False)
        self.panel_box.toggled.connect(lambda _on: self._refresh_panel())
        self.watch_label = QLabel("")                    # the status line: what GuideWire sees, in words
        self.watch_label.setWordWrap(True)
        self.watch_label.setObjectName("hint")
        self.cover_label = QLabel("")
        self.cover_label.setWordWrap(True)
        self.cover_label.setObjectName("error")
        self.cover_label.setVisible(False)
        self.side_button = QPushButton("Minimize GuideWire (the small guide stays on screen)")
        self.side_button.setToolTip("Hides this window so the application has the whole screen; the small guide box stays on top and can be moved, resized or minimized.")
        self.side_button.setVisible(False)
        self.side_button.clicked.connect(self.minimize_to_guide)
        self.start_button = QPushButton("Start")
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("primary")
        self.skip_button = QPushButton("Skip")
        self.prev_button = QPushButton("Previous step")
        self.pause_button = QPushButton("Pause")
        self.pause_button.setToolTip(self.PAUSE_TIP)
        self.goto_button = QPushButton("Go to this step")
        self.goto_button.setToolTip("Move the session to the step you are looking at (steps in between are skipped, or become to-do again when it is earlier).")
        self.unview_button = QPushButton("Back to my step")
        self.open_url = _open_in_browser                   # replaced in tests so no browser opens
        self.video_button = QPushButton("Watch this step in the video")
        self.video_button.setVisible(False)
        self.video_button.clicked.connect(self.watch_video)
        self.asker = None                                  # set by the main window: app.ask.Asker; None = no questions in sessions
        self.load_tutorial = None                          # (tutorial id) -> (steps, title, video link): set by the main window
        self.ai_allowed = True                             # the learner's Privacy choice
        self.question = QLineEdit()
        self.question.setPlaceholderText("Ask about this step, e.g. why do I press Tab?")
        self.question.returnPressed.connect(self.ask_question)
        self.question_button = QPushButton("Ask")
        self.question_button.clicked.connect(self.ask_question)
        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.back_button = QPushButton("Back")
        self.ask_button = QPushButton("Ask about this tutorial")
        self.prereq_button = QPushButton("Before you start")
        self.prereq_button.setCheckable(True)
        self.prereq_button.setToolTip("What this tutorial assumes you already have.")
        self.ask_button.clicked.connect(lambda: self.tutorial_id is not None and self.ask_about.emit(self.tutorial_id))
        self.start_button.clicked.connect(lambda: self._advance(self.engine.start))
        self.done_button.clicked.connect(lambda: self._advance(self.engine.complete))
        self.skip_button.clicked.connect(lambda: self._advance(self.engine.skip))
        self.prev_button.clicked.connect(self._previous)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.goto_button.clicked.connect(self._goto_viewed)
        self.unview_button.clicked.connect(self._unview)
        self.prereq_button.toggled.connect(lambda _on: self.refresh() if self.engine is not None else None)
        self.back_button.clicked.connect(self._leave)
        self.steps_list = StepList()
        self.steps_list.chosen.connect(self._view)
        self.prereq_label = QLabel("")
        self.prereq_label.setWordWrap(True)
        self.prereq_label.setTextFormat(Qt.TextFormat.RichText)
        content = QWidget()                                       # the page scrolls as a whole, so nothing is squeezed on a short window
        grid = page_grid(content)
        head = Head()
        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(self.back_button)
        head.body.addLayout(top)
        self.step_tile = step_tile = HeroTile(padding=26)
        self.step_pill = pill("Your current step")
        step_tile.body.addWidget(self.step_pill, 0, Qt.AlignmentFlag.AlignLeft)
        step_tile.body.addWidget(self.step_text)
        step_tile.body.addWidget(self.detail, 1)
        step_tile.body.addWidget(self.video_button, 0, Qt.AlignmentFlag.AlignLeft)
        view_row = QHBoxLayout()
        view_row.addWidget(self.goto_button)
        view_row.addWidget(self.unview_button)
        view_row.addStretch()
        step_tile.body.addLayout(view_row)
        self.prereq_tile = Tile("Before you start", variant="amber")
        self.prereq_tile.body.addWidget(self.prereq_label)
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
        row3 = QHBoxLayout()
        row3.addWidget(self.pause_button)
        row3.addWidget(self.prereq_button)
        controls.body.addLayout(row1)
        controls.body.addLayout(row2)
        controls.body.addLayout(row3)
        controls.body.addWidget(self.ask_button)
        controls.body.addStretch()
        guide = Tile("On your screen", variant="slate")
        self.about_guide = QLabel("While it is watching, GuideWire highlights the next thing to click, says what it sees, and completes a step only when the application shows it done.")
        self.about_guide.setObjectName("tileHint")
        self.about_guide.setWordWrap(True)
        guide.body.addWidget(self.about_guide)
        guide.body.addWidget(self.watch_box)
        guide.body.addWidget(self.panel_box)
        guide.body.addWidget(self.watch_label)
        guide.body.addWidget(self.cover_label)
        guide.body.addWidget(self.side_button)
        guide.body.addWidget(self.status)
        guide.body.addStretch()
        steps_tile = Tile("All steps")
        steps_tile.setMinimumWidth(320)
        self.steps_hint = QLabel("The step you are on is highlighted. Click any step to read it without moving.")
        self.steps_hint.setObjectName("tileHint")
        self.steps_hint.setWordWrap(True)
        steps_tile.body.addWidget(self.steps_hint)
        steps_tile.body.addWidget(self.steps_list, 1)
        grid.addWidget(head, 0, 0, 1, 3)
        grid.addWidget(step_tile, 1, 0, 1, 2)
        grid.addWidget(self.prereq_tile, 2, 0, 1, 2)
        grid.addWidget(progress_tile, 3, 0)
        grid.addWidget(controls, 3, 1)
        grid.addWidget(guide, 4, 0, 1, 2)
        grid.addWidget(steps_tile, 1, 2, 4, 1)
        self.question_tile = Tile("Ask about this step")
        q_row = QHBoxLayout()
        q_row.addWidget(self.question, 1)
        q_row.addWidget(self.question_button)
        self.question_tile.body.addLayout(q_row)
        self.question_tile.body.addWidget(self.answer, 1)
        grid.addWidget(self.question_tile, 5, 0, 1, 3)
        self._grid, self._steps_tile, self._narrow = grid, steps_tile, False
        self._main_tiles, self._pair = (step_tile, self.prereq_tile, guide), (progress_tile, controls)
        self.step_tile.setMinimumHeight(210)
        self.steps_list.setMinimumHeight(360)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 4)
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)           # the tiles hold unwrappable text (checkboxes, buttons): on a computer whose fonts are wide, sideways scrolling keeps all of it reachable
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.scroll = scroll

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._arrange(self.width() < self._width_for_side_by_side())

    def _width_for_side_by_side(self) -> int:
        """The window width at which the list of steps fits BESIDE the other tiles: what those tiles need at least, plus the list's own width, the gaps, the page margins and a scroll bar. It follows the real
        minimum sizes (fonts, theme, scaling), so no fixed number is ever too small for some computer."""
        from .bento import GAP, MARGIN
        main = max(max(t.minimumSizeHint().width() for t in self._main_tiles), sum(t.minimumSizeHint().width() for t in self._pair) + GAP)
        return main + self._steps_tile.minimumWidth() + GAP + 2 * MARGIN + 24

    def _arrange(self, narrow: bool) -> None:
        """Beside the other tiles on a wide window, below them (full width) on a narrow one, so the page never needs to scroll sideways."""
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self._grid.removeWidget(self._steps_tile)
        if narrow:
            self._grid.addWidget(self._steps_tile, 5, 0, 1, 3)
            self._grid.addWidget(self.question_tile, 6, 0, 1, 3)       # the question box goes below the steps list
            self._grid.setColumnStretch(2, 0)
        else:
            self._grid.addWidget(self._steps_tile, 1, 2, 4, 1)
            self._grid.addWidget(self.question_tile, 5, 0, 1, 3)
            self._grid.setColumnStretch(2, 4)

    # ---- screen guidance
    def set_bridge(self, bridge) -> None:
        self.bridge = bridge
        self.watch_box.setVisible(bridge is not None and bridge.available)
        self.panel_box.setVisible(bridge is not None and bridge.available)
        self._sync_timer()

    @property
    def watching(self) -> bool:
        return (self.bridge is not None and self.bridge.available and self.watch_box.isChecked() and self.engine is not None and self.engine.state == ACTIVE)

    @property
    def looking(self) -> bool:
        """Watching AND not paused: the screen is read, the highlight drawn and a step may be completed by what is seen."""
        return self.watching and not self.paused

    def _sync_timer(self) -> None:
        if self.looking and not self.sync and (self.isVisible() or self._minimized()):
            if not self.timer.isActive():
                self.timer.start()
                self.track_timer.start()
                self._background(True)
        else:
            self.timer.stop()
            self.track_timer.stop()
            self._background(False)
            if not self.watching:
                self.guide.clear()
                self.watch_label.setText(self._off_text())
                self.cover_label.setVisible(False)
                self.side_button.setVisible(False)
                if self.panel is not None:
                    self.panel.hide()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._window_minimized = False
        self._sync_timer()

    def set_window_minimized(self, on: bool) -> None:
        """The main window was minimized or restored. A minimized GuideWire keeps watching: the small guide box stays on screen."""
        self._window_minimized = on
        self._sync_timer()

    def _minimized(self) -> bool:
        return self._window_minimized

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        if self._minimized():
            return                                           # GuideWire minimized on purpose: the small guide and the highlight stay and keep watching
        self.pause_if_active()
        self.timer.stop()
        self.track_timer.stop()
        self.guide.clear()
        if self.panel is not None:
            self.panel.hide()

    def close_guides(self) -> None:
        """The overlay and the instruction box must not outlive the window."""
        self.timer.stop()
        self.track_timer.stop()
        self.guide.close()
        if self.panel is not None:
            self.panel.close()
            self.panel = None

    def stop_guidance(self) -> None:
        """Leave the screen clean (leaving the session, closing the app)."""
        self.timer.stop()
        self.track_timer.stop()
        self.guide.clear()
        if self.panel is not None:
            self.panel.hide()

    # ---- the instruction box
    def _ensure_panel(self) -> InstructionPanel:
        if self.panel is None:
            self.panel = InstructionPanel()
            self.panel.done_clicked.connect(lambda: self._advance(self.engine.complete))
            self.panel.skip_clicked.connect(lambda: self._advance(self.engine.skip))
            self.panel.back_clicked.connect(self._previous)
            self.panel.pause_clicked.connect(self.toggle_pause)
            self.panel.closed.connect(self._panel_closed)
        return self.panel

    def _panel_closed(self) -> None:
        step = None if self.engine is None else self.engine.current_step()
        self._dismissed_step = None if step is None else step.id            # closed for THIS step; the next step shows it again

    def _refresh_panel(self) -> None:
        e = self.engine
        step = None if e is None else e.current_step()
        if not (self.watching and self.panel_box.isChecked() and step is not None and step.id != self._dismissed_step):
            if self.panel is not None:
                self.panel.hide()
            return
        p = self._ensure_panel()
        p.set_content(f"GuideWire · step {e.position} of {len(e.steps)}", step.goal, [h.text for h in step.how_to], "Paused: press Resume to continue." if self.paused else self._last_hint, () if self.paused else self._last_keys)
        p.set_paused(self.paused)
        screen = self.window().screen()
        if screen is None:
            return
        a = screen.availableGeometry()
        x, y, _where = panel_position(self._last_window, (a.x(), a.y(), a.width(), a.height()), (p.width(), p.height()), self.window().devicePixelRatioF())
        p.put(x, y)

    def _background(self, on: bool) -> None:
        """While watching, GuideWire runs below normal priority so the application it watches is never slowed by it, and nothing in its own window drifts (each repaint is CPU)."""
        from .bento import set_calm
        set_calm(on)
        try:
            from vision import winplatform
            winplatform.set_background_priority(on)
        except Exception:
            pass

    def _pace(self) -> None:
        """How often to look at the screen. A look costs a capture of the application's window, so while the learner works (they moved the mouse or pressed a key in the last two seconds) it is
        looked at every 0.4 s, and while they read or are away, every 1.5 s. The first input after a quiet spell brings a look at once, so a menu they just opened is seen straight away."""
        try:
            from vision import winplatform
            idle = winplatform.idle_seconds()
        except Exception:
            return
        if idle is None:
            return
        want = self.LOOK_ACTIVE_MS if idle < self.IDLE_AFTER_S else self.LOOK_IDLE_MS
        if want != self.timer.interval():
            self.timer.setInterval(want)
            if want == self.LOOK_ACTIVE_MS:
                QTimer.singleShot(150, self.poll)

    def _track(self) -> None:
        """Follow the application window between looks: a move carries the highlight along at once; a resize clears it and asks for a new look."""
        if not self.looking or self.bridge is None:
            return
        self._pace()
        window = self.bridge.window_rect(self._app)
        change = self.guide.follow_window(window)
        if change in ("moved", "resized", "found"):
            self._last_window = window
            self._refresh_panel()
            if change == "resized":
                self.poll()

    def poll(self) -> None:
        """One look at the screen for the active step. The look runs off the window's thread; the judging (the database) stays on it."""
        if not self.looking or self._busy:
            return
        step = self.engine.current_step()
        if step is None:
            return
        app = self._app
        self._busy = True
        run_call(self, lambda _s: self.bridge.look(step, app), lambda look, sid=step.id: self._looked(look, sid), sync=self.sync)

    def _looked(self, look, step_id: str) -> None:
        self._busy = False
        if self.paused:                                        # the learner paused while the screen was being read: that look must not highlight or complete anything
            return
        if isinstance(look, Exception):
            self.watch_label.setText(f"Screen guidance hit a problem ({type(look).__name__}); use Done when you have finished the step.")
            self.guide.clear()
            return
        e = self.engine
        step = None if e is None else e.current_step()
        if step is None or step.id != step_id:                 # the learner moved on while the screen was being read: that look is for a step that is gone; look at the new one now
            if self.watching:
                self.poll()
            return
        tick = self.bridge.apply(e, look)
        self.watch_label.setText(tick.message)
        self._last_window, self._last_hint, self._last_keys = look.window_rect, tick.hint, tick.keys
        if tick.rect is not None:
            self.guide.show(tick.rect, look.window_rect)           # a box only: text drawn over the application is read back by the OCR (see docs/vision_integration.md)
        else:
            self.guide.clear()
        self._warn_if_covering(look.window_rect)
        self._check_prerequisites(look.observed)
        self._refresh_panel()
        if tick.advanced:
            self.status.setText(tick.message)
            self.viewing = None
            self.refresh()

    def _on_step_change(self, step) -> None:
        """One step, one guide: when the step changes, the previous step's highlight, hint, keys and animation are cleared in the same call that shows the new goal. Nothing of the old step can
        stay under the new one while the first look of the new step is being read."""
        sid = None if step is None else step.id
        if sid == self._shown_step:
            return
        self._shown_step = sid
        self._last_hint, self._last_keys = "", ()
        self.guide.clear()
        self.watch_label.setText(self._paused_text() if (sid is not None and self.paused) else "Looking at the screen..." if (sid is not None and self.watching) else self._off_text())

    def _paused_text(self) -> str:
        e = self.engine
        return f"Paused on step {e.position if e is not None and e.position else ''}: nothing is checked or highlighted. Press Resume when you want GuideWire to watch again.".replace("step :", "this step:")

    def _off_text(self) -> str:
        return "Screen guidance is off in your profile." if (self._profile_off and self.bridge is not None) else ""

    def _own_rect(self):
        w = self.window()
        g, r = w.frameGeometry(), w.devicePixelRatioF()
        return (round(g.x() * r), round(g.y() * r), round(g.width() * r), round(g.height() * r))

    def _warn_if_covering(self, window) -> None:
        covering = overlaps(self._own_rect(), window)
        self.cover_label.setVisible(covering)
        self.side_button.setVisible(self.watching)
        if covering:
            self.cover_label.setText("GuideWire is covering part of the application, so it cannot see everything. Minimize it: the small guide box stays on screen.")

    def minimize_to_guide(self) -> None:
        """Hide this window; the small guide box (draggable, resizable, minimizable) stays on top, so the application has the whole screen."""
        self._dismissed_step = None
        self._refresh_panel()
        self._window_minimized = True
        self.window().showMinimized()

    # ---- the session
    @property
    def tutorial_id(self) -> int | None:
        return None if self.engine is None else self.engine.db.get_session(self.engine.session_id)["tutorial_id"]

    # ---- the tutorial's video, and questions about the step
    def watch_video(self) -> None:
        """Open the tutorial's video at the moment this step is shown in it (in the web browser; GuideWire only opens a normal web link)."""
        url = self._video_url()
        if url:
            self.open_url(url)

    def _video_url(self) -> str | None:
        e = self.engine
        if e is None:
            return None
        pos = e.position or e.paused_at
        step = e.steps[pos - 1][1] if pos else None
        return watch_url(e.source_url, None if step is None else step.video_start_s)

    def ask_question(self) -> None:
        """Answer a question about the tutorial, knowing which step the learner is on. The AI model is only used if the learner allows it (Privacy)."""
        text = self.question.text().strip()
        e = self.engine
        if not text or e is None:
            return
        if self.asker is None or self.load_tutorial is None:
            self.answer.setText("Questions are not available on this computer.")
            return
        try:
            steps, title, url = self.load_tutorial(e.tutorial_id)
        except Exception:                                      # a tutorial that cannot be loaded must never take the window down (PyQt aborts on an exception in a slot)
            self.answer.setText("This tutorial could not be read for a question. Try the Ask screen from Home.")
            return
        pos = e.position or e.paused_at
        goal = e.steps[pos - 1][1].goal if pos else ""
        context = f"I am on step {pos} of this tutorial: {goal}. {text}" if pos else text
        use_model = bool(self.ai_allowed and self.asker.model_available)
        self.question_button.setEnabled(False)
        self.answer.setText("Thinking..." if use_model else "")
        app, asker = self._app, self.asker
        from .workers import run_call
        run_call(self, lambda _s: asker.ask(context, app, tutorial=steps, title=title, url=url, use_model=use_model), self._answered, sync=self.sync)

    def _answered(self, result) -> None:
        self.question_button.setEnabled(True)
        if isinstance(result, Exception):
            self.answer.setText(f"Sorry, that failed ({type(result).__name__}). Try again.")
            return
        self.answer.setText(result.text)
        self.question.clear()

    # ---- leaving never loses progress: the place is saved (the engine's paused state) and coming back continues from it
    def pause_if_active(self) -> None:
        """Leaving the session (Back, another screen, closing the app) saves the place: the session is paused where it is and coming back continues from that step."""
        e = self.engine
        if e is not None and e.state == ACTIVE:
            e.pause()

    def load(self, engine: SessionEngine, *, guidance: bool = True) -> None:
        """Open a session. `guidance` is the learner's profile preference ("Highlight the target on screen during a session"): when it is off the screen is not watched."""
        self.stop_guidance()
        self.engine = engine
        if engine.state == PAUSED:
            engine.resume()                                  # it was left here: carry on from exactly this step
        self.status.setText("")
        self._busy = False
        self._dismissed_step = None
        self._shown_step = None
        self._app = engine.app
        self.paused, self.viewing = False, None
        self.pause_button.setText("Pause")
        self.title.setText(f"Session: {engine.title}" if engine.title else "Session")
        self.prereqs = prerequisites([st for _, st in engine.steps], engine.app, engine.title)
        self.prereq_missing, self._prereq_checked = [], False
        self.prereq_button.blockSignals(True)
        self.prereq_button.setChecked(False)
        self.prereq_button.blockSignals(False)
        self.steps_list.set_steps([st.goal for _, st in engine.steps])
        self.watch_box.blockSignals(True)
        self.watch_box.setChecked(guidance)
        self.watch_box.blockSignals(False)
        self._profile_off = not guidance
        self.watch_label.setText(self._off_text())
        self.refresh()

    def _leave(self) -> None:
        self.stop_guidance()
        self.pause_if_active()
        self.back.emit()

    def _do(self, action) -> None:
        try:
            action()
        except EngineError as e:
            self.status.setText(str(e))
        else:
            self.status.setText("")
        self.viewing = None
        self.refresh()

    def _advance(self, action) -> None:
        """Start, Done or Skip: the learner is moving on, so a pause held on the step they were studying ends."""
        if self.paused:
            self.set_paused(False, refresh=False)
        self._do(action)

    # ---- pause, previous step, looking at a step
    def toggle_pause(self) -> None:
        self.set_paused(not self.paused)

    def set_paused(self, on: bool, refresh: bool = True) -> None:
        """Hold the session on this step (nothing looked at, drawn or completed) or let it watch again."""
        if on == self.paused:
            return
        self.paused = on
        self.pause_button.setText("Resume" if on else "Pause")
        if on:
            self._last_hint, self._last_keys = "", ()
            self.guide.clear()
            self.cover_label.setVisible(False)
            self.watch_label.setText(self._paused_text())
        else:
            self.watch_label.setText("Looking at the screen..." if self.watching else self._off_text())
        if refresh and self.engine is not None:
            self.refresh()
        if not on and not self.sync and self.looking:
            QTimer.singleShot(50, self.poll)                     # look at once: the learner may have changed the application while it was paused

    def _previous(self) -> None:
        """Back one step, and hold there: the step you went back to would otherwise be completed again at the next look whenever the application is already in the state it ends in (Pose Mode, say)."""
        e = self.engine
        if e is None:
            return
        self._do(e.back)
        if not self.status.text() and self.watching:
            self.set_paused(True, refresh=False)
            self.status.setText(f"Back on step {e.position}. GuideWire is paused so you can look at it: press Resume when you want it to watch again.")
            self.refresh()

    def _view(self, number: int) -> None:
        """Look at a step without moving the session."""
        e = self.engine
        if e is None or not 1 <= number <= len(e.steps):
            return
        self.viewing = None if (e.state == ACTIVE and number == e.position) else number
        self.refresh()

    def _unview(self) -> None:
        self.viewing = None
        if self.engine is not None:
            self.refresh()

    def _goto_viewed(self) -> None:
        e, n = self.engine, self.viewing
        if e is None or n is None or e.state != ACTIVE:
            return
        before = e.position or n
        if n > before and self.paused:
            self.set_paused(False, refresh=False)               # moving on
        self._do(lambda: e.jump_to(n))
        if not self.status.text():
            self.status.setText(f"Moved to step {n}.")
            if n < before and self.watching:
                self.set_paused(True, refresh=False)             # going back: hold there, as Previous step does
                self.refresh()

    # ---- what the tutorial assumes
    def _prereq_html(self) -> str:
        if not self.prereqs:
            return ""
        items = "".join(f"<li>{html.escape(p.text)}</li>" for p in self.prereqs)
        out = f"<p>This tutorial does not set these up for you. Have them ready before you start:</p><ul style='margin-left:8px; -qt-list-indent:0;'>{items}</ul>"
        if self.prereq_missing:
            what = "; ".join(p.text.split(".")[0] for p in self.prereq_missing)
            out += f"<p><b style='color:{current_palette()['warn']}'>GuideWire did not see this in your scene:</b> {html.escape(what)}. You can carry on, but later steps need it.</p>"
        return out

    def _check_prerequisites(self, observed) -> None:
        """Once per session, against the first state the application reports with a list of what is in the scene: what is missing is said, never enforced."""
        if self._prereq_checked or not self.prereqs or not observed or not observed.get("nodes"):
            return
        self._prereq_checked = True
        self.prereq_missing = unmet_prerequisites(self.prereqs, observed)
        if self.prereq_missing:
            self.refresh()

    @staticmethod
    def _detail_for(step, viewed: bool = False, mode: str | None = None) -> str:
        """What someone following the step needs: how to do it, how to tell it worked, and whether GuideWire can check it. The validator's notes (where a step's expected state came from, vocabulary warnings) are for the editor and stay on the Review screen."""
        parts: list[str] = []
        if step.why:
            parts.append("Why\n" + step.why)
        if step.how_to:
            parts.append("How to do it\n" + "\n".join(f"• {h.text}" for h in step.how_to))
        if step.check:
            parts.append("How you can tell it worked\n" + "\n".join(f"• {h.text}" for h in step.check))
        alts = key_alternatives.alternatives_of(step, mode)
        if alts:
            parts.append("Without the keyboard\n" + "\n".join(f"• {a.keys}: {a.text}" for a in alts))
        if step.common_mistakes:
            parts.append("Watch out\n" + "\n".join(f"• {m}" for m in step.common_mistakes))
        check = checkability(step)
        if check.level != "checkable":
            parts.append(check.full if viewed else f"{check.full} Press Done when you have finished it.")
        return "\n\n".join(parts)

    def refresh(self) -> None:
        e = self.engine
        assert e is not None
        if self.viewing is not None and (not 1 <= self.viewing <= len(e.steps) or (e.state == ACTIVE and self.viewing == e.position)):
            self.viewing = None
        done, total = e.progress()
        self.progress.setText(f"{done} of {total} steps done")
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        step = e.current_step()
        statuses = e.statuses()
        active = e.state == ACTIVE
        viewed = None if self.viewing is None else e.steps[self.viewing - 1][1]
        self.step_tile.set_watermark(str(self.viewing) if viewed is not None else (str(e.position) if active and e.position else ""))
        if viewed is not None:
            self.step_pill.setText(f"Looking at step {self.viewing}, not your current step")
            self.step_text.setText(f"<b>Step {self.viewing}:</b> {html.escape(viewed.goal)}")
            said = {"done": "You marked this step done.", "skipped": "You skipped this step.", "pending": "This step is still to do."}[statuses[self.viewing - 1]]
            self.detail.setText(said + "\n" + self._detail_for(viewed, True, key_alternatives.mode_for([s for _, s in e.steps], self.viewing - 1)))
        elif e.state == NOT_STARTED:
            self.step_pill.setText("Not started")
            self.step_text.setText("Check what this tutorial assumes, then press Start." if self.prereqs else "Press Start to begin.")
            self.detail.setText("")
        elif e.state == FINISHED:
            self.step_pill.setText("Finished")
            self.step_text.setText("Session finished. Well done!")
            self.detail.setText("")
        elif e.state == PAUSED:
            waiting = e.steps[(e.paused_at or 1) - 1][1]
            self.step_text.setText(f"<b>Paused at step {e.paused_at}:</b> {waiting.goal}")
            self.detail.setText("Your progress is saved. Press Resume to continue from this step.")
        else:
            self.step_pill.setText("Your current step" + (" (paused)" if self.paused else ""))
            self.step_text.setText(f"<b>Step {e.position}:</b> {html.escape(step.goal)}")
            self.detail.setText(self._detail_for(step, False, key_alternatives.mode_for([s for _, s in e.steps], (e.position or 1) - 1)))
        self.steps_list.show_state(statuses, e.position if active else None, self.viewing)
        self.goto_button.setVisible(viewed is not None and active)
        self.unview_button.setVisible(viewed is not None)
        self.prereq_button.setVisible(bool(self.prereqs) and e.state != NOT_STARTED)
        self.prereq_tile.setVisible(bool(self.prereqs) and (e.state == NOT_STARTED or self.prereq_button.isChecked() or bool(self.prereq_missing)))
        self.prereq_label.setText(self._prereq_html())
        self._on_step_change(step)
        self.start_button.setEnabled(e.state == NOT_STARTED)
        self.done_button.setEnabled(active)
        self.skip_button.setEnabled(active)
        self.prev_button.setEnabled(active and (e.position or 1) > 1)
        self.pause_button.setEnabled(active and (self.paused or self.watching))
        self.pause_button.setToolTip(self.PAUSE_TIP if self.pause_button.isEnabled() or not active else "Pausing holds GuideWire's watching. It is not watching your screen now, so the step already waits for you.")
        self.video_button.setVisible(e.state == ACTIVE and self._video_url() is not None)
        self.question_button.setEnabled(True)
        self._sync_timer()
        self._refresh_panel()


class HistoryScreen(QWidget):
    """The user's past and current sessions, newest first. A session can be used again: start the same tutorial from the beginning, continue one that was not finished, or look at its steps."""
    back = pyqtSignal()
    start_again = pyqtSignal(int)      # tutorial id
    resume = pyqtSignal(int)           # session id
    review = pyqtSignal(int)           # tutorial id

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self.list = QListWidget()
        tidy_list(self.list)
        self.empty = QLabel("")
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back.emit)
        self.empty.setObjectName("empty")
        self.again_button = QPushButton("Start again")
        self.again_button.setObjectName("primary")
        self.resume_button = QPushButton("Continue where I left off")
        self.review_button = QPushButton("Review steps")
        self.again_button.clicked.connect(lambda: self._emit(self.start_again, "tutorial_id"))
        self.resume_button.clicked.connect(lambda: self._emit(self.resume, "id"))
        self.review_button.clicked.connect(lambda: self._emit(self.review, "tutorial_id"))
        self.list.currentRowChanged.connect(lambda _r: self._buttons())
        self.list.itemDoubleClicked.connect(lambda _i: self._emit(self.start_again, "tutorial_id"))
        grid = page_grid(self)
        grid.addWidget(header("History", "Every session you have started, newest first. Pick one to use it again.", back=self.back_button, kicker="Your sessions"), 0, 0)
        box = Tile("Sessions")
        box.body.addWidget(self.empty)
        box.body.addWidget(self.list, 1)
        row = QHBoxLayout()
        for b in (self.again_button, self.resume_button, self.review_button):
            row.addWidget(b)
        row.addStretch()
        box.body.addLayout(row)
        grid.addWidget(box, 1, 0)
        grid.setRowStretch(1, 1)
        self._buttons()

    @staticmethod
    def describe(row: dict) -> str:
        state = {"not_started": "not started", "active": "in progress", "paused": "paused", "finished": "finished"}.get(row["state"], row["state"])
        when = (row["finished_at"] or row["started_at"] or "")[:16].replace("T", " ")
        return f"{row['title']} - {state} - {row['dealt']}/{row['total']} steps" + (f" - {when}" if when else "")

    def selected(self) -> dict | None:
        i = self.list.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def _buttons(self) -> None:
        row = self.selected()
        self.again_button.setEnabled(row is not None)
        self.review_button.setEnabled(row is not None)
        self.resume_button.setEnabled(row is not None and row["state"] in ("active", "paused"))

    def _emit(self, signal, key: str) -> None:
        row = self.selected()
        if row is not None:
            signal.emit(int(row[key]))

    def load(self, rows: list[dict]) -> None:
        self.rows = rows
        self.list.clear()
        self.empty.setText("" if rows else "No sessions yet. Start one from Home.")
        for r in rows:
            self.list.addItem(self.describe(r))
        if rows:
            self.list.setCurrentRow(0)
        self._buttons()


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
        grid.addWidget(header("Profile", "Your name, how the app looks, and your password.", back=self.back_button, kicker="Settings"), 0, 0, 1, 2)
        me = HeroTile("About you")
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
        self.ai_allowed = True        # the learner's Privacy choice: when off, nothing is sent to the AI model
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
        grid.addWidget(header("New tutorial", "Turn instructions, a transcript or a YouTube link into steps you can review.", back=self.back_button, kicker="Create"), 0, 0, 1, 2)
        details = HeroTile("Details")
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
        paste.body.addWidget(self.message)
        paste.body.addWidget(self.notes)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.create_button)
        paste.body.addLayout(actions)
        grid.addWidget(details, 1, 0)
        grid.addWidget(tips, 1, 1)
        grid.addWidget(paste, 2, 0, 1, 2)
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
        if link and not self.ai_allowed:
            self.message.setText("The AI model is turned off in Privacy, so a video link cannot be turned into steps. Paste the instructions as text instead, or turn it on in Privacy.")
            return
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
