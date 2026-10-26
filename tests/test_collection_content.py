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
    unload_collection,
)
from zomboid_mod_manager.collection_import import (
    CollectionModIdConflict,
    download_collection,
    profile_from_cached_collection,
)
from zomboid_mod_manager.collection_store import (
    CollectionStore,
    CollectionStoreError,
    copy_verified_tree,
    tree_digest,
    tree_digest_with_subtrees,
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

    def test_combined_tree_digest_matches_whole_item_and_entry_hashes(self):
        item = self.store.path(self.a)
        entry = item / "mods/PackA"
        media = entry / "media"
        item_digest, entry_digests = tree_digest_with_subtrees(item, [entry, media])
        self.assertEqual(item_digest, self.a.sha256)
        self.assertEqual(entry_digests[entry], tree_digest(entry))
        self.assertEqual(entry_digests[media], tree_digest(media))

    def test_verified_copy_reads_back_destination_without_rehashing_source(self):
        source = self.store.path(self.a) / "mods/PackA"
        destination = self.root / "copied/PackA"
        original_digest = tree_digest
        with patch(
            "zomboid_mod_manager.collection_store.tree_digest",
            wraps=original_digest,
        ) as digest:
            result = copy_verified_tree(
                source, destination, expected_digest=original_digest(source)
            )
        self.assertEqual(result, original_digest(source))
        self.assertEqual(digest.call_count, 1)
        self.assertEqual(digest.call_args.args[0], destination)

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

    def test_unload_archives_edited_owned_copy_without_hashing_its_contents(self):
        transaction, _ = load_collection(
            self.store, self.profile_a, self.local, [self.local]
        )
        name = transaction.new["folders"][0]["name"]
        owned_file = self.local / name / "media/example.lua"
        owned_file.write_text("edited but must remain recoverable")
        before_index = CollectionDeployment(self.local).index.read_bytes()

        with patch(
            "zomboid_mod_manager.collection_deployment.tree_digest",
            side_effect=AssertionError("fast unload should not read file contents"),
        ):
            unloaded, result = unload_collection(self.local, [self.local])

        archived = unloaded.root / "previous" / name / "media/example.lua"
        self.assertEqual(archived.read_text(), "edited but must remain recoverable")
        self.assertFalse((self.local / name).exists())
        state, _ = CollectionDeployment(self.local).read()
        self.assertEqual(state["folders"], [])
        self.assertEqual(state["schema"], 2)
        self.assertEqual(result.local_entries, ())
        self.assertNotEqual(
            CollectionDeployment(self.local).index.read_bytes(), before_index
        )

    def test_legacy_deployment_unload_falls_back_to_exact_content_hash(self):
        load_collection(self.store, self.profile_a, self.local, [self.local])
        deployment = CollectionDeployment(self.local)
        legacy = json.loads(deployment.index.read_text())
        legacy["schema"] = 1
        legacy["folders"] = [
            {"name": item["name"], "sha256": item["sha256"]}
            for item in legacy["folders"]
        ]
        deployment.index.write_text(json.dumps(legacy))

        with patch(
            "zomboid_mod_manager.collection_deployment.tree_digest",
            wraps=tree_digest,
        ) as digest:
            unload_collection(self.local, [self.local])

        digest.assert_called_once_with(
            self.local / legacy["folders"][0]["name"], cancelled=None
        )

    def test_changed_cache_is_refused_without_modifying_local_files(self):
        (self.store.path(self.a) / "mods/PackA/media/example.lua").write_text(
            "tampered"
        )
        with self.assertRaises(CollectionStoreError):
            load_collection(self.store, self.profile_a, self.local, [self.local])
        self.assertEqual(list(self.local.iterdir()), [])

    def test_reload_verifies_both_copies_without_copying_or_moving_folders(self):
        first, _ = load_collection(self.store, self.profile_a, self.local, [self.local])
        folder = self.local / first.new["folders"][0]["name"]
        with (
            patch(
                "zomboid_mod_manager.collection_deployment.copy_verified_tree"
            ) as copy,
            patch(
                "zomboid_mod_manager.collection_deployment.os.rename", wraps=os.rename
            ) as rename,
        ):
            second, _ = load_collection(
                self.store, self.profile_a, self.local, [self.local]
            )
            second.rollback()
        copy.assert_not_called()
        rename.assert_not_called()
        self.assertTrue(folder.is_dir())
        self.assertEqual(
            CollectionDeployment(self.local).loaded_profile(), self.profile_a
        )
        # Neither an edited deployed folder nor an edited cache may be reused.
        (folder / "media/example.lua").write_text("edited")
        with self.assertRaises(CollectionStoreError):
            load_collection(self.store, self.profile_a, self.local, [self.local])
        self.assertEqual((folder / "media/example.lua").read_text(), "edited")

    def test_switch_retains_shared_folder_and_rollback_restores_prior_pack(self):
        first, _ = load_collection(self.store, self.profile_a, self.local, [self.local])
        retained = first.new["folders"][0]["name"]
        combined = ModProfile(
            "Combined", ("PackA", "PackB"), ("1", "2"), None, (self.a, self.b)
        )
        from zomboid_mod_manager.collection_store import copy_verified_tree

        with patch(
            "zomboid_mod_manager.collection_deployment.copy_verified_tree",
            wraps=copy_verified_tree,
        ) as copy:
            second, result = load_collection(
                self.store, combined, self.local, [self.local]
            )
        self.assertEqual(copy.call_count, 1)
        self.assertEqual({e.mod_id for e in result.entries}, {"PackA", "PackB"})
        self.assertEqual(second.retained_names, {retained})
        self.assertFalse((second.root / "previous" / retained).exists())
        second.rollback()
        self.assertEqual(
            [e.mod_id for e in scan_mods(local_roots=[self.local]).entries], ["PackA"]
        )
        self.assertEqual(
            CollectionDeployment(self.local).loaded_profile(), self.profile_a
        )

    def test_reload_still_refuses_changed_cache_and_unowned_destination(self):
        first, _ = load_collection(self.store, self.profile_a, self.local, [self.local])
        deployed = self.local / first.new["folders"][0]["name"] / "media/example.lua"
        (self.store.path(self.a) / "mods/PackA/media/example.lua").write_text(
            "tampered cache"
        )
        with self.assertRaises(CollectionStoreError):
            load_collection(self.store, self.profile_a, self.local, [self.local])
        self.assertEqual(deployed.read_text(), "one")

        unowned = self.local / (
            "ZomboidSorter_" + tree_digest(self.store.path(self.b) / "mods/PackB")
        )
        unowned.mkdir()
        (unowned / "user.txt").write_text("preserve me")
        with self.assertRaisesRegex(CollectionStoreError, "unowned folder"):
            load_collection(self.store, self.profile_b, self.local, [self.local])
        self.assertEqual((unowned / "user.txt").read_text(), "preserve me")
        self.assertEqual(deployed.read_text(), "one")

    def test_retained_folder_is_rechecked_at_commit_and_cancellation_keeps_state(self):
        first, _ = load_collection(self.store, self.profile_a, self.local, [self.local])
        deployment = CollectionDeployment(self.local)
        before = deployment.index.read_bytes()
        prepared = deployment.prepare(self.store, self.profile_a)
        with self.assertRaises(CollectionStoreError):
            prepared.activate(cancelled=lambda: True)
        self.assertEqual(deployment.index.read_bytes(), before)
        changed = self.local / first.new["folders"][0]["name"] / "media/example.lua"
        changed.write_text("changed after preparation")
        with self.assertRaisesRegex(CollectionStoreError, "changed outside the app"):
            prepared.activate()
        self.assertEqual(changed.read_text(), "changed after preparation")
        self.assertEqual(deployment.index.read_bytes(), before)
        self.assertFalse(prepared.activated)

    def test_cancel_after_reusing_folder_rolls_back_new_copies_and_ownership(self):
        load_collection(self.store, self.profile_a, self.local, [self.local])
        combined = ModProfile(
            "Combined", ("PackA", "PackB"), ("1", "2"), None, (self.a, self.b)
        )
        before = CollectionDeployment(self.local).index.read_bytes()
        with (
            patch(
                "zomboid_mod_manager.collection_deployment.scan_mods",
                side_effect=RuntimeError("Cancelled during scan"),
            ),
            self.assertRaisesRegex(RuntimeError, "Cancelled during scan"),
        ):
            load_collection(self.store, combined, self.local, [self.local])
        self.assertEqual(CollectionDeployment(self.local).index.read_bytes(), before)
        self.assertEqual(
            [e.mod_id for e in scan_mods(local_roots=[self.local]).entries], ["PackA"]
        )

    def test_unreadable_metadata_names_the_workshop_item_and_keeps_cache(self):
        source = self.root / "not-a-mod"
        source.mkdir()
        (source / "readme.txt").write_text("No mod.info here")
        downloader = Mock()
        downloader.download.return_value = source
        cached = []
        with self.assertRaisesRegex(
            CollectionStoreError, "Broken item \\(Workshop ID 123\\)"
        ) as raised:
            download_collection(
                WorkshopCollectionResult(
                    "99",
                    (WorkshopItemMetadata("123", "Broken item", "", 108600, None),),
                ),
                "Broken",
                self.store,
                downloader,
                item_cached=cached.append,
            )
        self.assertIn("mod.info", str(raised.exception))
        self.assertEqual(len(cached), 1)
        self.assertTrue(cached[0].path.is_dir())
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

                def confirm_mod_list_change(box):
                    next(
                        button
                        for button in box.buttons()
                        if button.text() == "Apply Changes"
                    ).click()

                with (
                    patch(
                        "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes,
                    ),
                    patch(
                        "zomboid_mod_manager.ui.window_configuration.QMessageBox.exec",
                        new=confirm_mod_list_change,
                    ),
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

    def test_unload_keeps_global_list_and_staged_order_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "Zomboid/mods"
            local.mkdir(parents=True)
            config = local / "default.txt"
            config_bytes = (
                b"VERSION = 1,\n\nmods\n{\n    mod = PackA,\n}\n\nmaps\n{\n}\n"
            )
            config.write_bytes(config_bytes)
            store = CollectionStore(root / "app/collections")
            reference = store.intern(
                make_item(root / "download", "PackA", "collection"), "1"
            )
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
                self.assertTrue(window.unload_pack_button.isEnabled())
                staged_before = list(window._staged_mod_ids)
                with patch(
                    "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    window._unload_collection_mod_pack()

                self.assertEqual(config.read_bytes(), config_bytes)
                self.assertEqual(window._staged_mod_ids, staged_before)
                self.assertFalse(window._loaded_collection_content)
                self.assertFalse(window.unload_pack_button.isEnabled())
                self.assertTrue(
                    list(
                        (root / "Zomboid/.zomboidsorter-collections/transactions").glob(
                            "*/previous/ZomboidSorter_*"
                        )
                    )
                )
            finally:
                while any(w.isRunning() for w in window._background_workers()):
                    QTest.qWait(10)
                window.close()


if __name__ == "__main__":
    unittest.main()
