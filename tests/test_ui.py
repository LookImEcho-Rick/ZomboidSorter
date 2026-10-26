from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, QPoint, QRect, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QMovie
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
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
from zomboid_mod_manager.profiles import CollectionContent, ModProfile, ProfileStore
from zomboid_mod_manager.save_packs import GameSave, SaveAssignmentStore, save_key
from zomboid_mod_manager.sorting.user_rules import (
    UserOrderRule,
    parse_user_order_rules,
)
from zomboid_mod_manager.ui.file_overlap_dialog import FileOverlapDialog
from zomboid_mod_manager.ui.global_backup_dialog import GlobalBackupDialog
from zomboid_mod_manager.ui.main_window import MainWindow
from zomboid_mod_manager.ui.mod_packs_dialog import ModPacksDialog
from zomboid_mod_manager.ui.save_packs_dialog import SavePacksDialog, SavePickerDialog
from zomboid_mod_manager.ui.support_report_dialog import SupportReportDialog
from zomboid_mod_manager.ui.window_lifecycle import fit_window_geometry
from zomboid_mod_manager.ui.window_widgets import ISSUE_ROLE, PreviewLabel
from zomboid_mod_manager.ui.workshop_browser import (
    WorkshopBrowserPanel,
    _configure_persistent_profile,
)
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

    def test_window_geometry_fits_available_screen_and_preserves_valid_bounds(
        self,
    ) -> None:
        available = QRect(0, 0, 1280, 720)
        minimum = QSize(980, 680)
        cases = (
            (
                QRect(-2560, -200, 1440, 850),
                QRect(0, 0, 1280, 720),
            ),
            (
                QRect(-120, 50, 1100, 700),
                QRect(0, 20, 1100, 700),
            ),
            (
                QRect(100, 10, 1100, 700),
                QRect(100, 10, 1100, 700),
            ),
        )
        for geometry, expected in cases:
            with self.subTest(geometry=geometry):
                self.assertEqual(
                    fit_window_geometry(geometry, available, minimum), expected
                )

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

        def complete_update_check() -> None:
            worker = window._update_check_worker
            if worker is None:
                raise AssertionError("Update check worker was not created.")
            worker.result_ready.emit(check_for_update(__version__, "source"))
            worker.finished.emit()

        with (
            patch(
                "zomboid_mod_manager.ui.window_workers.check_for_update",
                return_value=None,
            ) as check_for_update,
            patch(
                "zomboid_mod_manager.ui.window_workers.UpdateCheckWorker.start",
                autospec=True,
                side_effect=complete_update_check,
            ) as start_update_check,
            patch(
                "zomboid_mod_manager.ui.window_updates.QMessageBox.information"
            ) as information,
            patch(
                "zomboid_mod_manager.ui.window_updates.QMessageBox.warning"
            ) as warning,
        ):
            window.update_button.click()
            deadline = time.monotonic() + 5
            while not window.update_button.isEnabled() and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(10)

        self.assertTrue(window.update_button.isEnabled())
        self.assertEqual(window.update_button.text(), "Check for Updates")
        self.assertIn("up to date", window.status.text().casefold())
        start_update_check.assert_called_once()
        check_for_update.assert_called_once_with(__version__, "source")
        information.assert_called_once()
        warning.assert_not_called()

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
        self.assertIs(
            panel.workshop_browser_layout.currentWidget(),
            panel.workshop_browser_placeholder,
        )

    def test_workshop_browser_preloads_home_once(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        browser = Mock()

        def ensure_browser():
            panel._browser_loaded = True
            return browser

        with patch.object(panel, "_ensure_browser", side_effect=ensure_browser):
            panel.preload_home()
            panel.preload_home()

        browser.setUrl.assert_called_once_with(
            QUrl("https://steamcommunity.com/app/108600/workshop/")
        )

    def test_workshop_browser_loading_surface_hides_white_renderer_until_ready(
        self,
    ) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        page = Mock()
        page.recommendedState.return_value = QWebEnginePage.LifecycleState.Active

        class FakeBrowser(QWidget):
            def page(self):
                return page

        browser = FakeBrowser(panel.workshop_browser_container)
        panel.workshop_browser = browser
        panel.workshop_browser_layout.addWidget(browser)

        panel._browser_load_started()
        self.assertIs(
            panel.workshop_browser_layout.currentWidget(),
            panel.workshop_browser_placeholder,
        )
        self.assertIn("Connecting", panel.workshop_browser_placeholder.text())

        panel._browser_load_finished(True)
        self.assertIs(panel.workshop_browser_layout.currentWidget(), browser)

    def test_hidden_workshop_browser_freezes_when_chromium_recommends_it(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        browser = Mock()
        browser.isVisible.return_value = False
        page = Mock()
        page.lifecycleState.return_value = QWebEnginePage.LifecycleState.Active
        page.recommendedState.return_value = QWebEnginePage.LifecycleState.Frozen
        page.isLoading.return_value = False
        browser.page.return_value = page
        panel.workshop_browser = browser

        panel._sync_browser_lifecycle()

        page.setLifecycleState.assert_called_once_with(
            QWebEnginePage.LifecycleState.Frozen
        )

    def test_visited_hidden_workshop_page_releases_renderer_after_delay(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        panel._tab_ever_opened = True
        browser = Mock()
        browser.isVisible.return_value = False
        page = Mock()
        page.lifecycleState.return_value = QWebEnginePage.LifecycleState.Frozen
        page.recommendedState.return_value = QWebEnginePage.LifecycleState.Discarded
        browser.page.return_value = page
        panel.workshop_browser = browser

        panel._sync_browser_lifecycle()
        self.assertTrue(panel._hidden_discard_timer.isActive())
        panel._discard_hidden_browser()

        page.setLifecycleState.assert_called_once_with(
            QWebEnginePage.LifecycleState.Discarded
        )

    def test_busy_hidden_workshop_page_also_releases_renderer(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        panel._tab_ever_opened = True
        browser = Mock()
        browser.isVisible.return_value = False
        page = Mock()
        page.lifecycleState.return_value = QWebEnginePage.LifecycleState.Active
        page.recommendedState.return_value = QWebEnginePage.LifecycleState.Active
        browser.page.return_value = page
        panel.workshop_browser = browser

        panel._sync_browser_lifecycle()
        self.assertTrue(panel._hidden_discard_timer.isActive())
        page.setLifecycleState.assert_not_called()
        panel._discard_hidden_browser()

        page.setLifecycleState.assert_called_once_with(
            QWebEnginePage.LifecycleState.Discarded
        )

    def test_active_workshop_browser_resumes_after_hidden_tab(self) -> None:
        panel = WorkshopBrowserPanel()
        self.addCleanup(panel.deleteLater)
        browser = Mock()
        page = Mock()
        page.lifecycleState.return_value = QWebEnginePage.LifecycleState.Frozen
        browser.page.return_value = page
        panel.workshop_browser = browser

        panel.set_tab_active(True)

        page.setLifecycleState.assert_called_once_with(
            QWebEnginePage.LifecycleState.Active
        )

    def test_workshop_browser_profile_persists_session_cookies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage_root = Path(temporary) / "workshop-browser"
            profile = Mock()
            _configure_persistent_profile(profile, storage_root)

            self.assertTrue((storage_root / "storage").is_dir())
            self.assertTrue((storage_root / "cache").is_dir())
            profile.setPersistentStoragePath.assert_called_once_with(
                str(storage_root / "storage")
            )
            profile.setCachePath.assert_called_once_with(str(storage_root / "cache"))
            profile.setPersistentCookiesPolicy.assert_called_once_with(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
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
        self.assertEqual(window.launch_game_button.text(), "Apply && Launch…")

        def cancel_apply_confirmation(box):
            self.assertEqual(box.windowTitle(), "Apply Changes and Launch")
            self.assertIn("save a backup first", box.informativeText())
            self.assertIn("your save files", box.informativeText().casefold())
            next(
                button for button in box.buttons() if button.text() == "Cancel"
            ).click()

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.exec",
                new=cancel_apply_confirmation,
            ),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl"
            ) as open_url,
        ):
            window._launch_project_zomboid()
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

        def accept_apply_confirmation(box):
            next(
                button for button in box.buttons() if button.text() == "Apply & Launch"
            ).click()

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.exec",
                new=accept_apply_confirmation,
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

    def test_loaded_collection_launch_prioritizes_local_pack_copies(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))
        self._wait_for_background_workers(window)
        window._loaded_collection_mod_ids = ("PackA",)
        window._confirm_configuration_preflight = lambda _action: True

        with patch(
            "zomboid_mod_manager.ui.window_configuration.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            window._launch_project_zomboid()

        self.assertEqual(
            bytes(open_url.call_args.args[0].toEncoded()).decode("ascii"),
            "steam://run/108600//-modfolders%20mods,workshop,steam",
        )
        self.assertIn("local copies were prioritized", window.status.text())

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
        self.assertEqual(window.activate_button.text(), "Add →")
        self.assertIn("stages the change", window.activate_button.toolTip())
        self.assertEqual(window.deactivate_button.text(), "← Remove")
        self.assertIn(
            "installed mod files stay in place", window.deactivate_button.toolTip()
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
        self.assertEqual(window.available_list.accessibleName(), "Available mods")
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
        staged_before_double_click = tuple(window._staged_mod_ids)
        other_available = next(
            window.available_list.item(i)
            for i in range(window.available_list.count())
            if window.available_list.item(i) is not item
            and window.available_list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled
        )
        other_available_id = other_available.data(Qt.ItemDataRole.UserRole)
        other_available.setSelected(True)
        item.setSelected(True)
        window.available_list.itemDoubleClicked.emit(item)
        self.assertEqual(
            tuple(window._staged_mod_ids),
            (*staged_before_double_click, "RepeatedDescription"),
        )
        self.assertNotIn(other_available_id, window._staged_mod_ids)
        active_item = window.active_list.item(0)
        active_mod_id = active_item.data(Qt.ItemDataRole.UserRole)
        window.active_list.item(1).setSelected(True)
        active_item.setSelected(True)
        window.active_list.itemDoubleClicked.emit(active_item)
        self.assertNotIn(active_mod_id, window._staged_mod_ids)
        self.assertIn("RepeatedDescription", window._staged_mod_ids)
        self.assertEqual(window.select_filtered_button.text(), "Select 3")
        self.assertTrue(window.open_workshop_button.isEnabled())
        window.manage_search.setText("not present in these fixtures")
        self.app.processEvents()
        self.assertEqual(window.available_list.visible_count, 0)
        self.assertIn("No mods match", window.available_list.empty_text)
        self.assertIn("0 of 4", window.inactive_heading.text())
        self.assertEqual(window.select_filtered_button.text(), "Select 0")
        self.assertFalse(window.select_filtered_button.isEnabled())
        self.assertFalse(window.activate_button.isEnabled())
        self._wait_for_background_workers(window)
        window.close()

    def test_workspace_rebuild_preserves_active_and_discover_scroll_positions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _config_path = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            base_entry = window._last_result.entries[0]
            base_candidate = base_entry.candidates[0]
            entries = []
            for index in range(60):
                mod_id = f"ScrollTest{index:02d}"
                name = f"Scroll Test {index:02d}"
                candidate = replace(
                    base_candidate,
                    fields={**base_candidate.fields, "id": mod_id, "name": name},
                )
                entries.append(
                    replace(
                        base_entry,
                        key=mod_id,
                        mod_id=mod_id,
                        name=name,
                        source="local",
                        workshop_id=None,
                        candidates=(candidate,),
                    )
                )
            window._last_result = ScanResult(tuple(entries), (), ())
            window._staged_mod_ids = [entry.mod_id for entry in entries[:30]]
            window.resize(1400, 800)
            window.show()
            window._refresh_management_lists()
            self.app.processEvents()

            active_scroll = window.active_list.verticalScrollBar()
            available_scroll = window.available_list.verticalScrollBar()
            self.assertGreater(active_scroll.maximum(), 0)
            self.assertGreater(available_scroll.maximum(), 0)
            available_id = window.available_list.item(0).data(Qt.ItemDataRole.UserRole)
            active_id = window.active_list.item(1).data(Qt.ItemDataRole.UserRole)
            window.available_list.setCurrentRow(0)
            window.active_list.setCurrentRow(1)
            self.assertIn(f"Mod ID: {active_id}", window.details.toPlainText())
            active_scroll.setValue(min(8, active_scroll.maximum()))
            available_scroll.setValue(min(11, available_scroll.maximum()))
            expected_active = active_scroll.value()
            expected_available = available_scroll.value()

            window._refresh_management_lists()
            self.app.processEvents()

            self.assertEqual(active_scroll.value(), expected_active)
            self.assertEqual(available_scroll.value(), expected_available)
            self.assertEqual(
                window.active_list.currentItem().data(Qt.ItemDataRole.UserRole),
                active_id,
            )
            self.assertEqual(
                window.available_list.currentItem().data(Qt.ItemDataRole.UserRole),
                available_id,
            )
            self.assertIn(f"Mod ID: {active_id}", window.details.toPlainText())
            self.assertEqual(
                window._staged_mod_ids, [entry.mod_id for entry in entries[:30]]
            )
            window.close()

    def test_scan_summary_uses_singular_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            entry = window._last_result.entries[0]
            metadata_count = len(entry.candidates)
            window._show_result(ScanResult((entry,), (), ()))

            summary = window.status.text()
            self.assertIn("1 mod entry;", summary)
            self.assertIn("0 Workshop items;", summary)
            self.assertIn(f"{metadata_count} metadata file", summary)
            self.assertNotIn("1 mod entries", summary)
            window.close()

    def test_empty_scan_points_to_paths_and_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            window._last_result = ScanResult((), (), ())
            window._filter_available_mods("")

            self.assertIn("No mod entries were found", window.available_list.empty_text)
            self.assertIn("Paths & Settings", window.available_list.empty_text)
            self.assertIn("refresh", window.available_list.empty_text)
            window.close()

    def test_library_table_explains_empty_and_no_match_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            entry = window._last_result.entries[0]
            window._show_result(ScanResult((entry,), (), ()))
            self.assertIs(window.library_table_stack.currentWidget(), window.table)
            self.assertEqual(
                window.table_model.item(0, 6).text(), entry.entry_path.name
            )
            self.assertEqual(
                window.table_model.item(0, 6).toolTip(), str(entry.entry_path)
            )

            window.search.setText("no matching mod")
            self.assertIs(
                window.library_table_stack.currentWidget(),
                window.library_table_empty,
            )
            self.assertIn(
                "No mods match this search", window.library_table_empty.text()
            )
            self.assertIn("Clear the search", window.library_table_empty.text())

            window.search.clear()
            self.assertIs(window.library_table_stack.currentWidget(), window.table)
            window._show_result(ScanResult((), (), ()))
            self.assertIs(
                window.library_table_stack.currentWidget(),
                window.library_table_empty,
            )
            self.assertIn(
                "No mod entries were found", window.library_table_empty.text()
            )
            self.assertIn("Paths & Settings", window.library_table_empty.text())
            window.close()

    def test_library_table_columns_fit_a_normal_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            window.resize(1440, 850)
            window.show()
            self._wait_for_background_workers(window)
            window.main_tabs.setCurrentWidget(window.library_page)
            self.app.processEvents()

            self.assertLessEqual(window.table.horizontalScrollBar().maximum(), 1)
            self.assertEqual(
                window.table_model.horizontalHeaderItem(6).text(), "Installed folder"
            )
            window.close()

    def test_empty_mod_pack_manager_shows_one_starting_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dialog = ModPacksDialog(ProfileStore(Path(temporary) / "profiles"))

            self.assertEqual(dialog.pack_list.count(), 0)
            self.assertTrue(dialog.details.isHidden())
            self.assertTrue(dialog.pack_preview.isHidden())
            self.assertFalse(dialog.load_apply_button.isEnabled())
            self.assertTrue(dialog.import_button.isEnabled())
            dialog.close()

    def test_mod_pack_summary_describes_order_only_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile_store = ProfileStore(Path(temporary) / "profiles")
            profile_store.save(ModProfile("Reordered Pack", ("Second", "First")))
            dialog = ModPacksDialog(
                profile_store,
                current_mod_ids=("First", "Second"),
                current_map_ids=(),
            )
            dialog.pack_list.setCurrentRow(0)

            self.assertEqual(
                dialog.change_summary.text(),
                "Changes the order of 2 mods.\nYour current map list stays the same.",
            )
            dialog.close()

            profile_store.save(ModProfile("Current Pack", ("First", "Second")))
            current_dialog = ModPacksDialog(
                profile_store,
                current_mod_ids=("First", "Second"),
                current_map_ids=(),
            )
            current_dialog.pack_list.setCurrentRow(0)

            self.assertEqual(
                current_dialog.backup_note.text(), "No game-list change is needed."
            )
            current_dialog.close()

    def test_small_window_keeps_paths_and_primary_actions_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            window.resize(980, 680)
            window.show()
            self._wait_for_background_workers(window)
            self.app.processEvents()
            window._staged_mod_ids.append("MissingMod")
            window._update_diagnostics()
            window.active_list.setFocus()
            QTest.keyClick(window.active_list, Qt.Key.Key_Tab)
            self.assertIs(QApplication.focusWidget(), window.review_active_order_button)

            self.assertEqual(window.launch_game_button.text(), "Launch Game")
            self.assertEqual(window.apply_config_button.text(), "Apply List…")
            self.assertGreaterEqual(
                window.select_filtered_button.width(),
                window.select_filtered_button.fontMetrics().horizontalAdvance(
                    window.select_filtered_button.text()
                )
                + 12,
            )
            self.assertEqual(window.detail_tabs.count(), 2)
            self.assertFalse(window.workflow_hint.isVisible())
            self.assertTrue(window.review_active_order_button.isVisible())
            self.assertLessEqual(
                window.review_active_order_button.geometry().right(),
                window.review_active_order_button.parentWidget().rect().right(),
            )
            self.assertTrue(window.review_library_findings_button.isVisible())
            self.assertLessEqual(
                window.review_library_findings_button.geometry().right(),
                window.review_library_findings_button.parentWidget().rect().right(),
            )

            window.main_tabs.setCurrentWidget(window.setup_page)
            self.app.processEvents()
            self.assertGreaterEqual(window.game_path.height(), 25)
            self.assertGreaterEqual(window.local_path.height(), 25)
            self.assertGreaterEqual(window.game_path.width(), 250)
            self.assertTrue(window.detect_all_paths_button.isVisible())
            self.assertTrue(window.game_path_detect_button.isVisible())
            self.assertTrue(window.game_path_health.isVisible())

    def test_small_window_keyboard_path_reaches_discover_action_and_details(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            window.resize(980, 680)
            window.show()
            self._wait_for_background_workers(window)
            self.app.processEvents()

            self.assertEqual(window.available_list.count(), 5)
            self.assertTrue(window.select_filtered_button.isEnabled())
            window.available_list.setCurrentRow(0)
            self.app.processEvents()
            self.assertTrue(window.activate_button.isEnabled())
            window.manage_search.setFocus()
            self.app.processEvents()
            self.assertIs(window.focusWidget(), window.manage_search)

            focus_path: list[QWidget] = []
            for _ in range(20):
                focused = window.focusWidget()
                self.assertIsNotNone(focused)
                QTest.keyClick(focused, Qt.Key.Key_Tab)
                self.app.processEvents()
                focused = window.focusWidget()
                if focused is not None:
                    focus_path.append(focused)
                if focused is window.detail_tabs.tabBar():
                    break

            self.assertIn(window.select_filtered_button, focus_path)
            self.assertIn(window.activate_button, focus_path)
            self.assertIn(window.active_search, focus_path)
            self.assertNotIn(window.metadata_preview_target, focus_path)
            self.assertLess(
                focus_path.index(window.select_filtered_button),
                focus_path.index(window.activate_button),
            )
            self.assertLess(
                focus_path.index(window.activate_button),
                focus_path.index(window.active_search),
            )
            self.assertIs(window.focusWidget(), window.detail_tabs.tabBar())

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
            self.assertIn("Paths && Settings", tab_labels)
            self.assertIn("Library && Diagnostics", tab_labels)
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
        self.assertTrue(
            window.workspace_page.isAncestorOf(window.view_pack_saves_button)
        )
        self.assertIn("Default", profile_store.list_names())
        self.assertEqual(profile_store.load("Default").mod_ids, ())
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

        with (
            patch(
                "zomboid_mod_manager.ui.window_profiles.QInputDialog.getText",
                return_value=("Default", True),
            ),
            patch(
                "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            window.save_profile_button.click()
        self.assertEqual(profile_store.load("Default").mod_ids, saved_order)
        self.assertTrue(list(profile_store.backup_root.glob("Default.json.*")))
        self.assertEqual(config_path.read_bytes(), original_config)
        window.close()

    def test_pack_saves_dialog_only_changes_app_owned_groupings(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        profiles = ProfileStore(root / "profiles")
        profiles.save(ModProfile("Weekend Pack", ("Base",)))
        save_dir = root / "Zomboid" / "Saves" / "Sandbox" / "Rosewood"
        save_dir.mkdir(parents=True)
        mods_file = save_dir / "mods.txt"
        mods_file.write_text("game save data stays unchanged\n", encoding="utf-8")
        key = save_key("Sandbox", "Rosewood")
        assignments = SaveAssignmentStore(profiles.root.parent)
        assignments.assign(key, "Weekend Pack")

        dialog = SavePacksDialog(profiles, "Weekend Pack", save_dir.parents[1])
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.saves_list.count(), 1)
        self.assertEqual(dialog.saves_list.item(0).text(), "Rosewood · Sandbox")
        self.assertEqual(dialog.status.text(), "1 save grouped under 'Weekend Pack'.")
        self.assertFalse(dialog.add_button.isEnabled())

        dialog._remove_selected()
        self.assertIsNone(assignments.assigned_pack(key))
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertTrue(save_dir.is_dir())
        self.assertEqual(
            mods_file.read_text(encoding="utf-8"),
            "game save data stays unchanged\n",
        )

        class SelectedSave:
            def __init__(self) -> None:
                self.selected_key = key

            def exec(self) -> int:
                return QDialog.DialogCode.Accepted

        with patch(
            "zomboid_mod_manager.ui.save_packs_dialog.SavePickerDialog",
            return_value=SelectedSave(),
        ):
            dialog._add_save()

        self.assertEqual(assignments.assigned_pack(key), "Weekend Pack")
        self.assertFalse(dialog.add_button.isEnabled())
        self.assertEqual(
            mods_file.read_text(encoding="utf-8"),
            "game save data stays unchanged\n",
        )

    def test_save_picker_filter_status_recovers_and_unreadable_groupings_block_add(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saves = (
                GameSave(
                    save_key("Sandbox", "Rosewood"),
                    "Rosewood",
                    "Sandbox",
                    root / "Rosewood",
                ),
                GameSave(
                    save_key("Sandbox", "Muldraugh"),
                    "Muldraugh",
                    "Sandbox",
                    root / "Muldraugh",
                ),
            )
            assignments = SaveAssignmentStore(root)
            dialog = SavePickerDialog(saves, assignments, "Weekend Pack")
            self.addCleanup(dialog.close)
            self.assertEqual(dialog.status.text(), "2 saves available to add.")
            dialog.search.setText("nowhere")
            self.assertIn("No saves match", dialog.status.text())
            self.assertFalse(dialog.add_button.isEnabled())
            dialog.search.clear()
            self.assertEqual(dialog.status.text(), "2 saves available to add.")

            assignments.path.write_text("not json", encoding="utf-8")
            blocked = SavePickerDialog(saves, assignments, "Weekend Pack")
            self.addCleanup(blocked.close)
            self.assertIn("not valid UTF-8 JSON", blocked.status.text())
            self.assertFalse(blocked.add_button.isEnabled())
            self.assertFalse(blocked.saves_list.isEnabled())

            pack_dialog = SavePacksDialog(
                ProfileStore(root / "profiles"), "Weekend Pack", root / "Saves"
            )
            self.addCleanup(pack_dialog.close)
            self.assertIn("not valid UTF-8 JSON", pack_dialog.status.text())
            self.assertFalse(pack_dialog.add_button.isEnabled())
            self.assertFalse(pack_dialog.remove_button.isEnabled())

    def test_saves_button_is_enabled_for_the_currently_loaded_pack(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config_path = root / "Zomboid" / "mods" / "default.txt"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "VERSION = 1,\n\nmods\n{\n    mod = Base,\n}\n\nmaps\n{\n}\n",
            encoding="utf-8",
        )
        profile_store = ProfileStore(root / "profiles")
        pack_name = f"Current Pack {root.name}"
        profile = ModProfile(pack_name, ("Base",))
        profile_store.save(profile)
        detected = DetectedPaths(
            (), (), (), (FIXTURES / "workshop",), FIXTURES / "local_mods"
        )
        window = MainWindow(
            detected,
            active_config_path=config_path,
            profile_store=profile_store,
        )

        def close_when_workers_finish() -> None:
            self._wait_for_background_workers(window)
            window.close()

        self.addCleanup(close_when_workers_finish)

        self.assertFalse(window.view_pack_saves_button.isEnabled())
        window._apply_mod_pack(profile)
        self.assertTrue(window.view_pack_saves_button.isEnabled())
        self.assertEqual(window._loaded_profile_name, pack_name)

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
                dialog.pack_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(dialog.pack_list.count())
            ]
            self.assertEqual(names, ["Other Pack", "Weekend Pack"])
            self.assertEqual(dialog.pack_list.currentRow(), -1)
            self.assertFalse(dialog.load_apply_button.isEnabled())
            item = next(
                dialog.pack_list.item(row)
                for row in range(dialog.pack_list.count())
                if dialog.pack_list.item(row).data(Qt.ItemDataRole.UserRole)
                == "Weekend Pack"
            )
            dialog.pack_list.setCurrentItem(item)
            self.assertTrue(dialog.load_apply_button.isEnabled())
            self.assertEqual(dialog.load_apply_button.text(), "Load & Apply")
            self.assertIn("adds 2 mods", dialog.change_summary.text().casefold())
            self.assertIn("removes 1 mod", dialog.change_summary.text().casefold())
            self.assertFalse(dialog.pack_preview.isVisible())
            dialog.details_toggle.click()
            self.assertIn("1. ModAlpha", dialog.pack_preview.toPlainText())
            self.assertIn("2. UninstalledMod", dialog.pack_preview.toPlainText())
            self.assertIn(
                "DETAILED GAME-LIST CHANGES", dialog.pack_preview.toPlainText()
            )
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

    def test_collection_pack_starts_loading_without_extra_confirmation(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))
        self._wait_for_background_workers(window)
        profile = ModProfile(
            "Workshop Pack",
            (),
            ("12345",),
            None,
            (CollectionContent("12345", "a" * 64),),
        )
        dialog = Mock()
        dialog.exec.return_value = QDialog.DialogCode.Accepted
        dialog.result_data = (object(), ScanResult((), (), ()))

        with (
            patch(
                "zomboid_mod_manager.ui.window_profiles.CollectionLoadDialog",
                return_value=dialog,
            ) as load_dialog,
            patch.object(window, "_show_result"),
            patch.object(window, "_apply_staged_configuration", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_profiles.QMessageBox.question"
            ) as confirm,
        ):
            window._load_collection_mod_pack(profile)

        load_dialog.assert_called_once()
        self.assertEqual(
            load_dialog.call_args.kwargs["initial"],
            "Preparing 'Workshop Pack' for Project Zomboid…",
        )
        confirm.assert_not_called()
        self.assertEqual(window._loaded_profile_name, "Workshop Pack")
        self.assertIn("Launch Project Zomboid from ZomboidSorter", window.status.text())
        window.close()

    def test_mod_pack_keeps_previous_staging_when_replaced_or_cancelled(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, config_path = self._make_launch_window(
            Path(temporary.name), mods=("Original",)
        )
        self._wait_for_background_workers(window)
        window._staged_mod_ids = ["Unfinished"]
        window._profile_workshop_ids = ("12345",)
        window._update_apply_enabled()
        profile = ModProfile("New Pack", ("PackMod",))

        with patch(
            "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            window._apply_mod_pack(profile)
        self.assertEqual(window._staged_mod_ids, ["Unfinished"])
        self.assertEqual(window._profile_workshop_ids, ("12345",))

        with (
            patch(
                "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(
                window, "_confirm_configuration_preflight", return_value=False
            ),
        ):
            window._apply_mod_pack(profile)
        self.assertEqual(window._staged_mod_ids, ["Unfinished"])
        self.assertEqual(window._profile_workshop_ids, ("12345",))
        self.assertTrue(window.apply_config_button.isEnabled())
        self.assertEqual(read_active_mods(config_path).config.mods, ("Original",))

    def test_mod_pack_does_not_claim_failed_verification_rolled_back_write(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, config_path = self._make_launch_window(
            Path(temporary.name), mods=("Original",)
        )
        self._wait_for_background_workers(window)
        window._staged_mod_ids = ["Unfinished"]
        profile = ModProfile("New Pack", ("PackMod",))

        def failed_reload(*, force: bool) -> None:
            self.assertTrue(force)
            window._active_config = None
            window._staged_mod_ids = []

        with (
            patch(
                "zomboid_mod_manager.ui.window_profiles.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch.object(
                window, "_load_active_configuration_impl", side_effect=failed_reload
            ),
            patch("zomboid_mod_manager.ui.window_configuration.QMessageBox.warning"),
        ):
            window._apply_mod_pack(profile)

        self.assertEqual(read_active_mods(config_path).config.mods, ("PackMod",))
        self.assertIsNone(window._active_config)
        self.assertEqual(window._staged_mod_ids, [])
        self.assertIn("Could not verify", window.configuration_status.text())
        self.assertIn("Reload", window.configuration_status.text())
        window.close()

    def test_clearing_list_selection_disables_staging_actions(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(
            Path(temporary.name), mods=("LegacyWorkshop",)
        )
        self._wait_for_background_workers(window)
        window.active_list.setCurrentRow(0)
        window.active_list.clearSelection()
        self.assertFalse(window.deactivate_button.isEnabled())
        before = list(window._staged_mod_ids)
        window._stage_deactivate()
        self.assertEqual(window._staged_mod_ids, before)

        window.available_list.setCurrentRow(0)
        window.available_list.clearSelection()
        self.assertFalse(window.activate_button.isEnabled())
        window._stage_activate()
        self.assertEqual(window._staged_mod_ids, before)

        window.active_list.setCurrentRow(0)
        window.active_list.item(0).setSelected(True)
        window._stage_deactivate()
        self.assertEqual(window._staged_mod_ids, [])
        self.assertIn("Removed 1 mod", window.configuration_status.text())
        self.assertIn("Choose mods in Available Mods", window.active_list.empty_text)

    def test_compact_workspace_keeps_build_and_apply_labels_readable(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))
        window.resize(980, 680)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.metadata_build_label.text(), "Build:")
        self.assertEqual(window.apply_config_button.text(), "Apply List…")
        self.assertIn(
            "global list", window.apply_config_button.accessibleName().lower()
        )
        window.resize(1280, 760)
        self.app.processEvents()
        self.assertEqual(window.metadata_build_label.text(), "Project Zomboid build:")

    def test_remove_feedback_counts_duplicate_active_rows(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))
        self._wait_for_background_workers(window)
        window._staged_mod_ids = ["Repeated", "Repeated"]
        window._refresh_management_lists()
        window.active_list.item(0).setSelected(True)
        window._stage_deactivate()
        self.assertEqual(window._staged_mod_ids, [])
        self.assertIn("Removed 2 mods", window.configuration_status.text())

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
        self.assertEqual(window.inactive_sort.accessibleName(), "Sort Available Mods")
        self.assertIn("Available Mods", window.inactive_filter.accessibleName())
        self.assertIn("Active Order", window.active_filter.accessibleName())
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
        self.assertEqual(window.select_filtered_button.text(), "Select 1")
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
        actions["Add selected to Active Order"].trigger()
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
        self.assertFalse(warning_item.data(ISSUE_ROLE))
        self.assertNotIn(
            "Build 42 ignores root-level mod files", warning_item.toolTip()
        )
        self.assertIn(
            "Build 42 ignores root-level mod files",
            window.diagnostics.toPlainText(),
        )
        summary_for_target = window.issue_summary.text()

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
        self.assertEqual(window.issue_summary.text(), summary_for_target)
        repeated_description = next(
            window.available_list.item(index)
            for index in range(window.available_list.count())
            if window.available_list.item(index).data(Qt.ItemDataRole.UserRole)
            == "RepeatedDescription"
        )
        self.assertTrue(repeated_description.data(ISSUE_ROLE))
        self.assertIn(
            "Build 42 ignores root-level mod files",
            repeated_description.toolTip(),
        )
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

    def test_declared_game_version_mismatch_is_a_discover_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workshop_root = root / "workshop"
            metadata = (
                workshop_root
                / "888888888"
                / "mods"
                / "VersionBound"
                / "42"
                / "mod.info"
            )
            metadata.parent.mkdir(parents=True)
            metadata.write_text(
                "name=Version Bound\nid=VersionBound\n"
                "versionMin=42.20.0\nversionMax=42.22.0\n",
                encoding="utf-8",
            )
            config_path = root / "Zomboid" / "mods" / "default.txt"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "VERSION = 1,\n\nmods\n{\n}\n\nmaps\n{\n}\n",
                encoding="utf-8",
            )
            window = MainWindow(
                DetectedPaths((), (), (), (workshop_root,), root / "local-mods"),
                active_config_path=config_path,
                profile_store=ProfileStore(root / "profiles"),
            )
            self.addCleanup(window.close)
            self._wait_for_background_workers(window)
            window.metadata_preview_target.setCurrentIndex(
                window.metadata_preview_target.findData("42")
            )
            window.metadata_build_version.setText("42.19.0")

            item = window.available_list.item(0)
            self.assertTrue(item.data(ISSUE_ROLE))
            self.assertIn("Declared minimum game version is 42.20.0", item.toolTip())
            self.assertIn("target is 42.19.0", window.diagnostics.toPlainText())

            window.metadata_build_version.setText("42.21.0")
            self.assertFalse(window.available_list.item(0).data(ISSUE_ROLE))

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

    def test_dependency_diagnostic_names_declaring_mod_and_shows_candidate_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "Zomboid" / "mods" / "default.txt"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "VERSION = 1,\n\nmods\n{\n    mod = Consumer,\n}\n\nmaps\n{\n}\n",
                encoding="utf-8",
            )
            window = MainWindow(
                DetectedPaths(
                    (), (), (), (FIXTURES / "dependencies",), root / "local-mods"
                ),
                active_config_path=config_path,
                profile_store=ProfileStore(root / "profiles"),
            )
            self.addCleanup(window.close)
            self._wait_for_background_workers(window)
            window.metadata_preview_target.setCurrentIndex(
                window.metadata_preview_target.findData("42")
            )
            window.metadata_build_version.setText("42.20.0")

            metadata_path = (
                FIXTURES
                / "dependencies"
                / "555555555"
                / "mods"
                / "Consumer"
                / "42.20"
                / "mod.info"
            )
            lines = window.diagnostics.toPlainText().splitlines()
            missing_index = next(
                index
                for index, line in enumerate(lines)
                if "[missing-dependency]" in line and "MissingMod" in line
            )
            self.assertIn(
                "Mod 'Consumer': Requires 'MissingMod', which was not found in the scanned folders.",
                lines[missing_index],
            )
            self.assertEqual(
                lines[missing_index + 1].strip(), f"Metadata file: {metadata_path}"
            )
            self.assertNotIn("Candidate:", lines[missing_index])

            warning = next(
                warning
                for warning in window._configuration_preflight_warnings()
                if "[missing-dependency]" in warning and "MissingMod" in warning
            )
            self.assertIn("Mod 'Consumer'", warning)
            self.assertEqual(warning.count(str(metadata_path)), 1)

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
        self.assertIn("Active order:", window.issue_summary.text())
        self.assertIn("warnings", window.inactive_heading.text())
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
        self.assertIn("1 error", window.inactive_heading.text())
        window._start_diagnostic("phase-d-test", lambda: "Completed")
        self.assertFalse(window.progress.isHidden())
        deadline = time.monotonic() + 5
        while not window.progress.isHidden() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(window.progress.isHidden())
        self.assertEqual(config_path.read_bytes(), original_bytes)
        window.close()

    def test_finding_counts_use_natural_singular_plural_labels(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window, _config_path = self._make_launch_window(Path(temporary.name))
        window.show()
        deadline = time.monotonic() + 5
        while (
            "scan complete" not in window.status.text().casefold()
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual(window.issue_summary.text(), "Active order: no issues")
        self.assertTrue(window.review_active_order_button.isHidden())
        self.assertGreater(window._library_warning_count, 0)
        self.assertFalse(window.review_library_findings_button.isHidden())
        self.assertEqual(
            window.review_library_findings_button.accessibleName(),
            "Review library findings",
        )
        self.assertTrue(
            window.review_library_findings_button.focusPolicy()
            & Qt.FocusPolicy.TabFocus
        )
        window.manage_search.setFocus()
        QTest.keyClick(
            window.manage_search,
            Qt.Key.Key_Tab,
            Qt.KeyboardModifier.ShiftModifier,
        )
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), window.review_library_findings_button)
        QTest.keyClick(window.review_library_findings_button, Qt.Key.Key_Space)
        self.assertIs(window.main_tabs.currentWidget(), window.library_page)
        self.assertTrue(
            window.diagnostics.textCursor()
            .block()
            .text()
            .startswith(("WARNING:", "ERROR:"))
        )

        first_library_line = window._library_diagnostic_text.splitlines()[0]
        window._show_scan_failure("Scan failed: fixture folder became unavailable.")
        self.assertIn(first_library_line, window.diagnostics.toPlainText())
        self.assertIn(
            "fixture folder became unavailable", window.diagnostics.toPlainText()
        )
        self.assertIn("Previous scan results remain in use", window.status.text())
        window.review_library_findings_button.click()
        self.assertEqual(
            window.diagnostics.textCursor().block().text(), first_library_line
        )

        window._show_result(ScanResult((), (), ()))
        self.assertTrue(window.review_library_findings_button.isHidden())
        window._show_result(
            ScanResult(
                (), (), (Diagnostic("Broken library entry", Path("mod.info"), "error"),)
            )
        )
        self.assertFalse(window.review_library_findings_button.isHidden())
        window.review_library_findings_button.click()
        self.assertEqual(
            window.diagnostics.textCursor().block().text(),
            "ERROR: Broken library entry",
        )

        self.assertIn("appear more than once", window.issue_summary.toolTip())
        window._staged_mod_ids.append("MissingMod")
        window._update_diagnostics()
        self.assertEqual(window.issue_summary.text(), "Active order: 1 issue")
        self.assertFalse(window.review_active_order_button.isHidden())
        self.assertTrue(
            window.review_active_order_button.focusPolicy() & Qt.FocusPolicy.TabFocus
        )
        QTest.keyClick(window.review_active_order_button, Qt.Key.Key_Space)
        self.assertIs(window.main_tabs.currentWidget(), window.library_page)
        self.assertIn(
            "WARNING [missing-active-mod-id]",
            window.diagnostics.textCursor().block().text(),
        )

        dialogs = []

        def cancel_review(dialog) -> int:
            dialogs.append(dialog)
            return QDialog.DialogCode.Rejected

        with (
            patch.object(
                window,
                "_configuration_preflight_warnings",
                return_value=("Missing mod",),
            ),
            patch(
                "zomboid_mod_manager.ui.window_configuration.PreflightReviewDialog.exec",
                cancel_review,
            ),
        ):
            self.assertFalse(window._confirm_configuration_preflight("applying"))
        self.assertIn("1 possible issue", dialogs[-1].findChild(QLabel).text())
        self.assertIn("Missing mod", dialogs[-1].findings.toPlainText())
        self.assertTrue(dialogs[-1].cancel_button.isDefault())
        self.assertEqual(dialogs[-1].continue_button.text(), "Review Changes…")

        warnings = tuple(f"Warning {number}" for number in range(41))
        with (
            patch.object(
                window, "_configuration_preflight_warnings", return_value=warnings
            ),
            patch(
                "zomboid_mod_manager.ui.window_configuration.PreflightReviewDialog.exec",
                cancel_review,
            ),
        ):
            self.assertFalse(window._confirm_configuration_preflight("launching"))
        self.assertIn("41 possible issues", dialogs[-1].findChild(QLabel).text())
        self.assertIn("1. Warning 0", dialogs[-1].findings.toPlainText())
        self.assertIn("41. Warning 40", dialogs[-1].findings.toPlainText())
        self.assertEqual(dialogs[-1].continue_button.text(), "Continue to Launch")

        with (
            patch.object(
                window, "_configuration_preflight_warnings", return_value=warnings
            ),
            patch(
                "zomboid_mod_manager.ui.window_configuration.PreflightReviewDialog.exec",
                return_value=QDialog.DialogCode.Accepted,
            ),
        ):
            self.assertTrue(window._confirm_configuration_preflight("applying"))
        window.close()

    def test_active_order_does_not_look_clear_before_first_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch("zomboid_mod_manager.ui.window_discovery.ScanWorker.start"):
                window, _config_path = self._make_launch_window(Path(temporary))

            self.assertEqual(window.issue_summary.text(), "Active order: checking…")
            window._scan_cancelled()
            self.assertEqual(window.issue_summary.text(), "Active order: not checked")
            self.assertIn("Scan cancelled", window.library_table_empty.text())
            window._show_scan_failure("The scan could not be completed.")
            self.assertEqual(window.issue_summary.text(), "Active order: not checked")
            self.assertIn("Scan failed", window.library_table_empty.text())
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
        previous_summary = window.issue_summary.text()

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
        self.assertEqual(window.issue_summary.text(), previous_summary)
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
        ambiguous_id = ambiguous.data(Qt.ItemDataRole.UserRole)
        window._staged_mod_ids.append(ambiguous_id)
        window._refresh_management_lists()
        active_ambiguous = next(
            window.active_list.item(i)
            for i in range(window.active_list.count())
            if window.active_list.item(i).data(Qt.ItemDataRole.UserRole) == ambiguous_id
        )
        self.assertIn("Multiple entries", active_ambiguous.toolTip())
        self.assertNotIn("not found in", active_ambiguous.toolTip())
        window._staged_mod_ids.remove(ambiguous_id)
        window._refresh_management_lists()

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
        self.assertIn("Open Mod Packs", window.configuration_status.text())
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

        def cancel_confirmation(box):
            next(
                button for button in box.buttons() if button.text() == "Cancel"
            ).click()

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.exec",
                new=cancel_confirmation,
            ),
        ):
            window._apply_active_configuration()
        self.assertEqual(config_path.read_bytes(), original)

        prompts = []

        def accept_confirmation(box):
            prompts.append(box)
            next(
                button for button in box.buttons() if button.text() == "Apply Changes"
            ).click()

        with (
            patch.object(window, "_confirm_configuration_preflight", return_value=True),
            patch(
                "zomboid_mod_manager.ui.window_configuration.QMessageBox.exec",
                new=accept_confirmation,
            ),
        ):
            window._apply_active_configuration()
        self.assertEqual(prompts[0].text(), "Update Project Zomboid's active mod list?")
        self.assertIn("Mods: 1 → 2", prompts[0].informativeText())
        self.assertIn("Maps: unchanged", prompts[0].informativeText())
        self.assertIn("Added: AddedMod", prompts[0].detailedText())
        self.assertIn("Maps: unchanged (1)", prompts[0].detailedText())
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
        self.assertIn("1 Project Zomboid item;", dialog.summary.text())
        self.assertIn("1 item not installed locally;", dialog.summary.text())
        self.assertIn("1 Workshop item unavailable.", dialog.summary.text())
        self.assertNotIn("missing or unavailable", dialog.summary.text())
        self.assertNotIn("1 Project Zomboid items", dialog.summary.text())

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

            self.assertEqual(window.detect_build_button.text(), "Detect Build")
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
                if item.data(Qt.ItemDataRole.UserRole) == "LegacyWorkshop":
                    window.available_list.setCurrentItem(item)
        window._stage_activate()
        self.assertTrue(wanted.issubset(window._staged_mod_ids))
        self.assertEqual(
            window.active_list.currentItem().data(Qt.ItemDataRole.UserRole),
            "LegacyWorkshop",
        )
        self.assertIn("Mod ID: LegacyWorkshop", window.details.toPlainText())

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

    def test_move_buttons_shift_all_selected_active_mods_one_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            window._staged_mod_ids = list("ABCDEF")
            window._refresh_management_lists()
            window.active_list.setCurrentRow(2)
            for row in (1, 2, 4):
                window.active_list.item(row).setSelected(True)
            self.assertEqual(
                {
                    item.data(Qt.ItemDataRole.UserRole)
                    for item in window.active_list.selectedItems()
                },
                {"B", "C", "E"},
            )

            window.move_up_button.click()
            self.assertEqual(window._staged_mod_ids, list("BCAEDF"))
            self.assertEqual(
                {
                    item.data(Qt.ItemDataRole.UserRole)
                    for item in window.active_list.selectedItems()
                },
                {"B", "C", "E"},
            )
            self.assertEqual(
                window.active_list.currentItem().data(Qt.ItemDataRole.UserRole), "C"
            )

            window.move_down_button.click()
            self.assertEqual(window._staged_mod_ids, list("ABCDEF"))
            window.active_list.clearSelection()
            for row in (0, 1):
                window.active_list.item(row).setSelected(True)
            self.assertFalse(window.move_up_button.isEnabled())
            self.assertTrue(window.move_down_button.isEnabled())

    def test_missing_active_mod_clears_previous_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            window._staged_mod_ids.append("MissingMod")
            window._refresh_management_lists()
            local_item = next(
                window.available_list.item(row)
                for row in range(window.available_list.count())
                if window.available_list.item(row).data(Qt.ItemDataRole.UserRole)
                == "LocalShared"
            )
            window.available_list.setCurrentItem(local_item)
            self.assertIsNotNone(window._selected_entry)

            window.active_list.setCurrentRow(0)
            self.assertIn("Mod ID: MissingMod", window.details.toPlainText())
            self.assertIsNone(window._selected_entry)
            self.assertIn(
                "not found in the local or Workshop folders",
                window.description.toPlainText(),
            )
            self.assertIn("Paths & Settings", window.description.toPlainText())
            self.assertFalse(window.open_folder_button.isEnabled())
            self.assertFalse(window.open_workshop_button.isEnabled())
            window.metadata_preview_target.setCurrentIndex(
                window.metadata_preview_target.findData("41")
            )
            self.assertIsNone(window._selected_entry)
            self.assertIn(
                "not found in the local or Workshop folders",
                window.description.toPlainText(),
            )

    def test_removed_discover_mod_clears_details_after_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            local_item = next(
                window.available_list.item(row)
                for row in range(window.available_list.count())
                if window.available_list.item(row).data(Qt.ItemDataRole.UserRole)
                == "LocalShared"
            )
            window.available_list.setCurrentItem(local_item)
            self.assertTrue(window.open_folder_button.isEnabled())
            window.manage_search.setText("no matching mod")
            self.assertTrue(local_item.isHidden())
            self.assertIsNotNone(window._selected_entry)
            window.manage_search.clear()

            result = window._last_result
            window._last_result = ScanResult(
                tuple(
                    entry
                    for entry in result.local_entries
                    if entry.mod_id != "LocalShared"
                ),
                result.workshop_items,
                result.diagnostics,
            )
            window._refresh_management_lists()

            self.assertIsNone(window._selected_entry)
            self.assertFalse(window.open_folder_button.isEnabled())
            self.assertFalse(window.open_workshop_button.isEnabled())
            self.assertIn("no longer", window.details.toPlainText().casefold())
            self.assertIn("No description", window.description.toPlainText())

    def test_library_selection_survives_equivalent_scan_and_clears_when_removed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window, _ = self._make_launch_window(Path(temporary))
            self._wait_for_background_workers(window)
            other_item = next(
                window.available_list.item(row)
                for row in range(window.available_list.count())
                if window.available_list.item(row).data(Qt.ItemDataRole.UserRole)
                == "RepeatedDescription"
            )
            window.available_list.setCurrentItem(other_item)
            window.main_tabs.setCurrentWidget(window.library_page)
            result = window._last_result
            selected_entry = next(
                entry for entry in result.local_entries if entry.mod_id == "LocalShared"
            )
            source_row = next(
                row
                for row in range(window.table_model.rowCount())
                if window.table_model.item(row, 0).data(Qt.ItemDataRole.UserRole)
                == selected_entry.key
            )
            selected_index = window._proxy.mapFromSource(
                window.table_model.index(source_row, 0)
            )
            window.table.setCurrentIndex(selected_index)
            self.assertTrue(window.inspect_library_button.isEnabled())

            window._show_result(result)
            current = window.table.currentIndex()
            self.assertTrue(current.isValid())
            self.assertEqual(
                current.sibling(current.row(), 0).data(Qt.ItemDataRole.UserRole),
                selected_entry.key,
            )
            self.assertIn("Mod ID: LocalShared", window.details.toPlainText())

            window.search.setText("no matching library entry")
            self.assertFalse(window.table.currentIndex().isValid())
            self.assertIn("hidden by search", window.details.toPlainText().casefold())
            window._show_result(result)
            self.assertIn("hidden by search", window.details.toPlainText().casefold())
            window.search.clear()
            current = window.table.currentIndex()
            self.assertTrue(current.isValid())
            self.assertEqual(
                current.sibling(current.row(), 0).data(Qt.ItemDataRole.UserRole),
                selected_entry.key,
            )

            removed_result = ScanResult(
                tuple(
                    entry
                    for entry in result.local_entries
                    if entry.key != selected_entry.key
                ),
                result.workshop_items,
                result.diagnostics,
            )
            window._show_result(removed_result)
            self.assertFalse(window.table.currentIndex().isValid())
            self.assertFalse(window.inspect_library_button.isEnabled())
            self.assertIsNone(window._selected_entry)
            self.assertFalse(window.open_folder_button.isEnabled())
            self.assertIn("no longer", window.details.toPlainText().casefold())

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
