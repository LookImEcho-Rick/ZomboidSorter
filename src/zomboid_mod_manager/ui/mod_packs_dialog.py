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
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.domain import ScanResult
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    parse_profile,
)
from zomboid_mod_manager.ui.save_mod_pack_dialog import SaveModPackDialog
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
            "NO SAVED MOD PACKS\nSave a load order or import a pack or save list to get started.",
        )


class ModPacksDialog(QDialog):
    """Let the user choose a pack to apply or manage saved packs."""

    def __init__(
        self,
        profile_store: ProfileStore,
        parent=None,
        *,
        scan_result: ScanResult | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile_store = profile_store
        self._scan_result = scan_result
        self.selected_pack: ModProfile | None = None
        self.setWindowTitle("Mod Packs")
        self.resize(700, 500)
        self.setMinimumSize(560, 400)
        apply_theme(self)

        layout = QVBoxLayout(self)
        heading = QLabel("Saved Mod Packs")
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Select a pack, then choose Apply. This updates the global "
            "Zomboid/mods/default.txt file and creates a timestamped backup. "
            "Per-save and server lists are not changed."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.pack_list = PackListWidget()
        self.pack_list.setAccessibleName("Saved Mod Packs")
        self.pack_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.pack_list.itemSelectionChanged.connect(self._update_selection)
        layout.addWidget(self.pack_list, 1)

        self.details = QLabel("Select a saved Mod Pack to see its contents.")
        self.details.setObjectName("secondaryText")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

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
        actions.addWidget(self.delete_button)
        self.import_button = QPushButton("Import…")
        self.import_button.clicked.connect(self._import_pack)
        actions.addWidget(self.import_button)
        self.import_save_button = QPushButton("From Save…")
        self.import_save_button.setToolTip(
            "Read a save's mods.txt and save its order as an app-owned Mod Pack."
        )
        self.import_save_button.clicked.connect(self._import_from_save)
        actions.addWidget(self.import_save_button)
        self.export_button = QPushButton("Export…")
        self.export_button.clicked.connect(self._export_selected_pack)
        actions.addWidget(self.export_button)
        self.more_button = QPushButton("Restore…")
        self.more_button.clicked.connect(self._show_restore_menu)
        actions.addWidget(self.more_button)
        actions.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        self.load_apply_button.setObjectName("primaryAction")
        actions.addWidget(self.load_apply_button)
        layout.addLayout(actions)

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
        if not name:
            message = (
                "Select a saved Mod Pack to inspect and apply it."
                if self.pack_list.count()
                else ""
            )
            self.details.setText(message)
            return
        try:
            profile = self._profile_store.load(name)
        except (OSError, ProfileError) as exc:
            self.details.setText(f"Could not read Mod Pack '{name}': {exc}")
            return
        self.details.setText(
            f"{len(profile.mod_ids)} Mod IDs in saved order · "
            f"{len(profile.workshop_ids)} Workshop items"
        )
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

    def _import_from_save(self) -> None:
        dialog = SaveModPackDialog(scan_result=self._scan_result, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = dialog.selected_profile
        if profile is None:
            return
        overwrite = False
        if profile.name in self._profile_store.list_names():
            answer = QMessageBox.question(
                self,
                "Replace Mod Pack",
                f"'{profile.name}' already exists. Replace it and keep a backup?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self._profile_store.save(profile, overwrite=overwrite)
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could Not Save Mod Pack", str(exc))
            return
        self.status.setText(
            f"Saved '{profile.name}' from a save's mods.txt. The save was not changed."
        )
        self._refresh_packs(profile.name)

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
