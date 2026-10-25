"""Public collection discovery from Steam's server-rendered browse data.

No account, API key, browser automation, or third-party scraping service is used.
Steam's website format is not a stable API: fail visibly if its shape changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .workshop import PZ_APP_ID, WorkshopApiError, parse_published_file_id

COLLECTION_SORTS = {
    "Popular this week": "trend",
    "Top rated": "toprated",
    "Newest": "mostrecent",
    "Recently updated": "lastupdated",
}
MAX_BROWSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class CollectionSummary:
    workshop_id: str
    title: str
    author: str
    description: str
    item_count: int
    favorites: int
    updated_at: int
    tags: tuple[str, ...]
    subscribers: int | None = None


@dataclass(frozen=True)
class CollectionPage:
    collections: tuple[CollectionSummary, ...]
    page: int
    total_pages: int
    total_count: int


class _SteamDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.reading = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "script" and dict(attrs).get("id") == "valve-ssr-data":
            self.reading = True

    def handle_endtag(self, tag) -> None:
        if tag == "script":
            self.reading = False

    def handle_data(self, data) -> None:
        if self.reading:
            self.parts.append(data)


def _integer(value: object) -> int:
    try:
        return max(0, int(value))
    except ValueError, TypeError:
        return 0


def parse_collection_page(
    html: str, *, page: int = 1, mods: bool = False
) -> CollectionPage:
    parser = _SteamDataParser()
    parser.feed(html)
    try:
        payload = json.loads("".join(parser.parts))
        queries = payload["renderContext"]["queryData"]
        if isinstance(queries, str):
            queries = json.loads(queries)
        queries = queries["queries"]
        browse = next(
            q["state"]["data"]
            for q in queries
            if q.get("queryKey", [None])[0] == "workshop_browse"
            and q["queryKey"][1].get("appid") == PZ_APP_ID
            and q["queryKey"][1].get("section")
            == ("readytouseitems" if mods else "collections")
        )
        if browse.get("eresult") != 1 or not isinstance(browse["results"], list):
            raise ValueError("unsuccessful browse")
        authors = {}
        for q in queries:
            key = q.get("queryKey", [])
            if len(key) > 1 and key[0] == "PlayerLinkDetails":
                public = q["state"]["data"].get("public_data", {})
                authors[key[1]] = public.get("persona_name", "")
        rows = []
        seen = set()
        for item in browse["results"]:
            if item.get("consumer_appid") != PZ_APP_ID or item.get("file_type") != (
                0 if mods else 2
            ):
                continue
            item_id = parse_published_file_id(str(item["publishedfileid"]))
            if item_id in seen:
                continue
            seen.add(item_id)
            rows.append(
                CollectionSummary(
                    item_id,
                    str(item.get("title") or item_id),
                    str(authors.get(item.get("creator")) or "Unknown creator"),
                    str(item.get("short_description") or ""),
                    _integer(item.get("num_children")),
                    _integer(item.get("favorited")),
                    _integer(item.get("time_updated")),
                    tuple(
                        str(tag["tag"])
                        for tag in item.get("tags", [])
                        if isinstance(tag, dict) and tag.get("tag")
                    ),
                    _integer(item["subscriptions"])
                    if "subscriptions" in item
                    else None,
                )
            )
        return CollectionPage(
            tuple(rows),
            page,
            max(1, min(1000, _integer(browse.get("total_pages")))),
            _integer(browse.get("total_count")),
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        StopIteration,
        AttributeError,
    ) as exc:
        raise WorkshopApiError(
            "Steam's Workshop catalog could not be read. Try again later."
        ) from exc


def browse_collections(
    search: str = "",
    *,
    sort: str = "trend",
    page: int = 1,
    build: str = "",
    timeout: float = 15.0,
    mods: bool = False,
) -> CollectionPage:
    if sort not in COLLECTION_SORTS.values() or not 1 <= page <= 1000:
        raise ValueError("Invalid collection sort or page.")
    if build not in {"", "Build 41", "Build 42"}:
        raise ValueError("Invalid collection build tag.")
    params = {
        "appid": str(PZ_APP_ID),
        "section": "readytouseitems" if mods else "collections",
        "browsesort": sort,
        "actualsort": sort,
        "p": str(page),
        "searchtext": search.strip()[:200],
        "l": "english",
    }
    if build:
        params["requiredtags[]"] = build
    request = Request(
        "https://steamcommunity.com/workshop/browse/?" + urlencode(params),
        headers={"User-Agent": "ZomboidSorter/collection-browser"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BROWSE_BYTES + 1)
        if len(raw) > MAX_BROWSE_BYTES:
            raise WorkshopApiError("Steam's catalog exceeded the 8 MiB response limit.")
        return parse_collection_page(raw.decode("utf-8"), page=page, mods=mods)
    except (OSError, UnicodeError) as exc:
        raise WorkshopApiError(f"Could not load Steam Workshop catalog: {exc}") from exc
