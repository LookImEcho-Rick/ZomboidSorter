"""Shared exact-content collection storage, separate from the installed library."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from pathlib import Path

from .discovery.scanner import scan_workshop_item
from .domain import ScanResult
from .profiles import CollectionContent, ModProfile, ProfileError


class CollectionStoreError(ProfileError):
    pass


def require_plain_path(path: Path) -> None:
    """Reject links/junctions in every existing ancestor, including broken links."""
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise CollectionStoreError(
                f"Linked collection paths are not supported: {part}"
            )


def check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise CollectionStoreError(
            "Collection operation cancelled; cached content is preserved."
        )


def tree_digest(root: Path, *, cancelled: Callable[[], bool] | None = None) -> str:
    """Hash exact relative paths, entry types, and file bytes; ignore timestamps."""
    require_plain_path(root)
    if not root.is_dir():
        raise CollectionStoreError(
            "Collection content is missing. Re-import this collection to download it."
        )
    digest = hashlib.sha256()
    count = 0
    for parent, folders, files in os.walk(root, followlinks=False):
        folders.sort()
        files.sort()
        for name in sorted(folders + files):
            check_cancelled(cancelled)
            path = Path(parent) / name
            if path.is_symlink() or path.is_junction():
                raise CollectionStoreError(
                    f"Collection content contains a link: {path}"
                )
            mode = path.stat().st_mode
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big") + relative)
            if stat.S_ISDIR(mode):
                digest.update(b"D")
            elif stat.S_ISREG(mode):
                digest.update(b"F" + path.stat().st_size.to_bytes(8, "big"))
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        check_cancelled(cancelled)
                        digest.update(chunk)
            else:
                raise CollectionStoreError("Collection contains a non-regular file.")
            count += 1
            if count > 1_000_000:
                raise CollectionStoreError(
                    "Collection content exceeds the file-count limit."
                )
    if not count:
        raise CollectionStoreError("The downloaded item is empty.")
    return digest.hexdigest()


def copy_verified_tree(source: Path, destination: Path, *, cancelled=None) -> str:
    expected = tree_digest(source, cancelled=cancelled)
    require_plain_path(destination)
    if destination.exists():
        raise CollectionStoreError("Refusing to overwrite an existing mod folder.")

    def copy_file(src, dst):
        check_cancelled(cancelled)
        require_plain_path(Path(src))
        with open(src, "rb") as incoming, open(dst, "xb") as outgoing:
            while chunk := incoming.read(1024 * 1024):
                check_cancelled(cancelled)
                outgoing.write(chunk)
        return dst

    shutil.copytree(source, destination, copy_function=copy_file)
    if (
        tree_digest(destination, cancelled=cancelled) != expected
        or tree_digest(source, cancelled=cancelled) != expected
    ):
        raise CollectionStoreError(
            "Mod files changed while copying; the incomplete copy was retained for inspection."
        )
    return expected


class CollectionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.content_root = root / "content"

    def path(self, content: CollectionContent) -> Path:
        if len(content.sha256) != 64 or any(
            c not in "0123456789abcdef" for c in content.sha256
        ):
            raise CollectionStoreError("Invalid collection content reference.")
        return self.content_root / content.sha256

    def intern(
        self, source: Path, workshop_id: str, *, cancelled=None
    ) -> CollectionContent:
        expected = tree_digest(source, cancelled=cancelled)
        reference = CollectionContent(workshop_id, expected)
        target = self.path(reference)
        require_plain_path(self.root)
        self.content_root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if tree_digest(target, cancelled=cancelled) != expected:
                raise CollectionStoreError(
                    "Shared cached content was modified; refusing to reuse it."
                )
            return reference
        staging = self.root / "incomplete" / uuid.uuid4().hex
        staging.parent.mkdir(parents=True, exist_ok=True)
        if copy_verified_tree(source, staging, cancelled=cancelled) != expected:
            raise CollectionStoreError("Downloaded content changed during import.")
        check_cancelled(cancelled)
        try:
            os.rename(staging, target)
        except FileExistsError:
            if tree_digest(target, cancelled=cancelled) != expected:
                raise CollectionStoreError(
                    "Another import changed the shared cache."
                ) from None
        return reference

    def scan(self, profile: ModProfile, *, cancelled=None) -> ScanResult:
        items = []
        diagnostics = []
        for content in profile.collection_content:
            check_cancelled(cancelled)
            path = self.path(content)
            if tree_digest(path, cancelled=cancelled) != content.sha256:
                raise CollectionStoreError(
                    "Cached collection content no longer matches this pack's exact version."
                )
            item = scan_workshop_item(path, content.workshop_id, cancelled=cancelled)
            items.append(item)
            diagnostics.extend(item.diagnostics)
        return ScanResult((), tuple(items), tuple(diagnostics))
