"""Small records shared by discovery and the desktop view."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SourceType = Literal["local", "workshop"]
DiagnosticLevel = Literal["warning", "error"]


@dataclass(frozen=True)
class Diagnostic:
    message: str
    path: Path | None = None
    level: DiagnosticLevel = "warning"


@dataclass(frozen=True)
class MetadataCandidate:
    """One mod.info file; candidates are retained without choosing a game build."""

    path: Path
    layout: str
    version_folder: str | None
    fields: dict[str, str]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModEntry:
    """One logical Mod ID at one installed entry path."""

    key: str
    mod_id: str | None
    name: str
    author: str
    description: str
    version: str
    requirements_raw: str
    source: SourceType
    installation_path: Path
    entry_path: Path
    workshop_id: str | None
    candidates: tuple[MetadataCandidate, ...]
    diagnostics: tuple[str, ...] = ()
    directory_candidates: tuple[MetadataCandidate, ...] = ()

    @property
    def layout_summary(self) -> str:
        labels = [candidate.layout for candidate in self.candidates]
        if len(labels) == 1:
            return labels[0]
        return f"{len(labels)} candidates: " + ", ".join(labels)


@dataclass(frozen=True)
class WorkshopItem:
    workshop_id: str
    path: Path
    entries: tuple[ModEntry, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    local_entries: tuple[ModEntry, ...]
    workshop_items: tuple[WorkshopItem, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def entries(self) -> tuple[ModEntry, ...]:
        workshop_entries = tuple(
            entry for item in self.workshop_items for entry in item.entries
        )
        return self.local_entries + workshop_entries

    @property
    def metadata_candidate_count(self) -> int:
        return sum(len(entry.candidates) for entry in self.entries)


@dataclass(frozen=True)
class DetectedPaths:
    steam_roots: tuple[Path, ...]
    steamapps_libraries: tuple[Path, ...]
    game_installations: tuple[Path, ...]
    workshop_roots: tuple[Path, ...]
    local_mod_root: Path
    diagnostics: tuple[str, ...] = ()
