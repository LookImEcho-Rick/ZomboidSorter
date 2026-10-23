from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.support_report import (
    build_support_report,
    format_support_report,
)


class SupportReportTests(unittest.TestCase):
    def test_report_aggregates_health_without_including_private_paths_or_ids(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="PrivateSupportUser-") as temporary:
            private_root = Path(temporary) / "PrivateWorkshopFolder"
            item_path = private_root / "900000001"
            item_path.mkdir(parents=True)
            (item_path / "mod.info").write_text(
                "name=Private Human Mod Name\nid=PrivateModIdentifier\n",
                encoding="utf-8",
            )
            result = scan_mods(workshop_roots=[private_root])
            report = build_support_report(
                app_version="0.1.7",
                build_id="a" * 40,
                python_version="3.14.0",
                pyside_version="6.12.0",
                qt_version="6.12.0",
                operating_system={
                    "name": "Windows",
                    "release": "11",
                    "architecture": "AMD64",
                },
                storage_mode="standard",
                selected_paths={
                    "game_installation": [],
                    "local_mods": [],
                    "workshop_content": [str(private_root)],
                    "global_mod_list": [],
                },
                scan_result=result,
                scan_duration_seconds=0.125,
                metadata_target="42",
                exact_game_version="Private Human Mod Name",
                detected_path_warning_count=0,
                active_configuration_loaded=True,
                staged_mod_ids=("PrivateModIdentifier", "MissingPrivateId"),
                ordering_rules_valid=True,
                ordering_rule_count=2,
            )

            serialized = format_support_report(report)

            self.assertEqual(report["paths"]["workshop_content"]["readable_count"], 1)
            self.assertEqual(report["discovery"]["workshop_item_count"], 1)
            self.assertEqual(report["discovery"]["workshop_mod_entry_count"], 1)
            self.assertEqual(report["discovery"]["scan_duration_ms"], 125)
            self.assertEqual(report["workspace"]["staged_mods_found"], 1)
            self.assertEqual(report["workspace"]["staged_mods_not_found"], 1)
            self.assertIsNone(report["settings"]["exact_game_version"])
            for private_value in (
                str(private_root),
                private_root.name,
                item_path.name,
                "Private Human Mod Name",
                "PrivateModIdentifier",
                "MissingPrivateId",
            ):
                self.assertNotIn(private_value, serialized)
            self.assertFalse(report["privacy"]["folder_paths_included"])
            self.assertFalse(report["privacy"]["mod_names_or_ids_included"])


if __name__ == "__main__":
    unittest.main()
