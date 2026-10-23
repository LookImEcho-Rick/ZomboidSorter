from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, QPoint, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from zomboid_mod_manager.discovery.scanner import ScanCancelled
from zomboid_mod_manager.domain import DetectedPaths, Diagnostic, ScanResult
from zomboid_mod_manager.gameio.active_mods import read_active_mods
from zomboid_mod_manager.profiles import ModProfile, ProfileStore
from zomboid_mod_manager.sorting.user_rules import (
    UserOrderRule,
    parse_user_order_rules,
)
from zomboid_mod_manager.ui.main_window import MainWindow
from zomboid_mod_manager.ui.workshop_browser import WorkshopBrowserPanel
from zomboid_mod_manager.updates import UpdateRelease

FIXTURES = Path(__file__).parent / "fixtures"


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_launch_window(
        self, root: Path, *, mods: tuple[str, ...] = ()
    ) -> tuple[MainWindow, Path]:
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        mod_lines = "".join(f"    mod = {mod_id},\n" for mod_id in mods)
        config_path.write_text(
            f"VERSION = 1,\n\nmods\n{{\n{mod_lines}}}\n\nmaps\n{{\n}}\n",
            encoding="utf-8",
        )
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )
        self.addCleanup(window.close)
        return window, config_path

    def test_update_button_checks_release_and_reports_when_current(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))

        with (
            patch(
                "zomboid_mod_manager.ui.main_window.check_for_update",
                return_value=None,
            ) as check_for_update,
            patch(
                "zomboid_mod_manager.ui.main_window.QMessageBox.information"
            ) as information,
        ):
            window.update_button.click()
            deadline = time.monotonic() + 5
            while not window.update_button.isEnabled() and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(10)

        self.assertTrue(window.update_button.isEnabled())
        self.assertEqual(window.update_button.text(), "Check for Updates")
        self.assertIn("up to date", window.status.text().casefold())
        check_for_update.assert_called_once_with("0.1.2")
        information.assert_called_once()

    def test_update_button_downloads_a_new_release_after_confirmation(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))
        release = UpdateRelease(
            version="0.1.3",
            tag_name="v0.1.3",
            installer_name="ZomboidSorter-0.1.3-windows-setup.exe",
            installer_url="https://github.com/LookImEcho-Rick/ZomboidSorter/releases/download/v0.1.3/ZomboidSorter-0.1.3-windows-setup.exe",
            installer_size=100,
            checksum_name="ZomboidSorter-0.1.3-windows-setup.exe.sha256",
            checksum_url="https://github.com/LookImEcho-Rick/ZomboidSorter/releases/download/v0.1.3/ZomboidSorter-0.1.3-windows-setup.exe.sha256",
        )

        with (
            patch(
                "zomboid_mod_manager.ui.main_window.check_for_update",
                return_value=release,
            ),
            patch.object(
                QMessageBox,
                "exec",
                return_value=QMessageBox.StandardButton.Yes,
            ) as prompt,
            patch.object(window, "_download_update") as download_update,
        ):
            window.update_button.click()
            deadline = time.monotonic() + 5
            while not download_update.called and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(10)

        self.assertTrue(prompt.called)
        download_update.assert_called_once_with(release)

    def test_workshop_browser_panel_starts_without_loading_webengine(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)

        self.assertIsNone(panel.workshop_browser)
        self.assertFalse(panel._browser_loaded)
        self.assertEqual(
            panel.workshop_search.placeholderText(),
            "Search Workshop, or enter a page URL / item ID",
        )

    def test_workshop_browser_panel_routes_item_ids_and_searches(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        browser = Mock()

        for query, expected_url in (
            (
                "123456789",
                "https://steamcommunity.com/sharedfiles/filedetails/?id=123456789",
            ),
            (
                "map pack",
                "https://steamcommunity.com/workshop/browse/?appid=108600&searchtext=map+pack",
            ),
        ):
            with self.subTest(query=query):
                panel.workshop_search.setText(query)
                with patch.object(panel, "_ensure_browser", return_value=browser):
                    panel.search()
                browser.setUrl.assert_called_with(QUrl(expected_url))

    def test_launch_button_explains_when_global_list_is_unavailable(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )

        self.assertFalse(window.launch_game_button.isEnabled())
        self.assertEqual(window.launch_readiness.text(), "Load global list")
        self.assertIn("default.txt", window.launch_readiness.toolTip())

        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n}\n\nmaps\n{\n}\n", encoding="utf-8"
        )
        window._load_active_configuration()
        self.assertTrue(window.launch_game_button.isEnabled())
        self.assertTrue(window.launch_readiness.isHidden())
        self.assertEqual(window.launch_game_button.text(), "Launch Project Zomboid")

        original_config = config_path.read_bytes()
        window._staged_mod_ids.append("ExampleMod")
        window._update_apply_enabled()
        self.assertEqual(window.launch_game_button.text(), "Apply & Launch…")
        with (
            patch(
                "zomboid_mod_manager.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as confirm,
            patch(
                "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl"
            ) as open_url,
        ):
            window._launch_project_zomboid()
        self.assertEqual(confirm.call_args.args[1], "Apply Mod List and Launch")
        self.assertIn("will open through Steam", confirm.call_args.args[2])
        self.assertEqual(config_path.read_bytes(), original_config)
        open_url.assert_not_called()

        window.active_config_path.setText(str(root / "other.txt"))
        self.assertFalse(window.launch_game_button.isEnabled())
        self.assertEqual(window.launch_readiness.text(), "Load selected list")

        window.active_config_path.setText(str(config_path))
        self.assertTrue(window.launch_game_button.isEnabled())
        window.close()

    def test_launch_rejects_external_config_changes(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        window, config_path = self._make_launch_window(root)
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = ChangedOutsideApp,\n}\n\nmaps\n{\n}\n",
            encoding="utf-8",
        )
        window._update_apply_enabled()
        self.assertFalse(window.launch_game_button.isEnabled())
        self.assertEqual(window.launch_readiness.text(), "Reload changed list")

        with (
            patch("zomboid_mod_manager.ui.main_window.QMessageBox.warning") as warning,
            patch(
                "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl"
            ) as open_url,
        ):
            window._launch_project_zomboid()

        self.assertEqual(warning.call_args.args[1], "Global Mod List Changed")
        open_url.assert_not_called()

    def test_launch_does_not_continue_after_failed_apply(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        window, config_path = self._make_launch_window(root)
        original_config = config_path.read_bytes()
        window._staged_mod_ids.append("PendingMod")
        window._update_apply_enabled()

        with (
            patch(
                "zomboid_mod_manager.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "zomboid_mod_manager.configuration.write_active_mods",
                side_effect=OSError("fixture write failure"),
            ),
            patch("zomboid_mod_manager.ui.main_window.QMessageBox.warning") as warning,
            patch(
                "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl"
            ) as open_url,
        ):
            window._launch_project_zomboid()

        self.assertEqual(warning.call_args.args[1], "Could not apply mod list")
        self.assertEqual(config_path.read_bytes(), original_config)
        open_url.assert_not_called()

    def test_launch_reports_steam_link_handoff_and_failure(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))

        with patch(
            "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            window._launch_project_zomboid()

        self.assertEqual(open_url.call_args.args[0].toString(), "steam://run/108600")
        self.assertIn("startup is not confirmed", window.status.text())

        with (
            patch(
                "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl",
                return_value=False,
            ),
            patch("zomboid_mod_manager.ui.main_window.QMessageBox.warning") as warning,
        ):
            window._launch_project_zomboid()

        self.assertEqual(warning.call_args.args[1], "Could Not Launch Project Zomboid")

    def test_workspace_uses_three_panels_and_list_selection_shows_details(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=FIXTURES / "config" / "default.txt",
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual(window.workspace_splitter.count(), 3)
        self.assertEqual(window.windowTitle(), "ZomboidSorter")
        self.assertTrue(
            window.workspace_splitter.widget(0).isAncestorOf(window.available_list)
        )
        self.assertTrue(
            window.workspace_splitter.widget(1).isAncestorOf(window.active_list)
        )
        self.assertTrue(
            window.workspace_splitter.widget(2).isAncestorOf(window.details)
        )
        self.assertTrue(
            window.workspace_splitter.widget(0).isAncestorOf(window.activate_button)
        )
        self.assertTrue(
            window.workspace_splitter.widget(1).isAncestorOf(window.deactivate_button)
        )
        self.assertIs(window.scan_button, window.workspace_scan_button)
        self.assertEqual(window.main_tabs.currentIndex(), 0)
        self.assertEqual(window.active_list.count(), 2)
        self.assertEqual(window.available_list.count(), 5)
        self.assertEqual(window.available_list.accessibleName(), "Inactive mods")
        self.assertEqual(window.active_search.accessibleName(), "Search active mods")
        self.assertEqual(
            window.available_list.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        item = next(
            window.available_list.item(i)
            for i in range(window.available_list.count())
            if window.available_list.item(i).data(Qt.ItemDataRole.UserRole)
            == "RepeatedDescription"
        )
        window.available_list.setCurrentItem(item)
        self.assertIn(item.text(), item.toolTip())
        self.assertIn("Mod ID: RepeatedDescription", window.details.toPlainText())
        self.assertTrue(window.open_workshop_button.isEnabled())
        window.manage_search.setText("not present in these fixtures")
        self.app.processEvents()
        self.assertEqual(window.available_list.visible_count, 0)
        self.assertIn("No mods match", window.available_list.empty_text)
        window.close()

    def test_mod_pack_save_captures_current_order(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        config_path = FIXTURES / "config" / "default.txt"
        original_config = config_path.read_bytes()
        profile_store = ProfileStore(Path(temporary.name) / "packs")
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=profile_store,
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)

        self.assertTrue(window.workspace_page.isAncestorOf(window.load_pack_button))
        self.assertTrue(window.workspace_page.isAncestorOf(window.save_profile_button))
        saved_order = tuple(window._staged_mod_ids)
        with patch(
            "zomboid_mod_manager.ui.main_window.QInputDialog.getText",
            return_value=("Weekend Pack", True),
        ):
            window.save_profile_button.click()

        self.assertEqual(profile_store.load("Weekend Pack").mod_ids, saved_order)
        self.assertIn("Saved Mod Pack 'Weekend Pack'", window.status.text())
        self.assertEqual(config_path.read_bytes(), original_config)
        self.assertEqual(config_path.read_bytes(), original_config)
        window.close()

    def test_mod_pack_manager_selection_applies_pack_to_global_config(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = OldMod,\n}\n\n"
            "maps\n{\n    map = Muldraugh, KY,\n}\n",
            encoding="utf-8",
        )
        original_config = config_path.read_bytes()
        profile_store = ProfileStore(root / "packs")
        profile_store.save(ModProfile("Other Pack", ("Other",)))
        profile_store.save(
            ModProfile("Weekend Pack", ("ModAlpha", "UninstalledMod"), ("12345",))
        )
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=profile_store,
        )

        def select_weekend_pack(dialog) -> int:
            names = [
                dialog.pack_list.item(row).text()
                for row in range(dialog.pack_list.count())
            ]
            self.assertEqual(names, ["Other Pack", "Weekend Pack"])
            self.assertEqual(dialog.pack_list.currentRow(), -1)
            self.assertFalse(dialog.load_apply_button.isEnabled())
            item = next(
                dialog.pack_list.item(row)
                for row in range(dialog.pack_list.count())
                if dialog.pack_list.item(row).text() == "Weekend Pack"
            )
            dialog.pack_list.setCurrentItem(item)
            self.assertTrue(dialog.load_apply_button.isEnabled())
            self.assertEqual(dialog.load_apply_button.text(), "Apply")
            dialog.load_apply_button.click()
            return dialog.result()

        with patch(
            "zomboid_mod_manager.ui.main_window.ModPacksDialog.exec",
            new=select_weekend_pack,
        ):
            window.load_pack_button.click()

        self.assertEqual(
            read_active_mods(config_path).config.mods,
            ("ModAlpha", "UninstalledMod"),
        )
        self.assertEqual(read_active_mods(config_path).config.maps, ("Muldraugh, KY",))
        backups = list(config_path.parent.glob("default.txt.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original_config)
        self.assertIn(
            "Loaded and applied Mod Pack 'Weekend Pack'", window.status.text()
        )
        self.assertFalse(window.apply_config_button.isEnabled())
        window.close()

    def test_workspace_filters_sort_and_context_actions_preserve_staged_state(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=FIXTURES / "config" / "default.txt",
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)

        window.inactive_sort.setCurrentIndex(1)
        names = [
            window.available_list.item(i).text()
            for i in range(window.available_list.count())
        ]
        self.assertIn("Repeated Description", names[0])
        window.inactive_filter.setCurrentText("Workshop")
        window.manage_search.setText("111111111")
        visible = [
            window.available_list.item(i)
            for i in range(window.available_list.count())
            if not window.available_list.item(i).isHidden()
        ]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].data(Qt.ItemDataRole.UserRole), "LegacyWorkshop")
        window.available_list.setCurrentItem(visible[0])
        menu = window._build_list_context_menu(window.available_list)
        actions = {action.text(): action for action in menu.actions()}
        self.assertIn("Open mod folder", actions)
        self.assertIn("Open Workshop page", actions)
        actions["Copy Mod ID"].trigger()
        self.assertEqual(self.app.clipboard().text(), "LegacyWorkshop")
        actions["Copy Workshop ID"].trigger()
        self.assertEqual(self.app.clipboard().text(), "111111111")
        with patch(
            "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl"
        ) as open_url:
            actions["Open mod folder"].trigger()
        self.assertEqual(
            Path(open_url.call_args.args[0].toLocalFile()),
            next(
                entry.entry_path
                for entry in window._last_result.entries
                if entry.mod_id == "LegacyWorkshop"
            ),
        )
        actions["Enable selected"].trigger()
        self.assertIn("LegacyWorkshop", window._staged_mod_ids)
        self.assertEqual(window.active_list.count(), 3)
        window.active_search.setText("LegacyWorkshop")
        self.assertFalse(window.active_list.dragEnabled())
        self.assertFalse(window.move_up_button.isEnabled())
        self.assertFalse(window.move_down_button.isEnabled())
        original_order = list(window._staged_mod_ids)
        window._handle_mod_list_drop(
            window.available_list,
            window.active_list,
            ["RepeatedDescription"],
            0,
        )
        self.assertEqual(window._staged_mod_ids[: len(original_order)], original_order)
        self.assertEqual(window._staged_mod_ids[-1], "RepeatedDescription")
        window.active_search.clear()
        self.assertTrue(window.active_list.dragEnabled())
        window.active_filter.setCurrentText("Missing / duplicate")
        self.assertFalse(window.active_list.dragEnabled())
        self.assertFalse(window.move_up_button.isEnabled())
        self.assertFalse(window.move_down_button.isEnabled())
        window.active_filter.setCurrentText("All active")
        self.assertTrue(window.active_list.dragEnabled())
        window.close()

    def test_workspace_shortcuts_stage_only_visible_selected_mods(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=FIXTURES / "config" / "default.txt",
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        window.show()
        self.app.processEvents()
        window.active_list.setCurrentRow(0)
        window.active_list.setFocus()
        QTest.keyClick(window.active_list, Qt.Key.Key_Delete)
        self.assertEqual(window._staged_mod_ids, ["Mod Beta"])
        window.manage_search.setText("RepeatedDescription")
        window.available_list.setCurrentRow(0)
        window.available_list.item(0).setSelected(True)
        window._stage_activate()
        self.assertEqual(window._staged_mod_ids, ["Mod Beta"])
        window.manage_search.setFocus()
        QTest.keyClick(window.manage_search, Qt.Key.Key_Escape)
        self.assertEqual(window.manage_search.text(), "")
        window.available_list.setFocus()
        QTest.keyClick(
            window.available_list,
            Qt.Key.Key_F,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertIs(self.app.focusWidget(), window.manage_search)
        window.available_list.setFocus()
        QTest.keyClick(
            window.available_list,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(len(window.available_list.selectedItems()), 4)
        window.close()

    def test_selected_mod_preview_loads_without_changing_config(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        entry_root = root / "Illustrated"
        entry_root.mkdir()
        (entry_root / "mod.info").write_text(
            "name=Illustrated Mod\nid=Illustrated\nposter=poster.png\n",
            encoding="utf-8",
        )
        image = QImage(40, 30, QImage.Format.Format_ARGB32)
        image.fill(QColor("#64a7dc"))
        self.assertTrue(image.save(str(entry_root / "poster.png")))
        config_path = FIXTURES / "config" / "default.txt"
        original = config_path.read_bytes()
        detected = DetectedPaths((), (), (), (), root)
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        item = next(
            window.available_list.item(i)
            for i in range(window.available_list.count())
            if window.available_list.item(i).data(Qt.ItemDataRole.UserRole)
            == "Illustrated"
        )
        window.available_list.setCurrentItem(item)
        deadline = time.monotonic() + 5
        while window.preview.pixmap().isNull() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(window.preview.pixmap().isNull())
        self.assertIn("root (Build 41 style)", window.preview_caption.text())
        self.assertIn("Click the image to enlarge it.", window.preview_caption.text())
        self.assertTrue(window.open_folder_button.isEnabled())
        window.show()
        self.app.processEvents()
        backdrop_point = QPoint(8, 8)
        backdrop_before = (
            window.centralWidget().grab().toImage().pixelColor(backdrop_point)
        )
        QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(window.preview_overlay.isVisible())
        backdrop_after = (
            window.preview_overlay.grab().toImage().pixelColor(backdrop_point)
        )
        self.assertLess(
            sum((backdrop_after.red(), backdrop_after.green(), backdrop_after.blue())),
            sum(
                (backdrop_before.red(), backdrop_before.green(), backdrop_before.blue())
            ),
        )
        self.assertGreater(
            window.preview_overlay.image_rect.width(),
            window.preview.pixmap().width(),
        )
        QTest.mouseClick(
            window.preview_overlay,
            Qt.MouseButton.LeftButton,
            pos=window.preview_overlay.rect().center(),
        )
        self.assertTrue(window.preview_overlay.isVisible())
        QTest.mouseClick(
            window.preview_overlay,
            Qt.MouseButton.LeftButton,
            pos=QPoint(window.preview_overlay.width() - 2, 2),
        )
        self.assertFalse(window.preview_overlay.isVisible())
        QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton)
        QTest.keyClick(window.preview_overlay, Qt.Key.Key_Escape)
        self.assertFalse(window.preview_overlay.isVisible())
        self.assertGreater(
            window.preview_overlay.image_rect.width(),
            0,
        )
        with patch(
            "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl"
        ) as open_url:
            window.open_folder_button.click()
        self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), entry_root)
        self.assertEqual(config_path.read_bytes(), original)
        window.close()

    def test_phase_d_revert_counts_and_busy_feedback(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        config_path = FIXTURES / "config" / "default.txt"
        original_bytes = config_path.read_bytes()
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        window.show()
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        while not window.progress.isHidden() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("warning(s)", window.issue_summary.text())
        self.assertIn("0 error(s)", window.issue_summary.text())
        self.assertTrue(window.progress.isHidden())

        original_ids = list(window._staged_mod_ids)
        window._staged_mod_ids.append("Temporary")
        window._update_apply_enabled()
        self.assertTrue(window.revert_button.isEnabled())
        self.assertIn("Unapplied changes", window.dirty_indicator.text())
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            window.revert_button.click()
        self.assertIn("Temporary", window._staged_mod_ids)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            window.revert_button.click()
        self.assertEqual(window._staged_mod_ids, original_ids)
        self.assertFalse(window.revert_button.isEnabled())
        self.assertEqual(window.dirty_indicator.text(), "No unapplied changes")

        window._show_result(ScanResult((), (), (Diagnostic("Broken", level="error"),)))
        self.assertIn("1 error(s)", window.issue_summary.text())
        window._start_diagnostic("phase-d-test", lambda: "Completed")
        self.assertFalse(window.progress.isHidden())
        deadline = time.monotonic() + 5
        while not window.progress.isHidden() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(window.progress.isHidden())
        self.assertEqual(config_path.read_bytes(), original_bytes)
        window.close()

    def test_cancel_scan_button_stops_scan_and_keeps_previous_results(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))
        window.show()
        deadline = time.monotonic() + 5
        while window._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertIsNotNone(window._last_result)
        previous_result = window._last_result

        scan_started = Event()

        def wait_until_cancelled(*, cancelled, **_kwargs):
            scan_started.set()
            while not cancelled():
                time.sleep(0.005)
            raise ScanCancelled

        with patch(
            "zomboid_mod_manager.ui.main_window.scan_mods",
            side_effect=wait_until_cancelled,
        ):
            window._start_scan()
            self.assertTrue(scan_started.wait(timeout=5))
            self.assertTrue(window.cancel_scan_button.isVisible())
            window.cancel_scan_button.click()

            deadline = time.monotonic() + 5
            while window._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(5)

        self.assertIsNone(window._worker)
        self.assertIs(window._last_result, previous_result)
        self.assertTrue(window.cancel_scan_button.isHidden())
        self.assertIn("cancelled", window.status.text().casefold())
        window.close()

    def test_close_does_not_block_while_scan_worker_finishes(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        scan_started = Event()

        def delayed_scan(**_kwargs):
            scan_started.set()
            time.sleep(0.35)
            return ScanResult((), (), ())

        with patch(
            "zomboid_mod_manager.ui.main_window.scan_mods",
            side_effect=delayed_scan,
        ):
            window, _ = self._make_launch_window(Path(temporary.name))
            window.show()
            self.assertTrue(scan_started.wait(timeout=5))

            close_started = time.monotonic()
            window.close()
            close_elapsed = time.monotonic() - close_started

            self.assertLess(close_elapsed, 0.15)
            self.assertTrue(window.isVisible())
            deadline = time.monotonic() + 5
            while window.isVisible() and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(5)

        self.assertFalse(window.isVisible())
        self.assertFalse(window._shutdown_workers)

    def test_window_scans_fixtures_and_filters_results(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        profile_store = ProfileStore(Path(temporary.name) / "profiles")
        profile_store.save(
            ModProfile("Fixture Profile", ("RepeatedDescription", "UninstalledMod"))
        )
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "workshop",),
            local_mod_root=FIXTURES / "local_mods",
        )
        config_path = FIXTURES / "config" / "default.txt"
        original_config = config_path.read_bytes()
        window = MainWindow(
            detected, active_config_path=config_path, profile_store=profile_store
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)

        self.assertIn("scan complete", window.status.text().casefold())
        self.assertEqual(window.table_model.rowCount(), 8)
        self.assertEqual(window.active_list.count(), 2)
        self.assertFalse(window.apply_config_button.isEnabled())
        ambiguous = next(
            window.available_list.item(i)
            for i in range(window.available_list.count())
            if window.available_list.item(i).text().startswith("Duplicate installation")
        )
        self.assertFalse(bool(ambiguous.flags() & Qt.ItemFlag.ItemIsEnabled))

        window.search.setText("RepeatedDescription")
        self.app.processEvents()
        self.assertEqual(window._proxy.rowCount(), 1)
        window.table.selectRow(0)
        self.app.processEvents()
        self.assertIn("Mod ID: RepeatedDescription", window.details.toPlainText())

        window.main_tabs.setCurrentWidget(window.main_tabs.widget(1))
        window.manage_search.setText("RepeatedDescription")
        matching_row = next(
            i
            for i in range(window.available_list.count())
            if not window.available_list.item(i).isHidden()
            and "RepeatedDescription" in window.available_list.item(i).text()
        )
        window.available_list.setCurrentRow(matching_row)
        window._stage_activate()
        self.assertEqual(window.active_list.count(), 3)
        window.active_list.setCurrentRow(2)
        window._move_active(-1)
        self.assertEqual(
            window._staged_mod_ids,
            ["ModAlpha", "RepeatedDescription", "Mod Beta"],
        )
        self.assertTrue(window.apply_config_button.isEnabled())
        self.assertEqual(config_path.read_bytes(), original_config)

        self.assertEqual(config_path.read_bytes(), original_config)
        window.close()

    def test_suggested_order_is_staged_only_after_confirmation(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        mods_path = root / "Zomboid" / "mods"
        mods_path.mkdir(parents=True)
        config_path = mods_path / "default.txt"
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = AfterCore,\n    mod = Core,\n    mod = Unsorted,\n}\n\nmaps\n{\n}\n",
            encoding="utf-8",
        )
        original_config = config_path.read_bytes()
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "dependencies",),
            local_mod_root=mods_path,
        )
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        with patch(
            "zomboid_mod_manager.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._suggest_dependency_order()
        self.assertEqual(window._staged_mod_ids, ["Core", "AfterCore", "Unsorted"])
        self.assertEqual(config_path.read_bytes(), original_config)
        window.close()

    def test_user_order_rules_are_applied_to_order_suggestions(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "dependencies",),
            local_mod_root=FIXTURES / "local_mods",
        )
        settings = QSettings(
            str(Path(temporary.name) / "settings.ini"), QSettings.Format.IniFormat
        )
        with (
            patch(
                "zomboid_mod_manager.ui.main_window.QSettings", return_value=settings
            ),
            patch(
                "zomboid_mod_manager.ui.main_window.detect_paths",
                return_value=detected,
            ),
        ):
            window = MainWindow(
                active_config_path=FIXTURES / "config" / "default.txt",
                profile_store=ProfileStore(Path(temporary.name) / "profiles"),
            )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        window._staged_mod_ids = ["Unsorted", "Other"]
        window._user_order_rules = ()
        with (
            patch("zomboid_mod_manager.ui.main_window.SortRulesDialog") as dialog_type,
            patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            dialog_type.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_type.return_value.rules.return_value = (
                UserOrderRule("Other", "Unsorted"),
            )
            window._manage_sort_rules()
            window._suggest_dependency_order()

        self.assertEqual(window._staged_mod_ids, ["Other", "Unsorted"])
        self.assertEqual(
            window._user_order_rules,
            (UserOrderRule("Other", "Unsorted"),),
        )
        self.assertEqual(
            parse_user_order_rules(settings.value("sorting/user_rules")),
            (UserOrderRule("Other", "Unsorted"),),
        )

        window._staged_mod_ids = ["Core", "Consumer"]
        window._user_order_rules = (UserOrderRule("Consumer", "Core"),)
        original_order = list(window._staged_mod_ids)
        with patch("zomboid_mod_manager.ui.main_window.QMessageBox.warning") as warning:
            window._suggest_dependency_order()
        warning.assert_called_once()
        self.assertEqual(window._staged_mod_ids, original_order)
        window.close()

    def test_workshop_collection_saves_pack_and_retains_missing_items(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        profile_store = ProfileStore(Path(temporary.name) / "profiles")
        config_path = FIXTURES / "config" / "default.txt"
        original_config = config_path.read_bytes()
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "workshop",),
            local_mod_root=FIXTURES / "local_mods",
        )
        window = MainWindow(
            detected, active_config_path=config_path, profile_store=profile_store
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        profile = ModProfile(
            "Imported Collection",
            ("LegacyWorkshop", "UnavailableMod"),
            ("111111111", "999999999"),
        )
        original_staged = tuple(window._staged_mod_ids)
        window._save_imported_collection_profile(profile)
        self.assertEqual(profile_store.load("Imported Collection"), profile)
        self.assertEqual(tuple(window._staged_mod_ids), original_staged)
        self.assertIn("Open Load Pack", window.configuration_status.text())
        self.assertEqual(config_path.read_bytes(), original_config)
        window.close()

    def test_closing_pack_manager_preserves_staged_changes(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        profile_store = ProfileStore(Path(temporary.name) / "profiles")
        profile_store.save(ModProfile("Saved", ("UninstalledMod",)))
        config_path = FIXTURES / "config" / "default.txt"
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "workshop",),
            local_mod_root=FIXTURES / "local_mods",
        )
        window = MainWindow(
            detected, active_config_path=config_path, profile_store=profile_store
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        initial = list(window._staged_mod_ids)
        window._staged_mod_ids.append("StagedOnly")
        with patch(
            "zomboid_mod_manager.ui.main_window.ModPacksDialog.exec",
            return_value=QDialog.DialogCode.Rejected,
        ):
            window.load_pack_button.click()
        self.assertEqual(window._staged_mod_ids, initial + ["StagedOnly"])

        alternate_path = Path(temporary.name) / "Zomboid" / "mods" / "default.txt"
        alternate_path.parent.mkdir(parents=True)
        alternate_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = Alternate,\n}\n\nmaps\n{\n}\n",
            encoding="utf-8",
        )
        window.active_config_path.setText(str(alternate_path))
        with patch(
            "zomboid_mod_manager.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            window.load_config_button.click()
        self.assertEqual(window._staged_mod_ids, initial + ["StagedOnly"])
        self.assertEqual(window._active_config.path, config_path)
        window.close()

    def test_game_list_apply_requires_confirmation_and_preserves_maps_with_backup(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = ExistingMod,\n}\n\nmaps\n{\n    map = Muldraugh, KY,\n}\n",
            encoding="utf-8",
        )
        original = config_path.read_bytes()
        detected = DetectedPaths((), (), (), (), FIXTURES / "local_mods")
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        window._staged_mod_ids.append("AddedMod")
        window._update_apply_enabled()
        self.assertTrue(window.apply_config_button.isEnabled())
        with patch(
            "zomboid_mod_manager.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            window._apply_active_configuration()
        self.assertEqual(config_path.read_bytes(), original)

        with patch(
            "zomboid_mod_manager.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._apply_active_configuration()
        self.assertNotEqual(config_path.read_bytes(), original)
        self.assertEqual(
            tuple(window._active_config.config.mods), ("ExistingMod", "AddedMod")
        )
        self.assertEqual(window._active_config.config.maps, ("Muldraugh, KY",))
        backups = list(config_path.parent.glob("default.txt.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        window.close()

    def test_workshop_page_button_opens_only_selected_workshop_item(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "workshop",),
            local_mod_root=FIXTURES / "local_mods",
        )
        config_path = FIXTURES / "config" / "default.txt"
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        workshop_row = next(
            row
            for row in range(window.table_model.rowCount())
            if window.table_model.item(row, 1).text() == "LegacyWorkshop"
        )
        window._show_selected_entry(
            window.table_model.index(workshop_row, 0), QModelIndex()
        )
        self.assertTrue(window.open_workshop_button.isEnabled())
        with patch(
            "zomboid_mod_manager.ui.main_window.QDesktopServices.openUrl"
        ) as open_url:
            window._open_selected_workshop_page()
        open_url.assert_called_once()
        self.assertEqual(
            open_url.call_args.args[0].toString(),
            "https://steamcommunity.com/sharedfiles/filedetails/?id=111111111",
        )
        window._show_selected_entry(QModelIndex(), QModelIndex())
        self.assertFalse(window.open_workshop_button.isEnabled())
        window.close()

    def test_bulk_selection_and_internal_order_changes_update_staged_ids(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "workshop",),
            local_mod_root=FIXTURES / "local_mods",
        )
        window = MainWindow(
            detected,
            active_config_path=FIXTURES / "config" / "default.txt",
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        wanted = {"LegacyWorkshop", "RepeatedDescription"}
        for index in range(window.available_list.count()):
            item = window.available_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) in wanted:
                item.setSelected(True)
        window._stage_activate()
        self.assertTrue(wanted.issubset(window._staged_mod_ids))

        original = list(window._staged_mod_ids)
        moved = window.active_list.takeItem(0)
        window.active_list.insertItem(2, moved)
        window._active_list_reordered()
        self.assertNotEqual(window._staged_mod_ids, original)
        self.assertEqual(
            window._staged_mod_ids,
            [
                window.active_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(window.active_list.count())
            ],
        )

        for index in range(min(2, window.active_list.count())):
            window.active_list.item(index).setSelected(True)
        removed = {
            window.active_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(min(2, window.active_list.count()))
        }
        window._stage_deactivate()
        self.assertTrue(removed.isdisjoint(window._staged_mod_ids))
        window.close()

    def test_read_only_file_and_console_diagnostics_are_connected_to_ui(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        detected = DetectedPaths(
            steam_roots=(),
            steamapps_libraries=(),
            game_installations=(),
            workshop_roots=(FIXTURES / "workshop",),
            local_mod_root=FIXTURES / "local_mods",
        )
        window = MainWindow(
            detected,
            active_config_path=FIXTURES / "config" / "default.txt",
            profile_store=ProfileStore(Path(temporary.name) / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())

        window.file_overlap_button.click()
        deadline = time.monotonic() + 5
        while (
            "potential file overlaps" not in window.diagnostics.toPlainText().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn(
            "potential file overlaps", window.diagnostics.toPlainText().casefold()
        )
        deadline = time.monotonic() + 5
        while not window.console_log_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(window.console_log_button.isEnabled())

        log_path = Path(temporary.name) / "console.txt"
        log_path.write_text(
            'ERROR: General f:0> ERROR: template "MissingEntry" not found\n',
            encoding="utf-8",
        )
        with patch(
            "zomboid_mod_manager.ui.main_window.QFileDialog.getOpenFileName",
            return_value=(str(log_path), ""),
        ):
            window.console_log_button.click()
        deadline = time.monotonic() + 5
        while (
            "missing-template" not in window.diagnostics.toPlainText().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIn("missing-template", window.diagnostics.toPlainText().casefold())
        window.close()


if __name__ == "__main__":
    unittest.main()
