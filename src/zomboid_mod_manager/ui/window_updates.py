"""Release checks, installer downloads, and update handoff."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
)

from zomboid_mod_manager import __version__
from zomboid_mod_manager.updates import UpdateRelease

from .window_workers import (
    UpdateCheckWorker,
    UpdateDownloadWorker,
)


class UpdateActionsMixin:
    def _check_for_updates(self) -> None:
        if (
            self._update_check_worker is not None
            and self._update_check_worker.isRunning()
        ):
            return
        if (
            self._update_download_worker is not None
            and self._update_download_worker.isRunning()
        ):
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("Checking…")
        self.status.setText("Checking GitHub for updates…")
        worker = UpdateCheckWorker(self)
        self._update_check_worker = worker
        worker.result_ready.connect(self._update_check_complete)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(self._update_check_worker_finished)
        worker.start()

    def _update_check_complete(self, release: UpdateRelease | None) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        if release is None:
            self.status.setText(f"ZomboidSorter {__version__} is up to date.")
            QMessageBox.information(
                self,
                "No Updates Available",
                f"You are using the latest release of ZomboidSorter ({__version__}).",
            )
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Update Available")
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setText(f"ZomboidSorter {release.version} is available.")
        message.setInformativeText(
            f"Installed version: {__version__}\n"
            "The verified Windows installer will open to complete the update."
        )
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message.setDefaultButton(QMessageBox.StandardButton.No)
        message.button(QMessageBox.StandardButton.Yes).setText("Download and Install")
        answer = message.exec()
        if self._shutdown_requested:
            return
        if answer == QMessageBox.StandardButton.Yes:
            self._download_update(release)
        else:
            self.status.setText(f"ZomboidSorter {release.version} is available.")

    def _update_check_failed(self, error: str) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        self.status.setText("Could not check for updates.")
        QMessageBox.warning(self, "Update Check Failed", error)

    def _update_check_worker_finished(self) -> None:
        if (
            self._update_check_worker is not None
            and not self._update_check_worker.isRunning()
        ):
            self._update_check_worker = None

    def _download_update(self, release: UpdateRelease) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText("Downloading…")
        self.status.setText(f"Downloading ZomboidSorter {release.version}…")
        worker = UpdateDownloadWorker(release)
        self._update_download_worker = worker
        worker.progress.connect(self._update_download_progress)
        worker.installer_ready.connect(self._launch_update_installer)
        worker.failed.connect(self._update_download_failed)
        worker.cancelled.connect(self._update_download_cancelled)
        worker.finished.connect(self._update_download_worker_finished)
        worker.start()

    def _update_download_progress(self, downloaded: int, total: int) -> None:
        if self._shutdown_requested:
            return
        percent = min(100, int(downloaded * 100 / total)) if total else 0
        self.status.setText(f"Downloading update… {percent}%")

    def _update_download_failed(self, error: str) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        self.status.setText("Update download failed.")
        QMessageBox.warning(self, "Update Download Failed", error)

    def _update_download_cancelled(self) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        self.status.setText("Update download cancelled.")

    def _update_download_worker_finished(self) -> None:
        if (
            self._update_download_worker is not None
            and not self._update_download_worker.isRunning()
        ):
            self._update_download_worker = None

    def _launch_update_installer(self, installer_path: str) -> None:
        installer = Path(installer_path)
        if self._shutdown_requested:
            try:
                installer.unlink(missing_ok=True)
            except OSError:
                pass
            return
        try:
            subprocess.Popen([str(installer)], close_fds=True, cwd=installer.parent)
        except OSError as exc:
            self.update_button.setEnabled(True)
            self.update_button.setText("Check for Updates")
            self.status.setText("Could not launch the update installer.")
            QMessageBox.warning(
                self,
                "Could Not Start Installer",
                f"The installer was downloaded and verified, but Windows could not open it:\n{exc}",
            )
            return
        self.status.setText(
            "Installer opened. Follow its prompts to complete the update."
        )
        QApplication.quit()

    def _show_failure(self, message: str) -> None:
        if self._shutdown_requested:
            return
        self._scan_result_received = True
        self.scan_button.setEnabled(True)
        self.workspace_scan_button.setEnabled(True)
        self.status.setText(message)
        if self._last_result is None:
            self.available_list.empty_text = "Scan failed · check Paths & Settings"
            self.available_list.viewport().update()
        self.diagnostics.setPlainText(message)
