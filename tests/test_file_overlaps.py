from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zomboid_mod_manager.diagnostics.file_overlaps import analyze_file_overlaps
from zomboid_mod_manager.discovery.scanner import scan_mods


class FileOverlapTests(unittest.TestCase):
    def _write_candidate_entry(self, root: Path, folder: str, mod_id: str) -> None:
        entry = root / folder
        candidates = {
            "": "root",
            "common": "common",
            "42.20": "42.20",
            "42.22": "42.22",
        }
        for candidate_folder, contents in candidates.items():
            candidate = entry / candidate_folder if candidate_folder else entry
            (candidate / "media" / "scripts").mkdir(parents=True)
            (candidate / "mod.info").write_text(
                f"name={folder}\nid={mod_id}\n", encoding="utf-8"
            )
            (candidate / "media" / "scripts" / "shared.lua").write_text(
                f"{mod_id}-{contents}", encoding="utf-8"
            )

    def test_selected_build_and_staged_mod_filter_limit_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            self._write_candidate_entry(root, "One", "OneMod")
            self._write_candidate_entry(root, "Two", "TwoMod")
            self._write_candidate_entry(root, "Inactive", "InactiveMod")
            result = scan_mods(local_roots=[root])

            report = analyze_file_overlaps(
                result,
                target_build="42.21.0",
                active_mod_ids=["OneMod", "TwoMod"],
            )

        self.assertEqual(report.target_build, "42.21.0")
        self.assertTrue(report.staged_only)
        self.assertEqual(report.entry_count, 2)
        self.assertEqual(report.candidate_count, 2)
        self.assertEqual(report.files_scanned, 2)
        self.assertEqual(report.overlap_count, 1)
        self.assertTrue(
            all(
                "42.20"
                in str(example.first_candidate.parent)
                + str(example.second_candidate.parent)
                for group in report.path_groups
                for example in group.examples
            )
        )

    def test_build_41_overlap_analysis_uses_root_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            self._write_candidate_entry(root, "One", "OneMod")
            self._write_candidate_entry(root, "Two", "TwoMod")
            report = analyze_file_overlaps(
                scan_mods(local_roots=[root]),
                target_build="41",
                active_mod_ids=("OneMod", "TwoMod"),
            )

        self.assertEqual(report.candidate_count, 2)
        self.assertEqual(report.files_scanned, 2)
        self.assertEqual(report.overlap_count, 1)
        self.assertTrue(
            all(
                example.first_candidate.parent.name == "One"
                or example.first_candidate.parent.name == "Two"
                for group in report.path_groups
                for example in group.examples
            )
        )

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
            self.assertEqual(report.different_count, 1)
            self.assertEqual(report.unverified_count, 0)
            self.assertEqual(report.unique_path_count, 1)
            self.assertEqual(len(report.path_groups), 1)
            self.assertEqual(report.path_groups[0].comparison_count, 1)
            self.assertEqual(report.path_groups[0].mod_ids, ("FirstMod", "SecondMod"))

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

    def test_path_group_counts_each_entry_pair_for_a_shared_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            for folder, mod_id, body in (
                ("One", "OneMod", "one"),
                ("Two", "TwoMod", "two"),
                ("Three", "ThreeMod", "three"),
            ):
                entry = root / folder
                (entry / "media" / "scripts").mkdir(parents=True)
                (entry / "mod.info").write_text(
                    f"name={folder}\nid={mod_id}\n", encoding="utf-8"
                )
                (entry / "media" / "scripts" / "shared.lua").write_text(
                    body, encoding="utf-8"
                )

            report = analyze_file_overlaps(scan_mods(local_roots=[root]))
            self.assertEqual(report.overlap_count, 3)
            self.assertEqual(report.unique_path_count, 1)
            self.assertEqual(report.different_count, 3)
            group = report.path_groups[0]
            self.assertEqual(group.relative_path, "media/scripts/shared.lua")
            self.assertEqual(group.comparison_count, 3)
            self.assertEqual(group.different_count, 3)
            self.assertEqual(group.mod_ids, ("OneMod", "ThreeMod", "TwoMod"))

    def test_path_group_keeps_unverified_status_and_source_example(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            for folder, mod_id, body in (
                ("One", "OneMod", "first"),
                ("Two", "TwoMod", "other"),
            ):
                entry = root / folder
                (entry / "media" / "scripts").mkdir(parents=True)
                (entry / "mod.info").write_text(
                    f"name={folder}\nid={mod_id}\n", encoding="utf-8"
                )
                (entry / "media" / "scripts" / "shared.lua").write_text(
                    body, encoding="utf-8"
                )

            with patch(
                "zomboid_mod_manager.diagnostics.file_overlaps._MAX_HASH_BYTES", 1
            ):
                report = analyze_file_overlaps(scan_mods(local_roots=[root]))

            self.assertEqual(report.overlap_count, 1)
            self.assertEqual(report.different_count, 0)
            self.assertEqual(report.unverified_count, 1)
            self.assertEqual(report.path_groups[0].unverified_count, 1)
            self.assertEqual(
                report.path_groups[0].examples[0].content_relation, "unverified"
            )

    def test_analyzer_retains_all_path_groups_for_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mods"
            for folder, mod_id in (("One", "OneMod"), ("Two", "TwoMod")):
                entry = root / folder
                scripts = entry / "media" / "scripts"
                scripts.mkdir(parents=True)
                (entry / "mod.info").write_text(
                    f"name={folder}\nid={mod_id}\n", encoding="utf-8"
                )
                for index in range(251):
                    (scripts / f"shared-{index:03}.lua").write_text(
                        f"{mod_id}-{index}", encoding="utf-8"
                    )

            report = analyze_file_overlaps(scan_mods(local_roots=[root]))

        self.assertEqual(report.unique_path_count, 251)
        self.assertEqual(len(report.path_groups), 251)
        self.assertFalse(report.path_groups_limited)


if __name__ == "__main__":
    unittest.main()
