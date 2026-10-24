from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, QPoint, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QMovie
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)

from zomboid_mod_manager import __version__
from zomboid_mod_manager.__main__ import _show_update_outcome
from zomboid_mod_manager.diagnostics.file_overlaps import (
    FileOverlap,
    FileOverlapPathGroup,
    FileOverlapReport,
)
from zomboid_mod_manager.discovery.scanner import ScanCancelled
from zomboid_mod_manager.domain import DetectedPaths, Diagnostic, ScanResult
from zomboid_mod_manager.gameio.active_mods import read_active_mods
from zomboid_mod_manager.profiles import ModProfile, ProfileStore
from zomboid_mod_manager.sorting.user_rules import (
    UserOrderRule,
    parse_user_order_rules,
)
from zomboid_mod_manager.ui.file_overlap_dialog import FileOverlapDialog
from zomboid_mod_manager.ui.global_backup_dialog import GlobalBackupDialog
from zomboid_mod_manager.ui.main_window import MainWindow
from zomboid_mod_manager.ui.support_report_dialog import SupportReportDialog
from zomboid_mod_manager.ui.window_widgets import ISSUE_ROLE, PreviewLabel
from zomboid_mod_manager.ui.workshop_browser import WorkshopBrowserPanel
from zomboid_mod_manager.ui.workshop_dialog import WorkshopCollectionDialog
from zomboid_mod_manager.updates import UpdateOutcome, UpdateRelease
from zomboid_mod_manager.workshop import (
    WorkshopCollectionResult,
    WorkshopItemMetadata,
)

