import hashlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zomboid_mod_manager import updates


def release_payload(version: str = "0.1.2") -> dict[str, object]:
    tag = f"v{version}"
    installer_name = f"ZomboidSorter-{version}-windows-setup.exe"
    checksum_name = f"{installer_name}.sha256"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": installer_name,
                "size": 1024,
                "browser_download_url": updates._release_asset_url(tag, installer_name),
            },
            {
                "name": checksum_name,
                "size": 100,
                "browser_download_url": updates._release_asset_url(tag, checksum_name),
            },
        ],
    }


class UpdateCheckTests(unittest.TestCase):
    def test_returns_release_when_latest_version_is_newer(self) -> None:
        payload = json.dumps(release_payload()).encode("utf-8")
        with patch.object(updates, "_read_url", return_value=payload):
            release = updates.check_for_update("0.1.1")

        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.1.2")
        self.assertEqual(
            release.installer_name, "ZomboidSorter-0.1.2-windows-setup.exe"
        )

    def test_returns_none_when_latest_is_not_newer(self) -> None:
        payload = json.dumps(release_payload("0.1.1")).encode("utf-8")
        with patch.object(updates, "_read_url", return_value=payload):
            release = updates.check_for_update("0.1.2")

        self.assertIsNone(release)

    def test_rejects_unexpected_asset_url(self) -> None:
        payload = release_payload()
        payload["assets"][0]["browser_download_url"] = "https://example.com/setup.exe"
        with (
            patch.object(
                updates, "_read_url", return_value=json.dumps(payload).encode("utf-8")
            ),
            self.assertRaises(updates.UpdateError),
        ):
            updates.check_for_update("0.1.1")

    def test_download_verifies_checksum_and_windows_installer_header(self) -> None:
        contents = b"MZ" + b"test installer contents"
        release = updates.UpdateRelease(
            version="0.1.2",
            tag_name="v0.1.2",
            installer_name="ZomboidSorter-0.1.2-windows-setup.exe",
            installer_url="https://github.com/example/release/setup.exe",
            installer_size=len(contents),
            checksum_name="ZomboidSorter-0.1.2-windows-setup.exe.sha256",
            checksum_url="https://github.com/example/release/setup.exe.sha256",
        )
        expected_digest = hashlib.sha256(contents).hexdigest()
        progress: list[tuple[int, int]] = []

        with (
            patch.object(updates, "_expected_sha256", return_value=expected_digest),
            patch.object(
                updates.urllib.request, "urlopen", return_value=io.BytesIO(contents)
            ),
            patch.object(updates, "verify_update_signature") as verify_signature,
        ):
            installer = updates.download_update(
                release,
                progress=lambda downloaded, total: progress.append((downloaded, total)),
            )

        try:
            self.assertEqual(installer.read_bytes(), contents)
            verify_signature.assert_called_once()
            self.assertTrue(
                str(verify_signature.call_args.args[0]).endswith(".part.exe")
            )
            self.assertEqual(progress[-1], (len(contents), len(contents)))
        finally:
            installer.unlink(missing_ok=True)

    def test_signature_verification_requires_the_running_publisher(self) -> None:
        thumbprint = "A" * 40
        result = SimpleNamespace(returncode=0, stdout=f"{thumbprint}\n")
        with patch.object(updates.subprocess, "run", return_value=result) as run:
            updates.verify_update_signature(
                Path("C:/temp/ZomboidSorter-setup.exe"),
                reference_executable=Path("C:/app/ZomboidSorter.exe"),
            )

        command = run.call_args.args[0]
        self.assertIn("Get-AuthenticodeSignature", command[-1])
        self.assertEqual(
            run.call_args.kwargs["env"]["ZOMBOIDSORTER_REFERENCE_EXE"],
            str(Path("C:/app/ZomboidSorter.exe")),
        )
        self.assertEqual(
            run.call_args.kwargs["env"]["ZOMBOIDSORTER_UPDATE_INSTALLER"],
            str(Path("C:/temp/ZomboidSorter-setup.exe")),
        )

    def test_signature_verification_rejects_a_different_publisher(self) -> None:
        result = SimpleNamespace(returncode=11, stdout="")
        with (
            patch.object(updates.subprocess, "run", return_value=result),
            self.assertRaisesRegex(updates.UpdateError, "different publisher"),
        ):
            updates.verify_update_signature(
                Path("C:/temp/ZomboidSorter-setup.exe"),
                reference_executable=Path("C:/app/ZomboidSorter.exe"),
            )

    def test_source_runs_cannot_claim_a_publisher_identity(self) -> None:
        with (
            patch.object(updates.sys, "frozen", False, create=True),
            self.assertRaisesRegex(updates.UpdateError, "signed ZomboidSorter"),
        ):
            updates.verify_update_signature(Path("C:/temp/setup.exe"))


if __name__ == "__main__":
    unittest.main()
