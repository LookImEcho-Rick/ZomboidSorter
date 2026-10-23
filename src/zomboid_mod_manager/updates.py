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
_API_URL = (
    f"https://api.github.com/repos/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases/latest"
)
_USER_AGENT = "ZomboidSorter-updater"
_HTTP_TIMEOUT_SECONDS = 20
_MAX_RELEASE_RESPONSE_BYTES = 2_000_000
_MAX_CHECKSUM_RESPONSE_BYTES = 4_096
_MAX_INSTALLER_BYTES = 2_000_000_000
_VERSION_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)\Z")
_CHECKSUM_PATTERN = re.compile(r"([0-9a-fA-F]{64})\s+\*?(.+)")
_SIGNER_THUMBPRINT_PATTERN = re.compile(r"[0-9a-fA-F]{40,64}\Z")


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


def check_for_update(current_version: str) -> UpdateRelease | None:
    """Return the latest compatible release when it is newer than this app."""
    current_key = _version_key(current_version)
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
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str):
        raise UpdateError("The latest GitHub release has no valid version tag.")
    version = tag_name.removeprefix("v")
    latest_key = _version_key(version)
    if payload.get("draft") or payload.get("prerelease"):
        raise UpdateError(
            "GitHub returned a draft or prerelease as the latest release."
        )
    if latest_key <= current_key:
        return None

    installer_name = f"ZomboidSorter-{version}-windows-setup.exe"
    checksum_name = f"{installer_name}.sha256"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("The latest release does not include downloadable assets.")
    by_name = {
        asset.get("name"): asset
        for asset in assets
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    }
    installer_asset = by_name.get(installer_name)
    checksum_asset = by_name.get(checksum_name)
    if not isinstance(installer_asset, dict) or not isinstance(checksum_asset, dict):
        raise UpdateError(
            "The latest release is missing its Windows installer or SHA-256 file."
        )
    installer_size = installer_asset.get("size")
    if (
        not isinstance(installer_size, int)
        or isinstance(installer_size, bool)
        or installer_size <= 0
        or installer_size > _MAX_INSTALLER_BYTES
    ):
        raise UpdateError("The installer has an invalid or unsupported file size.")

    expected_urls = {
        installer_name: _release_asset_url(tag_name, installer_name),
        checksum_name: _release_asset_url(tag_name, checksum_name),
    }
    if (
        installer_asset.get("browser_download_url") != expected_urls[installer_name]
        or checksum_asset.get("browser_download_url") != expected_urls[checksum_name]
    ):
        raise UpdateError("The release contains an unexpected installer download URL.")

    return UpdateRelease(
        version=version,
        tag_name=tag_name,
        installer_name=installer_name,
        installer_url=expected_urls[installer_name],
        installer_size=installer_size,
        checksum_name=checksum_name,
        checksum_url=expected_urls[checksum_name],
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
    return match.group(1).lower()


def verify_update_signature(
    installer_path: Path, *, reference_executable: Path | None = None
) -> None:
    """Require a trusted installer signature from the running app's publisher."""
    if os.name != "nt":
        raise UpdateError("Signed installer verification is available on Windows only.")

    if reference_executable is None:
        if not getattr(sys, "frozen", False):
            raise UpdateError(
                "Automatic updates require a signed ZomboidSorter installation. "
                "Download the installer from the official Releases page instead."
            )
        reference_executable = Path(sys.executable)

    environment = os.environ.copy()
    environment["ZOMBOIDSORTER_REFERENCE_EXE"] = str(reference_executable)
    environment["ZOMBOIDSORTER_UPDATE_INSTALLER"] = str(installer_path)
    script = """$ErrorActionPreference = 'Stop'
$reference = Get-AuthenticodeSignature -LiteralPath $env:ZOMBOIDSORTER_REFERENCE_EXE
$installer = Get-AuthenticodeSignature -LiteralPath $env:ZOMBOIDSORTER_UPDATE_INSTALLER
if ($reference.Status -ne 'Valid' -or $installer.Status -ne 'Valid') { exit 10 }
$referenceThumbprint = $reference.SignerCertificate.Thumbprint.Trim()
$installerThumbprint = $installer.SignerCertificate.Thumbprint.Trim()
if ($referenceThumbprint -ne $installerThumbprint) { exit 11 }
Write-Output $referenceThumbprint"""
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        result = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            env=environment,
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="replace",
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("Could not verify the Windows installer signature.") from exc

    if result.returncode == 10:
        raise UpdateError(
            "The running app or downloaded installer does not have a trusted publisher signature."
        )
    if result.returncode == 11:
        raise UpdateError(
            "The downloaded installer was signed by a different publisher than this app."
        )
    if result.returncode != 0:
        raise UpdateError("Could not verify the Windows installer signature.")
    thumbprint = result.stdout.strip()
    if not _SIGNER_THUMBPRINT_PATTERN.fullmatch(thumbprint):
        raise UpdateError("Windows returned an invalid installer signer identity.")


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
        Path(tempfile.gettempdir())
        / f"ZomboidSorter-update-{release.version}-{uuid.uuid4().hex}.exe"
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
        verify_update_signature(partial_path)
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
