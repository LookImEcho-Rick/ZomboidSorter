"""Application workflow for the supported global active-mod configuration."""

from __future__ import annotations

from pathlib import Path

from .gameio.active_mods import (
    ActiveModConfigError,
    ActiveModSnapshot,
    ConcurrentConfigChangeError,
    read_active_mods,
    write_active_mods,
)


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
