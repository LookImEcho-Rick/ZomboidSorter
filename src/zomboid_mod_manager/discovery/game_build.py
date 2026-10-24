"""Read-only detection of the installed Project Zomboid build family."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_BUILD_41_BRANCHES = {"legacy41", "legacy-41", "build41", "build-41"}
_BUILD_42_MARKER = b"VERSION_BUILD_42"
_CORE_CLASS_PATH = Path("zombie") / "core" / "Core.class"
_MAX_CLASS_BYTES = 2 * 1024 * 1024
_VERSION_LINE = re.compile(r"^(4[12](?:\.\d+){1,2})\b")
_MAX_VERSION_FILE_BYTES = 256


@dataclass(frozen=True)
class GameBuildDetection:
    """A build family and the local installation evidence used to infer it."""

    major_build: str | None
    exact_version: str | None
    source: str | None
    note: str


def format_game_build_detection(detection: GameBuildDetection) -> str:
    """Format detection evidence for a concise UI status line."""
    if detection.major_build is None:
        return detection.note
    version = f"{detection.exact_version}" if detection.exact_version else "family only"
    source = detection.source or "local game files"
    return f"Detected Build {detection.major_build} ({version}) from {source}. {detection.note}"


def _installed_core_class(game_path: Path) -> bytes | None:
    loose_class = game_path / _CORE_CLASS_PATH
    try:
        if loose_class.is_file() and not loose_class.is_symlink():
            if loose_class.stat().st_size <= _MAX_CLASS_BYTES:
                return loose_class.read_bytes()
            return None
    except OSError:
        return None

    for jar_name in ("projectzomboid.jar", "zombie.jar"):
        jar_path = game_path / jar_name
        try:
            if not jar_path.is_file() or jar_path.is_symlink():
                continue
            with zipfile.ZipFile(jar_path) as archive:
                info = archive.getinfo(_CORE_CLASS_PATH.as_posix())
                if info.file_size > _MAX_CLASS_BYTES:
                    continue
                with archive.open(info) as core_class:
                    data = core_class.read(_MAX_CLASS_BYTES + 1)
                if len(data) <= _MAX_CLASS_BYTES:
                    return data
        except OSError, KeyError, zipfile.BadZipFile:
            continue
    return None


def _steam_manifest(game_path: Path) -> tuple[str | None, Path | None, datetime | None]:
    for parent in game_path.parents:
        manifest = parent / "appmanifest_108600.acf"
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matches = re.findall(
            r'"BetaKey"\s+"((?:\\.|[^"])*)"', text, flags=re.IGNORECASE
        )
        branch = next((value.strip() for value in matches if value.strip()), None)
        updated_matches = re.findall(
            r'"LastUpdated"\s+"(\d+)"', text, flags=re.IGNORECASE
        )
        updated_at = None
        if updated_matches:
            try:
                updated_at = datetime.fromtimestamp(int(updated_matches[0]), UTC)
            except OSError, OverflowError, ValueError:
                updated_at = None
        return branch, manifest, updated_at
    return None, None, None


def _fresh_exact_version(updated_at: datetime | None) -> str | None:
    """Read the one-line game version only when Steam updated its install first.

    The user's Zomboid/version.txt can describe a different or older install.
    Requiring it to be at least as new as the selected Steam manifest avoids
    silently carrying a previous branch's exact version into metadata selection.
    """
    if updated_at is None:
        return None
    version_path = Path.home() / "Zomboid" / "version.txt"
    try:
        if version_path.is_symlink():
            return None
        info = version_path.stat()
        if info.st_size > _MAX_VERSION_FILE_BYTES:
            return None
        modified = datetime.fromtimestamp(info.st_mtime, UTC)
        if modified < updated_at:
            return None
        text = version_path.read_text(encoding="utf-8", errors="strict")
    except OSError, UnicodeDecodeError, ValueError:
        return None
    match = _VERSION_LINE.match(text.strip())
    if match is None:
        return None
    return match.group(1)


def detect_game_build(game_path: Path | str) -> GameBuildDetection:
    """Detect Build 41 from Steam's legacy branch or Build 42 from game code.

    Steam's manifest exposes the selected beta branch but not the exact game
    patch. Build 42's installed Core class carries a stable family marker; that
    also identifies the family without inventing an exact patch number.
    """
    root = Path(game_path).expanduser()
    branch, manifest, updated_at = _steam_manifest(root)
    exact_version = _fresh_exact_version(updated_at)
    if branch and branch.casefold() in _BUILD_41_BRANCHES:
        if exact_version is not None and not exact_version.startswith("41."):
            exact_version = None
        return GameBuildDetection(
            major_build="41",
            exact_version=exact_version,
            source=(
                f"{manifest} and Zomboid/version.txt"
                if exact_version
                else f"Steam branch '{branch}' in {manifest}"
            ),
            note=(
                "The Steam manifest identifies the legacy Build 41 branch."
                if exact_version
                else "The Steam manifest identifies the legacy Build 41 branch, but "
                "no current exact version is available."
            ),
        )

    core_class = _installed_core_class(root)
    if core_class is not None and _BUILD_42_MARKER in core_class:
        if exact_version is not None and not exact_version.startswith("42."):
            exact_version = None
        return GameBuildDetection(
            major_build="42",
            exact_version=exact_version,
            source=(
                "Build 42 marker and Zomboid/version.txt"
                if exact_version
                else f"Build 42 marker in {root / _CORE_CLASS_PATH}"
            ),
            note=(
                "The installed files identify Build 42."
                if exact_version
                else "The installed files identify Build 42, but do not expose the "
                "exact patch version. Enter the version shown on the game's "
                "main menu to select version-specific metadata."
            ),
        )

    if branch:
        return GameBuildDetection(
            major_build=None,
            exact_version=None,
            source=f"Steam branch '{branch}' in {manifest}",
            note=(
                "This Steam branch does not identify a supported build family. "
                "Choose the metadata target manually."
            ),
        )
    return GameBuildDetection(
        major_build=None,
        exact_version=None,
        source=None,
        note="No supported Project Zomboid build marker was found.",
    )
