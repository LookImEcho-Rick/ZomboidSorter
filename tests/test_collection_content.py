from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from zomboid_mod_manager.collection_deployment import (
    CollectionDeployment,
    load_collection,
)
from zomboid_mod_manager.collection_import import (
    CollectionModIdConflict,
    download_collection,
    profile_from_cached_collection,
)
from zomboid_mod_manager.collection_store import (
    CollectionStore,
    CollectionStoreError,
    tree_digest,
)
from zomboid_mod_manager.discovery.scanner import merge_scan_results, scan_mods
from zomboid_mod_manager.domain import DetectedPaths
from zomboid_mod_manager.gameio.active_mods import read_active_mods
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
    parse_profile,
    serialize_profile,
)
from zomboid_mod_manager.steamcmd import SteamCmdDownloader, verify_valve_signature
from zomboid_mod_manager.ui.main_window import MainWindow
from zomboid_mod_manager.workshop import WorkshopCollectionResult, WorkshopItemMetadata


def make_item(root, mod_id="PackA", content="one"):
    entry = root / "mods" / mod_id
    (entry / "media").mkdir(parents=True)
    (entry / "mod.info").write_text(f"name={mod_id}\nid={mod_id}\n", encoding="utf-8")
    (entry / "media/example.lua").write_text(content, encoding="utf-8")
    return root


class CollectionContentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = CollectionStore(self.root / "app/collections")
        self.local = self.root / "Zomboid/mods"
        self.local.mkdir(parents=True)
        self.a = self.store.intern(make_item(self.root / "download-a"), "1")
        self.b = self.store.intern(
            make_item(self.root / "download-b", "PackB", "two"), "2"
        )
        self.profile_a = ModProfile("A", ("PackA",), ("1",), None, (self.a,))
        self.profile_b = ModProfile("B", ("PackB",), ("2",), None, (self.b,))

    def test_exact_content_is_shared_but_different_bytes_get_separate_objects(self):
        same = self.store.intern(make_item(self.root / "identical"), "99")
        self.assertEqual(same.sha256, self.a.sha256)
        self.assertEqual(len(list(self.store.content_root.iterdir())), 2)
        changed = self.store.intern(
            make_item(self.root / "changed", content="different"), "1"
        )
        self.assertNotEqual(changed.sha256, self.a.sha256)
        self.assertEqual(len(list(self.store.content_root.iterdir())), 3)

    def test_profile_v4_round_trip_preserves_exact_references_and_old_profiles(self):
        encoded = serialize_profile(self.profile_a)
        self.assertEqual(json.loads(encoded)["schemaVersion"], 4)
        self.assertEqual(parse_profile(encoded), self.profile_a)
        old = ModProfile("Legacy", ("Local",))
        self.assertEqual(parse_profile(serialize_profile(old)), old)
        value = json.loads(encoded)
        value["collectionContent"][0]["sha256"] = "../outside"
        with self.assertRaises(ProfileError):
            parse_profile(json.dumps(value).encode())

    def test_cache_is_hidden_until_loaded_switching_and_rollback_preserve_objects(self):
        self.assertEqual(scan_mods(local_roots=[self.local]).entries, ())
        transaction, result = load_collection(
            self.store, self.profile_a, self.local, [self.local]
        )
        self.assertEqual([e.mod_id for e in result.entries], ["PackA"])
        self.assertEqual(
            CollectionDeployment(self.local).loaded_profile(), self.profile_a
        )
        second, result = load_collection(
            self.store, self.profile_b, self.local, [self.local], result
        )
        self.assertEqual([e.mod_id for e in result.entries], ["PackB"])
        self.assertTrue(any((second.root / "previous").iterdir()))
        second.rollback()
        self.assertEqual(
            [e.mod_id for e in scan_mods(local_roots=[self.local]).entries], ["PackA"]
        )
        self.assertEqual(tree_digest(self.store.path(self.a)), self.a.sha256)
        self.assertTrue(transaction.activated)

    def test_changed_cache_is_refused_without_modifying_local_files(self):
        (self.store.path(self.a) / "mods/PackA/media/example.lua").write_text(
            "tampered"
        )
        with self.assertRaises(CollectionStoreError):
            load_collection(self.store, self.profile_a, self.local, [self.local])
        self.assertEqual(list(self.local.iterdir()), [])

    def test_collection_copy_takes_priority_without_overwriting_user_copy(self):
        own = make_item(self.root / "user", "PackA", "user version") / "mods/PackA"
        own.rename(self.local / "UsersMod")
        installed = scan_mods(local_roots=[self.local])
        transaction, result = load_collection(
            self.store, self.profile_a, self.local, [self.local], installed
        )
        preferred = merge_scan_results(
            result,
            result,
            preferred_mod_ids=self.profile_a.mod_ids,
            preferred_roots=tuple(
                self.local / record["name"] for record in transaction.new["folders"]
            ),
        )
        self.assertEqual(
            (self.local / "UsersMod/media/example.lua").read_text(), "user version"
        )
        self.assertEqual([entry.mod_id for entry in preferred.entries], ["PackA"])
        self.assertEqual(
            preferred.local_entries[0].entry_path.relative_to(self.local).parts[0],
            transaction.new["folders"][0]["name"],
        )
        self.assertEqual(
            (preferred.local_entries[0].entry_path / "media/example.lua").read_text(),
            "one",
        )

    def test_load_reuses_prior_workshop_scan_instead_of_scanning_workshop_roots(self):
        workshop = self.root / "workshop"
        make_item(workshop / "123", "WorkshopOnly", "workshop")
        previous = scan_mods(workshop_roots=[workshop])
        with patch(
            "zomboid_mod_manager.collection_deployment.scan_mods",
            wraps=scan_mods,
        ) as scan:
            _, result = load_collection(
                self.store, self.profile_a, self.local, [self.local], previous
            )
        self.assertEqual(scan.call_count, 1)
        self.assertNotIn("workshop_roots", scan.call_args.kwargs)
        self.assertEqual(
            [entry.mod_id for entry in result.entries], ["PackA", "WorkshopOnly"]
        )

    def test_modified_app_copy_is_preserved_and_blocks_switch(self):
        transaction, _ = load_collection(
            self.store, self.profile_a, self.local, [self.local]
        )
        folder = self.local / transaction.new["folders"][0]["name"]
        (folder / "media/example.lua").write_text("user edit")
        with self.assertRaises(CollectionStoreError):
            load_collection(self.store, self.profile_b, self.local, [self.local])
        self.assertEqual((folder / "media/example.lua").read_text(), "user edit")

    def test_activation_failure_restores_previous_folders_and_index(self):
        load_collection(self.store, self.profile_a, self.local, [self.local])
        deployment = CollectionDeployment(self.local)
        original = deployment.index.read_bytes()
        prepared = deployment.prepare(self.store, self.profile_b)
        rename = os.rename

        def fail_new(source, target):
            if Path(source).parent.name == "prepared":
                raise OSError("Simulated failed move")
            return rename(source, target)

        with (
            patch(
                "zomboid_mod_manager.collection_deployment.os.rename",
                side_effect=fail_new,
            ),
            self.assertRaises(OSError),
        ):
            prepared.activate()
        self.assertEqual(deployment.index.read_bytes(), original)
        self.assertEqual(
            [e.mod_id for e in scan_mods(local_roots=[self.local]).entries], ["PackA"]
        )

    def test_cancel_before_loading_does_not_publish_mod_folders(self):
        with self.assertRaises((CollectionStoreError, RuntimeError)):
            load_collection(
                self.store,
                self.profile_a,
                self.local,
                [self.local],
                cancelled=lambda: True,
            )
        self.assertEqual(list(self.local.iterdir()), [])

    def test_import_reuses_shared_content_and_does_not_deploy(self):
        item = WorkshopItemMetadata("1", "Test", "", 108600, None)
        collection = WorkshopCollectionResult("99", (item,))
        downloader = Mock()
        downloader.download.return_value = self.root / "download-a"
        first = download_collection(collection, "First", self.store, downloader)
        second = download_collection(collection, "Second", self.store, downloader)
        self.assertEqual(first.collection_content, second.collection_content)
        self.assertEqual(len(list(self.store.content_root.iterdir())), 2)
        self.assertEqual(list(self.local.iterdir()), [])

    def test_batch_import_saves_all_items_as_one_user_named_pack(self):
        first = make_item(self.root / "download-first", "FirstMod")
        second = make_item(self.root / "download-second", "SecondMod")
        items = (
            WorkshopItemMetadata("111", "First", "", 108600, None),
            WorkshopItemMetadata("222", "Second", "", 108600, None),
        )

        class BatchDownloader:
            def download_many(self, requested, *, on_downloaded, **_kwargs):
                for item in requested:
                    source = first if item.workshop_id == "111" else second
                    on_downloaded(item, source)

        profile = download_collection(
            WorkshopCollectionResult("99", items),
            "My Renamed Collection",
            self.store,
            BatchDownloader(),
        )
        self.assertEqual(profile.name, "My Renamed Collection")
        self.assertEqual(profile.mod_ids, ("FirstMod", "SecondMod"))
        self.assertEqual(profile.workshop_ids, ("111", "222"))
        self.assertEqual(
            tuple(item.workshop_id for item in profile.collection_content),
            ("111", "222"),
        )

    def test_duplicate_mod_ids_can_be_resolved_by_excluding_a_workshop_item(self):
        first = make_item(self.root / "duplicate-first", "SharedMod", "first")
        second = make_item(self.root / "duplicate-second", "SharedMod", "second")
        third = make_item(self.root / "unique", "UniqueMod", "unique")
        items = (
            WorkshopItemMetadata("111", "First copy", "", 108600, None),
            WorkshopItemMetadata("222", "Second copy", "", 108600, None),
            WorkshopItemMetadata("333", "Unique", "", 108600, None),
        )

        class BatchDownloader:
            def download_many(self, requested, *, on_downloaded, **_kwargs):
                sources = {"111": first, "222": second, "333": third}
                for item in requested:
                    on_downloaded(item, sources[item.workshop_id])

        collection = WorkshopCollectionResult("99", items)
        with self.assertRaises(CollectionModIdConflict) as raised:
            download_collection(
                collection, "Resolved Pack", self.store, BatchDownloader()
            )
        conflict = raised.exception
        self.assertEqual(conflict.duplicate_sources, {"SharedMod": ("111", "222")})

        profile = profile_from_cached_collection(
            collection,
            "Resolved Pack",
            conflict.references,
            conflict.scan_result,
            excluded_workshop_ids={"222"},
        )
        self.assertEqual(profile.name, "Resolved Pack")
        self.assertEqual(profile.mod_ids, ("SharedMod", "UniqueMod"))
        self.assertEqual(profile.workshop_ids, ("111", "333"))
        self.assertEqual(
            tuple(item.workshop_id for item in profile.collection_content),
            ("111", "333"),
        )

    def test_unavailable_items_do_not_start_download_or_save_partial_pack(self):
        downloader = Mock()
        with self.assertRaises(CollectionStoreError):
            download_collection(
                WorkshopCollectionResult("99", (), ("404",)),
                "Pack",
                self.store,
                downloader,
            )
        downloader.download.assert_not_called()

    def test_signature_check_does_not_trust_an_unsigned_tool(self):
        with (
            patch(
                "zomboid_mod_manager.steamcmd.subprocess.run",
                return_value=Mock(returncode=1),
            ),
            self.assertRaises(CollectionStoreError),
        ):
            verify_valve_signature(self.root / "unsigned.exe")

    def test_downloader_is_anonymous_and_checks_fresh_receipt_before_success(self):
        tool = self.root / "tool"
        tool.mkdir()
        downloader = SteamCmdDownloader(tool)
        item = WorkshopItemMetadata("123", "Mod", "", 108600, None)
        process = Mock()
        process.poll.return_value = 0

        def start(args, **kwargs):
            self.assertIn("anonymous", args)
            self.assertNotIn("subscribe", " ".join(args))
            kwargs["stdout"].write(b'Success. Downloaded item 123 to "test"')
            kwargs["stdout"].flush()
            return process

        with (
            patch("zomboid_mod_manager.steamcmd.subprocess.Popen", side_effect=start),
            patch("zomboid_mod_manager.steamcmd._ProcessJob"),
            patch(
                "zomboid_mod_manager.steamcmd.installed_collection_ids",
                return_value=set(),
            ),
            self.assertRaises(CollectionStoreError),
        ):
            downloader._download(tool / "steamcmd.exe", item)

    def test_batch_download_uses_one_anonymous_process_and_verifies_each_item(self):
        tool = self.root / "tool"
        tool.mkdir()
        downloader = SteamCmdDownloader(tool)
        items = (
            WorkshopItemMetadata("123", "First", "", 108600, None),
            WorkshopItemMetadata("456", "Second", "", 108600, None),
        )
        process = Mock()
        process.poll.return_value = 0
        calls = []

        def start(args, **kwargs):
            calls.append(args)
            kwargs["stdout"].write(
                b'Success. Downloaded item 123 to "first"\n'
                b'Success. Downloaded item 456 to "second"'
            )
            kwargs["stdout"].flush()
            return process

        downloaded = []
        with (
            patch("zomboid_mod_manager.steamcmd.subprocess.Popen", side_effect=start),
            patch("zomboid_mod_manager.steamcmd._ProcessJob"),
            patch(
                "zomboid_mod_manager.steamcmd.installed_collection_ids",
                return_value={"123", "456"},
            ),
        ):
            downloader._download_batch(
                tool / "steamcmd.exe",
                items,
                on_downloaded=lambda item, path: downloaded.append(
                    (item.workshop_id, path.name)
                ),
            )

        self.assertEqual(len(calls), 1)
        self.assertIn("anonymous", calls[0])
        self.assertEqual(calls[0].count("+workshop_download_item"), 2)
        self.assertEqual(downloaded, [("123", "123"), ("456", "456")])

    def test_batch_download_reuses_current_receipts_without_starting_steamcmd(self):
        downloader = SteamCmdDownloader(self.root / "tool")
        items = (
            WorkshopItemMetadata("123", "First", "", 108600, None),
            WorkshopItemMetadata("456", "Second", "", 108600, None),
        )
        downloaded = []
        with (
            patch(
                "zomboid_mod_manager.steamcmd.installed_collection_ids",
                return_value={"123", "456"},
            ),
            patch.object(downloader, "ensure_tool") as ensure_tool,
        ):
            downloader.download_many(
                items,
                on_downloaded=lambda item, path: downloaded.append(
                    (item.workshop_id, path.name)
                ),
            )
        ensure_tool.assert_not_called()
        self.assertEqual(downloaded, [("123", "123"), ("456", "456")])


class CollectionWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loading_applies_global_list_disabled_mod_can_be_readded_other_cache_hidden(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "Zomboid/mods"
            local.mkdir(parents=True)
            config = local / "default.txt"
            config.write_text("VERSION = 1,\nmods\n{\n}\nmaps\n{\n}\n")
            profiles = ProfileStore(root / "app/profiles")
            store = CollectionStore(root / "app/collections")
            a = store.intern(make_item(root / "download-a"), "1")
            b = store.intern(make_item(root / "download-b", "PackB"), "2")
            profile = ModProfile("A", ("PackA",), ("1",), None, (a,))
            profiles.save(profile)
            profiles.save(ModProfile("B", ("PackB",), ("2",), None, (b,)))
            window = MainWindow(
                DetectedPaths((), (), (), (), local),
                active_config_path=config,
                profile_store=profiles,
            )
            try:
                deadline = time.monotonic() + 5
                while window._worker is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertEqual(window.available_list.count(), 0)
                with patch(
                    "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    window._apply_mod_pack(profile)
                self.assertEqual(read_active_mods(config).config.mods, ("PackA",))
                self.assertEqual(window.active_list.count(), 1)
                self.assertEqual(window.available_list.count(), 0)
                window.active_list.setCurrentRow(0)
                window._stage_deactivate()
                self.assertEqual(window.available_list.count(), 1)
                self.assertEqual(
                    window.available_list.item(0).data(Qt.ItemDataRole.UserRole),
                    "PackA",
                )
                self.assertNotIn(
                    "PackB", [e.mod_id for e in window._last_result.entries]
                )
                window.available_list.setCurrentRow(0)
                window._stage_activate()
                self.assertEqual(window._staged_mod_ids, ["PackA"])
                self.assertIn("AVAILABLE MODS", window.inactive_heading.text())
                self.assertEqual(
                    window.main_tabs.tabText(
                        window.main_tabs.indexOf(window.setup_page)
                    ),
                    "Paths && Settings",
                )
                self.assertEqual(
                    window.main_tabs.tabText(window.library_tab_index),
                    "Library && Diagnostics",
                )
            finally:
                while any(w.isRunning() for w in window._background_workers()):
                    QTest.qWait(10)
                window.close()

    def test_loaded_collection_copy_is_selected_in_workspace_and_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "Zomboid/mods"
            local.mkdir(parents=True)
            config = local / "default.txt"
            config.write_text("VERSION = 1,\nmods\n{\n}\nmaps\n{\n}\n")
            store = CollectionStore(root / "app/collections")
            reference = store.intern(
                make_item(root / "download", "PackA", "collection"), "1"
            )
            user_entry = make_item(root / "user", "PackA", "user copy") / "mods/PackA"
            user_entry.rename(local / "UsersMod")
            profile = ModProfile("A", ("PackA",), ("1",), None, (reference,))
            load_collection(store, profile, local, [local])

            window = MainWindow(
                DetectedPaths((), (), (), (), local),
                active_config_path=config,
                profile_store=ProfileStore(root / "app/profiles"),
            )
            try:
                deadline = time.monotonic() + 5
                while window._worker is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIsNone(window._worker)
                self.assertEqual(
                    [entry.mod_id for entry in window._last_scan_result.entries],
                    ["PackA", "PackA"],
                )
                self.assertEqual(
                    [entry.mod_id for entry in window._last_result.entries], ["PackA"]
                )
                selected = window._last_result.entries[0]
                self.assertEqual(
                    (selected.entry_path / "media/example.lua").read_text(),
                    "collection",
                )
                self.assertEqual(
                    (local / "UsersMod/media/example.lua").read_text(), "user copy"
                )
                window._staged_mod_ids = ["PackA"]
                self.assertFalse(
                    any(
                        "appears in 2 installed entries" in warning
                        for warning in window._configuration_preflight_warnings()
                    )
                )
            finally:
                while any(w.isRunning() for w in window._background_workers()):
                    QTest.qWait(10)
                window.close()


if __name__ == "__main__":
    unittest.main()
