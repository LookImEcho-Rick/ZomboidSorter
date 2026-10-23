"""Collect safe support details and open the report preview."""

from __future__ import annotations

import platform

import PySide6
from PySide6.QtCore import qVersion

from zomboid_mod_manager import __version__
from zomboid_mod_manager.portable import portable_settings_path
from zomboid_mod_manager.support_report import build_support_report
from zomboid_mod_manager.updates import installed_build_id

from .support_report_dialog import SupportReportDialog


class SupportActionsMixin:
    def _open_support_report(self) -> None:
        workshop_paths = [
            part.strip()
            for part in self.workshop_paths.text().split(";")
            if part.strip()
        ]
        selected_paths = {
            "game_installation": [self.game_path.text()],
            "local_mods": [self.local_path.text()],
            "workshop_content": workshop_paths,
            "global_mod_list": [self.active_config_path.text()],
        }
        metadata_target = str(self.metadata_preview_target.currentData())
        report = build_support_report(
            app_version=__version__,
            build_id=installed_build_id(),
            python_version=platform.python_version(),
            pyside_version=PySide6.__version__,
            qt_version=qVersion(),
            operating_system={
                "name": platform.system(),
                "release": platform.release(),
                "architecture": platform.machine(),
            },
            storage_mode=(
                "portable" if portable_settings_path() is not None else "standard"
            ),
            selected_paths=selected_paths,
            scan_result=self._last_result,
            scan_duration_seconds=(
                self._last_scan_duration if self._last_result is not None else None
            ),
            metadata_target=metadata_target,
            exact_game_version=(
                self.metadata_build_version.text().strip()
                if metadata_target == "42"
                else ""
            ),
            detected_path_warning_count=len(self._detected.diagnostics),
            active_configuration_loaded=self._active_config is not None,
            staged_mod_ids=self._staged_mod_ids,
            ordering_rules_valid=self._user_rule_settings_error is None,
            ordering_rule_count=len(self._user_order_rules),
        )
        dialog = SupportReportDialog(report, self)
        dialog.exec()
