"""Shared, lightweight Qt styling for the desktop workspace and dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background: #111719; color: #e9ece7; font-family: "Segoe UI"; font-size: 10.5pt;
}
QLabel { background: transparent; }
QWidget#imagePreviewOverlay { background: rgba(0, 0, 0, 200); }
QWidget#workspacePanel, QWidget#detailsPane {
    background: #171f21; border: 1px solid #344641; border-radius: 6px;
}
QWidget#workspaceNotice {
    background: #2b3026; border: 1px solid #8c9556; border-radius: 5px;
}
QLabel#appTitle { color: #f1ede0; font-size: 16pt; font-weight: 800; letter-spacing: 2px; }
QLabel#pageHeading { color: #f1ede0; font-size: 17pt; font-weight: 700; }
QLabel#sectionKicker, QLabel#panelHeading {
    color: #d9e2d4; font-weight: 700; font-size: 10.5pt; padding: 2px 0;
}
QLabel#sectionKicker { color: #b8c66d; letter-spacing: 1px; }
QLabel#secondaryText { color: #a4b2ab; }
QLabel#pathHealth {
    color: #84928a; font-size: 13pt; font-weight: 700;
}
QLabel#pathHealth[health="ready"] { color: #a6c77c; }
QLabel#pathHealth[health="missing"], QLabel#pathHealth[health="partial"],
QLabel#pathHealth[health="invalid"] { color: #e5b66c; }
QLabel#pathHealth[health="unreadable"] { color: #e9907e; }
QLabel#workflowHint { color: #b8c7b7; padding-left: 12px; }
QLabel#issueSummary { color: #e5b66c; padding: 4px 2px; }
QLabel#dirtyIndicator { color: #b8c7b7; padding: 4px; }
QLabel#configStatus {
    background: #1d2b27; color: #e2eadb; border: 1px solid #4b6654;
    border-radius: 4px; padding: 10px;
}
QFrame#footerRule { background: #344641; max-height: 1px; border: 0; }
QLabel#modPreview {
    background: #202b2c; color: #a4b2ab; border: 1px solid #42514d;
    font-size: 15px;
}
QLabel#workshopNote { background: #1b2627; border: 1px solid #3a4a46;
                     color: #a4b2ab; padding: 10px; }
QTabWidget::pane { border: 1px solid #34403e; background: #161e20; border-radius: 4px; }
QTabBar::tab {
    background: #1a2426; color: #b6c3bb; padding: 10px 18px;
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
QLineEdit { padding: 7px 10px; }
QComboBox { padding: 6px 9px; }
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
    border-radius: 4px; padding: 7px 11px; min-height: 22px;
    font-weight: 600;
}
QPushButton:hover { background: #42544c; border-color: #b8c66d; }
QPushButton:pressed { background: #526b50; }
QPushButton#subtleAction { background: #23312f; border-color: #3c5149; }
QPushButton#subtleAction:hover { background: #364a40; border-color: #b8c66d; }
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
QStatusBar QLabel { padding-left: 6px; }
QProgressBar { background: #24302e; border: 1px solid #44524c; }
QProgressBar::chunk { background: #a6b85c; }
QSplitter::handle { background: #34433e; }
QSplitter::handle:hover { background: #9eaf68; }
QScrollBar:vertical { background: #1b2527; width: 10px; }
QScrollBar::handle:vertical { background: #53685a; min-height: 28px;
                              border-radius: 4px; }
QScrollBar:horizontal { background: #1b2527; height: 10px; }
QScrollBar::handle:horizontal { background: #53685a; min-width: 28px; }
"""


def apply_theme(widget: QWidget) -> None:
    widget.setStyleSheet(STYLESHEET)
