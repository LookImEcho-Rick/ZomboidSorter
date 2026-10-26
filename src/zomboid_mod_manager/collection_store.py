"""Shared exact-content collection storage, separate from the installed library."""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event

from .discovery.scanner import scan_workshop_item
from .domain import ScanResult
from .profiles import CollectionContent, ModProfile, ProfileError


class CollectionStoreError(ProfileError):
    pass


_CopyFile2Callback = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
)


class _CopyFile2ExtendedParameters(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("dwCopyFlags", ctypes.c_uint32),
        ("pfCancel", ctypes.POINTER(ctypes.c_int32)),
        ("pProgressRoutine", _CopyFile2Callback),
        ("pvCallbackContext", ctypes.c_void_p),
    ]


_COPYFILE2_UNAVAILABLE = object()
_copy_file2 = None
_HASH_WORKERS = 4


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


def tree_digest_with_subtrees(
    root: Path,
    subtree_roots: tuple[Path, ...] | list[Path],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[str, dict[Path, str]]:
    """Hash a tree and selected nested trees during the same file reads."""
    require_plain_path(root)
    if not root.is_dir():
        raise CollectionStoreError(
            "Collection content is missing. Re-import this collection to download it."
        )

    root = Path(os.path.abspath(root))
    root_key = os.path.normcase(os.fspath(root))
    requested: dict[str, Path] = {}
    for subtree in subtree_roots:
        require_plain_path(subtree)
        subtree = Path(os.path.abspath(subtree))
        try:
            subtree.relative_to(root)
        except ValueError as exc:
            raise CollectionStoreError(
                "A collection mod folder is outside its cached Workshop item."
            ) from exc
        requested[os.path.normcase(os.fspath(subtree))] = subtree

    digest = hashlib.sha256()
    subtree_digests = {key: hashlib.sha256() for key in requested}
    subtree_counts = dict.fromkeys(requested, 0)
    active_by_directory = {
        root_key: ((root_key, root),) if root_key in requested else ()
    }
    count = 0

    def walk_error(error: OSError) -> None:
        raise CollectionStoreError(
            f"Could not read collection content: {error}"
        ) from error

    for parent, folders, files in os.walk(
        root, topdown=True, followlinks=False, onerror=walk_error
    ):
        check_cancelled(cancelled)
        folders.sort()
        files.sort()
        parent_path = Path(parent)
        parent_key = os.path.normcase(os.path.abspath(os.fspath(parent_path)))
        active_roots = active_by_directory.pop(parent_key, ())
        for name in sorted(folders + files):
            check_cancelled(cancelled)
            path = parent_path / name
            if path.is_symlink() or path.is_junction():
                raise CollectionStoreError(
                    f"Collection content contains a link: {path}"
                )
            info = path.stat(follow_symlinks=False)
            relative = path.relative_to(root).as_posix().encode("utf-8")
            record = len(relative).to_bytes(8, "big") + relative
            if stat.S_ISDIR(info.st_mode):
                record += b"D"
            elif stat.S_ISREG(info.st_mode):
                record += b"F" + info.st_size.to_bytes(8, "big")
            else:
                raise CollectionStoreError("Collection contains a non-regular file.")
            digest.update(record)

            relative_by_root = []
            for key, subtree in active_roots:
                subtree_relative = path.relative_to(subtree).as_posix().encode("utf-8")
                subtree_digests[key].update(
                    len(subtree_relative).to_bytes(8, "big")
                    + subtree_relative
                    + (
                        b"D"
                        if stat.S_ISDIR(info.st_mode)
                        else b"F" + info.st_size.to_bytes(8, "big")
                    )
                )
                subtree_counts[key] += 1
                relative_by_root.append(key)

            if stat.S_ISREG(info.st_mode):
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        check_cancelled(cancelled)
                        digest.update(chunk)
                        for key in relative_by_root:
                            subtree_digests[key].update(chunk)

            count += 1
            if count > 1_000_000:
                raise CollectionStoreError(
                    "Collection content exceeds the file-count limit."
                )

            if stat.S_ISDIR(info.st_mode):
                child_key = os.path.normcase(os.path.abspath(os.fspath(path)))
                child_roots = active_roots
                if child_key in requested:
                    child_roots = (*active_roots, (child_key, requested[child_key]))
                active_by_directory[child_key] = child_roots

    if not count:
        raise CollectionStoreError("The downloaded item is empty.")
    empty_subtrees = [
        requested[key] for key, amount in subtree_counts.items() if not amount
    ]
    if empty_subtrees:
        raise CollectionStoreError("A collection mod folder is empty.")
    return digest.hexdigest(), {
        requested[key]: value.hexdigest() for key, value in subtree_digests.items()
    }


def directory_identity(path: Path) -> tuple[int | None, int | None]:
    """Return stable device/file identifiers when the platform provides them."""
    require_plain_path(path)
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or not info.st_ino:
        return None, None
    return int(info.st_dev), int(info.st_ino)


def validate_plain_tree(
    root: Path, *, cancelled: Callable[[], bool] | None = None
) -> tuple[int | None, int | None]:
    """Check directory structure and reject links without reading file contents."""
    identity = directory_identity(root)
    count = 0

    def walk_error(error: OSError) -> None:
        raise CollectionStoreError(
            f"Could not inspect owned mod folder: {error}"
        ) from error

    for parent, folders, files in os.walk(
        root, topdown=True, followlinks=False, onerror=walk_error
    ):
        check_cancelled(cancelled)
        folders.sort()
        files.sort()
        for name in folders + files:
            check_cancelled(cancelled)
            path = Path(parent) / name
            if path.is_symlink() or path.is_junction():
                raise CollectionStoreError(
                    f"An app-owned mod folder contains a link: {path}"
                )
            mode = path.stat(follow_symlinks=False).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise CollectionStoreError(
                    "An app-owned mod folder contains a non-regular file."
                )
            count += 1
            if count > 1_000_000:
                raise CollectionStoreError(
                    "An app-owned mod folder exceeds the file-count limit."
                )
    return identity


def _windows_api_path(path: Path) -> str:
    value = os.path.abspath(os.fspath(path))
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _copy_file_with_copyfile2(
    source: Path, destination: Path, cancelled: Callable[[], bool] | None
) -> bool:
    """Use Windows' cancelable native copier when available; return False otherwise."""
    global _copy_file2
    if os.name != "nt":
        return False
    if _copy_file2 is None:
        try:
            _copy_file2 = ctypes.WinDLL("kernel32", use_last_error=True).CopyFile2
            _copy_file2.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.POINTER(_CopyFile2ExtendedParameters),
            ]
            _copy_file2.restype = ctypes.c_long
        except AttributeError, OSError:
            _copy_file2 = _COPYFILE2_UNAVAILABLE
    if _copy_file2 is _COPYFILE2_UNAVAILABLE:
        return False

    cancel_flag = ctypes.c_int32(0)
    cancellation_seen = False

    def on_progress(_message, _context):
        nonlocal cancellation_seen
        if cancelled is not None and cancelled():
            cancellation_seen = True
            cancel_flag.value = 1
            return 1  # COPYFILE2_PROGRESS_CANCEL; partial file fragments are removed.
        return 0  # COPYFILE2_PROGRESS_CONTINUE

    callback = _CopyFile2Callback(on_progress)
    parameters = _CopyFile2ExtendedParameters(
        ctypes.sizeof(_CopyFile2ExtendedParameters),
        0x00000001,  # COPY_FILE_FAIL_IF_EXISTS
        ctypes.pointer(cancel_flag),
        callback,
        None,
    )
    result = _copy_file2(
        _windows_api_path(source),
        _windows_api_path(destination),
        ctypes.byref(parameters),
    )
    if result == 0:
        return True

    error_code = result & 0xFFFF
    if cancellation_seen and error_code == 1235:  # ERROR_REQUEST_ABORTED
        raise CollectionStoreError(
            "Collection operation cancelled; cached content is preserved."
        )
    if error_code in (80, 183):  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
        raise FileExistsError(error_code, os.strerror(error_code), str(destination))
    if error_code == 127:  # ERROR_PROC_NOT_FOUND: use the portable fallback.
        _copy_file2 = _COPYFILE2_UNAVAILABLE
        return False
    raise OSError(error_code, os.strerror(error_code), str(source), str(destination))


