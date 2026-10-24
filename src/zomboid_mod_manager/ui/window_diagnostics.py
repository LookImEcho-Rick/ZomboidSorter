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
from zomboid_mod_manager.diagnostics.dependencies import analyze_dependencies
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
        warning_count = 0
        error_count = 0
        if self._user_rule_settings_error:
            lines.append(
                "WARNING [invalid-user-order-rules]: Stored rules were ignored: "
                + self._user_rule_settings_error
            )
            warning_count += 1
        result = self._last_result
        if result is not None:
            for diagnostic in result.diagnostics:
                lines.append(
                    f"{diagnostic.level.upper()}: {diagnostic.message}"
                    + (f"\n  {diagnostic.path}" if diagnostic.path else "")
                )
                if diagnostic.level == "warning":
                    warning_count += 1
                elif diagnostic.level == "error":
                    error_count += 1
            for item in result.workshop_items:
                for diagnostic in item.diagnostics:
                    if diagnostic not in result.diagnostics:
                        lines.append(
                            f"{diagnostic.level.upper()}: {diagnostic.message}\n  {diagnostic.path}"
                        )
                        if diagnostic.level == "warning":
                            warning_count += 1
                        elif diagnostic.level == "error":
                            error_count += 1
            for entry in result.entries:
                messages = self._entry_diagnostics_for_target(
                    entry, self._discover_target_build()
                )
                lines.extend(f"WARNING: {message}" for message in messages)
                warning_count += len(messages)

            installed_workshop_ids = {
                item.workshop_id for item in result.workshop_items
            }
            missing_workshop_ids = [
                workshop_id
                for workshop_id in self._profile_workshop_ids
                if workshop_id not in installed_workshop_ids
            ]
            if missing_workshop_ids:
                lines.append(
                    "WARNING [missing-workshop-items]: Profile references Workshop items not installed locally: "
                    + ", ".join(missing_workshop_ids)
                )
                warning_count += 1

            if self._active_config is not None:
                report = analyze_dependencies(
                    result.entries,
                    self._staged_mod_ids,
                    target_build=self._discover_target_build(),
                )
                for finding in report.findings:
                    level = "INFO" if finding.kind == "normalization" else "WARNING"
                    lines.append(
                        f"{level} [{finding.kind}]: {finding.message}"
                        + (
                            f"\n  {finding.candidate_path}"
                            if finding.candidate_path
                            else ""
                        )
                    )
                    if level == "WARNING":
                        warning_count += 1
        self._issue_error_count = error_count
        self.issue_summary.setText(
            f"⚠ {warning_count} warning(s)  ·  ● {error_count} error(s)"
        )
        self.diagnostics.setPlainText("\n".join(lines) or "No diagnostics.")
        if self._extra_diagnostics:
            extra = "\n\n".join(
                self._extra_diagnostics[key] for key in sorted(self._extra_diagnostics)
            )
            self.diagnostics.appendPlainText(extra)
        return warning_count

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
