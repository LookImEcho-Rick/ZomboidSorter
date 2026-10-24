import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zomboid_mod_manager.discovery.scanner import ScanCancelled, scan_mods

FIXTURES = Path(__file__).parent / "fixtures"


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = scan_mods(
            local_roots=[FIXTURES / "local_mods"],
            workshop_roots=[FIXTURES / "workshop"],
        )

    def test_build_41_root_workshop_entry_is_found(self) -> None:
        legacy = next(
            entry for entry in self.result.entries if entry.mod_id == "LegacyWorkshop"
        )
        self.assertEqual(legacy.source, "workshop")
        self.assertEqual(legacy.workshop_id, "111111111")
        self.assertEqual(legacy.candidates[0].layout, "root (Build 41 style)")

    def test_workshop_item_keeps_multiple_mods_and_version_candidates(self) -> None:
        item = next(
            item
            for item in self.result.workshop_items
            if item.workshop_id == "222222222"
        )
        self.assertEqual(
            {entry.mod_id for entry in item.entries},
            {"BundleCore", "BundleAddon", None},
        )
        core = next(entry for entry in item.entries if entry.mod_id == "BundleCore")
        self.assertEqual(len(core.candidates), 2)
        self.assertIn("common (shared)", core.layout_summary)
        self.assertIn("versioned (42.15)", core.layout_summary)
        self.assertEqual(core.requirements_raw, "BaseLib")

    def test_local_mod_and_duplicate_mod_id_are_preserved(self) -> None:
        duplicates = [
            entry for entry in self.result.entries if entry.mod_id == "BundleCore"
        ]
        self.assertEqual(len(duplicates), 2)
        self.assertEqual({entry.source for entry in duplicates}, {"local", "workshop"})
        self.assertTrue(
            any(
                "appears in 2 installed entries" in d.message
                for d in self.result.diagnostics
            )
        )

    def test_duplicate_workshop_item_in_multiple_scan_roots_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            roots = [Path(temporary) / "library-a", Path(temporary) / "library-b"]
            for index, root in enumerate(roots):
                entry = root / "777777777"
                entry.mkdir(parents=True)
                (entry / "mod.info").write_text(
                    f"name=Copy {index}\nid=Copy{index}\n", encoding="utf-8"
                )
            result = scan_mods(workshop_roots=roots)
            self.assertEqual(len(result.workshop_items), 2)
            self.assertTrue(
                any(
                    "Workshop item '777777777' is present in 2 scanned locations"
                    in item.message
                    for item in result.diagnostics
                )
            )

    def test_invalid_and_missing_metadata_are_reported(self) -> None:
        invalid = next(
            entry for entry in self.result.entries if entry.name == "Invalid Entry"
        )
        self.assertIsNone(invalid.mod_id)
        self.assertTrue(
            any("Missing required Mod ID" in warning for warning in invalid.diagnostics)
        )
        self.assertTrue(
            any("no recognized mod.info" in d.message for d in self.result.diagnostics)
        )
        self.assertTrue(
            any(
                item.workshop_id == "333333333" and item.diagnostics
                for item in self.result.workshop_items
            )
        )

    def test_parser_splits_once_and_retains_description_continuation(self) -> None:
        local = next(
            entry for entry in self.result.entries if entry.mod_id == "LocalShared"
        )
        common = next(
            candidate
            for candidate in local.candidates
            if candidate.layout == "common (shared)"
        )
        self.assertEqual(
            common.fields["description"],
            "First line with equals a=b\nsecond description line",
        )
        self.assertEqual(common.fields["require"], "BaseLib, OtherLib")

    def test_repeated_description_fields_are_combined_without_warning(self) -> None:
        entry = next(
            entry
            for entry in self.result.entries
            if entry.mod_id == "RepeatedDescription"
        )
        candidate = entry.candidates[0]
        self.assertEqual(
            candidate.fields["description"],
            "First description line\n\nFinal description line",
        )
        self.assertEqual(candidate.fields["poster"], "poster.png\nshowcase.png")
        self.assertEqual(
            candidate.fields["pack"], "ExampleTexturePack\nExampleOverlayPack"
        )
        self.assertEqual(
            candidate.fields["tiledef"], "example_tiles 1000\nexample_overlays 2000"
        )
        self.assertFalse(
            any(
                "Duplicate metadata key 'description'" in d
                for d in candidate.diagnostics
            )
        )
        self.assertFalse(
            any("Duplicate metadata key 'poster'" in d for d in candidate.diagnostics)
        )
        self.assertFalse(
            any("Duplicate metadata key 'pack'" in d for d in candidate.diagnostics)
        )
        self.assertFalse(
            any("Duplicate metadata key 'tiledef'" in d for d in candidate.diagnostics)
        )

    def test_oversized_and_unreadable_metadata_are_diagnosed_without_stopping_scan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            oversized = root / "Oversized"
            unreadable = root / "Unreadable"
            readable = root / "Readable"
            for entry in (oversized, unreadable, readable):
                entry.mkdir(parents=True)
            oversized_metadata = oversized / "mod.info"
            oversized_metadata.write_bytes(b"x" * (1024 * 1024 + 1))
            unreadable_metadata = unreadable / "mod.info"
            unreadable_metadata.write_text(
                "name=Unreadable\nid=Unreadable\n", encoding="utf-8"
            )
            (readable / "mod.info").write_text(
                "name=Readable\nid=Readable\n", encoding="utf-8"
            )

            real_open = os.open

            def open_or_deny(path, *args, **kwargs):
                if Path(path) == unreadable_metadata:
                    raise PermissionError("fixture permission denied")
                return real_open(path, *args, **kwargs)

            with patch(
                "zomboid_mod_manager.discovery.scanner.os.open",
                side_effect=open_or_deny,
            ):
                result = scan_mods(local_roots=[root])

            self.assertIn("Readable", {entry.mod_id for entry in result.entries})
            candidates = {
                entry.entry_path.name: entry.candidates[0] for entry in result.entries
            }
            self.assertTrue(
                any(
                    "exceeds the 1 MiB size limit" in message
                    for message in candidates["Oversized"].diagnostics
                )
            )
            self.assertTrue(
                any(
                    "Could not read mod.info" in message
                    for message in candidates["Unreadable"].diagnostics
                )
            )

    def test_metadata_invalid_as_utf8_and_windows_1252_is_diagnosed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            entry_path = root / "InvalidEncoding"
            entry_path.mkdir(parents=True)
            (entry_path / "mod.info").write_bytes(b"name=Invalid\nid=Bad\x81\n")

            result = scan_mods(local_roots=[root])

            candidate = result.entries[0].candidates[0]
            self.assertTrue(
                any(
                    "UTF-8 or Windows-1252" in message
                    for message in candidate.diagnostics
                )
            )

    def test_linked_mod_metadata_is_skipped_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            entry_path = root / "LinkedMetadata"
            entry_path.mkdir(parents=True)
            link = entry_path / "mod.info"
            link.write_text("name=Linked\nid=Linked\n", encoding="utf-8")
            path_type = type(link)
            real_is_symlink = path_type.is_symlink

            def mark_metadata_as_link(path: Path) -> bool:
                if path == link:
                    return True
                return real_is_symlink(path)

            with patch.object(path_type, "is_symlink", new=mark_metadata_as_link):
                result = scan_mods(local_roots=[root])

            self.assertFalse(result.entries)
            self.assertTrue(
                any(
                    diagnostic.path == link and "linked paths" in diagnostic.message
                    for diagnostic in result.diagnostics
                )
            )

    def test_scan_cancellation_is_checked_after_progress_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            root.mkdir()
            cancel_requested = False
            progress_messages: list[str] = []

            def report_progress(message: str) -> None:
                nonlocal cancel_requested
                progress_messages.append(message)
                if message.startswith("Checking local mods:"):
                    cancel_requested = True

            with self.assertRaises(ScanCancelled):
                scan_mods(
                    local_roots=[root],
                    cancelled=lambda: cancel_requested,
                    progress=report_progress,
                )

            self.assertEqual(len(progress_messages), 1)
            self.assertTrue(progress_messages[0].startswith("Checking local mods:"))


if __name__ == "__main__":
    unittest.main()
