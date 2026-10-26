"""Import a Workshop collection into the shared private content store."""

from __future__ import annotations

from collections import defaultdict

from .collection_store import CollectionStore, CollectionStoreError, check_cancelled
from .discovery.scanner import scan_workshop_item
from .domain import ScanResult
from .profiles import ModProfile
from .steamcmd import SteamCmdDownloader
from .workshop import (
    WorkshopCollectionResult,
    resolve_collection_import,
)


class CollectionModIdConflict(CollectionStoreError):
    """Downloaded collection entries reuse Mod IDs and require a user choice."""

    def __init__(self, duplicate_sources, references, scan_result) -> None:
        self.duplicate_sources = duplicate_sources
        self.references = references
        self.scan_result = scan_result
        conflicts = ", ".join(
            f"{mod_id} ({len(workshop_ids)} Workshop item(s))"
            for mod_id, workshop_ids in duplicate_sources.items()
        )
        super().__init__(
            f"Downloaded content has duplicate Mod IDs: {conflicts}. Choose which Workshop items to keep before saving the Mod Pack."
        )


def _duplicate_sources(scan_result: ScanResult, mod_ids: tuple[str, ...]):
    ambiguous = set(mod_ids)
    sources = defaultdict(set)
    for item in scan_result.workshop_items:
        for entry in item.entries:
            if entry.mod_id in ambiguous:
                sources[entry.mod_id].add(item.workshop_id)
    return {
        mod_id: tuple(sorted(workshop_ids))
        for mod_id, workshop_ids in sorted(sources.items())
    }


def profile_from_cached_collection(
    collection: WorkshopCollectionResult,
    name: str,
    references,
    scan_result: ScanResult,
    *,
    excluded_workshop_ids=(),
) -> ModProfile:
    """Create a pack from verified cache scan results after duplicate choices."""
    excluded = set(excluded_workshop_ids)
    selected_items = tuple(
        item for item in collection.items if item.workshop_id not in excluded
    )
    if not selected_items:
        raise CollectionStoreError(
            "No Workshop items remain selected for this Mod Pack."
        )
    selected_ids = {item.workshop_id for item in selected_items}
    selected_scan = ScanResult(
        (),
        tuple(
            item
            for item in scan_result.workshop_items
            if item.workshop_id in selected_ids
        ),
        scan_result.diagnostics,
    )
    selected_collection = WorkshopCollectionResult(
        collection.collection_id,
        selected_items,
        (),
        (),
    )
    plan = resolve_collection_import(selected_collection, selected_scan)
    scanned_by_id = {item.workshop_id: item for item in selected_scan.workshop_items}
    unreadable = []
    for metadata in selected_items:
        item = scanned_by_id.get(metadata.workshop_id)
        if (
            item is None
            or not item.entries
            or any(not entry.mod_id for entry in item.entries)
        ):
            unreadable.append(f"{metadata.title} (Workshop ID {metadata.workshop_id})")
    if unreadable:
        preview = "; ".join(unreadable[:8])
        remaining = f"; and {len(unreadable) - 8} more" if len(unreadable) > 8 else ""
        raise CollectionStoreError(
            f"No readable Mod IDs for: {preview}{remaining}. "
            "Open these Workshop pages to check that they contain Project Zomboid mods with valid mod.info files. "
            "Retry after the content is corrected. Cached files were preserved; no pack was saved."
        )
    if plan.ambiguous_mod_ids:
        raise CollectionModIdConflict(
            _duplicate_sources(selected_scan, plan.ambiguous_mod_ids),
            references,
            scan_result,
        )
    if plan.missing_ids or not plan.mod_ids:
        raise CollectionStoreError(
            "Some selected Workshop items have no readable Mod IDs. Cached files were preserved, but no complete pack was saved."
        )
    reference_by_id = {item.workshop_id: item for item in references}
    try:
        selected_references = tuple(
            reference_by_id[item.workshop_id] for item in selected_items
        )
    except KeyError as exc:
        raise CollectionStoreError(
            "Verified cached content is missing for a selected Workshop item. Retry the import."
        ) from exc
    workshop_ids = tuple(item.workshop_id for item in selected_items)
    return ModProfile(name, plan.mod_ids, workshop_ids, None, selected_references)


def download_collection(
    collection: WorkshopCollectionResult,
    name: str,
    store: CollectionStore,
    downloader: SteamCmdDownloader,
    *,
    cancelled=None,
    progress=None,
    item_cached=None,
) -> ModProfile:
    if collection.unavailable_ids or not collection.items:
        raise CollectionStoreError(
            "A complete collection cannot be imported while items are unavailable."
        )
    content_by_id = {}
    scanned_by_id = {}
    total = len(collection.items)

    def cache_item(item, source) -> None:
        check_cancelled(cancelled)
        if progress:
            progress(
                f"Verifying and caching item {len(content_by_id) + 1}/{total}: {item.title}"
            )
        reference = store.intern(
            source,
            item.workshop_id,
            cancelled=cancelled,
        )
        content_by_id[item.workshop_id] = reference
        scanned_by_id[item.workshop_id] = scan_workshop_item(
            store.path(reference), item.workshop_id, cancelled=cancelled
        )
        if item_cached:
            item_cached(scanned_by_id[item.workshop_id])
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
    check_cancelled(cancelled)
    references = tuple(content_by_id[item.workshop_id] for item in collection.items)
    if progress:
        progress("Checking downloaded Mod IDs and preparing the saved Mod Pack…")
    # intern() verifies that this exact cache object matches the SteamCMD source.
    # Its metadata was scanned without re-hashing all cached file bytes; loading
    # a saved pack re-hashes the shared cache before local mod files are prepared.
    scan = ScanResult(
        (),
        tuple(scanned_by_id[item.workshop_id] for item in collection.items),
        (),
    )
    return profile_from_cached_collection(collection, name, references, scan)
