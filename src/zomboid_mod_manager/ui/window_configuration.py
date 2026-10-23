"""Apply, revert, and launch the staged global mod configuration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QMessageBox,
)

from zomboid_mod_manager.configuration import (
    SelectedConfigurationPathMismatch,
    apply_active_configuration,
    is_global_default_mod_list,
    read_unchanged_active_configuration,
    selected_path_matches_configuration,
)
from zomboid_mod_manager.gameio.active_mods import (
    ActiveModConfigError,
    ConcurrentConfigChangeError,
)


class ActiveConfigurationMixin:
    def _update_apply_enabled(self) -> None:
        if not hasattr(self, "apply_config_button"):
            return
        same_target = False
        if self._active_config is not None:
            try:
                same_target = Path(self.active_config_path.text()).expanduser().resolve(
                    strict=False
                ) == self._active_config.path.resolve(strict=False)
            except OSError:
                same_target = False
        dirty = (
            self._active_config is not None
            and tuple(self._staged_mod_ids) != self._active_config.config.mods
        )
        self.apply_config_button.setEnabled(bool(same_target and dirty))
        self.launch_game_button.setText(
            "Apply & Launch…" if dirty else "Launch Project Zomboid"
        )
        launch_block = self._launch_block_message(same_target)
        self.launch_game_button.setEnabled(launch_block is None)
        if launch_block is None:
            self.launch_readiness.clear()
            self.launch_readiness.hide()
            if dirty:
                self.launch_game_button.setToolTip(
                    "Save the staged global mod-list changes, then launch Project Zomboid through Steam."
                )
            else:
                self.launch_game_button.setToolTip(
                    "Launch Project Zomboid through Steam using the loaded global mod list."
                )
        else:
            message, explanation = launch_block
            self.launch_readiness.setText(message)
            self.launch_readiness.setToolTip(explanation)
            self.launch_readiness.show()
            self.launch_game_button.setToolTip(explanation)
        self.revert_button.setEnabled(bool(dirty))
        if self._active_config is None:
            message = (
                "Changes; global list unavailable"
                if self._staged_mod_ids
                else "Global list unavailable"
            )
        elif not same_target:
            message = "Target path differs from loaded list"
        elif dirty:
            message = "● Unapplied changes"
        else:
            message = "No unapplied changes"
        self.dirty_indicator.setText(message)
        self.dirty_indicator.setStyleSheet(
            "color: #f2c978; font-weight: 700;"
            if dirty or not same_target
            else "color: #a4b2ab;"
        )

    def _launch_block_message(self, same_target: bool) -> tuple[str, str] | None:
        snapshot = self._active_config
        if snapshot is None:
            return (
                "Load global list",
                "Load a valid global Zomboid/mods/default.txt file to enable Launch.",
            )
        if not same_target:
            return (
                "Load selected list",
                "The selected path differs from the loaded mod list. Load the selected global list before launching.",
            )
        if not is_global_default_mod_list(snapshot.path):
            return (
                "Choose global default.txt",
                "Launch supports only the global Zomboid/mods/default.txt target. Save and server mod lists are not changed.",
            )
        try:
            read_unchanged_active_configuration(snapshot)
        except ConcurrentConfigChangeError:
            return (
                "Reload changed list",
                "The global mod list changed outside this app. Reload it before launching so the current list is clear.",
            )
        except OSError, ActiveModConfigError:
            return (
                "Reload global list",
                "The loaded global mod list can no longer be read. Load it again before launching.",
            )
        return None

    def _revert_staged_configuration(self) -> None:
        if self._active_config is None:
            return
        if tuple(self._staged_mod_ids) == self._active_config.config.mods:
            return
        answer = QMessageBox.question(
            self,
            "Discard changes",
            "Discard unapplied changes and restore the last loaded global mod list? "
            "Project Zomboid's files will not be changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._staged_mod_ids = list(self._active_config.config.mods)
        self._profile_workshop_ids = ()
        self._refresh_management_lists()
        self._update_apply_enabled()
        self.configuration_status.setText(
            "Changes discarded; restored the last loaded global mod list."
        )

    def _apply_active_configuration(self) -> bool:
        return self._apply_staged_configuration(require_confirmation=True)

    def _apply_staged_configuration(
        self, *, require_confirmation: bool, launch_after_apply: bool = False
    ) -> bool:
        if self._active_config is None:
            return False
        if not self._active_config_matches_selected_path():
            QMessageBox.warning(
                self,
                "Could Not Apply Mod List",
                "Load the selected global default mod list before applying it.",
            )
            return False
        if tuple(self._staged_mod_ids) == self._active_config.config.mods:
            return True
        if require_confirmation:
            title = (
                "Apply Mod List and Launch"
                if launch_after_apply
                else "Apply Global Mod List"
            )
            confirmation = (
                "Save the staged list to Project Zomboid's global default mod list? A timestamped backup will be created. "
                "After the saved list is verified, Project Zomboid will open through Steam. "
                "Per-save mod lists will not be changed."
                if launch_after_apply
                else "Update the global Project Zomboid default mod list? A timestamped backup will be created. "
                "Per-save mod lists will not be changed."
            )
            answer = QMessageBox.question(
                self,
                title,
                confirmation,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            backup = apply_active_configuration(
                self._active_config,
                self.active_config_path.text(),
                tuple(self._staged_mod_ids),
            )
        except SelectedConfigurationPathMismatch:
            QMessageBox.warning(
                self,
                "Could Not Apply Mod List",
                "Load the selected global default mod list before applying it.",
            )
            return False
        except (OSError, ActiveModConfigError) as exc:
            self.configuration_status.setText(f"Apply failed safely: {exc}")
            QMessageBox.warning(self, "Could not apply mod list", str(exc))
            self._update_apply_enabled()
            return False
        self._load_active_configuration_impl(force=True)
        if self._active_config is None or tuple(
            self._active_config.config.mods
        ) != tuple(self._staged_mod_ids):
            self.configuration_status.setText(
                "Apply could not be verified after reloading the global mod list."
            )
            QMessageBox.warning(
                self,
                "Could Not Verify Mod List",
                "The saved global mod list did not match the staged list after reload. The game was not launched.",
            )
            self._update_apply_enabled()
            return False
        self.configuration_status.setText(
            f"Applied {len(self._staged_mod_ids)} active Mod IDs. Backup: {backup}"
        )
        return True

    def _active_config_matches_selected_path(self) -> bool:
        if self._active_config is None:
            return False
        return selected_path_matches_configuration(
            self._active_config, self.active_config_path.text()
        )

    def _launch_project_zomboid(self) -> None:
        snapshot = self._active_config
        if snapshot is None:
            QMessageBox.warning(
                self,
                "Global Mod List Unavailable",
                "Load a valid global Zomboid/mods/default.txt file before launching.",
            )
            return
        if not self._active_config_matches_selected_path():
            QMessageBox.warning(
                self,
                "Global Mod List Changed",
                "Load the selected global default mod list before launching so the game uses the intended mods.",
            )
            return
        if not is_global_default_mod_list(snapshot.path):
            QMessageBox.warning(
                self,
                "Unsupported Mod List Target",
                "Launching from this app requires the global Zomboid/mods/default.txt target. Save and server mod lists are not changed.",
            )
            return
        if tuple(self._staged_mod_ids) != snapshot.config.mods:
            if not self._apply_staged_configuration(
                require_confirmation=True, launch_after_apply=True
            ):
                return
            snapshot = self._active_config
            if snapshot is None:
                return
        try:
            read_unchanged_active_configuration(snapshot)
        except ConcurrentConfigChangeError:
            QMessageBox.warning(
                self,
                "Global Mod List Changed",
                "The global mod list changed outside this app. Reload it before launching so the current list is clear.",
            )
            return
        except (OSError, ActiveModConfigError) as exc:
            QMessageBox.warning(
                self,
                "Could Not Verify Global Mod List",
                f"The global mod list could not be verified. Reload it before launching.\n\n{exc}",
            )
            return
        if not QDesktopServices.openUrl(QUrl("steam://run/108600")):
            QMessageBox.warning(
                self,
                "Could Not Launch Project Zomboid",
                "Windows could not open the Steam launch link. Make sure Steam is installed and its steam:// links are registered.",
            )
        else:
            self.status.setText(
                "Windows accepted the Steam launch link. Project Zomboid startup is not confirmed."
            )
