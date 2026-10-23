"""Application window shutdown and theme handling."""

from __future__ import annotations

from PySide6.QtCore import QTimer

from zomboid_mod_manager.ui.theme import apply_theme


class WindowLifecycleMixin:
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
