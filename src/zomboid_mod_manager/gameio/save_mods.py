"""Read-only discovery of explicit per-save Project Zomboid mod lists."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .active_mods import ActiveModConfig, ActiveModConfigError, parse_active_mod_config

_MAX_SAVE_MODS_BYTES = 1024 * 1024
_LINK_SKIP_MESSAGE = "Skipped a symbolic link or junction in the saves folder."


class SaveModDiscoveryError(ValueError):
    """The selected saves folder could not be read safely."""


@dataclass(frozen=True)
class SaveModList:
    game_mode: str
    save_directory: Path
    mods_path: Path
    config: ActiveModConfig

    @property
    def name(self) -> str:
        return self.save_directory.name

    @property
    def display_name(self) -> str:
        return f"{self.game_mode} · {self.name}"


@dataclass(frozen=True)
class SaveModDiscovery:
    saves_root: Path
    saves_with_explicit_lists: tuple[SaveModList, ...]
    inherited_global_count: int
    diagnostics: tuple[str, ...]


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _is_directory_without_following_links(path: Path) -> bool:
    return stat.S_ISDIR(path.stat(follow_symlinks=False).st_mode)


def _read_save_config(path: Path) -> ActiveModConfig:
    try:
        if _is_link_or_junction(path):
            raise SaveModDiscoveryError("mods.txt is a symbolic link or junction.")
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise SaveModDiscoveryError("mods.txt is not a regular file.")
        if info.st_size > _MAX_SAVE_MODS_BYTES:
            raise SaveModDiscoveryError("mods.txt exceeds the 1 MiB size limit.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened_info = os.fstat(source.fileno())
            if not stat.S_ISREG(opened_info.st_mode):
                raise SaveModDiscoveryError("mods.txt is not a regular file.")
            if opened_info.st_size > _MAX_SAVE_MODS_BYTES:
                raise SaveModDiscoveryError("mods.txt exceeds the 1 MiB size limit.")
            data = source.read(_MAX_SAVE_MODS_BYTES + 1)
        if len(data) > _MAX_SAVE_MODS_BYTES:
            raise SaveModDiscoveryError("mods.txt grew beyond the 1 MiB size limit.")
    except SaveModDiscoveryError:
        raise
    except OSError as exc:
        raise SaveModDiscoveryError(f"Could not read mods.txt: {exc}") from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SaveModDiscoveryError("mods.txt is not valid UTF-8.") from exc
    try:
        return parse_active_mod_config(text)
    except ActiveModConfigError as exc:
        raise SaveModDiscoveryError(str(exc)) from exc


def discover_save_mod_lists(saves_root: Path) -> SaveModDiscovery:
    """Read only immediate ``<mode>/<save>/mods.txt`` files under Saves.

    Saves without an explicit ``mods.txt`` inherit Project Zomboid's global
    default list and are counted separately; that list is never substituted
    into the save result. No other save files are opened or changed.
    """
    root = saves_root.expanduser()
    if _is_link_or_junction(root):
        raise SaveModDiscoveryError(
            "Choose the real Saves folder; linked folders are not followed."
        )
    try:
        if not _is_directory_without_following_links(root):
            raise SaveModDiscoveryError("The selected Saves path is not a folder.")
    except FileNotFoundError as exc:
        raise SaveModDiscoveryError(
            "The selected Saves folder does not exist."
        ) from exc
    except OSError as exc:
        raise SaveModDiscoveryError(
            f"Could not inspect the Saves folder: {exc}"
        ) from exc

    profiles: list[SaveModList] = []
    diagnostics: list[str] = []
    inherited_global_count = 0
    try:
        mode_directories = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        raise SaveModDiscoveryError(f"Could not list the Saves folder: {exc}") from exc

    for mode_directory in mode_directories:
        if _is_link_or_junction(mode_directory):
            diagnostics.append(f"{_LINK_SKIP_MESSAGE} {mode_directory}")
            continue
        try:
            if not _is_directory_without_following_links(mode_directory):
                continue
            save_directories = sorted(
                mode_directory.iterdir(), key=lambda path: path.name.casefold()
            )
        except OSError as exc:
            diagnostics.append(f"Could not list {mode_directory}: {exc}")
            continue

        for save_directory in save_directories:
            if _is_link_or_junction(save_directory):
                diagnostics.append(f"{_LINK_SKIP_MESSAGE} {save_directory}")
                continue
            try:
                if not _is_directory_without_following_links(save_directory):
                    continue
            except OSError as exc:
                diagnostics.append(f"Could not inspect {save_directory}: {exc}")
                continue
            mods_path = save_directory / "mods.txt"
            if _is_link_or_junction(mods_path):
                diagnostics.append(f"{_LINK_SKIP_MESSAGE} {mods_path}")
                continue
            try:
                mods_path.stat(follow_symlinks=False)
            except FileNotFoundError:
                inherited_global_count += 1
                continue
            except OSError as exc:
                diagnostics.append(f"Could not inspect {mods_path}: {exc}")
                continue
            try:
                config = _read_save_config(mods_path)
            except SaveModDiscoveryError as exc:
                diagnostics.append(f"{mods_path}: {exc}")
                continue
            profiles.append(
                SaveModList(
                    game_mode=mode_directory.name,
                    save_directory=save_directory,
                    mods_path=mods_path,
                    config=config,
                )
            )

    profiles.sort(key=lambda item: (item.game_mode.casefold(), item.name.casefold()))
    return SaveModDiscovery(
        saves_root=root,
        saves_with_explicit_lists=tuple(profiles),
        inherited_global_count=inherited_global_count,
        diagnostics=tuple(diagnostics),
    )
