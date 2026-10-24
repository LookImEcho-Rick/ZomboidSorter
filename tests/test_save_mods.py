from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.gameio.save_mods import (
    ConcurrentSaveModChangeError,
    SaveModDiscoveryError,
    discover_save_mod_lists,
    read_save_mod_target,
    write_save_mod_ids,
)

FIXTURE = Path(__file__).parent / "fixtures" / "save_profiles"


class SaveModDiscoveryTests(unittest.TestCase):
    def test_reads_explicit_save_list_and_reports_global_inheritance(self) -> None:
        before = (FIXTURE / "Sandbox" / "FixtureSave" / "mods.txt").read_bytes()

        result = discover_save_mod_lists(FIXTURE)

        self.assertEqual(len(result.saves_with_explicit_lists), 1)
        save = result.saves_with_explicit_lists[0]
        self.assertEqual(save.display_name, "Sandbox · FixtureSave")
        self.assertEqual(save.config.mods, ("SaveModFirst", "SaveModSecond"))
        self.assertEqual(save.config.maps, ("SaveMap",))
        self.assertEqual(result.inherited_global_count, 1)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            (FIXTURE / "Sandbox" / "FixtureSave" / "mods.txt").read_bytes(), before
        )

    def test_skips_malformed_and_oversized_save_lists_with_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Saves"
            malformed = root / "Sandbox" / "Malformed" / "mods.txt"
            malformed.parent.mkdir(parents=True)
            malformed.write_text("unknown data", encoding="utf-8")
            oversized = root / "Sandbox" / "Oversized" / "mods.txt"
            oversized.parent.mkdir()
            oversized.write_bytes(b"x" * (1024 * 1024 + 1))

            result = discover_save_mod_lists(root)

            self.assertEqual(result.saves_with_explicit_lists, ())
            self.assertEqual(len(result.diagnostics), 2)
            self.assertTrue(
                any("expected VERSION = 1" in item for item in result.diagnostics)
            )
            self.assertTrue(
                any("1 MiB size limit" in item for item in result.diagnostics)
            )

    def test_rejects_missing_or_linked_saves_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SaveModDiscoveryError):
                discover_save_mod_lists(root / "missing")

            linked = root / "linked"
            try:
                linked.symlink_to(root, target_is_directory=True)
            except OSError, NotImplementedError:
                self.skipTest(
                    "This Windows environment does not permit directory symlinks."
                )
            with self.assertRaisesRegex(SaveModDiscoveryError, "linked folders"):
                discover_save_mod_lists(linked)

    def test_save_target_write_backs_up_and_preserves_maps_bom_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "TargetSave"
            save.mkdir(parents=True)
            path = save / "mods.txt"
            original = (
                b"\xef\xbb\xbfVERSION = 1,\r\n\r\nmods\r\n{\r\n"
                b"    mod = OldMod,\r\n}\r\n\r\nmaps\r\n{\r\n"
                b"    map = OldMap,\r\n}\r\n"
            )
            path.write_bytes(original)

            snapshot = read_save_mod_target(root, save)
            backup = write_save_mod_ids(snapshot, ("NewMod", "SecondMod"))

            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_bytes(), original)
            updated = path.read_bytes()
            self.assertTrue(updated.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))
            readback = read_save_mod_target(root, save)
            self.assertEqual(readback.config.mods, ("NewMod", "SecondMod"))
            self.assertEqual(readback.config.maps, ("OldMap",))
            self.assertTrue(readback.config.has_utf8_bom)

    def test_creates_explicit_list_for_save_that_inherits_global(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "InheritedSave"
            save.mkdir(parents=True)

            snapshot = read_save_mod_target(root, save)
            self.assertTrue(snapshot.inherits_global_list)
            backup = write_save_mod_ids(snapshot, ("Core", "Addon"))

            self.assertIsNone(backup)
            result = read_save_mod_target(root, save)
            self.assertFalse(result.inherits_global_list)
            self.assertEqual(result.config.mods, ("Core", "Addon"))
            self.assertEqual(result.config.maps, ())

    def test_save_target_stale_snapshot_and_unsafe_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "TargetSave"
            save.mkdir(parents=True)
            path = save / "mods.txt"
            path.write_bytes(
                FIXTURE.joinpath("Sandbox", "FixtureSave", "mods.txt").read_bytes()
            )
            snapshot = read_save_mod_target(root, save)
            path.write_text("outside edit", encoding="utf-8")

            with self.assertRaises(ConcurrentSaveModChangeError):
                write_save_mod_ids(snapshot, ("Changed",))
            self.assertEqual(path.read_text(encoding="utf-8"), "outside edit")
            self.assertFalse(list(save.glob("mods.txt.bak-*")))
            with self.assertRaisesRegex(SaveModDiscoveryError, "exactly"):
                read_save_mod_target(root, root / "Sandbox")


if __name__ == "__main__":
    unittest.main()
