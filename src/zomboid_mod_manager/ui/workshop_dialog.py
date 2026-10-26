"""Native collection review and subscription-free shared-cache import."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from zomboid_mod_manager.collection_import import download_collection
from zomboid_mod_manager.collection_store import CollectionStore
from zomboid_mod_manager.domain import ScanResult
from zomboid_mod_manager.portable import app_data_directory
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    suggest_profile_name,
    validate_profile,
)
from zomboid_mod_manager.steamcmd import SteamCmdDownloader
from zomboid_mod_manager.workshop import (
    WorkshopCollectionResult,
    fetch_collection,
    resolve_collection_import,
)
from zomboid_mod_manager.workshop_install import installed_collection_ids

from .text import counted
from .theme import apply_theme


class CollectionWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, collection_text: str) -> None:
        super().__init__()
        self._collection_text = collection_text

    def run(self) -> None:
        try:
            result = fetch_collection(
                self._collection_text,
                timeout=5,
                max_items=2000,
                cancelled=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001 - Return API failures to the GUI.
            self.failed.emit(str(exc))


class CollectionDownloadWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, collection, name, store, downloader) -> None:
        super().__init__()
        self._args = collection, name, store, downloader

    def run(self) -> None:
        try:
            result = download_collection(
                *self._args,
                cancelled=self.isInterruptionRequested,
                progress=self.progress.emit,
            )
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001 - Return download failures to the GUI.
            self.failed.emit(str(exc))


class WorkshopCollectionDialog(QDialog):
    collection_imported = Signal(object)

    def __init__(
        self,
        scan_result: ScanResult,
        parent=None,
        *,
        collection_id="",
        title="",
        collection_store=None,
        downloader=None,
        profile_store: ProfileStore | None = None,
        save_profile=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Steam Workshop Collection")
        self.resize(960, 680)
        self.setMinimumSize(740, 540)
        apply_theme(self)
        self._scan_result = scan_result
        self._worker = None
        self._collection = None
        self._plan = None
        self._saved_pack = None
        self._store = collection_store or CollectionStore(
            app_data_directory() / "collections"
        )
        self._downloader = downloader or SteamCmdDownloader(
            app_data_directory() / "tools/steamcmd"
        )
        self._profile_store = profile_store
        self._save_profile = save_profile
        self._downloaded_profile = None
        self._installing = False
        self._closing = False
        self._pending_result = QDialog.DialogCode.Rejected
        self.downloads_checked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        heading = QLabel("Import a Collection as a Mod Pack")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        note = QLabel(
            "Downloads stay in a private shared collections folder without changing Steam subscriptions. Exact matching content is stored once. Load the saved pack to make its mods available to Zomboid and the workspace. Valve's signed SteamCMD downloader is prepared on first use."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        inputs = QHBoxLayout()
        self.collection_input = QLineEdit()
        self.collection_input.setPlaceholderText(
            "Paste a Steam collection URL or numeric ID"
        )
        self.collection_input.setAccessibleName("Steam collection URL or ID")
        inputs.addWidget(self.collection_input, 1)
        self.fetch_button = QPushButton("Fetch Collection")
        self.fetch_button.clicked.connect(self._fetch)
        inputs.addWidget(self.fetch_button)
        layout.addLayout(inputs)
        self.status = QLabel(
            "Review the collection before downloading. Importing does not load or apply the pack."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 0)
        self.download_progress.hide()
        layout.addWidget(self.download_progress)
        self.items = QTableWidget(0, 5)
        self.items.setAccessibleName(
            "Collection items, local installation, and private download status"
        )
        self.items.setHorizontalHeaderLabels(
            [
                "Workshop item",
                "Workshop ID",
                "Local install",
                "Downloaded / saved pack",
                "Contained Mod IDs",
            ]
        )
        self.items.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.items.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.items.setAlternatingRowColors(True)
        self.items.horizontalHeader().setStretchLastSection(True)
        self.items.setColumnWidth(0, 220)
        self.items.setColumnWidth(1, 115)
        self.items.setColumnWidth(2, 95)
        self.items.setColumnWidth(3, 150)
        self.items.currentCellChanged.connect(self._update_open_workshop_page_enabled)
        layout.addWidget(self.items, 1)
        item_actions = QHBoxLayout()
        item_actions.addStretch()
        self.open_missing_workshop_button = QPushButton("Open Selected Missing Item")
        self.open_missing_workshop_button.setEnabled(False)
        self.open_missing_workshop_button.clicked.connect(
            self._open_selected_missing_workshop_item
        )
        item_actions.addWidget(self.open_missing_workshop_button)
        layout.addLayout(item_actions)
        names = QHBoxLayout()
        names.addWidget(QLabel("Mod Pack name"))
        self.profile_name = QLineEdit()
        self.profile_name.setMaxLength(80)
        self.profile_name.setAccessibleName("Mod Pack name")
        self.profile_name.textChanged.connect(self._profile_name_changed)
        names.addWidget(self.profile_name, 1)
        layout.addLayout(names)
        actions = QHBoxLayout()
        self.import_button = QPushButton("Save Installed List Only…")
        self.import_button.setToolTip(
            "Save a list of currently installed Mod IDs without private downloads."
        )
        self.import_button.clicked.connect(self._create_profile)
        actions.addWidget(self.import_button)
        actions.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        self.install_button = QPushButton("Download && Import")
        self.install_button.setAccessibleName(
            "Download and import collection without subscriptions"
        )
        self.install_button.setObjectName("primaryAction")
        self.install_button.clicked.connect(self._start_install)
        actions.addWidget(self.install_button)
        layout.addLayout(actions)
        self._update_create_enabled()
        if title:
            suggested = suggest_profile_name(
                title, fallback=f"Steam Collection {collection_id}"
            )
            self.profile_name.setText(
                self._unique_profile_name(suggested, collection_id)
            )
        if collection_id:
            self.collection_input.setText(collection_id)
            QTimer.singleShot(0, self._fetch)

    def _fetch(self) -> None:
        if self._worker is not None:
            return
        value = self.collection_input.text().strip()
        if not value:
            self.status.setText("Enter a Steam collection URL or ID.")
            return
        self._collection = self._plan = self._downloaded_profile = None
        self._saved_pack = None
        self.items.setRowCount(0)
        self.status.setText("Reading collection details from Steam…")
        self._worker = CollectionWorker(value)
        self._worker.result_ready.connect(self._show_collection)
        self._worker.failed.connect(self._show_failure)
        self._worker.finished.connect(self._finished)
        self._set_busy(True)
        self._worker.start()

    def _show_collection(self, collection: WorkshopCollectionResult) -> None:
        self._collection = collection
        self._plan = resolve_collection_import(collection, self._scan_result)
        saved_pack = self._matching_saved_pack(collection)
        self._saved_pack = saved_pack
        if saved_pack is not None:
            self.profile_name.setText(saved_pack.name)
        elif not self.profile_name.text().strip():
            self.profile_name.setText(
                self._unique_profile_name(
                    f"Steam Collection {collection.collection_id}",
                    collection.collection_id,
                )
            )
        self.items.setRowCount(0)
        installed = set(self._plan.installed_ids)
        cached_ids = (
            {item.workshop_id for item in saved_pack.collection_content}
            if saved_pack is not None
            else set()
        )
        downloaded_ids = self._downloaded_item_ids(collection)
        local_items = {
            item.workshop_id: item for item in self._scan_result.workshop_items
        }
        rows: list[tuple[str, str, str, str, str]] = []
        for metadata in collection.items:
            local = local_items.get(metadata.workshop_id)
            ids = (
                ", ".join(entry.mod_id for entry in local.entries if entry.mod_id)
                if local
                else "—"
            )
            rows.append(
                (
                    metadata.title,
                    metadata.workshop_id,
                    "Yes" if metadata.workshop_id in installed else "No",
                    self._download_status(
                        metadata.workshop_id,
                        downloaded_ids,
                        cached_ids,
                        saved_pack,
                    ),
                    ids or "No Mod IDs",
                )
            )
        rows.extend(
            ("Unavailable or nested item", item_id, "No", "—", "—")
            for item_id in collection.unavailable_ids
        )
        rows.extend(
            ("Other Steam app", item_id, "—", "—", "Not imported")
            for item_id in collection.foreign_app_ids
        )
        for row_data in rows:
            row = self.items.rowCount()
            self.items.insertRow(row)
            for column, value in enumerate(row_data):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.items.setItem(row, column, cell)

        self._update_open_workshop_page_enabled()
        self._update_create_enabled()
        missing = len(self._plan.missing_ids)
        ambiguous = len(self._plan.ambiguous_mod_ids)
        self.status.setText(
            f"Collection {collection.collection_id}: "
            f"{counted(len(collection.items), 'Project Zomboid item')}; "
            f"{counted(len(self._plan.installed_ids), 'Workshop item')} installed locally; "
            f"{counted(missing, 'missing or unavailable item')}; "
            f"{counted(len(self._plan.mod_ids), 'unique Mod ID')} found in selected folders."
            + (
                f" Excluded {counted(ambiguous, 'duplicate Mod ID')}."
                if ambiguous
                else ""
            )
        )
        if saved_pack is not None:
            self.status.setText(
                self.status.text()
                + f" Downloaded content is already saved in Mod Pack '{saved_pack.name}'. Load it from Mod Packs to make these mods available."
            )
        elif downloaded_ids:
            self.status.setText(
                self.status.text()
                + f" {counted(len(downloaded_ids), 'Workshop item')} already downloaded privately; importing will reuse them."
            )

    def _show_failure(self, message) -> None:
        if not self._closing:
            self.status.setText(f"Collection import could not finish: {message}")

    def _profile_name_changed(self, name: str) -> None:
        if self._saved_pack is not None and name != self._saved_pack.name:
            self._saved_pack = None
        self._update_create_enabled()

    def _update_create_enabled(self) -> None:
        ready = (
            self._worker is None
            and self._plan is not None
            and bool(self.profile_name.text().strip())
        )
        self.import_button.setEnabled(ready and bool(self._plan.workshop_ids))
        self.install_button.setEnabled(ready and bool(self._collection.items))
        if self._downloaded_profile is not None:
            self.install_button.setText("Retry Save")
            self.install_button.setAccessibleName(
                "Retry saving the collection Mod Pack"
            )
        elif self._saved_pack is not None:
            self.install_button.setText("Update Saved Pack")
            self.install_button.setAccessibleName(
                f"Update saved collection Mod Pack {self._saved_pack.name}"
            )
        else:
            self.install_button.setText("Download && Import")
            self.install_button.setAccessibleName(
                "Download and import collection without subscriptions"
            )

    def _matching_saved_pack(self, collection: WorkshopCollectionResult):
        if self._profile_store is None:
            return None
        collection_ids = {item.workshop_id for item in collection.items}
        if not collection_ids:
            return None
        try:
            names = self._profile_store.list_names()
        except OSError:
            return None
        for name in names:
            try:
                profile = self._profile_store.load(name)
            except OSError, ProfileError:
                continue
            referenced_ids = {item.workshop_id for item in profile.collection_content}
            if (
                set(profile.workshop_ids) == collection_ids
                and referenced_ids == collection_ids
            ):
                return profile
        return None

    def _downloaded_item_ids(self, collection: WorkshopCollectionResult) -> set[str]:
        tool_root = getattr(self._downloader, "root", None)
        if not isinstance(tool_root, Path):
            return set()
        workshop_root = tool_root / "steamapps/workshop/content/108600"
        return installed_collection_ids(collection, [workshop_root])

    @staticmethod
    def _download_status(item_id, downloaded_ids, cached_ids, saved_pack):
        downloaded = item_id in downloaded_ids
        saved = item_id in cached_ids
        if saved and saved_pack is not None:
            return (
                f"Downloaded · {saved_pack.name}"
                if downloaded
                else f"Saved · {saved_pack.name}"
            )
        return "Downloaded" if downloaded else "—"

    def _unique_profile_name(self, suggested: str, collection_id: str) -> str:
        if self._profile_store is None:
            return suggested
        try:
            names = {name.casefold() for name in self._profile_store.list_names()}
        except OSError:
            return suggested
        if suggested.casefold() not in names:
            return suggested
        suffix = f" (Workshop {collection_id})"
        base = suggested[: 80 - len(suffix)].rstrip()
        candidate = f"{base}{suffix}"
        sequence = 2
        while candidate.casefold() in names:
            suffix = f" (Workshop {collection_id} {sequence})"
            base = suggested[: 80 - len(suffix)].rstrip()
            candidate = f"{base}{suffix}"
            sequence += 1
        return candidate

    def _selected_missing_workshop_id(self) -> str | None:
        row = self.items.currentRow()
        if row < 0:
            return None
        title = self.items.item(row, 0)
        workshop_id = self.items.item(row, 1)
        installed = self.items.item(row, 2)
        saved_pack = self.items.item(row, 3)
        if (
            title is None
            or title.text() == "Other Steam app"
            or workshop_id is None
            or not workshop_id.text().isdecimal()
            or installed is None
            or installed.text() != "No"
            or (saved_pack is not None and saved_pack.text() != "—")
        ):
            return None
        return workshop_id.text()

    def _update_open_workshop_page_enabled(self, *_args) -> None:
        self.open_missing_workshop_button.setEnabled(
            self._selected_missing_workshop_id() is not None
        )

    def _open_selected_missing_workshop_item(self) -> None:
        workshop_id = self._selected_missing_workshop_id()
        if workshop_id is None:
            return
        QDesktopServices.openUrl(
            QUrl(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
            )
        )

    def _set_busy(self, busy) -> None:
        for widget in (self.fetch_button, self.collection_input, self.profile_name):
            widget.setEnabled(not busy)
        self.download_progress.setVisible(busy)
        self.close_button.setText("Stop Import" if self._installing else "Close")
        self._update_create_enabled()

    def _start_install(self) -> None:
        if self._worker is not None or self._collection is None:
            return
        if self._downloaded_profile is not None:
            self._save(
                replace(self._downloaded_profile, name=self.profile_name.text().strip())
            )
            return
        if self._collection.unavailable_ids:
            self.status.setText(
                "This collection has unavailable items. A complete private pack cannot be created. Retry reading the collection, or explicitly save an installed-only list."
            )
            return
        try:
            validate_profile(ModProfile(self.profile_name.text().strip(), ()))
        except ProfileError as exc:
            self.status.setText(str(exc))
            return
        self._installing = True
        self.status.setText(
            "Preparing private collection downloads. Steam subscriptions stay unchanged…"
        )
        self._worker = CollectionDownloadWorker(
            self._collection,
            self.profile_name.text().strip(),
            self._store,
            self._downloader,
        )
        self._worker.result_ready.connect(self._download_ready)
        self._worker.failed.connect(self._show_failure)
        self._worker.progress.connect(self.status.setText)
        self._worker.finished.connect(self._finished)
        self._set_busy(True)
        self._worker.start()

    def _download_ready(self, profile) -> None:
        if self._closing:
            return
        self._downloaded_profile = profile
        self._save(profile)

    def _save(self, profile) -> None:
        try:
            validate_profile(profile)
        except ProfileError as exc:
            self.status.setText(str(exc))
            return
        if self._save_profile is None:
            self.status.setText(
                "Downloaded content is preserved, but this window has no Mod Pack storage connection, so no pack was saved."
            )
            return
        if not self._save_profile(profile):
            if self._saved_pack is not None and profile.name == self._saved_pack.name:
                self.status.setText(
                    f"The existing Mod Pack '{self._saved_pack.name}' was kept unchanged. New private downloads are retained. Rename the pack to save a separate copy, or use Retry Save."
                )
            else:
                self.status.setText(
                    "The pack was not saved. Private downloads are retained. Change its name or use Retry Save."
                )
            return
        self.collection_imported.emit(profile)
        self.accept()

    def _create_profile(self) -> None:
        if self._plan is None:
            return
        if (
            self._plan.missing_ids
            and QMessageBox.question(
                self,
                "Save an incomplete installed list?",
                "Missing items have no Mod IDs in this list. No private download will be made. Save this partial list?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._save(
            ModProfile(
                self.profile_name.text().strip(),
                self._plan.mod_ids,
                self._plan.workshop_ids,
            )
        )

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        worker.deleteLater()
        self._installing = False
        if self._closing:
            self.done(self._pending_result)
        else:
            self._set_busy(False)

    def done(self, result) -> None:
        if (
            not self._closing
            and self._installing
            and result != QDialog.DialogCode.Accepted
            and QMessageBox.question(
                self,
                "Stop collection import?",
                "Stop downloading? Completed shared content and partial SteamCMD downloads are retained for retry. No subscriptions were changed.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._closing = True
        self._pending_result = result
        if self._worker is not None:
            self._worker.requestInterruption()
            self.status.setText("Stopping after the current download or request…")
            return
        super().done(result)
