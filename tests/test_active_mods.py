from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.configuration import (
    list_active_configuration_backups,
    restore_active_configuration,
)
from zomboid_mod_manager.gameio.active_mods import (
    ActiveModConfig,
    ActiveModConfigError,
    ConcurrentConfigChangeError,
    parse_active_mod_config,
    read_active_mods,
    write_active_configuration,
    write_active_mods,
)

FIXTURE = Path(__file__).parent / "fixtures" / "config" / "default.txt"


def _default_path(root: str) -> Path:
    mods_dir = Path(root) / "Zomboid" / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    return mods_dir / "default.txt"


class ActiveModConfigTests(unittest.TestCase):
    def test_parses_global_mods_and_maps_preserving_order(self) -> None:
        config = parse_active_mod_config(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(config.version, 1)
        self.assertEqual(config.mods, ("ModAlpha", "Mod Beta"))
        self.assertEqual(config.maps, ("ExampleMap",))

    def test_rejects_unsupported_or_malformed_config_without_guessing(self) -> None:
        for text in (
            "VERSION = 2,\nmods\n{\n}\nmaps\n{\n}\n",
            "VERSION = 1,\nmods\n{\nmod = A,\n",
            "VERSION = 1,\nmods\nmod = A,\n}\nmaps\n{\n}\n",
            "VERSION = 1,\nmods\n{\nmod = A,\n}\nmaps\n{\nunknown = B,\n}\n",
            "VERSION = 1,\nmods\n{\nmod = A,\nmod = A,\n}\nmaps\n{\n}\n",
        ):
            with self.subTest(text=text), self.assertRaises(ActiveModConfigError):
                parse_active_mod_config(text)

    def test_write_backs_up_atomically_and_preserves_maps(self) -> None:
        original = FIXTURE.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            path = _default_path(temporary)
            path.write_bytes(original)
            snapshot = read_active_mods(path)
            backup = write_active_mods(snapshot, ("Mod Beta", "ModGamma"))

            self.assertEqual(backup.read_bytes(), original)
            updated = read_active_mods(path)
            self.assertEqual(updated.config.mods, ("Mod Beta", "ModGamma"))
            self.assertEqual(updated.config.maps, ("ExampleMap",))
            self.assertEqual(updated.config.newline, "\n")
            self.assertFalse(list(Path(temporary).glob("*.tmp")))

    def test_write_preserves_utf8_bom_and_crlf(self) -> None:
        content = b"\xef\xbb\xbfVERSION = 1,\r\n\r\nmods\r\n{\r\n    mod = Alpha,\r\n}\r\n\r\nmaps\r\n{\r\n}\r\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = _default_path(temporary)
            path.write_bytes(content)
            backup = write_active_mods(read_active_mods(path), ("Beta",))
            updated = path.read_bytes()
            self.assertEqual(backup.read_bytes(), content)
            self.assertTrue(updated.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", updated)
            self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))
            self.assertEqual(read_active_mods(path).config.mods, ("Beta",))

    def test_concurrent_edit_aborts_before_backup_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = _default_path(temporary)
            path.write_bytes(FIXTURE.read_bytes())
            snapshot = read_active_mods(path)
            path.write_text("external edit", encoding="utf-8")
            with self.assertRaises(ConcurrentConfigChangeError):
                write_active_mods(snapshot, ("ModGamma",))
            self.assertEqual(path.read_text(encoding="utf-8"), "external edit")
            self.assertFalse(list(Path(temporary).glob("*.bak-*")))

    def test_write_refuses_non_global_and_save_scoped_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in (
                root / "default.txt",
                root / "Zomboid" / "Saves" / "slot" / "mods" / "default.txt",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(FIXTURE.read_bytes())
                original = path.read_bytes()
                with self.subTest(path=path), self.assertRaises(ActiveModConfigError):
                    write_active_mods(read_active_mods(path), ("Changed",))
                self.assertEqual(path.read_bytes(), original)

    def test_restore_backup_restores_mods_maps_and_keeps_current_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = _default_path(temporary)
            original = FIXTURE.read_bytes()
            path.write_bytes(original)
            original_config = read_active_mods(path).config
            current_config = ActiveModConfig(
                version=1,
                mods=("Changed", "AnotherMod"),
                maps=("ChangedMap",),
                newline="\r\n",
                has_utf8_bom=True,
            )
            write_active_configuration(read_active_mods(path), current_config)
            current_bytes = path.read_bytes()
            backup_path = path.with_name("default.txt.bak-20261023T120000.000000")
            backup_path.write_bytes(original)

            snapshot = read_active_mods(path)
            listed = list_active_configuration_backups(snapshot)
            self.assertIn(backup_path, listed)

            current_backup = restore_active_configuration(snapshot, backup_path)

            restored = read_active_mods(path)
            self.assertEqual(restored.config, original_config)
            self.assertEqual(current_backup.read_bytes(), current_bytes)

    def test_restore_rejects_backup_outside_selected_config_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = _default_path(temporary)
            path.write_bytes(FIXTURE.read_bytes())
            outside = root / "outside" / "default.txt.bak-20261023"
            outside.parent.mkdir()
            outside.write_bytes(FIXTURE.read_bytes())
            snapshot = read_active_mods(path)

            with self.assertRaises(ActiveModConfigError):
                restore_active_configuration(snapshot, outside)

            self.assertEqual(path.read_bytes(), FIXTURE.read_bytes())


if __name__ == "__main__":
    unittest.main()
