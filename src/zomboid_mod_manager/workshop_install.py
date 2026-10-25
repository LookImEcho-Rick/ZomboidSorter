"""Read-only installation evidence for a collection downloaded by Steam."""

from __future__ import annotations

import re
from pathlib import Path

from .workshop import WorkshopCollectionResult


def _manifest_data(path: Path) -> dict:
    # Steam owns this file. Never write it or infer completion from a directory alone.
    try:
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            return {}
        with path.open("r", encoding="utf-8") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            return {}
        tokens = re.findall(r'"([^"\r\n]*)"|([{}])', raw)
        stack = [{}]
        key = None
        for text, brace in tokens:
            if brace == "{":
                if key is None or len(stack) >= 16:
                    return {}
                child = {}
                stack[-1][key] = child
                stack.append(child)
                key = None
            elif brace == "}":
                if key is not None or len(stack) == 1:
                    return {}
                stack.pop()
            elif key is None:
                key = text
            else:
                stack[-1][key] = text
                key = None
        data = (
            stack[0].get("AppWorkshop", {}) if len(stack) == 1 and key is None else {}
        )
        return data if isinstance(data, dict) else {}
    except OSError, UnicodeError:
        return {}


def installed_collection_ids(
    collection: WorkshopCollectionResult, workshop_roots: list[Path]
) -> set[str]:
    """Require a Steam install receipt current enough for fetched item metadata.

    This confirms Steam's recorded installation, not gameplay compatibility.
    A scan must separately establish the contained Mod IDs.
    """
    ready = set()
    for root in workshop_roots:
        data = _manifest_data(root.parent.parent / "appworkshop_108600.acf")
        installed = data.get("WorkshopItemsInstalled", {})
        details = data.get("WorkshopItemDetails", {})
        if not isinstance(installed, dict) or not isinstance(details, dict):
            continue
        for item in collection.items:
            record = installed.get(item.workshop_id)
            latest = details.get(item.workshop_id, {})
            if not isinstance(record, dict) or not isinstance(latest, dict):
                continue
            manifest = record.get("manifest", "")
            if (
                not isinstance(manifest, str)
                or not manifest.isdecimal()
                or manifest == "0"
            ):
                continue
            if latest.get("manifest", manifest) != manifest:
                continue
            try:
                if (
                    item.updated_at
                    and int(record.get("timeupdated", 0)) < item.updated_at
                ):
                    continue
            except ValueError, TypeError:
                continue
            folder = root / item.workshop_id
            if folder.is_dir() and not folder.is_symlink() and not folder.is_junction():
                ready.add(item.workshop_id)
    return ready
