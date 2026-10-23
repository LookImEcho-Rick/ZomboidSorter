import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zomboid_mod_manager import updates


def release_fixture(
    *, version: str = "0.1.5", build_id: str = "a" * 40
) -> tuple[dict[str, object], dict[str, object]]:
    installer_name = updates._INSTALLER_NAME
    checksum_name = updates._CHECKSUM_NAME
    checksum = "b" * 64
    manifest = {
        "schema": 1,
        "version": version,
        "build_id": build_id,
        "installer_name": installer_name,
        "installer_size": 1024,
        "sha256": checksum,
    }
    release = {
        "tag_name": updates._ROLLING_TAG,
        "draft": False,
        "prerelease": True,
        "assets": [
            {
                "name": installer_name,
                "size": 1024,
                "browser_download_url": updates._release_asset_url(
                    updates._ROLLING_TAG, installer_name
                ),
            },
            {
                "name": checksum_name,
                "size": 100,
                "browser_download_url": updates._release_asset_url(
                    updates._ROLLING_TAG, checksum_name
                ),
            },
            {
                "name": updates._MANIFEST_NAME,
                "size": 200,
                "browser_download_url": updates._release_asset_url(
                    updates._ROLLING_TAG, updates._MANIFEST_NAME
                ),
            },
        ],
    }
    return release, manifest


def read_release_fixture(release: dict[str, object], manifest: dict[str, object]):
    def read_url(url: str, *, maximum_bytes: int) -> bytes:
        del maximum_bytes
        if url == updates._API_URL:
            return json.dumps(release).encode("utf-8")
        if url == updates._release_asset_url(
            updates._ROLLING_TAG, updates._MANIFEST_NAME
        ):
            return json.dumps(manifest).encode("utf-8")
        raise AssertionError(f"Unexpected URL requested by updater: {url}")

    return read_url


class UpdateCheckTests(unittest.TestCase):
    def test_returns_release_when_installed_build_is_older(self) -> None:
        release_payload, manifest = release_fixture()
        with patch.object(
            updates,
            "_read_url",
            side_effect=read_release_fixture(release_payload, manifest),
        ):
            release = updates.check_for_update("0.1.4", "c" * 40)

        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.1.5")
        self.assertEqual(release.tag_name, "rolling")
        self.assertEqual(release.installer_name, "ZomboidSorter-windows-setup.exe")
        self.assertEqual(release.build_id, "a" * 40)
        self.assertEqual(release.expected_sha256, "b" * 64)

    def test_returns_none_when_installed_build_matches(self) -> None:
        release_payload, manifest = release_fixture()
        with patch.object(
            updates,
            "_read_url",
            side_effect=read_release_fixture(release_payload, manifest),
        ):
            release = updates.check_for_update("0.1.5", "a" * 40)

        self.assertIsNone(release)

    def test_source_run_does_not_offer_a_packaged_update(self) -> None:
        with patch.object(updates, "_read_url") as read_url:
            release = updates.check_for_update("0.1.5", "source")

        self.assertIsNone(release)
        read_url.assert_not_called()

    def test_rejects_unexpected_asset_url(self) -> None:
        release_payload, manifest = release_fixture()
        release_payload["assets"][0]["browser_download_url"] = (
            "https://example.com/setup.exe"
        )
        with (
            patch.object(
                updates,
                "_read_url",
                side_effect=read_release_fixture(release_payload, manifest),
            ),
            self.assertRaises(updates.UpdateError),
        ):
            updates.check_for_update("0.1.4", "c" * 40)

    def test_rejects_unsupported_manifest_schema(self) -> None:
        release_payload, manifest = release_fixture()
        manifest["schema"] = 2
        with (
            patch.object(
                updates,
                "_read_url",
                side_effect=read_release_fixture(release_payload, manifest),
            ),
            self.assertRaisesRegex(updates.UpdateError, "unsupported format"),
        ):
            updates.check_for_update("0.1.4", "c" * 40)

    def test_rejects_manifest_version_downgrade(self) -> None:
        release_payload, manifest = release_fixture(version="0.1.3")
        with (
            patch.object(
                updates,
                "_read_url",
                side_effect=read_release_fixture(release_payload, manifest),
            ),
            self.assertRaisesRegex(updates.UpdateError, "older than the installed"),
        ):
            updates.check_for_update("0.1.4", "c" * 40)

    def test_download_verifies_checksum_and_windows_installer_header(self) -> None:
        contents = b"MZ" + b"test installer contents"
        digest = hashlib.sha256(contents).hexdigest()
        release = updates.UpdateRelease(
            version="0.1.5",
            tag_name="rolling",
            installer_name=updates._INSTALLER_NAME,
            installer_url="https://github.com/example/release/setup.exe",
            installer_size=len(contents),
            checksum_name=updates._CHECKSUM_NAME,
            checksum_url="https://github.com/example/release/setup.exe.sha256",
            build_id="a" * 40,
            expected_sha256=digest,
        )
        checksum = f"{digest}  {release.installer_name}\n".encode("ascii")
        progress: list[tuple[int, int]] = []

        with (
            patch.object(updates, "_read_url", return_value=checksum),
            patch.object(
                updates.urllib.request, "urlopen", return_value=io.BytesIO(contents)
            ),
        ):
            installer = updates.download_update(
                release,
                progress=lambda downloaded, total: progress.append((downloaded, total)),
            )

        try:
            self.assertEqual(installer.read_bytes(), contents)
            self.assertEqual(progress[-1], (len(contents), len(contents)))
        finally:
            installer.unlink(missing_ok=True)

    def test_rejects_checksum_that_disagrees_with_manifest(self) -> None:
        release = updates.UpdateRelease(
            version="0.1.5",
            tag_name="rolling",
            installer_name=updates._INSTALLER_NAME,
            installer_url="https://github.com/example/release/setup.exe",
            installer_size=10,
            checksum_name=updates._CHECKSUM_NAME,
            checksum_url="https://github.com/example/release/setup.exe.sha256",
            expected_sha256="a" * 64,
        )
        checksum = f"{'b' * 64}  {release.installer_name}\n".encode("ascii")
        with (
            patch.object(updates, "_read_url", return_value=checksum),
            self.assertRaisesRegex(updates.UpdateError, "manifest"),
        ):
            updates._expected_sha256(release)

    def test_update_helper_waits_for_app_and_runs_silent_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_directory = Path(temporary) / "installed app"
            app_directory.mkdir()
            app_executable = app_directory / "ZomboidSorter.exe"
            installer = Path(temporary) / "update.exe"
            app_executable.touch()
            installer.touch()

            with (
                patch.object(updates.sys, "platform", "win32"),
                patch.object(updates.sys, "frozen", True, create=True),
                patch.object(updates.sys, "executable", str(app_executable)),
                patch.object(updates.subprocess, "Popen") as popen,
            ):
                updates.launch_update_helper(installer)

            arguments = popen.call_args.args[0]
            helper_path = Path(arguments[arguments.index("-File") + 1])
            try:
                helper_script = helper_path.read_text(encoding="utf-8")
                self.assertIn("Wait-Process -Id $ParentProcessId", helper_script)
                self.assertIn("/VERYSILENT", helper_script)
                self.assertIn("Start-Process -FilePath $AppPath", helper_script)
                self.assertEqual(popen.call_args.kwargs["cwd"], app_directory)
            finally:
                helper_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
