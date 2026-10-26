"""Mod Pack and global configuration dialogs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from zomboid_mod_manager.collection_deployment import (
    load_collection,
)
from zomboid_mod_manager.collection_store import CollectionStore
from zomboid_mod_manager.configuration import (
    is_global_default_mod_list,
    load_active_configuration,
    read_unchanged_active_configuration,
)
from zomboid_mod_manager.discovery.scanner import merge_scan_results, scan_mods
from zomboid_mod_manager.domain import ModEntry, ScanResult
from zomboid_mod_manager.gameio.active_mods import (
    ActiveModConfigError,
    ConcurrentConfigChangeError,
)
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
)
from zomboid_mod_manager.steamcmd import SteamCmdDownloader
from zomboid_mod_manager.ui.change_preview import format_ordered_list_change
from zomboid_mod_manager.ui.collection_browser_dialog import CollectionBrowserDialog
from zomboid_mod_manager.ui.collection_load_dialog import CollectionLoadDialog
from zomboid_mod_manager.ui.mod_packs_dialog import ModPacksDialog
from zomboid_mod_manager.ui.text import counted
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
            getattr(self, "_loaded_collection_content", ()),
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
            f"Saved Mod Pack '{profile.name}' with "
            f"{counted(len(profile.mod_ids), 'Mod ID')}."
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
        if self._active_config is not None and is_global_default_mod_list(
            self._active_config.path
        ):
            index = (
                self._active_config.path.parent.parent
                / ".zomboidsorter-collections/active.json"
            )
            if profile.collection_content or index.exists():
                self._load_collection_mod_pack(profile)
                return
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

        previous_mod_ids = list(self._staged_mod_ids)
        previous_workshop_ids = self._profile_workshop_ids
        if tuple(previous_mod_ids) != latest.config.mods:
            answer = QMessageBox.question(
                self,
                "Replace staged changes?",
                f"You have unapplied changes in Active Order. Applying Mod Pack '{profile.name}' "
                "will replace those staged changes. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.configuration_status.setText(
                    "Mod Pack not applied; your staged changes are still here."
                )
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
                    f"Mod Pack '{profile.name}' was not applied; your staged list and game list are unchanged."
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
        else:
            if self._active_config is latest:
                self._staged_mod_ids = previous_mod_ids
                self._profile_workshop_ids = previous_workshop_ids
                self._refresh_management_lists()
                self._update_apply_enabled()
                self.configuration_status.setText(
                    f"Mod Pack '{profile.name}' was not applied; your previous staged list was restored."
                )
            else:
                self.configuration_status.setText(
                    f"Could not verify Mod Pack '{profile.name}' after writing. "
                    "Reload the global mod list and inspect it before applying again."
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
                f"Loaded {counted(len(snapshot.config.mods), 'active Mod ID')} "
                "from the global default list. "
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
        cached = [
            item.workshop_id for item in getattr(self, "_loaded_collection_content", ())
        ]
        return tuple(dict.fromkeys(known + retained + cached))

    def _browse_workshop_mods(self) -> None:
        from zomboid_mod_manager.local_install import install_local_mod

        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Library scan running",
                "Wait for the library scan to finish before installing mods.",
            )
            return
        local_text = self.local_path.text().strip()
        if not local_text or not Path(local_text).expanduser().is_dir():
            QMessageBox.warning(
                self,
                "Local mods folder needed",
                "Choose an existing local mods folder in Paths & Settings first.",
            )
            return
        local_root = Path(local_text).expanduser().absolute()
        private_root = (self._profile_store.root.parent / "collections").resolve()
        if local_root.resolve().is_relative_to(private_root):
            QMessageBox.warning(
                self,
                "Choose a local mods folder",
                "The private collections cache cannot be used as the local mods folder.",
            )
            return
        browser = CollectionBrowserDialog(self, mods=True)
        if (
            browser.exec() != QDialog.DialogCode.Accepted
            or not browser.selected_collection
        ):
            return
        selected = browser.selected_collection
        if (
            QMessageBox.question(
                self,
                "Install local mod",
                f"Install '{selected.title}' into:\n{local_root}\n\nAll Mod IDs included in this Workshop item will stay installed across pack changes. Steam subscriptions and the active list will not change. Dependencies are not downloaded automatically.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        local_roots, workshop_roots = self._selected_roots()
        operation = lambda cancelled, progress: install_local_mod(
            selected.workshop_id,
            local_root,
            SteamCmdDownloader(self._profile_store.root.parent / "tools/steamcmd"),
            local_roots=local_roots,
            workshop_roots=workshop_roots,
            cancelled=cancelled,
            progress=progress,
        )
        dialog = CollectionLoadDialog(
            operation,
            self,
            title="Install Local Mod",
            initial="Downloading and preparing local mods…",
            stopping="Stopping local installation and restoring prepared files…",
        )
        dialog.exec()
        if dialog.error:
            QMessageBox.warning(self, "Local installation stopped", dialog.error)
        if dialog.result_data is not None:
            self.status.setText(
                f"Installed '{selected.title}' locally. Refreshing Available Mods…"
            )
            self._refresh_scan()

    def _browse_workshop_collections(self) -> None:
        browser = CollectionBrowserDialog(self)
        if (
            browser.exec() == QDialog.DialogCode.Accepted
            and browser.selected_collection
        ):
            selected = browser.selected_collection
            self._import_workshop_collection(selected.workshop_id, selected.title)

    def _import_workshop_collection(
        self, collection_id: str = "", title: str = ""
    ) -> None:
        dialog = WorkshopCollectionDialog(
            self._last_result or ScanResult((), (), ()),
            self,
            collection_id=collection_id,
            title=title,
            profile_store=self._profile_store,
            collection_store=CollectionStore(
                self._profile_store.root.parent / "collections"
            ),
            downloader=SteamCmdDownloader(
                self._profile_store.root.parent / "tools/steamcmd"
            ),
            save_profile=self._save_imported_collection_profile,
        )
        dialog.exec()
        # Imports remain private: do not add cache roots to library discovery.

    def _save_imported_collection_profile(self, profile: ModProfile) -> bool:
        try:
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
                    return False
                overwrite = True
            self._profile_store.save(profile, overwrite=overwrite)
        except (OSError, ProfileError) as exc:
            QMessageBox.warning(self, "Could not save collection Mod Pack", str(exc))
            return False
        self.configuration_status.setText(
            f"Saved Workshop collection as Mod Pack '{profile.name}' with "
            f"{counted(len(profile.mod_ids), 'installed Mod ID')} and "
            f"{counted(len(profile.workshop_ids), 'Workshop item')}. "
            "Open Mod Packs to load its files and apply the global list."
        )
        self.status.setText(f"Saved Workshop collection as Mod Pack '{profile.name}'.")
        self.collection_import_status.setText(
            f"Saved '{profile.name}' with {counted(len(profile.mod_ids), 'Mod ID')}. "
            "It now appears in Mod Packs. Open Mod Packs in Mod Workspace to load and apply it."
        )
        return True

    def _load_collection_mod_pack(self, profile: ModProfile) -> None:
        snapshot = self._active_config
        if (
            snapshot is None
            or not self._active_config_matches_selected_path()
            or not is_global_default_mod_list(snapshot.path)
        ):
            QMessageBox.warning(
                self,
                "Global Mod List Unavailable",
                "Load the supported global Zomboid/mods/default.txt before loading collection files.",
            )
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Scan in Progress",
                "Wait for the current library scan to finish before loading a collection pack.",
            )
            return
        if not self._confirm_staged_replacement("load this Mod Pack"):
            return
        answer = QMessageBox.question(
            self,
            "Load Collection Mod Pack",
            f"Load '{profile.name}'? Its exact cached copies will be prepared in {snapshot.path.parent}. When you launch from ZomboidSorter, those local copies take priority over Workshop copies with the same Mod ID. Other installed copies stay untouched. Close Project Zomboid first. You will review the global-list changes before applying them.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        roots, _workshop = self._selected_roots()
        old_mods = list(self._staged_mod_ids)
        old_workshop = self._profile_workshop_ids
        old_content = getattr(self, "_loaded_collection_content", ())
        old_scan = self._last_result
        old_raw_scan = self._last_scan_result or old_scan
        dialog = CollectionLoadDialog(
            lambda cancelled, progress: load_collection(
                CollectionStore(self._profile_store.root.parent / "collections"),
                profile,
                snapshot.path.parent,
                roots,
                old_raw_scan,
                cancelled=cancelled,
                progress=progress,
            ),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if dialog.error:
                QMessageBox.warning(
                    self, "Could Not Load Collection Pack", dialog.error
                )
            return
        prepared, result = dialog.result_data
        self._loaded_collection_content = profile.collection_content
        self._show_result(result)
        self._staged_mod_ids = list(profile.mod_ids)
        self._profile_workshop_ids = profile.workshop_ids
        self._refresh_management_lists()
        self._update_apply_enabled()
        before_write = self._active_config
        if self._apply_staged_configuration(
            require_confirmation=True, map_ids=profile.map_ids
        ):
            self.status.setText(
                f"Loaded and applied '{profile.name}'. Launch from ZomboidSorter to prioritize its exact copies over Workshop versions; other installed files stay untouched. Disabled pack mods remain in Available Mods."
            )
            return
        if self._active_config is not before_write:
            QMessageBox.warning(
                self,
                "Collection Apply Could Not Be Verified",
                f"The game list may have changed. Loaded collection files were retained to match it. Reload the global list before continuing. Recovery files: {prepared.root}",
            )
            return

        def restore(_cancelled, progress):
            progress("Restoring previous collection folders…")
            prepared.rollback()
            local_scan = scan_mods(
                local_roots=list(dict.fromkeys([snapshot.path.parent, *roots])),
            )
            previous_profile = prepared.owner.loaded_profile()
            state, _ = prepared.owner.read()
            return merge_scan_results(
                local_scan,
                old_raw_scan,
                preferred_mod_ids=(
                    previous_profile.mod_ids if previous_profile else ()
                ),
                preferred_roots=tuple(
                    snapshot.path.parent / record["name"] for record in state["folders"]
                ),
            )

        recovery = CollectionLoadDialog(restore, self, recovery=True)
        if recovery.exec() == QDialog.DialogCode.Accepted:
            self._loaded_collection_content = old_content
            self._show_result(recovery.result_data)
            self._staged_mod_ids = old_mods
            self._profile_workshop_ids = old_workshop
            self._refresh_management_lists()
            self._update_apply_enabled()
            self.configuration_status.setText(
                "Collection load cancelled or not applied; the previous pack and staged order were restored."
            )
        else:
            self._last_result = old_scan
            self._last_scan_result = old_raw_scan
            QMessageBox.warning(
                self,
                "Collection Recovery Needs Attention",
                recovery.error + f"\nRecovery folders: {prepared.root}",
            )
