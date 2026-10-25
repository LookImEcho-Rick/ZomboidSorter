from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.workshop import (
    PZ_APP_ID,
    WorkshopApiError,
    WorkshopCollectionResult,
    WorkshopItemMetadata,
    fetch_collection,
    parse_published_file_id,
    resolve_collection_import,
)


class WorkshopTests(unittest.TestCase):
    def test_accepts_numeric_ids_and_steam_collection_urls(self) -> None:
        self.assertEqual(parse_published_file_id("1234567890"), "1234567890")
        self.assertEqual(
            parse_published_file_id(
                "https://steamcommunity.com/sharedfiles/filedetails/?id=1234567890"
            ),
            "1234567890",
        )

    def test_rejects_non_steam_urls_and_ambiguous_ids(self) -> None:
        for value in (
            "https://example.com/sharedfiles/filedetails/?id=1234567890",
            "https://steamcommunity.com/sharedfiles/filedetails/?id=1&id=2",
            "https://steamcommunity.com/profiles/1234567890",
            "abc123",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_published_file_id(value)

    def test_collection_import_returns_only_project_zomboid_items(self) -> None:
        collection_response = {
            "response": {
                "collectiondetails": [
                    {
                        "publishedfileid": "9000000001",
                        "result": 1,
                        "children": [
                            {"publishedfileid": "2000000002", "sortorder": 2},
                            {"publishedfileid": "2000000001", "sortorder": 1},
                            {"publishedfileid": "2000000001", "sortorder": 3},
                            {"publishedfileid": "2000000003", "sortorder": 4},
                            {"publishedfileid": "2000000004", "sortorder": 5},
                        ],
                    }
                ]
            }
        }
        details_response = {
            "response": {
                "publishedfiledetails": [
                    {
                        "publishedfileid": "2000000001",
                        "result": 1,
                        "consumer_app_id": PZ_APP_ID,
                        "title": "First mod",
                        "description": "one",
                        "time_updated": 10,
                    },
                    {
                        "publishedfileid": "2000000002",
                        "result": 1,
                        "consumer_appid": PZ_APP_ID,
                        "title": "Second mod",
                        "description": "two",
                        "time_updated": 20,
                    },
                    {"publishedfileid": "2000000003", "result": 9},
                    {
                        "publishedfileid": "2000000004",
                        "result": 1,
                        "consumer_appid": 42,
                        "title": "Not a Zomboid item",
                    },
                ]
            }
        }
        with patch(
            "zomboid_mod_manager.workshop._post_json",
            side_effect=[collection_response, details_response],
        ) as post:
            result = fetch_collection(
                "https://steamcommunity.com/sharedfiles/filedetails/?id=9000000001"
            )

        self.assertEqual(result.collection_id, "9000000001")
        self.assertEqual(
            [item.workshop_id for item in result.items], ["2000000001", "2000000002"]
        )
        self.assertEqual(
            [item.title for item in result.items], ["First mod", "Second mod"]
        )
        self.assertEqual(result.unavailable_ids, ("2000000003",))
        self.assertEqual(result.foreign_app_ids, ("2000000004",))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args_list[0].args[1]["publishedfileids[0]"], "9000000001"
        )

    def test_refuses_inaccessible_collection_and_excessive_size(self) -> None:
        invalid = {
            "response": {"collectiondetails": [{"publishedfileid": "7", "result": 9}]}
        }
        with (
            patch("zomboid_mod_manager.workshop._post_json", return_value=invalid),
            self.assertRaises(WorkshopApiError),
        ):
            fetch_collection("7")

        children = [{"publishedfileid": str(i + 100), "sortorder": i} for i in range(3)]
        too_many = {
            "response": {
                "collectiondetails": [
                    {"publishedfileid": "8", "result": 1, "children": children}
                ]
            }
        }
        with (
            patch("zomboid_mod_manager.workshop._post_json", return_value=too_many),
            self.assertRaises(WorkshopApiError),
        ):
            fetch_collection("8", max_items=2)

    def test_resolves_installed_items_missing_ids_and_duplicate_mod_ids(self) -> None:
        fixture_root = Path(__file__).parent / "fixtures"
        scan = scan_mods(
            local_roots=[fixture_root / "local_mods"],
            workshop_roots=[fixture_root / "workshop"],
        )
        collection = WorkshopCollectionResult(
            collection_id="999999999",
            items=(
                WorkshopItemMetadata("111111111", "Legacy", "", PZ_APP_ID, None),
                WorkshopItemMetadata("222222222", "Bundle", "", PZ_APP_ID, None),
                WorkshopItemMetadata("999999999", "Missing", "", PZ_APP_ID, None),
            ),
            unavailable_ids=("888888888",),
            foreign_app_ids=("777777777",),
        )
        plan = resolve_collection_import(collection, scan)
        self.assertEqual(plan.installed_ids, ("111111111", "222222222"))
        self.assertEqual(plan.missing_ids, ("888888888", "999999999"))
        self.assertEqual(plan.mod_ids, ("LegacyWorkshop", "BundleAddon"))
        self.assertEqual(plan.ambiguous_mod_ids, ("BundleCore",))
        self.assertNotIn("777777777", plan.workshop_ids)


if __name__ == "__main__":
    unittest.main()
