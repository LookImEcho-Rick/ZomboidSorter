"""Isolated anonymous Workshop downloads using Valve's signed SteamCMD tool."""

from __future__ import annotations

import ctypes
import io
import os
import re
import subprocess
import time
import uuid
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.request import urlopen

from .collection_store import CollectionStoreError, check_cancelled, require_plain_path
from .workshop import WorkshopCollectionResult, WorkshopItemMetadata
from .workshop_install import installed_collection_ids

BOOTSTRAP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
DOWNLOAD_BATCH_SIZE = 200
_DOWNLOAD_SUCCESS = re.compile(rb"Success\. Downloaded item (\d{1,20}) to")


def verify_valve_signature(executable: Path) -> None:
    if os.name != "nt":
        raise CollectionStoreError(
            "Automatic SteamCMD setup is currently supported on Windows only."
        )
    environment = dict(os.environ, ZOMBOIDSORTER_STEAMCMD_EXE=str(executable))
    # A developer launching from PowerShell 7 can otherwise pass incompatible
    # module paths to the Windows PowerShell signature-verification process.
    environment = {
        key: value
        for key, value in environment.items()
        if key.casefold() != "psmodulepath"
    }
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ZOMBOIDSORTER_STEAMCMD_EXE; "
        r"if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch '(^|, )O=Valve( Corp\.)?(,|$)') { exit 1 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        check=False,
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise CollectionStoreError(
            "SteamCMD's Valve signature could not be verified. No download was started."
        )


