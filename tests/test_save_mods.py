from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.gameio.save_mods import (
    ConcurrentSaveModChangeError,
    SaveModDiscoveryError,
    discover_save_mod_lists,
    list_save_mod_backups,
    read_save_mod_backup,
    read_save_mod_target,
    reset_save_mod_target,
    restore_save_mod_backup,
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

    def test_restore_backup_restores_exact_bytes_and_backs_up_current_list(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "RestoreSave"
            save.mkdir(parents=True)
            path = save / "mods.txt"
            original = FIXTURE.joinpath(
                "Sandbox", "FixtureSave", "mods.txt"
            ).read_bytes()
            path.write_bytes(original)

            initial = read_save_mod_target(root, save)
            old_backup = write_save_mod_ids(initial, ("Changed", "Order"))
            current = path.read_bytes()
            snapshot = read_save_mod_target(root, save)
            self.assertEqual(list_save_mod_backups(snapshot), (old_backup,))
            backup = read_save_mod_backup(snapshot, old_backup)

            current_backup = restore_save_mod_backup(snapshot, backup)

            self.assertIsNotNone(current_backup)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(current_backup.read_bytes(), current)
            self.assertEqual(
                read_save_mod_target(root, save).config.mods,
                ("SaveModFirst", "SaveModSecond"),
            )

    def test_restore_rejects_stale_save_snapshot_and_foreign_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "RestoreSave"
            save.mkdir(parents=True)
            path = save / "mods.txt"
            path.write_bytes(
                FIXTURE.joinpath("Sandbox", "FixtureSave", "mods.txt").read_bytes()
            )
            initial = read_save_mod_target(root, save)
            backup_path = write_save_mod_ids(initial, ("Changed",))
            snapshot = read_save_mod_target(root, save)
            with self.assertRaisesRegex(SaveModDiscoveryError, "beside"):
                read_save_mod_backup(snapshot, Path(temporary) / "mods.txt.bak-other")
            backup = read_save_mod_backup(snapshot, backup_path)
            path.write_text("external edit", encoding="utf-8")

            with self.assertRaises(ConcurrentSaveModChangeError):
                restore_save_mod_backup(snapshot, backup)
            self.assertEqual(path.read_text(encoding="utf-8"), "external edit")

    def test_restore_backup_creates_explicit_list_for_inherited_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "InheritedSave"
            save.mkdir(parents=True)
            path = save / "mods.txt"
            backup_path = save / "mods.txt.bak-20261024-120000-000000"
            raw_backup = FIXTURE.joinpath(
                "Sandbox", "FixtureSave", "mods.txt"
            ).read_bytes()
            backup_path.write_bytes(raw_backup)

            snapshot = read_save_mod_target(root, save)
            self.assertTrue(snapshot.inherits_global_list)
            backup = read_save_mod_backup(snapshot, backup_path)
            current_backup = restore_save_mod_backup(snapshot, backup)

            self.assertIsNone(current_backup)
            self.assertEqual(path.read_bytes(), raw_backup)

    def test_reset_removes_explicit_list_after_backup_and_preserves_inheritance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "ResetSave"
            save.mkdir(parents=True)
            path = save / "mods.txt"
            original = FIXTURE.joinpath(
                "Sandbox", "FixtureSave", "mods.txt"
            ).read_bytes()
            path.write_bytes(original)
            snapshot = read_save_mod_target(root, save)

            backup = reset_save_mod_target(snapshot)

            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse(path.exists())
            self.assertTrue(read_save_mod_target(root, save).inherits_global_list)

    def test_reset_is_noop_for_inherited_save_and_rejects_stale_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Zomboid" / "Saves"
            save = root / "Sandbox" / "ResetSave"
            save.mkdir(parents=True)
            snapshot = read_save_mod_target(root, save)
            self.assertIsNone(reset_save_mod_target(snapshot))
            self.assertFalse(list(save.glob("mods.txt.bak-*")))

            path = save / "mods.txt"
            path.write_bytes(
                FIXTURE.joinpath("Sandbox", "FixtureSave", "mods.txt").read_bytes()
            )
            stale = read_save_mod_target(root, save)
            path.write_text("external edit", encoding="utf-8")
            with self.assertRaises(ConcurrentSaveModChangeError):
                reset_save_mod_target(stale)
            self.assertEqual(path.read_text(encoding="utf-8"), "external edit")

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
