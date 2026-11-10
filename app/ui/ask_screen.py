"""Ask GuideWire: a chat screen for questions, "where do I start" plans and "give me the steps" requests.

Wraps `app.ask.Asker`. Pick the application, optionally pick one of your tutorials (then "what is he doing at 1:30", "what's next" and "go back to ..." work on its steps), tick "Use the AI model"
for a fuller answer, and type. When an answer is a list of steps (a starter plan, the steps for a topic) a button saves it as a tutorial you can review and run a session on.
"""
from __future__ import annotations

import html

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from shared.step_record import StepList

from ..ask import Asker, AskResult
from ..pipeline import APPS
from .workers import run_call

EXAMPLES = ("Try:  where do i start rigging in maya   |   give me the steps to bind the mesh   |   my knee flips when i move the ik handle   |   what should i do before rigging")


class AskScreen(QWidget):
    back = pyqtSignal()
    save_steps = pyqtSignal(object, str)           # StepList, a title

    def __init__(self, asker: Asker | None = None, sync: bool = False):
        super().__init__()
        self.asker = asker or Asker()
        self.sync = sync                            # tests run the call inline
        self.load_tutorial = None                   # set by the main window: tid -> (StepList, title, url)
        self.last_steps: StepList | None = None
        self.app = QComboBox()
        self.app.addItems(APPS)
        self.tutorial = QComboBox()
        self.tutorial.addItem("(no tutorial: a general question)", None)
        self.use_model = QCheckBox("Use the AI model")
        self.use_model.setEnabled(self.asker.model_available)
        self.use_model.setChecked(self.asker.model_available)
        self.use_model.setToolTip("A fuller answer from the AI (about a tenth of a cent). Without it the answer comes from GuideWire's own knowledge base and rules.")
        self.transcript = QTextBrowser()
        self.transcript.setOpenLinks(False)
        self.hint = QLabel(EXAMPLES)
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type your question and press Enter")
        self.ask_button = QPushButton("Ask")
        self.ask_button.setObjectName("primary")
        self.save_button = QPushButton("Save these steps as a tutorial")
        self.save_button.setVisible(False)
        self.status = QLabel("")
        self.back_button = QPushButton("Back")
        self.ask_button.clicked.connect(self.submit)
        self.input.returnPressed.connect(self.submit)
        self.save_button.clicked.connect(self._save)
        self.back_button.clicked.connect(self.back.emit)
        self.app.currentTextChanged.connect(lambda _t: self._new_conversation())
        self.tutorial.currentIndexChanged.connect(lambda _i: self._new_conversation())
        top = QHBoxLayout()
        top.addWidget(QLabel("Application"))
        top.addWidget(self.app)
        top.addWidget(QLabel("About"))
        top.addWidget(self.tutorial, 1)
        top.addWidget(self.use_model)
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.ask_button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.save_button)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.back_button)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>Ask GuideWire</h2>"))
        root.addLayout(top)
        root.addWidget(self.transcript, 1)
        root.addWidget(self.hint)
        root.addLayout(row)
        root.addLayout(bottom)

    # ---- the tutorials the user can ask about
    def set_tutorials(self, rows: list[tuple[int, str]], select: int | None = None) -> None:
        self.tutorial.blockSignals(True)
        self.tutorial.clear()
        self.tutorial.addItem("(no tutorial: a general question)", None)
        for tid, title in rows:
            self.tutorial.addItem(title, tid)
        idx = next((i for i in range(self.tutorial.count()) if select is not None and self.tutorial.itemData(i) == select), 0)
        self.tutorial.setCurrentIndex(idx)
        self.tutorial.blockSignals(False)
        self._new_conversation()

    def _new_conversation(self) -> None:
        self.asker.reset()
        self.last_steps = None
        self.save_button.setVisible(False)
        self.status.setText("")
        self.transcript.setHtml("<p style='color:#666'>Ask a question below. " + ("This answer will be about the tutorial you chose." if self.tutorial.currentData() is not None else "No tutorial chosen: a general question.") + "</p>")

    def _append(self, who: str, text: str) -> None:
        body = html.escape(text).replace("\n", "<br>")
        color = "#1f4e79" if who == "You" else "#222"
        self.transcript.append(f"<p><b style='color:{color}'>{who}</b><br><span>{body}</span></p>")

    # ---- asking
    def submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("You", text)
        tid = self.tutorial.currentData()
        tut = title = url = None
        if tid is not None and self.load_tutorial is not None:
            tut, title, url = self.load_tutorial(tid)
        app, use_model = self.app.currentText(), self.use_model.isChecked()
        self.ask_button.setEnabled(False)
        self.status.setText("Thinking..." if use_model else "")
        run_call(self, lambda _status: self.asker.ask(text, app, tutorial=tut, title=title, url=url, use_model=use_model), self._on_result, sync=self.sync)

    def _on_result(self, result) -> None:
        self.ask_button.setEnabled(True)
        self.status.setText("")
        if isinstance(result, Exception):
            self._append("GuideWire", f"Sorry, that failed ({type(result).__name__}). Try again.")
            return
        result: AskResult
        self._append("GuideWire" + (" (AI)" if result.used_model else ""), result.text)
        self.last_steps = result.steps
        self.save_button.setVisible(result.steps is not None)
        if result.steps is not None:
            self.save_button.setText(f"Save these {len(result.steps.steps)} steps as a tutorial")

    def _save(self) -> None:
        if self.last_steps is None:
            return
        self.save_steps.emit(self.last_steps, self.last_steps.title or "Steps from GuideWire")

    def saved(self, title: str) -> None:
        self.save_button.setVisible(False)
        self._append("GuideWire", f"Saved as \"{title}\". Go back to Home to review the steps or start a session.")
