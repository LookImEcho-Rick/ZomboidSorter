"""Compose the ZomboidSorter main window from focused UI modules."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QSettings,
    QThread,
    QTimer,
)
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMainWindow

from zomboid_mod_manager import __version__
from zomboid_mod_manager.discovery.paths import detect_paths
from zomboid_mod_manager.domain import (
    DetectedPaths,
    ModEntry,
    ScanResult,
)
from zomboid_mod_manager.gameio.active_mods import ActiveModSnapshot
from zomboid_mod_manager.portable import portable_settings_path
from zomboid_mod_manager.profiles import ProfileStore
from zomboid_mod_manager.sorting.user_rules import parse_user_order_rules
from zomboid_mod_manager.ui.mod_details import PreviewChoice

from .window_configuration import ActiveConfigurationMixin
from .window_details import DetailsMixin
from .window_diagnostics import DiagnosticsMixin
from .window_discovery import DiscoveryMixin
from .window_layout import WindowLayoutMixin
from .window_library import LibraryMixin
from .window_lifecycle import WindowLifecycleMixin
from .window_profiles import ProfileActionsMixin
from .window_staging import StagingMixin
from .window_support import SupportActionsMixin
from .window_updates import UpdateActionsMixin
from .window_workers import (
    DiagnosticWorker,
    PreviewWorker,
    ScanWorker,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    WorkshopDescriptionWorker,
)


class MainWindow(
    WindowLayoutMixin,
    ProfileActionsMixin,
    LibraryMixin,
    StagingMixin,
    ActiveConfigurationMixin,
    DiscoveryMixin,
    DiagnosticsMixin,
    DetailsMixin,
    SupportActionsMixin,
    UpdateActionsMixin,
    WindowLifecycleMixin,
    QMainWindow,
):
    def __init__(
        self,
        detected: DetectedPaths | None = None,
        active_config_path: Path | None = None,
        profile_store: ProfileStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"ZomboidSorter v{__version__}")
        self.resize(1440, 850)
        self.setMinimumSize(980, 680)
        portable_settings = portable_settings_path()
        if portable_settings is None:
            self._settings = QSettings("ZomboidSorter", "ProjectZomboidModManager")
        else:
            portable_settings.parent.mkdir(parents=True, exist_ok=True)
            self._settings = QSettings(
                str(portable_settings), QSettings.Format.IniFormat
            )
        try:
            self._user_order_rules = parse_user_order_rules(
                self._settings.value("sorting/user_rules", "[]")
            )
            self._user_rule_settings_error: str | None = None
        except (TypeError, ValueError) as exc:
            self._user_order_rules = ()
            self._user_rule_settings_error = str(exc)
        saved_geometry = self._settings.value("window/geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        use_saved_paths = detected is None
        self._persist_settings = use_saved_paths
        self._detected = detected or detect_paths()
        self._worker: ScanWorker | None = None
        self._scan_again_after_current = False
        self._scan_result_received = False
        self._last_scan_key: tuple[tuple[str, str], ...] | None = None
        self._last_scan_at = 0.0
        self._last_scan_duration = 0.0
        self._last_scan_label = ""
        self._active_scan_key: tuple[tuple[str, str], ...] | None = None
        self._active_scan_started_at = 0.0
        self._shutdown_requested = False
        self._shutdown_workers: tuple[QThread, ...] = ()
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setSingleShot(True)
        self._shutdown_timer.timeout.connect(self._continue_shutdown)
        self._entries: dict[str, ModEntry] = {}
        self._last_result: ScanResult | None = None
        self._recently_added_workshop_entry_keys: set[str] = set()
        self._recently_added_workshop_item_count = 0
        self._active_config: ActiveModSnapshot | None = None
        self._staged_mod_ids: list[str] = []
        self._profile_workshop_ids: tuple[str, ...] = ()
        self._profile_store = profile_store or ProfileStore()
        self._diagnostic_worker: DiagnosticWorker | None = None
        self._extra_diagnostics: dict[str, str] = {}
        self._issue_error_count = 0
        self._preview_worker: PreviewWorker | None = None
        self._preview_pending: tuple[tuple[PreviewChoice, ...], int] | None = None
        self._preview_choices: tuple[PreviewChoice, ...] = ()
        self._preview_generation = 0
        self._preview_cache: OrderedDict[str, QImage] = OrderedDict()
        self._selected_entry: ModEntry | None = None
        self._last_management_mod_id: str | None = None
        self._workshop_description_worker: WorkshopDescriptionWorker | None = None
        self._workshop_description_pending: str | None = None
        self._workshop_description_requested_id: str | None = None
        self._workshop_description_cache: OrderedDict[str, tuple[str, str]] = (
            OrderedDict()
        )
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_download_worker: UpdateDownloadWorker | None = None
        self._build_application_ui(active_config_path, use_saved_paths)
