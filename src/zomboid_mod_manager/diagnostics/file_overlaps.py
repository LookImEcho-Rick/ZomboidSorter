"""Opt-in, read-only candidate file-overlap analysis.

An overlap means two distinct mod entries ship the same relative path in their
metadata candidate trees. It does not decide which candidate is active or
which file wins at runtime.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from zomboid_mod_manager.discovery.version_selection import resolve_entry_metadata
from zomboid_mod_manager.domain import MetadataCandidate, ModEntry, ScanResult

ContentRelation = Literal["different", "unverified"]
_MAX_FILES = 100_000
_MAX_HASH_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_HASH_BYTES = 512 * 1024 * 1024
_MAX_PAIR_COMPARISONS = 100_000
_MAX_STORED_DETAILS = 100
# Every reported path needs at least two indexed files, so this retains every
# group that can be found within the file scan limit.
_MAX_STORED_PATH_GROUPS = _MAX_FILES // 2


@dataclass(frozen=True)
class FileOverlap:
    relative_path: str
    first_mod_id: str
    second_mod_id: str
    first_file: Path
    second_file: Path
    first_candidate: Path
    second_candidate: Path
    content_relation: ContentRelation


@dataclass(frozen=True)
class FileOverlapPathGroup:
    relative_path: str
    comparison_count: int
    different_count: int
    unverified_count: int
    mod_ids: tuple[str, ...]
    examples: tuple[FileOverlap, ...]


@dataclass(frozen=True)
class FileOverlapReport:
    candidate_count: int
    entry_count: int
    target_build: str
    staged_only: bool
    files_scanned: int
    overlap_count: int
    different_count: int
    unverified_count: int
    unique_path_count: int
    path_groups: tuple[FileOverlapPathGroup, ...]
    path_groups_limited: bool
    overlaps: tuple[FileOverlap, ...]
    skipped_files: int
    truncated: bool
    details_limited: bool


@dataclass(frozen=True)
class _FileOwner:
    entry: ModEntry
    candidate: MetadataCandidate
    path: Path
    size: int


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _files_for_candidate(
    candidate: MetadataCandidate, sibling_candidate_roots: set[str]
) -> Iterator[Path]:
    root = candidate.path.parent
    if root.is_symlink() or not root.is_dir():
        return

    def walk_error(_error: OSError) -> None:
        return

    for current, directories, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=walk_error
    ):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if not (current_path / name).is_symlink()
            and _path_key(current_path / name) not in sibling_candidate_roots
        ]
        for filename in filenames:
            path = current_path / filename
            if filename.casefold() == "mod.info" or path.is_symlink():
                continue
            yield path


def _sha256(path: Path, cache: dict[str, str | None], expected_size: int) -> str | None:
    key = _path_key(path)
    if key in cache:
        return cache[key]
    try:
        before = path.stat(follow_symlinks=False)
        if before.st_size != expected_size or before.st_size > _MAX_HASH_BYTES:
            cache[key] = None
            return None
        digest = hashlib.sha256()
        bytes_read = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                bytes_read += len(block)
                if bytes_read > _MAX_HASH_BYTES:
                    cache[key] = None
                    return None
                digest.update(block)
        after = path.stat(follow_symlinks=False)
        value: str | None = (
            digest.hexdigest()
            if bytes_read == expected_size
            and before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            else None
        )
    except OSError:
        value = None
    cache[key] = value
    return value


def analyze_file_overlaps(
    scan_result: ScanResult,
    *,
    target_build: str = "all",
    active_mod_ids: Iterable[str] | None = None,
) -> FileOverlapReport:
    """Find paths shared by distinct mod entries without changing mod files.

    Candidate folders are treated independently. An exact target build selects
    its resolved candidate; ``all`` includes every candidate. When
    ``active_mod_ids`` is provided, entries outside that staged list are
    skipped. Overlaps are reported only when contents differ or are too
    large/unreadable to compare; identical copies are omitted. The work is
    bounded and callers should run it off the UI thread for real libraries.
    """
    staged_only = active_mod_ids is not None
    active_ids = set(active_mod_ids) if active_mod_ids is not None else None
    entries = tuple(
        entry
        for entry in scan_result.entries
        if entry.mod_id and (active_ids is None or entry.mod_id in active_ids)
    )
    candidates_by_entry = {
        entry.key: resolve_entry_metadata(entry, target_build).candidates
        for entry in entries
    }
    candidate_count = sum(
        len(candidates) for candidates in candidates_by_entry.values()
    )
    roots_by_entry = {
        entry.key: {_path_key(candidate.path.parent) for candidate in entry.candidates}
        for entry in entries
    }
    owners: dict[str, list[_FileOwner]] = defaultdict(list)
    file_count = 0
    skipped = 0
    truncated = False

    for entry in entries:
        for candidate in candidates_by_entry[entry.key]:
            sibling_roots = roots_by_entry.get(entry.key, set()) - {
                _path_key(candidate.path.parent)
            }
            for path in _files_for_candidate(candidate, sibling_roots):
                if file_count >= _MAX_FILES:
                    truncated = True
                    break
                relative_path = path.relative_to(candidate.path.parent).as_posix()
                relative_parts = relative_path.split("/")
                # PZ mod metadata lives beside the game-facing media tree.
                # Root-level icons, changelogs, and packaging files are not
                # meaningful content-overlap candidates.
                if len(relative_parts) < 2 or relative_parts[0].casefold() != "media":
                    continue
                file_count += 1
                try:
                    size = path.stat(follow_symlinks=False).st_size
                except OSError:
                    skipped += 1
                    continue
                relative = relative_path.casefold()
                owners[relative].append(_FileOwner(entry, candidate, path, size))
            if truncated:
                break
        if truncated:
            break

    overlaps: list[FileOverlap] = []
    digest_cache: dict[str, str | None] = {}
    hash_bytes = 0
    overlap_count = 0
    different_count = 0
    unverified_count = 0
    pair_comparisons = 0
    path_counts: Counter[str] = Counter()
    path_different_counts: Counter[str] = Counter()
    path_unverified_counts: Counter[str] = Counter()
    path_evidence: dict[str, list[tuple[_FileOwner, _FileOwner, ContentRelation]]] = {}
    for relative_path, path_owners in sorted(owners.items()):
        for index, first in enumerate(path_owners):
            for second in path_owners[index + 1 :]:
                if first.entry.key == second.entry.key:
                    continue
                pair_comparisons += 1
                if pair_comparisons > _MAX_PAIR_COMPARISONS:
                    truncated = True
                    break
                if first.size != second.size:
                    relation: ContentRelation = "different"
                elif first.size > _MAX_HASH_BYTES:
                    relation = "unverified"
                else:
                    new_paths = {
                        _path_key(path): size
                        for path, size in (
                            (first.path, first.size),
                            (second.path, second.size),
                        )
                        if _path_key(path) not in digest_cache
                    }
                    required_bytes = sum(new_paths.values())
                    if hash_bytes + required_bytes > _MAX_TOTAL_HASH_BYTES:
                        relation = "unverified"
                    else:
                        hash_bytes += required_bytes
                        first_hash = _sha256(first.path, digest_cache, first.size)
                        second_hash = _sha256(second.path, digest_cache, second.size)
                        if (
                            first_hash is not None
                            and second_hash is not None
                            and first_hash == second_hash
                        ):
                            continue
                        relation = (
                            "different"
                            if first_hash is not None and second_hash is not None
                            else "unverified"
                        )
                overlap_count += 1
                path_counts[relative_path] += 1
                if relation == "different":
                    different_count += 1
                    path_different_counts[relative_path] += 1
                else:
                    unverified_count += 1
                    path_unverified_counts[relative_path] += 1
                evidence = path_evidence.setdefault(relative_path, [])
                if not any(item[2] == relation for item in evidence):
                    evidence.append((first, second, relation))
                detail = FileOverlap(
                    relative_path,
                    first.entry.mod_id or "",
                    second.entry.mod_id or "",
                    first.path,
                    second.path,
                    first.candidate.path,
                    second.candidate.path,
                    relation,
                )
                if len(overlaps) < _MAX_STORED_DETAILS:
                    overlaps.append(detail)
            if truncated:
                break
        if truncated:
            break

    ranked_paths = sorted(path_counts, key=lambda path: (-path_counts[path], path))
    selected_paths = ranked_paths[:_MAX_STORED_PATH_GROUPS]
    path_groups = tuple(
        FileOverlapPathGroup(
            relative_path=relative_path,
            comparison_count=path_counts[relative_path],
            different_count=path_different_counts[relative_path],
            unverified_count=path_unverified_counts[relative_path],
            mod_ids=tuple(
                sorted(
                    {
                        owner.entry.mod_id
                        for owner in owners[relative_path]
                        if owner.entry.mod_id
                    },
                    key=str.casefold,
                )
            ),
            examples=tuple(
                FileOverlap(
                    relative_path,
                    first.entry.mod_id or "",
                    second.entry.mod_id or "",
                    first.path,
                    second.path,
                    first.candidate.path,
                    second.candidate.path,
                    relation,
                )
                for first, second, relation in path_evidence[relative_path]
            ),
        )
        for relative_path in selected_paths
    )

    return FileOverlapReport(
        candidate_count=candidate_count,
        entry_count=len(entries),
        target_build=target_build,
        staged_only=staged_only,
        files_scanned=file_count,
        overlap_count=overlap_count,
        different_count=different_count,
        unverified_count=unverified_count,
        unique_path_count=len(path_counts),
        path_groups=path_groups,
        path_groups_limited=len(path_counts) > len(path_groups),
        overlaps=tuple(overlaps),
        skipped_files=skipped,
        truncated=truncated,
        details_limited=overlap_count > len(overlaps),
    )


def format_file_overlap_report(report: FileOverlapReport) -> str:
    target = {
        "all": "all metadata candidates",
        "41": "Build 41 root metadata",
        "42": "Build 42 preview metadata",
    }.get(report.target_build, f"Build {report.target_build}")
    mod_scope = "staged active mods" if report.staged_only else "all discovered mods"
    summary = (
        f"Scanned {report.files_scanned} files across {report.candidate_count} metadata candidates; "
        f"found {report.overlap_count} potential file overlaps across "
        f"{report.unique_path_count} shared paths "
        f"({report.different_count} comparisons found different content, "
        f"{report.unverified_count} comparisons unavailable)."
    )
    lines = [
        summary,
        f"Scope: {mod_scope}; {target}; {report.entry_count} mod entries.",
    ]
    if report.skipped_files:
        lines.append(
            f"Skipped {report.skipped_files} files that could not be read for indexing."
        )
    if report.truncated:
        lines.append("Analysis reached a safety limit; results may be incomplete.")
    if report.path_groups_limited:
        lines.append(
            f"Showing the {len(report.path_groups)} shared paths with the most comparisons."
        )
    if not report.overlap_count:
        lines.append(
            "No differing or unverified overlaps were found in the scanned candidate folders."
        )
    elif report.path_groups:
        lines.append("Most repeated shared paths:")
        for group in report.path_groups[:10]:
            mod_ids = ", ".join(group.mod_ids[:4])
            if len(group.mod_ids) > 4:
                mod_ids += f", +{len(group.mod_ids) - 4} more"
            lines.append(
                f"  {group.relative_path}: {group.comparison_count} pair(s) "
                f"({group.different_count} different, {group.unverified_count} unverified)"
                + (f" · {mod_ids}" if mod_ids else "")
            )
    lines.append(
        "These are path/content overlaps, not a guarantee of an in-game conflict; candidate selection and runtime precedence depend on the game build and active load order."
    )
    return "\n".join(lines)
