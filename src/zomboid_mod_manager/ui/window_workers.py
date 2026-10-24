"""Reusable Qt workers and list/preview widgets for the main window."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QSize,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import (
    QImage,
    QImageReader,
    QMovie,
)

from zomboid_mod_manager import __version__
from zomboid_mod_manager.discovery.scanner import (
    ScanCancelled,
    scan_mods,
)
from zomboid_mod_manager.ui.mod_details import PreviewChoice
from zomboid_mod_manager.updates import (
    UpdateCancelled,
    UpdateError,
    UpdateRelease,
    check_for_update,
    download_update,
    installed_build_id,
)
from zomboid_mod_manager.workshop import fetch_item_metadata

SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SOURCE_ROLE = SEARCH_ROLE + 1
ISSUE_ROLE = SEARCH_ROLE + 2
NEW_WORKSHOP_ROLE = ISSUE_ROLE + 1


class ScanWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    cancelled = Signal()

    def __init__(self, local_roots: list[Path], workshop_roots: list[Path]) -> None:
        super().__init__()
        self._local_roots = local_roots
        self._workshop_roots = workshop_roots

    def run(self) -> None:
        try:
            result = scan_mods(
                local_roots=self._local_roots,
                workshop_roots=self._workshop_roots,
                cancelled=self.isInterruptionRequested,
                progress=self.progress.emit,
            )
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.result_ready.emit(result)
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - Surface unexpected scanner failures in the UI.
            self.failed.emit(f"Scan failed: {exc}")


class DiagnosticWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self._operation = operation

    def run(self) -> None:
        try:
            self.result_ready.emit(self._operation())
        except Exception as exc:  # noqa: BLE001 - Surface diagnostic failures in the UI.
            self.failed.emit(str(exc))


class UpdateCheckWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.result_ready.emit(check_for_update(__version__, installed_build_id()))
        except Exception as exc:  # noqa: BLE001 - Surface update check failures in the UI.
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)
    installer_ready = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, release: UpdateRelease) -> None:
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            installer = download_update(
                self.release,
                progress=self.progress.emit,
                cancelled=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                installer.unlink(missing_ok=True)
                self.cancelled.emit()
                return
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - Surface unexpected update failures.
            self.failed.emit(str(exc))
        else:
            self.installer_ready.emit(str(installer))


class WorkshopDescriptionWorker(QThread):
    result_ready = Signal(str, str, str)
    failed = Signal(str, str)

    def __init__(self, workshop_id: str) -> None:
        super().__init__()
        self.workshop_id = workshop_id

    def run(self) -> None:
        try:
            item = fetch_item_metadata(self.workshop_id)
            self.result_ready.emit(item.workshop_id, item.title, item.description)
        except Exception as exc:  # noqa: BLE001 - Surface read-only API failures in the UI.
            self.failed.emit(self.workshop_id, str(exc))


class PreviewWorker(QThread):
    loaded = Signal(str, int, object)

    def __init__(self, choices: tuple[PreviewChoice, ...], generation: int) -> None:
        super().__init__()
        self.choices = choices
        self.generation = generation

    def run(self) -> None:
        for choice in self.choices:
            if self.isInterruptionRequested():
                break
            image = QImage()
            try:
                if choice.path.stat().st_size <= 25_000_000:
                    reader = QImageReader(str(choice.path))
                    reader.setAutoTransform(True)
                    size = reader.size()
                    if size.isValid() and size.width() * size.height() <= 48_000_000:
                        is_oversized = size.width() > 960 or size.height() > 540
                        scaled = size.scaled(
                            QSize(960, 540), Qt.AspectRatioMode.KeepAspectRatio
                        )
                        if choice.path.suffix.casefold() == ".gif":
                            movie = QMovie(str(choice.path))
                            if movie.isValid():
                                if is_oversized:
                                    movie.setScaledSize(scaled)
                                if movie.jumpToFrame(0):
                                    image = movie.currentImage()
                            movie.stop()
                            del movie
                        if image.isNull():
                            if is_oversized:
                                reader.setScaledSize(scaled)
                            image = reader.read()
            except OSError:
                continue
            if not image.isNull():
                self.loaded.emit(str(choice.path), self.generation, image)
                return
        self.loaded.emit("", self.generation, QImage())
