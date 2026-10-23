from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.diagnostics.file_overlaps import analyze_file_overlaps
from zomboid_mod_manager.discovery.scanner import scan_mods


class FileOverlapTests(unittest.TestCase):
    def test_different_shared_file_is_reported_with_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            for folder, mod_id, body in (
                ("First", "FirstMod", "first"),
                ("Second", "SecondMod", "second"),
            ):
                entry = root / folder
                (entry / "media" / "scripts").mkdir(parents=True)
                (entry / "mod.info").write_text(
                    f"name={folder}\nid={mod_id}\n", encoding="utf-8"
                )
                (entry / "media" / "scripts" / "shared.lua").write_text(
                    body, encoding="utf-8"
                )
                (entry / "icon.png").write_text(body, encoding="utf-8")

            report = analyze_file_overlaps(scan_mods(local_roots=[root]))
            self.assertEqual(len(report.overlaps), 1)
            overlap = report.overlaps[0]
            self.assertEqual(overlap.relative_path, "media/scripts/shared.lua")
            self.assertEqual(
                {overlap.first_mod_id, overlap.second_mod_id}, {"FirstMod", "SecondMod"}
            )
            self.assertEqual(overlap.content_relation, "different")
            self.assertTrue(overlap.first_file.is_file())

    def test_identical_files_and_alternate_candidates_of_same_entry_are_ignored(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            common = root / "One" / "common"
            version = root / "One" / "42.21"
            other = root / "Two" / "common"
            for entry in (common, version, other):
                (entry / "media" / "scripts").mkdir(parents=True)
                (entry / "mod.info").write_text(
                    "name=Shared\nid=SharedMod\n", encoding="utf-8"
                )
                (entry / "media" / "scripts" / "shared.lua").write_text(
                    "same", encoding="utf-8"
                )

            report = analyze_file_overlaps(scan_mods(local_roots=[root]))
            self.assertEqual(report.overlaps, ())

    def test_candidate_roots_are_not_walked_as_part_of_root_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            entry = root / "One"
            (entry / "media" / "scripts").mkdir(parents=True)
            (entry / "common" / "media" / "scripts").mkdir(parents=True)
            (entry / "mod.info").write_text("name=One\nid=OneMod\n", encoding="utf-8")
            (entry / "common" / "mod.info").write_text(
                "name=One\nid=OneMod\n", encoding="utf-8"
            )
            (entry / "media" / "scripts" / "root.lua").write_text(
                "root", encoding="utf-8"
            )
            (entry / "common" / "media" / "scripts" / "common.lua").write_text(
                "common", encoding="utf-8"
            )

            report = analyze_file_overlaps(scan_mods(local_roots=[root]))
            self.assertEqual(report.overlaps, ())
            self.assertEqual(report.candidate_count, 2)


if __name__ == "__main__":
    unittest.main()
