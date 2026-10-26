from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from test_collection_import import catalog_html

from zomboid_mod_manager.collection_deployment import load_collection
from zomboid_mod_manager.collection_store import CollectionStore, CollectionStoreError
from zomboid_mod_manager.discovery.scanner import scan_mods
from zomboid_mod_manager.local_install import install_local_mod
from zomboid_mod_manager.profiles import ModProfile
from zomboid_mod_manager.ui.collection_browser_dialog import CollectionBrowserDialog
from zomboid_mod_manager.workshop import WorkshopItemMetadata
from zomboid_mod_manager.workshop_catalog import (
    browse_collections,
    parse_collection_page,
)


class LocalInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.local = self.root / "Zomboid/mods"
        self.local.mkdir(parents=True)
        self.source = self.root / "download"
        self.make_entry(self.source / "mods/A", "A")
        self.make_entry(self.source / "mods/B", "B", versioned=True)
        self.downloader = Mock()
        self.downloader.download.return_value = self.source
        metadata = patch(
            "zomboid_mod_manager.local_install.fetch_item_metadata",
            return_value=WorkshopItemMetadata("123", "Example", "", 108600, 1),
        )
        self.metadata = metadata.start()
        self.addCleanup(metadata.stop)

    def make_entry(self, path, mod_id, *, versioned=False):
        info = path / "42/mod.info" if versioned else path / "mod.info"
        info.parent.mkdir(parents=True)
        info.write_text(f"id={mod_id}\nname={mod_id}\n", encoding="utf-8")
        (info.parent / "media").mkdir()
        (info.parent / "media/data.lua").write_text("example", encoding="utf-8")

    def install(self, **kwargs):
        return install_local_mod("123", self.local, self.downloader, **kwargs)

    def test_entries_are_local_persistent_and_idempotent_without_global_list_write(
        self,
    ):
        config = self.local / "default.txt"
        config.write_text("unchanged")
        paths = self.install()
        self.assertEqual(
            {e.mod_id for e in scan_mods(local_roots=[self.local]).entries},
            {"A", "B"},
        )
        self.assertEqual(self.install(), paths)
        self.assertEqual(config.read_text(), "unchanged")
        self.assertFalse((self.root / "collections").exists())
        load_collection(
            CollectionStore(self.root / "collections"),
            ModProfile("Empty", ()),
            self.local,
            [self.local],
        )
        self.assertTrue(all(p.is_dir() for p in paths))
        self.assertTrue(
            all(
                e.source == "local" for e in scan_mods(local_roots=[self.local]).entries
            )
        )

    def test_existing_mod_id_or_changed_destination_blocks_all_writes(self):
        self.make_entry(self.local / "UsersMod", "A")
        with self.assertRaisesRegex(CollectionStoreError, "already installed"):
            self.install()
        self.assertEqual([p.name for p in self.local.iterdir()], ["UsersMod"])

    def test_modified_repeat_is_not_overwritten(self):
        paths = self.install()
        (paths[0] / "mod.info").write_text("id=A\nname=User edit\n")
        with self.assertRaisesRegex(CollectionStoreError, "differs"):
            self.install()
        self.assertIn("User edit", (paths[0] / "mod.info").read_text())

    def test_cancel_during_commit_restores_all_prepared_folders(self):
        rename = os.rename
        cancelled = False

        def move(source, target):
            nonlocal cancelled
            rename(source, target)
            if Path(target).parent == self.local:
                cancelled = True

        with (
            patch("zomboid_mod_manager.local_install.os.rename", side_effect=move),
            self.assertRaises(CollectionStoreError),
        ):
            self.install(cancelled=lambda: cancelled)
        self.assertEqual(list(self.local.iterdir()), [])
        self.assertTrue(
            list(
                self.root.glob(
                    "Zomboid/.zomboidsorter-local-install-*/WorkshopLocal_123_1"
                )
            )
        )

    def test_failed_second_move_rolls_back_first(self):
        rename = os.rename

        def move(source, target):
            if Path(target).parent == self.local and Path(target).name.endswith("_2"):
                raise OSError("fixture failure")
            rename(source, target)

        with (
            patch("zomboid_mod_manager.local_install.os.rename", side_effect=move),
            self.assertRaises(OSError),
        ):
            self.install()
        self.assertEqual(list(self.local.iterdir()), [])

    def test_missing_target_cancel_and_wrong_app_do_not_download(self):
        with self.assertRaises(CollectionStoreError):
            install_local_mod("123", self.root / "missing", self.downloader)
        with self.assertRaises(CollectionStoreError):
            self.install(cancelled=lambda: True)
        self.metadata.return_value = WorkshopItemMetadata(
            "123", "Other game", "", 42, 1
        )
        with self.assertRaises(CollectionStoreError):
            self.install()
        self.downloader.download.assert_not_called()

    def test_unreadable_or_duplicate_ids_do_not_install(self):
        self.make_entry(self.source / "mods/C", "A")
        with self.assertRaisesRegex(CollectionStoreError, "duplicate"):
            self.install()
        self.assertEqual(list(self.local.iterdir()), [])


class ModCatalogTests(unittest.TestCase):
    def html(self):
        return catalog_html(
            [
                {
                    "publishedfileid": "123",
                    "consumer_appid": 108600,
                    "file_type": 0,
                    "creator": "42",
                    "title": "Local Example",
                    "subscriptions": 123456,
                    "favorited": 51,
                    "tags": [{"tag": "Build 42"}],
                },
                {"publishedfileid": "124", "consumer_appid": 108600, "file_type": 2},
                {"publishedfileid": "125", "consumer_appid": 42, "file_type": 0},
            ],
            section="readytouseitems",
        )

    def test_mod_metadata_filters_and_correct_catalog_url(self):
        page = parse_collection_page(self.html(), mods=True)
        self.assertEqual(len(page.collections), 1)
        row = page.collections[0]
        self.assertEqual(
            (row.author, row.subscribers, row.tags), ("Creator", 123456, ("Build 42",))
        )
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = self.html().encode()
        with patch(
            "zomboid_mod_manager.workshop_catalog.urlopen", return_value=response
        ) as request:
            browse_collections("test", mods=True, sort="toprated", build="Build 42")
        self.assertIn("section=readytouseitems", request.call_args.args[0].full_url)

    def test_native_mod_browser_shows_subscribers_and_selects_install(self):
        app = QApplication.instance() or QApplication([])
        app.setFont(QFont("Segoe UI", 10))
        with patch.object(CollectionBrowserDialog, "_new_search"):
            dialog = CollectionBrowserDialog(mods=True)
            dialog._show_page(parse_collection_page(self.html(), mods=True))
            dialog.table.selectRow(0)
            dialog._set_busy(False)
            self.assertEqual(dialog.table.item(0, 2).text(), "123,456")
            self.assertIn("123,456 subscribers", dialog.details.toPlainText())
            self.assertEqual(dialog.choose.text(), "Install Locally…")
            dialog.resize(740, 540)
            dialog.show()
            app.processEvents()
            if os.environ.get("ZOMBOIDSORTER_CAPTURE_MOD_BROWSER"):
                dialog.grab().save(os.environ["ZOMBOIDSORTER_CAPTURE_MOD_BROWSER"])
            dialog._choose()
            self.assertEqual(dialog.selected_collection.workshop_id, "123")
            dialog.close()


if __name__ == "__main__":
    unittest.main()
