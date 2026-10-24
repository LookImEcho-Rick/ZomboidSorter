"""Read-only Steam collection import dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from zomboid_mod_manager.domain import ScanResult
from zomboid_mod_manager.profiles import ModProfile, ProfileError, validate_profile
from zomboid_mod_manager.ui.theme import apply_theme
from zomboid_mod_manager.workshop import (
    WorkshopCollectionResult,
    WorkshopImportPlan,
    fetch_collection,
    resolve_collection_import,
)


class CollectionWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, collection_text: str) -> None:
        super().__init__()
        self._collection_text = collection_text

    def run(self) -> None:
        try:
            self.result_ready.emit(
                fetch_collection(self._collection_text, timeout=5.0, max_items=200)
            )
        except Exception as exc:  # noqa: BLE001 - Steam/JSON failures are rendered in the dialog.
            self.failed.emit(str(exc))


class WorkshopCollectionDialog(QDialog):
    collection_imported = Signal(object)

    def __init__(self, scan_result: ScanResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Steam Workshop collection")
        self.resize(800, 540)
        apply_theme(self)
        self._scan_result = scan_result
        self._worker: CollectionWorker | None = None
        self._collection: WorkshopCollectionResult | None = None
        self._plan: WorkshopImportPlan | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("Review a Workshop Collection")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        explanation = QLabel(
            "Enter a public collection URL or ID, review which items are installed, "
            "then save the matching Mod IDs as a Mod Pack. Steam remains responsible for subscriptions and downloads."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("secondaryText")
        layout.addWidget(explanation)
        input_row = QHBoxLayout()
        self.collection_input = QLineEdit()
        self.collection_input.setPlaceholderText(
            "Paste a Steam collection URL or numeric ID"
        )
        self.collection_input.setAccessibleName("Steam collection URL or ID")
        self.collection_input.setClearButtonEnabled(True)
        input_row.addWidget(self.collection_input, 1)
        self.fetch_button = QPushButton("Fetch Collection")
        self.fetch_button.clicked.connect(self._fetch)
        input_row.addWidget(self.fetch_button)
        layout.addLayout(input_row)

        self.status = QLabel("Ready. Collection contents are read-only.")
        self.status.setObjectName("secondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.items = QTableWidget(0, 4)
        self.items.setAccessibleName("Collection items and installation status")
        self.items.setHorizontalHeaderLabels(
            ["Workshop item", "Workshop ID", "Installed", "Contained Mod IDs"]
        )
        self.items.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.items.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.items.setAlternatingRowColors(True)
        self.items.horizontalHeader().setStretchLastSection(True)
        self.items.setColumnWidth(0, 270)
        self.items.setColumnWidth(1, 125)
        self.items.setColumnWidth(2, 90)
        self.items.currentCellChanged.connect(self._update_open_workshop_page_enabled)
        layout.addWidget(self.items, 1)

        item_actions = QHBoxLayout()
        item_actions.addStretch(1)
        self.open_missing_workshop_button = QPushButton("Open Selected Missing Item")
        self.open_missing_workshop_button.setAccessibleName(
            "Open the selected missing Workshop item page"
        )
        self.open_missing_workshop_button.setToolTip(
            "Open the selected missing Project Zomboid item in Steam Community. This does not subscribe or download it."
        )
        self.open_missing_workshop_button.setEnabled(False)
        self.open_missing_workshop_button.clicked.connect(
            self._open_selected_missing_workshop_item
        )
        item_actions.addWidget(self.open_missing_workshop_button)
        layout.addLayout(item_actions)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Save as Mod Pack"))
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("Mod Pack name")
        self.profile_name.setAccessibleName("Mod Pack name")
        self.profile_name.setMaxLength(80)
        self.profile_name.textChanged.connect(self._update_create_enabled)
        profile_row.addWidget(self.profile_name, 1)
        self.import_button = QPushButton("Create Mod Pack")
        self.import_button.setObjectName("primaryAction")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._create_profile)
        profile_row.addWidget(self.import_button)
        layout.addLayout(profile_row)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignRight)

    def _fetch(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        value = self.collection_input.text().strip()
        if not value:
            self.status.setText("Enter a Steam collection URL or numeric ID.")
            return
        self.fetch_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self._collection = None
        self._plan = None
        self.items.setRowCount(0)
        self.open_missing_workshop_button.setEnabled(False)
        self.status.setText("Fetching collection details from Steam…")
        self._worker = CollectionWorker(value)
        self._worker.result_ready.connect(self._show_collection)
        self._worker.failed.connect(self._show_failure)
        self._worker.finished.connect(lambda: self.fetch_button.setEnabled(True))
        self._worker.start()

    def _show_collection(self, collection: WorkshopCollectionResult) -> None:
        self._collection = collection
        self._plan = resolve_collection_import(collection, self._scan_result)
        if not self.profile_name.text().strip():
            self.profile_name.setText(f"Steam Collection {collection.collection_id}")
        self.items.setRowCount(0)
        installed = set(self._plan.installed_ids)
        local_items = {
            item.workshop_id: item for item in self._scan_result.workshop_items
        }
        rows: list[tuple[str, str, str, str]] = []
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
                    ids or "No Mod IDs",
                )
            )
        rows.extend(
            ("Unavailable or nested item", item_id, "No", "—")
            for item_id in collection.unavailable_ids
        )
        rows.extend(
            ("Other Steam app", item_id, "—", "Not imported")
            for item_id in collection.foreign_app_ids
        )
        for row_data in rows:
            row = self.items.rowCount()
            self.items.insertRow(row)
            for column, value in enumerate(row_data):
                self.items.setItem(row, column, QTableWidgetItem(value))

        self._update_open_workshop_page_enabled()
        self._update_create_enabled()
        missing = len(self._plan.missing_ids)
        ambiguous = len(self._plan.ambiguous_mod_ids)
        self.status.setText(
            f"Collection {collection.collection_id}: {len(collection.items)} Project Zomboid items, "
            f"{len(self._plan.installed_ids)} installed locally, {missing} missing/unavailable, "
            f"{len(self._plan.mod_ids)} unique Mod IDs ready to stage."
            + (f" {ambiguous} duplicate Mod IDs were excluded." if ambiguous else "")
        )

    def _show_failure(self, message: str) -> None:
        self._collection = None
        self._plan = None
        self.import_button.setEnabled(False)
        self.open_missing_workshop_button.setEnabled(False)
        self.items.setRowCount(0)
        self.status.setText(f"Could not read this collection: {message}")

    def _update_create_enabled(self) -> None:
        self.import_button.setEnabled(
            self._plan is not None
            and bool(self._plan.workshop_ids)
            and bool(self.profile_name.text().strip())
        )

    def _selected_missing_workshop_id(self) -> str | None:
        row = self.items.currentRow()
        if row < 0:
            return None
        title = self.items.item(row, 0)
        workshop_id = self.items.item(row, 1)
        installed = self.items.item(row, 2)
        if (
            title is None
            or title.text() == "Other Steam app"
            or workshop_id is None
            or not workshop_id.text().isdecimal()
            or installed is None
            or installed.text() != "No"
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

    def _create_profile(self) -> None:
        if self._collection is None or self._plan is None:
            return
        profile = ModProfile(
            self.profile_name.text().strip(),
            self._plan.mod_ids,
            self._plan.workshop_ids,
        )
        try:
            validate_profile(profile)
        except ProfileError as exc:
            QMessageBox.warning(self, "Invalid Mod Pack name", str(exc))
            return
        self.collection_imported.emit(profile)
        self.accept()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.status.setText(
                "Waiting for the current Steam request to finish before closing…"
            )
            self._worker.wait()
        event.accept()
