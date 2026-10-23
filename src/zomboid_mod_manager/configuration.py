"""Application workflow for the supported global active-mod configuration."""

from __future__ import annotations

from pathlib import Path

from .gameio.active_mods import (
    ActiveModConfig,
    ActiveModConfigError,
    ActiveModSnapshot,
    ConcurrentConfigChangeError,
    read_active_mods,
    write_active_configuration,
    write_active_mods,
)

_MAX_ACTIVE_BACKUP_BYTES = 1024 * 1024


class SelectedConfigurationPathMismatch(ValueError):
    """The selected path no longer matches the configuration that was loaded."""


def load_active_configuration(path_text: str) -> ActiveModSnapshot:
    """Load a supported active-mod configuration from the selected path."""
    if not path_text.strip():
        raise ActiveModConfigError("Choose a global default.txt path first.")
    return read_active_mods(Path(path_text).expanduser())


def selected_path_matches_configuration(
    snapshot: ActiveModSnapshot, path_text: str
) -> bool:
    """Return whether the selected path still names the loaded configuration."""
    try:
        selected = Path(path_text).expanduser().resolve(strict=False)
        loaded = snapshot.path.expanduser().resolve(strict=False)
    except OSError:
        return False
    return selected == loaded


def is_global_default_mod_list(path: Path) -> bool:
    """Check whether a path is the supported global default list target."""
    if path.is_symlink():
        return False
    try:
        parts = tuple(part.casefold() for part in path.resolve(strict=False).parts)
    except OSError:
        return False
    return (
        len(parts) >= 3
        and parts[-3:] == ("zomboid", "mods", "default.txt")
        and "saves" not in parts
    )


def read_unchanged_active_configuration(
    snapshot: ActiveModSnapshot,
) -> ActiveModSnapshot:
    """Read a configuration again and reject it if it changed since loading."""
    latest = read_active_mods(snapshot.path)
    if latest.fingerprint != snapshot.fingerprint:
        raise ConcurrentConfigChangeError(
            "The global mod list changed since it was loaded; reload it before continuing."
        )
    return latest


def apply_active_configuration(
    snapshot: ActiveModSnapshot,
    selected_path_text: str,
    mod_ids: tuple[str, ...],
) -> Path:
    """Apply staged IDs after rechecking that the UI still targets this file."""
    if not selected_path_matches_configuration(snapshot, selected_path_text):
        raise SelectedConfigurationPathMismatch
    return write_active_mods(snapshot, mod_ids)


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def list_active_configuration_backups(
    snapshot: ActiveModSnapshot,
) -> tuple[Path, ...]:
    """List regular backup files beside the selected global mod list."""
    if not is_global_default_mod_list(snapshot.path):
        raise ActiveModConfigError(
            "Backups are available only for the global Zomboid/mods/default.txt file."
        )
    if not snapshot.path.parent.is_dir():
        return ()
    prefix = f"{snapshot.path.name}.bak-"
    parent = snapshot.path.parent.resolve(strict=False)
    backups = []
    for candidate in snapshot.path.parent.glob(f"{snapshot.path.name}.bak-*"):
        if not candidate.name.startswith(prefix) or _is_link_or_junction(candidate):
            continue
        try:
            if candidate.is_file() and candidate.resolve(strict=False).parent == parent:
                backups.append(candidate)
        except OSError:
            continue
    return tuple(sorted(backups, key=lambda path: path.name, reverse=True))


def read_active_configuration_backup(
    snapshot: ActiveModSnapshot, backup_path: Path
) -> ActiveModSnapshot:
    """Read a sibling global-list backup without modifying either file."""
    if not is_global_default_mod_list(snapshot.path):
        raise ActiveModConfigError(
            "Backups are available only for the global Zomboid/mods/default.txt file."
        )
    prefix = f"{snapshot.path.name}.bak-"
    if (
        not backup_path.name.startswith(prefix)
        or _is_link_or_junction(backup_path)
        or backup_path.parent.resolve(strict=False)
        != snapshot.path.parent.resolve(strict=False)
    ):
        raise ActiveModConfigError(
            "Choose a regular timestamped backup beside the selected global mod list."
        )
    try:
        if not backup_path.is_file():
            raise ActiveModConfigError("The selected backup is not a regular file.")
        if backup_path.stat(follow_symlinks=False).st_size > _MAX_ACTIVE_BACKUP_BYTES:
            raise ActiveModConfigError("The selected backup exceeds the 1 MiB limit.")
    except OSError as exc:
        raise ActiveModConfigError(
            f"Could not read the selected backup: {exc}"
        ) from exc
    return read_active_mods(backup_path)


def restore_active_configuration(
    snapshot: ActiveModSnapshot, backup_path: Path
) -> Path:
    """Restore a selected sibling backup through the guarded atomic writer."""
    backup = read_active_configuration_backup(snapshot, backup_path)
    config: ActiveModConfig = backup.config
    return write_active_configuration(snapshot, config)
