"""Opt-in, read-only candidate file-overlap analysis.

An overlap means two distinct mod entries ship the same relative path in their
metadata candidate trees. It does not decide which candidate is active or
which file wins at runtime.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from zomboid_mod_manager.domain import MetadataCandidate, ModEntry, ScanResult

ContentRelation = Literal["different", "unverified"]
_MAX_FILES = 100_000
_MAX_HASH_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_HASH_BYTES = 512 * 1024 * 1024
_MAX_PAIR_COMPARISONS = 100_000
_MAX_STORED_DETAILS = 100


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
class FileOverlapReport:
    candidate_count: int
    files_scanned: int
    overlap_count: int
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


def analyze_file_overlaps(scan_result: ScanResult) -> FileOverlapReport:
    """Find paths shared by distinct mod entries without changing mod files.

    Candidate folders are treated independently. Overlaps are reported only
    when contents differ or are too large/unreadable to compare; identical
    copies are omitted. The work is bounded and callers should run it off the
    UI thread for real libraries.
    """
    entries = scan_result.entries
    candidate_count = sum(len(entry.candidates) for entry in entries)
    roots_by_entry = {
        entry.key: {_path_key(candidate.path.parent) for candidate in entry.candidates}
        for entry in entries
    }
    owners: dict[str, list[_FileOwner]] = defaultdict(list)
    file_count = 0
    skipped = 0
    truncated = False

    for entry in entries:
        if not entry.mod_id:
            continue
        for candidate in entry.candidates:
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
    pair_comparisons = 0
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
                if len(overlaps) < _MAX_STORED_DETAILS:
                    overlaps.append(
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
                    )
            if truncated:
                break
        if truncated:
            break

    return FileOverlapReport(
        candidate_count,
        file_count,
        overlap_count,
        tuple(overlaps),
        skipped,
        truncated,
        overlap_count > len(overlaps),
    )


def format_file_overlap_report(report: FileOverlapReport) -> str:
    summary = (
        f"Scanned {report.files_scanned} files across {report.candidate_count} metadata candidates; "
        f"found {report.overlap_count} potential file overlaps with differing or unverified contents."
    )
    lines = [summary]
    if report.skipped_files:
        lines.append(
            f"Skipped {report.skipped_files} files that could not be read for indexing."
        )
    if report.truncated:
        lines.append("Analysis reached a safety limit; results may be incomplete.")
    if report.details_limited:
        lines.append(f"Showing the first {len(report.overlaps)} overlap details.")
    if not report.overlap_count:
        lines.append(
            "No differing overlaps were found in the scanned candidate folders."
        )
    for overlap in report.overlaps:
        confidence = (
            "content differs"
            if overlap.content_relation == "different"
            else "content comparison unavailable"
        )
        lines.extend(
            (
                f"POTENTIAL [{confidence}] {overlap.relative_path}",
                f"  {overlap.first_mod_id}: {overlap.first_file} ({overlap.first_candidate})",
                f"  {overlap.second_mod_id}: {overlap.second_file} ({overlap.second_candidate})",
            )
        )
    lines.append(
        "These are path/content overlaps, not a guarantee of an in-game conflict; candidate selection and runtime precedence depend on the game build and active load order."
    )
    return "\n".join(lines)
