"""Strict support for the verified global ``Zomboid/mods/default.txt`` format.

Per-save ``mods.txt`` files are intentionally unsupported here.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path


class ActiveModConfigError(ValueError):
    """The active-mod file is malformed or uses an unsupported format."""


class ConcurrentConfigChangeError(RuntimeError):
    """The configuration changed after it was read and before it was applied."""


@dataclass(frozen=True)
class ActiveModConfig:
    version: int
    mods: tuple[str, ...]
    maps: tuple[str, ...]
    newline: str = "\n"
    has_utf8_bom: bool = False


@dataclass(frozen=True)
class ActiveModSnapshot:
    path: Path
    config: ActiveModConfig
    raw_bytes: bytes
    fingerprint: str


_VERSION = re.compile(r"^VERSION\s*=\s*(\d+)\s*,?$")
_SECTION = re.compile(r"^(mods|maps)$")
_ENTRY = re.compile(r"^(mod|map)\s*=\s*(.*?)\s*,?$")


def _validate_identifiers(values: tuple[str, ...], label: str) -> None:
    if any(
        not value or value != value.strip() or "\n" in value or "\r" in value
        for value in values
    ):
        raise ActiveModConfigError(
            f"{label} must be non-empty, single-line identifiers without surrounding spaces."
        )
    if len(values) != len(set(values)):
        raise ActiveModConfigError(
            f"{label} contains duplicates; refusing to rewrite the file."
        )


def parse_active_mod_config(text: str) -> ActiveModConfig:
    """Parse the observed VERSION/mods/maps format, rejecting unknown syntax."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    significant = [
        (number, line.strip()) for number, line in enumerate(lines, 1) if line.strip()
    ]
    if not significant:
        raise ActiveModConfigError("The active-mod file is empty.")

    first_number, first_line = significant[0]
    version_match = _VERSION.fullmatch(first_line)
    if not version_match:
        raise ActiveModConfigError(f"Line {first_number}: expected VERSION = 1.")
    version = int(version_match.group(1))
    if version != 1:
        raise ActiveModConfigError(f"Unsupported active-mod file version {version}.")

    sections: dict[str, list[str]] = {}
    current: str | None = None
    block_open = False
    for number, raw_line in enumerate(lines[first_number:], first_number + 1):
        line = raw_line.strip()
        if not line:
            continue
        if current is None:
            section_match = _SECTION.fullmatch(line)
            if not section_match:
                raise ActiveModConfigError(
                    f"Line {number}: unsupported top-level syntax."
                )
            current = section_match.group(1)
            if current in sections:
                raise ActiveModConfigError(
                    f"Line {number}: duplicate '{current}' section."
                )
            sections[current] = []
            block_open = False
            continue

        if not block_open:
            if line != "{":
                raise ActiveModConfigError(
                    f"Line {number}: expected '{{' after the '{current}' section."
                )
            block_open = True
            continue
        if line == "}":
            current = None
            block_open = False
            continue
        if "{" in line or "}" in line:
            raise ActiveModConfigError(
                f"Line {number}: unsupported nested or malformed block."
            )

        entry_match = _ENTRY.fullmatch(line)
        if not entry_match:
            raise ActiveModConfigError(f"Line {number}: unsupported entry syntax.")
        expected_key = "mod" if current == "mods" else "map"
        if entry_match.group(1) != expected_key:
            raise ActiveModConfigError(
                f"Line {number}: expected '{expected_key}' in the '{current}' section."
            )
        value = entry_match.group(2).strip()
        if not value:
            raise ActiveModConfigError(
                f"Line {number}: empty {expected_key} identifier."
            )
        sections[current].append(value)

    if current is not None:
        raise ActiveModConfigError(
            f"The '{current}' section is missing its closing brace."
        )
    if set(sections) != {"mods", "maps"}:
        raise ActiveModConfigError(
            "Expected exactly one 'mods' section and one 'maps' section."
        )

    mods = tuple(sections["mods"])
    maps = tuple(sections["maps"])
    _validate_identifiers(mods, "Mod IDs")
    _validate_identifiers(maps, "Map IDs")
    return ActiveModConfig(version, mods, maps, newline)