class _ProcessJob:
    """Keep self-updater child processes inside a cancellable Windows job."""

    def __init__(self, process: subprocess.Popen) -> None:
        self.handle = None
        if os.name == "nt":
            from ctypes import wintypes

            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]
            self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.kernel.CreateJobObjectW(None, None)
            if not self.handle or not self.kernel.AssignProcessToJobObject(
                self.handle, int(process._handle)
            ):
                self.close()
                process.kill()
                raise CollectionStoreError(
                    "Could not isolate the SteamCMD downloader process."
                )
        self.process = process

    def close(self) -> None:
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SteamCmdDownloader:
    def __init__(self, tool_root: Path) -> None:
        self.root = tool_root

    def ensure_tool(self, *, cancelled=None, progress=None) -> Path:
        require_plain_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        executable = self.root / "steamcmd.exe"
        require_plain_path(executable)
        if not executable.exists():
            if progress:
                progress("Preparing Valve's SteamCMD downloader for first use…")
            with urlopen(BOOTSTRAP_URL, timeout=30) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
            if len(raw) > 20 * 1024 * 1024:
                raise CollectionStoreError(
                    "SteamCMD bootstrap exceeded the download limit."
                )
            check_cancelled(cancelled)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.getinfo("steamcmd.exe")
                if info.file_size > 20 * 1024 * 1024:
                    raise CollectionStoreError(
                        "SteamCMD executable exceeded the size limit."
                    )
                payload = archive.read(info)
            staging = self.root / f"steamcmd-{uuid.uuid4().hex}.exe"
            with staging.open("xb") as stream:
                stream.write(payload)
            verify_valve_signature(staging)
            check_cancelled(cancelled)
            os.rename(staging, executable)
        else:
            verify_valve_signature(executable)
        return executable

    def download(
        self,
        item: WorkshopItemMetadata,
        *,
        cancelled=None,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        source = {}
        self.download_many(
            (item,),
            cancelled=cancelled,
            progress=progress,
            on_downloaded=lambda downloaded_item, path: source.setdefault(
                downloaded_item.workshop_id, path
            ),
        )
        return source[item.workshop_id]

    def download_many(
        self,
        items: Sequence[WorkshopItemMetadata],
        *,
        cancelled=None,
        progress: Callable[[str], None] | None = None,
        on_downloaded: Callable[[WorkshopItemMetadata, Path], None] | None = None,
    ) -> None:
        items = tuple(items)
        if not items:
            return
        from .workshop import parse_published_file_id

        for item in items:
            parse_published_file_id(item.workshop_id)
            if item.consumer_app_id != 108600:
                raise CollectionStoreError(
                    "Only Project Zomboid Workshop content can be downloaded."
                )

        # Avoid two app instances racing in the shared SteamCMD installation.
        require_plain_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / "zomboidsorter-download.lock"
        require_plain_path(lock_path)
        with lock_path.open("a+b") as lock:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                lock.write(b"0")
                lock.flush()
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise CollectionStoreError(
                        "Another collection download is already running. Retry when it finishes."
                    ) from exc
            try:
                total = len(items)
                workshop_root = self.root / "steamapps/workshop/content/108600"
                collection = WorkshopCollectionResult(items[0].workshop_id, items)
                if progress:
                    progress("Checking for previously downloaded collection items…")
                ready_ids = installed_collection_ids(collection, [workshop_root])
                completed_count = 0
                pending = []
                for index, item in enumerate(items, 1):
                    check_cancelled(cancelled)
                    if item.workshop_id not in ready_ids:
                        pending.append(item)
                        continue
                    if progress:
                        progress(
                            f"Reusing verified download {index}/{total}: {item.title}"
                        )
                    if on_downloaded is not None:
                        on_downloaded(item, workshop_root / item.workshop_id)
                    completed_count += 1

                if not pending:
                    return
                executable = self.ensure_tool(cancelled=cancelled, progress=progress)
                for start in range(0, len(pending), DOWNLOAD_BATCH_SIZE):
                    check_cancelled(cancelled)
                    batch = pending[start : start + DOWNLOAD_BATCH_SIZE]
                    if progress:
                        progress(
                            f"Downloading the next {len(batch)} of {total - completed_count} remaining items through SteamCMD…"
                        )
                    self._download_batch(
                        executable,
                        batch,
                        progress=progress,
                        progress_base=completed_count,
                        progress_total=total,
                        cancelled=cancelled,
                        on_downloaded=on_downloaded,
                    )
                    completed_count += len(batch)
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def _download(
        self,
        executable: Path,
        item: WorkshopItemMetadata,
        *,
        cancelled=None,
        progress=None,
    ) -> Path:
        source = {}
        self._download_batch(
            executable,
            (item,),
            progress=progress,
            progress_base=0,
            progress_total=1,
            cancelled=cancelled,
            on_downloaded=lambda downloaded_item, path: source.setdefault(
                downloaded_item.workshop_id, path
            ),
        )
        return source[item.workshop_id]

    def _download_batch(
        self,
        executable: Path,
        items: Sequence[WorkshopItemMetadata],
        *,
        cancelled=None,
        progress=None,
        progress_base=0,
        progress_total=1,
        on_downloaded=None,
    ) -> None:
        from .workshop import parse_published_file_id

        item_ids = tuple(parse_published_file_id(item.workshop_id) for item in items)
        if any(item.consumer_app_id != 108600 for item in items):
            raise CollectionStoreError(
                "Only Project Zomboid Workshop content can be downloaded."
            )
        log_path = self.root / f"download-{uuid.uuid4().hex}.log"
        root = self.root / "steamapps/workshop/content/108600"
        collection = WorkshopCollectionResult(item_ids[0], tuple(items))
        arguments = [
            str(executable),
            "+@ShutdownOnFailedCommand",
            "1",
            "+@NoPromptForPassword",
            "1",
            "+login",
            "anonymous",
        ]
        for item_id in item_ids:
            arguments.extend(["+workshop_download_item", "108600", item_id, "validate"])
        arguments.append("+quit")
        requested = set(item_ids)
        successful: set[str] = set()
        offset = 0
        pending = b""

        def consume(data: bytes, *, final: bool = False) -> None:
            nonlocal pending
            lines = (pending + data).splitlines(keepends=True)
            pending = b""
            if lines and not final and not lines[-1].endswith((b"\n", b"\r")):
                pending = lines.pop()
            elif final and lines:
                pending = b""
            for line in lines:
                match = _DOWNLOAD_SUCCESS.search(line)
                if match is None:
                    continue
                item_id = match.group(1).decode("ascii")
                if item_id in requested and item_id not in successful:
                    successful.add(item_id)
                    if progress:
                        progress(
                            f"SteamCMD completed {progress_base + len(successful)}/{progress_total} collection items…"
                        )

        with log_path.open("xb") as log:
            process = subprocess.Popen(
                arguments,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            job = _ProcessJob(process)
            deadline = time.monotonic() + 30 * 60 * len(items)
            last_size = -1
            idle_since = time.monotonic()
            all_items_reported_at = None
            try:
                while time.monotonic() < deadline:
                    check_cancelled(cancelled)
                    with log_path.open("rb") as stream:
                        stream.seek(offset)
                        chunk = stream.read()
                    if chunk:
                        offset += len(chunk)
                        consume(chunk)
                    size = log_path.stat().st_size
                    if size != last_size:
                        last_size, idle_since = size, time.monotonic()
                    if (
                        len(successful) == len(item_ids)
                        and all_items_reported_at is None
                    ):
                        all_items_reported_at = time.monotonic()
                    process_exited = process.poll() is not None
                    if process_exited:
                        # Process exit closes SteamCMD's output stream; consume a
                        # final unterminated log line before deciding it is missing.
                        consume(b"", final=True)
                        if len(successful) == len(item_ids):
                            break
                        if time.monotonic() - idle_since > 10:
                            break
                    elif (
                        all_items_reported_at is not None
                        and time.monotonic() - all_items_reported_at > 30
                    ):
                        # Let SteamCMD finish writing its install receipt after
                        # its final success marker, but do not wait forever.
                        break
                    time.sleep(0.15)
                else:
                    raise CollectionStoreError(
                        f"SteamCMD download timed out. Diagnostic log: {log_path}"
                    )
            finally:
                job.close()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)

        with log_path.open("rb") as stream:
            stream.seek(offset)
            consume(stream.read(), final=True)
        receipt_ids = installed_collection_ids(collection, [root])
        verified = successful & receipt_ids
        for item in items:
            if item.workshop_id in verified and on_downloaded is not None:
                on_downloaded(item, root / item.workshop_id)

        missing_markers = [item_id for item_id in item_ids if item_id not in successful]
        if missing_markers:
            preview = ", ".join(missing_markers[:5])
            suffix = "…" if len(missing_markers) > 5 else ""
            raise CollectionStoreError(
                f"SteamCMD did not confirm {len(missing_markers)} of {len(item_ids)} items ({preview}{suffix}). Anonymous access may be unavailable. Diagnostic log: {log_path}"
            )
        missing_receipts = [item_id for item_id in item_ids if item_id not in verified]
        if missing_receipts:
            preview = ", ".join(missing_receipts[:5])
            suffix = "…" if len(missing_receipts) > 5 else ""
            raise CollectionStoreError(
                f"SteamCMD reported success, but installation receipts could not be verified for {len(missing_receipts)} items ({preview}{suffix}). Diagnostic log: {log_path}"
            )