def copy_verified_tree(
    source: Path,
    destination: Path,
    *,
    cancelled=None,
    expected_digest: str | None = None,
) -> str:
    expected = (
        expected_digest
        if expected_digest is not None
        else tree_digest(source, cancelled=cancelled)
    )
    require_plain_path(destination)
    if destination.exists():
        raise CollectionStoreError("Refusing to overwrite an existing mod folder.")

    def copy_file(src, dst):
        check_cancelled(cancelled)
        require_plain_path(Path(src))
        if _copy_file_with_copyfile2(Path(src), Path(dst), cancelled):
            return dst
        with open(src, "rb") as incoming, open(dst, "xb") as outgoing:
            while chunk := incoming.read(1024 * 1024):
                check_cancelled(cancelled)
                outgoing.write(chunk)
        return dst

    shutil.copytree(source, destination, copy_function=copy_file)
    if tree_digest(destination, cancelled=cancelled) != expected:
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
            require_plain_path(target)
            if not target.is_dir():
                raise CollectionStoreError(
                    "Shared cached content is not a directory; refusing to reuse it."
                )
            if tree_digest(target, cancelled=cancelled) != expected:
                raise CollectionStoreError(
                    "Shared cached content was modified; refusing to reuse it."
                )
            return reference
        staging = self.root / "incomplete" / uuid.uuid4().hex
        staging.parent.mkdir(parents=True, exist_ok=True)
        if (
            copy_verified_tree(
                source,
                staging,
                cancelled=cancelled,
                expected_digest=expected,
            )
            != expected
        ):
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

    def scan(self, profile: ModProfile, *, cancelled=None, progress=None) -> ScanResult:
        result, _ = self.scan_with_entry_digests(
            profile, cancelled=cancelled, progress=progress
        )
        return result

    def scan_with_entry_digests(
        self, profile: ModProfile, *, cancelled=None, progress=None
    ) -> tuple[ScanResult, dict[Path, str]]:
        entry_digests = {}

        def verify_item(number, content, stop_event):
            def item_cancelled():
                return stop_event.is_set() or (cancelled is not None and cancelled())

            check_cancelled(item_cancelled)
            path = self.path(content)
            item = scan_workshop_item(
                path, content.workshop_id, cancelled=item_cancelled
            )
            item_digest, item_entry_digests = tree_digest_with_subtrees(
                path,
                list(dict.fromkeys(entry.entry_path for entry in item.entries)),
                cancelled=item_cancelled,
            )
            if item_digest != content.sha256:
                raise CollectionStoreError(
                    "Cached collection content no longer matches this pack's exact version."
                )
            return number, content, item, item_entry_digests

        contents = profile.collection_content
        items = [None] * len(contents)
        if progress and contents:
            progress(f"Verifying saved Workshop items: 0/{len(contents)}…")
        if contents:
            stop_event = Event()
            with ThreadPoolExecutor(
                max_workers=min(_HASH_WORKERS, len(contents)),
                thread_name_prefix="collection-hash",
            ) as executor:
                futures = [
                    executor.submit(verify_item, number, content, stop_event)
                    for number, content in enumerate(contents, 1)
                ]
                for completed, future in enumerate(as_completed(futures), 1):
                    try:
                        number, content, item, digests = future.result()
                    except Exception:
                        stop_event.set()
                        for pending in futures:
                            if pending is not future:
                                pending.cancel()
                        raise
                    items[number - 1] = item
                    entry_digests.update(digests)
                    check_cancelled(cancelled)
                    if progress:
                        progress(
                            f"Verified saved Workshop item {completed}/{len(contents)} (ID {content.workshop_id})"
                        )

        verified_items = tuple(item for item in items if item is not None)
        diagnostics = [
            diagnostic for item in verified_items for diagnostic in item.diagnostics
        ]
        return ScanResult((), verified_items, tuple(diagnostics)), entry_digests
