from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.gameio.save_mods import (
    SaveModDiscoveryError,
    discover_save_mod_lists,
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


if __name__ == "__main__":
    unittest.main()
