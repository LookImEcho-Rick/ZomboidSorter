import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.discovery.paths import detect_paths, find_steamapps_libraries


class PathDiscoveryTests(unittest.TestCase):
    def test_reads_secondary_steam_library_and_project_zomboid_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steam = root / "Steam"
            secondary = root / "Games Library"
            (steam / "steamapps").mkdir(parents=True)
            secondary_steamapps = secondary / "steamapps"
            game = secondary_steamapps / "common" / "ProjectZomboid"
            game.mkdir(parents=True)
            workshop = secondary_steamapps / "workshop" / "content" / "108600"
            workshop.mkdir(parents=True)
            escaped = str(secondary).replace("\\", "\\\\")
            (steam / "steamapps" / "libraryfolders.vdf").write_text(
                '"libraryfolders" { "0" { "path" "'
                + str(steam).replace("\\", "\\\\")
                + '" } "1" { "path" "'
                + escaped
                + '" } }',
                encoding="utf-8",
            )
            (secondary_steamapps / "appmanifest_108600.acf").write_text(
                '"AppState" { "installdir" "ProjectZomboid" }', encoding="utf-8"
            )

            libraries = find_steamapps_libraries(steam)
            self.assertIn(secondary_steamapps, libraries)
            detected = detect_paths(home=root / "User", steam_roots=[steam])
            self.assertIn(game, detected.game_installations)
            self.assertIn(workshop, detected.workshop_roots)
            self.assertEqual(
                detected.local_mod_root, root / "User" / "Zomboid" / "mods"
            )

    def test_missing_steam_is_a_diagnostic_and_local_default_is_retained(self) -> None:
        home = Path("/not-a-real-user-home")
        detected = detect_paths(home=home, steam_roots=[])
        self.assertFalse(detected.steam_roots)
        self.assertEqual(detected.local_mod_root, home / "Zomboid" / "mods")
        self.assertTrue(
            any("Steam was not detected" in message for message in detected.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
