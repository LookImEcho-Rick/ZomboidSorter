"""Guarded writes to the separate Project Zomboid server settings file."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_MAX_SERVER_INI_BYTES = 1024 * 1024
_SETTING_LINE = re.compile(
    r"^([ \t]*(Mods|WorkshopItems)[ \t]*=[ \t]*)(.*)$", re.IGNORECASE
)
_WORKSHOP_ID = re.compile(r"^\d{1,20}$")


class ServerSettingsError(ValueError):
    """The selected server settings file is malformed or unsafe to update."""


class ConcurrentServerSettingsChangeError(RuntimeError):
    """The server settings changed after loading and before applying."""


@dataclass(frozen=True)
class ServerSettingsConfig:
    mods: tuple[str, ...]
    workshop_items: tuple[str, ...]


@dataclass(frozen=True)
class ServerSettingsSnapshot:
    path: Path
    config: ServerSettingsConfig
    raw_bytes: bytes
    fingerprint: str


def _split_ids(value: str, label: str, *, workshop: bool) -> tuple[str, ...]:
    if not value.strip():
        return ()
    parts = value.split(";")
    values = tuple(part.strip() for part in parts)
    if any(not item for item in values):
        raise ServerSettingsError(f"{label} contains an empty item between separators.")
    if any("\n" in item or "\r" in item or "=" in item for item in values):
        raise ServerSettingsError(f"{label} contains unsupported characters.")
    if workshop and any(not _WORKSHOP_ID.fullmatch(item) for item in values):
        raise ServerSettingsError("WorkshopItems must contain numeric Workshop IDs.")
    if len(values) != len(set(values)):
        raise ServerSettingsError(f"{label} contains duplicate entries.")
    return values


def _locate_settings(
    text: str,
) -> tuple[ServerSettingsConfig, dict[str, int], list[str]]:
    lines = text.splitlines(keepends=True)
    positions: dict[str, int] = {}
    values: dict[str, tuple[str, ...]] = {}
    for index, raw_line in enumerate(lines):
        body = raw_line.rstrip("\r\n")
        match = _SETTING_LINE.fullmatch(body)
        if match is None:
            continue
        key = match.group(2).casefold()
        if key in positions:
            raise ServerSettingsError(
                f"Server settings contain more than one {key} line."
            )
        positions[key] = index
        values[key] = _split_ids(
            match.group(3),
            "Mods" if key == "mods" else "WorkshopItems",
            workshop=key == "workshopitems",
        )
    if set(positions) != {"mods", "workshopitems"}:
        missing = " and ".join(
            key for key in ("Mods", "WorkshopItems") if key.casefold() not in positions
        )
        raise ServerSettingsError(
            f"Server settings must contain both Mods and WorkshopItems lines; missing {missing}."
        )
    return (
        ServerSettingsConfig(values["mods"], values["workshopitems"]),
        positions,
        lines,
    )


def parse_server_settings(text: str) -> ServerSettingsConfig:
    """Parse only the two verified semicolon-delimited server settings."""
    config, _positions, _lines = _locate_settings(text)
    return config


def _decode(raw: bytes) -> tuple[str, bool]:
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        return raw.decode("utf-8-sig"), has_bom
    except UnicodeDecodeError as exc:
        raise ServerSettingsError(
            "The server settings file is not valid UTF-8."
        ) from exc


def _validate_server_path(path: Path) -> Path:
    target = path.expanduser().absolute()
    if target.suffix.casefold() != ".ini":
        raise ServerSettingsError("Choose a Project Zomboid server .ini file.")
    server_dir = target.parent
    zomboid_dir = server_dir.parent
    if (
        server_dir.name.casefold() != "server"
        or zomboid_dir.name.casefold() != "zomboid"
    ):
        raise ServerSettingsError(
            "Writes are limited to <Zomboid>/Server/<server-name>.ini."
        )
    for directory in (zomboid_dir, server_dir):
        if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
            raise ServerSettingsError(
                "Linked server configuration folders are not supported."
            )
    if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
        raise ServerSettingsError(
            "Linked server settings files cannot be written safely."
        )
    try:
        info = target.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ServerSettingsError(
                "The selected server settings path is not a regular file."
            )
        if info.st_size > _MAX_SERVER_INI_BYTES:
            raise ServerSettingsError(
                "The server settings file exceeds the 1 MiB size limit."
            )
        resolved = target.resolve(strict=True)
        resolved_server = server_dir.resolve(strict=True)
        resolved_zomboid = zomboid_dir.resolve(strict=True)
    except OSError as exc:
        raise ServerSettingsError(
            f"Could not validate server settings path: {exc}"
        ) from exc
    if resolved.parent != resolved_server or resolved_server.parent != resolved_zomboid:
        raise ServerSettingsError(
            "Server settings path resolves outside its selected folder."
        )
    return resolved


def _read_raw(path: Path) -> bytes:
    try:
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ServerSettingsError("The server settings path is not a regular file.")
        if info.st_size > _MAX_SERVER_INI_BYTES:
            raise ServerSettingsError(
                "The server settings file exceeds the 1 MiB size limit."
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened_info = os.fstat(source.fileno())
            if not stat.S_ISREG(opened_info.st_mode):
                raise ServerSettingsError(
                    "The server settings path is not a regular file."
                )
            raw = source.read(_MAX_SERVER_INI_BYTES + 1)
    except ServerSettingsError:
        raise
    except OSError as exc:
        raise ServerSettingsError(f"Could not read server settings: {exc}") from exc
    if len(raw) > _MAX_SERVER_INI_BYTES:
        raise ServerSettingsError(
            "The server settings file grew beyond the size limit."
        )
    return raw


def read_server_settings(path: Path | str) -> ServerSettingsSnapshot:
    """Read one selected server .ini without changing it."""
    target = _validate_server_path(Path(path))
    raw = _read_raw(target)
    text, _has_bom = _decode(raw)
    config = parse_server_settings(text)
    return ServerSettingsSnapshot(
        path=target,
        config=config,
        raw_bytes=raw,
        fingerprint=hashlib.sha256(raw).hexdigest(),
    )


def _render(snapshot: ServerSettingsSnapshot, config: ServerSettingsConfig) -> bytes:
    text, has_bom = _decode(snapshot.raw_bytes)
    _old_config, positions, lines = _locate_settings(text)
    replacements = {
        "mods": ";".join(config.mods),
        "workshopitems": ";".join(config.workshop_items),
    }
    for key, index in positions.items():
        raw_line = lines[index]
        line_ending = (
            "\r\n"
            if raw_line.endswith("\r\n")
            else (
                "\n"
                if raw_line.endswith("\n")
                else "\r"
                if raw_line.endswith("\r")
                else ""
            )
        )
        body = raw_line[: -len(line_ending)] if line_ending else raw_line
        match = _SETTING_LINE.fullmatch(body)
        assert match is not None
        lines[index] = f"{match.group(1)}{replacements[key]}{line_ending}"
    output = "".join(lines).encode("utf-8")
    return b"\xef\xbb\xbf" + output if has_bom else output


def _backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{suffix}")
        suffix += 1
    return candidate


def _atomic_replace(path: Path, data: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, temp_path)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def write_server_settings(
    snapshot: ServerSettingsSnapshot,
    *,
    mods: tuple[str, ...],
    workshop_items: tuple[str, ...],
) -> Path | None:
    """Replace only Mods/WorkshopItems after backup and stale-file checks."""
    path = _validate_server_path(snapshot.path)
    if path != snapshot.path:
        raise ServerSettingsError(
            "The selected server settings target changed after loading."
        )
    raw = _read_raw(path)
    if hashlib.sha256(raw).hexdigest() != snapshot.fingerprint:
        raise ConcurrentServerSettingsChangeError(
            "Server settings changed after they were loaded; reload before applying."
        )
    config = ServerSettingsConfig(mods, workshop_items)
    # Validate identifiers and separator safety using the same parser used on readback.
    if any(
        not value
        or value != value.strip()
        or ";" in value
        or "\n" in value
        or "\r" in value
        or "=" in value
        for value in mods
    ):
        raise ServerSettingsError("Mod IDs contain unsupported server-list characters.")
    if len(mods) != len(set(mods)):
        raise ServerSettingsError("Mod IDs contain duplicates.")
    if any(not _WORKSHOP_ID.fullmatch(value) for value in workshop_items):
        raise ServerSettingsError("WorkshopItems must contain numeric Workshop IDs.")
    if len(workshop_items) != len(set(workshop_items)):
        raise ServerSettingsError("WorkshopItems contain duplicates.")
    if config == snapshot.config:
        return None
    output = _render(snapshot, config)
    try:
        parsed = parse_server_settings(_decode(output)[0])
    except ServerSettingsError as exc:
        raise ServerSettingsError(
            "Generated server settings did not validate."
        ) from exc
    if parsed != config:
        raise ServerSettingsError("Generated server settings did not round-trip.")

    backup = _backup_path(path)
    try:
        with backup.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ServerSettingsError(
            f"Could not create server settings backup: {exc}"
        ) from exc
    try:
        _atomic_replace(path, output)
        written = _read_raw(path)
        if written != output or parse_server_settings(_decode(written)[0]) != config:
            raise ServerSettingsError("Updated server settings did not verify.")
    except Exception as exc:
        try:
            latest = _read_raw(path)
        except ServerSettingsError:
            latest = None
        if latest == output:
            try:
                _atomic_replace(path, raw)
            except OSError as rollback_error:
                raise ServerSettingsError(
                    f"Server settings verification failed and rollback failed. Backup: {backup}"
                ) from rollback_error
            raise ServerSettingsError(
                f"Server settings verification failed; the original file was restored. Backup: {backup}"
            ) from exc
        raise ServerSettingsError(
            f"Server settings changed after replacement and were left untouched. Backup: {backup}"
        ) from exc
    return backup
