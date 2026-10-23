from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    parse_profile,
    serialize_profile,
)


class ProfileTests(unittest.TestCase):
    def test_profile_round_trip_preserves_order_and_unavailable_ids(self) -> None:
        profile = ModProfile(
            "B42 Co-op",
            ("WorkshopMod", "MissingLocalMod", "MapMod"),
            ("123456789", "987654321"),
        )
        self.assertEqual(parse_profile(serialize_profile(profile)), profile)

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
            store.save(ModProfile("Shared", ("Z", "A")))
            store.export("Shared", exported)
            imported_store = ProfileStore(root / "other-profiles")
            imported, _ = imported_store.import_file(exported)
            self.assertEqual(imported, ModProfile("Shared", ("Z", "A")))

            deleted = store.delete("Shared")
            self.assertEqual(store.list_names(), ())
            restored = store.restore_deleted(deleted)
            self.assertEqual(restored, ModProfile("Shared", ("Z", "A")))
            self.assertEqual(store.load("Shared"), restored)

    def test_import_rejects_unknown_schema(self) -> None:
        with self.assertRaises(ProfileError):
            parse_profile(b'{"schemaVersion": 2, "name": "x", "modIds": []}')
        old_profile = parse_profile(
            b'{"schemaVersion": 1, "name": "Old", "modIds": ["A"]}'
        )
        self.assertEqual(old_profile, ModProfile("Old", ("A",)))


if __name__ == "__main__":
    unittest.main()
