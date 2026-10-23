"""Build redacted, read-only support reports for troubleshooting."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from zomboid_mod_manager.discovery.version_selection import is_numeric_game_build
from zomboid_mod_manager.domain import ScanResult

PathKind = Literal["directory", "file"]


def _inspect_path(value: str, kind: PathKind) -> tuple[bool, bool]:
    if not value.strip():
        return False, False
    try:
        path = Path(value).expanduser()
        exists = path.is_dir() if kind == "directory" else path.is_file()
        readable = exists and os.access(path, os.R_OK)
    except OSError, RuntimeError, ValueError:
        return False, False
    return exists, readable


def _path_summary(values: Sequence[str], kind: PathKind) -> dict[str, int | str]:
    statuses = [_inspect_path(value, kind) for value in values]
    return {
        "expected": kind,
        "configured_count": sum(bool(value.strip()) for value in values),
        "existing_count": sum(exists for exists, _readable in statuses),
        "readable_count": sum(readable for _exists, readable in statuses),
    }


def build_support_report(
    *,
    app_version: str,
    build_id: str,
    python_version: str,
    pyside_version: str,
    qt_version: str,
    operating_system: Mapping[str, str],
    storage_mode: str,
    selected_paths: Mapping[str, Sequence[str]],
    scan_result: ScanResult | None,
    scan_duration_seconds: float | None,
    metadata_target: str,
    exact_game_version: str,
    detected_path_warning_count: int,
    active_configuration_loaded: bool,
    staged_mod_ids: Sequence[str],
    ordering_rules_valid: bool,
    ordering_rule_count: int,
) -> dict[str, Any]:
    """Return troubleshooting counts and statuses without path or mod values."""
    result = scan_result
    entries = result.entries if result is not None else ()
    known_mod_ids = {entry.mod_id for entry in entries if entry.mod_id}
    diagnostic_levels = (
        [diagnostic.level for diagnostic in result.diagnostics]
        if result is not None
        else []
    )
    metadata_diagnostic_count = sum(
        len(entry.diagnostics)
        + sum(len(candidate.diagnostics) for candidate in entry.candidates)
        for entry in entries
    )
    scan_duration_ms = (
        max(0, round(scan_duration_seconds * 1000))
        if scan_duration_seconds is not None
        else None
    )
    active_ids = tuple(staged_mod_ids)
    safe_metadata_target = (
        metadata_target if metadata_target in {"all", "41", "42"} else "unknown"
    )
    safe_game_version = (
        exact_game_version.strip()
        if safe_metadata_target == "42"
        and is_numeric_game_build(exact_game_version.strip())
        else None
    )

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "app": {
            "version": app_version,
            "build_id": build_id,
            "python_version": python_version,
            "pyside_version": pyside_version,
            "qt_version": qt_version,
            "storage_mode": storage_mode,
        },
        "system": dict(operating_system),
        "settings": {
            "metadata_target": safe_metadata_target,
            "exact_game_version": safe_game_version,
            "ordering_rules_valid": ordering_rules_valid,
            "ordering_rule_count": ordering_rule_count,
        },
        "paths": {
            role: _path_summary(
                values, "file" if role == "global_mod_list" else "directory"
            )
            for role, values in selected_paths.items()
        },
        "discovery": {
            "scan_completed": result is not None,
            "scan_duration_ms": scan_duration_ms,
            "local_mod_entry_count": len(result.local_entries) if result else 0,
            "workshop_item_count": len(result.workshop_items) if result else 0,
            "workshop_mod_entry_count": (
                sum(len(item.entries) for item in result.workshop_items)
                if result
                else 0
            ),
            "metadata_candidate_count": result.metadata_candidate_count
            if result
            else 0,
            "scan_warning_count": diagnostic_levels.count("warning"),
            "scan_error_count": diagnostic_levels.count("error"),
            "metadata_diagnostic_count": metadata_diagnostic_count,
            "detected_path_warning_count": detected_path_warning_count,
        },
        "workspace": {
            "global_configuration_loaded": active_configuration_loaded,
            "staged_mod_count": len(active_ids),
            "staged_mods_found": sum(mod_id in known_mod_ids for mod_id in active_ids),
            "staged_mods_not_found": sum(
                mod_id not in known_mod_ids for mod_id in active_ids
            ),
        },
        "privacy": {
            "folder_paths_included": False,
            "mod_names_or_ids_included": False,
            "workshop_ids_included": False,
            "console_logs_or_file_contents_included": False,
        },
    }


def format_support_report(report: Mapping[str, Any]) -> str:
    """Format the redacted report for preview and JSON export."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
