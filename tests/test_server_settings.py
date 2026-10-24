from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.gameio.server_settings import (
    ConcurrentServerSettingsChangeError,
    ServerSettingsError,
    list_server_settings_backups,
    parse_server_settings,
    read_server_settings,
    read_server_settings_backup,
    restore_server_settings_backup,
    write_server_settings,
)


class ServerSettingsTests(unittest.TestCase):
    def _path(self, root: Path) -> Path:
        path = root / "Zomboid" / "Server" / "servertest.ini"
        path.parent.mkdir(parents=True)
        path.write_text(
            "# keep this comment\n"
            "Mods=OldMod;SecondMod\n"
            "WorkshopItems=123456;789012\n"
            "Map=Riverside, KY;West Point, KY\n"
            "PVP=true\n",
            encoding="utf-8",
        )
        return path

    def test_parses_distinct_mod_and_workshop_lists(self) -> None:
        config = parse_server_settings(
            "Mods=ModOne;ModTwo\nWorkshopItems=123;456\nOther=kept\n"
        )
        self.assertEqual(config.mods, ("ModOne", "ModTwo"))
        self.assertEqual(config.workshop_items, ("123", "456"))

    def test_rejects_ambiguous_or_malformed_server_lists(self) -> None:
        for text in (
            "Mods=A\nWorkshopItems=1\nMods=B\n",
            "Mods=A;;B\nWorkshopItems=1\n",
            "Mods=A\nWorkshopItems=not-a-number\n",
            "Mods=A\nOther=1\n",
        ):
            with self.subTest(text=text), self.assertRaises(ServerSettingsError):
                parse_server_settings(text)

    def test_updates_only_mod_lists_with_backup_and_preserves_other_settings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._path(Path(temporary))
            before = path.read_bytes()
            snapshot = read_server_settings(path)

            backup = write_server_settings(
                snapshot,
                mods=("NewMod", "Local Mod"),
                workshop_items=("999",),
            )

            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_bytes(), before)
            output = path.read_text(encoding="utf-8")
            self.assertIn("# keep this comment\n", output)
            self.assertIn("Mods=NewMod;Local Mod\n", output)
            self.assertIn("WorkshopItems=999\n", output)
            self.assertIn("Map=Riverside, KY;West Point, KY\n", output)
            self.assertIn("PVP=true\n", output)
            self.assertEqual(
                read_server_settings(path).config.mods, ("NewMod", "Local Mod")
            )

    def test_preserves_bom_crlf_and_rejects_concurrent_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._path(Path(temporary))
            path.write_bytes(
                b"\xef\xbb\xbf# test\r\nMods=Old\r\n"
                b"WorkshopItems=123\r\nMap=Somewhere\r\n"
            )
            snapshot = read_server_settings(path)
            backup = write_server_settings(
                snapshot, mods=("New",), workshop_items=("456",)
            )
            self.assertIsNotNone(backup)
            updated = path.read_bytes()
            self.assertTrue(updated.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))
            self.assertIn(b"Map=Somewhere\r\n", updated)

            stale = read_server_settings(path)
            path.write_text("external edit", encoding="utf-8")
            with self.assertRaises(ConcurrentServerSettingsChangeError):
                write_server_settings(stale, mods=("Third",), workshop_items=("789",))
            self.assertEqual(path.read_text(encoding="utf-8"), "external edit")

    def test_rejects_non_server_target_without_changing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "ordinary.ini"
            path.write_text("Mods=A\nWorkshopItems=1\n", encoding="utf-8")
            original = path.read_bytes()

            with self.assertRaisesRegex(ServerSettingsError, r"<Zomboid>/Server"):
                read_server_settings(path)

            self.assertEqual(path.read_bytes(), original)

    def test_restore_backup_restores_exact_bytes_and_backs_up_current_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._path(Path(temporary))
            original = path.read_bytes()
            initial = read_server_settings(path)
            old_backup = write_server_settings(
                initial, mods=("Changed",), workshop_items=("999",)
            )
            current = path.read_bytes()
            snapshot = read_server_settings(path)
            self.assertEqual(list_server_settings_backups(snapshot), (old_backup,))
            backup = read_server_settings_backup(snapshot, old_backup)

            current_backup = restore_server_settings_backup(snapshot, backup)

            self.assertIsNotNone(current_backup)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(current_backup.read_bytes(), current)
            self.assertEqual(
                read_server_settings(path).config.mods, ("OldMod", "SecondMod")
            )

    def test_restore_rejects_stale_snapshot_and_foreign_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._path(root)
            initial = read_server_settings(path)
            backup_path = write_server_settings(
                initial, mods=("Changed",), workshop_items=("999",)
            )
            snapshot = read_server_settings(path)
            with self.assertRaisesRegex(ServerSettingsError, "beside"):
                read_server_settings_backup(snapshot, root / "elsewhere.ini.bak-backup")
            backup = read_server_settings_backup(snapshot, backup_path)
            path.write_text("external edit", encoding="utf-8")

            with self.assertRaises(ConcurrentServerSettingsChangeError):
                restore_server_settings_backup(snapshot, backup)
            self.assertEqual(path.read_text(encoding="utf-8"), "external edit")


if __name__ == "__main__":
    unittest.main()
