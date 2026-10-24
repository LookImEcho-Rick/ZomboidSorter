from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.discovery.version_selection import (
    declared_version_range_diagnostics,
    resolve_entry_metadata,
)


class VersionSelectionTests(unittest.TestCase):
    def _scan_entry(self, root: Path, files: dict[str, str]):
        entry_root = root / "Entry"
        for relative_path, content in files.items():
            path = entry_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        result = scan_mods(local_roots=[root])
        return {entry.mod_id: entry for entry in result.entries}

    def test_selects_the_highest_numeric_folder_at_or_below_the_game_build(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {
                    "common/mod.info": "name=Shared\nid=Example\n",
                    "42/mod.info": "name=Build 42\nid=Example\n",
                    "42.9/mod.info": "name=Build 42.9\nid=Example\n",
                    "42.10/mod.info": "name=Build 42.10\nid=Example\n",
                    "42.22/mod.info": "name=Future\nid=Example\n",
                },
            )

        selected = resolve_entry_metadata(entries["Example"], "42.21.0")
        self.assertEqual(selected.status, "selected-version")
        self.assertEqual(selected.candidates[0].version_folder, "42.10")

    def test_uses_shared_metadata_when_no_version_folder_is_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {
                    "common/mod.info": "name=Shared\nid=Example\n",
                    "42.20/mod.info": "name=Future\nid=Example\n",
                },
            )

        selected = resolve_entry_metadata(entries["Example"], "42.15.0")
        self.assertEqual(selected.status, "selected-common")
        self.assertEqual(selected.candidates[0].layout, "common (shared)")

    def test_explains_root_only_metadata_is_not_available_to_build_42(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {"mod.info": "name=Legacy Example\nid=Example\n"},
            )

        preview = resolve_entry_metadata(entries["Example"], "42")
        exact = resolve_entry_metadata(entries["Example"], "42.21.0")
        self.assertEqual(preview.status, "missing")
        self.assertEqual(exact.status, "missing")
        self.assertIn("root (Build 41 style)", preview.message)
        self.assertIn("Build 42 ignores root-level mod files", exact.message)

    def test_explains_build42_only_metadata_is_not_available_to_build_41(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {"42/mod.info": "name=Modern Example\nid=Example\n"},
            )

        selected = resolve_entry_metadata(entries["Example"], "41")
        self.assertEqual(selected.status, "build-41")
        self.assertFalse(selected.candidates)
        self.assertIn("Only Build 42", selected.message)
        self.assertIn("Build 41 requires root-level metadata", selected.message)

    def test_versioned_id_supersedes_common_id_for_the_same_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {
                    "common/mod.info": "name=Shared\nid=SharedID\n",
                    "42.10/mod.info": "name=Versioned\nid=VersionedID\n",
                },
            )

        shared = resolve_entry_metadata(entries["SharedID"], "42.15.0")
        versioned = resolve_entry_metadata(entries["VersionedID"], "42.15.0")
        self.assertEqual(shared.status, "superseded")
        self.assertIn("VersionedID", shared.message)
        self.assertEqual(versioned.status, "selected-version")
        self.assertEqual(versioned.candidates[0].version_folder, "42.10")

        older = resolve_entry_metadata(entries["SharedID"], "42.9.0")
        self.assertEqual(older.status, "selected-common")

    def test_rejects_non_numeric_game_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {"42/mod.info": "name=Example\nid=Example\n"},
            )

        selected = resolve_entry_metadata(entries["Example"], "42.beta")
        self.assertEqual(selected.status, "invalid")
        self.assertFalse(selected.candidates)

    def test_declared_game_version_bounds_are_checked_against_exact_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = self._scan_entry(
                Path(temporary),
                {
                    "42/mod.info": (
                        "name=Example\nid=Example\n"
                        "versionMin=42.20.0\nversionMax=42.22.0\n"
                    ),
                },
            )

        candidate = entries["Example"].candidates[0]
        too_old = declared_version_range_diagnostics(candidate, "42.19.0")
        too_new = declared_version_range_diagnostics(candidate, "42.23.0")
        compatible = declared_version_range_diagnostics(candidate, "42.21.0")
        self.assertEqual(len(too_old), 1)
        self.assertIn("minimum game version is 42.20.0", too_old[0])
        self.assertEqual(len(too_new), 1)
        self.assertIn("maximum game version is 42.22.0", too_new[0])
        self.assertEqual(compatible, ())


if __name__ == "__main__":
    unittest.main()
