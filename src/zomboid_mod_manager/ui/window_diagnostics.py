"""Background dependency, file-overlap, and console diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from zomboid_mod_manager.diagnostics.console_log import (
    analyze_console_log,
    format_console_log_report,
)
from zomboid_mod_manager.diagnostics.dependencies import (
    analyze_dependencies,
    format_dependency_finding,
)
from zomboid_mod_manager.diagnostics.file_overlaps import (
    FileOverlapReport,
    analyze_file_overlaps,
    format_file_overlap_report,
)

from .file_overlap_dialog import FileOverlapDialog
from .window_workers import (
    DiagnosticWorker,
)


class DiagnosticsMixin:
    def _update_diagnostics(self) -> int:
        lines = [f"INFO: {message}" for message in self._detected.diagnostics]
        active_diagnostic_lines: list[str] = []
        library_warning_count = 0
        active_warning_count = 0
        error_count = 0
        first_library_diagnostic: str | None = None
        if self._user_rule_settings_error:
            line = (
                "WARNING [invalid-user-order-rules]: Stored rules were ignored: "
                + self._user_rule_settings_error
            )
            lines.append(line)
            active_diagnostic_lines.append(line)
            active_warning_count += 1
        result = self._last_result
        if result is not None:
            for diagnostic in result.diagnostics:
                line = f"{diagnostic.level.upper()}: {diagnostic.message}"
                if diagnostic.path:
                    line += f"\n  {diagnostic.path}"
                lines.append(line)
                if diagnostic.level == "warning":
                    library_warning_count += 1
                    if first_library_diagnostic is None:
                        first_library_diagnostic = line
                elif diagnostic.level == "error":
                    error_count += 1
                    if first_library_diagnostic is None:
                        first_library_diagnostic = line
            for item in result.workshop_items:
                for diagnostic in item.diagnostics:
                    if diagnostic not in result.diagnostics:
                        line = (
                            f"{diagnostic.level.upper()}: {diagnostic.message}"
                            f"\n  {diagnostic.path}"
                        )
                        lines.append(line)
                        if diagnostic.level == "warning":
                            library_warning_count += 1
                            if first_library_diagnostic is None:
                                first_library_diagnostic = line
                        elif diagnostic.level == "error":
                            error_count += 1
                            if first_library_diagnostic is None:
                                first_library_diagnostic = line
            for entry in result.entries:
                messages = self._entry_diagnostics_for_target(
                    entry, self._metadata_target_build()
                )
                for message in messages:
                    line = f"WARNING: {message}"
                    lines.append(line)
                    if first_library_diagnostic is None:
                        first_library_diagnostic = line
                library_warning_count += len(messages)

            installed_workshop_ids = {
                item.workshop_id for item in result.workshop_items
            }
            missing_workshop_ids = [
                workshop_id
                for workshop_id in self._profile_workshop_ids
                if workshop_id not in installed_workshop_ids
            ]
            if missing_workshop_ids:
                line = (
                    "WARNING [missing-workshop-items]: Profile references Workshop items not found in the scanned Workshop folders: "
                    + ", ".join(missing_workshop_ids)
                )
                lines.append(line)
                if first_library_diagnostic is None:
                    first_library_diagnostic = line
                library_warning_count += 1

            if self._active_config is not None:
                entries_by_id: dict[str, list] = {}
                for entry in result.entries:
                    if entry.mod_id:
                        entries_by_id.setdefault(entry.mod_id, []).append(entry)
                active_counts: dict[str, int] = {}
                for mod_id in self._staged_mod_ids:
                    active_counts[mod_id] = active_counts.get(mod_id, 0) + 1
                for mod_id, count in active_counts.items():
                    if count > 1:
                        line = (
                            f"WARNING [duplicate-active-mod-id]: '{mod_id}' appears "
                            f"{count} times in the active order."
                        )
                        lines.append(line)
                        active_diagnostic_lines.append(line)
                        active_warning_count += 1
                    installed = entries_by_id.get(mod_id, ())
                    if not installed:
                        line = (
                            f"WARNING [missing-active-mod-id]: '{mod_id}' is active "
                            "but was not found in the scanned library."
                        )
                        lines.append(line)
                        active_diagnostic_lines.append(line)
                        active_warning_count += 1
                    elif len(installed) > 1:
                        line = (
                            f"WARNING [ambiguous-active-mod-id]: '{mod_id}' matches "
                            f"{len(installed)} installed entries."
                        )
                        lines.append(line)
                        active_diagnostic_lines.append(line)
                        active_warning_count += 1

                report = analyze_dependencies(
                    result.entries,
                    self._staged_mod_ids,
                    target_build=self._metadata_target_build(),
                )
                for finding in report.findings:
                    level = "INFO" if finding.kind == "normalization" else "WARNING"
                    line = (
                        f"{level} [{finding.kind}]: "
                        f"{format_dependency_finding(finding)}"
                    )
                    lines.append(line)
                    if level == "WARNING":
                        active_diagnostic_lines.append(line)
                        active_warning_count += 1
        self._issue_error_count = error_count
        warning_count = library_warning_count + active_warning_count
        self._library_warning_count = library_warning_count
        self._library_error_count = error_count
        self._library_diagnostic_text = first_library_diagnostic
        self.review_library_findings_button.setVisible(
            first_library_diagnostic is not None
        )
        if active_warning_count == 0:
            summary = "Active order: no issues"
        else:
            issue_label = "issue" if active_warning_count == 1 else "issues"
            summary = f"Active order: {active_warning_count} {issue_label}"
        self.issue_summary.setText(summary)
        self._active_diagnostic_text = (
            active_diagnostic_lines[0] if active_diagnostic_lines else None
        )
        self.review_active_order_button.setVisible(active_warning_count > 0)
        if self._last_result is not None:
            self._filter_available_mods(self.manage_search.text())
        self.diagnostics.setPlainText("\n".join(lines) or "No diagnostics.")
        if self._extra_diagnostics:
            extra = "\n\n".join(
                self._extra_diagnostics[key] for key in sorted(self._extra_diagnostics)
            )
            self.diagnostics.appendPlainText(extra)
        return warning_count

    def _review_library_findings(self) -> None:
        self._review_diagnostic(self._library_diagnostic_text)

    def _review_active_order_issues(self) -> None:
        self._review_diagnostic(self._active_diagnostic_text)

    def _review_diagnostic(self, diagnostic_text: str | None) -> None:
        self.main_tabs.setCurrentWidget(self.library_page)
        self.diagnostics.setFocus()
        if diagnostic_text:
            first_line = diagnostic_text.splitlines()[0]
            cursor = self.diagnostics.document().find(first_line)
            if not cursor.isNull():
                self.diagnostics.setTextCursor(cursor)
                self.diagnostics.centerCursor()

    def _analyze_file_overlaps(self) -> None:
        if self._last_result is None:
            self.status.setText("Scan the mod library before analyzing file overlaps.")
            return
        result = self._last_result
        target_build = self._metadata_target_build()
        active_mod_ids = (
            tuple(self._staged_mod_ids)
            if self.file_overlap_active_only.isChecked()
            else None
        )
        self._start_diagnostic(
            "file-overlaps",
            lambda: analyze_file_overlaps(
                result,
                target_build=target_build,
                active_mod_ids=active_mod_ids,
            ),
        )

    def _analyze_console_log(self) -> None:
        initial = Path.home() / "Zomboid" / "console.txt"
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a Project Zomboid console log",
            str(initial),
            "Text logs (*.txt *.log);;All files (*.*)",
        )
        if not selected:
            return
        path = Path(selected)

        def operation() -> str:
            report = analyze_console_log(path)
            return format_console_log_report(path, report)

        self._start_diagnostic("console-log", operation)

    def _start_diagnostic(self, key: str, operation: Callable[[], object]) -> None:
        if self._diagnostic_worker is not None and self._diagnostic_worker.isRunning():
            self.status.setText("A diagnostic analysis is already running.")
            return
        self.file_overlap_button.setEnabled(False)
        self.console_log_button.setEnabled(False)
        self.status.setText("Running read-only diagnostic analysis…")
        self.progress.show()
        worker = DiagnosticWorker(operation)
        self._diagnostic_worker = worker
        worker.result_ready.connect(
            lambda value: self._show_extra_diagnostic(key, value)
        )
        worker.failed.connect(
            lambda message: self._show_extra_diagnostic(
                key, f"Analysis failed: {message}"
            )
        )
        worker.finished.connect(self._finish_diagnostic)
        worker.start()

    def _show_extra_diagnostic(self, key: str, result: object) -> None:
        if key == "file-overlaps" and isinstance(result, FileOverlapReport):
            text = format_file_overlap_report(result)
            self._extra_diagnostics[key] = text
            self._update_diagnostics()
            dialog = FileOverlapDialog(result, self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._file_overlap_dialog = dialog
            dialog.finished.connect(
                lambda _result: setattr(self, "_file_overlap_dialog", None)
            )
            dialog.show()
            self.status.setText("Read-only file-overlap report opened.")
            return
        text = str(result)
        self._extra_diagnostics[key] = text
        self._update_diagnostics()
        self.status.setText("Read-only diagnostic analysis complete.")

    def _finish_diagnostic(self) -> None:
        self.file_overlap_button.setEnabled(True)
        self.console_log_button.setEnabled(True)
        self._diagnostic_worker = None
        self._update_busy_indicator()
