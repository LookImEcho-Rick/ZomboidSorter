"""Read-only scanner for supported Project Zomboid mod layouts."""

from __future__ import annotations

import os
import re
import stat
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from zomboid_mod_manager.domain import (
    Diagnostic,
    MetadataCandidate,
    ModEntry,
    ScanResult,
    SourceType,
    WorkshopItem,
)

_VERSION_FOLDER = re.compile(r"^\d+(?:\.\d+)*$")
_MAX_METADATA_BYTES = 1024 * 1024
_REPEATABLE_METADATA_FIELDS = {"description", "poster", "pack", "tiledef"}
_LINK_SKIP_MESSAGE = (
    "Skipped symbolic link or junction; discovery does not follow linked paths."
)


class ScanCancelled(Exception):
    """Raised when the caller requests that a read-only scan stop."""


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ScanCancelled


def _report_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_link(path: Path) -> bool:
    """Recognize symlinks and Windows junctions without following them."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _report_link(path: Path, diagnostics: list[Diagnostic] | None) -> None:
    if diagnostics is None or any(
        diagnostic.path == path and diagnostic.message == _LINK_SKIP_MESSAGE
        for diagnostic in diagnostics
    ):
        return
    diagnostics.append(Diagnostic(_LINK_SKIP_MESSAGE, path))


def _candidate_paths(
    entry_path: Path,
    diagnostics: list[Diagnostic] | None = None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[Path, ...]:
    _check_cancelled(cancelled)
    candidates: list[Path] = []
    if _is_link(entry_path):
        _report_link(entry_path, diagnostics)
        return ()

    root_info = entry_path / "mod.info"
    if _is_link(root_info):
        _report_link(root_info, diagnostics)
    elif root_info.is_file():
        candidates.append(root_info)

    common_dir = entry_path / "common"
    common_info = entry_path / "common" / "mod.info"
    if _is_link(common_dir):
        _report_link(common_dir, diagnostics)
    elif _is_link(common_info):
        _report_link(common_info, diagnostics)
    elif common_info.is_file():
        candidates.append(common_info)

    try:
        children: list[Path] = []
        for child in entry_path.iterdir():
            _check_cancelled(cancelled)
            children.append(child)
    except OSError:
        children = []

    version_dirs: list[Path] = []
    for child in children:
        _check_cancelled(cancelled)
        if not _VERSION_FOLDER.fullmatch(child.name):
            continue
        if _is_link(child):
            _report_link(child, diagnostics)
        elif child.is_dir():
            version_dirs.append(child)
    version_dirs.sort(
        key=lambda child: tuple(int(part) for part in child.name.split("."))
    )

    for version_dir in version_dirs:
        _check_cancelled(cancelled)
        metadata_path = version_dir / "mod.info"
        if _is_link(metadata_path):
            _report_link(metadata_path, diagnostics)
        elif metadata_path.is_file():
            candidates.append(metadata_path)
    return tuple(candidates)


def _layout(entry_path: Path, metadata_path: Path) -> tuple[str, str | None]:
    parent = metadata_path.parent
    if parent == entry_path:
        return "root (Build 41 style)", None
    if parent.name.casefold() == "common":
        return "common (shared)", None
    return f"versioned ({parent.name})", parent.name


def _parse_metadata(
    metadata_path: Path,
    entry_path: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> MetadataCandidate:
    _check_cancelled(cancelled)
    diagnostics: list[str] = []
    layout, version_folder = _layout(entry_path, metadata_path)

    def failed_candidate(message: str) -> MetadataCandidate:
        return MetadataCandidate(
            path=metadata_path,
            layout=layout,
            version_folder=version_folder,
            fields={},
            diagnostics=(message,),
        )

    try:
        if _is_link(metadata_path):
            return failed_candidate(
                "mod.info is a symbolic link or junction; linked paths are skipped."
            )
        file_stat = metadata_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(file_stat.st_mode):
            return failed_candidate("mod.info is not a regular file; skipped.")
        if file_stat.st_size > _MAX_METADATA_BYTES:
            return failed_candidate(
                "mod.info exceeds the 1 MiB size limit; metadata was skipped."
            )

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(metadata_path, flags)
        with os.fdopen(descriptor, "rb") as source_file:
            _check_cancelled(cancelled)
            opened_stat = os.fstat(source_file.fileno())
            if not stat.S_ISREG(opened_stat.st_mode):
                return failed_candidate("mod.info is not a regular file; skipped.")
            if opened_stat.st_size > _MAX_METADATA_BYTES:
                return failed_candidate(
                    "mod.info exceeds the 1 MiB size limit; metadata was skipped."
                )
            raw = source_file.read(_MAX_METADATA_BYTES + 1)
        if len(raw) > _MAX_METADATA_BYTES:
            return failed_candidate(
                "mod.info grew beyond the 1 MiB size limit while being read; metadata was skipped."
            )
    except OSError as exc:
        return failed_candidate(f"Could not read mod.info: {exc}")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            return failed_candidate(
                "Could not decode mod.info as UTF-8 or Windows-1252; metadata was skipped."
            )
        diagnostics.append("Metadata is not UTF-8; decoded with Windows-1252 fallback.")

    fields: dict[str, str] = {}
    current_key: str | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            if current_key == "description":
                fields[current_key] += "\n" + line
            else:
                diagnostics.append(f"Line {line_number} has no key=value separator.")
            continue

        raw_key, value = line.split("=", 1)
        key = raw_key.strip().casefold()
        if not key:
            diagnostics.append(f"Line {line_number} has an empty metadata key.")
            current_key = None
            continue
        if key in fields:
            if key in _REPEATABLE_METADATA_FIELDS:
                # Project Zomboid metadata can declare multiple descriptions,
                # posters, texture packs, and tile definitions. Preserve all
                # values instead of reporting supported repeats as duplicates.
                fields[key] += "\n" + value.strip()
                current_key = key
                continue
            diagnostics.append(
                f"Duplicate metadata key '{key}' at line {line_number}; first value kept."
            )
            current_key = None
            continue
        fields[key] = value.strip()
        current_key = key

    if not fields:
        diagnostics.append("No key=value metadata was found.")
    if not fields.get("id"):
        diagnostics.append("Missing required Mod ID field 'id'.")
    if not fields.get("name"):
        diagnostics.append("Missing display name field 'name'.")

    return MetadataCandidate(
        path=metadata_path,
        layout=layout,
        version_folder=version_folder,
        fields=fields,
        diagnostics=tuple(diagnostics),
    )


def _build_entries(
    entry_path: Path,
    installation_path: Path,
    source: SourceType,
    workshop_id: str | None,
    metadata_paths: tuple[Path, ...],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ModEntry, ...]:
    parsed_candidates: list[MetadataCandidate] = []
    for path in metadata_paths:
        _check_cancelled(cancelled)
        parsed_candidates.append(_parse_metadata(path, entry_path, cancelled=cancelled))
    parsed = tuple(parsed_candidates)
    grouped: dict[str, list[MetadataCandidate]] = defaultdict(list)
    for candidate in parsed:
        mod_id = candidate.fields.get("id", "").strip()
        # Invalid metadata files remain separately visible rather than being merged.
        group_key = mod_id or f"__invalid__:{_path_key(candidate.path)}"
        grouped[group_key].append(candidate)

    entries: list[ModEntry] = []
    for group_key, candidates_list in grouped.items():
        candidates = tuple(candidates_list)
        first = candidates[0]
        mod_id = first.fields.get("id", "").strip() or None
        names = {candidate.fields.get("name", "").strip() for candidate in candidates}
        issues = [
            f"{candidate.path}: {message}"
            for candidate in candidates
            for message in candidate.diagnostics
        ]
        if len(names - {""}) > 1:
            issues.append(
                "Metadata candidates have different names; no active build was selected."
            )

        name = first.fields.get("name", "").strip() or mod_id or entry_path.name
        version = (
            first.fields.get("modversion", "").strip()
            or first.fields.get("version", "").strip()
        )
        entry_key = "|".join(
            (
                source,
                workshop_id or "",
                _path_key(entry_path),
                mod_id or group_key,
            )
        )
        entries.append(
            ModEntry(
                key=entry_key,
                mod_id=mod_id,
                name=name,
                author=(
                    first.fields.get("author") or first.fields.get("authors") or ""
                ).strip(),
                description=first.fields.get("description", "").strip(),
                version=version,
                requirements_raw=first.fields.get("require", "").strip(),
                source=source,
                installation_path=installation_path,
                entry_path=entry_path,
                workshop_id=workshop_id,
                candidates=candidates,
                diagnostics=tuple(issues),
                directory_candidates=parsed,
            )
        )
    return tuple(entries)


def _is_entry(
    entry_path: Path,
    diagnostics: list[Diagnostic] | None = None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> bool:
    return bool(_candidate_paths(entry_path, diagnostics, cancelled=cancelled))


def _workshop_entry_roots(
    item_path: Path,
    diagnostics: list[Diagnostic],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[str] = set()
    for wrapper in (item_path / "mods", item_path / "Contents" / "mods"):
        _check_cancelled(cancelled)
        if _is_link(wrapper):
            _report_link(wrapper, diagnostics)
            continue
        if not wrapper.is_dir():
            continue
        try:
            children = []
            for child in wrapper.iterdir():
                _check_cancelled(cancelled)
                children.append(child)
            children.sort(key=lambda path: path.name.casefold())
        except OSError:
            continue
        for child in children:
            _check_cancelled(cancelled)
            if _is_link(child):
                _report_link(child, diagnostics)
                continue
            if not child.is_dir():
                continue
            key = _path_key(child)
            if key not in seen:
                seen.add(key)
                roots.append(child)

    if _is_entry(item_path, diagnostics, cancelled=cancelled):
        roots.insert(0, item_path)
    return tuple(roots)


def _scan_local_root(
    root: Path,
    diagnostics: list[Diagnostic],
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[ModEntry]:
    _check_cancelled(cancelled)
    _report_progress(progress, f"Checking local mods: {root}")
    if _is_link(root):
        _report_link(root, diagnostics)
        return []
    if not root.is_dir():
        diagnostics.append(
            Diagnostic("Local mod folder does not exist or is unreadable.", root)
        )
        return []

    entry_roots: list[Path] = []
    seen: set[str] = set()
    if _is_entry(root, diagnostics, cancelled=cancelled):
        entry_roots.append(root)
        seen.add(_path_key(root))
    try:
        children = []
        for child in root.iterdir():
            _check_cancelled(cancelled)
            children.append(child)
        children.sort(key=lambda path: path.name.casefold())
    except OSError as exc:
        diagnostics.append(
            Diagnostic(f"Could not list local mod folder: {exc}", root, "error")
        )
        return []

    for child in children:
        _check_cancelled(cancelled)
        if _is_link(child):
            _report_link(child, diagnostics)
        elif child.is_dir() and _path_key(child) not in seen:
            entry_roots.append(child)
            seen.add(_path_key(child))

    entries: list[ModEntry] = []
    for index, entry_root in enumerate(entry_roots, start=1):
        _check_cancelled(cancelled)
        if index == 1 or index % 25 == 0 or index == len(entry_roots):
            _report_progress(
                progress,
                f"Scanning local mods: {index}/{len(entry_roots)} folders",
            )
        metadata_paths = _candidate_paths(entry_root, diagnostics, cancelled=cancelled)
        if not metadata_paths:
            diagnostics.append(
                Diagnostic("Local mod entry has no recognized mod.info.", entry_root)
            )
            continue
        entries.extend(
            _build_entries(
                entry_root,
                entry_root,
                "local",
                None,
                metadata_paths,
                cancelled=cancelled,
            )
        )
    return entries


def scan_workshop_item(
    item_path: Path,
    workshop_id: str,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> WorkshopItem:
    """Read one item, including an explicitly selected shared collection object."""
    diagnostics: list[Diagnostic] = []
    _check_cancelled(cancelled)
    if _is_link(item_path):
        _report_link(item_path, diagnostics)
        return WorkshopItem(workshop_id, item_path, (), tuple(diagnostics))
    roots = _workshop_entry_roots(item_path, diagnostics, cancelled=cancelled)
    if not roots:
        diagnostics.append(
            Diagnostic(
                "Workshop item has no recognized mod.info or mod entry folder.",
                item_path,
            )
        )
    entries: list[ModEntry] = []
    for root in roots:
        metadata = _candidate_paths(root, diagnostics, cancelled=cancelled)
        if not metadata:
            diagnostics.append(
                Diagnostic("Workshop mod entry has no recognized mod.info.", root)
            )
            continue
        entries.extend(
            _build_entries(
                root, item_path, "workshop", workshop_id, metadata, cancelled=cancelled
            )
        )
    return WorkshopItem(workshop_id, item_path, tuple(entries), tuple(diagnostics))


def _scan_workshop_root(
    root: Path,
    diagnostics: list[Diagnostic],
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[WorkshopItem]:
    _check_cancelled(cancelled)
    _report_progress(progress, f"Listing Workshop items: {root}")
    if _is_link(root):
        _report_link(root, diagnostics)
        return []
    if not root.is_dir():
        diagnostics.append(
            Diagnostic("Workshop content folder does not exist or is unreadable.", root)
        )
        return []

    try:
        item_paths = []
        for item_path in root.iterdir():
            _check_cancelled(cancelled)
            item_paths.append(item_path)
        item_paths.sort(key=lambda path: path.name)
    except OSError as exc:
        diagnostics.append(
            Diagnostic(f"Could not list Workshop content folder: {exc}", root, "error")
        )
        return []

    items: list[WorkshopItem] = []
    scanned_items = 0
    for item_path in item_paths:
        _check_cancelled(cancelled)
        if not item_path.name.isdecimal():
            continue
        scanned_items += 1
        if scanned_items == 1 or scanned_items % 25 == 0:
            _report_progress(
                progress, f"Scanning Workshop items: {scanned_items} checked"
            )
        if _is_link(item_path):
            _report_link(item_path, diagnostics)
            continue
        if not item_path.is_dir():
            continue
        item = scan_workshop_item(item_path, item_path.name, cancelled=cancelled)
        items.append(item)
        diagnostics.extend(item.diagnostics)
    _report_progress(progress, f"Scanned {scanned_items} Workshop item folders")
    return items


def _duplicate_mod_id_diagnostics(
    entries: Iterable[ModEntry],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> list[Diagnostic]:
    by_id: dict[str, list[ModEntry]] = defaultdict(list)
    for entry in entries:
        _check_cancelled(cancelled)
        if entry.mod_id:
            by_id[entry.mod_id].append(entry)

    diagnostics = []
    for mod_id, matches in sorted(by_id.items(), key=lambda item: item[0].casefold()):
        _check_cancelled(cancelled)
        if len({entry.key for entry in matches}) > 1:
            locations = ", ".join(str(entry.entry_path) for entry in matches)
            diagnostics.append(
                Diagnostic(
                    f"Mod ID '{mod_id}' appears in {len({entry.key for entry in matches})} installed entries; all copies are preserved. Locations: {locations}"
                )
            )
    return diagnostics


def merge_scan_results(
    local_scan: ScanResult,
    previous_scan: ScanResult | None,
    *,
    preferred_mod_ids: Iterable[str] = (),
    preferred_roots: Iterable[Path] = (),
) -> ScanResult:
    """Refresh local entries while reusing a prior Workshop scan.

    When an app-owned collection copy is preferred, other scanned entries with
    the same Mod ID stay untouched on disk but are omitted from the active scan
    view while that pack is loaded.
    """
    workshop_items = previous_scan.workshop_items if previous_scan else ()
    preferred_ids = set(preferred_mod_ids)
    root_keys = tuple(_path_key(Path(root)).rstrip(os.sep) for root in preferred_roots)

    def is_preferred(entry: ModEntry) -> bool:
        entry_key = _path_key(entry.entry_path)
        return any(
            entry_key == root_key or entry_key.startswith(root_key + os.sep)
            for root_key in root_keys
        )

    original_entries = local_scan.local_entries + tuple(
        entry for item in workshop_items for entry in item.entries
    )
    preferred_ids_found = {
        mod_id
        for mod_id in preferred_ids
        if any(
            entry.mod_id == mod_id and is_preferred(entry) for entry in original_entries
        )
    }

    def keep_entry(entry: ModEntry) -> bool:
        return entry.mod_id not in preferred_ids_found or is_preferred(entry)

    local_entries = tuple(
        entry for entry in local_scan.local_entries if keep_entry(entry)
    )
    workshop_items = tuple(
        replace(
            item, entries=tuple(entry for entry in item.entries if keep_entry(entry))
        )
        for item in workshop_items
    )
    entries = local_entries + tuple(
        entry for item in workshop_items for entry in item.entries
    )

    duplicate_prefix = "Mod ID '"
    diagnostics = list(
        dict.fromkeys(
            diagnostic
            for source in (local_scan, previous_scan)
            if source is not None
            for diagnostic in source.diagnostics
            if not diagnostic.message.startswith(duplicate_prefix)
        )
    )
    diagnostics.extend(_duplicate_mod_id_diagnostics(entries))
    return ScanResult(local_entries, workshop_items, tuple(diagnostics))


def scan_mods(
    *,
    local_roots: Iterable[Path] = (),
    workshop_roots: Iterable[Path] = (),
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScanResult:
    """Scan chosen roots without modifying files or choosing a game-version candidate."""
    _check_cancelled(cancelled)
    diagnostics: list[Diagnostic] = []
    unique_local: list[Path] = []
    unique_workshop: list[Path] = []
    seen_local: set[str] = set()
    seen_workshop: set[str] = set()

    for root in local_roots:
        _check_cancelled(cancelled)
        key = _path_key(Path(root))
        if key not in seen_local:
            seen_local.add(key)
            unique_local.append(Path(root))
    for root in workshop_roots:
        _check_cancelled(cancelled)
        key = _path_key(Path(root))
        if key not in seen_workshop:
            seen_workshop.add(key)
            unique_workshop.append(Path(root))

    if not unique_local and not unique_workshop:
        diagnostics.append(Diagnostic("No scan locations are configured."))

    local_entries: list[ModEntry] = []
    for root in unique_local:
        local_entries.extend(
            _scan_local_root(
                root,
                diagnostics,
                cancelled=cancelled,
                progress=progress,
            )
        )
    workshop_items: list[WorkshopItem] = []
    for root in unique_workshop:
        workshop_items.extend(
            _scan_workshop_root(
                root,
                diagnostics,
                cancelled=cancelled,
                progress=progress,
            )
        )

    all_entries = list(local_entries)
    for item in workshop_items:
        _check_cancelled(cancelled)
        all_entries.extend(item.entries)
    diagnostics.extend(_duplicate_mod_id_diagnostics(all_entries, cancelled=cancelled))

    by_workshop_id: dict[str, list[WorkshopItem]] = defaultdict(list)
    for item in workshop_items:
        _check_cancelled(cancelled)
        by_workshop_id[item.workshop_id].append(item)
    for workshop_id, items in sorted(by_workshop_id.items()):
        _check_cancelled(cancelled)
        if len(items) > 1:
            locations = ", ".join(str(item.path) for item in items)
            diagnostics.append(
                Diagnostic(
                    f"Workshop item '{workshop_id}' is present in {len(items)} scanned locations; all copies are preserved. Locations: {locations}"
                )
            )

    _check_cancelled(cancelled)
    return ScanResult(
        local_entries=tuple(local_entries),
        workshop_items=tuple(workshop_items),
        diagnostics=tuple(diagnostics),
    )
