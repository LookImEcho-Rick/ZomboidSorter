"""Shared, lightweight Qt styling for the desktop workspace and dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background: #111719; color: #e9ece7; font-family: "Segoe UI"; font-size: 10pt;
}
QWidget#imagePreviewOverlay { background: rgba(0, 0, 0, 200); }
QWidget#detailsPane { background: #171f21; border: 1px solid #34403e; }
QLabel#appTitle { color: #f1ede0; font-size: 16pt; font-weight: 800; letter-spacing: 2px; }
QLabel#sectionKicker, QLabel#panelHeading {
    color: #d9e2d4; font-weight: 700; font-size: 10pt; padding: 2px 0;
}
QLabel#sectionKicker { color: #b8c66d; letter-spacing: 1px; }
QLabel#secondaryText { color: #a4b2ab; }
QLabel#issueSummary { color: #e5b66c; padding: 4px 2px; }
QLabel#dirtyIndicator { color: #b8c7b7; padding: 4px; }
QLabel#modPreview {
    background: #202b2c; color: #a4b2ab; border: 1px solid #42514d;
    font-size: 15px;
}
QLabel#workshopNote { background: #1b2627; border: 1px solid #3a4a46;
                     color: #a4b2ab; padding: 10px; }
QTabWidget::pane { border: 1px solid #34403e; background: #161e20; }
QTabBar::tab {
    background: #1a2426; color: #a4b2ab; padding: 9px 17px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { background: #273432; color: #f1f1e9; }
QTabBar::tab:selected { background: #26312e; color: #f2f1e9;
                         border-bottom: 2px solid #bac875; }
QTabBar::tab:focus { border: 2px solid #b8c66d; }
QLineEdit, QPlainTextEdit, QListWidget, QTableView, QTableWidget,
QTextBrowser, QComboBox {
    background: #1b2527; color: #e9ece7; border: 1px solid #3b4a48;
    border-radius: 4px; selection-background-color: #4b654d;
    selection-color: #ffffff;
}
QLineEdit { padding: 6px 9px; }
QComboBox { padding: 5px 8px; }
QPlainTextEdit, QTextBrowser { padding: 7px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus, QListWidget:focus,
QTableView:focus, QTableWidget:focus, QComboBox:focus, QPushButton:focus {
    border: 2px solid #b8c66d;
}
QListWidget::item { padding: 7px 8px; margin: 1px 2px; border-radius: 3px; }
QListWidget::item:hover { background: #2a3938; }
QListWidget::item:selected { background: #435f4b; color: #ffffff; }
QListWidget::item:disabled { color: #dfac73; }
QPushButton {
    background: #2c3b3b; color: #edf0e7; border: 1px solid #52615a;
    border-radius: 4px; padding: 6px 10px; min-height: 20px;
    font-weight: 600;
}
QPushButton:hover { background: #42544c; border-color: #b8c66d; }
QPushButton:pressed { background: #526b50; }
QPushButton:disabled { background: #202a2b; color: #84928a;
                       border-color: #34413f; }
QPushButton#primaryAction { background: #a6b85c; color: #111913;
                             border-color: #c4d478; font-weight: 700; }
QPushButton#primaryAction:hover { background: #c0d478; }
QPushButton#primaryAction:disabled { background: #425042; color: #a8b1a3;
                                      border-color: #53614e; }
QMenu, QToolTip { background: #23302e; color: #e9ece7;
                  border: 1px solid #637266; }
QMenu::item { padding: 6px 16px; }
QMenu::item:selected { background: #435f4b; }
QCheckBox { spacing: 6px; padding: 4px 7px; }
QCheckBox:focus { border: 2px solid #b8c66d; }
QStatusBar { background: #182123; border-top: 1px solid #34403e; }
QProgressBar { background: #24302e; border: 1px solid #44524c; }
QProgressBar::chunk { background: #a6b85c; }
QSplitter::handle { background: #34433e; }
QScrollBar:vertical { background: #1b2527; width: 10px; }
QScrollBar::handle:vertical { background: #53685a; min-height: 28px;
                              border-radius: 4px; }
QScrollBar:horizontal { background: #1b2527; height: 10px; }
QScrollBar::handle:horizontal { background: #53685a; min-width: 28px; }
"""


def apply_theme(widget: QWidget) -> None:
    widget.setStyleSheet(STYLESHEET)
