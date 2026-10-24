"""Path selection, mod scanning, and scan-result handling."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QFileInfo,
    Qt,
    QThread,
)
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLineEdit,
)

from zomboid_mod_manager.discovery.game_build import (
    detect_game_build,
    format_game_build_detection,
)
from zomboid_mod_manager.discovery.paths import detect_paths
from zomboid_mod_manager.domain import DetectedPaths, ScanResult

from .window_workers import (
    ScanWorker,
)

_SCAN_CACHE_SECONDS = 30.0
_SCAN_CACHE_MIN_SECONDS = 0.25


class DiscoveryMixin:
    def _refresh_detected_paths(self) -> DetectedPaths:
        self._detected = detect_paths()
        self._update_diagnostics()
        return self._detected

    def _choose_game_installation(self, installations: tuple[Path, ...]) -> Path | None:
        if not installations:
            return None
        if len(installations) == 1:
            return installations[0]
        choices = [str(path) for path in installations]
        selection, accepted = QInputDialog.getItem(
            self,
            "Choose Game Installation",
            "Multiple Project Zomboid installations were found:",
            choices,
            0,
            False,
        )
        if not accepted:
            return None
        try:
            return installations[choices.index(selection)]
        except ValueError:
            return None

    def _auto_detect_all_paths(self) -> None:
        detected = self._refresh_detected_paths()
        updated: list[str] = []
        kept: list[str] = []

        game_installation = self._choose_game_installation(detected.game_installations)
        if game_installation is None:
            kept.append(
                "game folder (selection cancelled)"
                if detected.game_installations
                else "game folder (not found)"
            )
        else:
            self.game_path.setText(str(game_installation))
            self._use_detected_game_build()
            updated.append("game folder")

        self.local_path.setText(str(detected.local_mod_root))
        updated.append("local mods folder")

        if detected.workshop_roots:
            self.workshop_paths.setText(";".join(map(str, detected.workshop_roots)))
            updated.append("Workshop folders")
        else:
            kept.append("Workshop folders (not found)")

        result_parts = []
        if updated:
            result_parts.append("Updated " + ", ".join(updated))
        if kept:
            result_parts.append("kept " + ", ".join(kept))
        self.status.setText("Auto-detect complete: " + "; ".join(result_parts) + ".")

    def _auto_detect_game_path(self) -> None:
        detected = self._refresh_detected_paths()
        if not detected.game_installations:
            self.status.setText(
                "Project Zomboid was not detected; the current game folder was kept."
            )
            return
        game_installation = self._choose_game_installation(detected.game_installations)
        if game_installation is None:
            self.status.setText(
                "Game folder selection cancelled; the current path was kept."
            )
            return
        self.game_path.setText(str(game_installation))
        self._use_detected_game_build()
        self.status.setText("Game folder updated from the detected Steam installation.")

    def _auto_detect_local_path(self) -> None:
        detected = self._refresh_detected_paths()
        self.local_path.setText(str(detected.local_mod_root))
        if detected.local_mod_root.is_dir():
            self.status.setText("Local mods path updated to the detected folder.")
        else:
            self.status.setText(
                "Local mods path reset to the standard folder; it does not exist yet."
            )

    def _auto_detect_workshop_paths(self) -> None:
        detected = self._refresh_detected_paths()
        if not detected.workshop_roots:
            self.status.setText(
                "No Workshop folders were detected; the current paths were kept."
            )
            return
        self.workshop_paths.setText(";".join(map(str, detected.workshop_roots)))
        count = len(detected.workshop_roots)
        self.status.setText(
            f"Workshop content paths updated from {count} detected Steam "
            f"librar{'y' if count == 1 else 'ies'}."
        )

    @staticmethod
    def _folder_health(path_text: str, expected: str) -> tuple[str, str, str]:
        value = path_text.strip()
        if not value:
            return "unset", "Not set", f"No folder is set. Expected {expected}."

        path = str(Path(value).expanduser())
        info = QFileInfo(path)
        if not info.exists():
            return "missing", "Missing", f"Folder not found. Expected {expected}."
        if not info.isDir():
            return (
                "invalid",
                "Not a folder",
                f"Select a folder. Expected {expected}.",
            )
        if not info.isReadable():
            return (
                "unreadable",
                "Unreadable",
                f"Folder cannot be read. Expected {expected}.",
            )
        return "ready", "Found", f"Folder is available. Expected {expected}."

    @staticmethod
    def _set_path_health(label, state: str, text: str, description: str) -> None:
        indicator = {
            "ready": "✓",
            "missing": "!",
            "unreadable": "×",
            "invalid": "!",
            "partial": "!",
            "unset": "·",
        }.get(state, "?")
        detail = f"{text}. {description}"
        label.setText(indicator)
        label.setToolTip(detail)
        label.setAccessibleDescription(detail)
        if label.property("health") != state:
            label.setProperty("health", state)
            label.style().unpolish(label)
            label.style().polish(label)

    def _update_path_health(self) -> None:
        game = self._folder_health(
            self.game_path.text(),
            "the Project Zomboid installation folder containing the game files",
        )
        self._set_path_health(self.game_path_health, *game)

        local = self._folder_health(
            self.local_path.text(), "the user's Zomboid/mods folder"
        )
        self._set_path_health(self.local_path_health, *local)

        workshop_paths = [
            part.strip()
            for part in self.workshop_paths.text().split(";")
            if part.strip()
        ]
        if not workshop_paths:
            workshop = (
                "unset",
                "Not set",
                "No Workshop folders are set. Expected steamapps/workshop/content/108600.",
            )
        else:
            checks = [
                self._folder_health(
                    path, "a Project Zomboid steamapps/workshop/content/108600 folder"
                )
                for path in workshop_paths
            ]
            found_count = sum(state == "ready" for state, _, _ in checks)
            if found_count == len(checks):
                state = "ready"
                text = "Found" if len(checks) == 1 else f"{found_count} Found"
            elif found_count:
                state = "partial"
                text = f"{found_count}/{len(checks)} Found"
            elif any(state == "unreadable" for state, _, _ in checks):
                state, text = "unreadable", "Unreadable"
            elif any(state == "invalid" for state, _, _ in checks):
                state, text = "invalid", "Not a folder"
            else:
                state, text = "missing", "Missing"
            failures = [
                description
                for check_state, _, description in checks
                if check_state != "ready"
            ]
            description = (
                f"{found_count} of {len(checks)} Workshop folders are available. "
                "Expected steamapps/workshop/content/108600."
            )
            if failures:
                description += " " + " ".join(failures)
            workshop = (state, text, description)
        self._set_path_health(self.workshop_paths_health, *workshop)

    def _schedule_path_health_update(self) -> None:
        self._path_health_timer.start()

    def _use_detected_game_build(self) -> None:
        detection = detect_game_build(self.game_path.text().strip())
        self._game_build_detection = detection
        self.game_build_status.setText(format_game_build_detection(detection))
        if detection.major_build not in {"41", "42"}:
            return
        index = self.metadata_preview_target.findData(detection.major_build)
        if index >= 0:
            self.metadata_preview_target.setCurrentIndex(index)
        self.metadata_build_version.setText(detection.exact_version or "")
        self._metadata_preview_target_changed()

    @staticmethod
    def _browse_into(field: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(
            field.window(), "Choose folder", field.text()
        )
        if selected:
            field.setText(selected)

    def _add_workshop_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Project Zomboid Workshop content folder",
            self.workshop_paths.text(),
        )
        if not selected:
            return
        current = [
            part.strip()
            for part in self.workshop_paths.text().split(";")
            if part.strip()
        ]
        if selected not in current:
            current.append(selected)
        self.workshop_paths.setText(";".join(current))

    def _selected_roots(self) -> tuple[list[Path], list[Path]]:
        local_text = self.local_path.text().strip()
        local_roots = [Path(local_text).expanduser()] if local_text else []
        workshop_roots = [
            Path(part.strip()).expanduser()
            for part in self.workshop_paths.text().split(";")
            if part.strip()
        ]
        return local_roots, workshop_roots

    def _scan_key(
        self, local_roots: list[Path], workshop_roots: list[Path]
    ) -> tuple[tuple[str, str], ...]:
        roots: list[tuple[str, str]] = []
        for kind, selected in (("local", local_roots), ("workshop", workshop_roots)):
            for path in selected:
                try:
                    normalized = path.expanduser().resolve(strict=False)
                except OSError, RuntimeError:
                    normalized = path.expanduser().absolute()
                roots.append((kind, os.path.normcase(str(normalized))))
        return tuple(roots)

    def _refresh_scan(self) -> None:
        self._start_scan(force=True)

    def _start_scan(self, *, force: bool = False) -> None:
        if self._shutdown_requested:
            return
        local_roots, workshop_roots = self._selected_roots()
        scan_key = self._scan_key(local_roots, workshop_roots)
        if self._worker is not None and self._worker.isRunning():
            self._scan_again_after_current = scan_key != self._active_scan_key
            return
        if (
            not force
            and self._last_result is not None
            and scan_key == self._last_scan_key
            and self._last_scan_duration >= _SCAN_CACHE_MIN_SECONDS
            and time.monotonic() - self._last_scan_at < _SCAN_CACHE_SECONDS
        ):
            self.status.setText(
                f"Library scan reused from {self._last_scan_label}; "
                "select Refresh to check for newly installed mods."
            )
            return
        self._scan_result_received = False
        self.scan_button.setEnabled(False)
        self.workspace_scan_button.setEnabled(False)
        self.status.setText("Scanning selected folders…")
        if self._last_result is None:
            self.issue_summary.setText("Active order: checking…")
            self.available_list.empty_text = "Scanning installed mods…"
            self.available_list.viewport().update()
        self.progress.show()
        self._worker = ScanWorker(local_roots, workshop_roots)
        self._active_scan_key = scan_key
        self._active_scan_started_at = time.monotonic()
        self._worker.result_ready.connect(self._show_result)
        self._worker.failed.connect(self._show_failure)
        self._worker.progress.connect(self._scan_progress)
        self._worker.cancelled.connect(self._scan_cancelled)
        self._worker.finished.connect(self._finish_scan)
        self.cancel_scan_button.setEnabled(True)
        self.cancel_scan_button.show()
        self._worker.start()

    def _scan_progress(self, message: str) -> None:
        worker = self._worker
        if (
            self._shutdown_requested
            or self._scan_result_received
            or worker is None
            or worker.isInterruptionRequested()
        ):
            return
        self.status.setText(message)

    def _cancel_scan(self) -> None:
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        self._scan_again_after_current = False
        self.cancel_scan_button.setEnabled(False)
        self.status.setText("Cancelling scan…")
        worker.requestInterruption()

    def _scan_cancelled(self) -> None:
        if self._shutdown_requested:
            return
        self._scan_result_received = True
        self._scan_again_after_current = False
        if self._last_result is None:
            self.issue_summary.setText("Active order: not checked")
            self.available_list.empty_text = (
                "Scan cancelled · select Refresh to try again"
            )
            self.available_list.viewport().update()
        self.status.setText("Scan cancelled; previous results are unchanged.")

    def _finish_scan(self) -> None:
        self._worker = None
        self._active_scan_key = None
        self.cancel_scan_button.hide()
        self.cancel_scan_button.setEnabled(True)
        if self._shutdown_requested:
            return
        self.scan_button.setEnabled(True)
        self.workspace_scan_button.setEnabled(True)
        self._update_busy_indicator()
        if self._scan_again_after_current:
            self._scan_again_after_current = False
            self._start_scan()

    def _update_busy_indicator(self) -> None:
        scan_busy = self._worker is not None and self._worker.isRunning()
        diagnostic_busy = (
            self._diagnostic_worker is not None and self._diagnostic_worker.isRunning()
        )
        self.progress.setVisible(scan_busy or diagnostic_busy)

    def _background_workers(self) -> tuple[QThread, ...]:
        return tuple(
            worker
            for worker in (
                self._worker,
                self._diagnostic_worker,
                self._workshop_description_worker,
                self._preview_worker,
                self._update_check_worker,
                self._update_download_worker,
            )
            if worker is not None
        )

    def _continue_shutdown(self) -> None:
        if not self._shutdown_requested:
            return
        if any(worker.isRunning() for worker in self._shutdown_workers):
            if not self._shutdown_timer.isActive():
                self._shutdown_timer.start(25)
            return
        self._shutdown_timer.stop()
        self._shutdown_workers = ()
        self.close()

    def _show_result(self, result: ScanResult) -> None:
        if self._shutdown_requested:
            return
        if self._worker is not None and self._worker.isInterruptionRequested():
            self._scan_cancelled()
            return
        self._scan_result_received = True
        self.scan_button.setEnabled(True)
        self.workspace_scan_button.setEnabled(True)
        self.import_workshop_collection_button.setEnabled(True)
        previous_result = self._last_result
        previous_workshop_ids = (
            {item.workshop_id for item in previous_result.workshop_items}
            if previous_result is not None
            else set()
        )
        previous_entry_keys = (
            {entry.key for entry in previous_result.entries}
            if previous_result is not None
            else set()
        )
        new_workshop_ids = (
            {item.workshop_id for item in result.workshop_items} - previous_workshop_ids
            if previous_result is not None
            else set()
        )
        self._recently_added_workshop_item_count = len(new_workshop_ids)
        self._recently_added_workshop_entry_keys = {
            entry.key
            for entry in result.entries
            if entry.source == "workshop"
            and previous_result is not None
            and (
                entry.key not in previous_entry_keys
                or entry.workshop_id in new_workshop_ids
            )
        }
        self.collection_import_status.setText(
            f"Library ready: {len(result.workshop_items)} Workshop items and "
            f"{len(result.entries)} mod entries."
        )
        self._preview_generation += 1
        self._preview_cache.clear()
        self._last_result = result
        self._last_scan_key = self._active_scan_key
        self._last_scan_at = time.monotonic()
        self._last_scan_duration = max(
            0.0, self._last_scan_at - self._active_scan_started_at
        )
        self._last_scan_label = datetime.now().astimezone().strftime("%H:%M:%S")
        self._entries = {entry.key: entry for entry in result.entries}
        self.table_model.removeRows(0, self.table_model.rowCount())
        for entry in result.entries:
            values = (
                self._entry_display_name(entry),
                entry.mod_id or "(missing ID)",
                entry.workshop_id or "—",
                "Workshop" if entry.source == "workshop" else "Local",
                entry.layout_summary,
                str(len(entry.candidates)),
                str(entry.entry_path),
            )
            row = [QStandardItem(value) for value in values]
            row[0].setData(entry.key, Qt.ItemDataRole.UserRole)
            self.table_model.appendRow(row)

        self.details.setPlainText(
            "Select a mod entry to inspect its metadata candidates.\n\n"
            f"Workshop items: {len(result.workshop_items)}\n"
            f"Mod entries: {len(result.entries)}\n"
            f"Metadata files: {result.metadata_candidate_count}\n"
            "No active Build 42 metadata candidate was selected."
        )
        self._clear_preview(
            "PROJECT ZOMBOID\nMOD DETAILS", "Select a mod to view its declared poster."
        )
        self._refresh_management_lists()
        self._update_apply_enabled()
        warning_count = self._update_diagnostics()
        new_content = []
        if self._recently_added_workshop_item_count:
            count = self._recently_added_workshop_item_count
            new_content.append(f"{count} new Workshop item{'s' if count != 1 else ''}")
        if self._recently_added_workshop_entry_keys:
            count = len(self._recently_added_workshop_entry_keys)
            new_content.append(f"{count} new mod entr{'y' if count == 1 else 'ies'}")
        addition_summary = (
            f" New since the previous scan: {', '.join(new_content)}; marked NEW."
            if new_content
            else ""
        )
        self.status.setText(
            f"Read-only scan complete — {len(result.entries)} mod entries, "
            f"{len(result.workshop_items)} Workshop items, "
            f"{result.metadata_candidate_count} metadata files, "
            f"{warning_count} warnings, {self._issue_error_count} errors."
            f"{addition_summary}"
        )
