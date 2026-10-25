"""Portable, app-owned mod profiles with atomic persistence and recovery."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .portable import app_data_directory


class ProfileError(ValueError):
    """A profile is invalid or the requested profile operation is unsafe."""


@dataclass(frozen=True)
class CollectionContent:
    workshop_id: str
    sha256: str


@dataclass(frozen=True)
class ModProfile:
    name: str
    mod_ids: tuple[str, ...]
    workshop_ids: tuple[str, ...] = ()
    map_ids: tuple[str, ...] | None = None
    collection_content: tuple[CollectionContent, ...] = ()


_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAME = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_MAX_PROFILE_BYTES = 4 * 1024 * 1024
_MAX_PROFILE_MODS = 100_000


def suggest_profile_name(title: str, *, fallback: str) -> str:
    """Turn a public collection title into an editable Windows-safe pack name."""
    name = " ".join(_INVALID_NAME.sub(" ", title).split())[:80].rstrip(". ")
    try:
        validate_profile(ModProfile(name, ()))
    except ProfileError:
        return fallback
    return name


def validate_profile(profile: ModProfile) -> None:
    name = profile.name
    if not name or name != name.strip() or len(name) > 80:
        raise ProfileError(
            "Profile names must contain 1–80 characters with no leading or trailing spaces."
        )
    if (
        _INVALID_NAME.search(name)
        or name.endswith((".", " "))
        or _RESERVED_NAME.fullmatch(name)
    ):
        raise ProfileError("The profile name contains characters reserved by Windows.")
    if len(profile.mod_ids) > _MAX_PROFILE_MODS:
        raise ProfileError("The profile contains too many Mod IDs.")
    if any(
        not mod_id or mod_id != mod_id.strip() or "\n" in mod_id or "\r" in mod_id
        for mod_id in profile.mod_ids
    ):
        raise ProfileError(
            "Mod IDs must be non-empty, single-line values without surrounding spaces."
        )
    if len(profile.mod_ids) != len(set(profile.mod_ids)):
        raise ProfileError("The profile contains duplicate Mod IDs.")
    if profile.map_ids is not None:
        if len(profile.map_ids) > _MAX_PROFILE_MODS:
            raise ProfileError("The profile contains too many Map IDs.")
        if any(
            not map_id or map_id != map_id.strip() or "\n" in map_id or "\r" in map_id
            for map_id in profile.map_ids
        ):
            raise ProfileError(
                "Map IDs must be non-empty, single-line values without surrounding spaces."
            )
        if len(profile.map_ids) != len(set(profile.map_ids)):
            raise ProfileError("The profile contains duplicate Map IDs.")
    if any(
        not re.fullmatch(r"\d{1,20}", workshop_id)
        for workshop_id in profile.workshop_ids
    ):
        raise ProfileError("Workshop IDs must contain 1–20 decimal digits.")
    if len(profile.workshop_ids) > 5000:
        raise ProfileError("The profile contains too many Workshop IDs.")
    if len(profile.workshop_ids) != len(set(profile.workshop_ids)):
        raise ProfileError("The profile contains duplicate Workshop IDs.")
    content_ids = [item.workshop_id for item in profile.collection_content]
    if (
        len(content_ids) > 5000
        or len(content_ids) != len(set(content_ids))
        or any(
            item.workshop_id not in profile.workshop_ids
            or not re.fullmatch(r"[0-9a-f]{64}", item.sha256)
            for item in profile.collection_content
        )
    ):
        raise ProfileError(
            "Collection content must reference unique Workshop IDs and exact SHA-256 content hashes."
        )


def parse_profile(data: bytes) -> ModProfile:
    if len(data) > _MAX_PROFILE_BYTES:
        raise ProfileError("The profile file is too large.")
    try:
        value: Any = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileError("The profile is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ProfileError("The profile root must be a JSON object.")
    version = value.get("schemaVersion")
    expected_keys = {"schemaVersion", "name", "modIds"}
    if version in (2, 3, 4):
        expected_keys.add("workshopIds")
    if version in (3, 4):
        expected_keys.add("mapIds")
    if version == 4:
        expected_keys.add("collectionContent")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in (1, 2, 3, 4)
    ):
        raise ProfileError(f"Unsupported profile schema version: {version!r}.")
    if set(value) != expected_keys:
        raise ProfileError(f"Version {version} profile has an unexpected field set.")
    if not isinstance(value["name"], str) or not isinstance(value["modIds"], list):
        raise ProfileError("Profile name must be text and modIds must be a list.")
    if any(not isinstance(mod_id, str) for mod_id in value["modIds"]):
        raise ProfileError("Every Mod ID must be text.")
    map_ids = value.get("mapIds")
    if version == 3 and not isinstance(map_ids, list):
        raise ProfileError("mapIds must be a list of text IDs.")
    if map_ids is not None and (
        not isinstance(map_ids, list)
        or any(not isinstance(map_id, str) for map_id in map_ids)
    ):
        raise ProfileError("mapIds must be a list of text IDs.")
    workshop_ids = value.get("workshopIds", [])
    if not isinstance(workshop_ids, list) or any(
        not isinstance(item, str) for item in workshop_ids
    ):
        raise ProfileError("workshopIds must be a list of text IDs.")
    content = value.get("collectionContent", [])
    if not isinstance(content, list) or any(
        not isinstance(item, dict)
        or set(item) != {"workshopId", "sha256"}
        or not isinstance(item["workshopId"], str)
        or not isinstance(item["sha256"], str)
        for item in content
    ):
        raise ProfileError(
            "collectionContent must contain Workshop IDs and SHA-256 hashes."
        )
    profile = ModProfile(
        value["name"],
        tuple(value["modIds"]),
        tuple(workshop_ids),
        tuple(map_ids) if map_ids is not None else None,
        tuple(
            CollectionContent(item["workshopId"], item["sha256"]) for item in content
        ),
    )
    validate_profile(profile)
    return profile


def serialize_profile(profile: ModProfile) -> bytes:
    validate_profile(profile)
    version = (
        4 if profile.collection_content else 3 if profile.map_ids is not None else 2
    )
    value = {
        "schemaVersion": version,
        "name": profile.name,
        "modIds": list(profile.mod_ids),
        "workshopIds": list(profile.workshop_ids),
    }
    if profile.map_ids is not None:
        value["mapIds"] = list(profile.map_ids)
    if profile.collection_content:
        value["mapIds"] = list(profile.map_ids) if profile.map_ids is not None else None
        value["collectionContent"] = [
            {"workshopId": item.workshop_id, "sha256": item.sha256}
            for item in profile.collection_content
        ]
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def default_profile_root() -> Path:
    return app_data_directory() / "profiles"


class ProfileStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_profile_root()).expanduser()
        self.backup_root = self.root / "backups"
        self.deleted_root = self.root / "deleted"

    def _path(self, name: str) -> Path:
        profile = ModProfile(name, ())
        validate_profile(profile)
        return self.root / f"{name}.json"

    def list_names(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(
            sorted(
                (path.stem for path in self.root.glob("*.json") if path.is_file()),
                key=str.casefold,
            )
        )

    def load(self, name: str) -> ModProfile:
        path = self._path(name)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ProfileError(f"Could not read profile '{name}': {exc}") from exc
        profile = parse_profile(data)
        if profile.name != name:
            raise ProfileError("Profile file name does not match its stored name.")
        return profile

    def save(self, profile: ModProfile, *, overwrite: bool = False) -> Path | None:
        validate_profile(profile)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(profile.name)
        backup: Path | None = None
        if path.exists():
            if not overwrite:
                raise ProfileError(f"Profile '{profile.name}' already exists.")
            self.backup_root.mkdir(parents=True, exist_ok=True)
            backup = self._unique_archive_path(self.backup_root, path.name)
            shutil.copy2(path, backup)
        self._atomic_write(path, serialize_profile(profile))
        return backup

    def import_file(
        self, source: Path, *, overwrite: bool = False
    ) -> tuple[ModProfile, Path | None]:
        try:
            profile = parse_profile(source.read_bytes())
        except OSError as exc:
            raise ProfileError(f"Could not import profile: {exc}") from exc
        backup = self.save(profile, overwrite=overwrite)
        return profile, backup

    def export(
        self, name: str, destination: Path, *, overwrite: bool = False
    ) -> Path | None:
        profile = self.load(name)
        if destination.exists() and not overwrite:
            raise ProfileError("The export destination already exists.")
        backup: Path | None = None
        if destination.exists():
            backup = self._unique_archive_path(destination.parent, destination.name)
            shutil.copy2(destination, backup)
        self._atomic_write(destination, serialize_profile(profile))
        return backup

    def delete(self, name: str) -> Path:
        path = self._path(name)
        if not path.is_file():
            raise ProfileError(f"Profile '{name}' does not exist.")
        self.deleted_root.mkdir(parents=True, exist_ok=True)
        archived = self._unique_archive_path(self.deleted_root, path.name)
        os.replace(path, archived)
        return archived

    def restore_deleted(
        self, archived_path: Path, *, overwrite: bool = False
    ) -> ModProfile:
        if archived_path.resolve(strict=False).parent != self.deleted_root.resolve(
            strict=False
        ):
            raise ProfileError(
                "Only profiles from the deleted-profiles archive can be restored here."
            )
        profile = parse_profile(archived_path.read_bytes())
        target = self._path(profile.name)
        if target.exists() and not overwrite:
            raise ProfileError(f"Profile '{profile.name}' already exists.")
        if target.exists():
            self.save(profile, overwrite=True)
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            os.replace(archived_path, target)
        return profile

    def restore_backup(self, name: str, backup_path: Path) -> Path | None:
        profile = parse_profile(backup_path.read_bytes())
        if profile.name != name:
            raise ProfileError("Backup belongs to a different profile.")
        return self.save(profile, overwrite=True)

    @staticmethod
    def _unique_archive_path(folder: Path, filename: str) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        candidate = folder / f"{filename}.{stamp}"
        sequence = 1
        while candidate.exists():
            candidate = folder / f"{filename}.{stamp}.{sequence}"
            sequence += 1
        return candidate

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
