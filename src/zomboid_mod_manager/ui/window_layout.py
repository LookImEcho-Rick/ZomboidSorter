"""Main window layout and tab composition."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyle,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager import __version__
from zomboid_mod_manager.ui.workshop_browser import WorkshopBrowserPanel

from .window_widgets import (
    ImagePreviewOverlay,
    OrderedModListWidget,
    PreviewLabel,
    StagingModListWidget,
)


class WindowLayoutMixin:
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
        self.setup_layout = QVBoxLayout(self.setup_page)

        paths_form = QFormLayout()
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
        self.game_path.setPlaceholderText(
            "Optional: select ProjectZomboid install folder"
        )
        game_row = QHBoxLayout()
        game_row.addWidget(self.game_path)
        game_browse = QPushButton("Browse…")
        game_browse.clicked.connect(lambda: self._browse_into(self.game_path))
        game_row.addWidget(game_browse)
        paths_form.addRow("Game folder", game_row)

        saved_local_path = (
            self._settings.value("paths/local", self._detected.local_mod_root)
            if use_saved_paths
            else self._detected.local_mod_root
        )
        self.local_path = QLineEdit(str(saved_local_path))
        local_row = QHBoxLayout()
        local_row.addWidget(self.local_path)
        local_browse = QPushButton("Browse…")
        local_browse.clicked.connect(lambda: self._browse_into(self.local_path))
        local_row.addWidget(local_browse)
        paths_form.addRow("Local mods", local_row)

        default_workshop_paths = ";".join(map(str, self._detected.workshop_roots))
        saved_workshop_paths = (
            self._settings.value("paths/workshop", default_workshop_paths)
            if use_saved_paths
            else default_workshop_paths
        )
        self.workshop_paths = QLineEdit(str(saved_workshop_paths))
        self.workshop_paths.setPlaceholderText(
            "One or more Workshop content folders, separated by semicolons"
        )
        workshop_row = QHBoxLayout()
        workshop_row.addWidget(self.workshop_paths)
        workshop_browse = QPushButton("Add Folder…")
        workshop_browse.clicked.connect(self._add_workshop_folder)
        workshop_row.addWidget(workshop_browse)
        paths_form.addRow("Workshop content", workshop_row)
        self.setup_layout.addLayout(paths_form)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Filter by name, Mod ID, Workshop ID, source, or path"
        )
        controls.addWidget(self.search, 1)
        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        library_layout.addLayout(controls)

        self.table_model = QStandardItemModel(0, 7, self)
        self.table_model.setHorizontalHeaderLabels(
            [
                "Name",
                "Mod ID",
                "Workshop ID",
                "Source",
                "Metadata",
                "Candidates",
                "Entry path",
            ]
        )
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self.table_model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self._proxy.setFilterFixedString)

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.selectionModel().currentRowChanged.connect(self._show_selected_entry)
        self.table.horizontalHeader().setStretchLastSection(True)

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
        self.preview_caption = QLabel("Select a mod to view its declared poster.")
        self.preview_caption.setWordWrap(True)
        details_layout.addWidget(self.preview_caption)
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target metadata:"))
        self.metadata_preview_target = QComboBox()
        self.metadata_preview_target.addItem("All candidates", "all")
        self.metadata_preview_target.addItem("Build 41", "41")
        self.metadata_preview_target.addItem("Build 42", "42")
        saved_metadata_target = (
            str(self._settings.value("metadata/target", "all"))
            if use_saved_paths
            else "all"
        )
        saved_target_index = self.metadata_preview_target.findData(
            saved_metadata_target
        )
        if saved_target_index >= 0:
            self.metadata_preview_target.setCurrentIndex(saved_target_index)
        self.metadata_preview_target.setAccessibleName("Metadata target build")
        self.metadata_preview_target.setToolTip(
            "Build 41 uses root metadata. For Build 42, enter the exact game version to select the newest compatible version folder. "
            "This selects metadata only; it does not verify mod content compatibility."
        )
        self.metadata_preview_target.currentIndexChanged.connect(
            self._metadata_preview_target_changed
        )
        target_row.addWidget(self.metadata_preview_target, 1)
        saved_metadata_build = (
            self._settings.value("metadata/build_version", "")
            if use_saved_paths
            else ""
        )
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
        details_layout.addLayout(target_row)
        description_panel = QWidget()
        description_layout = QVBoxLayout(description_panel)
        description_layout.setContentsMargins(0, 0, 0, 0)
        description_layout.setSpacing(3)
        self.description_heading = QLabel("Description")
        self.description_heading.setObjectName("panelHeading")
        description_layout.addWidget(self.description_heading)
        self.description_source = QLabel("Select a mod to view its description.")
        self.description_source.setObjectName("secondaryText")
        self.description_source.setWordWrap(True)
        self.description_source.setTextFormat(Qt.TextFormat.PlainText)
        description_layout.addWidget(self.description_source)
        self.description = QTextBrowser()
        self.description.setObjectName("modDescription")
        self.description.setAccessibleName("Selected mod description")
        self.description.setMinimumHeight(75)
        self.description.setOpenLinks(False)
        self.description.setOpenExternalLinks(False)
        self.description.setHtml(
            '<p style="margin:4px 0; color:#9cadbd; font-style:italic;">'
            "Select a mod to read its description.</p>"
        )
        description_layout.addWidget(self.description, 1)
        metadata_panel = QWidget()
        metadata_layout = QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(3)
        self.metadata_heading = QLabel("Metadata")
        self.metadata_heading.setObjectName("panelHeading")
        metadata_layout.addWidget(self.metadata_heading)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected mod details")
        self.details.setMinimumHeight(75)
        metadata_layout.addWidget(self.details, 1)
        self.detail_panels_splitter = QSplitter(Qt.Orientation.Vertical)
        self.detail_panels_splitter.setChildrenCollapsible(False)
        self.detail_panels_splitter.setHandleWidth(5)
        self.detail_panels_splitter.addWidget(description_panel)
        self.detail_panels_splitter.addWidget(metadata_panel)
        self.detail_panels_splitter.setStretchFactor(0, 2)
        self.detail_panels_splitter.setStretchFactor(1, 1)
        self.detail_panels_splitter.setSizes([280, 190])
        details_layout.addWidget(self.detail_panels_splitter, 1)
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
        diagnostic_page = QWidget()
        diagnostic_layout = QVBoxLayout(diagnostic_page)
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
        diagnostic_actions.addWidget(self.file_overlap_active_only)
        self.console_log_button = QPushButton("Analyze Console Log…")
        self.console_log_button.clicked.connect(self._analyze_console_log)
        diagnostic_actions.addWidget(self.console_log_button)
        diagnostic_actions.addStretch(1)
        diagnostic_layout.addLayout(diagnostic_actions)
        diagnostic_layout.addWidget(self.diagnostics, 1)
        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.addWidget(self.table)
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
        self.main_tabs.addTab(self.setup_page, "Paths & Settings")
        self.library_page = library_page
        self.library_tab_index = self.main_tabs.addTab(
            self.library_page, "Library & Diagnostics"
        )
        self.main_tabs.setTabVisible(self.library_tab_index, False)
        self.advanced_preview_checkbox = QCheckBox("Advanced Preview")
        self.advanced_preview_checkbox.setObjectName("advancedPreviewToggle")
        self.advanced_preview_checkbox.setAccessibleName(
            "Show Library and diagnostics tab"
        )
        self.advanced_preview_checkbox.setToolTip(
            "Show the library table and optional file/log diagnostics."
        )
        self.advanced_preview_checkbox.toggled.connect(
            self._set_advanced_preview_visible
        )
        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(0)
        title = QLabel(f"ZOMBOID  /  MOD CONTROL  ·  v{__version__}")
        title.setObjectName("appTitle")
        identity.addWidget(title)
        subtitle = QLabel("Build your global load order, then apply it when ready")
        subtitle.setObjectName("secondaryText")
        identity.addWidget(subtitle)
        header.addLayout(identity, 1)
        self.update_button = QPushButton("Check for Updates")
        self.update_button.setToolTip(
            f"Check GitHub for a newer ZomboidSorter release (current: {__version__})."
        )
        self.update_button.clicked.connect(self._check_for_updates)
        header.addWidget(self.update_button)
        header.addWidget(self.advanced_preview_checkbox)
        layout.addLayout(header)
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

        if self._detected.diagnostics:
            self.diagnostics.setPlainText("\n".join(self._detected.diagnostics))
        self._load_active_configuration()
        self._start_scan()

    def _build_management_tab(
        self, active_config_path: Path | None, details_page: QWidget
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        target_row = QHBoxLayout()
        default_path = active_config_path or (
            Path.home() / "Zomboid" / "mods" / "default.txt"
        )
        saved_config_path = (
            self._settings.value("paths/active_config", default_path)
            if active_config_path is None
            else default_path
        )
        self.active_config_path = QLineEdit(str(saved_config_path))
        self.active_config_path.textChanged.connect(self._configuration_path_changed)
        target_row.addWidget(self.active_config_path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_active_config)
        target_row.addWidget(browse)
        self.load_config_button = QPushButton("Load")
        self.load_config_button.clicked.connect(
            lambda: self._load_active_configuration()
        )
        target_row.addWidget(self.load_config_button)
        self.restore_config_button = QPushButton("Restore Backup…")
        self.restore_config_button.setToolTip(
            "Preview and restore a timestamped backup of the global mod list."
        )
        self.restore_config_button.clicked.connect(
            self._restore_active_configuration_backup
        )
        target_row.addWidget(self.restore_config_button)
        self.setup_layout.addLayout(target_row)

        self.configuration_status = QLabel(
            "The global default mod list has not been loaded."
        )
        self.configuration_status.setWordWrap(True)
        self.setup_layout.addWidget(self.configuration_status)
        warning = QLabel(
            "This tab changes only Zomboid/mods/default.txt. Import save lists read-only from Mod Packs."
        )
        warning.setWordWrap(True)
        self.setup_layout.addWidget(warning)

        profile_row = QHBoxLayout()
        profile_label = QLabel("LOAD ORDER")
        profile_label.setObjectName("sectionKicker")
        profile_row.addWidget(profile_label)
        profile_row.addStretch(1)
        self.save_profile_button = QPushButton("Save as Pack…")
        self.save_profile_button.setToolTip(
            "Save the current ordered active list as a named Mod Pack."
        )
        self.save_profile_button.clicked.connect(self._save_profile)
        profile_row.addWidget(self.save_profile_button)
        self.load_pack_button = QPushButton("Mod Packs…")
        self.load_pack_button.setAccessibleName("Load or manage Mod Packs")
        self.load_pack_button.setToolTip(
            "Choose a saved Mod Pack to load and apply, or manage saved packs."
        )
        self.load_pack_button.clicked.connect(self._open_mod_packs)
        profile_row.addWidget(self.load_pack_button)
        layout.addLayout(profile_row)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(5)
        details_page.setMinimumWidth(280)

        available_panel = QWidget()
        available_panel.setMinimumWidth(230)
        available_column = QVBoxLayout(available_panel)
        available_column.setContentsMargins(8, 8, 8, 8)
        self.inactive_heading = QLabel("DISCOVER  ·  0")
        self.inactive_heading.setObjectName("panelHeading")
        available_column.addWidget(self.inactive_heading)
        self.manage_search = QLineEdit()
        self.manage_search.setPlaceholderText("Search inactive mods")
        self.manage_search.setAccessibleName("Search inactive mods")
        self.manage_search.setToolTip("Search mod names, Mod IDs, and Workshop IDs.")
        self.manage_search.textChanged.connect(self._filter_available_mods)
        available_column.addWidget(self.manage_search)
        inactive_options = QHBoxLayout()
        self.inactive_filter = QComboBox()
        self.inactive_filter.addItems(["All sources", "Workshop", "Local", "Warnings"])
        self.inactive_filter.currentIndexChanged.connect(
            lambda _index: self._filter_available_mods(self.manage_search.text())
        )
        inactive_options.addWidget(self.inactive_filter)
        self.inactive_sort = QComboBox()
        self.inactive_sort.addItems(
            ["Name A–Z", "Name Z–A", "Mod ID A–Z", "Mod ID Z–A"]
        )
        self.inactive_sort.currentIndexChanged.connect(
            lambda _index: self._refresh_management_lists()
        )
        inactive_options.addWidget(self.inactive_sort)
        available_column.addLayout(inactive_options)
        self.available_list = StagingModListWidget()
        self.available_list.empty_text = "Scanning installed mods…"
        self.available_list.setAccessibleName("Inactive mods")
        self.available_list.setToolTip("Drag selected mods to Active to enable them.")
        self.available_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.available_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.available_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.available_list.itemDoubleClicked.connect(
            lambda _item: self._stage_activate()
        )
        self.available_list.items_dropped.connect(
            lambda source, mod_ids, row: self._handle_mod_list_drop(
                source, self.available_list, mod_ids, row
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        self.available_list.currentItemChanged.connect(self._show_management_item)
        self.available_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.available_list.customContextMenuRequested.connect(
            lambda point: self._show_list_context_menu(self.available_list, point)
        )
        available_column.addWidget(self.available_list, 1)
        self.select_filtered_button = QPushButton("Select Filtered")
        self.select_filtered_button.clicked.connect(self._select_filtered_available)
        available_actions = QHBoxLayout()
        available_actions.addWidget(self.select_filtered_button)
        self.launch_game_button = QPushButton("Launch Project Zomboid")
        self.launch_game_button.setToolTip(
            "Apply staged global mod-list changes, then launch Project Zomboid through Steam."
        )
        self.launch_game_button.clicked.connect(self._launch_project_zomboid)
        self.launch_readiness = QLabel()
        self.launch_readiness.setObjectName("issueSummary")
        self.launch_readiness.setAccessibleName("Launch readiness")
        self.launch_readiness.setToolTipDuration(10000)
        self.launch_readiness.hide()
        # Transfer controls are added after both lists have been constructed.
        self.workspace_splitter.addWidget(available_panel)

        self.activate_button = QPushButton("Enable →")
        self.activate_button.setToolTip(
            "Enable selected mods. You can also drag them to Active."
        )
        self.activate_button.clicked.connect(self._stage_activate)
        self.deactivate_button = QPushButton("← Disable")
        self.deactivate_button.setToolTip(
            "Disable selected mods. You can also drag them to Inactive."
        )
        self.deactivate_button.clicked.connect(self._stage_deactivate)
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(lambda: self._move_active(-1))
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(lambda: self._move_active(1))
        self.suggest_order_button = QPushButton("Suggest Order…")
        self.suggest_order_button.clicked.connect(self._suggest_dependency_order)
        self.manage_sort_rules_button = QPushButton("Rules…")
        self.manage_sort_rules_button.clicked.connect(self._manage_sort_rules)
        active_panel = QWidget()
        active_panel.setMinimumWidth(230)
        active_column = QVBoxLayout(active_panel)
        active_column.setContentsMargins(8, 8, 8, 8)
        self.active_heading = QLabel("ACTIVE ORDER  ·  0")
        self.active_heading.setObjectName("panelHeading")
        active_column.addWidget(self.active_heading)
        self.active_search = QLineEdit()
        self.active_search.setPlaceholderText("Search active mods")
        self.active_search.setAccessibleName("Search active mods")
        self.active_search.setToolTip(
            "Search the staged global mod list by name or ID."
        )
        self.active_search.textChanged.connect(self._filter_active_mods)
        active_column.addWidget(self.active_search)
        self.active_filter = QComboBox()
        self.active_filter.addItems(
            ["All active", "Workshop", "Local", "Warnings", "Missing / duplicate"]
        )
        self.active_filter.currentIndexChanged.connect(
            lambda _index: self._filter_active_mods(self.active_search.text())
        )
        active_column.addWidget(self.active_filter)
        self.active_list = OrderedModListWidget()
        self.active_list.empty_text = "No active Mod IDs in the global list"
        self.active_list.setAccessibleName("Active mods in global default order")
        self.active_list.setToolTip(
            "Drag selected mods to Inactive to disable them. Drag within this list to reorder."
        )
        self.active_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.active_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.active_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.active_list.order_changed.connect(self._active_list_reordered)
        self.active_list.items_dropped.connect(
            lambda source, mod_ids, row: self._handle_mod_list_drop(
                source, self.active_list, mod_ids, row
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        self.active_list.itemDoubleClicked.connect(
            lambda _item: self._stage_deactivate()
        )
        self.active_list.currentItemChanged.connect(self._show_management_item)
        self.active_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.active_list.customContextMenuRequested.connect(
            lambda point: self._show_list_context_menu(self.active_list, point)
        )
        active_column.addWidget(self.active_list, 1)
        self.issue_summary = QLabel("0 warnings  ·  0 errors")
        self.issue_summary.setObjectName("issueSummary")
        self.issue_summary.setAccessibleName("Warning and error counts")
        self.issue_summary.setToolTip(
            "Counts from discovery and declared dependency checks. "
            "Optional file and log analyses are shown in Library & diagnostics."
        )
        active_column.addWidget(self.issue_summary)
        active_column.addWidget(self.deactivate_button)
        order_buttons = QHBoxLayout()
        order_buttons.addWidget(self.move_up_button)
        order_buttons.addWidget(self.move_down_button)
        active_column.addLayout(order_buttons)
        order_actions = QHBoxLayout()
        order_actions.addWidget(self.suggest_order_button)
        order_actions.addWidget(self.manage_sort_rules_button)
        active_column.addLayout(order_actions)
        self.workspace_splitter.addWidget(active_panel)
        available_actions.addWidget(self.activate_button)
        available_column.addLayout(available_actions)
        details_page.setObjectName("detailsPane")
        self.workspace_splitter.addWidget(details_page)
        self.workspace_splitter.setSizes([400, 390, 470])
        saved_splitter = self._settings.value("window/workspace_splitter")
        if saved_splitter is not None:
            self.workspace_splitter.restoreState(saved_splitter)
        layout.addWidget(self.workspace_splitter, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.workspace_scan_button = QPushButton("Refresh")
        self.workspace_scan_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.launch_game_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.workspace_scan_button.setToolTip(
            "Rescan installed mods without changing game files."
        )
        self.workspace_scan_button.clicked.connect(self._start_scan)
        self.scan_button = self.workspace_scan_button
        footer.addWidget(self.workspace_scan_button)
        footer.addWidget(self.launch_game_button)
        footer.addWidget(self.launch_readiness)
        self.revert_button = QPushButton("Discard Changes")
        self.revert_button.setToolTip(
            "Restore the last loaded global mod list in this window. Game files are unchanged."
        )
        self.revert_button.clicked.connect(self._revert_staged_configuration)
        footer.addWidget(self.revert_button)
        footer.addStretch(1)
        self.dirty_indicator = QLabel("No unapplied changes")
        self.dirty_indicator.setObjectName("dirtyIndicator")
        footer.addWidget(self.dirty_indicator)
        self.apply_config_button = QPushButton("Apply To Project Zomboid…")
        self.apply_config_button.setObjectName("primaryAction")
        self.apply_config_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.apply_config_button.setToolTip(
            "Back up and update the global default mod list after confirmation."
        )
        self.apply_config_button.clicked.connect(self._apply_active_configuration)
        footer.addWidget(self.apply_config_button)
        layout.addLayout(footer)
        self._install_workspace_shortcuts()
        self._update_apply_enabled()
        return page

    def _build_import_collection_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QLabel("Import a Steam Workshop Collection")
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        instructions = QLabel(
            "Enter a public Project Zomboid Workshop collection URL or ID to "
            "review its items and save the installed mods as a Mod Pack. "
            "Workshop subscriptions and downloads are still handled by Steam."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.import_workshop_collection_button = QPushButton("Import Collection…")
        self.import_workshop_collection_button.setToolTip(
            "Read a public collection and save its installed mods as a Mod Pack."
        )
        self.import_workshop_collection_button.setEnabled(False)
        self.import_workshop_collection_button.clicked.connect(
            self._import_workshop_collection
        )
        layout.addWidget(
            self.import_workshop_collection_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.collection_import_status = QLabel(
            "Scan the library from Mod Workspace before importing a collection."
        )
        self.collection_import_status.setWordWrap(True)
        self.collection_import_status.setObjectName("secondaryText")
        layout.addWidget(self.collection_import_status)
        layout.addStretch(1)
        return page

    def _set_advanced_preview_visible(self, visible: bool) -> None:
        self.main_tabs.setTabVisible(self.library_tab_index, visible)

    def _on_main_tab_changed(self, index: int) -> None:
        page = self.main_tabs.widget(index)
        if page is self.workshop_page:
            self.workshop_page.open_home_if_needed()
            return
        if page is not self.workspace_page:
            return
        if self._worker is not None and self._worker.isRunning():
            self._scan_again_after_current = True
            return
        self._start_scan()
