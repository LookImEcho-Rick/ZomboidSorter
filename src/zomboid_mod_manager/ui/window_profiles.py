"""Mod Pack and global configuration dialogs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from zomboid_mod_manager.configuration import (
    is_global_default_mod_list,
    load_active_configuration,
    read_unchanged_active_configuration,
)
from zomboid_mod_manager.domain import ModEntry
from zomboid_mod_manager.gameio.active_mods import (
    ActiveModConfigError,
    ConcurrentConfigChangeError,
)
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
)
from zomboid_mod_manager.ui.change_preview import format_ordered_list_change
from zomboid_mod_manager.ui.mod_packs_dialog import ModPacksDialog
from zomboid_mod_manager.ui.workshop_dialog import WorkshopCollectionDialog


class ProfileActionsMixin:
    def _save_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Mod Pack", "Mod Pack name:")
        if not accepted:
            return
        profile = ModProfile(
            name.strip(),
            tuple(self._staged_mod_ids),
            self._staged_workshop_ids(),
            self._active_config.config.maps
            if self._active_config is not None
            else None,
        )
        overwrite = False
        if profile.name in self._profile_store.list_names():
            answer = QMessageBox.question(
                self,
                "Replace Mod Pack",
                f"Replace '{profile.name}'? Its current version will be backed up.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self._profile_store.save(profile, overwrite=overwrite)
        except ProfileError as exc:
            QMessageBox.warning(self, "Could not save Mod Pack", str(exc))
            return
        self.configuration_status.setText(
            f"Saved Mod Pack '{profile.name}'. The game list was not changed."
        )
        self.status.setText(
            f"Saved Mod Pack '{profile.name}' with {len(profile.mod_ids)} Mod IDs."
        )

    def _open_mod_packs(self) -> None:
        dialog = ModPacksDialog(
            self._profile_store,
            self,
            current_mod_ids=(
                tuple(self._active_config.config.mods)
                if self._active_config is not None
                else None
            ),
            current_map_ids=(
                tuple(self._active_config.config.maps)
                if self._active_config is not None
                else None
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.selected_pack is not None:
            self._apply_mod_pack(dialog.selected_pack)

    def _apply_mod_pack(self, profile: ModProfile) -> None:
        snapshot = self._active_config
        if snapshot is None or not self._active_config_matches_selected_path():
            QMessageBox.warning(
                self,
                "Global Mod List Unavailable",
                "Load the supported global Zomboid/mods/default.txt file before applying a Mod Pack.",
            )
            return
        if not is_global_default_mod_list(snapshot.path):
            QMessageBox.warning(
                self,
                "Unsupported Mod List",
                "Choose the global Zomboid/mods/default.txt file to apply a Mod Pack.",
            )
            return
        try:
            latest = read_unchanged_active_configuration(snapshot)
        except ConcurrentConfigChangeError:
            QMessageBox.warning(
                self,
                "Global Mod List Changed",
                "The global mod list changed since it was loaded. Reload it, then load the Mod Pack again.",
            )
            return
        except (OSError, ActiveModConfigError) as exc:
            QMessageBox.warning(self, "Could not read global Mod List", str(exc))
            return

        desired_maps = (
            latest.config.maps if profile.map_ids is None else profile.map_ids
        )
        maps_changed = desired_maps != latest.config.maps
        if maps_changed:
            changes = format_ordered_list_change(
                "Mod IDs", latest.config.mods, profile.mod_ids
            )
            changes.extend(
                format_ordered_list_change("Maps", latest.config.maps, desired_maps)
            )
            change_text = "\n".join(changes)
            answer = QMessageBox.question(
                self,
                "Replace Global Map List?",
                f"Apply Mod Pack '{profile.name}' and replace the global map list with "
                f"{len(profile.map_ids or ())} Map IDs? A timestamped backup will be created. "
                f"Only the global mod list will be changed.\n\nChanges:\n{change_text}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.configuration_status.setText(
                    f"Applying Mod Pack '{profile.name}' was cancelled; the game list was not changed."
                )
                return

        self._active_config = latest
        self._staged_mod_ids = list(profile.mod_ids)
        self._profile_workshop_ids = profile.workshop_ids
        self._refresh_management_lists()
        self._update_apply_enabled()
        self._update_diagnostics()
        if tuple(profile.mod_ids) == latest.config.mods and not maps_changed:
            self.configuration_status.setText(
                f"Mod Pack '{profile.name}' is already active; no file change was needed."
            )
            self.status.setText(f"Mod Pack '{profile.name}' is already active.")
            return

        if self._apply_staged_configuration(
            require_confirmation=False, map_ids=profile.map_ids
        ):
            self._profile_workshop_ids = profile.workshop_ids
            self._refresh_management_lists()
            self._update_diagnostics()
            self.status.setText(
                f"Loaded and applied Mod Pack '{profile.name}' to the global mod list."
            )

    def _browse_active_config(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose the global default mod list",
            self.active_config_path.text(),
            "Project Zomboid mod list (default.txt);;Text files (*.txt)",
        )
        if selected:
            self.active_config_path.setText(selected)

    def _configuration_path_changed(self) -> None:
        self._update_apply_enabled()

    def _load_active_configuration(self) -> None:
        self._load_active_configuration_impl(force=False)

    def _load_active_configuration_impl(self, *, force: bool) -> None:
        if not force and not self._confirm_staged_replacement(
            "load a different game configuration"
        ):
            return
        path_text = self.active_config_path.text().strip()
        try:
            if not path_text:
                raise ActiveModConfigError("Choose a global default.txt path first.")
            snapshot = load_active_configuration(path_text)
        except (OSError, ActiveModConfigError) as exc:
            self._active_config = None
            self._staged_mod_ids = []
            self._profile_workshop_ids = ()
            self.configuration_status.setText(f"Could not load this mod list: {exc}")
        else:
            self._active_config = snapshot
            self._staged_mod_ids = list(snapshot.config.mods)
            self._profile_workshop_ids = ()
            self.configuration_status.setText(
                f"Loaded {len(snapshot.config.mods)} active mod IDs from the global default list. "
                "Map order is preserved. Changes are staged until Apply."
            )
        self._refresh_management_lists()
        self._update_apply_enabled()

    def _confirm_staged_replacement(self, action: str) -> bool:
        has_staged_changes = bool(self._staged_mod_ids) and self._active_config is None
        if self._active_config is not None:
            has_staged_changes = tuple(
                self._staged_mod_ids
            ) != self._active_config.config.mods or Path(
                self.active_config_path.text()
            ).expanduser().resolve(strict=False) != self._active_config.path.resolve(
                strict=False
            )
        if not has_staged_changes:
            return True
        answer = QMessageBox.question(
            self,
            "Discard staged changes?",
            f"You have staged mod-list changes. Continue to {action} and discard them? "
            "They have not been written to Project Zomboid.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _staged_workshop_ids(self) -> tuple[str, ...]:
        """Return installed Workshop origins plus unavailable profile IDs."""
        if self._last_result is None:
            return self._profile_workshop_ids
        entries_by_id: dict[str, list[ModEntry]] = {}
        for entry in self._last_result.entries:
            if entry.mod_id:
                entries_by_id.setdefault(entry.mod_id, []).append(entry)
        known: list[str] = []
        for mod_id in self._staged_mod_ids:
            matches = entries_by_id.get(mod_id, [])
            if (
                len(matches) == 1
                and matches[0].workshop_id
                and matches[0].workshop_id not in known
            ):
                known.append(matches[0].workshop_id)
        installed_workshop_ids = {
            item.workshop_id for item in self._last_result.workshop_items
        }
        retained = [
            workshop_id
            for workshop_id in self._profile_workshop_ids
            if workshop_id not in installed_workshop_ids
        ]
        return tuple(dict.fromkeys(known + retained))

    def _import_workshop_collection(self) -> None:
        if self._last_result is None:
            QMessageBox.information(
                self,
                "Scan required",
                "Scan the mod library before importing a collection so installed items can be resolved.",
            )
            return
        dialog = WorkshopCollectionDialog(self._last_result, self)
        dialog.collection_imported.connect(self._save_imported_collection_profile)
        dialog.exec()

    def _save_imported_collection_profile(self, profile: ModProfile) -> None:
        overwrite = False
        if profile.name in self._profile_store.list_names():
            answer = QMessageBox.question(
                self,
                "Replace Mod Pack",
                f"Replace '{profile.name}'? Its current version will be backed up.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self._profile_store.save(profile, overwrite=overwrite)
        except ProfileError as exc:
            QMessageBox.warning(self, "Could not save collection Mod Pack", str(exc))
            return
        self.configuration_status.setText(
            f"Saved Workshop collection as Mod Pack '{profile.name}' with "
            f"{len(profile.mod_ids)} installed Mod IDs and "
            f"{len(profile.workshop_ids)} Workshop items. Open Load Pack to apply it."
        )
        self.status.setText(f"Saved Workshop collection as Mod Pack '{profile.name}'.")
