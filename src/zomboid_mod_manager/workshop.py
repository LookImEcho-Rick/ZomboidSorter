"""Read-only Steam Workshop links, collection imports, and public metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from zomboid_mod_manager.domain import ScanResult

PZ_APP_ID = 108600
_STEAM_COMMUNITY_HOSTS = {"steamcommunity.com", "www.steamcommunity.com"}
_NUMERIC_ID = re.compile(r"^\d{1,20}$")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_COLLECTION_ITEMS = 2000


class WorkshopApiError(RuntimeError):
    """Steam returned an unusable response or could not be reached."""


@dataclass(frozen=True)
class WorkshopItemMetadata:
    workshop_id: str
    title: str
    description: str
    consumer_app_id: int | None
    updated_at: int | None


@dataclass(frozen=True)
class WorkshopCollectionResult:
    collection_id: str
    items: tuple[WorkshopItemMetadata, ...]
    unavailable_ids: tuple[str, ...] = ()
    foreign_app_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkshopImportPlan:
    workshop_ids: tuple[str, ...]
    installed_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    mod_ids: tuple[str, ...]
    ambiguous_mod_ids: tuple[str, ...]


def parse_published_file_id(value: str) -> str:
    """Accept a decimal ID or a Steam Community shared-file URL."""
    candidate = value.strip()
    if _NUMERIC_ID.fullmatch(candidate):
        return candidate
    parsed = urlparse(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in _STEAM_COMMUNITY_HOSTS
        or parsed.path.rstrip("/") != "/sharedfiles/filedetails"
    ):
        raise ValueError(
            "Enter a numeric Workshop ID or a Steam Community shared-file URL."
        )
    values = parse_qs(parsed.query, keep_blank_values=True).get("id", [])
    if len(values) != 1 or not _NUMERIC_ID.fullmatch(values[0]):
        raise ValueError(
            "The Steam URL must contain exactly one numeric 'id' parameter."
        )
    return values[0]


def _post_json(url: str, fields: dict[str, str], *, timeout: float) -> dict:
    body = urlencode(fields).encode("ascii")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ProjectZomboidModManager/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise WorkshopApiError(f"Steam Workshop request failed: {exc}") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise WorkshopApiError(
            "Steam Workshop response exceeded the 4 MiB safety limit."
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkshopApiError("Steam Workshop returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise WorkshopApiError("Steam Workshop returned an unexpected response shape.")
    return data


def _response_object(data: dict) -> dict:
    response = data.get("response")
    if not isinstance(response, dict):
        raise WorkshopApiError(
            "Steam Workshop response is missing its response object."
        )
    return response


def _numeric_response_id(value: object) -> str | None:
    text = str(value or "")
    return text if _NUMERIC_ID.fullmatch(text) else None


def fetch_collection(
    collection: str,
    *,
    timeout: float = 10.0,
    max_items: int = _MAX_COLLECTION_ITEMS,
) -> WorkshopCollectionResult:
    """Fetch public collection children and PZ item metadata without subscribing.

    Steam documents these public endpoints without a client API key. Requests
    are read-only and contain no account credentials or subscription actions.
    """
    collection_id = parse_published_file_id(collection)
    collection_data = _post_json(
        "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/",
        {"collectioncount": "1", "publishedfileids[0]": collection_id},
        timeout=timeout,
    )
    response = _response_object(collection_data)
    details = response.get("collectiondetails")
    if not isinstance(details, list) or not details:
        raise WorkshopApiError("Steam did not return details for this collection.")
    collection_info = next(
        (
            detail
            for detail in details
            if isinstance(detail, dict)
            and _numeric_response_id(detail.get("publishedfileid")) == collection_id
        ),
        None,
    )
    if collection_info is None or collection_info.get("result") != 1:
        raise WorkshopApiError(
            "This Workshop collection is unavailable or not publicly readable."
        )
    children = collection_info.get("children", [])
    if not isinstance(children, list):
        raise WorkshopApiError("Steam returned an invalid collection item list.")

    ordered_ids: list[str] = []
    child_ids: list[tuple[int, str]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        item_id = _numeric_response_id(child.get("publishedfileid"))
        if item_id is None or item_id == collection_id:
            continue
        try:
            order = int(child.get("sortorder", len(child_ids)))
        except TypeError, ValueError:
            order = len(child_ids)
        child_ids.append((order, item_id))
    for _order, item_id in sorted(child_ids):
        if item_id not in ordered_ids:
            ordered_ids.append(item_id)
    if len(ordered_ids) > max_items:
        raise WorkshopApiError(
            f"Collection has {len(ordered_ids)} items; limit is {max_items}."
        )

    metadata: dict[str, dict] = {}
    for offset in range(0, len(ordered_ids), 100):
        batch = ordered_ids[offset : offset + 100]
        fields = {"itemcount": str(len(batch))}
        fields.update(
            {
                f"publishedfileids[{index}]": item_id
                for index, item_id in enumerate(batch)
            }
        )
        result = _post_json(
            "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
            fields,
            timeout=timeout,
        )
        item_details = _response_object(result).get("publishedfiledetails")
        if not isinstance(item_details, list):
            raise WorkshopApiError("Steam returned invalid published-file details.")
        for item in item_details:
            if isinstance(item, dict):
                item_id = _numeric_response_id(item.get("publishedfileid"))
                if item_id:
                    metadata[item_id] = item

    items: list[WorkshopItemMetadata] = []
    unavailable: list[str] = []
    foreign: list[str] = []
    for item_id in ordered_ids:
        item = metadata.get(item_id)
        if item is None or item.get("result") != 1:
            unavailable.append(item_id)
            continue
        try:
            consumer_app_id = int(item.get("consumer_appid"))
        except TypeError, ValueError:
            consumer_app_id = None
        if consumer_app_id != PZ_APP_ID:
            foreign.append(item_id)
            continue
        try:
            updated_at = int(item.get("time_updated"))
        except TypeError, ValueError:
            updated_at = None
        items.append(
            WorkshopItemMetadata(
                workshop_id=item_id,
                title=str(item.get("title") or item_id),
                description=str(item.get("description") or ""),
                consumer_app_id=consumer_app_id,
                updated_at=updated_at,
            )
        )

    return WorkshopCollectionResult(
        collection_id=collection_id,
        items=tuple(items),
        unavailable_ids=tuple(unavailable),
        foreign_app_ids=tuple(foreign),
    )


def fetch_item_metadata(
    workshop_item: str, *, timeout: float = 5.0
) -> WorkshopItemMetadata:
    """Fetch one public Workshop item's title and full description read-only."""
    item_id = parse_published_file_id(workshop_item)
    data = _post_json(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
        {"itemcount": "1", "publishedfileids[0]": item_id},
        timeout=timeout,
    )
    details = _response_object(data).get("publishedfiledetails")
    if not isinstance(details, list):
        raise WorkshopApiError("Steam returned invalid published-file details.")
    item = next(
        (
            detail
            for detail in details
            if isinstance(detail, dict)
            and _numeric_response_id(detail.get("publishedfileid")) == item_id
        ),
        None,
    )
    if item is None or item.get("result") != 1:
        raise WorkshopApiError("This Workshop item is unavailable or not public.")
    try:
        consumer_app_id = int(item.get("consumer_appid"))
    except TypeError, ValueError:
        consumer_app_id = None
    if consumer_app_id is not None and consumer_app_id != PZ_APP_ID:
        raise WorkshopApiError("This Workshop item is not for Project Zomboid.")
    try:
        updated_at = int(item.get("time_updated"))
    except TypeError, ValueError:
        updated_at = None
    return WorkshopItemMetadata(
        workshop_id=item_id,
        title=str(item.get("title") or item_id),
        description=str(item.get("description") or ""),
        consumer_app_id=consumer_app_id,
        updated_at=updated_at,
    )


