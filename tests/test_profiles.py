from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zomboid_mod_manager.portable import (
    app_data_directory,
    portable_data_directory,
    portable_settings_path,
)
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    parse_profile,
    serialize_profile,
)


class ProfileTests(unittest.TestCase):
    def test_portable_marker_keeps_app_data_beside_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_directory = Path(temporary)
            (app_directory / "portable.flag").touch()
            with patch(
                "zomboid_mod_manager.portable.application_directory",
                return_value=app_directory,
            ):
                self.assertEqual(portable_data_directory(), app_directory / "data")
                self.assertEqual(app_data_directory(), app_directory / "data")
                self.assertEqual(
                    portable_settings_path(), app_directory / "data" / "settings.ini"
                )
                self.assertEqual(
                    ProfileStore().root, app_directory / "data" / "profiles"
                )

    def test_profile_round_trip_preserves_order_and_unavailable_ids(self) -> None:
        profile = ModProfile(
            "B42 Co-op",
            ("WorkshopMod", "MissingLocalMod", "MapMod"),
            ("123456789", "987654321"),
            ("Riverside, KY", "NorthMap"),
        )
        serialized = serialize_profile(profile)
        self.assertIn(b'"schemaVersion": 3', serialized)
        self.assertEqual(parse_profile(serialized), profile)

    def test_profile_validation_rejects_bad_names_and_duplicate_ids(self) -> None:
        for profile in (
            ModProfile("../escape", ("Mod",)),
            ModProfile("CON", ("Mod",)),
            ModProfile("Valid", ("Mod", "Mod")),
        ):
            with self.subTest(profile=profile), self.assertRaises(ProfileError):
                serialize_profile(profile)

    def test_store_save_overwrite_backup_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(Path(temporary) / "profiles")
            first = ModProfile("Solo", ("Base", "MapPack"))
            self.assertIsNone(store.save(first))
            store.save(ModProfile("Solo", ("Base",)), overwrite=True)
            self.assertEqual(store.load("Solo").mod_ids, ("Base",))
            backups = list((store.backup_root).glob("Solo.json.*"))
            self.assertEqual(len(backups), 1)
            store.restore_backup("Solo", backups[0])
            self.assertEqual(store.load("Solo"), first)

    def test_import_export_and_reversible_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileStore(root / "profiles")
            exported = root / "shared-profile.json"
            shared_profile = ModProfile(
                "Shared",
                ("Z", "A"),
                ("123456789",),
                ("Riverside, KY", "NorthMap"),
            )
            store.save(shared_profile)
            store.export("Shared", exported)
            imported_store = ProfileStore(root / "other-profiles")
            imported, _ = imported_store.import_file(exported)
            self.assertEqual(imported, shared_profile)

            deleted = store.delete("Shared")
            self.assertEqual(store.list_names(), ())
            restored = store.restore_deleted(deleted)
            self.assertEqual(restored, shared_profile)
            self.assertEqual(store.load("Shared"), restored)

    def test_import_rejects_unknown_schema(self) -> None:
        with self.assertRaises(ProfileError):
            parse_profile(b'{"schemaVersion": 2, "name": "x", "modIds": []}')
        old_profile = parse_profile(
            b'{"schemaVersion": 1, "name": "Old", "modIds": ["A"]}'
        )
        self.assertEqual(old_profile, ModProfile("Old", ("A",)))
        old_workshop_profile = parse_profile(
            b'{"schemaVersion": 2, "name": "Older", "modIds": ["A"], '
            b'"workshopIds": ["123"]}'
        )
        self.assertEqual(old_workshop_profile, ModProfile("Older", ("A",), ("123",)))
        self.assertIn(b'"schemaVersion": 2', serialize_profile(old_workshop_profile))

    def test_profile_validation_rejects_bad_map_ids(self) -> None:
        for map_ids in (("Map", "Map"), ("Map", " bad"), ("Map\nOther",)):
            with self.subTest(map_ids=map_ids), self.assertRaises(ProfileError):
                serialize_profile(
                    ModProfile("Invalid map pack", ("Mod",), map_ids=map_ids)
                )
        with self.assertRaises(ProfileError):
            parse_profile(
                b'{"schemaVersion":3,"name":"Invalid map pack",'
                b'"modIds":[],"workshopIds":[],"mapIds":null}'
            )


if __name__ == "__main__":
    unittest.main()
