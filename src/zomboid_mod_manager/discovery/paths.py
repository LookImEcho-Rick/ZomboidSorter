"""Steam, game, and user mod path detection."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

from zomboid_mod_manager.domain import DetectedPaths

PZ_APP_ID = "108600"
_VDF_PATH = re.compile(r'"path"\s+"((?:\\.|[^"])*)"')
_INSTALL_DIR = re.compile(r'"installdir"\s+"([^"]+)"', re.IGNORECASE)


def _registry_steam_root() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
        return Path(os.path.expandvars(value.replace("/", os.sep)))
    except OSError, ImportError:
        return None


def _candidate_steam_roots(home: Path) -> list[Path]:
    candidates = [
        _registry_steam_root(),
        Path(os.environ["STEAM_PATH"]) if os.environ.get("STEAM_PATH") else None,
        Path("C:/Program Files (x86)/Steam"),
        Path("C:/Program Files/Steam"),
        home / ".steam" / "steam",
    ]
    return [candidate for candidate in candidates if candidate is not None]


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def parse_libraryfolders_vdf(path: Path) -> tuple[Path, ...]:
    """Read library roots from Steam's libraryfolders.vdf without a VDF dependency."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()

    libraries: list[Path] = []
    seen: set[str] = set()
    for match in _VDF_PATH.finditer(content):
        value = match.group(1).replace('\\"', '"').replace("\\\\", "\\")
        library = Path(value)
        key = _path_key(library)
        if key not in seen:
            seen.add(key)
            libraries.append(library)
    return tuple(libraries)


def find_steamapps_libraries(steam_root: Path) -> tuple[Path, ...]:
    base = steam_root / "steamapps"
    libraries: list[Path] = []
    seen: set[str] = set()

    if base.is_dir():
        libraries.append(base)
        seen.add(_path_key(base))

    for library_root in parse_libraryfolders_vdf(base / "libraryfolders.vdf"):
        steamapps = library_root / "steamapps"
        key = _path_key(steamapps)
        if steamapps.is_dir() and key not in seen:
            seen.add(key)
            libraries.append(steamapps)
    return tuple(libraries)


def _is_steam_root(path: Path) -> bool:
    return (path / "steamapps").is_dir() or (
        path / "config" / "libraryfolders.vdf"
    ).is_file()


def _game_installation(steamapps: Path) -> Path | None:
    manifest = steamapps / f"appmanifest_{PZ_APP_ID}.acf"
    install_dir = "ProjectZomboid"
    try:
        match = _INSTALL_DIR.search(
            manifest.read_text(encoding="utf-8", errors="replace")
        )
        if match:
            install_dir = match.group(1)
    except OSError:
        pass

    candidates = (
        steamapps / "common" / install_dir,
        steamapps / "common" / "ProjectZomboid",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def detect_paths(
    *, home: Path | None = None, steam_roots: Iterable[Path] | None = None
) -> DetectedPaths:
    """Detect common Windows Steam locations and the current user's local mod root.

    `steam_roots` is injectable for tests and for callers with a known Steam path.
    The returned paths are hints; callers may always use explicit paths instead.
    """
    user_home = home or Path.home()
    roots_to_check = (
        list(steam_roots)
        if steam_roots is not None
        else _candidate_steam_roots(user_home)
    )
    roots: list[Path] = []
    seen_roots: set[str] = set()
    for candidate in roots_to_check:
        try:
            resolved = candidate.expanduser()
            if not _is_steam_root(resolved):
                continue
            key = _path_key(resolved)
            if key not in seen_roots:
                seen_roots.add(key)
                roots.append(resolved)
        except OSError:
            continue

    libraries: list[Path] = []
    game_paths: list[Path] = []
    workshop_paths: list[Path] = []
    seen_libraries: set[str] = set()
    seen_games: set[str] = set()
    seen_workshops: set[str] = set()

    for root in roots:
        for steamapps in find_steamapps_libraries(root):
            library_key = _path_key(steamapps)
            if library_key in seen_libraries:
                continue
            seen_libraries.add(library_key)
            libraries.append(steamapps)

            game_path = _game_installation(steamapps)
            if game_path is not None and _path_key(game_path) not in seen_games:
                seen_games.add(_path_key(game_path))
                game_paths.append(game_path)

            workshop_path = steamapps / "workshop" / "content" / PZ_APP_ID
            if (
                workshop_path.is_dir()
                and _path_key(workshop_path) not in seen_workshops
            ):
                seen_workshops.add(_path_key(workshop_path))
                workshop_paths.append(workshop_path)

    diagnostics: list[str] = []
    if not roots:
        diagnostics.append(
            "Steam was not detected; choose Workshop folders manually if needed."
        )
    if not game_paths:
        diagnostics.append(
            "Project Zomboid was not detected in the discovered Steam libraries."
        )

    return DetectedPaths(
        steam_roots=tuple(roots),
        steamapps_libraries=tuple(libraries),
        game_installations=tuple(game_paths),
        workshop_roots=tuple(workshop_paths),
        local_mod_root=user_home / "Zomboid" / "mods",
        diagnostics=tuple(diagnostics),
    )
