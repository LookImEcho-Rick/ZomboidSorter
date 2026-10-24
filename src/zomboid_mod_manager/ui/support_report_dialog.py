"""Preview and save a privacy-aware support report."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.support_report import format_support_report
from zomboid_mod_manager.ui.theme import apply_theme


class SupportReportDialog(QDialog):
    def __init__(self, report: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Support Report")
        self.resize(720, 620)
        apply_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("Review Support Report")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        privacy_note = QLabel(
            "Review before saving. This report omits folder paths, mod names and IDs, "
            "Workshop IDs, logs, and file contents."
        )
        privacy_note.setWordWrap(True)
        privacy_note.setObjectName("secondaryText")
        layout.addWidget(privacy_note)

        self.preview = QPlainTextEdit()
        self.preview.setAccessibleName("Redacted support report preview")
        self.preview.setReadOnly(True)
        self.preview.setPlainText(format_support_report(report))
        layout.addWidget(self.preview, 1)

        self.status = QLabel("")
        self.status.setObjectName("secondaryText")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save Report…")
        save_button.setObjectName("primaryAction")
        save_button.clicked.connect(self._save_report)
        buttons.addWidget(save_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _save_report(self) -> None:
        suggested_directory = Path.home() / "Documents"
        if not suggested_directory.is_dir():
            suggested_directory = Path.home()
        suggested_name = (
            "ZomboidSorter-support-"
            f"{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}.json"
        )
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Support Report",
            str(suggested_directory / suggested_name),
            "JSON support reports (*.json)",
        )
        if not selected:
            return
        destination = Path(selected)
        if not destination.suffix:
            destination = destination.with_suffix(".json")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(self.preview.toPlainText())
            os.replace(temporary_path, destination)
        except (OSError, ValueError) as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            QMessageBox.warning(
                self,
                "Could Not Save Support Report",
                f"The report could not be saved: {exc}",
            )
            return
        self.status.setText("Support report saved.")
