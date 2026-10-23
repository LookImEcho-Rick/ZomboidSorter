"""Build the Workshop collection import tab."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class WorkshopCollectionLayoutMixin:
    def _build_import_collection_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QLabel("Import a Steam Workshop Collection")
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Enter a public Project Zomboid Workshop collection URL or ID to "
            "review its items and save the installed mods as a Mod Pack. "
            "Workshop subscriptions and downloads are still handled by Steam."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.import_workshop_collection_button = QPushButton("Import Collection…")
        self.import_workshop_collection_button.setToolTip(
            "Read a public collection and save its installed mods as a Mod Pack."
        )
        self.import_workshop_collection_button.setEnabled(False)
        self.import_workshop_collection_button.clicked.connect(
            self._import_workshop_collection
        )
        layout.addWidget(
            self.import_workshop_collection_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.collection_import_status = QLabel(
            "Scan the library from Mod Workspace before importing a collection."
        )
        self.collection_import_status.setWordWrap(True)
        self.collection_import_status.setObjectName("secondaryText")
        layout.addWidget(self.collection_import_status)
        layout.addStretch(1)
        return page
