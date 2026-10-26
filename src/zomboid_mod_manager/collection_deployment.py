"""Prepare shared collection content in PZ's supported local mod directory.

Only explicitly recorded app-owned directories move. Replaced copies are archived
beside the mod root on the same volume; user mods and cached objects are untouched.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .collection_store import (
    CollectionStore,
    CollectionStoreError,
    check_cancelled,
    copy_verified_tree,
    require_plain_path,
    tree_digest,
)
from .discovery.scanner import merge_scan_results, scan_mods
from .domain import ScanResult
from .profiles import ModProfile, parse_profile, serialize_profile

_FOLDER = re.compile(r"ZomboidSorter_[0-9a-f]{64}$")


def _write(path: Path, data: bytes) -> None:
    require_plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if path.read_bytes() != data:
        raise CollectionStoreError("Collection deployment state could not be verified.")


class CollectionDeployment:
    def __init__(self, local_root: Path) -> None:
        self.local_root = local_root
        if (
            local_root.name.lower() != "mods"
            or local_root.parent.name.lower() != "zomboid"
        ):
            raise CollectionStoreError(
                "Collection loading supports only the global Zomboid/mods folder."
            )
        require_plain_path(local_root)
        self.root = local_root.parent / ".zomboidsorter-collections"
        self.index = self.root / "active.json"

    def read(self) -> tuple[dict, bytes | None]:
        require_plain_path(self.index)
        if not self.index.exists():
            return {"folders": [], "profile": None}, None
        try:
            with self.index.open("rb") as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("too large")
            value = json.loads(raw)
            if (
                value.get("schema") != 1
                or value.get("localRoot") != str(self.local_root.absolute())
                or not isinstance(value.get("folders"), list)
            ):
                raise ValueError("unexpected state")
            names = set()
            for item in value["folders"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"name", "sha256"}
                    or not isinstance(item["name"], str)
                    or not _FOLDER.fullmatch(item["name"])
                    or item["name"] != "ZomboidSorter_" + item["sha256"]
                    or item["name"] in names
                ):
                    raise ValueError("unsafe folder")
                names.add(item["name"])
            parse_profile(json.dumps(value["profile"]).encode())
            return value, raw
        except (ValueError, KeyError, TypeError) as exc:
            raise CollectionStoreError(
                "The app-owned collection deployment record is invalid. No mod folders were changed."
            ) from exc

    def loaded_profile(self) -> ModProfile | None:
        state, raw = self.read()
        return (
            parse_profile(json.dumps(state["profile"]).encode())
            if raw is not None
            else None
        )

    def prepare(
        self,
        store: CollectionStore,
        profile: ModProfile,
        *,
        cancelled=None,
        progress=None,
    ):
        old, old_bytes = self.read()
        old_names = {x["name"] for x in old["folders"]}
        cache_scan = store.scan(profile, cancelled=cancelled, progress=progress)
        sources = {}
        mod_sources = {}
        entry_digests = {}
        for number, entry in enumerate(cache_scan.entries, 1):
            if progress:
                progress(
                    f"Checking collection mod folder {number}/{len(cache_scan.entries)}: {entry.mod_id}"
                )
            if not entry.mod_id:
                raise CollectionStoreError(
                    "The collection contains unreadable mod metadata."
                )
            if entry.entry_path not in entry_digests:
                entry_digests[entry.entry_path] = tree_digest(
                    entry.entry_path, cancelled=cancelled
                )
            digest = entry_digests[entry.entry_path]
            if entry.mod_id in mod_sources and mod_sources[entry.mod_id] != digest:
                raise CollectionStoreError(
                    f"Collection contains different copies of Mod ID '{entry.mod_id}'. Resolve the duplicate before loading."
                )
            mod_sources[entry.mod_id] = digest
            sources[digest] = entry.entry_path
        transaction_root = self.root / "transactions" / uuid.uuid4().hex
        require_plain_path(transaction_root)
        prepared = transaction_root / "prepared"
        prepared.mkdir(parents=True)
        records = []
        for number, (digest, source) in enumerate(sources.items(), 1):
            check_cancelled(cancelled)
            if progress:
                progress(f"Preparing collection mod folders: {number}/{len(sources)}")
            name = "ZomboidSorter_" + digest
            target = self.local_root / name
            if target.exists() and name not in old_names:
                raise CollectionStoreError(
                    "An unowned folder occupies the collection destination. No user files were replaced."
                )
            # Reuse only exact folders listed in the prior ownership record. All
            # prior folders, including these retained copies, are fully hashed
            # at activation before any move. Cache objects are verified above.
            if name not in old_names:
                copy_verified_tree(
                    source, prepared / name, cancelled=cancelled, expected_digest=digest
                )
            records.append({"name": name, "sha256": digest})
        new_state = {
            "schema": 1,
            "localRoot": str(self.local_root.absolute()),
            "folders": records,
            "profile": json.loads(serialize_profile(profile)),
        }
        new_bytes = json.dumps(new_state, indent=2).encode()
        _write(
            transaction_root / "journal.json",
            json.dumps({"status": "prepared", "old": old, "new": new_state}).encode(),
        )
        return PreparedDeployment(
            self, transaction_root, old, old_bytes, new_state, new_bytes
        )


@dataclass
class PreparedDeployment:
    owner: CollectionDeployment
    root: Path
    old: dict
    old_bytes: bytes | None
    new: dict
    new_bytes: bytes
    activated: bool = False

    @property
    def retained_names(self) -> set[str]:
        """Ownership-recorded folders shared by both deployments."""
        return {record["name"] for record in self.old["folders"]} & {
            record["name"] for record in self.new["folders"]
        }

    def activate(self, *, cancelled=None, progress=None) -> None:
        owner = self.owner
        # Check immediately before commit: retained folders must still contain
        # their exact bytes, even if changed after preparation finished.
        for number, record in enumerate(self.old["folders"], 1):
            if progress:
                progress(
                    f"Checking previously loaded mod folders: {number}/{len(self.old['folders'])}"
                )
            if (
                tree_digest(owner.local_root / record["name"], cancelled=cancelled)
                != record["sha256"]
            ):
                raise CollectionStoreError(
                    "An app-deployed mod was changed outside the app. Its files were preserved; resolve the change before switching packs."
                )
        check_cancelled(cancelled)
        _, current = owner.read()
        if current != self.old_bytes:
            raise CollectionStoreError(
                "Another operation changed the loaded collection. Retry loading the pack."
            )
        backup = self.root / "previous"
        backup.mkdir()
        moved_old = []
        moved_new = []
        retained = self.retained_names
        owner.local_root.mkdir(parents=True, exist_ok=True)
        try:
            for record in self.old["folders"]:
                path = owner.local_root / record["name"]
                require_plain_path(path)
                if record["name"] in retained:
                    continue
                os.rename(path, backup / record["name"])
                moved_old.append(record["name"])
            for record in self.new["folders"]:
                target = owner.local_root / record["name"]
                require_plain_path(target)
                if record["name"] in retained:
                    continue
                if target.exists():
                    raise CollectionStoreError(
                        "A mod folder appeared during collection activation."
                    )
                os.rename(self.root / "prepared" / record["name"], target)
                moved_new.append(record["name"])
            _write(owner.index, self.new_bytes)
            self.activated = True
        except Exception:
            for name in reversed(moved_new):
                os.rename(owner.local_root / name, self.root / "prepared" / name)
            for name in reversed(moved_old):
                os.rename(backup / name, owner.local_root / name)
            if self.old_bytes is not None:
                _write(owner.index, self.old_bytes)
            raise

    def rollback(self) -> None:
        if not self.activated:
            return
        owner = self.owner
        _, raw = owner.read()
        if raw != self.new_bytes:
            raise CollectionStoreError(
                f"Collection state changed; recovery copies remain at {self.root}"
            )
        retained = self.retained_names
        for record in self.new["folders"]:
            if tree_digest(owner.local_root / record["name"]) != record["sha256"]:
                raise CollectionStoreError(
                    f"Deployed content changed; recovery copies remain at {self.root}"
                )
        for record in self.new["folders"]:
            if record["name"] in retained:
                continue
            os.rename(
                owner.local_root / record["name"],
                self.root / "prepared" / record["name"],
            )
        for record in self.old["folders"]:
            if record["name"] in retained:
                continue
            target = owner.local_root / record["name"]
            if target.exists():
                raise CollectionStoreError(
                    f"Recovery destination is occupied; backups remain at {self.root}"
                )
            os.rename(self.root / "previous" / record["name"], target)
        # Keep an explicit empty state on first-import rollback, never delete data.
        empty = {
            "schema": 1,
            "localRoot": str(owner.local_root.absolute()),
            "folders": [],
            "profile": json.loads(
                serialize_profile(ModProfile("No collection loaded", ()))
            ),
        }
        _write(
            owner.index,
            self.old_bytes
            if self.old_bytes is not None
            else json.dumps(empty).encode(),
        )
        self.activated = False


def load_collection(
    store,
    profile,
    local_root,
    local_roots,
    previous_scan: ScanResult | None = None,
    *,
    cancelled=None,
    progress=None,
):
    check_cancelled(cancelled)
    deployment = CollectionDeployment(local_root)
    roots = list(dict.fromkeys([local_root, *local_roots]))
    if progress:
        progress("Verifying the saved collection content…")
    prepared = deployment.prepare(
        store, profile, cancelled=cancelled, progress=progress
    )
    check_cancelled(cancelled)
    prepared.activate(cancelled=cancelled, progress=progress)
    try:
        local_scan = scan_mods(
            local_roots=roots,
            cancelled=cancelled,
            progress=progress,
        )
        result = merge_scan_results(
            local_scan,
            previous_scan,
        )
        check_cancelled(cancelled)
    except Exception:
        prepared.rollback()
        raise
    return prepared, result
