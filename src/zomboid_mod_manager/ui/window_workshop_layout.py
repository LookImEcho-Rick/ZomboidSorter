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
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Turn the mods you already have from a public collection into a reusable Mod Pack. "
            "This reads collection details from Steam and never subscribes to or downloads items."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("secondaryText")
        layout.addWidget(instructions)
        steps = QLabel(
            "1  Scan your installed mods     2  Review collection items     3  Save a Mod Pack"
        )
        steps.setObjectName("workflowHint")
        steps.setWordWrap(True)
        layout.addWidget(steps)
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
