"""Build the mod workspace tab and its staging controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .window_widgets import OrderedModListWidget, StagingModListWidget


class WorkspaceLayoutMixin:
    def _build_management_tab(
        self, active_config_path: Path | None, details_page: QWidget
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

        target_heading = QLabel("GLOBAL MOD LIST")
        target_heading.setObjectName("sectionKicker")
        self.setup_layout.addWidget(target_heading)
        target_intro = QLabel(
            "Load Zomboid/mods/default.txt to stage changes. Applying creates a backup before updating this file."
        )
        target_intro.setObjectName("secondaryText")
        target_intro.setWordWrap(True)
        self.setup_layout.addWidget(target_intro)
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
        self.active_config_path.setAccessibleName("Global mod list path")
        self.active_config_path.setClearButtonEnabled(True)
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
        self.configuration_status.setObjectName("configStatus")
        self.configuration_status.setWordWrap(True)
        self.setup_layout.addWidget(self.configuration_status)
        profile_row = QHBoxLayout()
        profile_label = QLabel("MOD WORKSPACE")
        profile_label.setObjectName("sectionKicker")
        profile_row.addWidget(profile_label)
        self.workflow_hint = QLabel(
            "Choose mods  →  arrange the order  →  apply when ready"
        )
        self.workflow_hint.setObjectName("workflowHint")
        profile_row.addWidget(self.workflow_hint)
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
        self.view_pack_saves_button = QPushButton("Saves…")
        self.view_pack_saves_button.setAccessibleName(
            "View saves grouped with the loaded Mod Pack"
        )
        self.view_pack_saves_button.setToolTip(
            "View and organize existing saves for the currently loaded Mod Pack."
        )
        self.view_pack_saves_button.setEnabled(False)
        self.view_pack_saves_button.clicked.connect(self._open_pack_saves)
        profile_row.addWidget(self.view_pack_saves_button)
        self.unload_pack_button = QPushButton("Unload Pack")
        self.unload_pack_button.setAccessibleName("Unload loaded Mod Pack files")
        self.unload_pack_button.setToolTip(
            "Archive the loaded pack's app-owned mod folders. The saved pack remains available, "
            "and the global mod list and staged Active Order stay unchanged."
        )
        self.unload_pack_button.setEnabled(False)
        self.unload_pack_button.clicked.connect(self._unload_collection_mod_pack)
        profile_row.addWidget(self.unload_pack_button)
        layout.addLayout(profile_row)
        self.workspace_notice = QWidget()
        self.workspace_notice.setObjectName("workspaceNotice")
        notice_row = QHBoxLayout(self.workspace_notice)
        notice_row.setContentsMargins(12, 8, 12, 8)
        self.workspace_notice_text = QLabel()
        self.workspace_notice_text.setWordWrap(True)
        notice_row.addWidget(self.workspace_notice_text, 1)
        open_settings = QPushButton("Open Paths && Settings")
        open_settings.clicked.connect(
            lambda: self.main_tabs.setCurrentWidget(self.setup_page)
        )
        notice_row.addWidget(open_settings)
        layout.addWidget(self.workspace_notice)
        self.workspace_notice.hide()

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(5)
        details_page.setMinimumWidth(280)

        available_panel = QWidget()
        available_panel.setObjectName("workspacePanel")
        available_panel.setMinimumWidth(230)
        available_column = QVBoxLayout(available_panel)
        available_column.setContentsMargins(12, 12, 12, 12)
        available_column.setSpacing(7)
        self.inactive_heading = QLabel("AVAILABLE MODS  ·  0")
        self.inactive_heading.setObjectName("panelHeading")
        self.inactive_heading.setWordWrap(True)
        available_column.addWidget(self.inactive_heading)
        self.browse_mods_button = QPushButton("Browse Mods…")
        self.browse_mods_button.setToolTip(
            "Search Workshop mods and install them into your local-mod folder without subscribing."
        )
        self.browse_mods_button.clicked.connect(self._browse_workshop_mods)
        available_column.addWidget(self.browse_mods_button)
        self.available_intro = QLabel("Installed mods you can add to the load order")
        self.available_intro.setObjectName("secondaryText")
        self.available_intro.setWordWrap(True)
        available_intro_row = QHBoxLayout()
        available_intro_row.addWidget(self.available_intro, 1)
        self.review_library_findings_button = QPushButton("Review")
        self.review_library_findings_button.setObjectName("subtleAction")
        self.review_library_findings_button.setAccessibleName("Review library findings")
        self.review_library_findings_button.setToolTip(
            "Open Library Diagnostics at the first library warning or error."
        )
        self.review_library_findings_button.clicked.connect(
            self._review_library_findings
        )
        self.review_library_findings_button.hide()
        available_intro_row.addWidget(self.review_library_findings_button)
        available_column.addLayout(available_intro_row)
        self.manage_search = QLineEdit()
        self.manage_search.setPlaceholderText("Search installed mods or IDs")
        self.manage_search.setClearButtonEnabled(True)
        self.manage_search.setAccessibleName("Search available mods")
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
        self.inactive_build_filter = QComboBox()
        self.inactive_build_filter.addItem("Show all", "all")
        self.inactive_build_filter.addItem("Build 41", "41")
        self.inactive_build_filter.addItem("Build 42", "42")
        self.inactive_build_filter.setAccessibleName("Available Mods game build filter")
        self.inactive_build_filter.setToolTip(
            "Filter which metadata layouts appear in Available Mods. Compatibility warnings follow Target metadata, not this list filter."
        )
        self.inactive_build_filter.currentIndexChanged.connect(
            lambda _index: self._refresh_management_lists()
        )
        available_column.addWidget(self.inactive_build_filter)
        self.available_list = StagingModListWidget()
        self.available_list.empty_text = "Scanning installed mods…"
        self.available_list.setAccessibleName("Available mods")
        self.available_list.setToolTip(
            "Select a mod to inspect it. Double-click or drag it to Active Order to add it."
        )
        self.available_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.available_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.available_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.available_list.itemDoubleClicked.connect(self._stage_activate_item)
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
        self.select_filtered_button = QPushButton("Select")
        self.select_filtered_button.setObjectName("subtleAction")
        self.select_filtered_button.setAccessibleName(
            "Select all shown Available Mods mods"
        )
        self.select_filtered_button.setToolTip(
            "Select every mod currently shown in Available Mods. Use Add to stage them."
        )
        self.select_filtered_button.clicked.connect(self._select_filtered_available)
        available_actions = QHBoxLayout()
        available_actions.addWidget(self.select_filtered_button)
        self.launch_game_button = QPushButton("Launch Project Zomboid")
        self.launch_game_button.setToolTip(
            "Apply staged global mod-list changes, then launch through Steam. A loaded collection uses a one-time folder order that puts its local copies ahead of Workshop copies."
        )
        self.launch_game_button.clicked.connect(self._launch_project_zomboid)
        self.launch_readiness = QLabel()
        self.launch_readiness.setObjectName("issueSummary")
        self.launch_readiness.setAccessibleName("Launch readiness")
        self.launch_readiness.setToolTipDuration(10000)
        self.launch_readiness.hide()
        # Transfer controls are added after both lists have been constructed.
        self.workspace_splitter.addWidget(available_panel)

        self.activate_button = QPushButton("Add →")
        self.activate_button.setAccessibleName("Add mods to Active Order")
        self.activate_button.setToolTip(
            "Add selected mods to Active Order. This stages the change; the game list stays the same until you apply."
        )
        self.activate_button.clicked.connect(self._stage_activate)
        self.deactivate_button = QPushButton("← Remove")
        self.deactivate_button.setAccessibleName("Remove mods from Active Order")
        self.deactivate_button.setObjectName("subtleAction")
        self.deactivate_button.setToolTip(
            "Remove selected mods from Active Order. This stages the change; installed mod files stay in place."
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
        active_panel.setObjectName("workspacePanel")
        active_panel.setMinimumWidth(230)
        active_column = QVBoxLayout(active_panel)
        active_column.setContentsMargins(12, 12, 12, 12)
        active_column.setSpacing(7)
        self.active_heading = QLabel("ACTIVE ORDER  ·  0")
        self.active_heading.setObjectName("panelHeading")
        active_column.addWidget(self.active_heading)
        self.active_intro = QLabel("Drag to reorder; changes stay staged until applied")
        self.active_intro.setObjectName("secondaryText")
        self.active_intro.setWordWrap(True)
        active_column.addWidget(self.active_intro)
        self.active_search = QLineEdit()
        self.active_search.setPlaceholderText("Search active mods or IDs")
        self.active_search.setClearButtonEnabled(True)
        self.active_search.setAccessibleName("Search active mods")
        self.active_search.setToolTip(
            "Search the staged global mod list by name or ID."
        )
        self.active_search.textChanged.connect(self._filter_active_mods)
        active_column.addWidget(self.active_search)
        self.active_filter = QComboBox()
        self.active_filter.addItems(
            ["All active", "Workshop", "Local", "Missing / duplicate"]
        )
        self.active_filter.currentIndexChanged.connect(
            lambda _index: self._filter_active_mods(self.active_search.text())
        )
        active_column.addWidget(self.active_filter)
        self.active_list = OrderedModListWidget()
        self.active_list.empty_text = (
            "Active Order is empty. Choose mods in Available Mods, then select Add."
        )
        self.active_list.setAccessibleName("Active mods in global default order")
        self.active_list.setToolTip(
            "Select a mod to inspect it. Double-click or drag it to Available Mods to remove it; drag within this list to reorder."
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
        self.active_list.itemDoubleClicked.connect(self._stage_deactivate_item)
        self.active_list.currentItemChanged.connect(self._show_management_item)
        self.active_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.active_list.customContextMenuRequested.connect(
            lambda point: self._show_list_context_menu(self.active_list, point)
        )
        active_column.addWidget(self.active_list, 1)
        self.issue_summary = QLabel("Active order: not checked")
        self.issue_summary.setObjectName("issueSummary")
        self.issue_summary.setAccessibleName("Active-order issues")
        self.issue_summary.setToolTip(
            "Counts mods in the active list that are missing or appear more than once, plus requirement issues. "
            "Library warnings and errors are shown in Available Mods. "
            "Optional file and log checks are shown in Library & diagnostics."
        )
        active_issue_row = QHBoxLayout()
        active_issue_row.setSpacing(6)
        active_issue_row.addWidget(self.issue_summary, 1)
        self.review_active_order_button = QPushButton("Review")
        self.review_active_order_button.setObjectName("subtleAction")
        self.review_active_order_button.setAccessibleName("Review active-order issues")
        self.review_active_order_button.setToolTip(
            "Open Library Diagnostics at the first active-order finding."
        )
        self.review_active_order_button.clicked.connect(
            self._review_active_order_issues
        )
        self.review_active_order_button.hide()
        active_issue_row.addWidget(self.review_active_order_button)
        active_column.addLayout(active_issue_row)
        active_actions = QGridLayout()
        active_actions.setSpacing(6)
        active_actions.addWidget(self.deactivate_button, 0, 0)
        active_actions.addWidget(self.suggest_order_button, 0, 1, 1, 2)
        active_actions.addWidget(self.move_up_button, 1, 0)
        active_actions.addWidget(self.move_down_button, 1, 1)
        active_actions.addWidget(self.manage_sort_rules_button, 1, 2)
        active_column.addLayout(active_actions)
        self.workspace_splitter.addWidget(active_panel)
        available_actions.addWidget(self.activate_button)
        available_column.addLayout(available_actions)
        details_page.setObjectName("detailsPane")
        self.workspace_splitter.addWidget(details_page)
        self.workspace_splitter.setSizes([400, 390, 470])
        for mod_list in (self.available_list, self.active_list):
            mod_list.itemSelectionChanged.connect(self._update_workspace_actions)
            mod_list.currentRowChanged.connect(self._update_workspace_actions)
        saved_splitter = self._settings.value("window/workspace_splitter")
        if saved_splitter is not None:
            self.workspace_splitter.restoreState(saved_splitter)
        layout.addWidget(self.workspace_splitter, 1)
        QWidget.setTabOrder(self.available_list, self.select_filtered_button)
        QWidget.setTabOrder(self.select_filtered_button, self.activate_button)
        QWidget.setTabOrder(self.activate_button, self.active_search)

        footer_rule = QFrame()
        footer_rule.setFrameShape(QFrame.Shape.HLine)
        footer_rule.setObjectName("footerRule")
        layout.addWidget(footer_rule)
        utility_row = QHBoxLayout()
        utility_row.setSpacing(8)
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
        self.workspace_scan_button.clicked.connect(self._refresh_scan)
        self.scan_button = self.workspace_scan_button
        utility_row.addWidget(self.workspace_scan_button)
        utility_row.addWidget(self.launch_game_button)
        utility_row.addWidget(self.launch_readiness)
        self.revert_button = QPushButton("Discard Changes")
        self.revert_button.setToolTip(
            "Restore the last loaded global mod list in this window. Game files are unchanged."
        )
        self.revert_button.clicked.connect(self._revert_staged_configuration)
        utility_row.addWidget(self.revert_button)
        utility_row.addStretch(1)
        self.dirty_indicator = QLabel("No unapplied changes")
        self.dirty_indicator.setObjectName("dirtyIndicator")
        utility_row.addWidget(self.dirty_indicator)
        self.apply_config_button = QPushButton("Apply To Project Zomboid…")
        self.apply_config_button.setAccessibleName(
            "Apply staged global list to Project Zomboid"
        )
        self.apply_config_button.setObjectName("primaryAction")
        self.apply_config_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.apply_config_button.setToolTip(
            "Back up and update the global default mod list after confirmation."
        )
        self.apply_config_button.clicked.connect(self._apply_active_configuration)
        utility_row.addWidget(self.apply_config_button)
        layout.addLayout(utility_row)
        self._install_workspace_shortcuts()
        self._update_apply_enabled()
        return page
