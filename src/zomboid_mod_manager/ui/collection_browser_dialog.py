"""Native searchable Steam collection catalog; selection feeds the existing importer."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from zomboid_mod_manager.workshop_catalog import (
    COLLECTION_SORTS,
    CollectionPage,
    browse_collections,
)

from .theme import apply_theme
from .window_workers import DiagnosticWorker


class CollectionBrowserDialog(QDialog):
    def __init__(self, parent=None, *, mods=False) -> None:
        super().__init__(parent)
        self.mods = mods
        self.setWindowTitle(
            "Browse Project Zomboid Mods"
            if mods
            else "Browse Project Zomboid Collections"
        )
        self.resize(1080, 700)
        self.setMinimumSize(740, 500)
        apply_theme(self)
        self.selected_collection = None
        self._worker = None
        self._page = None
        self._query = ("", "trend", "")
        self._closing = False
        layout = QVBoxLayout(self)
        heading = QLabel(
            "Find mods to install locally" if mods else "Find your next Mod Pack"
        )
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        note = QLabel(
            "Install Workshop mods into your local-mod folder without subscribing. Installed mods stay available across pack changes."
            if mods
            else "Browse public Project Zomboid collections. Download privately without changing Steam subscriptions."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search mods by name or description"
            if mods
            else "Search collections by name or description"
        )
        self.search.setAccessibleName(
            "Search Workshop mods" if mods else "Search Workshop collections"
        )
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._new_search)
        controls.addWidget(self.search, 1)
        self.sort = QComboBox()
        self.sort.setAccessibleName("Workshop sort")
        for label, value in COLLECTION_SORTS.items():
            self.sort.addItem(label, value)
        self.sort.currentIndexChanged.connect(self._new_search)
        controls.addWidget(self.sort)
        self.build = QComboBox()
        self.build.setAccessibleName("Workshop build tag")
        self.build.addItem("All builds", "")
        self.build.addItem("Build 41", "Build 41")
        self.build.addItem("Build 42", "Build 42")
        self.build.currentIndexChanged.connect(self._new_search)
        controls.addWidget(self.build)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._new_search)
        controls.addWidget(self.search_button)
        layout.addLayout(controls)
        self.status = QLabel("Loading mods…" if mods else "Loading collections…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setAccessibleName(
            "Workshop mods" if mods else "Workshop collections"
        )
        self.table.setHorizontalHeaderLabels(
            ["Mod", "Author", "Subscribers", "Favorites", "Updated"]
            if mods
            else ["Collection", "Creator", "Items", "Favorites", "Updated"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self._choose())
        splitter.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName(
            "Selected mod description and tags"
            if mods
            else "Selected collection description and tags"
        )
        self.details.setPlaceholderText(
            "Select a mod to read its description and build tags."
            if mods
            else "Select a collection to read its description and build tags."
        )
        splitter.addWidget(self.details)
        splitter.setSizes([360, 150])
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.previous = QPushButton("Previous")
        self.previous.clicked.connect(lambda: self._load(self._page.page - 1))
        actions.addWidget(self.previous)
        self.page_label = QLabel()
        actions.addWidget(self.page_label)
        self.next = QPushButton("Next")
        self.next.clicked.connect(lambda: self._load(self._page.page + 1))
        actions.addWidget(self.next)
        actions.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.choose = QPushButton("Install Locally…" if mods else "Review && Import…")
        self.choose.setObjectName("primaryAction")
        self.choose.setEnabled(False)
        self.choose.clicked.connect(self._choose)
        actions.addWidget(self.choose)
        layout.addLayout(actions)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        QTimer.singleShot(0, self._new_search)

    def _new_search(self, *_args) -> None:
        if self._worker is not None:
            return
        self._query = (
            self.search.text().strip(),
            self.sort.currentData(),
            self.build.currentData(),
        )
        self._load(1)

    def _load(self, page: int) -> None:
        if self._worker is not None or self._closing:
            return
        search, sort, build = self._query
        self._set_busy(True)
        self.status.setText(
            "Loading mods from Steam…"
            if self.mods
            else "Loading collections from Steam…"
        )
        self._worker = DiagnosticWorker(
            lambda: browse_collections(
                search,
                sort=sort,
                build=build,
                page=page,
                **({"mods": True} if self.mods else {}),
            )
        )
        self._worker.result_ready.connect(self._show_page)
        self._worker.failed.connect(self._failed)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.search,
            self.search_button,
            self.sort,
            self.build,
            self.table,
        ):
            widget.setEnabled(not busy)
        self.previous.setEnabled(
            not busy and self._page is not None and self._page.page > 1
        )
        self.next.setEnabled(
            not busy
            and self._page is not None
            and self._page.page < self._page.total_pages
        )
        self.choose.setEnabled(not busy and self.table.currentRow() >= 0)

    def _show_page(self, page: CollectionPage) -> None:
        self._page = page
        self.table.setRowCount(0)
        self.details.clear()
        for collection in page.collections:
            row = self.table.rowCount()
            self.table.insertRow(row)
            try:
                updated = (
                    datetime.fromtimestamp(collection.updated_at).strftime("%Y-%m-%d")
                    if collection.updated_at
                    else "Unknown"
                )
            except ValueError, OSError, OverflowError:
                updated = "Unknown"
            values = (
                collection.title,
                collection.author,
                (
                    f"{collection.subscribers:,}"
                    if collection.subscribers is not None
                    else "Not supplied"
                )
                if self.mods
                else str(collection.item_count),
                f"{collection.favorites:,}",
                updated,
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
        self.page_label.setText(f"Page {page.page} of {page.total_pages}")
        self.status.setText(
            f"{len(page.collections)} {'mods' if self.mods else 'collections'} shown. Build tags are supplied by creators and do not prove compatibility."
            if page.collections
            else (
                "No mods match. Try a different search or build tag."
                if self.mods
                else "No collections match. Try a different search or build tag."
            )
        )

    def _selection_changed(self, *_args) -> None:
        row = self.table.currentRow()
        valid = self._page is not None and 0 <= row < len(self._page.collections)
        self.choose.setEnabled(valid and self._worker is None)
        if valid:
            collection = self._page.collections[row]
            count = (
                (
                    f"{collection.subscribers:,} subscribers"
                    if collection.subscribers is not None
                    else "Subscriber count not supplied"
                )
                if self.mods
                else f"{collection.item_count} items"
            )
            self.details.setPlainText(
                f"{collection.title}\nBy {collection.author} · {count}\n\n{collection.description}\n\nTags: {', '.join(collection.tags) or 'Not supplied'}\nWorkshop ID: {collection.workshop_id}"
            )

    def _choose(self) -> None:
        row = self.table.currentRow()
        if (
            self._worker is None
            and self._page is not None
            and 0 <= row < len(self._page.collections)
        ):
            self.selected_collection = self._page.collections[row]
            self.accept()

    def _failed(self, message: str) -> None:
        self.status.setText(
            f"Could not load Workshop catalog: {message} Search again to retry."
        )
        self._page = None
        self.table.setRowCount(0)
        self.details.clear()
        self.page_label.clear()

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        worker.deleteLater()
        if self._closing:
            self.reject()
        else:
            self._set_busy(False)

    def done(self, result: int) -> None:
        if self._worker is not None:
            self._closing = True
            self.status.setText("Finishing the current Steam request before closing…")
            return
        super().done(result)