def resolve_collection_import(
    collection: WorkshopCollectionResult, scan_result: ScanResult
) -> WorkshopImportPlan:
    """Map collection items to unique installed Mod IDs without downloading."""
    installed_items = {item.workshop_id: item for item in scan_result.workshop_items}
    entries_by_id: dict[str, int] = {}
    for entry in scan_result.entries:
        if entry.mod_id:
            entries_by_id[entry.mod_id] = entries_by_id.get(entry.mod_id, 0) + 1

    installed_ids: list[str] = []
    missing_ids = list(collection.unavailable_ids)
    mod_ids: list[str] = []
    ambiguous: set[str] = set()
    for metadata in collection.items:
        item = installed_items.get(metadata.workshop_id)
        if item is None:
            missing_ids.append(metadata.workshop_id)
            continue
        installed_ids.append(metadata.workshop_id)
        for entry in item.entries:
            if not entry.mod_id:
                continue
            if entries_by_id.get(entry.mod_id, 0) != 1:
                ambiguous.add(entry.mod_id)
                continue
            if entry.mod_id not in mod_ids:
                mod_ids.append(entry.mod_id)

    workshop_ids = tuple(
        dict.fromkeys(
            [metadata.workshop_id for metadata in collection.items]
            + list(collection.unavailable_ids)
        )
    )
    return WorkshopImportPlan(
        workshop_ids=workshop_ids,
        installed_ids=tuple(installed_ids),
        missing_ids=tuple(dict.fromkeys(missing_ids)),
        mod_ids=tuple(mod_ids),
        ambiguous_mod_ids=tuple(sorted(ambiguous, key=str.casefold)),
    )
