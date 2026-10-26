"""Read-only game-save discovery and app-owned Mod Pack associations."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .profiles import ModProfile, ProfileError, validate_profile


class SavePackError(ValueError):
    """A save association is invalid or the app-owned index is unreadable."""


@dataclass(frozen=True)
class GameSave:
    """A discovered game save folder and its stable, app-owned grouping key."""

    key: str
    name: str
    mode: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.name} · {self.mode}"


_INDEX_NAME = "save-assignments.json"
_MAX_INDEX_BYTES = 2 * 1024 * 1024
_MAX_ASSIGNMENTS = 20_000
_MAX_DISCOVERED_SAVES = 20_000


def default_saves_root() -> Path:
    """Return the standard Windows/macOS/Linux Project Zomboid save root."""
    return Path.home() / "Zomboid" / "Saves"


def save_key(mode: str, name: str) -> str:
    """Return a case-insensitive key for one immediate mode/save folder pair."""
    parts = (mode, name)
    if any(
        not part
        or part != part.strip()
        or part in {".", ".."}
        or len(part) > 255
        or any(ord(char) < 32 or char in "\\/:" for char in part)
        for part in parts
    ):
        raise SavePackError("The save folder name cannot be used for a pack link.")
    return f"{mode.casefold()}/{name.casefold()}"


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def discover_saves(root: Path) -> tuple[GameSave, ...]:
    """List immediate ``Saves/<mode>/<save>`` directories without reading files."""
    root = root.expanduser()
    if not root.exists():
        return ()
    if _is_link_or_junction(root):
        raise SavePackError("The Project Zomboid Saves folder is a link or junction.")
    try:
        if not root.is_dir():
            raise SavePackError(
                "The selected Project Zomboid Saves path is not a folder."
            )
        resolved_root = root.resolve(strict=True)
        modes = tuple(root.iterdir())
    except OSError as exc:
        raise SavePackError(
            f"Could not read the Project Zomboid Saves folder: {exc}"
        ) from exc

    saves: list[GameSave] = []
    for mode_path in modes:
        if _is_link_or_junction(mode_path):
            continue
        try:
            if not mode_path.is_dir():
                continue
            mode_resolved = mode_path.resolve(strict=True)
            mode_resolved.relative_to(resolved_root)
            children = tuple(mode_path.iterdir())
        except OSError, ValueError:
            continue
        for save_path in children:
            if _is_link_or_junction(save_path):
                continue
            try:
                if not save_path.is_dir():
                    continue
                resolved = save_path.resolve(strict=True)
                resolved.relative_to(mode_resolved)
                key = save_key(mode_path.name, save_path.name)
            except OSError, ValueError, SavePackError:
                continue
            saves.append(
                GameSave(
                    key=key,
                    name=save_path.name,
                    mode=mode_path.name,
                    path=save_path,
                )
            )
            if len(saves) > _MAX_DISCOVERED_SAVES:
                raise SavePackError(
                    f"The Saves folder contains more than {_MAX_DISCOVERED_SAVES:,} entries."
                )
    return tuple(
        sorted(saves, key=lambda item: (item.mode.casefold(), item.name.casefold()))
    )


class SaveAssignmentStore:
    """Persist save-to-pack grouping in the app data directory only."""

    def __init__(self, app_data_root: Path) -> None:
        self.root = app_data_root.expanduser()
        self.path = self.root / _INDEX_NAME

    def assigned_pack(self, key: str) -> str | None:
        return self._read().get(_validate_key(key))

    def list_for_pack(self, pack_name: str) -> tuple[str, ...]:
        folded = pack_name.casefold()
        return tuple(
            sorted(
                key for key, name in self._read().items() if name.casefold() == folded
            )
        )

    def assign(self, key: str, pack_name: str) -> None:
        key = _validate_key(key)
        _validate_pack_name(pack_name)
        assignments = self._read()
        assignments[key] = pack_name
        self._write(assignments)

    def unassign(self, key: str, pack_name: str) -> None:
        key = _validate_key(key)
        assignments = self._read()
        current = assignments.get(key)
        if current is None or current.casefold() != pack_name.casefold():
            return
        del assignments[key]
        self._write(assignments)

    def unassign_pack(self, pack_name: str) -> None:
        folded = pack_name.casefold()
        assignments = self._read()
        updated = {
            key: name for key, name in assignments.items() if name.casefold() != folded
        }
        if updated != assignments:
            self._write(updated)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        if _is_link_or_junction(self.path):
            raise SavePackError("The app-owned save-assignment file is a link.")
        try:
            if self.path.lstat().st_size > _MAX_INDEX_BYTES:
                raise SavePackError("The app-owned save-assignment file is too large.")
            data = self.path.read_bytes()
        except OSError as exc:
            raise SavePackError(f"Could not read save groupings: {exc}") from exc
        if len(data) > _MAX_INDEX_BYTES:
            raise SavePackError("The app-owned save-assignment file is too large.")
        try:
            value: Any = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SavePackError(
                "The save-assignment file is not valid UTF-8 JSON."
            ) from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"schemaVersion", "assignments"}
            or value["schemaVersion"] != 1
            or isinstance(value["schemaVersion"], bool)
            or not isinstance(value["assignments"], dict)
            or len(value["assignments"]) > _MAX_ASSIGNMENTS
        ):
            raise SavePackError(
                "The save-assignment file has an unsupported structure."
            )
        assignments: dict[str, str] = {}
        try:
            for key, name in value["assignments"].items():
                validated_key = _validate_key(key)
                _validate_pack_name(name)
                if validated_key != key or validated_key in assignments:
                    raise SavePackError(
                        "The save-assignment file contains duplicate keys."
                    )
                assignments[validated_key] = name
        except (TypeError, ProfileError) as exc:
            raise SavePackError(
                f"The save-assignment file contains invalid data: {exc}"
            ) from exc
        return assignments

    def _write(self, assignments: dict[str, str]) -> None:
        if len(assignments) > _MAX_ASSIGNMENTS:
            raise SavePackError("There are too many save-to-pack groupings.")
        value = {
            "schemaVersion": 1,
            "assignments": dict(sorted(assignments.items())),
        }
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and _is_link_or_junction(self.path):
            raise SavePackError("The app-owned save-assignment file is a link.")
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.root
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _validate_key(key: str) -> str:
    if not isinstance(key, str) or key.count("/") != 1:
        raise SavePackError("A save reference must contain one mode and one save name.")
    mode, name = key.split("/", 1)
    normalized = save_key(mode, name)
    if normalized != key:
        raise SavePackError("Save references must use normalized folder names.")
    return key


def _validate_pack_name(name: str) -> None:
    if not isinstance(name, str):
        raise SavePackError("A Mod Pack name must be text.")
    try:
        validate_profile(ModProfile(name, ()))
    except ProfileError as exc:
        raise SavePackError(f"The Mod Pack name is invalid: {exc}") from exc
