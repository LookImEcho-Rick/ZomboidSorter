from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from zomboid_mod_manager.discovery.game_build import detect_game_build


class GameBuildDetectionTests(unittest.TestCase):
    def test_detects_legacy_41_from_steam_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "steamapps" / "common" / "ProjectZomboid"
            game.mkdir(parents=True)
            manifest = game.parents[1] / "appmanifest_108600.acf"
            manifest.write_text('"AppState" { "BetaKey" "legacy41" }', encoding="utf-8")

            result = detect_game_build(game)

        self.assertEqual(result.major_build, "41")
        self.assertIsNone(result.exact_version)
        self.assertIn("legacy41", result.source or "")

    def test_detects_42_from_loose_core_class_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            core = game / "zombie" / "core" / "Core.class"
            core.parent.mkdir(parents=True)
            core.write_bytes(b"class data VERSION_BUILD_42 more class data")

            result = detect_game_build(game)

        self.assertEqual(result.major_build, "42")
        self.assertIsNone(result.exact_version)
        self.assertIn("Build 42 marker", result.source or "")
        self.assertIn("exact patch", result.note)

    def test_detects_42_from_jarred_core_class(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            with zipfile.ZipFile(game / "projectzomboid.jar", "w") as archive:
                archive.writestr("zombie/core/Core.class", b"VERSION_BUILD_42")

            result = detect_game_build(game)

        self.assertEqual(result.major_build, "42")

    def test_detects_exact_version_only_when_version_file_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "steamapps" / "common" / "ProjectZomboid"
            game.mkdir(parents=True)
            (game / "zombie" / "core").mkdir(parents=True)
            (game / "zombie" / "core" / "Core.class").write_bytes(b"VERSION_BUILD_42")
            updated = datetime(2026, 10, 20, tzinfo=UTC).timestamp()
            manifest = game.parents[1] / "appmanifest_108600.acf"
            manifest.write_text(
                f'"AppState" {{ "BetaKey" "unstable" "LastUpdated" "{int(updated)}" }}',
                encoding="utf-8",
            )
            home = root / "user"
            version_path = home / "Zomboid" / "version.txt"
            version_path.parent.mkdir(parents=True)
            version_path.write_text("42.21.0 abc123\n", encoding="utf-8")
            os.utime(version_path, (updated + 10, updated + 10))

            with patch(
                "zomboid_mod_manager.discovery.game_build.Path.home",
                return_value=home,
            ):
                result = detect_game_build(game)

        self.assertEqual(result.major_build, "42")
        self.assertEqual(result.exact_version, "42.21.0")
        self.assertIn("version.txt", result.source or "")

    def test_ignores_stale_exact_version_after_steam_install_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "steamapps" / "common" / "ProjectZomboid"
            game.mkdir(parents=True)
            manifest = game.parents[1] / "appmanifest_108600.acf"
            updated = datetime(2026, 10, 20, tzinfo=UTC).timestamp()
            manifest.write_text(
                f'"AppState" {{ "BetaKey" "legacy41" "LastUpdated" "{int(updated)}" }}',
                encoding="utf-8",
            )
            home = root / "user"
            version_path = home / "Zomboid" / "version.txt"
            version_path.parent.mkdir(parents=True)
            version_path.write_text("42.21.0 stale\n", encoding="utf-8")
            os.utime(version_path, (updated - 10, updated - 10))

            with patch(
                "zomboid_mod_manager.discovery.game_build.Path.home",
                return_value=home,
            ):
                result = detect_game_build(game)

        self.assertEqual(result.major_build, "41")
        self.assertIsNone(result.exact_version)
        self.assertIn("no current exact version", result.note)

    def test_does_not_guess_from_unknown_branch_or_empty_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "steamapps" / "common" / "ProjectZomboid"
            game.mkdir(parents=True)
            (game.parents[1] / "appmanifest_108600.acf").write_text(
                '"AppState" { "BetaKey" "unstable" }', encoding="utf-8"
            )

            result = detect_game_build(game)

        self.assertIsNone(result.major_build)
        self.assertIn("Choose the metadata target manually", result.note)


if __name__ == "__main__":
    unittest.main()
