"""Selection and management window for saved Mod Packs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    parse_profile,
)
from zomboid_mod_manager.ui.change_preview import format_ordered_list_change
from zomboid_mod_manager.ui.text import counted
from zomboid_mod_manager.ui.theme import apply_theme


class PackListWidget(QListWidget):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.count():
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#9bacaa"))
        painter.drawText(
            self.viewport().rect().adjusted(20, 20, -20, -20),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            "NO SAVED MOD PACKS\nUse Save as Pack in the workspace, import a pack, or create one from a Workshop collection.",
        )


class ModPacksDialog(QDialog):
    """Let the user choose a pack to apply or manage saved packs."""

    def __init__(
        self,
        profile_store: ProfileStore,
        parent=None,
        *,
        current_mod_ids: tuple[str, ...] | None = None,
        current_map_ids: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile_store = profile_store
        self._current_mod_ids = current_mod_ids
        self._current_map_ids = current_map_ids
        self.selected_pack: ModProfile | None = None
        self.setWindowTitle("Mod Packs")
        self.resize(780, 600)
        self.setMinimumSize(620, 460)
        apply_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("Saved Mod Packs")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Select a pack, then choose Apply. Collection packs first prepare their local mod files. This updates the global "
            "Zomboid/mods/default.txt file and creates a timestamped backup."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.pack_list = PackListWidget()
        self.pack_list.setAccessibleName("Saved Mod Packs")
        self.pack_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.pack_list.itemSelectionChanged.connect(self._update_selection)
        layout.addWidget(self.pack_list, 1)

        self.details = QLabel("Select a Mod Pack to preview its order and changes.")
        self.details.setObjectName("secondaryText")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.pack_preview = QPlainTextEdit()
        self.pack_preview.setReadOnly(True)
        self.pack_preview.setAccessibleName(
            "Selected Mod Pack contents and global list changes"
        )
        self.pack_preview.setPlaceholderText("Mod IDs and changes appear here.")
        self.pack_preview.setMinimumHeight(100)
        layout.addWidget(self.pack_preview, 2)

        self.status = QLabel()
        self.status.setObjectName("secondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.load_apply_button = QPushButton("Apply")
        self.load_apply_button.setDefault(True)
        self.load_apply_button.setToolTip(
            "Write this Mod Pack to the global default list after creating a backup."
        )
        self.load_apply_button.clicked.connect(self._load_selected_pack)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.clicked.connect(self._delete_selected_pack)
        self.import_button = QPushButton("Import…")
        self.import_button.clicked.connect(self._import_pack)
        actions.addWidget(self.import_button)
        self.export_button = QPushButton("Export…")
        self.export_button.clicked.connect(self._export_selected_pack)
        actions.addWidget(self.export_button)
        self.more_button = QPushButton("Restore…")
        self.more_button.clicked.connect(self._show_restore_menu)
        actions.addWidget(self.more_button)
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)
        commit_actions = QHBoxLayout()
        commit_actions.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        commit_actions.addWidget(self.close_button)
        self.load_apply_button.setObjectName("primaryAction")
        commit_actions.addWidget(self.load_apply_button)
        layout.addLayout(commit_actions)

        self._refresh_packs()

    def _selected_name(self) -> str:
        item = self.pack_list.currentItem()
        return item.text() if item is not None else ""

    def _refresh_packs(self, selected: str | None = None) -> None:
        current = selected or self._selected_name()
        self.pack_list.clear()
        self.pack_list.addItems(self._profile_store.list_names())
        if current:
            match = self.pack_list.findItems(current, Qt.MatchFlag.MatchExactly)
            if match:
                self.pack_list.setCurrentItem(match[0])
        self._update_selection()

    def _update_selection(self) -> None:
        name = self._selected_name()
        enabled = bool(name)
        self.delete_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.load_apply_button.setEnabled(False)
        has_packs = self.pack_list.count() > 0
        self.details.setVisible(has_packs)
        self.pack_preview.setVisible(has_packs)
        if not name:
            self.details.setText(
                "Select a Mod Pack to preview its order and changes."
                if has_packs
                else ""
            )
            self.pack_preview.clear()
            return
        try:
            profile = self._profile_store.load(name)
        except (OSError, ProfileError) as exc:
            self.details.setText(f"Could not read Mod Pack '{name}': {exc}")
            self.pack_preview.clear()
            return
        self.details.setText(
            f"{counted(len(profile.mod_ids), 'Mod ID')} in saved order · "
            f"{counted(len(profile.workshop_ids), 'Workshop item')} · "
            + (
                f"{counted(len(profile.map_ids), 'Map ID')} in saved order"
                if profile.map_ids is not None
                else "map list not saved (current maps stay unchanged)"
            )
        )
        self.load_apply_button.setText(
            "Load && Apply…" if profile.collection_content else "Apply"
        )
        sections = [
            "LOAD ORDER",
            *(
                f"{index}. {mod_id}"
                for index, mod_id in enumerate(profile.mod_ids, start=1)
            ),
        ]
        if not profile.mod_ids:
            sections.append("No Mod IDs saved")
        sections.extend(["", "WORKSHOP ITEMS", *(profile.workshop_ids or ("None",))])
        sections.extend(["", "MAPS"])
        sections.extend(
            (profile.map_ids or ("None (saved empty list)",))
            if profile.map_ids is not None
            else ("Not saved; current maps will be preserved",)
        )
        if self._current_mod_ids is not None:
            sections.extend(["", "CHANGES TO GLOBAL LIST"])
            sections.extend(
                format_ordered_list_change(
                    "Mod IDs", self._current_mod_ids, profile.mod_ids
                )
            )
            if self._current_map_ids is not None:
                resulting_maps = (
                    self._current_map_ids
                    if profile.map_ids is None
                    else profile.map_ids
                )
                sections.extend(
                    format_ordered_list_change(
                        "Maps", self._current_map_ids, resulting_maps
                    )
                )
        self.pack_preview.setPlainText("\n".join(sections))
        self.load_apply_button.setEnabled(True)

    def _load_selected_pack(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            self.selected_pack = self._profile_store.load(name)
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not load Mod Pack", str(exc))
            return
        self.accept()

    def _delete_selected_pack(self) -> None:
        name = self._selected_name()
        if not name:
            return
        answer = QMessageBox.question(
            self,
            "Delete Mod Pack",
            f"Move '{name}' to the recoverable deleted-Mod-Pack archive?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._profile_store.delete(name)
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not delete Mod Pack", str(exc))
            return
        self.status.setText(f"Deleted '{name}'. It can be restored from the archive.")
        self._refresh_packs()

    def _import_pack(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Import Mod Pack",
            str(Path.home()),
            "Mod Packs (*.json);;JSON files (*.json)",
        )
        if not source:
            return
        try:
            profile = parse_profile(Path(source).read_bytes())
            overwrite = False
            if profile.name in self._profile_store.list_names():
                answer = QMessageBox.question(
                    self,
                    "Replace imported Mod Pack",
                    f"'{profile.name}' already exists. Replace it and keep a backup?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                overwrite = True
            self._profile_store.save(profile, overwrite=overwrite)
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not import Mod Pack", str(exc))
            return
        self.status.setText(f"Imported Mod Pack '{profile.name}'.")
        self._refresh_packs(profile.name)

    def _export_selected_pack(self) -> None:
        name = self._selected_name()
        if not name:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export Mod Pack",
            f"{name}.json",
            "Mod Packs (*.json)",
        )
        if not destination:
            return
        path = Path(destination)
        overwrite = False
        if path.exists():
            answer = QMessageBox.question(
                self,
                "Replace exported file",
                "The destination exists. Replace it and keep a timestamped backup?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self._profile_store.export(name, path, overwrite=overwrite)
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not export Mod Pack", str(exc))
            return
        self.status.setText(f"Exported Mod Pack '{name}' to {path}.")

    def _show_restore_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Restore Deleted Pack…", self._restore_deleted_pack)
        menu.addAction("Restore Previous Version…", self._restore_pack_backup)
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    def _restore_deleted_pack(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Restore deleted Mod Pack",
            str(self._profile_store.deleted_root),
            "Archived Mod Packs (*.json.*);;All files (*.*)",
        )
        if not source:
            return
        try:
            profile = self._profile_store.restore_deleted(Path(source))
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not restore Mod Pack", str(exc))
            return
        self.status.setText(f"Restored Mod Pack '{profile.name}'.")
        self._refresh_packs(profile.name)

    def _restore_pack_backup(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Restore a previous Mod Pack version",
            str(self._profile_store.backup_root),
            "Mod Pack backups (*.json.*);;All files (*.*)",
        )
        if not source:
            return
        try:
            profile = parse_profile(Path(source).read_bytes())
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not read Mod Pack backup", str(exc))
            return
        if profile.name in self._profile_store.list_names():
            answer = QMessageBox.question(
                self,
                "Restore Mod Pack backup",
                f"Replace '{profile.name}' with this version? The current version will also be backed up.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._profile_store.restore_backup(profile.name, Path(source))
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not restore Mod Pack backup", str(exc))
            return
        self.status.setText(f"Restored previous version of '{profile.name}'.")
        self._refresh_packs(profile.name)
