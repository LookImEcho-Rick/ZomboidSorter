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
            "Find a public collection, review its mods, and import it as a reusable Mod Pack. "
            "Downloads use a shared private cache without changing your Steam subscriptions."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("secondaryText")
        layout.addWidget(instructions)
        steps = QLabel(
            "1  Find a collection     2  Download privately     3  Load your Mod Pack when ready"
        )
        steps.setObjectName("workflowHint")
        steps.setWordWrap(True)
        layout.addWidget(steps)
        self.import_workshop_collection_button = QPushButton("Browse Collections…")
        self.import_workshop_collection_button.setObjectName("primaryAction")
        self.import_workshop_collection_button.setToolTip(
            "Search, sort, and review public Workshop collections without browsing Steam pages."
        )
        self.import_workshop_collection_button.setEnabled(True)
        self.import_workshop_collection_button.clicked.connect(
            self._browse_workshop_collections
        )
        direct = QPushButton("Import Collection URL…")
        direct.clicked.connect(lambda: self._import_workshop_collection())
        layout.addWidget(
            self.import_workshop_collection_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(direct, 0, Qt.AlignmentFlag.AlignLeft)
        self.collection_import_status = QLabel(
            "Imported downloads stay hidden until you load the pack from Mod Packs."
        )
        self.collection_import_status.setWordWrap(True)
        self.collection_import_status.setObjectName("secondaryText")
        layout.addWidget(self.collection_import_status)
        layout.addStretch(1)
        return page
