"""Read GitHub releases and prepare verified Windows installer updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_OWNER = "LookImEcho-Rick"
REPOSITORY_NAME = "ZomboidSorter"
_API_URL = f"https://api.github.com/repos/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases/tags/rolling"
_ROLLING_TAG = "rolling"
_INSTALLER_NAME = "ZomboidSorter-windows-setup.exe"
_CHECKSUM_NAME = f"{_INSTALLER_NAME}.sha256"
_MANIFEST_NAME = "ZomboidSorter-update.json"
_USER_AGENT = "ZomboidSorter-updater"
_HTTP_TIMEOUT_SECONDS = 20
_MAX_RELEASE_RESPONSE_BYTES = 2_000_000
_MAX_CHECKSUM_RESPONSE_BYTES = 4_096
_MAX_MANIFEST_RESPONSE_BYTES = 16_384
_MAX_INSTALLER_BYTES = 2_000_000_000
_VERSION_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)\Z")
_CHECKSUM_PATTERN = re.compile(r"([0-9a-fA-F]{64})\s+\*?(.+)")
_BUILD_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class UpdateError(RuntimeError):
    """An update could not be checked, downloaded, or verified."""


class UpdateCancelled(UpdateError):
    """The user closed the app while an update download was in progress."""


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    tag_name: str
    installer_name: str
    installer_url: str
    installer_size: int
    checksum_name: str
    checksum_url: str
    build_id: str = ""
    expected_sha256: str = ""


def _version_key(version: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(version)
    if not match:
        raise UpdateError(f"Unsupported release version format: {version!r}.")
    return tuple(int(part) for part in match.groups())


def _read_url(url: str, *, maximum_bytes: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            data = response.read(maximum_bytes + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}.") from exc
    if len(data) > maximum_bytes:
        raise UpdateError("GitHub returned a response that was larger than expected.")
    return data


def _release_asset_url(tag_name: str, asset_name: str) -> str:
    encoded_tag = urllib.parse.quote(tag_name, safe="")
    encoded_name = urllib.parse.quote(asset_name, safe="")
    return (
        f"https://github.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}"
        f"/releases/download/{encoded_tag}/{encoded_name}"
    )


def installed_build_id() -> str:
    """Return the commit baked into a packaged app, or a source-run marker."""
    if not getattr(sys, "frozen", False):
        return "source"
    build_id_path = Path(sys.executable).resolve().parent / "BUILD_ID"
    try:
        build_id = build_id_path.read_text(encoding="ascii").strip().lower()
    except OSError, UnicodeDecodeError:
        return "unknown"
    return build_id if _BUILD_ID_PATTERN.fullmatch(build_id) else "unknown"


def check_for_update(
    current_version: str, current_build_id: str | None = None
) -> UpdateRelease | None:
    """Return the newest successful rolling build when it differs from this app."""
    current_key = _version_key(current_version)
    if current_build_id == "source":
        return None
    try:
        payload = json.loads(
            _read_url(_API_URL, maximum_bytes=_MAX_RELEASE_RESPONSE_BYTES).decode(
                "utf-8"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub returned invalid release information.") from exc

    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an unexpected release response.")
    if (
        payload.get("tag_name") != _ROLLING_TAG
        or payload.get("draft")
        or not payload.get("prerelease")
    ):
        raise UpdateError("GitHub returned an unexpected rolling update release.")

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("The rolling release does not include downloadable assets.")
    by_name = {
        asset.get("name"): asset
        for asset in assets
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    }
    manifest_asset = by_name.get(_MANIFEST_NAME)
    if not isinstance(manifest_asset, dict):
        raise UpdateError("The rolling release is missing its update manifest.")
    manifest_url = _release_asset_url(_ROLLING_TAG, _MANIFEST_NAME)
    if manifest_asset.get("browser_download_url") != manifest_url:
        raise UpdateError("The rolling release contains an unexpected manifest URL.")
    try:
        manifest = json.loads(
            _read_url(manifest_url, maximum_bytes=_MAX_MANIFEST_RESPONSE_BYTES).decode(
                "utf-8-sig"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(
            "GitHub returned an invalid rolling update manifest."
        ) from exc
    if not isinstance(manifest, dict):
        raise UpdateError("GitHub returned an unexpected rolling manifest shape.")
    schema = manifest.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema != 1:
        raise UpdateError("The rolling update manifest uses an unsupported format.")

    version = manifest.get("version")
    build_id = manifest.get("build_id")
    installer_name = manifest.get("installer_name")
    installer_size = manifest.get("installer_size")
    expected_sha256 = manifest.get("sha256")
    if not isinstance(version, str):
        raise UpdateError("The rolling manifest has no valid app version.")
    latest_key = _version_key(version)
    if latest_key < current_key:
        raise UpdateError("The rolling build is older than the installed app.")
    if not isinstance(build_id, str) or not _BUILD_ID_PATTERN.fullmatch(build_id):
        raise UpdateError("The rolling manifest has an invalid commit ID.")
    if installer_name != _INSTALLER_NAME:
        raise UpdateError("The rolling manifest names an unexpected installer.")
    if not isinstance(expected_sha256, str) or not _SHA256_PATTERN.fullmatch(
        expected_sha256
    ):
        raise UpdateError("The rolling manifest has an invalid installer checksum.")
    if current_build_id is None:
        current_build_id = installed_build_id()
    if build_id == current_build_id:
        return None

    checksum_name = _CHECKSUM_NAME
    installer_asset = by_name.get(installer_name)
    checksum_asset = by_name.get(checksum_name)
    if not isinstance(installer_asset, dict) or not isinstance(checksum_asset, dict):
        raise UpdateError(
            "The rolling release is missing its Windows installer or SHA-256 file."
        )
    if (
        not isinstance(installer_size, int)
        or isinstance(installer_size, bool)
        or installer_size <= 0
        or installer_size > _MAX_INSTALLER_BYTES
    ):
        raise UpdateError("The rolling installer has an invalid or unsupported size.")
    if installer_asset.get("size") != installer_size:
        raise UpdateError("The rolling manifest size does not match the release asset.")

    expected_urls = {
        installer_name: _release_asset_url(_ROLLING_TAG, installer_name),
        checksum_name: _release_asset_url(_ROLLING_TAG, checksum_name),
    }
    if (
        installer_asset.get("browser_download_url") != expected_urls[installer_name]
        or checksum_asset.get("browser_download_url") != expected_urls[checksum_name]
    ):
        raise UpdateError("The rolling release contains an unexpected installer URL.")

    return UpdateRelease(
        version=version,
        tag_name=_ROLLING_TAG,
        installer_name=installer_name,
        installer_url=expected_urls[installer_name],
        installer_size=installer_size,
        checksum_name=checksum_name,
        checksum_url=expected_urls[checksum_name],
        build_id=build_id,
        expected_sha256=expected_sha256,
    )


def _expected_sha256(release: UpdateRelease) -> str:
    data = _read_url(release.checksum_url, maximum_bytes=_MAX_CHECKSUM_RESPONSE_BYTES)
    try:
        checksum_line = data.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise UpdateError("The release checksum file is not valid ASCII text.") from exc
    match = _CHECKSUM_PATTERN.fullmatch(checksum_line)
    if not match or match.group(2) != release.installer_name:
        raise UpdateError("The release checksum does not match the installer name.")
    digest = match.group(1).lower()
    if release.expected_sha256 and digest != release.expected_sha256:
        raise UpdateError("The release checksum does not match its update manifest.")
    return digest


def download_update(
    release: UpdateRelease,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Download an installer to the system temp folder and verify its checksum."""
    expected_digest = _expected_sha256(release)
    if cancelled is not None and cancelled():
        raise UpdateCancelled("The update download was cancelled.")

    installer_path = (
        Path(tempfile.gettempdir()) / f"ZomboidSorter-update-{uuid.uuid4().hex}.exe"
    )
    partial_path = installer_path.with_suffix(".part.exe")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        request = urllib.request.Request(
            release.installer_url,
            headers={"User-Agent": _USER_AGENT},
        )
        try:
            with (
                urllib.request.urlopen(
                    request, timeout=_HTTP_TIMEOUT_SECONDS
                ) as response,
                partial_path.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    if cancelled is not None and cancelled():
                        raise UpdateCancelled("The update download was cancelled.")
                    downloaded += len(chunk)
                    if downloaded > release.installer_size:
                        raise UpdateError(
                            "The installer download exceeded its release size."
                        )
                    digest.update(chunk)
                    output.write(chunk)
                    if progress is not None:
                        progress(downloaded, release.installer_size)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdateError(
                f"Could not download the Windows installer: {exc}."
            ) from exc

        if downloaded != release.installer_size:
            raise UpdateError(
                "The downloaded installer size does not match the release."
            )
        if digest.hexdigest() != expected_digest:
            raise UpdateError(
                "The installer checksum does not match the release SHA-256."
            )
        with partial_path.open("rb") as installer_file:
            if installer_file.read(2) != b"MZ":
                raise UpdateError(
                    "The downloaded file is not a valid Windows installer."
                )
        partial_path.replace(installer_path)
        return installer_path
    except UpdateError:
        raise
    except OSError as exc:
        raise UpdateError(
            f"Could not save the installer to the temp folder: {exc}."
        ) from exc
    finally:
        partial_path.unlink(missing_ok=True)


def launch_update_helper(installer_path: Path) -> None:
    """Close this packaged app, run the verified installer silently, then relaunch."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise UpdateError(
            "Automatic updates are available only in the packaged Windows app."
        )

    installer = installer_path.resolve(strict=True)
    app_executable = Path(sys.executable).resolve(strict=True)
    app_directory = app_executable.parent
    helper_path = (
        Path(tempfile.gettempdir()) / f"ZomboidSorter-update-{uuid.uuid4().hex}.ps1"
    )
    helper_source = r"""param(
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$AppDirectory,
    [Parameter(Mandatory=$true)][int]$ParentProcessId
)
$ErrorActionPreference = 'Stop'
$AppPath = Join-Path $AppDirectory 'ZomboidSorter.exe'
$LogPath = Join-Path $env:TEMP 'ZomboidSorter-update-error.txt'
try {
    Wait-Process -Id $ParentProcessId -ErrorAction SilentlyContinue
    $Setup = Start-Process -FilePath $InstallerPath `
        -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$AppDirectory`"") `
        -PassThru -Wait -WindowStyle Hidden
    if ($Setup.ExitCode -ne 0) {
        throw "The installer exited with code $($Setup.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
        throw 'The installer finished but the app executable is missing.'
    }
    Start-Process -FilePath $AppPath -WorkingDirectory $AppDirectory
} catch {
    try { [System.IO.File]::WriteAllText($LogPath, $_.Exception.Message) } catch {}
    if (Test-Path -LiteralPath $AppPath -PathType Leaf) {
        try { Start-Process -FilePath $AppPath -WorkingDirectory $AppDirectory } catch {}
    }
} finally {
    Start-Sleep -Seconds 2
    Remove-Item -LiteralPath $InstallerPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
"""
    try:
        helper_path.write_text(helper_source, encoding="utf-8")
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(helper_path),
                "-InstallerPath",
                str(installer),
                "-AppDirectory",
                str(app_directory),
                "-ParentProcessId",
                str(os.getpid()),
            ],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=app_directory,
        )
    except OSError as exc:
        helper_path.unlink(missing_ok=True)
        raise UpdateError(f"Could not start the update helper: {exc}.") from exc
