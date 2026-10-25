"""Lazy embedded browser for the Project Zomboid Steam Workshop."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager.portable import app_data_directory
from zomboid_mod_manager.workshop import parse_published_file_id

if TYPE_CHECKING:
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

_WORKSHOP_HOME = "https://steamcommunity.com/app/108600/workshop/"
_HIDDEN_DISCARD_DELAY_MS = 2_000


def _configure_persistent_profile(
    profile: QWebEngineProfile, storage_root: Path
) -> None:
    from PySide6.QtWebEngineCore import QWebEngineProfile

    storage_path = storage_root / "storage"
    cache_path = storage_root / "cache"
    storage_path.mkdir(parents=True, exist_ok=True)
    cache_path.mkdir(parents=True, exist_ok=True)
    profile.setPersistentStoragePath(str(storage_path))
    profile.setCachePath(str(cache_path))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )


class WorkshopBrowserPanel(QWidget):
    """Own the Workshop browser controls and lazily created WebEngine view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workshop_browser: QWebEngineView | None = None
        self._browser_profile: QWebEngineProfile | None = None
        self._browser_loaded = False
        self._browser_ready = False
        self._tab_active = False
        self._tab_ever_opened = False
        self._storage_error: str | None = None
        self._storage_error_shown = False
        self._hidden_discard_timer = QTimer(self)
        self._hidden_discard_timer.setSingleShot(True)
        self._hidden_discard_timer.setInterval(_HIDDEN_DISCARD_DELAY_MS)
        self._hidden_discard_timer.timeout.connect(self._discard_hidden_browser)

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
        self.browser_note = QLabel(
            "Steam's sign-in session is kept with ZomboidSorter's local app data "
            "between launches. After you leave this tab, its page may reload "
            "to free memory. Use Steam's sign-out option "
            "to end the session. "
            "Open In Browser uses your default browser. "
            "Refresh Mod Workspace after Steam installs or changes mods."
        )
        self.browser_note.setObjectName("secondaryText")
        self.browser_note.setWordWrap(True)
        layout.addWidget(self.browser_note)

        self.workshop_browser_container = QWidget(self)
        self.workshop_browser_layout = QStackedLayout(self.workshop_browser_container)
        self.workshop_browser_layout.setContentsMargins(0, 0, 0, 0)
        self.workshop_browser_placeholder = QLabel(
            "Opening the Project Zomboid Steam Workshop…"
        )
        self.workshop_browser_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.workshop_browser_placeholder.setWordWrap(True)
        self.workshop_browser_layout.addWidget(self.workshop_browser_placeholder)
        layout.addWidget(self.workshop_browser_container, 1)

    def open_home_if_needed(self) -> None:
        if not self._browser_loaded:
            self.open_home()

    def preload_home(self) -> None:
        """Warm the first Workshop page while the user gets started elsewhere."""
        if not self._browser_loaded:
            self.open_home()

    def open_home(self) -> None:
        self._ensure_browser().setUrl(QUrl(_WORKSHOP_HOME))

    def set_tab_active(self, active: bool) -> None:
        self._tab_active = active
        if active:
            self._tab_ever_opened = (
                self._tab_ever_opened or self.workshop_browser is not None
            )
            self._show_storage_warning()
        self._sync_browser_lifecycle()
        if not active:
            # Let QTabWidget hide the view before asking Chromium to freeze it.
            QTimer.singleShot(0, self._sync_browser_lifecycle)

    def _show_storage_warning(self) -> None:
        if self._storage_error is None or self._storage_error_shown:
            return
        self._storage_error_shown = True
        QMessageBox.warning(
            self,
            "Steam session won't be remembered",
            "ZomboidSorter could not prepare local Workshop browser storage. "
            "Steam's sign-in may not carry over to the next launch.\n\n"
            f"{self._storage_error}",
        )

    def _sync_browser_lifecycle(self, *_args) -> None:
        browser = self.workshop_browser
        if browser is None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage

        page = browser.page()
        if self._tab_active:
            self._hidden_discard_timer.stop()
            if page.lifecycleState() == QWebEnginePage.LifecycleState.Discarded:
                self._browser_ready = False
                self.workshop_browser_placeholder.setText(
                    "Reopening the Project Zomboid Steam Workshop…"
                )
                self.workshop_browser_layout.setCurrentWidget(
                    self.workshop_browser_placeholder
                )
            desired_state = QWebEnginePage.LifecycleState.Active
        else:
            if browser.isVisible():
                self._hidden_discard_timer.stop()
                return
            lifecycle_state = page.lifecycleState()
            if lifecycle_state == QWebEnginePage.LifecycleState.Discarded:
                self._hidden_discard_timer.stop()
                return
            if not self._tab_ever_opened and page.isLoading():
                # Let the startup warm-up finish before freezing its hidden page.
                self._hidden_discard_timer.stop()
                return
            if self._tab_ever_opened and not self._hidden_discard_timer.isActive():
                # A busy Steam page may never recommend a lower-resource state.
                # Once hidden, release it after a short grace period anyway.
                self._hidden_discard_timer.start()
            recommended_state = page.recommendedState()
            if recommended_state == QWebEnginePage.LifecycleState.Active:
                return
            desired_state = QWebEnginePage.LifecycleState.Frozen
        if page.lifecycleState() != desired_state:
            page.setLifecycleState(desired_state)

    def _discard_hidden_browser(self) -> None:
        browser = self.workshop_browser
        if browser is None or self._tab_active or browser.isVisible():
            return
        page = browser.page()
        from PySide6.QtWebEngineCore import QWebEnginePage

        if page.lifecycleState() != QWebEnginePage.LifecycleState.Discarded:
            page.setLifecycleState(QWebEnginePage.LifecycleState.Discarded)

    def open_externally(self) -> None:
        url = self.workshop_browser.url() if self.workshop_browser else QUrl()
        if not url.isValid() or not url.scheme():
            url = QUrl(_WORKSHOP_HOME)
        QDesktopServices.openUrl(url)

    def _ensure_browser(self) -> QWebEngineView:
        if self.workshop_browser is None:
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
            from PySide6.QtWebEngineWidgets import QWebEngineView

            try:
                self._browser_profile = QWebEngineProfile(
                    "zomboid-sorter-workshop", self
                )
                _configure_persistent_profile(
                    self._browser_profile,
                    app_data_directory() / "workshop-browser",
                )
            except OSError as exc:
                self._browser_profile = None
                self.browser_note.setText(
                    "Local browser storage could not be prepared, so Steam's sign-in "
                    "may not carry over to the next launch."
                )
                self.browser_note.setToolTip(str(exc))
                self._storage_error = str(exc)
            self.workshop_browser = QWebEngineView(self.workshop_browser_container)
            self.workshop_browser.setAccessibleName("Steam Project Zomboid Workshop")
            if self._tab_active:
                self._tab_ever_opened = True
            if self._browser_profile is not None:
                page = QWebEnginePage(self._browser_profile, self.workshop_browser)
                self.workshop_browser.setPage(page)
            page = self.workshop_browser.page()
            page.setBackgroundColor(self.palette().color(QPalette.ColorRole.Window))
            page.recommendedStateChanged.connect(self._sync_browser_lifecycle)
            self.workshop_browser.urlChanged.connect(self._sync_location)
            self.workshop_browser.loadStarted.connect(self._browser_load_started)
            self.workshop_browser.loadFinished.connect(self._browser_load_finished)
            self.workshop_browser_layout.addWidget(self.workshop_browser)
            self.workshop_browser_layout.setCurrentWidget(
                self.workshop_browser_placeholder
            )
            self._sync_browser_lifecycle()
        self._browser_loaded = True
        return self.workshop_browser

    def _browser_load_started(self) -> None:
        if self._browser_ready:
            return
        self.workshop_browser_placeholder.setText(
            "Connecting to the Project Zomboid Steam Workshop…"
        )
        self.workshop_browser_layout.setCurrentWidget(self.workshop_browser_placeholder)

    def _browser_load_finished(self, succeeded: bool) -> None:
        browser = self.workshop_browser
        if browser is None:
            return
        if succeeded:
            self._browser_ready = True
            self.workshop_browser_layout.setCurrentWidget(browser)
        else:
            self.workshop_browser_placeholder.setText(
                "Steam Workshop couldn't be loaded. Check your connection, then "
                "select Reload to try again."
            )
            self.workshop_browser_layout.setCurrentWidget(
                self.workshop_browser_placeholder
            )
        self._sync_browser_lifecycle()

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
