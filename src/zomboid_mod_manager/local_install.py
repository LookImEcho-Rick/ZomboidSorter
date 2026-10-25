"""Install a downloaded Workshop item's entries as persistent local mods."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from .collection_store import (
    CollectionStoreError,
    check_cancelled,
    copy_verified_tree,
    require_plain_path,
    tree_digest,
)
from .discovery.scanner import scan_mods, scan_workshop_item
from .workshop import PZ_APP_ID, fetch_item_metadata, parse_published_file_id


def install_local_mod(
    workshop_id,
    local_root,
    downloader,
    *,
    local_roots=(),
    workshop_roots=(),
    cancelled=None,
    progress=None,
):
    """Prepare outside discovery, then rename complete entries without overwrites.

    Never register these folders as temporary collection deployments. Failed or
    cancelled preparation/recovery is retained outside the scanned root.
    """
    workshop_id = parse_published_file_id(workshop_id)
    local_root = Path(local_root).expanduser().absolute()
    require_plain_path(local_root)
    if not local_root.is_dir() or (local_root / "mod.info").exists():
        raise CollectionStoreError(
            "Choose an existing local mods folder in Paths & Settings."
        )
    check_cancelled(cancelled)
    if progress:
        progress("Checking Workshop item and downloading through SteamCMD…")
    metadata = fetch_item_metadata(workshop_id, timeout=15)
    if metadata.consumer_app_id != PZ_APP_ID:
        raise CollectionStoreError(
            "The download could not be verified as a Project Zomboid item."
        )
    source = downloader.download(metadata, cancelled=cancelled, progress=progress)
    item = scan_workshop_item(source, workshop_id, cancelled=cancelled)
    if not item.entries or any(not entry.mod_id for entry in item.entries):
        raise CollectionStoreError(
            "The download has no complete, readable Mod IDs. Nothing was installed."
        )
    ids = [entry.mod_id for entry in item.entries]
    if len(ids) != len(set(ids)):
        raise CollectionStoreError(
            "This item contains duplicate Mod IDs. Nothing was installed."
        )
    paths = sorted(
        {entry.entry_path for entry in item.entries}, key=lambda p: str(p).casefold()
    )
    targets = {
        path: local_root / f"WorkshopLocal_{workshop_id}_{index}"
        for index, path in enumerate(paths, 1)
    }
    installed = scan_mods(
        local_roots=list(dict.fromkeys([local_root, *local_roots])),
        workshop_roots=workshop_roots,
        cancelled=cancelled,
    )
    for entry in installed.entries:
        if entry.mod_id in ids:
            matching = [e for e in item.entries if e.mod_id == entry.mod_id]
            expected = targets[matching[0].entry_path]
            if entry.entry_path != expected:
                raise CollectionStoreError(
                    f"Mod ID '{entry.mod_id}' is already installed at {entry.entry_path}. Existing mods were preserved."
                )
    pending = []
    for path, target in targets.items():
        require_plain_path(target)
        if target.exists():
            if tree_digest(path, cancelled=cancelled) != tree_digest(
                target, cancelled=cancelled
            ):
                raise CollectionStoreError(
                    f"An existing folder differs: {target}. Nothing was overwritten."
                )
        else:
            pending.append((path, target))
    if not pending:
        return tuple(targets.values())
    staging = local_root.parent / f".zomboidsorter-local-install-{uuid.uuid4().hex}"
    require_plain_path(staging)
    staging.mkdir()
    prepared = []
    for path, target in pending:
        if progress:
            progress(f"Preparing {target.name}…")
        temporary = staging / target.name
        digest = copy_verified_tree(path, temporary, cancelled=cancelled)
        prepared.append((temporary, target, digest))
    check_cancelled(cancelled)
    moved = []
    try:
        for temporary, target, digest in prepared:
            check_cancelled(cancelled)
            require_plain_path(local_root)
            require_plain_path(target)
            # Windows rename fails if the target already exists.
            if target.exists():
                raise CollectionStoreError(
                    f"Installation destination became occupied: {target}"
                )
            os.rename(temporary, target)
            moved.append((temporary, target, digest))
        check_cancelled(cancelled)
    except Exception:
        for temporary, target, digest in reversed(moved):
            require_plain_path(target)
            if tree_digest(target) != digest:
                raise CollectionStoreError(
                    f"Installed files changed during recovery. Inspect {target} and {staging}."
                ) from None
            os.rename(target, temporary)
        raise
    return tuple(targets.values())
