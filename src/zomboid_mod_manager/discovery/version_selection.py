"""Choose metadata candidates for a user-selected Project Zomboid build."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from zomboid_mod_manager.domain import MetadataCandidate, ModEntry

_NUMERIC_VERSION = re.compile(r"^\d+(?:\.\d+)*$")

SelectionStatus = Literal[
    "all",
    "build-41",
    "build-42-preview",
    "selected-version",
    "selected-common",
    "missing",
    "invalid",
    "ambiguous",
    "superseded",
]


@dataclass(frozen=True)
class CandidateSelection:
    candidates: tuple[MetadataCandidate, ...]
    status: SelectionStatus
    message: str


def _version_key(value: str) -> tuple[int, ...] | None:
    if not _NUMERIC_VERSION.fullmatch(value):
        return None
    parts = [int(part) for part in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_numeric_game_build(value: str) -> bool:
    """Return whether a game build is written as dot-separated numbers."""
    return _version_key(value) is not None


def declared_version_range_diagnostics(
    candidate: MetadataCandidate, target_build: str
) -> tuple[str, ...]:
    """Report declared min/max game-version bounds that exclude an exact target."""
    target_version = _version_key(target_build)
    if target_version is None or "." not in target_build:
        return ()

    def compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
        width = max(len(left), len(right))
        left_padded = left + (0,) * (width - len(left))
        right_padded = right + (0,) * (width - len(right))
        return (left_padded > right_padded) - (left_padded < right_padded)

    diagnostics: list[str] = []
    minimum_raw = candidate.fields.get("versionmin", "").strip()
    minimum = _version_key(minimum_raw)
    if minimum is not None and compare(target_version, minimum) < 0:
        diagnostics.append(
            f"Declared minimum game version is {minimum_raw}; target is {target_build}."
        )

    maximum_raw = candidate.fields.get("versionmax", "").strip()
    maximum = _version_key(maximum_raw)
    if maximum is not None and compare(target_version, maximum) > 0:
        diagnostics.append(
            f"Declared maximum game version is {maximum_raw}; target is {target_build}."
        )
    return tuple(diagnostics)


def _missing_build_42_message(
    candidates: tuple[MetadataCandidate, ...],
    directory_candidates: tuple[MetadataCandidate, ...],
) -> str:
    universe = directory_candidates or candidates
    has_root_metadata = any(
        candidate.layout == "root (Build 41 style)" for candidate in universe
    )
    has_build_42_metadata = any(
        candidate.layout == "common (shared)" or candidate.version_folder
        for candidate in universe
    )
    if has_root_metadata and not has_build_42_metadata:
        return (
            "Only root (Build 41 style) metadata was found. Build 42 ignores "
            "root-level mod files; this mod needs common metadata or a compatible "
            "42+ version folder."
        )
    return "No Build 42 shared or versioned metadata candidate was found."


def resolve_metadata_candidates(
    candidates: tuple[MetadataCandidate, ...],
    target_build: str,
    *,
    directory_candidates: tuple[MetadataCandidate, ...] = (),
) -> CandidateSelection:
    """Resolve one effective metadata file when an exact game build is known.

    "all", "41", and "42" keep their preview meanings. An exact dotted build
    selects the highest numeric version folder at or below that build; common
    metadata is used when no compatible versioned metadata file exists.
    """
    if target_build == "all":
        return CandidateSelection(candidates, "all", "Showing all metadata candidates.")

    if target_build == "41":
        root_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.layout == "root (Build 41 style)"
        )
        if root_candidates:
            message = "Using root metadata for Build 41."
        elif any(
            candidate.layout == "common (shared)" or candidate.version_folder
            for candidate in candidates
        ):
            message = (
                "Only Build 42 shared or versioned metadata is available for this "
                "Mod ID; Build 41 requires root-level metadata."
            )
        else:
            message = "No Build 41 root metadata candidate was found."
        return CandidateSelection(root_candidates, "build-41", message)

    if target_build == "42":
        build_42_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.layout == "common (shared)" or candidate.version_folder
        )
        if not build_42_candidates:
            return CandidateSelection(
                (),
                "missing",
                _missing_build_42_message(candidates, directory_candidates),
            )
        return CandidateSelection(
            build_42_candidates,
            "build-42-preview",
            "Enter the exact Build 42 version to select one compatible version folder; all shared and versioned candidates are shown for now.",
        )

    universe = directory_candidates or candidates
    target_version = _version_key(target_build)
    if target_version is None:
        return CandidateSelection(
            (),
            "invalid",
            "Enter a numeric game build such as 42.21.0.",
        )

    if target_version[0] <= 41:
        root_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.layout == "root (Build 41 style)"
        )
        message = (
            f"Using root metadata for game build {target_build}."
            if root_candidates
            else f"No root metadata candidate was found for game build {target_build}."
        )
        return CandidateSelection(root_candidates, "build-41", message)

    versioned: list[tuple[tuple[int, ...], MetadataCandidate]] = []
    for candidate in universe:
        if not candidate.version_folder:
            continue
        candidate_version = _version_key(candidate.version_folder)
        if candidate_version is not None and candidate_version <= target_version:
            versioned.append((candidate_version, candidate))

    if versioned:
        latest_version = max(version for version, _candidate in versioned)
        latest = tuple(
            candidate for version, candidate in versioned if version == latest_version
        )
        if len(latest) > 1:
            folders = ", ".join(
                sorted(candidate.version_folder or "" for candidate in latest)
            )
            return CandidateSelection(
                (),
                "ambiguous",
                f"More than one version folder represents the newest compatible version for game build {target_build}: {folders}.",
            )
        selected = latest[0]
        if selected not in candidates:
            selected_id = selected.fields.get("id", "").strip() or "(missing ID)"
            return CandidateSelection(
                (),
                "superseded",
                f"Version folder {selected.version_folder} is the newest compatible one for game build {target_build}, but its Mod ID is '{selected_id}', not this entry's ID.",
            )
        return CandidateSelection(
            (selected,),
            "selected-version",
            f"Using version folder {selected.version_folder} for game build {target_build}; it is the newest version at or below that build.",
        )

    common_candidates = tuple(
        candidate for candidate in candidates if candidate.layout == "common (shared)"
    )
    if len(common_candidates) == 1:
        return CandidateSelection(
            common_candidates,
            "selected-common",
            f"No compatible versioned metadata file was found for game build {target_build}; using shared common metadata.",
        )
    if len(common_candidates) > 1:
        return CandidateSelection(
            (),
            "ambiguous",
            f"Multiple shared common metadata files were found for game build {target_build}.",
        )

    return CandidateSelection(
        (),
        "missing",
        (
            _missing_build_42_message(candidates, universe)
            if target_version[0] >= 42
            else f"No compatible metadata candidate was found for game build {target_build}."
        ),
    )


def resolve_entry_metadata(entry: ModEntry, target_build: str) -> CandidateSelection:
    """Resolve an entry against every metadata file in its physical mod folder."""
    return resolve_metadata_candidates(
        entry.candidates,
        target_build,
        directory_candidates=entry.directory_candidates,
    )
