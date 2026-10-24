"""Explicit save-list and server-settings apply actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from zomboid_mod_manager.gameio.save_mods import (
    ConcurrentSaveModChangeError,
    SaveModDiscoveryError,
    SaveModTargetSnapshot,
    list_save_mod_backups,
    read_save_mod_backup,
    read_save_mod_target,
    reset_save_mod_target,
    restore_save_mod_backup,
    write_save_mod_ids,
)
from zomboid_mod_manager.gameio.server_settings import (
    ConcurrentServerSettingsChangeError,
    ServerSettingsError,
    list_server_settings_backups,
    read_server_settings,
    read_server_settings_backup,
    restore_server_settings_backup,
    write_server_settings,
)
from zomboid_mod_manager.ui.change_preview import (
    format_ini_file_diff,
    format_ordered_list_change,
)


class GameTargetActionsMixin:
    def _stored_directory(self, key: str, fallback: Path) -> Path:
        configured = self._settings.value(key)
        if configured:
            try:
                candidate = Path(str(configured)).expanduser()
                if candidate.is_dir():
                    return candidate
            except OSError:
                pass
        return fallback

    def _save_target_start_directory(self, saves_root: Path) -> Path:
        configured = self._settings.value("paths/save_target")
        if configured:
            try:
                target = Path(str(configured)).expanduser().resolve(strict=True)
                root = saves_root.expanduser().resolve(strict=True)
                if target.is_dir() and target.parent.parent == root:
                    return target
            except OSError:
                pass
        return saves_root

    def _remember_save_target(self, snapshot: SaveModTargetSnapshot) -> None:
        if not self._persist_settings:
            return
        self._settings.setValue("paths/saves_root", str(snapshot.saves_root))
        self._settings.setValue("paths/save_target", str(snapshot.save_directory))
        self._settings.sync()

    def _remember_server_target(self, directory: Path) -> None:
        if not self._persist_settings:
            return
        self._settings.setValue("paths/server_settings", str(directory))
        self._settings.sync()

    def _choose_save_target(self) -> SaveModTargetSnapshot | None:
        saves_root_text = QFileDialog.getExistingDirectory(
            self,
            "Choose the Project Zomboid Saves folder",
            str(
                self._stored_directory(
                    "paths/saves_root", Path.home() / "Zomboid" / "Saves"
                )
            ),
        )
        if not saves_root_text:
            return None
        saves_root = Path(saves_root_text)
        save_directory_text = QFileDialog.getExistingDirectory(
            self,
            "Choose one save folder under <Saves>/<mode>/",
            str(self._save_target_start_directory(saves_root)),
        )
        if not save_directory_text:
            return None
        try:
            snapshot = read_save_mod_target(saves_root, Path(save_directory_text))
        except (OSError, SaveModDiscoveryError) as exc:
            QMessageBox.warning(self, "Could Not Read Save Mod List", str(exc))
            return None
        self._remember_save_target(snapshot)
        return snapshot

    def _server_settings_start_directory(self) -> Path:
        return self._stored_directory(
            "paths/server_settings", Path.home() / "Zomboid" / "Server"
        )

    def _apply_staged_to_save(self) -> None:
        snapshot = self._choose_save_target()
        if snapshot is None:
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
        preview = format_ordered_list_change("Mod IDs", snapshot.config.mods, mod_ids)
        preview.extend(
            format_ordered_list_change(
                "Maps", snapshot.config.maps, snapshot.config.maps
            )
        )
        preview_text = "\n".join(preview)
        answer = QMessageBox.question(
            self,
            "Apply Mod List to Save",
            f"Write {len(mod_ids)} staged Mod IDs to {snapshot.save_directory.parent.name} · {snapshot.save_directory.name}?\n\n"
            f"{current_description}\n\nChanges:\n{preview_text}\n\n"
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

    def _restore_save_backup(self) -> None:
        snapshot = self._choose_save_target()
        if snapshot is None:
            return
        try:
            backups = list_save_mod_backups(snapshot)
        except (OSError, SaveModDiscoveryError) as exc:
            QMessageBox.warning(self, "Could Not Read Save Backups", str(exc))
            return
        if not backups:
            QMessageBox.information(
                self,
                "No Save Mod-List Backups",
                "No timestamped backups were found beside this save's mods.txt.",
            )
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a save mod-list backup",
            str(snapshot.mods_path.parent),
            "Save mod-list backups (mods.txt.bak-*)",
        )
        if not selected:
            return
        try:
            backup = read_save_mod_backup(snapshot, selected)
        except (OSError, SaveModDiscoveryError) as exc:
            QMessageBox.warning(self, "Could Not Read Save Backup", str(exc))
            return

        preview = format_ordered_list_change(
            "Mod IDs", snapshot.config.mods, backup.config.mods
        )
        preview.extend(
            format_ordered_list_change("Maps", snapshot.config.maps, backup.config.maps)
        )
        preview_text = "\n".join(preview)
        target = snapshot.save_directory
        target_name = f"{target.parent.name} · {target.name}"
        if snapshot.inherits_global_list:
            current_state = "This save currently inherits the global list. Restoring will create an explicit save list."
        else:
            current_state = (
                "A backup of the current save list will be created before restoring."
            )
        prompt = (
            f"Restore {backup.path.name} to {target_name}?\n\n"
            f"{current_state}\n\nChanges:\n{preview_text}\n\n"
            "Close Project Zomboid and do not load this save while restoring."
        )
        answer = QMessageBox.question(
            self,
            "Restore Save Mod-List Backup",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            current_backup = restore_save_mod_backup(snapshot, backup)
        except (
            OSError,
            SaveModDiscoveryError,
            ConcurrentSaveModChangeError,
        ) as exc:
            QMessageBox.warning(self, "Could Not Restore Save Backup", str(exc))
            return
        if snapshot.raw_bytes == backup.raw_bytes:
            self.configuration_status.setText(
                f"Save {target.name} already matches {backup.path.name}; no file change was needed."
            )
        elif current_backup is None:
            self.configuration_status.setText(
                f"Restored the save list for {target.name}; it had no previous explicit list to back up."
            )
        else:
            self.configuration_status.setText(
                f"Restored the save list for {target.name}. Previous file backed up to {current_backup}."
            )

    def _reset_save_to_inherit(self) -> None:
        snapshot = self._choose_save_target()
        if snapshot is None:
            return
        if snapshot.inherits_global_list:
            QMessageBox.information(
                self,
                "Save Already Inherits Global List",
                f"{snapshot.save_directory.name} has no explicit mods.txt and already inherits the global mod list.",
            )
            return

        preview = format_ordered_list_change("Mod IDs", snapshot.config.mods, ())
        preview.extend(format_ordered_list_change("Maps", snapshot.config.maps, ()))
        preview_text = "\n".join(preview)
        answer = QMessageBox.question(
            self,
            "Reset Save to Global Mod List",
            f"Remove the explicit mod list for {snapshot.save_directory.parent.name} · {snapshot.save_directory.name}?\n\n"
            "The save will inherit the global default list the next time it loads. "
            "A timestamped backup of this save list will be created first.\n\n"
            f"Changes:\n{preview_text}\n\n"
            "Close Project Zomboid and do not load this save while resetting.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            backup = reset_save_mod_target(snapshot)
        except (
            OSError,
            SaveModDiscoveryError,
            ConcurrentSaveModChangeError,
        ) as exc:
            QMessageBox.warning(self, "Could Not Reset Save Mod List", str(exc))
            return
        if backup is None:
            self.configuration_status.setText(
                f"Save {snapshot.save_directory.name} already inherits the global mod list."
            )
        else:
            self.configuration_status.setText(
                f"Save {snapshot.save_directory.name} now inherits the global mod list. Backup: {backup}"
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
            str(self._server_settings_start_directory()),
            "Project Zomboid server settings (*.ini)",
        )
        if not selected:
            return
        try:
            snapshot = read_server_settings(selected)
        except (OSError, ServerSettingsError) as exc:
            QMessageBox.warning(self, "Could Not Read Server Settings", str(exc))
            return
        self._remember_server_target(snapshot.path.parent)

        mods = tuple(self._staged_mod_ids)
        change_lines = format_ordered_list_change("Mod IDs", snapshot.config.mods, mods)
        change_lines.extend(
            format_ordered_list_change(
                "Workshop IDs", snapshot.config.workshop_items, workshop_ids
            )
        )
        change_text = "\n".join(change_lines)
        prompt = (
            f"Replace Mods with {len(mods)} staged Mod IDs and WorkshopItems with "
            f"{len(workshop_ids)} uniquely resolved Workshop IDs in {snapshot.path.name}?\n\n"
            f"Changes:\n{change_text}\n\n"
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

    def _restore_server_backup(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Project Zomboid server settings",
            str(self._server_settings_start_directory()),
            "Project Zomboid server settings (*.ini)",
        )
        if not selected:
            return
        try:
            snapshot = read_server_settings(selected)
            backups = list_server_settings_backups(snapshot)
        except (OSError, ServerSettingsError) as exc:
            QMessageBox.warning(self, "Could Not Read Server Backups", str(exc))
            return
        self._remember_server_target(snapshot.path.parent)
        if not backups:
            QMessageBox.information(
                self,
                "No Server Settings Backups",
                "No timestamped backups were found beside this server settings file.",
            )
            return
        backup_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a server settings backup",
            str(snapshot.path.parent),
            "Server settings backups (*.ini.bak-*)",
        )
        if not backup_path:
            return
        try:
            backup = read_server_settings_backup(snapshot, backup_path)
        except (OSError, ServerSettingsError) as exc:
            QMessageBox.warning(self, "Could Not Read Server Backup", str(exc))
            return

        preview = format_ini_file_diff(snapshot.raw_bytes, backup.raw_bytes)
        preview_text = "\n".join(preview)
        prompt = (
            f"Restore {backup.path.name} to {snapshot.path.name}?\n\n"
            "Server-file changes (first 24 changed lines; passwords, tokens, and secrets are masked):\n"
            f"{preview_text}\n\n"
            "Other server settings will be restored from the backup. A backup of the current file will be created. "
            "Stop the server and close its settings editor before restoring."
        )
        answer = QMessageBox.question(
            self,
            "Restore Server Settings Backup",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            current_backup = restore_server_settings_backup(snapshot, backup)
        except (
            OSError,
            ServerSettingsError,
            ConcurrentServerSettingsChangeError,
        ) as exc:
            QMessageBox.warning(self, "Could Not Restore Server Backup", str(exc))
            return
        if current_backup is None:
            self.configuration_status.setText(
                f"Server settings {snapshot.path.name} already match {backup.path.name}; no file change was needed."
            )
        else:
            self.configuration_status.setText(
                f"Restored server settings from {backup.path.name}. Previous file backed up to {current_backup}."
            )
