from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from zomboid_mod_manager.collection_store import CollectionStore
from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.profiles import (
    CollectionContent,
    ModProfile,
    ProfileStore,
    suggest_profile_name,
    validate_profile,
)
from zomboid_mod_manager.steamcmd import SteamCmdDownloader
from zomboid_mod_manager.ui.collection_browser_dialog import CollectionBrowserDialog
from zomboid_mod_manager.ui.workshop_dialog import (
    DuplicateModIdResolutionDialog,
    WorkshopCollectionDialog,
)
from zomboid_mod_manager.workshop import (
    WorkshopApiError,
    WorkshopCollectionResult,
    WorkshopItemMetadata,
    fetch_collection,
)
from zomboid_mod_manager.workshop_catalog import (
    CollectionPage,
    CollectionSummary,
    browse_collections,
    parse_collection_page,
)
from zomboid_mod_manager.workshop_install import installed_collection_ids

FIXTURES = Path(__file__).parent / "fixtures"


def catalog_html(items=None, *, section="collections"):
    queries = [
        {
            "queryKey": ["workshop_browse", {"appid": 108600, "section": section}],
            "state": {
                "data": {
                    "eresult": 1,
                    "results": items
                    if items is not None
                    else [
                        {
                            "publishedfileid": "123",
                            "consumer_appid": 108600,
                            "file_type": 2,
                            "title": "A <collection>",
                            "creator": "42",
                            "num_children": 200,
                            "favorited": 99,
                            "tags": [{"tag": "Build 42"}],
                        }
                    ],
                    "total_pages": 8,
                    "total_count": 240,
                }
            },
        },
        {
            "queryKey": ["PlayerLinkDetails", "42"],
            "state": {"data": {"public_data": {"persona_name": "Creator"}}},
        },
    ]
    return (
        '<script type="application/json" id="valve-ssr-data">'
        + json.dumps({"renderContext": {"queryData": json.dumps({"queries": queries})}})
        + "</script>"
    )


