"""Discovery and guarded writes for per-save Project Zomboid mod lists."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .active_mods import (
    ActiveModConfig,
    ActiveModConfigError,
    parse_active_mod_config,
    render_active_mod_config,
)

_MAX_SAVE_MODS_BYTES = 1024 * 1024
_LINK_SKIP_MESSAGE = "Skipped a symbolic link or junction in the saves folder."


class SaveModDiscoveryError(ValueError):
    """A save list or selected save target is malformed or unsafe."""


class ConcurrentSaveModChangeError(RuntimeError):
    """A save mod list changed after it was read and before it was applied."""


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


@dataclass(frozen=True)
class SaveModTargetSnapshot:
    """One validated save target and its exact on-disk state."""

    saves_root: Path
    save_directory: Path
    mods_path: Path
    config: ActiveModConfig
    raw_bytes: bytes | None
    fingerprint: str | None

    @property
    def inherits_global_list(self) -> bool:
        return self.raw_bytes is None


@dataclass(frozen=True)
class SaveModBackup:
    """One validated backup of a selected save's explicit mod list."""

    path: Path
    config: ActiveModConfig
    raw_bytes: bytes
    fingerprint: str


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


def _read_save_bytes(
    path: Path, *, allow_missing: bool, label: str = "mods.txt"
) -> bytes | None:
    if _is_link_or_junction(path):
        raise SaveModDiscoveryError(f"{label} is a symbolic link or junction.")
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise SaveModDiscoveryError(f"{label} does not exist.") from None
    except OSError as exc:
        raise SaveModDiscoveryError(f"Could not inspect {label}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SaveModDiscoveryError(f"{label} is not a regular file.")
    if info.st_size > _MAX_SAVE_MODS_BYTES:
        raise SaveModDiscoveryError(f"{label} exceeds the 1 MiB size limit.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened_info = os.fstat(source.fileno())
            if not stat.S_ISREG(opened_info.st_mode):
                raise SaveModDiscoveryError(f"{label} is not a regular file.")
            if opened_info.st_size > _MAX_SAVE_MODS_BYTES:
                raise SaveModDiscoveryError(f"{label} exceeds the 1 MiB size limit.")
            data = source.read(_MAX_SAVE_MODS_BYTES + 1)
    except SaveModDiscoveryError:
        raise
    except OSError as exc:
        raise SaveModDiscoveryError(f"Could not read {label}: {exc}") from exc
    if len(data) > _MAX_SAVE_MODS_BYTES:
        raise SaveModDiscoveryError(f"{label} grew beyond the 1 MiB size limit.")
    return data


def _validate_save_snapshot(snapshot: SaveModTargetSnapshot) -> Path:
    resolved_root, resolved_save = _validate_save_target(
        snapshot.saves_root, snapshot.save_directory
    )
    path = resolved_save / "mods.txt"
    if (
        resolved_root != snapshot.saves_root
        or resolved_save != snapshot.save_directory
        or path != snapshot.mods_path
    ):
        raise SaveModDiscoveryError(
            "The selected save target changed after it was read."
        )
    return path


def _parse_save_config(raw: bytes, label: str) -> ActiveModConfig:
    try:
        return replace(
            parse_active_mod_config(raw.decode("utf-8-sig")),
            has_utf8_bom=raw.startswith(b"\xef\xbb\xbf"),
        )
    except UnicodeDecodeError as exc:
        raise SaveModDiscoveryError(f"{label} is not valid UTF-8.") from exc
    except ActiveModConfigError as exc:
        raise SaveModDiscoveryError(f"{label}: {exc}") from exc


def _validate_save_target(saves_root: Path, save_directory: Path) -> tuple[Path, Path]:
    root = saves_root.expanduser().absolute()
    save = save_directory.expanduser().absolute()
    if root.name.casefold() != "saves":
        raise SaveModDiscoveryError("Choose the Project Zomboid Saves folder.")
    if _is_link_or_junction(root):
        raise SaveModDiscoveryError("Linked Saves folders cannot be written safely.")
    if _is_link_or_junction(save):
        raise SaveModDiscoveryError("Linked save folders cannot be written safely.")
    mode = save.parent
    if mode.parent != root:
        raise SaveModDiscoveryError(
            "A save target must be exactly <Saves>/<mode>/<save>/mods.txt."
        )
    if _is_link_or_junction(mode):
        raise SaveModDiscoveryError("Linked save-mode folders are not supported.")
    try:
        if not stat.S_ISDIR(root.stat(follow_symlinks=False).st_mode):
            raise SaveModDiscoveryError("The selected Saves path is not a folder.")
        if not stat.S_ISDIR(mode.stat(follow_symlinks=False).st_mode):
            raise SaveModDiscoveryError("The save-mode path is not a folder.")
        if not stat.S_ISDIR(save.stat(follow_symlinks=False).st_mode):
            raise SaveModDiscoveryError("The selected save path is not a folder.")
        resolved_root = root.resolve(strict=True)
        resolved_mode = mode.resolve(strict=True)
        resolved_save = save.resolve(strict=True)
    except OSError as exc:
        raise SaveModDiscoveryError(
            f"Could not validate the save target: {exc}"
        ) from exc
    if resolved_mode.parent != resolved_root or resolved_save.parent != resolved_mode:
        raise SaveModDiscoveryError(
            "The save target resolves outside the selected Saves folder."
        )
    return resolved_root, resolved_save


def read_save_mod_target(
    saves_root: Path, save_directory: Path
) -> SaveModTargetSnapshot:
    """Read one immediate save target, including saves inheriting the global list."""
    resolved_root, resolved_save = _validate_save_target(saves_root, save_directory)
    mods_path = resolved_save / "mods.txt"
    raw = _read_save_bytes(mods_path, allow_missing=True)
    if raw is None:
        config = ActiveModConfig(version=1, mods=(), maps=())
        fingerprint = None
    else:
        config = _parse_save_config(raw, "mods.txt")
        fingerprint = hashlib.sha256(raw).hexdigest()
    return SaveModTargetSnapshot(
        saves_root=resolved_root,
        save_directory=resolved_save,
        mods_path=mods_path,
        config=config,
        raw_bytes=raw,
        fingerprint=fingerprint,
    )


def list_save_mod_backups(snapshot: SaveModTargetSnapshot) -> tuple[Path, ...]:
    """List sibling timestamped backups for this exact save target."""
    path = _validate_save_snapshot(snapshot)
    try:
        backups = [
            child
            for child in path.parent.glob("mods.txt.bak-*")
            if not _is_link_or_junction(child)
            and stat.S_ISREG(child.stat(follow_symlinks=False).st_mode)
        ]
    except OSError as exc:
        raise SaveModDiscoveryError(f"Could not list save-list backups: {exc}") from exc
    return tuple(sorted(backups, key=lambda item: item.name, reverse=True))


def read_save_mod_backup(
    snapshot: SaveModTargetSnapshot, backup_path: Path | str
) -> SaveModBackup:
    """Read and validate a backup beside the exact selected save list."""
    path = _validate_save_snapshot(snapshot)
    backup = Path(backup_path).expanduser().absolute()
    if (
        backup.parent != path.parent
        or not backup.name.startswith("mods.txt.bak-")
        or _is_link_or_junction(backup)
    ):
        raise SaveModDiscoveryError(
            "Choose a timestamped backup beside the selected save's mods.txt."
        )
    raw = _read_save_bytes(backup, allow_missing=False, label="save-list backup")
    assert raw is not None
    config = _parse_save_config(raw, "Save-list backup")
    return SaveModBackup(
        path=backup,
        config=config,
        raw_bytes=raw,
        fingerprint=hashlib.sha256(raw).hexdigest(),
    )


def restore_save_mod_backup(
    snapshot: SaveModTargetSnapshot, backup: SaveModBackup
) -> Path | None:
    """Restore a validated backup after stale-file checks and a fresh backup."""
    path = _validate_save_snapshot(snapshot)
    current = _read_save_bytes(path, allow_missing=True)
    current_fingerprint = (
        hashlib.sha256(current).hexdigest() if current is not None else None
    )
    if current_fingerprint != snapshot.fingerprint:
        raise ConcurrentSaveModChangeError(
            "The save mod list changed after it was loaded; reload before restoring."
        )

    selected = read_save_mod_backup(snapshot, backup.path)
    if (
        selected.raw_bytes != backup.raw_bytes
        or selected.fingerprint != backup.fingerprint
    ):
        raise ConcurrentSaveModChangeError(
            "The selected save-list backup changed after it was previewed; choose it again."
        )
    if current == backup.raw_bytes:
        return None

    current_backup: Path | None = None
    if current is not None:
        current_backup = _save_backup_path(path)
        try:
            with current_backup.open("xb") as stream:
                stream.write(current)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise SaveModDiscoveryError(
                f"Could not create save-list backup: {exc}"
            ) from exc

    try:
        _atomic_save_replace(path, backup.raw_bytes, must_not_exist=current is None)
        written = _read_save_bytes(path, allow_missing=False)
        assert written is not None
        if (
            written != backup.raw_bytes
            or _parse_save_config(written, "mods.txt") != backup.config
        ):
            raise SaveModDiscoveryError("Restored save mod list did not verify.")
    except Exception as exc:
        try:
            latest = _read_save_bytes(path, allow_missing=True)
        except SaveModDiscoveryError:
            latest = None
        if latest == backup.raw_bytes:
            try:
                if current is None:
                    path.unlink()
                else:
                    _atomic_save_replace(path, current, must_not_exist=False)
            except OSError as rollback_error:
                raise SaveModDiscoveryError(
                    f"Save-list restore failed and rollback failed. Backup: {current_backup}"
                ) from rollback_error
            raise SaveModDiscoveryError(
                f"Save-list restore failed; the previous state was restored. Backup: {current_backup}"
            ) from exc
        raise SaveModDiscoveryError(
            f"The save list changed during restore and was left untouched. Backup: {current_backup}"
        ) from exc
    return current_backup


def reset_save_mod_target(snapshot: SaveModTargetSnapshot) -> Path | None:
    """Remove one explicit save list so the save inherits the global list.

    An existing file is copied to its timestamped sibling backup before it is
    removed. A save already inheriting the global list is left unchanged.
    """
    path = _validate_save_snapshot(snapshot)
    current = _read_save_bytes(path, allow_missing=True)
    current_fingerprint = (
        hashlib.sha256(current).hexdigest() if current is not None else None
    )
    if current_fingerprint != snapshot.fingerprint:
        raise ConcurrentSaveModChangeError(
            "The save mod list changed after it was loaded; reload before resetting."
        )
    if current is None:
        if _read_save_bytes(path, allow_missing=True) is not None:
            raise ConcurrentSaveModChangeError(
                "A save mod list appeared while resetting; reload before trying again."
            )
        return None

    backup = _save_backup_path(path)
    try:
        with backup.open("xb") as stream:
            stream.write(current)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise SaveModDiscoveryError(
            f"Could not create save-list backup: {exc}"
        ) from exc
    backed_up = _read_save_bytes(backup, allow_missing=False, label="save-list backup")
    if backed_up != current:
        raise SaveModDiscoveryError(
            f"Save-list backup did not verify; the save was left unchanged. Backup: {backup}"
        )

    latest = _read_save_bytes(path, allow_missing=True)
    if latest != snapshot.raw_bytes:
        raise ConcurrentSaveModChangeError(
            f"The save mod list changed while resetting; reload before trying again. Backup: {backup}"
        )
    try:
        path.unlink()
    except OSError as exc:
        raise SaveModDiscoveryError(
            f"Could not remove the explicit save list. Backup: {backup}"
        ) from exc
    remaining = _read_save_bytes(path, allow_missing=True)
    if remaining is not None:
        raise ConcurrentSaveModChangeError(
            f"The save mod list changed during reset and was left in place. Backup: {backup}"
        )
    return backup


def _save_backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{suffix}")
        suffix += 1
    return candidate


def _atomic_save_replace(path: Path, data: bytes, *, must_not_exist: bool) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if must_not_exist:
            # A hard link makes creation atomic and fails if another process has
            # created the inherited save's explicit list after our read.
            os.link(temp_path, path)
            temp_path.unlink()
        else:
            shutil.copystat(path, temp_path)
            os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def write_save_mod_ids(
    snapshot: SaveModTargetSnapshot, mod_ids: tuple[str, ...]
) -> Path | None:
    """Back up and atomically write one explicit save mod list.

    Maps are preserved for saves with an explicit file. For a save inheriting
    global settings, an explicit list is created with no map IDs.
    """
    path = _validate_save_snapshot(snapshot)
    current = _read_save_bytes(path, allow_missing=True)
    current_fingerprint = (
        hashlib.sha256(current).hexdigest() if current is not None else None
    )
    if current_fingerprint != snapshot.fingerprint:
        raise ConcurrentSaveModChangeError(
            "The save mod list changed after it was loaded; reload before applying."
        )
    config = ActiveModConfig(
        version=snapshot.config.version,
        mods=mod_ids,
        maps=snapshot.config.maps,
        newline=snapshot.config.newline,
        has_utf8_bom=snapshot.config.has_utf8_bom,
    )
    if current is not None and config == snapshot.config:
        return None
    try:
        output = render_active_mod_config(config).encode("utf-8")
    except ActiveModConfigError as exc:
        raise SaveModDiscoveryError(str(exc)) from exc
    if config.has_utf8_bom:
        output = b"\xef\xbb\xbf" + output
    try:
        parsed = parse_active_mod_config(output.decode("utf-8-sig"))
    except (UnicodeDecodeError, ActiveModConfigError) as exc:
        raise SaveModDiscoveryError(
            "Generated save mod list did not validate."
        ) from exc
    if replace(parsed, has_utf8_bom=config.has_utf8_bom) != config:
        raise SaveModDiscoveryError("Generated save mod list did not round-trip.")

    backup: Path | None = None
    if current is not None:
        backup = _save_backup_path(path)
        try:
            with backup.open("xb") as stream:
                stream.write(current)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise SaveModDiscoveryError(
                f"Could not create save-list backup: {exc}"
            ) from exc
    try:
        _atomic_save_replace(path, output, must_not_exist=current is None)
        written = _read_save_bytes(path, allow_missing=False)
        verified = replace(
            parse_active_mod_config(written.decode("utf-8-sig")),
            has_utf8_bom=config.has_utf8_bom,
        )
        if written != output or verified != config:
            raise SaveModDiscoveryError("Written save mod list did not verify.")
    except Exception as exc:
        try:
            latest = _read_save_bytes(path, allow_missing=True)
        except SaveModDiscoveryError:
            latest = None
        if latest == output:
            try:
                if current is None:
                    path.unlink()
                else:
                    _atomic_save_replace(path, current, must_not_exist=False)
            except OSError as rollback_error:
                raise SaveModDiscoveryError(
                    f"Save-list verification failed and rollback failed. Backup: {backup}"
                ) from rollback_error
            raise SaveModDiscoveryError(
                f"Save-list verification failed; the previous state was restored. Backup: {backup}"
            ) from exc
        raise SaveModDiscoveryError(
            f"The save list changed after replacement and was left untouched. Backup: {backup}"
        ) from exc
    return backup


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
