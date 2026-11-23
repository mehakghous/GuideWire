"""Ask GuideWire: a chat, the way an AI assistant's chat looks.

A conversation list on the left (New chat, and every earlier chat, saved in the database so you can come back to it), the conversation in the middle as bubbles, a composer at the bottom, and, on an empty
chat, a greeting with things to try. What the chat is about is set with small toggles in its top bar: the application (Blender, Maya or Houdini), the tutorial it is about, and whether the AI model is used.

When an answer is a list of steps (a starter plan, the steps for a topic) it comes as a card inside the chat: save it as a tutorial, save it and start a session on it at once, or map the same question
onto another application (Blender, Maya, Houdini) and get that application's steps.

When the assistant recommends tutorials, each one is a card with a clickable title, its creator, length, publication date and link, and its own "Turn into steps" button. Turning one into steps runs
in the background with its status shown on the card; the result is saved as a normal tutorial (the ones Home lists), becomes what the chat is about, and can be asked about at once. A failed one says
why and offers Retry. What the chat remembers (the videos, the picked one, the guide) is kept with the chat, so opening it again later finds it as it was.

Wraps `app.ask.Asker`; the conversations live in `app.db` (`conversation`, `chat_message`).
"""
from __future__ import annotations

import html

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from shared.step_record import StepList

from ..ask import Asker
from ..chat_context import ChatContext, Video
from ..pipeline import APPS
from .bento import Tile, page_grid
from .workers import run_call

SUGGESTIONS = (
    "Where do I start rigging in {app}?",
    "Give me the steps to bind the mesh",
    "My knee flips when I move the IK handle",
    "What should I do before rigging?",
)
APP_LABELS = {"blender": "Blender", "maya": "Maya", "houdini": "Houdini"}
BUBBLE_WIDTH = 620


def _label(text: str, name: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if name:
        lab.setObjectName(name)
    return lab


def retarget(question: str, app: str) -> str:
    """The same question for another application: "where do i start rigging in maya" -> "where do i start rigging in Blender". A question that names no application gets "in <app>" added."""
    import re
    label = APP_LABELS.get(app, app)
    names = re.compile(r"\b(" + "|".join(APPS) + r")\b", re.I)
    if names.search(question):
        return names.sub(label, question)
    return f"{question.rstrip(' ?.!')} in {label}"


def _discard(widget: QWidget) -> None:
    """Take a widget off the screen now (a deferred delete alone leaves it showing until the event loop gets to it)."""
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


class Composer(QPlainTextEdit):
    """The message box: Enter sends, Shift+Enter starts a new line, and it grows with what is typed (up to a few lines)."""
    submitted = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("composerEdit")
        self.setPlaceholderText("Ask about a tool, a step or a whole workflow...")
        self.setTabChangesFocus(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().contentsChanged.connect(self._fit)
        self._fit()

    def _fit(self) -> None:
        line = max(self.fontMetrics().lineSpacing(), 1)
        lines = max(1, min(5, round(self.document().size().height() / line)))
        self.setFixedHeight(lines * line + 22)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if lines < 5 else Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class VideoCard(QFrame):
    """One recommended tutorial inside the chat: a clickable title, who made it, how long it is, when it was published, its link, and what can be done with it. The one action that matters, Turn into
    steps, is on the card, so it is clear which video it is for (it is not a button on every message)."""
    turn_into_steps = pyqtSignal(str)          # the video's key
    pick = pyqtSignal(str)
    review = pyqtSignal(int)                   # the saved tutorial's id
    start_session = pyqtSignal(int)

    def __init__(self, video: Video, number: int):
        super().__init__()
        self.setObjectName("card")
        self.setMinimumWidth(480)
        self.key = video.key
        self.video = video
        self.tutorial_id: int | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(4)
        self.title = _label("", "cardTitle")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.title.setOpenExternalLinks(True)                       # a click opens the video in the browser
        self.title.setText(f"{number}. <a href=\"{html.escape(video.url, quote=True)}\">{html.escape(video.title)}</a>")
        self.meta = _label(video.details(), "cardMeta")
        self.link = _label(video.url, "cardMeta")
        self.status = _label("", "hint")
        box.addWidget(self.title)
        box.addWidget(self.meta)
        box.addWidget(self.link)
        box.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.steps_button = QPushButton("Turn into steps")
        self.steps_button.setObjectName("primary")
        self.retry_button = QPushButton("Retry")
        self.pick_button = QPushButton("Pick this one")
        self.pick_button.setObjectName("chip")
        self.review_button = QPushButton("Review steps")
        self.session_button = QPushButton("Start session")
        self.session_button.setObjectName("primary")
        self.steps_button.clicked.connect(lambda _=False: self.turn_into_steps.emit(self.key))
        self.retry_button.clicked.connect(lambda _=False: self.turn_into_steps.emit(self.key))
        self.pick_button.clicked.connect(lambda _=False: self.pick.emit(self.key))
        self.review_button.clicked.connect(lambda _=False: self.review.emit(int(self.tutorial_id or 0)))
        self.session_button.clicked.connect(lambda _=False: self.start_session.emit(int(self.tutorial_id or 0)))
        for b in (self.steps_button, self.retry_button, self.review_button, self.session_button, self.pick_button):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        row.addStretch()
        box.addLayout(row)
        self.refresh(video, False)

    def refresh(self, video: Video, focused: bool) -> None:
        """Show the video's state: new, being read, failed (with why, and Retry), or done (with its saved tutorial)."""
        self.video = video
        self.tutorial_id = video.tutorial_id
        st = video.status
        self.setProperty("selected", bool(focused))
        self.style().unpolish(self)
        self.style().polish(self)
        self.steps_button.setVisible(st == "new")
        self.retry_button.setVisible(st == "failed")
        self.pick_button.setVisible(st in ("new", "failed") and not focused)
        saved = st == "done" and video.tutorial_id is not None
        self.review_button.setVisible(saved)
        self.session_button.setVisible(saved)
        self.status.setText({"new": "Picked: say \"turn it into steps\" or press the button." if focused else "",
                             "processing": "Turning this video into steps... this can take a minute or two.",
                             "failed": f"Could not make steps: {video.error}" if video.error else "Could not make steps.",
                             "done": ("Steps ready and saved as a tutorial." if saved else "Steps ready.")}.get(st, ""))
        self.status.setVisible(bool(self.status.text()))

    def set_working(self) -> None:
        self.steps_button.setVisible(False)
        self.retry_button.setVisible(False)
        self.pick_button.setVisible(False)
        self.status.setText("Turning this video into steps... this can take a minute or two.")
        self.status.setVisible(True)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))


