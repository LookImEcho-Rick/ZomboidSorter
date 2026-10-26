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
    content_by_id = {}
    total = len(collection.items)

    def cache_item(item, source) -> None:
        check_cancelled(cancelled)
        content_by_id[item.workshop_id] = store.intern(
            source, item.workshop_id, cancelled=cancelled
        )
        if progress:
            progress(
                f"Cached {len(content_by_id)}/{total} items; matching content is shared across packs."
            )

    # The production downloader batches items into fewer SteamCMD sessions. Keep
    # the one-item protocol for simple injected downloaders and existing callers.
    if callable(getattr(type(downloader), "download_many", None)):
        downloader.download_many(
            collection.items,
            cancelled=cancelled,
            progress=progress,
            on_downloaded=cache_item,
        )
    else:
        for index, item in enumerate(collection.items, 1):
            check_cancelled(cancelled)
            if progress:
                progress(f"Downloading item {index}/{total}: {item.title}")
            cache_item(
                item,
                downloader.download(item, cancelled=cancelled, progress=progress),
            )

    if len(content_by_id) != total:
        raise CollectionStoreError(
            "SteamCMD did not finish every collection item. Completed cached content was preserved; retry the import."
        )
    references = tuple(content_by_id[item.workshop_id] for item in collection.items)
    workshop_ids = tuple(item.workshop_id for item in collection.items)
    draft = ModProfile(name, (), workshop_ids, None, references)
    if progress:
        progress("Checking downloaded Mod IDs and preparing the saved Mod Pack…")
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
