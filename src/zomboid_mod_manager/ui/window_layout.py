"""Main window layout and tab composition."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QAction, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
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
        self._game_build_detection = detect_game_build(str(saved_game_path))
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
        if use_saved_paths and self._settings.contains("metadata/target"):
            saved_metadata_target = str(self._settings.value("metadata/target"))
        else:
            saved_metadata_target = self._game_build_detection.major_build or "all"
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
        self.detect_build_button = QPushButton("Use Installed")
        self.detect_build_button.setAccessibleName(
            "Detect the installed Project Zomboid build"
        )
        self.detect_build_button.setToolTip(
            "Detect the installed build family and use a current exact version when Steam's install record supports it. "
            "You can edit the version field at any time."
        )
        self.detect_build_button.clicked.connect(self._use_detected_game_build)
        target_row.addWidget(self.detect_build_button)
        details_layout.addLayout(target_row)
        self.game_build_status = QLabel(
            format_game_build_detection(self._game_build_detection)
        )
        self.game_build_status.setObjectName("secondaryText")
        self.game_build_status.setWordWrap(True)
        self.game_build_status.setAccessibleName("Detected game build evidence")
        details_layout.addWidget(self.game_build_status)
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

        if self._detected.diagnostics:
            self.diagnostics.setPlainText("\n".join(self._detected.diagnostics))
        self._load_active_configuration()
        self._start_scan()

    def _set_advanced_preview_visible(self, visible: bool) -> None:
        self.main_tabs.setTabVisible(self.library_tab_index, visible)

    def _on_main_tab_changed(self, index: int) -> None:
        page = self.main_tabs.widget(index)
        if page is self.workshop_page:
            self.workshop_page.open_home_if_needed()
            return
        if page is not self.workspace_page:
            return
        local_roots, workshop_roots = self._selected_roots()
        scan_key = self._scan_key(local_roots, workshop_roots)
        if self._worker is not None and self._worker.isRunning():
            self._scan_again_after_current = scan_key != self._active_scan_key
            return
        self._start_scan()
