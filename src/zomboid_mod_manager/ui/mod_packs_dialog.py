"""Selection and management window for saved Mod Packs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    parse_profile,
)
from zomboid_mod_manager.save_packs import SaveAssignmentStore, SavePackError
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
        self.resize(820, 590)
        self.setMinimumSize(650, 480)
        apply_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        heading = QLabel("Choose a Mod Pack")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Preview a saved setup, then load it into Project Zomboid. You can review the game-list changes before they are saved."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("secondaryText")
        layout.addWidget(instructions)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)
        content.setHandleWidth(5)

        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 8, 0)
        list_layout.setSpacing(8)
        list_heading = QLabel("SAVED PACKS")
        list_heading.setObjectName("sectionKicker")
        list_layout.addWidget(list_heading)
        self.pack_list = PackListWidget()
        self.pack_list.setAccessibleName("Saved Mod Packs")
        self.pack_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.pack_list.setSpacing(3)
        self.pack_list.itemSelectionChanged.connect(self._update_selection)
        list_layout.addWidget(self.pack_list, 1)
        content.addWidget(list_panel)

        self.details_panel = QFrame()
        self.details_panel.setObjectName("packDetailsPanel")
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(16, 14, 16, 14)
        details_layout.setSpacing(10)

        self.selected_pack_name = QLabel("Select a pack")
        self.selected_pack_name.setObjectName("packTitle")
        self.selected_pack_name.setTextFormat(Qt.TextFormat.PlainText)
        self.selected_pack_name.setWordWrap(True)
        details_layout.addWidget(self.selected_pack_name)

        self.details = QLabel(
            "Choose a saved pack to preview its contents and changes."
        )
        self.details.setObjectName("secondaryText")
        self.details.setWordWrap(True)
        details_layout.addWidget(self.details)

        stats = QGridLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(8)
        self.stat_values = []
        for index, label in enumerate(("MODS", "WORKSHOP ITEMS", "MAPS")):
            card = QFrame()
            card.setObjectName("packStat")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(2)
            value = QLabel("—")
            value.setObjectName("packStatValue")
            caption = QLabel(label)
            caption.setObjectName("packStatLabel")
            card_layout.addWidget(value)
            card_layout.addWidget(caption)
            stats.addWidget(card, 0, index)
            self.stat_values.append(value)
        details_layout.addLayout(stats)

        self.change_card = QFrame()
        self.change_card.setObjectName("packChangeCard")
        change_layout = QVBoxLayout(self.change_card)
        change_layout.setContentsMargins(12, 10, 12, 10)
        change_layout.setSpacing(5)
        change_heading = QLabel("CHANGES TO PROJECT ZOMBOID")
        change_heading.setObjectName("sectionKicker")
        change_layout.addWidget(change_heading)
        self.change_summary = QLabel()
        self.change_summary.setObjectName("packChangeSummary")
        self.change_summary.setWordWrap(True)
        change_layout.addWidget(self.change_summary)
        self.backup_note = QLabel(
            "A backup is created automatically before the game list is updated."
        )
        self.backup_note.setObjectName("secondaryText")
        self.backup_note.setWordWrap(True)
        change_layout.addWidget(self.backup_note)
        details_layout.addWidget(self.change_card)

        self.details_toggle = QPushButton("Show saved IDs")
        self.details_toggle.setObjectName("subtleAction")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setAccessibleName("Show or hide saved Mod and Workshop IDs")
        self.details_toggle.toggled.connect(self._toggle_technical_details)
        details_layout.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.pack_preview = QPlainTextEdit()
        self.pack_preview.setReadOnly(True)
        self.pack_preview.setAccessibleName(
            "Saved Mod IDs, Workshop IDs, maps, and detailed list changes"
        )
        self.pack_preview.setPlaceholderText("Saved IDs appear here.")
        self.pack_preview.setMinimumHeight(110)
        self.pack_preview.setMaximumHeight(190)
        details_layout.addWidget(self.pack_preview, 1)
        details_layout.addStretch(1)
        content.addWidget(self.details_panel)
        content.setStretchFactor(0, 2)
        content.setStretchFactor(1, 5)
        content.setSizes([245, 555])
        layout.addWidget(content, 1)

        self.status = QLabel()
        self.status.setObjectName("secondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.import_button = QPushButton("Import")
        self.import_button.setToolTip("Add a saved Mod Pack file.")
        self.import_button.clicked.connect(self._import_pack)
        actions.addWidget(self.import_button)
        self.export_button = QPushButton("Export")
        self.export_button.setToolTip("Save the selected Mod Pack to a file.")
        self.export_button.clicked.connect(self._export_selected_pack)
        actions.addWidget(self.export_button)
        self.more_button = QPushButton("Restore…")
        self.more_button.setToolTip("Restore a deleted pack or an earlier version.")
        self.more_button.clicked.connect(self._show_restore_menu)
        actions.addWidget(self.more_button)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setToolTip(
            "Move the selected pack to the recoverable archive."
        )
        self.delete_button.clicked.connect(self._delete_selected_pack)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)

        commit_actions = QHBoxLayout()
        commit_actions.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        commit_actions.addWidget(self.close_button)
        self.load_apply_button = QPushButton("Load & Apply")
        self.load_apply_button.setDefault(True)
        self.load_apply_button.setAccessibleName("Load and apply selected Mod Pack")
        self.load_apply_button.setToolTip(
            "Load this saved setup. Review its game-list changes before they are saved."
        )
        self.load_apply_button.clicked.connect(self._load_selected_pack)
        self.load_apply_button.setObjectName("primaryAction")
        commit_actions.addWidget(self.load_apply_button)
        layout.addLayout(actions)
        layout.addLayout(commit_actions)

        self._refresh_packs()

    def _selected_name(self) -> str:
        item = self.pack_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def _refresh_packs(self, selected: str | None = None) -> None:
        current = selected or self._selected_name()
        self.pack_list.clear()
        for name in self._profile_store.list_names():
            item = QListWidgetItem("")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, name)
            item.setToolTip(name)
            try:
                profile = self._profile_store.load(name)
                summary = (
                    f"{counted(len(profile.mod_ids), 'mod')} · "
                    f"{counted(len(profile.workshop_ids), 'item')}"
                )
                item.setToolTip(
                    f"{name}\n{counted(len(profile.mod_ids), 'mod')} · "
                    f"{counted(len(profile.workshop_ids), 'Workshop item')}"
                )
            except OSError, ProfileError:
                summary = "Pack details unavailable"
            row = QWidget(self.pack_list)
            row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(8, 4, 6, 4)
            row_layout.setSpacing(1)
            title = QLabel(name)
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            title.setStyleSheet("font-weight: 600;")
            detail = QLabel(summary)
            detail.setObjectName("secondaryText")
            detail.setWordWrap(True)
            detail.setStyleSheet("font-size: 8.5pt;")
            row_layout.addWidget(title)
            row_layout.addWidget(detail)
            item.setSizeHint(QSize(0, 74))
            self.pack_list.addItem(item)
            self.pack_list.setItemWidget(item, row)
        if current:
            for row in range(self.pack_list.count()):
                item = self.pack_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == current:
                    self.pack_list.setCurrentItem(item)
                    break
        self._update_selection()

    def _update_selection(self) -> None:
        name = self._selected_name()
        enabled = bool(name)
        self.delete_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.load_apply_button.setEnabled(False)
        has_packs = self.pack_list.count() > 0
        self.details_panel.setVisible(has_packs)
        self.details.setVisible(has_packs)
        if not name:
            self.details.setText(
                "Choose a saved pack to preview its contents and changes."
                if has_packs
                else ""
            )
            self.selected_pack_name.setText("Select a pack")
            self.selected_pack_name.setToolTip("")
            for value in self.stat_values:
                value.setText("—")
            self.change_summary.setText("")
            self.change_card.hide()
            self.details_toggle.hide()
            self.pack_preview.clear()
            self.pack_preview.hide()
            return
        try:
            profile = self._profile_store.load(name)
        except (OSError, ProfileError) as exc:
            self.details.setText(f"Could not read Mod Pack '{name}': {exc}")
            self.change_card.hide()
            self.details_toggle.hide()
            self.pack_preview.clear()
            self.pack_preview.hide()
            return
        self.selected_pack_name.setText(profile.name)
        self.selected_pack_name.setToolTip(profile.name)
        self.details.setText("Saved load order and Workshop sources")
        self.stat_values[0].setText(str(len(profile.mod_ids)))
        self.stat_values[1].setText(str(len(profile.workshop_ids)))
        self.stat_values[2].setText(
            "Keep current" if profile.map_ids is None else str(len(profile.map_ids))
        )
        self.change_summary.setText(self._change_summary(profile))
        no_game_list_change = (
            self._current_mod_ids is not None
            and self._current_mod_ids == profile.mod_ids
            and (
                profile.map_ids is None
                or (
                    self._current_map_ids is not None
                    and self._current_map_ids == profile.map_ids
                )
            )
        )
        self.backup_note.setText(
            "No game-list change is needed."
            if no_game_list_change
            else "A backup is created automatically before the game list is updated."
        )
        self.change_card.show()
        self.details_toggle.show()
        self.details_toggle.setChecked(False)
        self.details_toggle.setText("Show saved IDs")
        sections = self._technical_details(profile)
        self.pack_preview.setPlainText("\n".join(sections))
        self.pack_preview.setVisible(False)
        self.load_apply_button.setEnabled(True)

    def _change_summary(self, profile: ModProfile) -> str:
        if self._current_mod_ids is None:
            return "Load the global mod list to preview what will change."

        before = self._current_mod_ids
        after = profile.mod_ids
        if before == after:
            mod_summary = "Your active mod list already matches this pack."
        else:
            before_set = set(before)
            after_set = set(after)
            added = len(after_set - before_set)
            removed = len(before_set - after_set)
            kept = len(before_set & after_set)
            shared_before = tuple(item for item in before if item in after_set)
            shared_after = tuple(item for item in after if item in before_set)
            order_changed = shared_before != shared_after
            if not added and not removed:
                mod_summary = (
                    f"Changes the order of {counted(kept, 'mod')}."
                    if order_changed
                    else "Keeps the same mods."
                )
            else:
                parts = []
                if added:
                    parts.append(f"adds {counted(added, 'mod')}")
                if removed:
                    parts.append(f"removes {counted(removed, 'mod')}")
                if kept:
                    parts.append(f"keeps {counted(kept, 'existing mod')}")
                if order_changed:
                    parts.append("reorders existing mods")
                mod_summary = "; ".join(parts).capitalize() + "."

        if profile.map_ids is None:
            map_summary = "Your current map list stays the same."
        elif self._current_map_ids is None:
            map_summary = (
                f"Sets the map list to {counted(len(profile.map_ids), 'entry')}."
            )
        elif profile.map_ids == self._current_map_ids:
            map_summary = "Your map list already matches this pack."
        else:
            map_summary = (
                f"Updates the map list to {counted(len(profile.map_ids), 'entry')}."
            )
        return f"{mod_summary}\n{map_summary}"

    def _technical_details(self, profile: ModProfile) -> list[str]:
        sections = [
            "SAVED MOD IDS · LOAD ORDER",
            *(
                f"{index}. {mod_id}"
                for index, mod_id in enumerate(profile.mod_ids, start=1)
            ),
        ]
        if not profile.mod_ids:
            sections.append("None saved")
        sections.extend(["", "WORKSHOP ITEM IDS", *(profile.workshop_ids or ("None",))])
        sections.extend(["", "MAP IDS"])
        sections.extend(
            (profile.map_ids or ("None (empty list)",))
            if profile.map_ids is not None
            else ("Not saved; current map list is kept",)
        )
        if self._current_mod_ids is not None:
            sections.extend(["", "DETAILED GAME-LIST CHANGES"])
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
        return sections

    def _toggle_technical_details(self, checked: bool) -> None:
        self.pack_preview.setVisible(checked)
        self.details_toggle.setText("Hide saved IDs" if checked else "Show saved IDs")

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
        try:
            SaveAssignmentStore(self._profile_store.root.parent).unassign_pack(name)
        except SavePackError as exc:
            QMessageBox.warning(
                self,
                "Pack Deleted; Save Groupings Need Attention",
                f"The Mod Pack was deleted, but its save groupings could not be cleared: {exc}",
            )
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
