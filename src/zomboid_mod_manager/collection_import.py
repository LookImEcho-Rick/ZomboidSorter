"""Import a Workshop collection into the shared private content store."""

from __future__ import annotations

from .collection_store import CollectionStore, CollectionStoreError, check_cancelled
from .profiles import ModProfile
from .steamcmd import SteamCmdDownloader
from .workshop import WorkshopCollectionResult, resolve_collection_import


def download_collection(
    collection: WorkshopCollectionResult,
    name: str,
    store: CollectionStore,
    downloader: SteamCmdDownloader,
    *,
    cancelled=None,
    progress=None,
) -> ModProfile:
    if collection.unavailable_ids or not collection.items:
        raise CollectionStoreError(
            "A complete collection cannot be imported while items are unavailable."
        )
    content = []
    total = len(collection.items)
    for index, item in enumerate(collection.items, 1):
        check_cancelled(cancelled)
        if progress:
            progress(f"Item {index}/{total}: {item.title}")
        source = downloader.download(item, cancelled=cancelled, progress=progress)
        content.append(store.intern(source, item.workshop_id, cancelled=cancelled))
        if progress:
            progress(
                f"Cached {index}/{total} items; matching content is shared across packs."
            )
    references = tuple(content)
    workshop_ids = tuple(item.workshop_id for item in collection.items)
    draft = ModProfile(name, (), workshop_ids, None, references)
    scan = store.scan(draft, cancelled=cancelled)
    plan = resolve_collection_import(collection, scan)
    if plan.missing_ids or plan.ambiguous_mod_ids or not plan.mod_ids:
        raise CollectionStoreError(
            "Downloaded content contains missing or duplicate Mod IDs. Cached files were preserved, but no complete pack was saved."
        )
    if any(
        not item.entries or any(not entry.mod_id for entry in item.entries)
        for item in scan.workshop_items
    ):
        raise CollectionStoreError(
            "Some downloaded items have no readable Mod IDs. No complete pack was saved."
        )
    return ModProfile(name, plan.mod_ids, workshop_ids, None, references)
