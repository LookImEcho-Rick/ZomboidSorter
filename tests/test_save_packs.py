from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.profiles import ModProfile, ProfileStore
from zomboid_mod_manager.save_packs import (
    SaveAssignmentStore,
    SavePackError,
    discover_saves,
    save_key,
)


class SavePackTests(unittest.TestCase):
    def test_discovers_only_immediate_mode_and_save_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Saves"
            (root / "Sandbox" / "Rosewood").mkdir(parents=True)
            (root / "Sandbox" / "Rosewood" / "nested").mkdir()
            (root / "Apocalypse" / "West Point").mkdir(parents=True)
            (root / "Loose folder").mkdir()

            saves = discover_saves(root)

            self.assertEqual(
                tuple((save.mode, save.name) for save in saves),
                (("Apocalypse", "West Point"), ("Sandbox", "Rosewood")),
            )
            self.assertEqual(saves[1].key, "sandbox/rosewood")

    def test_assignment_is_one_to_one_and_persists_in_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SaveAssignmentStore(Path(temporary) / "app-data")
            key = save_key("Sandbox", "Rosewood")

            store.assign(key, "Default")
            self.assertEqual(store.assigned_pack(key), "Default")
            self.assertEqual(store.list_for_pack("default"), (key,))

            store.assign(key, "Weekend Pack")
            self.assertEqual(store.assigned_pack(key), "Weekend Pack")
            self.assertEqual(store.list_for_pack("Default"), ())
            self.assertEqual(store.list_for_pack("Weekend Pack"), (key,))

            reopened = SaveAssignmentStore(Path(temporary) / "app-data")
            reopened.unassign(key, "Default")
            self.assertEqual(reopened.assigned_pack(key), "Weekend Pack")
            reopened.unassign(key, "Weekend Pack")
            self.assertIsNone(reopened.assigned_pack(key))

    def test_assignment_index_rejects_corrupt_or_non_normalized_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "save-assignments.json"
            store = SaveAssignmentStore(root)
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "assignments": {"Sandbox/Rosewood": "Default"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SavePackError):
                store.list_for_pack("Default")

            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(SavePackError):
                store.assigned_pack("sandbox/rosewood")

    def test_save_key_rejects_paths(self) -> None:
        for mode, name in (("..", "World"), ("Sandbox", "../World"), ("", "World")):
            with self.subTest(mode=mode, name=name), self.assertRaises(SavePackError):
                save_key(mode, name)

    def test_fresh_profile_store_seeds_one_empty_default_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(Path(temporary) / "profiles")

            self.assertTrue(store.ensure_default_pack())
            self.assertEqual(store.list_names(), ("Default",))
            default = store.load("Default")
            self.assertEqual(default, ModProfile("Default", (), (), ()))
            self.assertFalse(store.ensure_default_pack())

            store.save(ModProfile("Default", ("PlayerMod",)), overwrite=True)
            self.assertEqual(store.load("Default").mod_ids, ("PlayerMod",))

    def test_existing_packs_do_not_get_a_new_default_afterward(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(Path(temporary) / "profiles")
            store.save(ModProfile("Custom", ("A",)))

            self.assertFalse(store.ensure_default_pack())
            self.assertEqual(store.list_names(), ("Custom",))
            store.delete("Custom")
            self.assertFalse(store.ensure_default_pack())
            self.assertEqual(store.list_names(), ())


if __name__ == "__main__":
    unittest.main()