class StepsCard(QFrame):
    """The steps an answer gave, inside the chat: what they are, and what can be done with them."""
    save = pyqtSignal()
    save_and_start = pyqtSignal()
    start = pyqtSignal()
    review = pyqtSignal()
    map_to = pyqtSignal(str)

    def __init__(self, steps: StepList, app: str, saved_tutorial: int | None = None, mapping: bool = True):
        super().__init__()
        self.setObjectName("stepsCard")
        self.setMinimumWidth(480)
        self.steps = steps
        self.tutorial_id: int | None = saved_tutorial
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(8)
        n = len(steps.steps)
        title = _label(f"<b>{n} steps</b> for {APP_LABELS.get(app, app)}" + (f" &middot; {steps.title}" if steps.title else ""))
        box.addWidget(title)
        self.hint = _label("Save them as a tutorial to review every step and run a guided session on them.")
        box.addWidget(self.hint)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.save_button = QPushButton("Save as tutorial")
        self.start_button = QPushButton("Save and start session")
        self.start_button.setObjectName("primary")
        self.open_button = QPushButton("Start session")
        self.open_button.setObjectName("primary")
        self.review_button = QPushButton("Review steps")
        self.save_button.clicked.connect(self.save)
        self.start_button.clicked.connect(self.save_and_start)
        self.open_button.clicked.connect(self.start)
        self.review_button.clicked.connect(self.review)
        for b in (self.save_button, self.start_button, self.open_button, self.review_button):
            row.addWidget(b)
        row.addStretch()
        box.addLayout(row)
        self.saved_label = _label("")
        box.addWidget(self.saved_label)
        map_row = QHBoxLayout()
        map_row.setSpacing(6)
        map_label = _label("Map the same question onto:")
        map_label.setWordWrap(False)
        map_row.addWidget(map_label)
        self.map_buttons: dict[str, QPushButton] = {}
        for a in (APPS if mapping else ()):                       # a guide made from one video is for that video's application: mapping it onto another one makes no sense
            if a == app:
                continue
            b = QPushButton(APP_LABELS.get(a, a))
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=a: self.map_to.emit(a))
            map_row.addWidget(b)
            self.map_buttons[a] = b
        map_row.addStretch()
        if mapping:
            box.addLayout(map_row)
        self.set_saved(saved_tutorial)

    def set_saved(self, tutorial_id: int | None, title: str = "") -> None:
        self.tutorial_id = tutorial_id
        done = tutorial_id is not None
        self.save_button.setVisible(not done)
        self.start_button.setVisible(not done)
        self.open_button.setVisible(done)
        self.review_button.setVisible(done)
        self.hint.setText("Review every step, or run a guided session on them." if done else "Save them as a tutorial to review every step and run a guided session on them.")
        self.saved_label.setText((f"Saved as \"{title}\"." if title else "Saved as a tutorial.") if done else "")
        self.saved_label.setVisible(done)


