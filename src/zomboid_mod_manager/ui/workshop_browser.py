"""Lazy embedded browser for the Project Zomboid Steam Workshop."""

from __future__ import annotations

from urllib.parse import quote_plus

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager.workshop import parse_published_file_id

_WORKSHOP_HOME = "https://steamcommunity.com/app/108600/workshop/"


class WorkshopBrowserPanel(QWidget):
    """Own the Workshop browser controls and lazily created WebEngine view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workshop_browser: QWebEngineView | None = None
        self._browser_loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.workshop_back_button = QPushButton("Back")
        self.workshop_back_button.setEnabled(False)
        self.workshop_back_button.clicked.connect(
            lambda: self.workshop_browser and self.workshop_browser.back()
        )
        search_row.addWidget(self.workshop_back_button)

        self.workshop_forward_button = QPushButton("Forward")
        self.workshop_forward_button.setEnabled(False)
        self.workshop_forward_button.clicked.connect(
            lambda: self.workshop_browser and self.workshop_browser.forward()
        )
        search_row.addWidget(self.workshop_forward_button)

        self.workshop_reload_button = QPushButton("Reload")
        self.workshop_reload_button.clicked.connect(
            lambda: self.workshop_browser and self.workshop_browser.reload()
        )
        search_row.addWidget(self.workshop_reload_button)

        self.open_workshop_home_button = QPushButton("Home")
        self.open_workshop_home_button.setToolTip(
            "Show the Project Zomboid Workshop home page in this tab."
        )
        self.open_workshop_home_button.clicked.connect(self.open_home)
        search_row.addWidget(self.open_workshop_home_button)

        self.workshop_search = QLineEdit()
        self.workshop_search.setPlaceholderText(
            "Search Workshop, or enter a page URL / item ID"
        )
        self.workshop_search.setAccessibleName("Search Workshop or navigate to a page")
        self.workshop_search.setClearButtonEnabled(True)
        self.workshop_search.returnPressed.connect(self.search)
        search_row.addWidget(self.workshop_search, 1)

        self.workshop_search_button = QPushButton("Go")
        self.workshop_search_button.setToolTip(
            "Search for a title or open the entered Workshop URL or item ID."
        )
        self.workshop_search_button.clicked.connect(self.search)
        search_row.addWidget(self.workshop_search_button)

        self.open_workshop_external_button = QPushButton("Open In Browser")
        self.open_workshop_external_button.setToolTip(
            "Open the current Workshop page in your default browser."
        )
        self.open_workshop_external_button.clicked.connect(self.open_externally)
        search_row.addWidget(self.open_workshop_external_button)
        layout.addLayout(search_row)
        browser_note = QLabel(
            "Browse the Project Zomboid Workshop here. Refresh Mod Workspace after Steam installs or changes mods."
        )
        browser_note.setObjectName("secondaryText")
        browser_note.setWordWrap(True)
        layout.addWidget(browser_note)

        self.workshop_browser_container = QWidget(self)
        self.workshop_browser_layout = QVBoxLayout(self.workshop_browser_container)
        self.workshop_browser_layout.setContentsMargins(0, 0, 0, 0)
        self.workshop_browser_placeholder = QLabel(
            "Opening the Project Zomboid Steam Workshop…"
        )
        self.workshop_browser_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.workshop_browser_layout.addWidget(self.workshop_browser_placeholder)
        layout.addWidget(self.workshop_browser_container, 1)

    def open_home_if_needed(self) -> None:
        if not self._browser_loaded:
            self.open_home()

    def open_home(self) -> None:
        self._ensure_browser().setUrl(QUrl(_WORKSHOP_HOME))

    def open_externally(self) -> None:
        url = self.workshop_browser.url() if self.workshop_browser else QUrl()
        if not url.isValid() or not url.scheme():
            url = QUrl(_WORKSHOP_HOME)
        QDesktopServices.openUrl(url)

    def _ensure_browser(self) -> QWebEngineView:
        if self.workshop_browser is None:
            self.workshop_browser_layout.removeWidget(self.workshop_browser_placeholder)
            self.workshop_browser_placeholder.hide()
            self.workshop_browser_placeholder.deleteLater()
            self.workshop_browser = QWebEngineView(self.workshop_browser_container)
            self.workshop_browser.setAccessibleName("Steam Project Zomboid Workshop")
            self.workshop_browser.urlChanged.connect(self._sync_location)
            self.workshop_browser_layout.addWidget(self.workshop_browser)
        self._browser_loaded = True
        return self.workshop_browser

    def _sync_location(self, url: QUrl) -> None:
        self.workshop_search.setText(url.toString())
        if self.workshop_browser is not None:
            self.workshop_back_button.setEnabled(
                self.workshop_browser.history().canGoBack()
            )
            self.workshop_forward_button.setEnabled(
                self.workshop_browser.history().canGoForward()
            )

    def search(self) -> None:
        query = self.workshop_search.text().strip()
        if not query:
            self.open_home()
            return
        if query.isdecimal():
            try:
                workshop_id = parse_published_file_id(query)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid Workshop item", str(exc))
                return
            url = QUrl(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
            )
        elif query.startswith(("https://", "http://")):
            url = QUrl.fromUserInput(query)
            if not url.isValid() or url.scheme() not in ("https", "http"):
                QMessageBox.warning(
                    self,
                    "Invalid Workshop URL",
                    "Enter a valid HTTP or HTTPS page address.",
                )
                return
        else:
            url = QUrl(
                "https://steamcommunity.com/workshop/browse/?appid=108600&searchtext="
                + quote_plus(query)
            )
        self._ensure_browser().setUrl(url)
