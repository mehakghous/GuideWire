"""One light style for the whole app: readable text, roomy buttons, an accent colour for the main action. Plain Qt style sheet, nothing to install."""

STYLE = """
QWidget { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; color: #1e2430; }
QMainWindow, QStackedWidget, QWidget#root { background: #f4f6fa; }
QLabel#hint { color: #5b6677; font-size: 9.5pt; }
QLabel#empty { color: #5b6677; font-size: 11pt; padding: 18px; background: #ffffff; border: 1px dashed #b8c2d3; border-radius: 8px; }
QPushButton { background: #ffffff; border: 1px solid #b8c2d3; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #eaf1fb; border-color: #7fa6dc; }
QPushButton:disabled { color: #9aa4b5; background: #eef1f6; }
QPushButton#primary { background: #2f6fdb; border-color: #2f6fdb; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background: #2559b3; }
QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QComboBox { background: #ffffff; border: 1px solid #c5cedd; border-radius: 6px; padding: 5px; }
QListWidget { outline: 0; }
QListWidget::item { padding: 7px; }
QListWidget::item:selected { background: #dce9fb; color: #1e2430; }
QCheckBox { spacing: 8px; }
QFrame#card { background: #ffffff; border: 1px solid #c5cedd; border-radius: 8px; }
QPushButton#danger { color: #b3261e; }
QPushButton#danger:hover { background: #fdecea; border-color: #e5a7a1; }
"""