def render_active_mod_config(config: ActiveModConfig) -> str:
    """Render only the supported config schema using the source line ending."""
    if config.version != 1:
        raise ActiveModConfigError(
            f"Unsupported active-mod file version {config.version}."
        )
    _validate_identifiers(config.mods, "Mod IDs")
    _validate_identifiers(config.maps, "Map IDs")
    nl = config.newline if config.newline in ("\n", "\r\n") else "\n"
    lines = [f"VERSION = {config.version},", "", "mods", "{"]
    lines.extend(f"    mod = {mod_id}," for mod_id in config.mods)
    lines.extend(("}", "", "maps", "{"))
    lines.extend(f"    map = {map_id}," for map_id in config.maps)
    lines.extend(("}", ""))
    return nl.join(lines)


def read_active_mods(path: Path) -> ActiveModSnapshot:
    """Read and validate a global default list without touching it."""
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ActiveModConfigError(
            "The active-mod file is not valid UTF-8; refusing to rewrite it."
        ) from exc
    config = parse_active_mod_config(text)
    config = replace(config, has_utf8_bom=has_bom)
    return ActiveModSnapshot(
        path=path,
        config=config,
        raw_bytes=raw,
        fingerprint=hashlib.sha256(raw).hexdigest(),
    )


def _backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{suffix}")
        suffix += 1
    return candidate


def _write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


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
        if path.exists():
            shutil.copystat(path, temp_path)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _require_global_default_target(path: Path) -> None:
    if path.is_symlink():
        raise ActiveModConfigError(
            "Symbolic-link config targets cannot be written safely."
        )
    resolved = path.resolve(strict=False)
    parts = tuple(part.casefold() for part in resolved.parts)
    if len(parts) < 3 or parts[-3:] != ("zomboid", "mods", "default.txt"):
        raise ActiveModConfigError(
            "Writes are limited to the global Zomboid/mods/default.txt file."
        )
    if "saves" in parts:
        raise ActiveModConfigError("Save data is protected and cannot be modified.")


def write_active_mods(snapshot: ActiveModSnapshot, mod_ids: tuple[str, ...]) -> Path:
    """Back up, atomically replace, and verify a previously-read default list."""
    _require_global_default_target(snapshot.path)
    _validate_identifiers(mod_ids, "Mod IDs")
    current_bytes = snapshot.path.read_bytes()
    current_fingerprint = hashlib.sha256(current_bytes).hexdigest()
    if current_fingerprint != snapshot.fingerprint:
        raise ConcurrentConfigChangeError(
            "The active-mod file changed since it was loaded; reload before applying."
        )
    if mod_ids == snapshot.config.mods:
        raise ActiveModConfigError("The active mod list has no changes to apply.")

    new_config = replace(snapshot.config, mods=mod_ids)
    output_text = render_active_mod_config(new_config)
    output_bytes = output_text.encode("utf-8")
    if new_config.has_utf8_bom:
        output_bytes = b"\xef\xbb\xbf" + output_bytes
    # Validate the exact bytes that will be written before creating a backup.
    verified = parse_active_mod_config(output_bytes.decode("utf-8-sig"))
    if replace(verified, has_utf8_bom=new_config.has_utf8_bom) != new_config:
        raise ActiveModConfigError(
            "Generated configuration did not round-trip; refusing to write."
        )

    backup_path = _backup_path(snapshot.path)
    _write_exclusive(backup_path, snapshot.raw_bytes)
    _atomic_replace(snapshot.path, output_bytes)

    try:
        written = snapshot.path.read_bytes()
        if written != output_bytes:
            raise ConcurrentConfigChangeError(
                "The file changed immediately after the write."
            )
        result = read_active_mods(snapshot.path)
        if result.config != new_config:
            raise ActiveModConfigError("Written configuration did not round-trip.")
    except Exception as exc:
        try:
            current_bytes = snapshot.path.read_bytes()
        except OSError:
            current_bytes = None
        if current_bytes == output_bytes:
            try:
                _atomic_replace(snapshot.path, snapshot.raw_bytes)
            except OSError as rollback_error:
                raise ActiveModConfigError(
                    f"Post-write verification failed and automatic rollback failed. Backup: {backup_path}"
                ) from rollback_error
            raise ActiveModConfigError(
                f"Post-write verification failed; the original file was restored. Backup: {backup_path}"
            ) from exc
        raise ActiveModConfigError(
            f"The file changed after replacement and was left untouched. Backup: {backup_path}"
        ) from exc
    return backup_path
