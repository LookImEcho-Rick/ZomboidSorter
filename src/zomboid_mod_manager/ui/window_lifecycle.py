"""Application window shutdown and theme handling."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QApplication

from zomboid_mod_manager.ui.theme import apply_theme


def fit_window_geometry(
    geometry: QRect, available_geometry: QRect, minimum_size: QSize
) -> QRect:
    """Keep a restored or initial window rectangle on the available screen."""
    if available_geometry.isEmpty():
        return QRect(geometry)

    minimum_width = min(minimum_size.width(), available_geometry.width())
    minimum_height = min(minimum_size.height(), available_geometry.height())
    width = min(max(geometry.width(), minimum_width), available_geometry.width())
    height = min(max(geometry.height(), minimum_height), available_geometry.height())
    left = min(
        max(geometry.left(), available_geometry.left()),
        available_geometry.right() - width + 1,
    )
    top = min(
        max(geometry.top(), available_geometry.top()),
        available_geometry.bottom() - height + 1,
    )
    return QRect(left, top, width, height)


class WindowLifecycleMixin:
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_workshop_preload_scheduled", False):
            return
        self._workshop_preload_scheduled = True
        if QApplication.platformName().casefold() == "offscreen":
            return
        # Give the window time to paint and let its library scan finish before
        # starting Chromium and loading the first Workshop page.
        QTimer.singleShot(1200, self._preload_workshop_when_idle)

    def _preload_workshop_when_idle(self) -> None:
        if self._shutdown_requested or not self.isVisible() or self.isMinimized():
            return
        if self.main_tabs.currentWidget() is self.workshop_page:
            self.workshop_page.open_home_if_needed()
            return
        worker = self._worker
        if worker is not None and worker.isRunning():
            QTimer.singleShot(1000, self._preload_workshop_when_idle)
            return
        self.workshop_page.preload_home()

    def _fit_window_to_available_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available_geometry = screen.availableGeometry()
        if available_geometry.isEmpty():
            return
        minimum_size = self.minimumSize()
        if (
            available_geometry.width() < minimum_size.width()
            or available_geometry.height() < minimum_size.height()
        ):
            return
        self.setGeometry(
            fit_window_geometry(self.geometry(), available_geometry, minimum_size)
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_compact_workspace()

    def _update_compact_workspace(self) -> None:
        if not hasattr(self, "workflow_hint"):
            return
        roomy = self.height() >= 760
        self.workflow_hint.setVisible(roomy)
        self.available_intro.setVisible(roomy)
        self.active_intro.setVisible(roomy)
        compact = self.width() < 1160
        self.metadata_build_label.setText(
            "Build:" if compact else "Project Zomboid build:"
        )
        self.revert_button.setText("Discard" if compact else "Discard Changes")
        self.apply_config_button.setText(
            "Apply List…" if compact else "Apply To Project Zomboid…"
        )
        dirty = (
            self._active_config is not None
            and tuple(self._staged_mod_ids) != self._active_config.config.mods
        )
        self.launch_game_button.setText(
            "Apply && Launch…"
            if dirty
            else "Launch Game"
            if compact
            else "Launch Project Zomboid"
        )
        self.dirty_indicator.setVisible(
            not compact or self.dirty_indicator.text() != "No unapplied changes"
        )

    def closeEvent(self, event) -> None:
        if self._persist_settings:
            self._settings.setValue("window/geometry", self.saveGeometry())
            self._settings.setValue(
                "window/workspace_splitter", self.workspace_splitter.saveState()
            )
            self._settings.setValue("paths/game", self.game_path.text())
            self._settings.setValue(
                "metadata/build_version", self.metadata_build_version.text().strip()
            )
            self._settings.setValue(
                "metadata/target", self.metadata_preview_target.currentData()
            )
            self._settings.setValue("paths/local", self.local_path.text())
            self._settings.setValue("paths/workshop", self.workshop_paths.text())
            self._settings.setValue(
                "paths/active_config", self.active_config_path.text()
            )
            self._settings.sync()
        workers = tuple(
            worker for worker in self._background_workers() if worker.isRunning()
        )
        if workers:
            if not self._shutdown_requested:
                self._shutdown_requested = True
                self._shutdown_workers = workers
                self._scan_again_after_current = False
                self._workshop_description_pending = None
                self._preview_pending = None
                self.status.setText("Closing after background work stops…")
                self.progress.show()
                self.centralWidget().setEnabled(False)
                self.cancel_scan_button.hide()
                for worker in workers:
                    worker.finished.connect(self._continue_shutdown)
                    worker.requestInterruption()
            event.ignore()
            QTimer.singleShot(0, self._continue_shutdown)
            return
        event.accept()

    def _apply_theme(self) -> None:
        apply_theme(self)
        browse_width = max(
            button.sizeHint().width() for button in self._settings_browse_buttons
        )
        secondary_width = max(
            button.sizeHint().width() for button in self._settings_secondary_buttons
        )
        trailing_width = max(
            (button.sizeHint().width() for button in self._settings_trailing_buttons),
            default=20,
        )
        for button in self._settings_browse_buttons:
            button.setFixedWidth(browse_width)
        for button in self._settings_secondary_buttons:
            button.setFixedWidth(secondary_width)
        for button in self._settings_trailing_buttons:
            button.setFixedWidth(trailing_width)
        self.detect_all_trailing_spacer.setFixedWidth(trailing_width)
        for indicator in self._settings_path_health_indicators:
            indicator.setFixedWidth(trailing_width)
            indicator.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
