"""Filterable, source-backed file-overlap results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager.diagnostics.file_overlaps import (
    FileOverlapPathGroup,
    FileOverlapReport,
)

_PAGE_SIZE = 250


class FileOverlapDialog(QDialog):
    def __init__(self, report: FileOverlapReport, parent: QWidget | None = None):
        super().__init__(parent)
        self._report = report
        self._visible_groups: list[FileOverlapPathGroup] = []
        self._displayed_group_count = 0
        self.setWindowTitle("Potential File Overlaps")
        self.resize(1050, 680)
        self.setMinimumSize(820, 520)

        layout = QVBoxLayout(self)
        self.summary = QLabel(self._summary_text())
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by shared path or Mod ID")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Filter overlap paths and Mod IDs")
        filters.addWidget(self.search, 1)

        filters.addWidget(QLabel("Content status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("All findings", "all")
        self.status_filter.addItem("Different content", "different")
        self.status_filter.addItem("Comparison unavailable", "unverified")
        self.status_filter.setAccessibleName("Filter overlap content status")
        filters.addWidget(self.status_filter)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Shared path", "Pairs", "Different", "Unverified", "Mod IDs"]
        )
        self.table.setAccessibleName("Grouped file overlap findings")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 400)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 85)
        self.table.setColumnWidth(3, 95)
        layout.addWidget(self.table, 3)

        result_controls = QHBoxLayout()
        self.result_status = QLabel()
        result_controls.addWidget(self.result_status, 1)
        self.load_more_button = QPushButton(f"Load {_PAGE_SIZE} more paths")
        self.load_more_button.clicked.connect(self._load_more_groups)
        result_controls.addWidget(self.load_more_button)
        layout.addLayout(result_controls)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a shared path to view source examples.")
        self.details.setAccessibleName("Selected overlap source examples")
        layout.addWidget(self.details, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._refresh_rows)
        self.status_filter.currentIndexChanged.connect(self._refresh_rows)
        self.table.currentCellChanged.connect(self._show_selected_group)
        self._refresh_rows()

    def _summary_text(self) -> str:
        text = (
            f"{self._report.overlap_count} potential file-overlap pairs across "
            f"{self._report.unique_path_count} shared paths: "
            f"{self._report.different_count} comparisons found different content and "
            f"{self._report.unverified_count} could not be compared."
        )
        target = {
            "all": "all metadata candidates",
            "41": "Build 41 root metadata",
            "42": "Build 42 preview metadata",
        }.get(self._report.target_build, f"Build {self._report.target_build}")
        mod_scope = (
            "staged active mods" if self._report.staged_only else "all discovered mods"
        )
        text += (
            f"\nScope: {mod_scope}; {target}; {self._report.entry_count} mod entries."
        )
        if self._report.truncated:
            text += " Analysis reached a safety limit, so totals may be incomplete."
        if self._report.path_groups_limited:
            text += f" Showing the {len(self._report.path_groups)} paths with the most pairs."
        return text

    def _refresh_rows(self) -> None:
        query = self.search.text().casefold().strip()
        selected_status = self.status_filter.currentData()
        self._visible_groups = [
            group
            for group in self._report.path_groups
            if (
                not query
                or query in group.relative_path.casefold()
                or any(query in mod_id.casefold() for mod_id in group.mod_ids)
            )
            and (
                selected_status == "all"
                or (selected_status == "different" and group.different_count > 0)
                or (selected_status == "unverified" and group.unverified_count > 0)
            )
        ]
        self._displayed_group_count = 0
        self.table.setRowCount(0)
        self._load_more_groups()
        if self._visible_groups:
            self.table.selectRow(0)
            self._show_selected_group(0, 0, -1, -1)
        else:
            self.details.clear()
            if self._report.path_groups:
                self.details.setPlainText("No shared paths match these filters.")

    def _load_more_groups(self) -> None:
        start = self._displayed_group_count
        end = min(start + _PAGE_SIZE, len(self._visible_groups))
        self.table.setRowCount(end)
        for row in range(start, end):
            group = self._visible_groups[row]
            visible_mod_ids = ", ".join(group.mod_ids[:5])
            if len(group.mod_ids) > 5:
                visible_mod_ids += f", +{len(group.mod_ids) - 5} more"
            values = (
                group.relative_path,
                str(group.comparison_count),
                str(group.different_count),
                str(group.unverified_count),
                visible_mod_ids,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, group)
                self.table.setItem(row, column, item)
        self._displayed_group_count = end
        self.load_more_button.setVisible(end < len(self._visible_groups))
        self.result_status.setText(
            f"Showing {end} of {len(self._visible_groups)} matching paths; "
            f"search covers all {len(self._report.path_groups)} analyzed paths."
        )

    def _show_selected_group(
        self, row: int, _column: int, _previous_row: int, _previous_column: int
    ) -> None:
        if row < 0 or row >= len(self._visible_groups):
            self.details.clear()
            return
        group = self._visible_groups[row]
        mod_ids = ", ".join(group.mod_ids) or "Unknown Mod ID"
        lines = [
            f"Shared path: {group.relative_path}",
            f"Mod IDs: {mod_ids}",
            f"Pairs: {group.comparison_count} · Different: {group.different_count} · Unverified: {group.unverified_count}",
            "",
            "Example source comparisons:",
        ]
        for index, overlap in enumerate(group.examples, start=1):
            relation = (
                "different content"
                if overlap.content_relation == "different"
                else "content comparison unavailable"
            )
            lines.extend(
                (
                    f"{index}. {overlap.first_mod_id} ↔ {overlap.second_mod_id} ({relation})",
                    f"   {overlap.first_file} ({overlap.first_candidate})",
                    f"   {overlap.second_file} ({overlap.second_candidate})",
                )
            )
        lines.append(
            "\nThese are path/content overlaps, not a guarantee of an in-game conflict."
        )
        self.details.setPlainText("\n".join(lines))
