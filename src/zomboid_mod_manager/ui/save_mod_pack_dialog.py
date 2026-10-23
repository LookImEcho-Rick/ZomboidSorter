"""Read-only save-list inspection and app-owned Mod Pack import dialog."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from zomboid_mod_manager.domain import ScanResult
from zomboid_mod_manager.gameio.save_mods import (
    SaveModDiscovery,
    SaveModDiscoveryError,
    SaveModList,
    discover_save_mod_lists,
)
from zomboid_mod_manager.profiles import ModProfile, ProfileError, validate_profile
from zomboid_mod_manager.ui.theme import apply_theme

_INVALID_PROFILE_CHARS = '<>:"/\\|?*'


class SaveModPackDialog(QDialog):
    """Inspect saved per-save mod lists and return a profile for explicit saving."""

    def __init__(
        self,
        *,
        saves_root: Path | None = None,
        scan_result: ScanResult | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import a Save Mod List")
        self.resize(760, 560)
        self.setMinimumSize(620, 440)
        apply_theme(self)
        self._scan_result = scan_result
        self._discovery: SaveModDiscovery | None = None
        self.selected_profile: ModProfile | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Read a Save's Mod List")
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "This reads only each save's mods.txt and copies its ordered Mod IDs "
            "into an app-owned Mod Pack. Save files are never changed. Applying "
            "the pack to the global list is a separate action."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        root_row = QHBoxLayout()
        self.saves_root = QLineEdit(
            str(saves_root or Path.home() / "Zomboid" / "Saves")
        )
        self.saves_root.setAccessibleName("Project Zomboid Saves folder")
        root_row.addWidget(self.saves_root, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_saves_root)
        root_row.addWidget(browse_button)
        self.scan_button = QPushButton("Scan Saves")
        self.scan_button.clicked.connect(self._scan_saves)
        root_row.addWidget(self.scan_button)
        layout.addLayout(root_row)

        self.saves_list = QListWidget()
        self.saves_list.setAccessibleName("Saves with explicit mod lists")
        self.saves_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.saves_list.itemSelectionChanged.connect(self._show_selection)
        layout.addWidget(self.saves_list, 1)

        self.discovery_status = QLabel()
        self.discovery_status.setObjectName("secondaryText")
        self.discovery_status.setWordWrap(True)
        layout.addWidget(self.discovery_status)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected save mod-list preview")
        self.details.setPlaceholderText("Select a save with an explicit mods.txt.")
        layout.addWidget(self.details, 2)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Mod Pack name:"))
        self.pack_name = QLineEdit()
        self.pack_name.setMaxLength(80)
        self.pack_name.setAccessibleName("Imported Mod Pack name")
        self.pack_name.textChanged.connect(self._update_buttons)
        name_row.addWidget(self.pack_name, 1)
        layout.addLayout(name_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("Save as Mod Pack")
        self.save_button.setEnabled(False)
        buttons.accepted.connect(self._accept_profile)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._scan_saves()

    def _browse_saves_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Choose the Project Zomboid Saves folder", self.saves_root.text()
        )
        if selected:
            self.saves_root.setText(selected)
            self._scan_saves()

    def _scan_saves(self) -> None:
        self.saves_list.clear()
        self.details.clear()
        self.pack_name.clear()
        self.selected_profile = None
        try:
            self._discovery = discover_save_mod_lists(
                Path(self.saves_root.text()).expanduser()
            )
        except SaveModDiscoveryError as exc:
            self._discovery = None
            self.discovery_status.setText(str(exc))
            self._update_buttons()
            return

        for save in self._discovery.saves_with_explicit_lists:
            item = QListWidgetItem(
                f"{save.display_name} · {len(save.config.mods)} Mod IDs · "
                f"{len(save.config.maps)} maps"
            )
            item.setData(Qt.ItemDataRole.UserRole, save)
            self.saves_list.addItem(item)
        status = (
            f"Found {len(self._discovery.saves_with_explicit_lists)} explicit save mod list(s). "
            f"{self._discovery.inherited_global_count} save(s) have no mods.txt and use the global list."
        )
        if self._discovery.diagnostics:
            status += f" {len(self._discovery.diagnostics)} item(s) could not be read."
            self.discovery_status.setToolTip("\n".join(self._discovery.diagnostics))
        else:
            self.discovery_status.setToolTip("")
        self.discovery_status.setText(status)
        if self.saves_list.count():
            self.saves_list.setCurrentRow(0)
        self._update_buttons()

    def _selected_save(self) -> SaveModList | None:
        item = self.saves_list.currentItem()
        if item is None:
            return None
        save = item.data(Qt.ItemDataRole.UserRole)
        return save if isinstance(save, SaveModList) else None

    def _show_selection(self) -> None:
        save = self._selected_save()
        if save is None:
            self.details.clear()
            self.pack_name.clear()
            self._update_buttons()
            return

        if not self.pack_name.text().strip():
            suggested = self._suggested_profile_name(save)
            self.pack_name.setText(suggested)
        lines = [
            f"Save: {save.display_name}",
            f"Source: {save.mods_path}",
            f"Mod IDs ({len(save.config.mods)}) in saved order:",
        ]
        lines.extend(f"  {mod_id}" for mod_id in save.config.mods)
        lines.append(f"\nMaps ({len(save.config.maps)}) in saved order:")
        lines.extend(f"  {map_id}" for map_id in save.config.maps)
        lines.append(
            "\nThese ordered Mod IDs and map IDs are copied to the new app-owned pack."
        )
        self.details.setPlainText("\n".join(lines))
        self._update_buttons()

    def _suggested_profile_name(self, save: SaveModList) -> str:
        name = f"{save.game_mode} - {save.name}"
        for character in _INVALID_PROFILE_CHARS:
            name = name.replace(character, "_")
        return name.strip(" .")[:80]

    def _workshop_ids(self, mod_ids: tuple[str, ...]) -> tuple[str, ...]:
        if self._scan_result is None:
            return ()
        entries_by_id: dict[str, list] = defaultdict(list)
        for entry in self._scan_result.entries:
            if entry.mod_id:
                entries_by_id[entry.mod_id].append(entry)
        workshop_ids = []
        for mod_id in mod_ids:
            matches = entries_by_id.get(mod_id, ())
            if (
                len(matches) == 1
                and matches[0].workshop_id
                and matches[0].workshop_id not in workshop_ids
            ):
                workshop_ids.append(matches[0].workshop_id)
        return tuple(workshop_ids)

    def _update_buttons(self) -> None:
        self.save_button.setEnabled(
            self._selected_save() is not None and bool(self.pack_name.text().strip())
        )

    def _accept_profile(self) -> None:
        save = self._selected_save()
        if save is None:
            return
        profile = ModProfile(
            name=self.pack_name.text().strip(),
            mod_ids=save.config.mods,
            workshop_ids=self._workshop_ids(save.config.mods),
            map_ids=save.config.maps,
        )
        try:
            validate_profile(profile)
        except ProfileError as exc:
            self.discovery_status.setText(f"Could not save this Mod Pack: {exc}")
            return
        self.selected_profile = profile
        self.accept()
