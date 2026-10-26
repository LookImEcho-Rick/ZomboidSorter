"""Main window layout and tab composition."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager import __version__
from zomboid_mod_manager.discovery.game_build import (
    detect_game_build,
    format_game_build_detection,
)
from zomboid_mod_manager.ui.workshop_browser import WorkshopBrowserPanel

from .window_widgets import ImagePreviewOverlay, PreviewLabel
from .window_workshop_layout import WorkshopCollectionLayoutMixin
from .window_workspace_layout import WorkspaceLayoutMixin


class WindowLayoutMixin(WorkspaceLayoutMixin, WorkshopCollectionLayoutMixin):
    def _build_application_ui(
        self, active_config_path: Path | None, use_saved_paths: bool
    ) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        self.preview_overlay = ImagePreviewOverlay(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        self.setup_page = QWidget()
        setup_page_layout = QVBoxLayout(self.setup_page)
        setup_page_layout.setContentsMargins(0, 0, 0, 0)
        setup_scroll = QScrollArea()
        setup_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        setup_scroll.setWidgetResizable(True)
        setup_page_layout.addWidget(setup_scroll)
        setup_content = QWidget()
        setup_scroll.setWidget(setup_content)
        self.setup_layout = QVBoxLayout(setup_content)
        self.setup_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.setup_layout.setContentsMargins(24, 20, 24, 20)
        self.setup_layout.setSpacing(14)
        setup_heading = QLabel("Paths & Settings")
        setup_heading.setObjectName("pageHeading")
        self.setup_layout.addWidget(setup_heading)
        setup_intro = QLabel(
            "Review the folders used for read-only scans. Changes to these paths take effect on the next refresh."
        )
        setup_intro.setObjectName("secondaryText")
        setup_intro.setWordWrap(True)
        self.setup_layout.addWidget(setup_intro)
        scan_heading_row = QHBoxLayout()
        scan_heading = QLabel("SCAN LOCATIONS")
        scan_heading.setObjectName("sectionKicker")
        scan_heading_row.addWidget(scan_heading)
        scan_heading_row.addStretch(1)
        self.detect_all_paths_button = QPushButton("Detect All")
        self.detect_all_paths_button.setAccessibleName("Auto-detect all scan paths")
        self.detect_all_paths_button.setToolTip(
            "Refresh discovery and update all game, local mods, and Workshop paths."
        )
        self.detect_all_paths_button.clicked.connect(self._auto_detect_all_paths)
        scan_heading_row.addWidget(self.detect_all_paths_button)
        self.detect_all_trailing_spacer = QWidget()
        scan_heading_row.addWidget(self.detect_all_trailing_spacer)
        self.setup_layout.addLayout(scan_heading_row)

        paths_form = QFormLayout()
        paths_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.settings_paths_form = paths_form
        self._settings_browse_buttons: list[QPushButton] = []
        self._settings_secondary_buttons: list[QPushButton] = [
            self.detect_all_paths_button
        ]
        self._settings_trailing_buttons: list[QPushButton] = []
        self._settings_path_health_indicators: list[QLabel] = []
        default_game_path = (
            str(self._detected.game_installations[0])
            if self._detected.game_installations
            else ""
        )
        saved_game_path = (
            self._settings.value("paths/game", default_game_path)
            if use_saved_paths
            else default_game_path
        )
        self.game_path = QLineEdit(str(saved_game_path))
        self.game_path.setAccessibleName("Project Zomboid game folder")
        self.game_path.setPlaceholderText(
            "Optional: select ProjectZomboid install folder"
        )
        self._game_build_detection = detect_game_build(str(saved_game_path))
        game_row = QHBoxLayout()
        game_row.addWidget(self.game_path)
        game_browse = QPushButton("Browse…")
        game_browse.clicked.connect(lambda: self._browse_into(self.game_path))
        self._settings_browse_buttons.append(game_browse)
        game_row.addWidget(game_browse)
        self.game_path_detect_button = QPushButton("Auto Detect")
        self._settings_secondary_buttons.append(self.game_path_detect_button)
        self.game_path_detect_button.setAccessibleName("Auto-detect game folder")
        self.game_path_detect_button.setToolTip(
            "Find the Project Zomboid installation in the detected Steam libraries."
        )
        self.game_path_detect_button.clicked.connect(self._auto_detect_game_path)
        game_row.addWidget(self.game_path_detect_button)
        self.game_path_health = QLabel("·")
        self.game_path_health.setObjectName("pathHealth")
        self.game_path_health.setAccessibleName("Game folder path health")
        self.game_path_health.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.game_path_health.setFixedWidth(20)
        self._settings_path_health_indicators.append(self.game_path_health)
        game_row.addWidget(self.game_path_health)
        paths_form.addRow("Game folder", game_row)

        saved_local_path = (
            self._settings.value("paths/local", self._detected.local_mod_root)
            if use_saved_paths
            else self._detected.local_mod_root
        )
        self.local_path = QLineEdit(str(saved_local_path))
        self.local_path.setAccessibleName("Project Zomboid local mods folder")
        local_row = QHBoxLayout()
        local_row.addWidget(self.local_path)
        local_browse = QPushButton("Browse…")
        local_browse.clicked.connect(lambda: self._browse_into(self.local_path))
        self._settings_browse_buttons.append(local_browse)
        local_row.addWidget(local_browse)
        self.local_path_detect_button = QPushButton("Auto Detect")
        self._settings_secondary_buttons.append(self.local_path_detect_button)
        self.local_path_detect_button.setAccessibleName("Auto-detect local mods folder")
        self.local_path_detect_button.setToolTip(
            "Reset to the standard Project Zomboid local mods folder."
        )
        self.local_path_detect_button.clicked.connect(self._auto_detect_local_path)
        local_row.addWidget(self.local_path_detect_button)
        self.local_path_health = QLabel("·")
        self.local_path_health.setObjectName("pathHealth")
        self.local_path_health.setAccessibleName("Local mods path health")
        self.local_path_health.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.local_path_health.setFixedWidth(20)
        self._settings_path_health_indicators.append(self.local_path_health)
        local_row.addWidget(self.local_path_health)
        paths_form.addRow("Local mods", local_row)

        default_workshop_paths = ";".join(map(str, self._detected.workshop_roots))
        saved_workshop_paths = (
            self._settings.value("paths/workshop", default_workshop_paths)
            if use_saved_paths
            else default_workshop_paths
        )
        self.workshop_paths = QLineEdit(str(saved_workshop_paths))
        self.workshop_paths.setAccessibleName(
            "Project Zomboid Workshop content folders"
        )
        self.workshop_paths.setPlaceholderText(
            "One or more Workshop content folders, separated by semicolons"
        )
        workshop_row = QHBoxLayout()
        workshop_row.addWidget(self.workshop_paths)
        workshop_browse = QPushButton("Add Folder…")
        workshop_browse.clicked.connect(self._add_workshop_folder)
        self._settings_browse_buttons.append(workshop_browse)
        workshop_row.addWidget(workshop_browse)
        self.workshop_paths_detect_button = QPushButton("Auto Detect")
        self._settings_secondary_buttons.append(self.workshop_paths_detect_button)
        self.workshop_paths_detect_button.setAccessibleName(
            "Auto-detect Workshop content folders"
        )
        self.workshop_paths_detect_button.setToolTip(
            "Find Project Zomboid Workshop folders in the detected Steam libraries."
        )
        self.workshop_paths_detect_button.clicked.connect(
            self._auto_detect_workshop_paths
        )
        workshop_row.addWidget(self.workshop_paths_detect_button)
        self.workshop_paths_health = QLabel("·")
        self.workshop_paths_health.setObjectName("pathHealth")
        self.workshop_paths_health.setAccessibleName("Workshop paths health")
        self.workshop_paths_health.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.workshop_paths_health.setFixedWidth(20)
        self._settings_path_health_indicators.append(self.workshop_paths_health)
        workshop_row.addWidget(self.workshop_paths_health)
        paths_form.addRow("Workshop content", workshop_row)
        self.setup_layout.addLayout(paths_form)

        self._path_health_timer = QTimer(self)
        self._path_health_timer.setSingleShot(True)
        self._path_health_timer.setInterval(250)
        self._path_health_timer.timeout.connect(self._update_path_health)
        for path_field in (self.game_path, self.local_path, self.workshop_paths):
            path_field.textChanged.connect(self._schedule_path_health_update)
        self._update_path_health()

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search mod name, Mod ID, Workshop ID, source, or folder name"
        )
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search discovered mods")
        controls.addWidget(self.search, 1)
        self.inspect_library_button = QPushButton("Inspect Selected")
        self.inspect_library_button.setToolTip(
            "Show the selected entry's preview and metadata in Mod Workspace."
        )
        self.inspect_library_button.setEnabled(False)
        self.inspect_library_button.clicked.connect(self._open_library_entry)
        controls.addWidget(self.inspect_library_button)
        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        library_layout.setContentsMargins(12, 12, 12, 10)
        library_layout.setSpacing(10)
        library_heading = QLabel("LIBRARY & DIAGNOSTICS")
        library_heading.setObjectName("sectionKicker")
        library_layout.addWidget(library_heading)
        library_intro = QLabel(
            "Inspect every discovered entry. File overlaps and console logs are analyzed only when you request them."
        )
        library_intro.setObjectName("secondaryText")
        library_intro.setWordWrap(True)
        library_layout.addWidget(library_intro)
        library_layout.addLayout(controls)

        self.table_model = QStandardItemModel(0, 7, self)
        self.table_model.setHorizontalHeaderLabels(
            [
                "Name",
                "Mod ID",
                "Workshop ID",
                "Source",
                "Metadata",
                "Files",
                "Installed folder",
            ]
        )
        self.table_model.horizontalHeaderItem(2).setToolTip(
            "Steam Workshop item ID. One Workshop item can contain several Mod IDs."
        )
        self.table_model.horizontalHeaderItem(4).setToolTip(
            "The metadata layout used to describe this mod; it does not prove compatibility."
        )
        self.table_model.horizontalHeaderItem(5).setToolTip(
            "Number of mod.info metadata files found for this installed mod entry."
        )
        self.table_model.horizontalHeaderItem(6).setToolTip(
            "The folder containing this mod. The app reads these files but does not change them."
        )
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self.table_model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self._proxy.setFilterFixedString)
        self.search.textChanged.connect(self._restore_library_selection)
        self.search.textChanged.connect(self._update_library_table_state)

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Discovered mods and Workshop items")
        self.table.selectionModel().currentRowChanged.connect(self._show_selected_entry)
        self.table.doubleClicked.connect(self._open_library_entry)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((135, 95, 105, 60, 110, 50)):
            self.table.setColumnWidth(column, width)
        self.library_table_empty = QLabel("Scanning local and Workshop folders…")
        self.library_table_empty.setObjectName("secondaryText")
        self.library_table_empty.setAccessibleName("Library results")
        self.library_table_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.library_table_empty.setWordWrap(True)
        self.library_table_stack = QStackedWidget()
        self.library_table_stack.addWidget(self.table)
        self.library_table_stack.addWidget(self.library_table_empty)
        self.library_table_stack.setCurrentWidget(self.library_table_empty)

        details_page = QWidget()
        details_layout = QVBoxLayout(details_page)
        details_layout.setContentsMargins(6, 6, 6, 6)
        details_layout.setSpacing(4)
        self.preview = PreviewLabel()
        self.preview.show_placeholder("PROJECT ZOMBOID\nMOD DETAILS")
        self.preview.setObjectName("modPreview")
        self.preview.setAccessibleName("Selected mod preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(72)
        self.preview.setMaximumHeight(180)
        self.preview.clicked.connect(self._show_enlarged_preview)
        details_layout.addWidget(self.preview)
        self.preview_caption = QLabel("Select a mod to preview its artwork.")
        self.preview_caption.setWordWrap(True)
        details_layout.addWidget(self.preview_caption)
        self._metadata_target_controls = QWidget(details_page)
        metadata_target_layout = QVBoxLayout(self._metadata_target_controls)
        metadata_target_layout.setContentsMargins(0, 0, 0, 0)
        target_row = QHBoxLayout()
        self.metadata_build_label = QLabel("Project Zomboid build:")
        target_row.addWidget(self.metadata_build_label)
        self.metadata_preview_target = QComboBox()
        self.metadata_preview_target.addItem("All candidates", "all")
        self.metadata_preview_target.addItem("Build 41", "41")
        self.metadata_preview_target.addItem("Build 42", "42")
        if use_saved_paths and self._settings.contains("metadata/target"):
            saved_metadata_target = str(self._settings.value("metadata/target"))
        else:
            saved_metadata_target = self._game_build_detection.major_build or "all"
        saved_target_index = self.metadata_preview_target.findData(
            saved_metadata_target
        )
        if saved_target_index >= 0:
            self.metadata_preview_target.setCurrentIndex(saved_target_index)
        self.metadata_preview_target.setAccessibleName(
            "Project Zomboid build for mod details"
        )
        self.metadata_preview_target.setToolTip(
            "Build 41 uses root metadata. Build 42 ignores root-level Build 41 mod files; "
            "those entries need common metadata or a compatible version folder. "
            "Enter the exact game version to select the newest compatible version folder. "
            "This selects metadata only; it does not verify mod content compatibility."
        )
        self.metadata_preview_target.currentIndexChanged.connect(
            self._metadata_preview_target_changed
        )
        target_row.addWidget(self.metadata_preview_target, 1)
        if use_saved_paths and self._settings.contains("metadata/build_version"):
            saved_metadata_build = self._settings.value("metadata/build_version", "")
        else:
            saved_metadata_build = self._game_build_detection.exact_version or ""
        self.metadata_build_version = QLineEdit(str(saved_metadata_build))
        self.metadata_build_version.setAccessibleName("Exact Build 42 game version")
        self.metadata_build_version.setPlaceholderText("e.g. 42.21.0")
        self.metadata_build_version.setMaxLength(32)
        self.metadata_build_version.setMaximumWidth(120)
        self.metadata_build_version.setToolTip(
            "Enter the exact Project Zomboid version shown in the game's main menu, such as 42.21.0."
        )
        self.metadata_build_version.textChanged.connect(
            self._metadata_preview_target_changed
        )
        self.metadata_build_version.setVisible(
            self.metadata_preview_target.currentData() == "42"
        )
        target_row.addWidget(self.metadata_build_version)
        self.detect_build_button = QPushButton("Detect Build")
        self.detect_build_button.setAccessibleName(
            "Detect the installed Project Zomboid build"
        )
        self.detect_build_button.setToolTip(
            "Detect the installed build family and use a current exact version when Steam's install record supports it. "
            "You can edit the version field at any time."
        )
        self.detect_build_button.clicked.connect(self._use_detected_game_build)
        target_row.addWidget(self.detect_build_button)
        metadata_target_layout.addLayout(target_row)
        self.game_build_status = QLabel(
            format_game_build_detection(self._game_build_detection)
        )
        self.game_build_status.setObjectName("secondaryText")
        self.game_build_status.setWordWrap(True)
        self.game_build_status.setAccessibleName("Detected game build evidence")
        metadata_target_layout.addWidget(self.game_build_status)
        # Keep the persisted target and detection behavior for metadata consumers,
        # but remove this redundant control block from the visible Details pane.
        self._metadata_target_controls.hide()
        description_panel = QWidget()
        description_layout = QVBoxLayout(description_panel)
        description_layout.setContentsMargins(0, 0, 0, 0)
        description_layout.setSpacing(3)
        self.description_source = QLabel()
        self.description_source.setObjectName("secondaryText")
        self.description_source.setWordWrap(True)
        self.description_source.setTextFormat(Qt.TextFormat.PlainText)
        self.description_source.setAccessibleName("Description source")
        description_layout.addWidget(self.description_source)
        self.description = QTextBrowser()
        self.description.setObjectName("modDescription")
        self.description.setAccessibleName("Selected mod description")
        self.description.setMinimumHeight(0)
        self.description.setOpenLinks(False)
        self.description.setOpenExternalLinks(False)
        self.description.setHtml(
            '<p style="margin:4px 0; color:#9cadbd; font-style:italic;">'
            "Select a mod in Available Mods or Active Order to read its description. "
            "The Metadata tab shows its IDs and declared requirements.</p>"
        )
        description_layout.addWidget(self.description, 1)
        metadata_panel = QWidget()
        metadata_layout = QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected mod details")
        self.details.setMinimumHeight(0)
        metadata_layout.addWidget(self.details, 1)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setDocumentMode(True)
        self.detail_tabs.addTab(description_panel, "Description")
        self.detail_tabs.addTab(metadata_panel, "Metadata")
        details_layout.addWidget(self.detail_tabs, 1)
        details_actions = QHBoxLayout()
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        details_actions.addWidget(self.open_folder_button)
        self.open_workshop_button = QPushButton("Open Workshop Page")
        self.open_workshop_button.setEnabled(False)
        self.open_workshop_button.clicked.connect(self._open_selected_workshop_page)
        details_actions.addWidget(self.open_workshop_button)
        details_layout.addLayout(details_actions)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setPlaceholderText(
            "Choose an analysis above to see evidence-based findings here."
        )
        diagnostic_page = QWidget()
        diagnostic_page.setObjectName("workspacePanel")
        diagnostic_layout = QVBoxLayout(diagnostic_page)
        diagnostic_layout.setContentsMargins(12, 12, 12, 12)
        diagnostic_layout.setSpacing(8)
        diagnostics_heading = QLabel("ON-DEMAND CHECKS")
        diagnostics_heading.setObjectName("panelHeading")
        diagnostic_layout.addWidget(diagnostics_heading)
        diagnostic_actions = QHBoxLayout()
        self.file_overlap_button = QPushButton("Analyze File Overlaps…")
        self.file_overlap_button.clicked.connect(self._analyze_file_overlaps)
        diagnostic_actions.addWidget(self.file_overlap_button)
        self.file_overlap_active_only = QCheckBox("Staged active mods only")
        self.file_overlap_active_only.setChecked(True)
        self.file_overlap_active_only.setAccessibleName(
            "Limit file overlap analysis to staged active mods"
        )
        self.file_overlap_active_only.setToolTip(
            "Compare only Mod IDs in the staged active order. Clear this to include all discovered mods. "
            "The selected metadata target controls which candidates are analyzed."
        )
        self.console_log_button = QPushButton("Analyze Console Log…")
        self.console_log_button.clicked.connect(self._analyze_console_log)
        diagnostic_actions.addWidget(self.console_log_button)
        diagnostic_actions.addStretch(1)
        diagnostic_layout.addLayout(diagnostic_actions)
        diagnostic_layout.addWidget(self.file_overlap_active_only)
        diagnostic_layout.addWidget(self.diagnostics, 1)
        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.addWidget(self.library_table_stack)
        library_split.addWidget(diagnostic_page)
        library_split.setStretchFactor(0, 3)
        library_split.setStretchFactor(1, 2)
        library_layout.addWidget(library_split, 1)

        self.main_tabs = QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.workspace_page = self._build_management_tab(
            active_config_path, details_page
        )
        self.main_tabs.addTab(self.workspace_page, "Mod Workspace")
        self.workshop_page = WorkshopBrowserPanel()
        self.main_tabs.addTab(self.workshop_page, "Steam Workshop")
        self.import_collection_page = self._build_import_collection_tab()
        self.main_tabs.addTab(self.import_collection_page, "Import Collection")
        self.setup_layout.addStretch(1)
        self.main_tabs.addTab(self.setup_page, "Paths && Settings")
        self.library_page = library_page
        self.library_tab_index = self.main_tabs.addTab(
            self.library_page, "Library && Diagnostics"
        )
        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(2)
        title = QLabel(f"ZOMBOID  /  MOD CONTROL  ·  v{__version__}")
        title.setObjectName("appTitle")
        identity.addWidget(title)
        subtitle = QLabel("Your mod library, load order, and game targets in one place")
        subtitle.setObjectName("secondaryText")
        identity.addWidget(subtitle)
        header.addLayout(identity, 1)
        self.update_button = QPushButton("Check for Updates")
        self.update_button.setToolTip(
            f"Check GitHub for a newer ZomboidSorter release (current: {__version__})."
        )
        self.update_button.clicked.connect(self._check_for_updates)
        header.addWidget(self.update_button)
        layout.addLayout(header)
        help_menu = self.menuBar().addMenu("&Help")
        self.support_report_action = QAction("Save Support Report…", self)
        self.support_report_action.setStatusTip(
            "Preview and save a report with private paths and mod identifiers omitted."
        )
        self.support_report_action.triggered.connect(self._open_support_report)
        help_menu.addAction(self.support_report_action)
        self.main_tabs.currentChanged.connect(self._on_main_tab_changed)
        layout.addWidget(self.main_tabs, 1)

        self.status = QLabel("Ready · scans only read installed mod folders")
        self.statusBar().addWidget(self.status, 1)
        self.cancel_scan_button = QPushButton("Cancel scan")
        self.cancel_scan_button.setAccessibleName("Cancel mod scan")
        self.cancel_scan_button.setToolTip("Stop scanning the selected mod folders.")
        self.cancel_scan_button.clicked.connect(self._cancel_scan)
        self.statusBar().addPermanentWidget(self.cancel_scan_button)
        self.cancel_scan_button.hide()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(110)
        self.statusBar().addPermanentWidget(self.progress)
        self.progress.hide()
        self._apply_theme()
        self._update_compact_workspace()

        if self._detected.diagnostics:
            self.diagnostics.setPlainText("\n".join(self._detected.diagnostics))
        self._load_active_configuration()
        self._start_scan()

    def _on_main_tab_changed(self, index: int) -> None:
        page = self.main_tabs.widget(index)
        self.workshop_page.set_tab_active(page is self.workshop_page)
        if page is self.workshop_page:
            # Let Qt show the tab while ensuring the browser exists when needed.
            QTimer.singleShot(0, self._open_workshop_tab_if_selected)
            return
        if page is not self.workspace_page:
            return
        local_roots, workshop_roots = self._selected_roots()
        scan_key = self._scan_key(local_roots, workshop_roots)
        if self._worker is not None and self._worker.isRunning():
            self._scan_again_after_current = scan_key != self._active_scan_key
            return
        self._start_scan()

    def _open_workshop_tab_if_selected(self) -> None:
        if self.main_tabs.currentWidget() is self.workshop_page:
            self.workshop_page.open_home_if_needed()