FIXTURES = Path(__file__).parent / "fixtures"


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _wait_for_background_workers(self, window: MainWindow) -> None:
        deadline = time.monotonic() + 10
        while (
            any(worker.isRunning() for worker in window._background_workers())
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        # A worker can finish while qWait pumps events. Drain the queued
        # finished/result signals once more before callers inspect window state.
        self.app.processEvents()
        QTest.qWait(10)
        self.app.processEvents()
        running = tuple(
            type(worker).__name__
            for worker in window._background_workers()
            if worker.isRunning()
        )
        self.assertFalse(running, f"Background workers did not finish: {running}")

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

        def close_when_workers_finish() -> None:
            self._wait_for_background_workers(window)
            window.close()

        self.addCleanup(close_when_workers_finish)
        return window, config_path

    def test_update_outcome_dialog_reports_verified_success_and_failure(self) -> None:
        window = QWidget()
        window.status = QLabel(window)
        self.addCleanup(window.close)
        shown_dialogs: list[tuple[str, str, str]] = []

        def capture_dialog(dialog: QMessageBox) -> int:
            shown_dialogs.append(
                (dialog.windowTitle(), dialog.text(), dialog.informativeText())
            )
            return 0

        with patch("zomboid_mod_manager.__main__.QMessageBox.exec", capture_dialog):
            _show_update_outcome(
                window,
                UpdateOutcome("success", "0.1.6", "a" * 40, "a" * 40, "verified", ""),
            )
            self.assertIn("installed and verified", window.status.text())
            _show_update_outcome(
                window,
                UpdateOutcome(
                    "failed",
                    "0.1.6",
                    "a" * 40,
                    "",
                    "installer failed",
                    "C:/Temp/ZomboidSorter-update-error.txt",
                ),
            )

        self.assertEqual(len(shown_dialogs), 2)
        self.assertEqual(shown_dialogs[0][0], "Update Complete")
        self.assertIn("Verified build aaaaaaaa", shown_dialogs[0][2])
        self.assertEqual(shown_dialogs[1][0], "Update Needs Attention")
        self.assertIn("installer failed", shown_dialogs[1][2])
        self.assertIn("ZomboidSorter-update-error.txt", shown_dialogs[1][2])

    def test_portable_mode_writes_qsettings_beside_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_directory = Path(temporary)
            (app_directory / "portable.flag").touch()
            with (
                patch(
                    "zomboid_mod_manager.portable.application_directory",
                    return_value=app_directory,
                ),
                patch(
                    "zomboid_mod_manager.ui.main_window.detect_paths",
                    return_value=DetectedPaths((), (), (), (), app_directory / "mods"),
                ),
            ):
                window = MainWindow(
                    profile_store=ProfileStore(app_directory / "data" / "profiles"),
                )
                self.addCleanup(window.close)
                window.show()
                self._wait_for_background_workers(window)
                window.close()

            self.assertTrue((app_directory / "data" / "settings.ini").is_file())

    def test_update_button_checks_release_and_reports_when_current(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)

        with (
            patch(
                "zomboid_mod_manager.ui.window_workers.check_for_update",
                return_value=None,
            ) as check_for_update,
            patch(
                "zomboid_mod_manager.ui.window_updates.QMessageBox.information"
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
        check_for_update.assert_called_once_with(__version__, "source")
        information.assert_called_once()

    def test_update_button_downloads_a_new_pushed_build_automatically(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))
        release = UpdateRelease(
            version="0.1.5",
            tag_name="rolling",
            installer_name="ZomboidSorter-windows-setup.exe",
            installer_url="https://github.com/LookImEcho-Rick/ZomboidSorter/releases/download/rolling/ZomboidSorter-windows-setup.exe",
            installer_size=100,
            checksum_name="ZomboidSorter-windows-setup.exe.sha256",
            checksum_url="https://github.com/LookImEcho-Rick/ZomboidSorter/releases/download/rolling/ZomboidSorter-windows-setup.exe.sha256",
            build_id="a" * 40,
            expected_sha256="b" * 64,
        )

        with (
            patch(
                "zomboid_mod_manager.ui.window_workers.check_for_update",
                return_value=release,
            ),
            patch.object(window, "_download_update") as download_update,
        ):
            window.update_button.click()
            deadline = time.monotonic() + 5
            while not download_update.called and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(10)

        download_update.assert_called_once_with(release)

    def test_successful_update_download_starts_helper_and_closes_app(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))
        installer = Path(temporary.name) / "verified-update.exe"
        installer.write_bytes(b"MZ")

        with (
            patch(
                "zomboid_mod_manager.ui.window_updates.launch_update_helper"
            ) as helper,
            patch(
                "zomboid_mod_manager.ui.window_updates.QApplication.quit"
            ) as quit_app,
        ):
            release = UpdateRelease(
                version="0.1.6",
                tag_name="rolling",
                installer_name="ZomboidSorter-windows-setup.exe",
                installer_url="https://github.com/LookImEcho-Rick/ZomboidSorter/releases/download/rolling/ZomboidSorter-windows-setup.exe",
                installer_size=100,
                checksum_name="ZomboidSorter-windows-setup.exe.sha256",
                checksum_url="https://github.com/LookImEcho-Rick/ZomboidSorter/releases/download/rolling/ZomboidSorter-windows-setup.exe.sha256",
                build_id="c" * 40,
                expected_sha256="b" * 64,
            )
            window._launch_update_installer(str(installer), release)

        helper.assert_called_once_with(
            installer,
            expected_version="0.1.6",
            expected_build_id="c" * 40,
        )
        quit_app.assert_called_once_with()
        self.assertIn("Applying update", window.status.text())

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
        self._wait_for_background_workers(window)

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
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as confirm,
            patch(
                "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl"
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
        self._wait_for_background_workers(window)
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = ChangedOutsideApp,\n}\n\nmaps\n{\n}\n",
            encoding="utf-8",
        )
        window._update_apply_enabled()
        self.assertFalse(window.launch_game_button.isEnabled())
        self.assertEqual(window.launch_readiness.text(), "Reload changed list")

        with (
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.warning"
            ) as warning,
            patch(
                "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl"
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
        self._wait_for_background_workers(window)
        original_config = config_path.read_bytes()
        window._staged_mod_ids.append("PendingMod")
        window._update_apply_enabled()

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "zomboid_mod_manager.configuration.write_active_mods",
                side_effect=OSError("fixture write failure"),
            ),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.warning"
            ) as warning,
            patch(
                "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl"
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
        self._wait_for_background_workers(window)

        with patch(
            "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            window._launch_project_zomboid()

        self.assertEqual(open_url.call_args.args[0].toString(), "steam://run/108600")
        self.assertIn("startup is not confirmed", window.status.text())

        with (
            patch(
                "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl",
                return_value=False,
            ),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.warning"
            ) as warning,
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
        self.assertEqual(window.windowTitle(), f"ZomboidSorter v{__version__}")
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
        self.assertTrue(window.main_tabs.isTabVisible(window.library_tab_index))
        self.assertEqual(window.active_list.count(), 2)
        self.assertEqual(window.available_list.count(), 5)
        window.main_tabs.setCurrentWidget(window.library_page)
        window.table.selectRow(0)
        self.assertTrue(window.inspect_library_button.isEnabled())
        window.inspect_library_button.click()
        self.assertIs(window.main_tabs.currentWidget(), window.workspace_page)
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
        self.assertIn("0 of 5", window.inactive_heading.text())
        self.assertFalse(window.select_filtered_button.isEnabled())
        self.assertFalse(window.activate_button.isEnabled())
        self._wait_for_background_workers(window)
        window.close()

    def test_small_window_keeps_paths_and_primary_actions_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            window.resize(980, 680)
            window.show()
            self._wait_for_background_workers(window)
            self.app.processEvents()

            self.assertEqual(window.launch_game_button.text(), "Launch Game")
            self.assertEqual(window.apply_config_button.text(), "Apply Global List…")
            self.assertEqual(window.detail_tabs.count(), 2)
            self.assertFalse(window.workflow_hint.isVisible())

            window.main_tabs.setCurrentWidget(window.setup_page)
            self.app.processEvents()
            self.assertGreaterEqual(window.game_path.height(), 25)
            self.assertGreaterEqual(window.local_path.height(), 25)
            self.assertGreaterEqual(window.game_path.width(), 250)
            self.assertTrue(window.detect_all_paths_button.isVisible())
            self.assertTrue(window.game_path_detect_button.isVisible())
            self.assertTrue(window.game_path_health.isVisible())

    def test_path_detection_buttons_refresh_fields_and_tab_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window, _ = self._make_launch_window(root)
            self._wait_for_background_workers(window)

            detected_game = root / "Steam Library" / "ProjectZomboid"
            detected_local = root / "User" / "Zomboid" / "mods"
            detected_local.mkdir(parents=True)
            detected_workshop = root / "Steam Library" / "workshop" / "108600"
            detected_paths = DetectedPaths(
                (),
                (),
                (detected_game,),
                (detected_workshop,),
                detected_local,
            )
            with patch(
                "zomboid_mod_manager.ui.window_discovery.detect_paths",
                return_value=detected_paths,
            ):
                window.game_path_detect_button.click()
                self.assertEqual(window.game_path.text(), str(detected_game))
                window.local_path_detect_button.click()
                self.assertEqual(window.local_path.text(), str(detected_local))
                window.workshop_paths_detect_button.click()
                self.assertEqual(window.workshop_paths.text(), str(detected_workshop))

            tab_labels = [
                window.main_tabs.tabText(index)
                for index in range(window.main_tabs.count())
            ]
            self.assertIn("Paths Settings", tab_labels)
            self.assertIn("Library Diagnostics", tab_labels)
            self.assertTrue(all("_" not in label for label in tab_labels))

            previous_game_path = window.game_path.text()
            with patch(
                "zomboid_mod_manager.ui.window_discovery.detect_paths",
                return_value=DetectedPaths((), (), (), (), detected_local),
            ):
                window.game_path_detect_button.click()
            self.assertEqual(window.game_path.text(), previous_game_path)
            self.assertIn("current game folder was kept", window.status.text())

    def test_detect_all_updates_each_available_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window, _ = self._make_launch_window(root)
            self._wait_for_background_workers(window)

            game = root / "Steam Library" / "ProjectZomboid"
            local = root / "User" / "Zomboid" / "mods"
            workshop = root / "Steam Library" / "workshop" / "108600"
            for path in (game, local, workshop):
                path.mkdir(parents=True)
            detected = DetectedPaths((), (), (game,), (workshop,), local)
            with patch(
                "zomboid_mod_manager.ui.window_discovery.detect_paths",
                return_value=detected,
            ):
                window.detect_all_paths_button.click()

            self.assertEqual(window.game_path.text(), str(game))
            self.assertEqual(window.local_path.text(), str(local))
            self.assertEqual(window.workshop_paths.text(), str(workshop))
            self.assertIn(
                "Updated game folder, local mods folder, Workshop folders",
                window.status.text(),
            )

            previous_game = window.game_path.text()
            previous_workshop = window.workshop_paths.text()
            undetected = DetectedPaths((), (), (), (), root / "Fallback mods")
            with patch(
                "zomboid_mod_manager.ui.window_discovery.detect_paths",
                return_value=undetected,
            ):
                window.detect_all_paths_button.click()
            self.assertEqual(window.game_path.text(), previous_game)
            self.assertEqual(window.workshop_paths.text(), previous_workshop)
            self.assertIn("game folder (not found)", window.status.text())
            self.assertIn("Workshop folders (not found)", window.status.text())

    def test_game_path_auto_detect_lets_user_choose_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window, _ = self._make_launch_window(root)
            self._wait_for_background_workers(window)
            first = root / "Steam A" / "ProjectZomboid"
            second = root / "Steam B" / "ProjectZomboid"
            detected = DetectedPaths((), (), (first, second), (), root / "mods")

            with (
                patch(
                    "zomboid_mod_manager.ui.window_discovery.detect_paths",
                    return_value=detected,
                ),
                patch(
                    "zomboid_mod_manager.ui.window_discovery.QInputDialog.getItem",
                    return_value=(str(second), True),
                ) as choose_installation,
            ):
                window.game_path_detect_button.click()

            self.assertEqual(window.game_path.text(), str(second))
            self.assertEqual(choose_installation.call_count, 1)

            previous = window.game_path.text()
            with (
                patch(
                    "zomboid_mod_manager.ui.window_discovery.detect_paths",
                    return_value=detected,
                ),
                patch(
                    "zomboid_mod_manager.ui.window_discovery.QInputDialog.getItem",
                    return_value=("", False),
                ),
            ):
                window.game_path_detect_button.click()
            self.assertEqual(window.game_path.text(), previous)
            self.assertIn("selection cancelled", window.status.text())

    def test_path_health_labels_report_found_missing_and_wrong_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window, _ = self._make_launch_window(root)
            self._wait_for_background_workers(window)
            found = root / "Found Folder"
            found.mkdir()
            wrong_folder = root / "not-a-folder.txt"
            wrong_folder.write_text("file", encoding="utf-8")
            missing = root / "Missing Folder"

            window.game_path.setText(str(missing))
            window._update_path_health()
            self.assertEqual(window.game_path_health.text(), "!")
            self.assertIn("Missing", window.game_path_health.toolTip())

            window.game_path.setText(str(found))
            window.local_path.setText(str(wrong_folder))
            window.workshop_paths.setText(f"{found};{missing}")
            window._update_path_health()

            self.assertEqual(window.game_path_health.text(), "✓")
            self.assertEqual(window.local_path_health.text(), "!")
            self.assertEqual(window.workshop_paths_health.text(), "!")
            self.assertIn("Not a folder", window.local_path_health.toolTip())
            self.assertIn("Zomboid/mods", window.local_path_health.toolTip())
            self.assertIn(
                "1 of 2 Workshop folders", window.workshop_paths_health.toolTip()
            )

            window.workshop_paths.setText(str(wrong_folder))
            window._update_path_health()
            self.assertIn("Not a folder", window.workshop_paths_health.toolTip())

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
            "zomboid_mod_manager.ui.window_profiles.QInputDialog.getText",
            return_value=("Weekend Pack", True),
        ):
            window.save_profile_button.click()

        self.assertEqual(profile_store.load("Weekend Pack").mod_ids, saved_order)
        self.assertEqual(profile_store.load("Weekend Pack").map_ids, ("ExampleMap",))
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
            self.assertIn("1. ModAlpha", dialog.pack_preview.toPlainText())
            self.assertIn("2. UninstalledMod", dialog.pack_preview.toPlainText())
            self.assertIn("CHANGES TO GLOBAL LIST", dialog.pack_preview.toPlainText())
            self.assertIn("OldMod", dialog.pack_preview.toPlainText())
            self.assertIn("ModAlpha", dialog.pack_preview.toPlainText())
            dialog.load_apply_button.click()
            return dialog.result()

        with (
            patch(
                "zomboid_mod_manager.ui.window_profiles.ModPacksDialog.exec",
                new=select_weekend_pack,
            ),
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
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

    def test_map_aware_mod_pack_confirms_and_applies_global_map_list(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        original = (
            "VERSION = 1,\n\nmods\n{\n    mod = ExistingMod,\n}\n\n"
            "maps\n{\n    map = ExistingMap,\n}\n"
        )
        config_path.write_text(original, encoding="utf-8")
        profile = ModProfile(
            "Imported Save",
            ("SaveMod",),
            map_ids=("Riverside, KY", "NorthMap"),
        )
        detected = DetectedPaths((), (), (), (), FIXTURES / "local_mods")
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )
        self._wait_for_background_workers(window)

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ),
        ):
            window._apply_mod_pack(profile)
        self.assertEqual(config_path.read_text(encoding="utf-8"), original)

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as confirm,
        ):
            window._apply_mod_pack(profile)
        self.assertEqual(confirm.call_count, 1)
        apply_prompt = confirm.call_args.args[2]
        self.assertIn("ExistingMod", apply_prompt)
        self.assertIn("SaveMod", apply_prompt)
        self.assertIn("ExistingMap", apply_prompt)
        self.assertIn("Riverside, KY", apply_prompt)
        self.assertEqual(read_active_mods(config_path).config.mods, ("SaveMod",))
        self.assertEqual(
            read_active_mods(config_path).config.maps, ("Riverside, KY", "NorthMap")
        )
        backups = list(config_path.parent.glob("default.txt.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
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
            "zomboid_mod_manager.ui.window_staging.QDesktopServices.openUrl"
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

    def test_discover_build_filter_scopes_mods_and_metadata_warnings(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(
            Path(temporary.name), mods=("LegacyWorkshop",)
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)

        self.assertEqual(
            [
                window.inactive_build_filter.itemText(index)
                for index in range(window.inactive_build_filter.count())
            ],
            ["Show all", "Build 41", "Build 42"],
        )
        window.metadata_preview_target.setCurrentIndex(
            window.metadata_preview_target.findData("42")
        )
        warning_item = next(
            window.active_list.item(index)
            for index in range(window.active_list.count())
            if window.active_list.item(index).data(Qt.ItemDataRole.UserRole)
            == "LegacyWorkshop"
        )
        self.assertTrue(warning_item.data(ISSUE_ROLE))

        window.inactive_build_filter.setCurrentIndex(
            window.inactive_build_filter.findData("41")
        )
        visible_ids = {
            window.available_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(window.available_list.count())
            if not window.available_list.item(index).isHidden()
        }
        self.assertIn("RepeatedDescription", visible_ids)
        self.assertNotIn("BundleAddon", visible_ids)
        warning_item = next(
            window.active_list.item(index)
            for index in range(window.active_list.count())
            if window.active_list.item(index).data(Qt.ItemDataRole.UserRole)
            == "LegacyWorkshop"
        )
        self.assertFalse(warning_item.data(ISSUE_ROLE))

        window.inactive_build_filter.setCurrentIndex(
            window.inactive_build_filter.findData("42")
        )
        visible_ids = {
            window.available_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(window.available_list.count())
            if not window.available_list.item(index).isHidden()
        }
        self.assertIn("BundleAddon", visible_ids)
        self.assertNotIn("RepeatedDescription", visible_ids)
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
        self._wait_for_background_workers(window)
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
            "zomboid_mod_manager.ui.window_details.QDesktopServices.openUrl"
        ) as open_url:
            window.open_folder_button.click()
        self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), entry_root)
        self.assertEqual(config_path.read_bytes(), original)
        window.close()

    def test_preview_label_plays_gif_and_stops_when_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            gif_path = Path(temporary) / "preview.gif"
            gif_path.write_bytes(
                base64.b64decode(
                    "R0lGODlhCAAIAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQADAAAACwAAAAACAAIAAAIDwABCBxIsKDBgwgTKkwYEAAh+QQBDAABACwAAAAACAAIAIEAAP8AAAAAAAAAAAAIDwABCBxIsKDBgwgTKkwYEAA7"
                )
            )
            preview = PreviewLabel()
            preview.resize(160, 90)
            self.assertTrue(preview.show_movie(gif_path))
            movie = preview._movie
            self.assertIsNotNone(movie)
            self.assertEqual(movie.state(), QMovie.MovieState.Running)
            frames = []
            movie.frameChanged.connect(frames.append)
            QTest.qWait(300)
            self.assertIn(1, frames)
            self.assertFalse(preview.image.isNull())

            preview.show_placeholder("No preview")
            self.assertEqual(movie.state(), QMovie.MovieState.NotRunning)
            self.assertIsNone(preview._movie)
            self.app.processEvents()

    def test_build42_root_only_entry_keeps_name_and_uses_its_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry_root = root / "LegacyMod"
            entry_root.mkdir()
            (entry_root / "mod.info").write_text(
                "name=Legacy Mod\nid=LegacyMod\nposter=poster.png\n",
                encoding="utf-8",
            )
            image = QImage(40, 30, QImage.Format.Format_ARGB32)
            image.fill(QColor("#64a7dc"))
            self.assertTrue(image.save(str(entry_root / "poster.png")))
            window = MainWindow(
                DetectedPaths((), (), (), (), root),
                active_config_path=FIXTURES / "config" / "default.txt",
                profile_store=ProfileStore(root / "profiles"),
            )
            self.addCleanup(window.close)
            self._wait_for_background_workers(window)

            window.metadata_preview_target.setCurrentIndex(
                window.metadata_preview_target.findData("42")
            )
            window.metadata_build_version.setText("42.21.0")
            item = window.available_list.item(0)
            self.assertIn("Legacy Mod", item.text())
            self.assertTrue(item.data(ISSUE_ROLE))
            self.assertIn("Build 42 ignores root-level mod files", item.toolTip())
            window.available_list.setCurrentItem(item)
            self._wait_for_background_workers(window)

            self.assertFalse(window.preview.pixmap().isNull())
            self.assertIn("root (Build 41 style)", window.preview_caption.text())
            self.assertIn(
                "does not indicate mod compatibility", window.preview_caption.text()
            )

    def test_exact_build_updates_names_details_and_dependency_diagnostics(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        local_root = base / "local-mods"
        entry_root = local_root / "Example"
        for folder, metadata in (
            (
                "common",
                "name=Shared Name\nid=Example\nrequire=MissingShared\n",
            ),
            ("42", "name=Build 42 Name\nid=Example\nrequire=MissingBase\n"),
            (
                "42.21",
                "name=Build 42.21 Name\nid=Example\nrequire=MissingCurrent\n",
            ),
        ):
            candidate = entry_root / folder / "mod.info"
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(metadata, encoding="utf-8")

        config_path = base / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = Example,\n}\n\nmaps\n{\n}\n",
            encoding="utf-8",
        )
        detected = DetectedPaths((), (), (), (), local_root)
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(base / "profiles"),
        )
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)

        window.metadata_preview_target.setCurrentIndex(
            window.metadata_preview_target.findData("42")
        )
        window.metadata_build_version.setText("42.21.0")
        window.active_list.setCurrentRow(0)
        self.app.processEvents()

        self.assertTrue(
            window.active_list.item(0).text().startswith("Build 42.21 Name")
        )
        self.assertIn("versioned (42.21)", window.details.toPlainText())
        self.assertNotIn("Shared Name", window.details.toPlainText())
        diagnostics = window.diagnostics.toPlainText()
        self.assertIn("MissingCurrent", diagnostics)
        self.assertNotIn("MissingShared", diagnostics)
        self.assertNotIn("MissingBase", diagnostics)
        window.close()

    def test_metadata_target_and_build_are_restored_from_settings(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = QSettings(
            str(Path(temporary.name) / "settings.ini"), QSettings.Format.IniFormat
        )
        settings.setValue("metadata/target", "42")
        settings.setValue("metadata/build_version", "42.21.0")
        detected = DetectedPaths((), (), (), (), None)

        with (
            patch(
                "zomboid_mod_manager.ui.main_window.QSettings", return_value=settings
            ),
            patch(
                "zomboid_mod_manager.ui.main_window.detect_paths",
                return_value=detected,
            ),
            patch.object(MainWindow, "_start_scan"),
        ):
            window = MainWindow(
                active_config_path=FIXTURES / "config" / "default.txt",
                profile_store=ProfileStore(Path(temporary.name) / "profiles"),
            )

        self.assertEqual(window.metadata_preview_target.currentData(), "42")
        self.assertEqual(window.metadata_build_version.text(), "42.21.0")
        self.assertFalse(window.metadata_build_version.isHidden())
        window.close()
        self.assertEqual(settings.value("metadata/target"), "42")

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
            "zomboid_mod_manager.ui.window_workers.scan_mods",
            side_effect=wait_until_cancelled,
        ):
            window._refresh_scan()
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

    def test_recent_slow_scan_is_reused_until_refresh_is_requested(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _ = self._make_launch_window(Path(temporary.name))
        window.show()
        deadline = time.monotonic() + 5
        while window._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertIsNotNone(window._last_result)

        local_roots, workshop_roots = window._selected_roots()
        window._last_scan_key = window._scan_key(local_roots, workshop_roots)
        window._last_scan_duration = 0.5
        window._last_scan_at = time.monotonic()
        window._last_scan_label = "12:34:56"
        with patch(
            "zomboid_mod_manager.ui.window_workers.scan_mods",
            return_value=window._last_result,
        ) as scan_mods:
            window._last_scan_duration = 0.1
            window._start_scan()
            deadline = time.monotonic() + 5
            while window._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(5)
            self.assertIsNone(window._worker)
            scan_mods.assert_called_once()

        window._last_scan_key = window._scan_key(local_roots, workshop_roots)
        window._last_scan_duration = 0.5
        window._last_scan_at = time.monotonic()
        window._last_scan_label = "12:34:56"
        window._start_scan()
        self.assertIsNone(window._worker)
        self.assertIn("reused from 12:34:56", window.status.text())

        with patch(
            "zomboid_mod_manager.ui.window_workers.scan_mods",
            return_value=window._last_result,
        ) as scan_mods:
            window._refresh_scan()
            deadline = time.monotonic() + 5
            while window._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(5)
            self.assertIsNone(window._worker)
            scan_mods.assert_called_once()
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
            "zomboid_mod_manager.ui.window_workers.scan_mods",
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

    def test_support_report_action_opens_a_redacted_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SupportPrivateUser-") as temporary:
            window, _config_path = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)

            with patch(
                "zomboid_mod_manager.ui.window_support.SupportReportDialog"
            ) as dialog_class:
                window.support_report_action.trigger()

            report = dialog_class.call_args.args[0]
            serialized = json.dumps(report)
            self.assertNotIn(temporary, serialized)
            self.assertNotIn(str(FIXTURES), serialized)
            self.assertEqual(report["discovery"]["scan_completed"], True)
            self.assertTrue(report["privacy"]["folder_paths_included"] is False)
            dialog_class.return_value.exec.assert_called_once_with()

        preview = SupportReportDialog(report)
        self.addCleanup(preview.close)
        self.assertTrue(
            any(
                "folder paths" in label.text().casefold()
                for label in preview.findChildren(QLabel)
            )
        )
        self.assertIn("schema_version", preview.preview.toPlainText())

    def test_support_report_dialog_saves_only_after_user_selects_a_file(self) -> None:
        report = {"schema_version": 1, "privacy": {"folder_paths_included": False}}
        dialog = SupportReportDialog(report)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.status.text())

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "support-report"
            with patch.object(
                QFileDialog,
                "getSaveFileName",
                return_value=(str(destination), "JSON support reports (*.json)"),
            ):
                dialog._save_report()

            saved_report = destination.with_suffix(".json")
            self.assertTrue(saved_report.is_file())
            self.assertEqual(
                json.loads(saved_report.read_text(encoding="utf-8")), report
            )
            self.assertEqual(dialog.status.text(), "Support report saved.")

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
        completed_status = window.status.text()
        window._scan_progress("Late progress message")
        self.assertEqual(window.status.text(), completed_status)
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
        deadline = time.monotonic() + 10
        while (
            window._worker is not None or window._scan_again_after_current
        ) and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIsNone(window._worker)
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
        deadline = time.monotonic() + 10
        while (
            any(worker.isRunning() for worker in window._background_workers())
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(
            any(worker.isRunning() for worker in window._background_workers())
        )
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
        stable_since = None
        while time.monotonic() < deadline:
            self.app.processEvents()
            worker = window._worker
            settled = (
                "scan complete" in window.status.text().casefold()
                and not window._scan_again_after_current
                and (worker is None or not worker.isRunning())
            )
            if settled:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 0.05:
                    break
            else:
                stable_since = None
            QTest.qWait(10)
        self.assertIn("scan complete", window.status.text().casefold())
        self.assertIsNone(window._worker)

        with patch(
            "zomboid_mod_manager.ui.window_staging.QMessageBox.question",
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
        deadline = time.monotonic() + 20
        stable_since = None
        while time.monotonic() < deadline:
            self.app.processEvents()
            worker = window._worker
            settled = (
                "scan complete" in window.status.text().casefold()
                and not window._scan_again_after_current
                and (worker is None or not worker.isRunning())
            )
            if settled:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 0.05:
                    break
            else:
                stable_since = None
            QTest.qWait(10)
        self.assertIn(
            "scan complete",
            window.status.text().casefold(),
            f"worker={window._worker!r}; rescan={window._scan_again_after_current}",
        )
        self.assertIsNone(window._worker)

        window._staged_mod_ids = ["Unsorted", "Other"]
        window._user_order_rules = ()
        with (
            patch(
                "zomboid_mod_manager.ui.window_staging.SortRulesDialog"
            ) as dialog_type,
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
        with patch(
            "zomboid_mod_manager.ui.window_staging.QMessageBox.warning"
        ) as warning:
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
            "zomboid_mod_manager.ui.window_profiles.ModPacksDialog.exec",
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
            "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
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
        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ),
        ):
            window._apply_active_configuration()
        self.assertEqual(config_path.read_bytes(), original)

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as confirm,
        ):
            window._apply_active_configuration()
        apply_prompt = confirm.call_args.args[2]
        self.assertIn("Added: AddedMod", apply_prompt)
        self.assertIn("Maps: unchanged (1)", apply_prompt)
        self.assertNotEqual(config_path.read_bytes(), original)
        self.assertEqual(
            tuple(window._active_config.config.mods), ("ExistingMod", "AddedMod")
        )
        self.assertEqual(window._active_config.config.maps, ("Muldraugh, KY",))
        backups = list(config_path.parent.glob("default.txt.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        window.close()

    def test_restore_backup_previews_and_restores_with_backup_of_current(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        current_text = (
            "VERSION = 1,\n\nmods\n{\n    mod = CurrentMod,\n}\n\n"
            "maps\n{\n    map = CurrentMap,\n}\n"
        )
        backup_text = (
            "VERSION = 1,\n\nmods\n{\n    mod = PriorMod,\n}\n\n"
            "maps\n{\n    map = PriorMap,\n}\n"
        )
        config_path.write_text(current_text, encoding="utf-8")
        current_bytes = config_path.read_bytes()
        backup_path = config_path.with_name("default.txt.bak-20261023T120000.000000Z")
        backup_path.write_text(backup_text, encoding="utf-8")
        detected = DetectedPaths((), (), (), (), FIXTURES / "local_mods")
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=ProfileStore(root / "profiles"),
        )
        self.addCleanup(window.close)
        self._wait_for_background_workers(window)

        def choose_backup(dialog: GlobalBackupDialog) -> QDialog.DialogCode:
            self.assertIn("PriorMod", dialog.preview.toPlainText())
            dialog._accept_selected()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(GlobalBackupDialog, "exec", new=choose_backup),
            patch.object(
                QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes
            ),
        ):
            window._restore_active_configuration_backup()

        self.assertEqual(window._active_config.config.mods, ("PriorMod",))
        self.assertEqual(window._active_config.config.maps, ("PriorMap",))
        self.assertEqual(config_path.read_text(encoding="utf-8"), backup_text)
        current_backups = [
            path
            for path in config_path.parent.glob("default.txt.bak-*")
            if path != backup_path
        ]
        self.assertEqual(len(current_backups), 1)
        self.assertEqual(current_backups[0].read_bytes(), current_bytes)
        self.assertIn(
            "Restored the global mod list", window.configuration_status.text()
        )

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
            "zomboid_mod_manager.ui.window_details.QDesktopServices.openUrl"
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

    def test_collection_dialog_opens_missing_item_but_not_foreign_app_page(
        self,
    ) -> None:
        scan_result = ScanResult(local_entries=(), workshop_items=(), diagnostics=())
        dialog = WorkshopCollectionDialog(scan_result)
        collection = WorkshopCollectionResult(
            collection_id="1000000000",
            items=(
                WorkshopItemMetadata(
                    workshop_id="1111111111",
                    title="Missing PZ Mod",
                    description="",
                    consumer_app_id=108600,
                    updated_at=None,
                ),
            ),
            unavailable_ids=("2222222222",),
            foreign_app_ids=("3333333333",),
        )
        dialog._show_collection(collection)

        dialog.items.setCurrentCell(0, 0)
        self.assertTrue(dialog.open_missing_workshop_button.isEnabled())
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.QDesktopServices.openUrl"
        ) as open_url:
            dialog.open_missing_workshop_button.click()
        open_url.assert_called_once_with(
            QUrl("https://steamcommunity.com/sharedfiles/filedetails/?id=1111111111")
        )

        dialog.items.setCurrentCell(1, 0)
        self.assertTrue(dialog.open_missing_workshop_button.isEnabled())
        with patch(
            "zomboid_mod_manager.ui.workshop_dialog.QDesktopServices.openUrl"
        ) as open_url:
            dialog.open_missing_workshop_button.click()
        open_url.assert_called_once_with(
            QUrl("https://steamcommunity.com/sharedfiles/filedetails/?id=2222222222")
        )

        dialog.items.setCurrentCell(2, 0)
        self.assertFalse(dialog.open_missing_workshop_button.isEnabled())
        dialog.close()

    def test_use_installed_build_refreshes_target_and_clears_stale_version(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "steamapps" / "common" / "ProjectZomboid"
            game.mkdir(parents=True)
            (game.parents[1] / "appmanifest_108600.acf").write_text(
                '"AppState" { "BetaKey" "legacy41" }', encoding="utf-8"
            )
            detected = DetectedPaths(
                steam_roots=(),
                steamapps_libraries=(),
                game_installations=(game,),
                workshop_roots=(),
                local_mod_root=FIXTURES / "local_mods",
            )
            window = MainWindow(
                detected,
                active_config_path=FIXTURES / "config" / "default.txt",
                profile_store=ProfileStore(Path(temporary) / "profiles"),
            )
            self.addCleanup(window.close)
            window.metadata_preview_target.setCurrentIndex(
                window.metadata_preview_target.findData("42")
            )
            window.metadata_build_version.setText("42.21.0")

            window._use_detected_game_build()

            self.assertEqual(window.metadata_preview_target.currentData(), "41")
            self.assertEqual(window.metadata_build_version.text(), "")
            self.assertIn("legacy41", window.game_build_status.text())
            self._wait_for_background_workers(window)

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
        self.assertIsNotNone(window._file_overlap_dialog)
        window._file_overlap_dialog.close()
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
            "zomboid_mod_manager.ui.window_diagnostics.QFileDialog.getOpenFileName",
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

    def test_file_overlap_dialog_filters_by_path_mod_id_and_status(self) -> None:
        first_example = FileOverlap(
            "media/scripts/shared.lua",
            "AlphaMod",
            "BetaMod",
            Path("alpha/media/scripts/shared.lua"),
            Path("beta/media/scripts/shared.lua"),
            Path("alpha/mod.info"),
            Path("beta/mod.info"),
            "different",
        )
        second_example = FileOverlap(
            "media/scripts/shared.lua",
            "GammaMod",
            "DeltaMod",
            Path("gamma/media/scripts/shared.lua"),
            Path("delta/media/scripts/shared.lua"),
            Path("gamma/mod.info"),
            Path("delta/mod.info"),
            "unverified",
        )
        report = FileOverlapReport(
            candidate_count=4,
            entry_count=4,
            target_build="all",
            staged_only=False,
            files_scanned=4,
            overlap_count=3,
            different_count=2,
            unverified_count=1,
            unique_path_count=2,
            path_groups=(
                FileOverlapPathGroup(
                    "media/scripts/shared.lua",
                    2,
                    1,
                    1,
                    ("AlphaMod", "BetaMod", "GammaMod", "DeltaMod"),
                    (first_example, second_example),
                ),
                FileOverlapPathGroup(
                    "media/textures/unique.png",
                    1,
                    1,
                    0,
                    ("AlphaMod", "OmegaMod"),
                    (first_example,),
                ),
            ),
            path_groups_limited=False,
            overlaps=(first_example, second_example),
            skipped_files=0,
            truncated=False,
            details_limited=True,
        )
        dialog = FileOverlapDialog(report)
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.table.rowCount(), 2)
        dialog.status_filter.setCurrentIndex(1)
        self.assertEqual(dialog.table.rowCount(), 2)
        dialog.search.setText("OmegaMod")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).text(), "media/textures/unique.png")
        dialog.status_filter.setCurrentIndex(2)
        self.assertEqual(dialog.table.rowCount(), 0)
        dialog.search.clear()
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertIn("content comparison unavailable", dialog.details.toPlainText())

    def test_file_overlap_dialog_searches_all_paths_and_loads_more_rows(self) -> None:
        groups = []
        for index in range(300):
            relative_path = f"media/scripts/shared-{index:03}.lua"
            mod_id = f"Mod{index:03}"
            example = FileOverlap(
                relative_path,
                mod_id,
                "OtherMod",
                Path(f"{mod_id}/{relative_path}"),
                Path(f"OtherMod/{relative_path}"),
                Path(f"{mod_id}/mod.info"),
                Path("OtherMod/mod.info"),
                "different",
            )
            groups.append(
                FileOverlapPathGroup(
                    relative_path,
                    1,
                    1,
                    0,
                    (mod_id, "OtherMod"),
                    (example,),
                )
            )
        report = FileOverlapReport(
            candidate_count=2,
            entry_count=2,
            target_build="42.21.0",
            staged_only=True,
            files_scanned=600,
            overlap_count=300,
            different_count=300,
            unverified_count=0,
            unique_path_count=300,
            path_groups=tuple(groups),
            path_groups_limited=False,
            overlaps=tuple(group.examples[0] for group in groups[:100]),
            skipped_files=0,
            truncated=False,
            details_limited=True,
        )
        dialog = FileOverlapDialog(report)
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.table.rowCount(), 250)
        self.assertFalse(dialog.load_more_button.isHidden())
        self.assertIn(
            "search covers all 300 analyzed paths", dialog.result_status.text()
        )
        dialog.search.setText("Mod299")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).text(), "media/scripts/shared-299.lua")
        dialog.search.clear()
        self.assertEqual(dialog.table.rowCount(), 250)
        dialog.load_more_button.click()
        self.assertEqual(dialog.table.rowCount(), 300)
        self.assertTrue(dialog.load_more_button.isHidden())

    def test_file_overlap_analysis_uses_selected_target_and_active_scope(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))
        result = ScanResult((), (), ())
        window._last_result = result
        window._staged_mod_ids = ["AlphaMod", "BetaMod"]
        window.metadata_preview_target.setCurrentIndex(
            window.metadata_preview_target.findData("41")
        )

        with (
            patch.object(window, "_start_diagnostic") as start_diagnostic,
            patch(
                "zomboid_mod_manager.ui.window_diagnostics.analyze_file_overlaps"
            ) as analyze,
        ):
            window.file_overlap_active_only.setChecked(True)
            window._analyze_file_overlaps()
            self.assertEqual(start_diagnostic.call_args.args[0], "file-overlaps")
            start_diagnostic.call_args.args[1]()
            analyze.assert_called_once_with(
                result,
                target_build="41",
                active_mod_ids=("AlphaMod", "BetaMod"),
            )

            start_diagnostic.reset_mock()
            analyze.reset_mock()
            window.file_overlap_active_only.setChecked(False)
            window._analyze_file_overlaps()
            start_diagnostic.call_args.args[1]()
            analyze.assert_called_once_with(
                result,
                target_build="41",
                active_mod_ids=None,
            )


if __name__ == "__main__":
    unittest.main()
