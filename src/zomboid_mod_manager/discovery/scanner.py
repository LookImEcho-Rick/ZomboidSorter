"""Read-only scanner for supported Project Zomboid mod layouts."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Iterable
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


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _candidate_paths(entry_path: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    root_info = entry_path / "mod.info"
    if root_info.is_file():
        candidates.append(root_info)

    common_info = entry_path / "common" / "mod.info"
    if common_info.is_file():
        candidates.append(common_info)

    try:
        version_dirs = sorted(
            (
                child
                for child in entry_path.iterdir()
                if child.is_dir() and _VERSION_FOLDER.fullmatch(child.name)
            ),
            key=lambda child: tuple(int(part) for part in child.name.split(".")),
        )
    except OSError:
        version_dirs = []

    candidates.extend(
        version_dir / "mod.info"
        for version_dir in version_dirs
        if (version_dir / "mod.info").is_file()
    )
    return tuple(candidates)


def _layout(entry_path: Path, metadata_path: Path) -> tuple[str, str | None]:
    parent = metadata_path.parent
    if parent == entry_path:
        return "root (Build 41 style)", None
    if parent.name.casefold() == "common":
        return "common (shared)", None
    return f"versioned ({parent.name})", parent.name


def _parse_metadata(metadata_path: Path, entry_path: Path) -> MetadataCandidate:
    diagnostics: list[str] = []
    try:
        raw = metadata_path.read_bytes()
    except OSError as exc:
        return MetadataCandidate(
            path=metadata_path,
            layout=_layout(entry_path, metadata_path)[0],
            version_folder=_layout(entry_path, metadata_path)[1],
            fields={},
            diagnostics=(f"Could not read mod.info: {exc}",),
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
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
            if key in {"description", "poster"}:
                # Real Build 42 mods commonly split long descriptions across
                # repeated description= lines. The Build 42.21 mod.info
                # reference also permits multiple poster= images. Preserve
                # both supported repeatable fields instead of flagging them.
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

    layout, version_folder = _layout(entry_path, metadata_path)
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
) -> tuple[ModEntry, ...]:
    parsed = tuple(_parse_metadata(path, entry_path) for path in metadata_paths)
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
            )
        )
    return tuple(entries)


def _is_entry(entry_path: Path) -> bool:
    return bool(_candidate_paths(entry_path))


def _workshop_entry_roots(item_path: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[str] = set()
    for wrapper in (item_path / "mods", item_path / "Contents" / "mods"):
        if not wrapper.is_dir():
            continue
        try:
            children = sorted(wrapper.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            key = _path_key(child)
            if key not in seen:
                seen.add(key)
                roots.append(child)

    if _is_entry(item_path):
        roots.insert(0, item_path)
    return tuple(roots)


def _scan_local_root(root: Path, diagnostics: list[Diagnostic]) -> list[ModEntry]:
    if not root.is_dir():
        diagnostics.append(
            Diagnostic("Local mod folder does not exist or is unreadable.", root)
        )
        return []

    entry_roots: list[Path] = []
    seen: set[str] = set()
    if _is_entry(root):
        entry_roots.append(root)
        seen.add(_path_key(root))
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        diagnostics.append(
            Diagnostic(f"Could not list local mod folder: {exc}", root, "error")
        )
        return []

    for child in children:
        if child.is_dir() and _path_key(child) not in seen:
            entry_roots.append(child)
            seen.add(_path_key(child))

    entries: list[ModEntry] = []
    for entry_root in entry_roots:
        metadata_paths = _candidate_paths(entry_root)
        if not metadata_paths:
            diagnostics.append(
                Diagnostic("Local mod entry has no recognized mod.info.", entry_root)
            )
            continue
        entries.extend(
            _build_entries(entry_root, entry_root, "local", None, metadata_paths)
        )
    return entries


def _scan_workshop_root(
    root: Path, diagnostics: list[Diagnostic]
) -> list[WorkshopItem]:
    if not root.is_dir():
        diagnostics.append(
            Diagnostic("Workshop content folder does not exist or is unreadable.", root)
        )
        return []

    try:
        item_paths = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        diagnostics.append(
            Diagnostic(f"Could not list Workshop content folder: {exc}", root, "error")
        )
        return []

    items: list[WorkshopItem] = []
    for item_path in item_paths:
        if not item_path.is_dir() or not item_path.name.isdecimal():
            continue
        item_diags: list[Diagnostic] = []
        entry_roots = _workshop_entry_roots(item_path)
        if not entry_roots:
            item_diags.append(
                Diagnostic(
                    "Workshop item has no recognized mod.info or mod entry folder.",
                    item_path,
                )
            )

        entries: list[ModEntry] = []
        for entry_root in entry_roots:
            metadata_paths = _candidate_paths(entry_root)
            if not metadata_paths:
                item_diags.append(
                    Diagnostic(
                        "Workshop mod entry has no recognized mod.info.", entry_root
                    )
                )
                continue
            entries.extend(
                _build_entries(
                    entry_root, item_path, "workshop", item_path.name, metadata_paths
                )
            )

        items.append(
            WorkshopItem(
                workshop_id=item_path.name,
                path=item_path,
                entries=tuple(entries),
                diagnostics=tuple(item_diags),
            )
        )
        diagnostics.extend(item_diags)
    return items


def scan_mods(
    *, local_roots: Iterable[Path] = (), workshop_roots: Iterable[Path] = ()
) -> ScanResult:
    """Scan chosen roots without modifying files or choosing a game-version candidate."""
    diagnostics: list[Diagnostic] = []
    unique_local: list[Path] = []
    unique_workshop: list[Path] = []
    seen_local: set[str] = set()
    seen_workshop: set[str] = set()

    for root in local_roots:
        key = _path_key(Path(root))
        if key not in seen_local:
            seen_local.add(key)
            unique_local.append(Path(root))
    for root in workshop_roots:
        key = _path_key(Path(root))
        if key not in seen_workshop:
            seen_workshop.add(key)
            unique_workshop.append(Path(root))

    if not unique_local and not unique_workshop:
        diagnostics.append(Diagnostic("No scan locations are configured."))

    local_entries = [
        entry for root in unique_local for entry in _scan_local_root(root, diagnostics)
    ]
    workshop_items = [
        item
        for root in unique_workshop
        for item in _scan_workshop_root(root, diagnostics)
    ]

    all_entries = local_entries + [
        entry for item in workshop_items for entry in item.entries
    ]
    by_id: dict[str, list[ModEntry]] = defaultdict(list)
    for entry in all_entries:
        if entry.mod_id:
            by_id[entry.mod_id].append(entry)
    for mod_id, matches in sorted(by_id.items(), key=lambda item: item[0].casefold()):
        distinct_entries = {entry.key for entry in matches}
        if len(distinct_entries) > 1:
            locations = ", ".join(str(entry.entry_path) for entry in matches)
            diagnostics.append(
                Diagnostic(
                    f"Mod ID '{mod_id}' appears in {len(distinct_entries)} installed entries; all copies are preserved. Locations: {locations}"
                )
            )

    by_workshop_id: dict[str, list[WorkshopItem]] = defaultdict(list)
    for item in workshop_items:
        by_workshop_id[item.workshop_id].append(item)
    for workshop_id, items in sorted(by_workshop_id.items()):
        if len(items) > 1:
            locations = ", ".join(str(item.path) for item in items)
            diagnostics.append(
                Diagnostic(
                    f"Workshop item '{workshop_id}' is present in {len(items)} scanned locations; all copies are preserved. Locations: {locations}"
                )
            )

    return ScanResult(
        local_entries=tuple(local_entries),
        workshop_items=tuple(workshop_items),
        diagnostics=tuple(diagnostics),
    )
