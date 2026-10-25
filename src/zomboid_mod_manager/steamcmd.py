"""Isolated anonymous Workshop downloads using Valve's signed SteamCMD tool."""

from __future__ import annotations

import ctypes
import io
import os
import subprocess
import time
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.request import urlopen

from .collection_store import CollectionStoreError, check_cancelled, require_plain_path
from .workshop import WorkshopCollectionResult, WorkshopItemMetadata
from .workshop_install import installed_collection_ids

BOOTSTRAP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"


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
        executable = self.ensure_tool(cancelled=cancelled, progress=progress)
        # Avoid two app instances racing in the shared SteamCMD installation.
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
                return self._download(
                    executable, item, cancelled=cancelled, progress=progress
                )
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
        from .workshop import parse_published_file_id

        item_id = parse_published_file_id(item.workshop_id)
        if item.consumer_app_id != 108600:
            raise CollectionStoreError(
                "Only Project Zomboid Workshop content can be downloaded."
            )
        log_path = self.root / f"download-{uuid.uuid4().hex}.log"
        root = self.root / "steamapps/workshop/content/108600"
        collection = WorkshopCollectionResult(item_id, (item,))
        if progress:
            progress(f"Downloading {item.title} anonymously through SteamCMD…")
        with log_path.open("xb") as log:
            process = subprocess.Popen(
                [
                    str(executable),
                    "+@ShutdownOnFailedCommand",
                    "1",
                    "+@NoPromptForPassword",
                    "1",
                    "+login",
                    "anonymous",
                    "+workshop_download_item",
                    "108600",
                    item_id,
                    "validate",
                    "+quit",
                ],
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            job = _ProcessJob(process)
            deadline = time.monotonic() + 30 * 60
            last_size = -1
            idle_since = time.monotonic()
            try:
                while time.monotonic() < deadline:
                    check_cancelled(cancelled)
                    with log_path.open("rb") as stream:
                        stream.seek(max(0, log_path.stat().st_size - 65536))
                        tail = stream.read().decode("utf-8", errors="replace")
                    if f"Success. Downloaded item {item_id} to" in tail:
                        if item_id not in installed_collection_ids(collection, [root]):
                            raise CollectionStoreError(
                                "SteamCMD reported success, but its installation receipt could not be verified."
                            )
                        return root / item_id
                    size = log_path.stat().st_size
                    if size != last_size:
                        last_size, idle_since = size, time.monotonic()
                    if (
                        process.poll() is not None
                        and time.monotonic() - idle_since > 10
                    ):
                        raise CollectionStoreError(
                            f"SteamCMD did not complete this item. Anonymous access may be unavailable. Diagnostic log: {log_path}"
                        )
                    time.sleep(0.15)
                raise CollectionStoreError(
                    f"SteamCMD download timed out. Diagnostic log: {log_path}"
                )
            finally:
                job.close()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