class CatalogTests(unittest.TestCase):
    def test_parses_native_catalog_metadata_and_empty_results(self):
        page = parse_collection_page(catalog_html(), page=2)
        self.assertEqual((page.page, page.total_pages, page.total_count), (2, 8, 240))
        row = page.collections[0]
        self.assertEqual(
            (row.title, row.author, row.item_count, row.favorites, row.tags),
            ("A <collection>", "Creator", 200, 99, ("Build 42",)),
        )
        self.assertEqual(parse_collection_page(catalog_html([])).collections, ())

    def test_filters_foreign_apps_noncollections_and_duplicates(self):
        rows = [
            {"publishedfileid": "1", "consumer_appid": 108600, "file_type": 2},
            {"publishedfileid": "2", "consumer_appid": 42, "file_type": 2},
            {"publishedfileid": "3", "consumer_appid": 108600, "file_type": 0},
        ]
        page = parse_collection_page(catalog_html(rows + rows))
        self.assertEqual([r.workshop_id for r in page.collections], ["1"])

    def test_format_change_and_noncollection_query_fail_visibly(self):
        for html in (
            "<html>Login</html>",
            catalog_html(section="items"),
            '<script id="valve-ssr-data">{bad}</script>',
        ):
            with self.subTest(html=html), self.assertRaises(WorkshopApiError):
                parse_collection_page(html)

    def test_search_sort_page_and_tag_are_encoded_in_fixed_steam_url(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = catalog_html().encode()
        with patch(
            "zomboid_mod_manager.workshop_catalog.urlopen", return_value=response
        ) as request:
            browse_collections("cats & dogs", sort="toprated", page=3, build="Build 42")
        url = request.call_args.args[0].full_url
        self.assertTrue(url.startswith("https://steamcommunity.com/workshop/browse/?"))
        for value in (
            "section=collections",
            "searchtext=cats+%26+dogs",
            "p=3",
            "requiredtags%5B%5D=Build+42",
            "browsesort=toprated",
        ):
            self.assertIn(value, url)
        for args in ({"sort": "bad"}, {"page": 0}, {"build": "anything"}):
            with self.assertRaises(ValueError):
                browse_collections(**args)

    def test_nested_collections_expand_in_order_without_subscribing_to_collection_ids(
        self,
    ):
        def details(id, children):
            return {
                "response": {
                    "collectiondetails": [
                        {
                            "publishedfileid": id,
                            "result": 1,
                            "children": [
                                {
                                    "publishedfileid": i,
                                    "sortorder": n,
                                    "filetype": 2 if i == "20" else 0,
                                }
                                for n, i in enumerate(children)
                            ],
                        }
                    ]
                }
            }

        def metadata(rows):
            return {
                "response": {
                    "publishedfiledetails": [
                        {
                            "publishedfileid": id,
                            "result": 1,
                            "consumer_app_id": 108600,
                        }
                        for id, kind in rows
                    ]
                }
            }

        with patch(
            "zomboid_mod_manager.workshop._post_json",
            side_effect=[
                details("10", ["1", "20", "3"]),
                metadata([("1", 0), ("20", 2), ("3", 0)]),
                details("20", ["2", "1"]),
                metadata([("2", 0), ("1", 0)]),
            ],
        ):
            result = fetch_collection("10")
        self.assertEqual([x.workshop_id for x in result.items], ["1", "2", "3"])

    def test_nested_cycle_and_cancel_refuse_partial_result(self):
        with self.assertRaises(WorkshopApiError):
            fetch_collection("10", _ancestors=("10",))
        with (
            patch("zomboid_mod_manager.workshop._post_json") as request,
            self.assertRaises(WorkshopApiError),
        ):
            fetch_collection("10", cancelled=lambda: True)
        request.assert_not_called()

    def test_download_completion_requires_current_steam_receipt_and_folder(self):
        collection = WorkshopCollectionResult(
            "99", (WorkshopItemMetadata("123", "Item", "", 108600, 20),)
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "steamapps/workshop/content/108600"
            (root / "123").mkdir(parents=True)
            manifest = root.parent.parent / "appworkshop_108600.acf"
            self.assertEqual(installed_collection_ids(collection, [root]), set())

            def write(timestamp=20, latest="100"):
                manifest.write_text(
                    '"AppWorkshop" { "WorkshopItemsInstalled" { "123" { "manifest" "100" "timeupdated" "'
                    + str(timestamp)
                    + '" } } "WorkshopItemDetails" { "123" { "manifest" "'
                    + latest
                    + '" } } }'
                )

            write()
            self.assertEqual(installed_collection_ids(collection, [root]), {"123"})
            write(timestamp=19)
            self.assertEqual(installed_collection_ids(collection, [root]), set())
            write(latest="101")
            self.assertEqual(installed_collection_ids(collection, [root]), set())
            manifest.write_text('"AppWorkshop" { "WorkshopItemsInstalled" {')
            self.assertEqual(installed_collection_ids(collection, [root]), set())
            manifest.write_text('"AppWorkshop" "invalid"')
            self.assertEqual(installed_collection_ids(collection, [root]), set())
            manifest.write_text(
                '"AppWorkshop" { "WorkshopItemsInstalled" { "123" { "manifest" { "invalid" "shape" } } } }'
            )
            self.assertEqual(installed_collection_ids(collection, [root]), set())


class CollectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, save=None, profile_store=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        scan = scan_mods(local_roots=[], workshop_roots=[FIXTURES / "workshop"])
        dialog = WorkshopCollectionDialog(
            scan,
            collection_store=CollectionStore(Path(temp.name) / "collections"),
            downloader=Mock(),
            profile_store=profile_store,
            save_profile=save,
        )
        dialog._show_collection(
            WorkshopCollectionResult(
                "99", (WorkshopItemMetadata("111111111", "Legacy", "", 108600, None),)
            )
        )
        self.addCleanup(dialog.deleteLater)
        return dialog, scan

    def wait(self, dialog):
        deadline = time.monotonic() + 3
        while dialog._worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(dialog._worker)

    def test_catalog_selection_description_empty_state_and_choose(self):
        with patch.object(CollectionBrowserDialog, "_new_search"):
            dialog = CollectionBrowserDialog()
            row = CollectionSummary(
                "123", "Title", "Author", "Description", 20, 15, 0, ("Build 42",)
            )
            dialog._show_page(CollectionPage((row,), 1, 2, 31))
            dialog.table.setCurrentCell(0, 0)
            self.assertTrue(dialog.choose.isEnabled())
            self.assertIn("Description", dialog.details.toPlainText())
            dialog._choose()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_collection, row)
            dialog._show_page(CollectionPage((), 1, 1, 0))
            self.assertFalse(dialog.choose.isEnabled())
            self.assertIn("No collections match", dialog.status.text())
            dialog.deleteLater()

    def test_private_download_is_saved_without_loading_or_discovering_content(self):
        save = Mock(return_value=True)
        dialog, _ = self.dialog(save)
        profile = ModProfile("Steam Collection 99", ("LegacyWorkshop",), ("111111111",))
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.download_collection",
            return_value=profile,
        ) as download:
            dialog._start_install()
            self.wait(dialog)
        download.assert_called_once()
        save.assert_called_once_with(profile)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(dialog.downloads_checked)

    def test_revisited_collection_shows_the_named_saved_pack_and_its_mods(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = ProfileStore(Path(tmp) / "profiles")
            profiles.save(
                ModProfile(
                    "My Collection Name",
                    ("Legacy",),
                    ("111111111",),
                    None,
                    (CollectionContent("111111111", "0" * 64),),
                )
            )
            dialog, _ = self.dialog(profile_store=profiles)
            self.assertEqual(dialog.profile_name.text(), "My Collection Name")
            self.assertEqual(
                dialog.items.item(0, 3).text(), "Saved · My Collection Name"
            )
            self.assertEqual(dialog.install_button.text(), "Update Saved Pack")
            self.assertIn("not installed locally", dialog.status.text())
            self.assertNotIn("missing or unavailable", dialog.status.text())

    def test_duplicate_resolution_requires_a_choice_and_excludes_the_other_item(self):
        collection = WorkshopCollectionResult(
            "99",
            (
                WorkshopItemMetadata("111", "First", "", 108600, None),
                WorkshopItemMetadata("222", "Second", "", 108600, None),
            ),
        )
        dialog = DuplicateModIdResolutionDialog(
            collection, {"SharedMod": ("111", "222")}
        )
        self.assertFalse(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )
        choice = dialog._choices["SharedMod"][1]
        choice.setCurrentIndex(1)
        self.assertTrue(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )
        self.assertEqual(dialog.excluded_workshop_ids(), {"222"})
        dialog.deleteLater()

    def test_revisited_collection_marks_verified_unreferenced_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tools/steamcmd"
            workshop = root / "steamapps/workshop/content/108600"
            (workshop / "111111111").mkdir(parents=True)
            manifest = workshop.parent.parent / "appworkshop_108600.acf"
            manifest.write_text(
                '"AppWorkshop" { "WorkshopItemsInstalled" { '
                '"111111111" { "manifest" "100" "timeupdated" "1" } '
                '} "WorkshopItemDetails" { "111111111" { "manifest" "100" } } }',
                encoding="utf-8",
            )
            dialog, _ = self.dialog()
            dialog._downloader = SteamCmdDownloader(root)
            dialog._show_collection(dialog._collection)
            self.assertEqual(dialog.items.item(0, 3).text(), "Downloaded")
            self.assertIn("already downloaded privately", dialog.status.text())

    def test_failed_download_does_not_save_partial_pack(self):
        save = Mock()
        dialog, _ = self.dialog(save)
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.download_collection",
            side_effect=RuntimeError("Download rejected"),
        ):
            dialog._start_install()
            self.wait(dialog)
        save.assert_not_called()
        self.assertIn("Download rejected", dialog.status.text())
        self.assertTrue(dialog.install_button.isEnabled())

    def test_save_failure_retries_without_downloading_again(self):
        save = Mock(side_effect=[False, True])
        dialog, _ = self.dialog(save)
        profile = ModProfile("Steam Collection 99", ("LegacyWorkshop",), ("111111111",))
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.download_collection",
            return_value=profile,
        ) as download:
            dialog._start_install()
            self.wait(dialog)
            self.assertEqual(dialog.install_button.text(), "Retry Save")
            dialog._start_install()
        self.assertEqual(download.call_count, 1)
        self.assertEqual(save.call_count, 2)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_async_fetch_enables_import_after_worker_finishes(self):
        dialog, _ = self.dialog()
        collection = dialog._collection
        dialog.collection_input.setText("99")
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.fetch_collection",
            return_value=collection,
        ):
            dialog._fetch()
            self.assertFalse(dialog.install_button.isEnabled())
            self.wait(dialog)
        self.assertTrue(dialog.install_button.isEnabled())

    def test_incomplete_list_requires_explicit_confirmation(self):
        save = Mock()
        dialog, _ = self.dialog(save)
        dialog._show_collection(
            WorkshopCollectionResult(
                "99", (WorkshopItemMetadata("404", "Missing", "", 108600, None),)
            )
        )
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            dialog._create_profile()
        save.assert_not_called()

    def test_catalog_close_defers_without_blocking_ui(self):
        with patch.object(CollectionBrowserDialog, "_new_search"):
            dialog = CollectionBrowserDialog()
            worker = Mock()
            dialog._worker = worker
            dialog.reject()
            self.assertTrue(dialog._closing)
            worker.wait.assert_not_called()
            dialog._finished()
            dialog.deleteLater()

    def test_collection_titles_become_valid_editable_pack_names(self):
        for title in ('Build 42: A/B "Pack"?', "CON", "...", "  A\nB  ", "x" * 200):
            validate_profile(
                ModProfile(
                    suggest_profile_name(title, fallback="Steam Collection 123"), ()
                )
            )


if __name__ == "__main__":
    unittest.main()
