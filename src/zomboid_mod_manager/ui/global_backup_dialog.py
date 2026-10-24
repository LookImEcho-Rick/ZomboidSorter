"""Newest-first browser and preview for global Mod List backups."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.configuration import read_active_configuration_backup
from zomboid_mod_manager.gameio.active_mods import (
    ActiveModConfigError,
    ActiveModSnapshot,
)
from zomboid_mod_manager.ui.change_preview import format_ordered_list_change
from zomboid_mod_manager.ui.theme import apply_theme


class GlobalBackupDialog(QDialog):
    """Let the user inspect a timestamped backup before restoring it."""

    def __init__(
        self,
        snapshot: ActiveModSnapshot,
        backup_paths: tuple[Path, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._preview_path: Path | None = None
        self._preview_snapshot: ActiveModSnapshot | None = None
        self.selected_path: Path | None = None
        self.selected_backup: ActiveModSnapshot | None = None
        self.setWindowTitle("Global Mod List Backups")
        self.resize(820, 620)
        self.setMinimumSize(680, 500)
        apply_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("Global Mod List Backups")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Backups are listed newest first. Select one to preview its Mod IDs, maps, and changes to the loaded global list."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.backup_list = QListWidget()
        self.backup_list.setAccessibleName("Global mod list backups, newest first")
        self.backup_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.backup_list.setMinimumWidth(230)
        for backup_path in backup_paths:
            item = QListWidgetItem(self._display_time(backup_path))
            item.setData(Qt.ItemDataRole.UserRole, str(backup_path))
            item.setToolTip(backup_path.name)
            self.backup_list.addItem(item)
        self.backup_list.currentItemChanged.connect(self._show_selected_backup)
        body.addWidget(self.backup_list, 1)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Selected global backup contents and changes")
        self.preview.setPlaceholderText("Select a backup to preview its contents.")
        body.addWidget(self.preview, 2)
        layout.addLayout(body, 1)

        self.status = QLabel("Select a backup to inspect it.")
        self.status.setObjectName("secondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self.restore_button = QPushButton("Choose Backup…")
        self.restore_button.setObjectName("primaryAction")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self._accept_selected)
        buttons.addButton(self.restore_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)

        if self.backup_list.count():
            self.backup_list.setCurrentRow(0)

    @staticmethod
    def _display_time(path: Path) -> str:
        prefix = "default.txt.bak-"
        stamp = path.name.removeprefix(prefix)
        try:
            saved_at = datetime.strptime(stamp[:22], "%Y%m%d-%H%M%S-%f")
        except ValueError:
            return path.name
        return saved_at.strftime("%b %d, %Y  %I:%M:%S %p")

    def _show_selected_backup(self, item, _previous) -> None:
        self._preview_path = None
        self._preview_snapshot = None
        self.restore_button.setEnabled(False)
        if item is None:
            self.preview.clear()
            self.status.setText("Select a backup to inspect it.")
            return

        backup_path = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            backup = read_active_configuration_backup(self._snapshot, backup_path)
        except (OSError, ActiveModConfigError) as exc:
            self.preview.clear()
            self.status.setText(f"Could not read this backup: {exc}")
            return

        self._preview_path = backup_path
        self._preview_snapshot = backup
        self.restore_button.setEnabled(True)
        current = self._snapshot.config
        restored = backup.config
        lines = [
            f"BACKUP · {self._display_time(backup_path)}",
            f"{len(restored.mods)} Mod IDs · {len(restored.maps)} maps",
            "",
            "CHANGES TO LOADED GLOBAL LIST",
            *format_ordered_list_change("Mod IDs", current.mods, restored.mods),
            "",
            *format_ordered_list_change("Maps", current.maps, restored.maps),
            "",
            "MOD IDs IN BACKUP ORDER",
            *self._ordered_values(restored.mods),
            "",
            "MAPS IN BACKUP ORDER",
            *self._ordered_values(restored.maps),
        ]
        self.preview.setPlainText("\n".join(lines))
        self.status.setText(
            f"Ready to restore {len(restored.mods)} Mod IDs and {len(restored.maps)} maps."
        )

    @staticmethod
    def _ordered_values(values: tuple[str, ...]) -> list[str]:
        if not values:
            return ["None"]
        lines = [f"{index}. {value}" for index, value in enumerate(values[:40], 1)]
        if len(values) > 40:
            lines.append(f"…and {len(values) - 40} more")
        return lines

    def _accept_selected(self) -> None:
        if self._preview_path is None or self._preview_snapshot is None:
            return
        self.selected_path = self._preview_path
        self.selected_backup = self._preview_snapshot
        self.accept()