class AskScreen(QWidget):
    back = pyqtSignal()
    save_steps = pyqtSignal(object, str)           # StepList, a title
    save_and_start = pyqtSignal(object, str)       # the same, and then open a session on it
    start_session = pyqtSignal(int)                # an already saved tutorial
    review_tutorial = pyqtSignal(int)              # open a saved tutorial's steps (the review screen)
    save_guide = pyqtSignal(object, str, str)      # the steps made from a video in the chat, a title, the video's link: the main window saves them as a tutorial

    def __init__(self, asker: Asker | None = None, sync: bool = False):
        super().__init__()
        self.asker = asker or Asker()
        self.sync = sync                            # tests run the call inline
        self.db = None
        self.user_id: int | None = None
        self.load_tutorial = None                   # set by the main window: tid -> (StepList, title, url)
        self.find_saved = None                      # set by the main window: video link -> (StepList, title, tutorial id) of a tutorial already made from it, or None
        self.last_steps: StepList | None = None
        self.conversation_id: int | None = None
        self._cards: list[tuple[StepsCard, int | None, str]] = []          # (card, the chat message it belongs to, the question it answered)
        self._card_saving: StepsCard | None = None
        self._thinking: QWidget | None = None
        self._video_cards: dict[str, VideoCard] = {}
        self._last_bot_message: int | None = None
        self._messages: list[tuple[str, str]] = []                          # (who, text) shown now: what tests and "copy" read
        # ---- the toggles (small things to change, like a model picker)
        self.app = QComboBox()                      # the state of the application toggle; the chips drive it
        self.app.addItems(APPS)
        self.app.hide()
        self.app_button = QToolButton()
        self.app_button.setObjectName("picker")
        self.app_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.app_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.app_button.setToolTip("Which application the steps are for")
        self.app_menu = QMenu(self.app_button)
        self.app_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for a in APPS:
            act = QAction(APP_LABELS.get(a, a), self.app_menu, checkable=True)
            act.triggered.connect(lambda _=False, a=a: self.app.setCurrentText(a))
            group.addAction(act)
            self.app_menu.addAction(act)
            self.app_actions[a] = act
        self.app_button.setMenu(self.app_menu)
        self._sync_app_picker()
        self.app.currentTextChanged.connect(self._app_changed)
        self.tutorial = QComboBox()
        self.tutorial.addItem("General question", None)
        self.tutorial.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.tutorial.setToolTip("Pick one of your tutorials and the chat is about its steps: \"what is he doing at 1:30\", \"what's next\", \"go back to ...\"")
        self.tutorial.currentIndexChanged.connect(lambda _i: self._tutorial_changed())
        self.tutorial.hide()
        self.about_button = QToolButton()
        self.about_button.setObjectName("picker")
        self.about_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.setToolTip("What the chat is about: a general question, or one of your tutorials (then \"what is he doing at 1:30\", \"what's next\" work on its steps)")
        self.about_menu = QMenu(self.about_button)
        self.about_button.setMenu(self.about_menu)
        self._sync_about_picker()
        self.use_model = QPushButton("AI answers")
        self.use_model.setObjectName("chip")
        self.use_model.setCheckable(True)
        self.use_model.setEnabled(self.asker.model_available)
        self.use_model.setChecked(self.asker.model_available)
        self.use_model.setToolTip("A fuller answer from the AI (about a tenth of a cent). Without it the answer comes from GuideWire's own knowledge base and rules.")
        self.use_model.clicked.connect(lambda _=False: self.asker.reset())
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("linkButton")
        self.back_button.clicked.connect(self.back.emit)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        # ---- the conversation list (history)
        self.new_chat_button = QPushButton("+  New chat")
        self.new_chat_button.setObjectName("primary")
        self.new_chat_button.clicked.connect(self.new_chat)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.chat_list.itemClicked.connect(self._open_item)
        self.delete_chat_button = QPushButton("Delete this chat")
        self.delete_chat_button.setObjectName("linkButton")
        self.delete_chat_button.clicked.connect(self.delete_chat)
        self.no_chats = QLabel("Your chats show up here, so you can come back to them.")
        self.no_chats.setObjectName("hint")
        self.no_chats.setWordWrap(True)
        # ---- the messages
        self.messages = QVBoxLayout()
        self.messages.setSpacing(12)
        self.messages.setContentsMargins(6, 6, 6, 6)
        holder = QWidget()
        holder_box = QVBoxLayout(holder)
        holder_box.setContentsMargins(0, 0, 0, 0)
        self.welcome = self._build_welcome()
        holder_box.addWidget(self.welcome)
        holder_box.addLayout(self.messages)
        holder_box.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("chatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(holder)
        # ---- the composer
        self.composer = Composer()
        self.composer.submitted.connect(self.submit)
        self.send_button = QPushButton("↑")
        self.send_button.setObjectName("send")
        self.send_button.setToolTip("Send (Enter)")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self.submit)
        bar = QFrame()
        bar.setObjectName("composer")
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(12, 6, 8, 6)
        bar_row.addWidget(self.composer, 1)
        bar_row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        # ---- layout
        grid = page_grid(self)
        side = Tile(padding=14)
        side.setFixedWidth(250)
        side.body.addWidget(self.new_chat_button)
        side.body.addWidget(self.no_chats)
        side.body.addWidget(self.chat_list, 1)
        side.body.addWidget(self.delete_chat_button, 0, Qt.AlignmentFlag.AlignLeft)
        main = Tile(padding=16)
        self.title = QLabel("New chat")
        self.title.setObjectName("tileTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)         # a long title is cut, it never widens the window
        self.title.setMinimumWidth(60)
        self.title.setStyleSheet("font-size: 13pt;")
        head = QHBoxLayout()
        head.addWidget(self.title, 1)
        head.addWidget(self.back_button)
        main.body.addLayout(head)
        main.body.addWidget(self.scroll, 1)
        main.body.addWidget(self.status)
        main.body.addWidget(bar)
        picks = QHBoxLayout()                       # below the text box, where an AI chat keeps its model picker
        picks.setContentsMargins(10, 0, 10, 0)
        picks.setSpacing(6)
        picks.addWidget(self.about_button)
        picks.addStretch(1)
        self.use_model.setVisible(False)            # no with/without choice: the normal flow uses the AI whenever it is available
        picks.addWidget(self.app_button)
        main.body.addLayout(picks)
        grid.addWidget(side, 0, 0)
        grid.addWidget(main, 0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)

    # ---- the empty chat
    def _build_welcome(self) -> QWidget:
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(20, 36, 20, 10)
        box.setSpacing(14)
        self.greeting = QLabel("What do you want to learn today?")
        self.greeting.setObjectName("greet")
        self.greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Ask a question, or ask for the steps and map them onto Blender, Maya or Houdini.")
        sub.setObjectName("hint")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try_label = QLabel("Try asking")
        try_label.setObjectName("who")
        try_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.greeting)
        box.addWidget(sub)
        box.addSpacing(10)
        box.addWidget(try_label)
        self.suggest_grid = QGridLayout()
        self.suggest_grid.setSpacing(10)
        box.addLayout(self.suggest_grid)
        self.suggest_buttons: list[QPushButton] = []
        self._fill_suggestions()
        return w

    def _fill_suggestions(self) -> None:
        for b in self.suggest_buttons:
            self.suggest_grid.removeWidget(b)
            b.deleteLater()
        self.suggest_buttons = []
        for i, text in enumerate(SUGGESTIONS):
            q = text.format(app=APP_LABELS.get(self.app.currentText(), self.app.currentText()))
            b = QPushButton(q)
            b.setObjectName("suggest")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, q=q: self.send(q))
            self.suggest_grid.addWidget(b, i // 2, i % 2)
            self.suggest_buttons.append(b)

    # ---- who is signed in, and what they can ask about
    def set_user(self, db, user_id: int) -> None:
        self.db, self.user_id = db, user_id
        self.refresh_chats()

    def set_tutorials(self, rows: list[tuple[int, str]], select: int | None = None) -> None:
        """The tutorials a chat can be about. Opening the screen starts a new chat (about `select` when given)."""
        self.tutorial.blockSignals(True)
        self.tutorial.clear()
        self.tutorial.addItem("General question", None)
        for tid, title in rows:
            self.tutorial.addItem(title, tid)
        idx = next((i for i in range(self.tutorial.count()) if select is not None and self.tutorial.itemData(i) == select), 0)
        self.tutorial.setCurrentIndex(idx)
        self.tutorial.blockSignals(False)
        self._sync_about_picker()
        self.new_chat()

    def _sync_app_picker(self) -> None:
        app = self.app.currentText()
        if app in self.app_actions:
            self.app_actions[app].setChecked(True)
        self.app_button.setText(f"{APP_LABELS.get(app, app)}  ▾")

    def _sync_about_picker(self) -> None:
        """Rebuild the About menu from the tutorials the chat can be about (the hidden combo box is its state)."""
        self.about_menu.clear()
        group = QActionGroup(self.about_menu)
        group.setExclusive(True)
        for i in range(self.tutorial.count()):
            act = QAction(self.tutorial.itemText(i), self.about_menu, checkable=True)
            act.setChecked(i == self.tutorial.currentIndex())
            act.triggered.connect(lambda _=False, i=i: self.tutorial.setCurrentIndex(i))
            group.addAction(act)
            self.about_menu.addAction(act)
        name = self.tutorial.currentText() or "General question"
        short = name if len(name) <= 30 else name[:29] + "…"
        self.about_button.setText(f"About: {short}  ▾")

    def _app_changed(self, app: str) -> None:
        self._sync_app_picker()
        self._fill_suggestions()
        self.asker.reset()
        if self.conversation_id is not None and self.db is not None:
            self.db.update_conversation(self.conversation_id, app=app)

    def _tutorial_changed(self) -> None:
        self._sync_about_picker()
        self.asker.reset()
        if self.conversation_id is not None and self.db is not None:
            self.db.update_conversation(self.conversation_id, tutorial_id=self.tutorial.currentData())

    # ---- the list of chats
    def refresh_chats(self) -> None:
        self.chat_list.clear()
        rows: list = self.db.list_conversations(self.user_id) if self.db is not None and self.user_id is not None else []
        self.no_chats.setVisible(not rows)
        for r in rows:
            item = QListWidgetItem(r["title"])
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            item.setToolTip(f"{r['title']}\n{APP_LABELS.get(r['app'], r['app'])} - {r['messages']} messages")
            self.chat_list.addItem(item)
            if r["id"] == self.conversation_id:
                self.chat_list.setCurrentItem(item)
        self.delete_chat_button.setEnabled(self.conversation_id is not None)

    def _open_item(self, item: QListWidgetItem) -> None:
        self.open_chat(int(item.data(Qt.ItemDataRole.UserRole)))

    def new_chat(self) -> None:
        """An empty chat: the greeting and things to try. Nothing is stored until the first message."""
        self.asker.new_conversation()
        self.conversation_id = None
        self.last_steps = None
        self._clear_messages()
        self.title.setText("New chat")
        self.status.setText("")
        self.welcome.setVisible(True)
        self.chat_list.clearSelection()
        self.delete_chat_button.setEnabled(False)
        self.composer.setFocus()

    def open_chat(self, conversation_id: int) -> None:
        """Go back to an earlier chat: its messages, its steps cards (saved or not), and what it was about."""
        if self.db is None or self.user_id is None:
            return
        conv = self.db.get_conversation(self.user_id, conversation_id)
        if conv is None:
            return
        self.asker.new_conversation(self._restored_context(conversation_id))
        self.conversation_id = conversation_id
        self.last_steps = None
        self._clear_messages()
        self.welcome.setVisible(False)
        self.title.setText(conv["title"])
        self.tutorial.blockSignals(True)
        self.tutorial.setCurrentIndex(next((i for i in range(self.tutorial.count()) if self.tutorial.itemData(i) == conv["tutorial_id"]), 0))
        self.tutorial.blockSignals(False)
        self._sync_about_picker()
        self.app.blockSignals(True)
        self.app.setCurrentText(conv["app"])
        self.app.blockSignals(False)
        self._sync_app_picker()
        self._fill_suggestions()
        question = ""
        for m in self.db.chat_messages(conversation_id):
            if m["role"] == "user":
                question = m["text"]
                self._add_bubble("You", m["text"], user=True)
            else:
                steps = StepList.model_validate_json(m["steps_json"]) if m["steps_json"] else None
                self._add_bubble(m["meta"].get("who", "GuideWire"), m["text"], user=False)
                for n, key in enumerate(m["meta"].get("videos", []), 1):
                    v = next((x for x in self.asker.context.videos if x.key == key), None)
                    if v is not None:
                        self._add_video_card(v, n)
                if steps is not None:
                    self._add_card(steps, m["meta"].get("app", conv["app"]), m["id"], m["meta"].get("tutorial_id"), question, mapping=not m["meta"].get("guide"))
                    self.last_steps = steps
                self._last_bot_message = m["id"]
        self.refresh_chats()
        self._scroll_down()

    def delete_chat(self) -> None:
        if self.conversation_id is None or self.db is None or self.user_id is None:
            return
        self.db.delete_conversation(self.user_id, self.conversation_id)
        self.new_chat()
        self.refresh_chats()

    # ---- the bubbles
    def _clear_messages(self) -> None:
        while self.messages.count():
            item = self.messages.takeAt(0)
            if item.widget() is not None:
                _discard(item.widget())
            elif item.layout() is not None:
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget() is not None:
                        _discard(sub.widget())
        self._cards = []
        self._card_saving = None
        self._thinking = None
        self._messages = []
        self._video_cards = {}
        self._last_bot_message = None

    def _remove_row(self, widget: QWidget) -> None:
        for i in range(self.messages.count()):
            item = self.messages.itemAt(i)
            lay = item.layout() if item is not None else None
            if lay is not None and any(lay.itemAt(j).widget() is widget for j in range(lay.count())):
                while lay.count():
                    sub = lay.takeAt(0)
                    if sub.widget() is not None:
                        _discard(sub.widget())
                self.messages.takeAt(i)
                return

    def _add_row(self, widget: QWidget, user: bool) -> QWidget:
        widget.setMaximumWidth(BUBBLE_WIDTH)
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if user:
            row.addStretch(1)
            row.addWidget(widget)
        else:
            row.addWidget(widget)
            row.addStretch(1)
        self.messages.addLayout(row)
        return widget

    def _add_bubble(self, who: str, text: str, user: bool) -> QFrame:
        bubble = QFrame()
        bubble.setObjectName("bubbleUser" if user else "bubbleBot")
        box = QVBoxLayout(bubble)
        box.setContentsMargins(16, 10, 16, 12)
        box.setSpacing(2)
        if not user:
            box.addWidget(_label(who, "who"))
        box.addWidget(_label(text))
        self._messages.append((who, text))
        self.welcome.setVisible(False)
        self._add_row(bubble, user)
        self._scroll_down()
        return bubble

    def _restored_context(self, conversation_id: int) -> ChatContext:
        """What the chat remembered when it was last used: the context kept with its newest answer, and the guide's steps reloaded from the tutorial they were saved as."""
        ctx = ChatContext()
        if self.db is None:
            return ctx
        for m in reversed(self.db.chat_messages(conversation_id)):
            if isinstance(m["meta"].get("context"), dict):
                ctx = ChatContext.from_dict(m["meta"]["context"])
                break
        if ctx.guide_tutorial_id is not None and self.load_tutorial is not None:
            try:
                ctx.guide_steps, loaded_title, _url = self.load_tutorial(ctx.guide_tutorial_id)
                ctx.guide_title = ctx.guide_title or loaded_title
            except Exception:                                      # the tutorial was deleted since: the chat goes on without a guide
                ctx.guide_tutorial_id, ctx.guide_video = None, None
        return ctx

    def _add_video_card(self, v: Video, number: int) -> VideoCard:
        card = VideoCard(v, number)
        card.turn_into_steps.connect(self._turn_into_steps)
        card.pick.connect(self._pick_video)
        card.review.connect(self.review_tutorial)
        card.start_session.connect(self.start_session)
        self._video_cards[v.key] = card
        self._add_row(card, False)
        self._scroll_down()
        return card

    def _sync_video_cards(self) -> None:
        ctx = self.asker.context
        for key, card in self._video_cards.items():
            v = next((x for x in ctx.videos if x.key == key), None)
            if v is not None:
                card.refresh(v, ctx.focus_video is v)

    def _turn_into_steps(self, key: str) -> None:
        v = next((x for x in self.asker.context.videos if x.key == key), None)
        if v is not None and self.send_button.isEnabled():
            self.send(f"Turn \"{v.title}\" into steps", action="steps", video_key=key)

    def _pick_video(self, key: str) -> None:
        v = next((x for x in self.asker.context.videos if x.key == key), None)
        if v is not None and self.send_button.isEnabled():
            self.send(f"Pick \"{v.title}\"", action="select", video_key=key)

    def _add_card(self, steps: StepList, app: str, message_id: int | None, tutorial_id: int | None, question: str, mapping: bool = True) -> StepsCard:
        card = StepsCard(steps, app, tutorial_id, mapping)
        card.save.connect(lambda c=card: self._save(c, start=False))
        card.save_and_start.connect(lambda c=card: self._save(c, start=True))
        card.start.connect(lambda c=card: self._start_saved(c))
        card.review.connect(lambda c=card: self.review_tutorial.emit(int(c.tutorial_id)) if c.tutorial_id and c.tutorial_id > 0 else None)
        card.map_to.connect(lambda a, q=question: self._map(q, a))
        self._cards.append((card, message_id, question))
        self._add_row(card, False)
        self._scroll_down()
        return card

    def _scroll_down(self) -> None:
        bar = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def transcript_text(self) -> str:
        """Everything said in the chat on screen, as plain text (and what the tests read)."""
        return "\n".join(f"{who}: {text}" for who, text in self._messages)

    # ---- asking
    def submit(self) -> None:
        text = self.composer.toPlainText().strip()
        if text:
            self.composer.clear()
            self.send(text)

    def send(self, text: str, action: str = "", video_key: str = "") -> None:
        """Send one message, from the composer, a suggestion, a 'map onto' button or a tutorial card's button (`action` and `video_key` then say which video outright)."""
        text = text.strip()
        if not text or not self.send_button.isEnabled():
            return
        if self.db is not None and self.user_id is not None:
            if self.conversation_id is None:
                self.conversation_id = self.db.new_conversation(self.user_id, text, self.app.currentText(), self.tutorial.currentData())
                self.title.setText(text[:80])
            self.db.add_chat_message(self.conversation_id, "user", text)
        self._add_bubble("You", text, user=True)
        tid = self.tutorial.currentData()
        tut = title = url = None
        if tid is not None and self.load_tutorial is not None:
            tut, title, url = self.load_tutorial(tid)
        app, use_model = self.app.currentText(), self.asker.model_available
        self._prepare_saved_lookup(text)
        self.send_button.setEnabled(False)
        self.status.setText("")
        self._thinking = self._add_bubble("GuideWire", "Thinking..." if use_model else "Looking that up...", user=False)
        self._messages.pop()                       # the placeholder is not part of the transcript
        if action == "steps" and video_key in self._video_cards:
            self._video_cards[video_key].set_working()
        run_call(self, lambda status: self.asker.ask(text, app, tutorial=tut, title=title, url=url, use_model=use_model, on_status=status, action=action, video_key=video_key),
                 lambda r, t=text, a=app: self._on_result(r, t, a), on_status=self._on_status, sync=self.sync)

    def _prepare_saved_lookup(self, text: str) -> None:
        """Tell the asker which videos of this chat already are saved tutorials. Done here because the database belongs to this thread and the asker answers on another one."""
        if self.find_saved is None:
            return
        import re
        links = {v.url: v.key for v in self.asker.context.videos}
        for m in re.finditer(r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/\S+", text):
            links.setdefault(m.group(0).rstrip(".,)"), "")
        found = {}
        for url in links:
            try:
                got = self.find_saved(url)
            except Exception:
                got = None
            if got is not None:
                from ..chat_context import video_id
                found[links[url] or video_id(url) or url] = got
        self.asker.saved_tutorials = found

    def _on_status(self, text: str) -> None:
        """What the background work is doing now (looking up the video, the AI watching it, grouping the steps): shown in the waiting bubble and on the video's card."""
        if self._thinking is not None:
            labels = self._thinking.findChildren(QLabel)
            if labels:
                labels[-1].setText(text)
        for key, card in self._video_cards.items():
            if card.video.status == "processing":
                card.set_status(text)

    def _on_result(self, result, question: str = "", app: str = "") -> None:
        self.send_button.setEnabled(True)
        if self._thinking is not None:
            self._remove_row(self._thinking)
            self._thinking = None
        failed = isinstance(result, Exception)
        if failed:
            who, text, steps, shown = "GuideWire", f"Sorry, that failed ({type(result).__name__}). Try again.", None, []
            videos, guide = [], None
        else:
            who, text, steps = "GuideWire" + (" (AI)" if result.used_model else ""), result.headline or result.text, result.steps
            videos, guide = result.videos, result.guide
            shown = videos
        self._add_bubble(who, text, user=False)
        for n, v in enumerate(shown, 1):
            self._add_video_card(v, n)
        card_app = app or self.app.currentText()
        guide_video = None if failed else result.guide_video
        message_id = None
        if self.db is not None and self.conversation_id is not None:
            meta = {"who": who, "app": card_app, "context": self.asker.context.to_dict(), "videos": [v.key for v in shown]}
            if guide is not None or (guide_video is not None and guide_video.status == "done" and not failed):
                meta["guide"] = True
            shown_steps = guide if guide is not None else steps
            message_id = self.db.add_chat_message(self.conversation_id, "bot", text, shown_steps.model_dump_json() if shown_steps is not None else None, meta)
            self._last_bot_message = message_id
        self.last_steps = steps
        if steps is not None:
            self._add_card(steps, card_app, message_id, None, question)
        if guide is not None:
            tid = None if failed else result.reused_tutorial_id
            card = self._add_card(guide, guide_video.app or card_app if guide_video else card_app, message_id, tid, question, mapping=False)
            if tid is None:
                self._card_saving = card
                self.save_guide.emit(guide, guide.title or (guide_video.title if guide_video else "Tutorial from a video"), guide_video.url if guide_video else "")
            else:
                self._guide_in_use(tid, guide_video.title if guide_video else "", card)
        self._sync_video_cards()
        self._persist_context()
        self.refresh_chats()

    # ---- a guide made from a video
    def guide_saved(self, tutorial_id: int, title: str) -> None:
        """The main window saved the guide as a tutorial: the card says so, and the chat is now about it (so "explain step 4" and "what does he do in step 3" work at once)."""
        card = self._card_saving
        self.saved(title, tutorial_id)
        self._guide_in_use(tutorial_id, title, card)
        self._persist_context()

    def guide_not_saved(self, why: str) -> None:
        card, self._card_saving = self._card_saving, None
        self._add_bubble("GuideWire", f"I made the steps but could not save them as a tutorial ({why}). They are still here in the chat: press Save as tutorial on the card to try again.", user=False)
        if card is not None:
            card.set_saved(None)

    def _guide_in_use(self, tutorial_id: int, title: str, card: StepsCard | None) -> None:
        ctx = self.asker.context
        ctx.guide_tutorial_id, ctx.guide_title = tutorial_id, title or ctx.guide_title
        v = ctx.video_at(ctx.guide_video)
        if v is not None:
            v.tutorial_id = tutorial_id
        if card is not None and card.tutorial_id != tutorial_id:
            card.set_saved(tutorial_id, title)
        self.tutorial.blockSignals(True)                          # the new tutorial joins the picker and the chat is about it
        idx = next((i for i in range(self.tutorial.count()) if self.tutorial.itemData(i) == tutorial_id), -1)
        if idx < 0:
            self.tutorial.addItem(title, tutorial_id)
            idx = self.tutorial.count() - 1
        self.tutorial.setCurrentIndex(idx)
        self.tutorial.blockSignals(False)
        self._sync_about_picker()
        self.asker.reset()
        if self.db is not None and self.conversation_id is not None:
            self.db.update_conversation(self.conversation_id, tutorial_id=tutorial_id)
        self._sync_video_cards()

    def _persist_context(self) -> None:
        """Keep the chat's memory (videos, the picked one, the guide's tutorial) with its newest answer, so opening the chat later finds it as it was."""
        if self.db is None or self.conversation_id is None or self._last_bot_message is None:
            return
        row = next((m for m in self.db.chat_messages(self.conversation_id) if m["id"] == self._last_bot_message), None)
        if row is not None:
            self.db.set_chat_message_meta(self._last_bot_message, {**row["meta"], "context": self.asker.context.to_dict()})

    # ---- what can be done with an answer's steps
    def _save(self, card: StepsCard, start: bool) -> None:
        self._card_saving = card
        self.save_and_start.emit(card.steps, card.steps.title or "Steps from GuideWire") if start else self.save_steps.emit(card.steps, card.steps.title or "Steps from GuideWire")

    def saved(self, title: str, tutorial_id: int | None = None) -> None:
        """The main window saved the steps as a tutorial: the card says so and offers to start a session on it."""
        card = self._card_saving
        if card is None:
            return
        card.set_saved(tutorial_id if tutorial_id is not None else -1, title)
        if self.db is not None:
            for c, message_id, _q in self._cards:
                if c is card and message_id is not None:
                    row = next((m for m in self.db.chat_messages(self.conversation_id) if m["id"] == message_id), None) if self.conversation_id is not None else None
                    if row is not None:
                        self.db.set_chat_message_meta(message_id, {**row["meta"], "tutorial_id": tutorial_id, "saved_title": title})
        self._card_saving = None

    def _start_saved(self, card: StepsCard) -> None:
        if card.tutorial_id is not None and card.tutorial_id > 0:
            self.start_session.emit(int(card.tutorial_id))

    def _map(self, question: str, app: str) -> None:
        """Ask the same question again for another application: its own steps, in the same chat."""
        if not question:
            return
        self.app.setCurrentText(app)
        self.send(retarget(question, app))
