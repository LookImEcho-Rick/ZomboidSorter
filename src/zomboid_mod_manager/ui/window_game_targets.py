"""Explicit save-list and server-settings apply actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from zomboid_mod_manager.gameio.save_mods import (
    ConcurrentSaveModChangeError,
    SaveModDiscoveryError,
    read_save_mod_target,
    write_save_mod_ids,
)
from zomboid_mod_manager.gameio.server_settings import (
    ConcurrentServerSettingsChangeError,
    ServerSettingsError,
    read_server_settings,
    write_server_settings,
)


class GameTargetActionsMixin:
    def _apply_staged_to_save(self) -> None:
        saves_root_text = QFileDialog.getExistingDirectory(
            self,
            "Choose the Project Zomboid Saves folder",
            str(Path.home() / "Zomboid" / "Saves"),
        )
        if not saves_root_text:
            return
        save_directory_text = QFileDialog.getExistingDirectory(
            self,
            "Choose one save folder under <Saves>/<mode>/",
            saves_root_text,
        )
        if not save_directory_text:
            return
        try:
            snapshot = read_save_mod_target(
                Path(saves_root_text), Path(save_directory_text)
            )
        except (OSError, SaveModDiscoveryError) as exc:
            QMessageBox.warning(self, "Could Not Read Save Mod List", str(exc))
            return

        mod_ids = tuple(self._staged_mod_ids)
        if snapshot.inherits_global_list:
            current_description = (
                "This save currently inherits the global mod list. Applying will create an explicit save mod list "
                "with the staged Mod ID order and no map IDs. There is no existing save-list file to back up."
            )
        else:
            current_description = (
                f"This save has {len(snapshot.config.mods)} explicit Mod IDs and "
                f"{len(snapshot.config.maps)} map IDs. Its map order will be preserved, and a timestamped backup will be created."
            )
        answer = QMessageBox.question(
            self,
            "Apply Mod List to Save",
            f"Write {len(mod_ids)} staged Mod IDs to {snapshot.save_directory.parent.name} · {snapshot.save_directory.name}?\n\n"
            f"{current_description}\n\n"
            "Close Project Zomboid and do not load this save while applying.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            backup = write_save_mod_ids(snapshot, mod_ids)
        except (OSError, SaveModDiscoveryError, ConcurrentSaveModChangeError) as exc:
            QMessageBox.warning(self, "Could Not Apply Save Mod List", str(exc))
            return
        if snapshot.raw_bytes is not None and backup is None:
            self.configuration_status.setText(
                f"Save {snapshot.save_directory.name} already has the staged Mod ID order; no file change was needed."
            )
        elif backup is None:
            self.configuration_status.setText(
                f"Created an explicit save mod list for {snapshot.save_directory.name}; no previous file existed to back up."
            )
        else:
            self.configuration_status.setText(
                f"Applied {len(mod_ids)} Mod IDs to save {snapshot.save_directory.name}. Backup: {backup}"
            )

    def _workshop_ids_for_staged_mods(self) -> tuple[str, ...]:
        if self._last_result is None:
            raise ServerSettingsError(
                "Scan the mod library before applying server settings so Workshop origins can be resolved."
            )
        entries_by_id = {}
        for entry in self._last_result.entries:
            if entry.mod_id:
                entries_by_id.setdefault(entry.mod_id, []).append(entry)
        workshop_ids: list[str] = []
        for mod_id in self._staged_mod_ids:
            matches = entries_by_id.get(mod_id, [])
            if not matches:
                raise ServerSettingsError(
                    f"'{mod_id}' is not present in the scanned library. Remove it or resolve it before applying server settings."
                )
            if len(matches) != 1:
                raise ServerSettingsError(
                    f"'{mod_id}' has multiple installed entries; its server origin is ambiguous."
                )
            entry = matches[0]
            if entry.source == "workshop":
                if not entry.workshop_id or not entry.workshop_id.isdecimal():
                    raise ServerSettingsError(
                        f"'{mod_id}' has no valid Workshop origin in the scan."
                    )
                if entry.workshop_id not in workshop_ids:
                    workshop_ids.append(entry.workshop_id)
        return tuple(workshop_ids)

    def _apply_staged_to_server(self) -> None:
        try:
            workshop_ids = self._workshop_ids_for_staged_mods()
        except ServerSettingsError as exc:
            QMessageBox.warning(self, "Cannot Resolve Server Mods", str(exc))
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Project Zomboid server settings",
            str(Path.home() / "Zomboid" / "Server"),
            "Project Zomboid server settings (*.ini)",
        )
        if not selected:
            return
        try:
            snapshot = read_server_settings(selected)
        except (OSError, ServerSettingsError) as exc:
            QMessageBox.warning(self, "Could Not Read Server Settings", str(exc))
            return

        mods = tuple(self._staged_mod_ids)
        prompt = (
            f"Replace Mods with {len(mods)} staged Mod IDs and WorkshopItems with "
            f"{len(workshop_ids)} uniquely resolved Workshop IDs in {snapshot.path.name}?\n\n"
            "Other server settings, including Map, will be preserved. A timestamped backup will be created. "
            "Stop the server and close its settings editor before applying."
        )
        answer = QMessageBox.question(
            self,
            "Apply Mod List to Server",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            backup = write_server_settings(
                snapshot, mods=mods, workshop_items=workshop_ids
            )
        except (
            OSError,
            ServerSettingsError,
            ConcurrentServerSettingsChangeError,
        ) as exc:
            QMessageBox.warning(self, "Could Not Apply Server Settings", str(exc))
            return
        if backup is None:
            self.configuration_status.setText(
                f"Server settings {snapshot.path.name} already match the staged Mod IDs and Workshop origins."
            )
        else:
            self.configuration_status.setText(
                f"Updated Mods and WorkshopItems in {snapshot.path.name}. Backup: {backup}"
            )
