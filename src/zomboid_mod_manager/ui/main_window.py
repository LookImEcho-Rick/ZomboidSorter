"""Project Zomboid library and staged global mod-list workspace."""

from __future__ import annotations

import subprocess
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QRect,
    QSettings,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from zomboid_mod_manager import __version__
from zomboid_mod_manager.configuration import (
    SelectedConfigurationPathMismatch,
    apply_active_configuration,
    is_global_default_mod_list,
    load_active_configuration,
    read_unchanged_active_configuration,
    selected_path_matches_configuration,
)
from zomboid_mod_manager.diagnostics.console_log import (
    analyze_console_log,
    format_console_log_report,
)
from zomboid_mod_manager.diagnostics.dependencies import analyze_dependencies
from zomboid_mod_manager.diagnostics.file_overlaps import (
    analyze_file_overlaps,
    format_file_overlap_report,
)
from zomboid_mod_manager.discovery.paths import detect_paths
from zomboid_mod_manager.discovery.scanner import ScanCancelled, scan_mods
from zomboid_mod_manager.domain import DetectedPaths, ModEntry, ScanResult
from zomboid_mod_manager.gameio.active_mods import (
    ActiveModConfigError,
    ActiveModSnapshot,
    ConcurrentConfigChangeError,
)
from zomboid_mod_manager.profiles import (
    ModProfile,
    ProfileError,
    ProfileStore,
)
from zomboid_mod_manager.sorting.dependency_order import propose_dependency_order
from zomboid_mod_manager.sorting.user_rules import (
    parse_user_order_rules,
    serialize_user_order_rules,
)
from zomboid_mod_manager.ui.mod_details import (
    candidates_for_build,
    find_preview_for_candidates,
    format_entry_description_html,
    format_entry_details,
    format_workshop_description_html,
)
from zomboid_mod_manager.ui.mod_packs_dialog import ModPacksDialog
from zomboid_mod_manager.ui.sort_rules_dialog import SortRulesDialog
from zomboid_mod_manager.ui.theme import apply_theme
from zomboid_mod_manager.ui.workshop_browser import WorkshopBrowserPanel
from zomboid_mod_manager.ui.workshop_dialog import WorkshopCollectionDialog
from zomboid_mod_manager.updates import (
    UpdateCancelled,
    UpdateError,
    UpdateRelease,
    check_for_update,
    download_update,
)
from zomboid_mod_manager.workshop import fetch_item_metadata

SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SOURCE_ROLE = SEARCH_ROLE + 1
ISSUE_ROLE = SEARCH_ROLE + 2
NEW_WORKSHOP_ROLE = ISSUE_ROLE + 1


class ScanWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    cancelled = Signal()

    def __init__(self, local_roots: list[Path], workshop_roots: list[Path]) -> None:
        super().__init__()
        self._local_roots = local_roots
        self._workshop_roots = workshop_roots

    def run(self) -> None:
        try:
            result = scan_mods(
                local_roots=self._local_roots,
                workshop_roots=self._workshop_roots,
                cancelled=self.isInterruptionRequested,
                progress=self.progress.emit,
            )
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.result_ready.emit(result)
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - Surface unexpected scanner failures in the UI.
            self.failed.emit(f"Scan failed: {exc}")


class DiagnosticWorker(QThread):
    result_ready = Signal(str)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], str]) -> None:
        super().__init__()
        self._operation = operation

    def run(self) -> None:
        try:
            self.result_ready.emit(self._operation())
        except Exception as exc:  # noqa: BLE001 - Surface diagnostic failures in the UI.
            self.failed.emit(str(exc))


class UpdateCheckWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.result_ready.emit(check_for_update(__version__))
        except Exception as exc:  # noqa: BLE001 - Surface update check failures in the UI.
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)
    installer_ready = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, release: UpdateRelease) -> None:
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            installer = download_update(
                self.release,
                progress=self.progress.emit,
                cancelled=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                installer.unlink(missing_ok=True)
                self.cancelled.emit()
                return
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - Surface unexpected update failures.
            self.failed.emit(str(exc))
        else:
            self.installer_ready.emit(str(installer))


class WorkshopDescriptionWorker(QThread):
    result_ready = Signal(str, str, str)
    failed = Signal(str, str)

    def __init__(self, workshop_id: str) -> None:
        super().__init__()
        self.workshop_id = workshop_id

    def run(self) -> None:
        try:
            item = fetch_item_metadata(self.workshop_id)
            self.result_ready.emit(item.workshop_id, item.title, item.description)
        except Exception as exc:  # noqa: BLE001 - Surface read-only API failures in the UI.
            self.failed.emit(self.workshop_id, str(exc))


class PreviewWorker(QThread):
    loaded = Signal(str, int, object)

    def __init__(self, path: Path, generation: int) -> None:
        super().__init__()
        self.path = path
        self.generation = generation

    def run(self) -> None:
        image = QImage()
        try:
            if self.path.stat().st_size <= 25_000_000:
                reader = QImageReader(str(self.path))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid() and size.width() * size.height() <= 48_000_000:
                    scaled = size.scaled(
                        QSize(960, 540), Qt.AspectRatioMode.KeepAspectRatio
                    )
                    reader.setScaledSize(scaled)
                    image = reader.read()
        except OSError:
            pass
        self.loaded.emit(str(self.path), self.generation, image)


class PreviewLabel(QLabel):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._mouse_pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def show_placeholder(self, text: str) -> None:
        self._image = QImage()
        self._mouse_pressed = False
        self.clear()
        self.setText(text)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def show_image(self, image: QImage) -> None:
        self._image = image
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click or press Enter to enlarge this image")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._refresh_image()

    @property
    def image(self) -> QImage:
        return self._image

    def mousePressEvent(self, event) -> None:
        self._mouse_pressed = (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
            and not self._image.isNull()
        )
        if self._mouse_pressed:
            self.setFocus()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        clicked = (
            self._mouse_pressed
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
            and not self._image.isNull()
        )
        self._mouse_pressed = False
        if clicked:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
            and not self._image.isNull()
        ):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_image()

    def _refresh_image(self) -> None:
        if self._image.isNull():
            return
        self.setPixmap(
            QPixmap.fromImage(self._image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class ImagePreviewOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("imagePreviewOverlay")
        self.setAccessibleName("Enlarged mod preview overlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pixmap = QPixmap()
        self._image_rect = QRect()
        self._pressed_outside_image = False
        self._previous_focus: QWidget | None = None
        parent.installEventFilter(self)
        self.hide()

    @property
    def image_rect(self) -> QRect:
        return QRect(self._image_rect)

    def show_image(self, image: QImage) -> None:
        if image.isNull():
            return
        self._previous_focus = self.window().focusWidget()
        self._pixmap = QPixmap.fromImage(image)
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        self.update()

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.parentWidget()
            and event.type() == QEvent.Type.Resize
            and self.isVisible()
        ):
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        bounds = self.rect().adjusted(32, 32, -32, -58)
        fitted = self._pixmap.scaled(
            bounds.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = bounds.x() + (bounds.width() - fitted.width()) // 2
        y = bounds.y() + (bounds.height() - fitted.height()) // 2
        self._image_rect = QRect(x, y, fitted.width(), fitted.height())
        painter.drawPixmap(self._image_rect, fitted)
        painter.setPen(QColor("#d5dee7"))
        painter.drawText(
            QRect(0, self.height() - 36, self.width(), 24),
            Qt.AlignmentFlag.AlignCenter,
            "Click outside the image or press Esc to close",
        )

    def mousePressEvent(self, event) -> None:
        self._pressed_outside_image = not self._image_rect.contains(
            event.position().toPoint()
        )
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        outside_image = not self._image_rect.contains(event.position().toPoint())
        if self._pressed_outside_image and outside_image:
            self._dismiss()
        self._pressed_outside_image = False
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._dismiss()
            event.accept()
            return
        super().keyPressEvent(event)

    def _dismiss(self) -> None:
        self.hide()
        if self._previous_focus is not None and self._previous_focus.isVisible():
            self._previous_focus.setFocus(Qt.FocusReason.OtherFocusReason)
        self._previous_focus = None


class ModRowDelegate(QStyledItemDelegate):
    """Draw compact two-line mod rows without creating widgets per item."""

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        size.setHeight(48)
        return size

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        issue = bool(index.data(ISSUE_ROLE))
        recent = bool(index.data(NEW_WORKSHOP_ROLE))
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        card = option.rect.adjusted(2, 2, -2, -2)
        background = "#425d49" if selected else "#293734" if hovered else "#202c2c"
        painter.setPen(QColor("#627963" if selected else "#354744"))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(card, 4, 4)
        painter.fillRect(
            QRect(card.left(), card.top() + 3, 3, card.height() - 6),
            QColor("#e5b66c" if issue else "#8fc991" if recent else "#52695d"),
        )
        label = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        label = label.removeprefix("NEW  ·  ").removeprefix("⚠  ")
        title, separator, mod_id = label.partition("  ·  ")
        if not separator:
            mod_id = str(index.data(Qt.ItemDataRole.UserRole) or "")
        left = card.left() + 12
        right = card.right() - 10
        if issue or recent:
            badge = "ISSUE" if issue else "NEW"
            badge_width = 48
            badge_rect = QRect(right - badge_width, card.top() + 7, badge_width, 18)
            painter.setPen(QColor("#211c13" if issue else "#102116"))
            painter.setBrush(QColor("#e7b973" if issue else "#92c995"))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
            right -= badge_width + 8
        title_font = option.font
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#f3f4ed" if enabled else "#dba96f"))
        painter.drawText(
            QRect(left, card.top() + 5, right - left, 19),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideRight, right - left
            ),
        )
        meta_font = option.font
        meta_font.setPointSizeF(max(8.0, meta_font.pointSizeF() - 1.0))
        painter.setFont(meta_font)
        painter.setPen(QColor("#b0c3b6" if selected else "#9bacaa"))
        painter.drawText(
            QRect(left, card.top() + 24, card.width() - 22, 16),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                mod_id, Qt.TextElideMode.ElideRight, card.width() - 22
            ),
        )
        painter.restore()


class StagingModListWidget(QListWidget):
    items_dropped = Signal(object, object, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.empty_text = "No mods to show"
        self.visible_count = 0
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setItemDelegate(ModRowDelegate(self))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.visible_count:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#9baea5"))
        painter.drawText(
            self.viewport().rect().adjusted(18, 18, -18, -18),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self.empty_text,
        )

    def dropEvent(self, event) -> None:
        source = event.source()
        if not isinstance(source, StagingModListWidget) or source is self:
            event.ignore()
            return
        mod_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in sorted(source.selectedItems(), key=source.row)
            if not item.isHidden()
            and item.flags() & Qt.ItemFlag.ItemIsEnabled
            and isinstance(item.data(Qt.ItemDataRole.UserRole), str)
        ]
        if not mod_ids:
            event.ignore()
            return
        position = event.position().toPoint()
        row = self.indexAt(position).row()
        if row < 0:
            row = self.count()
        elif position.y() > self.visualItemRect(self.item(row)).center().y():
            row += 1
        self.items_dropped.emit(source, mod_ids, row)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


class OrderedModListWidget(StagingModListWidget):
    order_changed = Signal()

    def dropEvent(self, event) -> None:
        if event.source() is self:
            QListWidget.dropEvent(self, event)
            self.order_changed.emit()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        detected: DetectedPaths | None = None,
        active_config_path: Path | None = None,
        profile_store: ProfileStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ZomboidSorter")
        self.resize(1440, 850)
        self.setMinimumSize(980, 620)
        self._settings = QSettings("ZomboidSorter", "ProjectZomboidModManager")
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
        self._preview_pending: Path | None = None
        self._preview_requested: str | None = None
        self._preview_generation = 0
        self._preview_cache: OrderedDict[str, QImage] = OrderedDict()
        self._selected_entry: ModEntry | None = None
        self._workshop_description_worker: WorkshopDescriptionWorker | None = None
        self._workshop_description_pending: str | None = None
        self._workshop_description_requested_id: str | None = None
        self._workshop_description_cache: OrderedDict[str, tuple[str, str]] = (
            OrderedDict()
        )
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_download_worker: UpdateDownloadWorker | None = None

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
        target_row.addWidget(QLabel("Metadata preview:"))
        self.metadata_preview_target = QComboBox()
        self.metadata_preview_target.addItem("All candidates", "all")
        self.metadata_preview_target.addItem("Build 41", "41")
        self.metadata_preview_target.addItem("Build 42", "42")
        self.metadata_preview_target.setAccessibleName("Metadata preview target build")
        self.metadata_preview_target.setToolTip(
            "Filters the displayed metadata and poster by observed root or shared/versioned layout. "
            "This preview does not verify compatibility or select a runtime candidate."
        )
        self.metadata_preview_target.currentIndexChanged.connect(
            self._metadata_preview_target_changed
        )
        target_row.addWidget(self.metadata_preview_target, 1)
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
        title = QLabel("ZOMBOID  /  MOD CONTROL")
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
        self.setup_layout.addLayout(target_row)

        self.configuration_status = QLabel(
            "The global default mod list has not been loaded."
        )
        self.configuration_status.setWordWrap(True)
        self.setup_layout.addWidget(self.configuration_status)
        warning = QLabel(
            "Changes apply only to Zomboid/mods/default.txt. Per-save mod lists are protected."
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

    def _save_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Mod Pack", "Mod Pack name:")
        if not accepted:
            return
        profile = ModProfile(
            name.strip(), tuple(self._staged_mod_ids), self._staged_workshop_ids()
        )
        overwrite = False
        if profile.name in self._profile_store.list_names():
            answer = QMessageBox.question(
                self,
                "Replace Mod Pack",
                f"Replace '{profile.name}'? Its current version will be backed up.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self._profile_store.save(profile, overwrite=overwrite)
        except ProfileError as exc:
            QMessageBox.warning(self, "Could not save Mod Pack", str(exc))
            return
        self.configuration_status.setText(
            f"Saved Mod Pack '{profile.name}'. The game list was not changed."
        )
        self.status.setText(
            f"Saved Mod Pack '{profile.name}' with {len(profile.mod_ids)} Mod IDs."
        )

    def _open_mod_packs(self) -> None:
        dialog = ModPacksDialog(self._profile_store, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.selected_pack is not None:
            self._apply_mod_pack(dialog.selected_pack)

    def _apply_mod_pack(self, profile: ModProfile) -> None:
        snapshot = self._active_config
        if snapshot is None or not self._active_config_matches_selected_path():
            QMessageBox.warning(
                self,
                "Global Mod List Unavailable",
                "Load the supported global Zomboid/mods/default.txt file before applying a Mod Pack.",
            )
            return
        if not is_global_default_mod_list(snapshot.path):
            QMessageBox.warning(
                self,
                "Unsupported Mod List",
                "Mod Packs can only be applied to the global Zomboid/mods/default.txt file. Per-save and server lists are protected.",
            )
            return
        try:
            latest = read_unchanged_active_configuration(snapshot)
        except ConcurrentConfigChangeError:
            QMessageBox.warning(
                self,
                "Global Mod List Changed",
                "The global mod list changed since it was loaded. Reload it, then load the Mod Pack again.",
            )
            return
        except (OSError, ActiveModConfigError) as exc:
            QMessageBox.warning(self, "Could not read global Mod List", str(exc))
            return

        self._active_config = latest
        self._staged_mod_ids = list(profile.mod_ids)
        self._profile_workshop_ids = profile.workshop_ids
        self._refresh_management_lists()
        self._update_apply_enabled()
        self._update_diagnostics()
        if tuple(profile.mod_ids) == latest.config.mods:
            self.configuration_status.setText(
                f"Mod Pack '{profile.name}' is already active; no file change was needed."
            )
            self.status.setText(f"Mod Pack '{profile.name}' is already active.")
            return

        if self._apply_staged_configuration(require_confirmation=False):
            self._profile_workshop_ids = profile.workshop_ids
            self._refresh_management_lists()
            self._update_diagnostics()
            self.status.setText(
                f"Loaded and applied Mod Pack '{profile.name}' to the global mod list."
            )

    def _browse_active_config(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose the global default mod list",
            self.active_config_path.text(),
            "Project Zomboid mod list (default.txt);;Text files (*.txt)",
        )
        if selected:
            self.active_config_path.setText(selected)

    def _configuration_path_changed(self) -> None:
        self._update_apply_enabled()

    def _load_active_configuration(self) -> None:
        self._load_active_configuration_impl(force=False)

    def _load_active_configuration_impl(self, *, force: bool) -> None:
        if not force and not self._confirm_staged_replacement(
            "load a different game configuration"
        ):
            return
        path_text = self.active_config_path.text().strip()
        try:
            if not path_text:
                raise ActiveModConfigError("Choose a global default.txt path first.")
            snapshot = load_active_configuration(path_text)
        except (OSError, ActiveModConfigError) as exc:
            self._active_config = None
            self._staged_mod_ids = []
            self._profile_workshop_ids = ()
            self.configuration_status.setText(f"Could not load this mod list: {exc}")
        else:
            self._active_config = snapshot
            self._staged_mod_ids = list(snapshot.config.mods)
            self._profile_workshop_ids = ()
            self.configuration_status.setText(
                f"Loaded {len(snapshot.config.mods)} active mod IDs from the global default list. "
                "Map order is preserved. Changes are staged until Apply."
            )
        self._refresh_management_lists()
        self._update_apply_enabled()

    def _confirm_staged_replacement(self, action: str) -> bool:
        has_staged_changes = bool(self._staged_mod_ids) and self._active_config is None
        if self._active_config is not None:
            has_staged_changes = tuple(
                self._staged_mod_ids
            ) != self._active_config.config.mods or Path(
                self.active_config_path.text()
            ).expanduser().resolve(strict=False) != self._active_config.path.resolve(
                strict=False
            )
        if not has_staged_changes:
            return True
        answer = QMessageBox.question(
            self,
            "Discard staged changes?",
            f"You have staged mod-list changes. Continue to {action} and discard them? "
            "They have not been written to Project Zomboid.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _staged_workshop_ids(self) -> tuple[str, ...]:
        """Return installed Workshop origins plus unavailable profile IDs."""
        if self._last_result is None:
            return self._profile_workshop_ids
        entries_by_id: dict[str, list[ModEntry]] = {}
        for entry in self._last_result.entries:
            if entry.mod_id:
                entries_by_id.setdefault(entry.mod_id, []).append(entry)
        known: list[str] = []
        for mod_id in self._staged_mod_ids:
            matches = entries_by_id.get(mod_id, [])
            if (
                len(matches) == 1
                and matches[0].workshop_id
                and matches[0].workshop_id not in known
            ):
                known.append(matches[0].workshop_id)
        installed_workshop_ids = {
            item.workshop_id for item in self._last_result.workshop_items
        }
        retained = [
            workshop_id
            for workshop_id in self._profile_workshop_ids
            if workshop_id not in installed_workshop_ids
        ]
        return tuple(dict.fromkeys(known + retained))

    def _import_workshop_collection(self) -> None:
        if self._last_result is None:
            QMessageBox.information(
                self,
                "Scan required",
                "Scan the mod library before importing a collection so installed items can be resolved.",
            )
            return
        dialog = WorkshopCollectionDialog(self._last_result, self)
        dialog.collection_imported.connect(self._save_imported_collection_profile)
        dialog.exec()

    def _save_imported_collection_profile(self, profile: ModProfile) -> None:
        overwrite = False
        if profile.name in self._profile_store.list_names():
            answer = QMessageBox.question(
                self,
                "Replace Mod Pack",
                f"Replace '{profile.name}'? Its current version will be backed up.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self._profile_store.save(profile, overwrite=overwrite)
        except ProfileError as exc:
            QMessageBox.warning(self, "Could not save collection Mod Pack", str(exc))
            return
        self.configuration_status.setText(
            f"Saved Workshop collection as Mod Pack '{profile.name}' with "
            f"{len(profile.mod_ids)} installed Mod IDs and "
            f"{len(profile.workshop_ids)} Workshop items. Open Load Pack to apply it."
        )
        self.status.setText(f"Saved Workshop collection as Mod Pack '{profile.name}'.")

    def _refresh_management_lists(self) -> None:
        selected_id = None
        selected_ids: set[str] = set()
        for widget in (self.active_list, self.available_list):
            if widget.currentItem() is not None:
                selected_id = widget.currentItem().data(Qt.ItemDataRole.UserRole)
            selected_ids.update(
                item.data(Qt.ItemDataRole.UserRole) for item in widget.selectedItems()
            )
        self.available_list.clear()
        self.active_list.clear()

        entries_by_id: dict[str, list[ModEntry]] = {}
        if self._last_result is not None:
            for entry in self._last_result.entries:
                if entry.mod_id:
                    entries_by_id.setdefault(entry.mod_id, []).append(entry)

        staged = set(self._staged_mod_ids)
        for mod_id in self._staged_mod_ids:
            matches = entries_by_id.get(mod_id, [])
            if len(matches) == 1:
                label = f"{matches[0].name}  ·  {mod_id}"
            elif len(matches) > 1:
                label = f"Duplicate installation  ·  {mod_id}"
            else:
                label = f"Not installed  ·  {mod_id}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, mod_id)
            item.setToolTip(label)
            self._set_list_item_metadata(item, mod_id, matches)
            if len(matches) != 1:
                item.setText("⚠  " + label)
                item.setToolTip(
                    f"{label}\n\nThe configured Mod ID is missing or has multiple installed copies."
                )
            elif matches[0].diagnostics:
                item.setText("⚠  " + label)
                item.setToolTip(label + "\n\n" + "\n".join(matches[0].diagnostics))
            self._mark_recently_added_workshop_entry(item, matches)
            self.active_list.addItem(item)

        sort_mode = self.inactive_sort.currentIndex()
        inactive_entries = sorted(
            entries_by_id.items(),
            key=lambda pair: (
                pair[0].casefold() if sort_mode >= 2 else pair[1][0].name.casefold(),
                pair[0].casefold(),
            ),
            reverse=sort_mode in (1, 3),
        )
        for mod_id, matches in inactive_entries:
            if mod_id in staged:
                continue
            if len(matches) == 1:
                label = f"{matches[0].name}  ·  {mod_id}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setToolTip(label)
                if matches[0].diagnostics:
                    item.setText("⚠  " + label)
                    item.setToolTip(label + "\n\n" + "\n".join(matches[0].diagnostics))
            else:
                label = f"Duplicate installation  ·  {mod_id}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setToolTip(
                    f"{label}\n\nResolve duplicate Mod IDs before activating this entry."
                )
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._set_list_item_metadata(item, mod_id, matches)
            self._mark_recently_added_workshop_entry(item, matches)
            self.available_list.addItem(item)
        new_inactive_count = sum(
            bool(self.available_list.item(index).data(NEW_WORKSHOP_ROLE))
            for index in range(self.available_list.count())
        )
        new_active_count = sum(
            bool(self.active_list.item(index).data(NEW_WORKSHOP_ROLE))
            for index in range(self.active_list.count())
        )
        inactive_new_label = (
            f"  ·  {new_inactive_count} new" if new_inactive_count else ""
        )
        active_new_label = f"  ·  {new_active_count} new" if new_active_count else ""
        self.inactive_heading.setText(
            f"DISCOVER  ·  {self.available_list.count()}{inactive_new_label}"
        )
        self.active_heading.setText(
            f"ACTIVE ORDER  ·  {self.active_list.count()}{active_new_label}"
        )
        self._filter_available_mods(self.manage_search.text())
        self._filter_active_mods(self.active_search.text())
        if selected_id:
            for widget in (self.active_list, self.available_list):
                for row in range(widget.count()):
                    item = widget.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == selected_id:
                        widget.setCurrentItem(item)
                    if item.data(Qt.ItemDataRole.UserRole) in selected_ids:
                        item.setSelected(True)
        self._update_diagnostics()

    def _mark_recently_added_workshop_entry(
        self, item: QListWidgetItem, matches: list[ModEntry]
    ) -> None:
        is_new = any(
            entry.key in self._recently_added_workshop_entry_keys for entry in matches
        )
        item.setData(NEW_WORKSHOP_ROLE, is_new)
        if not is_new:
            return
        item.setText(f"NEW  ·  {item.text()}")
        item.setForeground(QColor("#8fe0a7"))
        item.setToolTip(
            item.toolTip() + "\n\nNew Workshop content found on the latest scan."
        )

    @staticmethod
    def _set_list_item_metadata(
        item: QListWidgetItem, mod_id: str, matches: list[ModEntry]
    ) -> None:
        item.setData(
            SEARCH_ROLE,
            " ".join(
                [mod_id]
                + [entry.name for entry in matches]
                + [entry.workshop_id or "" for entry in matches]
            ).casefold(),
        )
        item.setData(SOURCE_ROLE, matches[0].source if len(matches) == 1 else "")
        item.setData(
            ISSUE_ROLE,
            len(matches) != 1
            or any(
                entry.diagnostics
                or any(candidate.diagnostics for candidate in entry.candidates)
                for entry in matches
            ),
        )

    @staticmethod
    def _matches_list_filter(item: QListWidgetItem, query: str, mode: str) -> bool:
        if query.casefold().strip() not in (item.data(SEARCH_ROLE) or ""):
            return False
        if mode in ("Workshop", "Local"):
            return item.data(SOURCE_ROLE) == mode.casefold()
        if mode == "Warnings":
            return bool(item.data(ISSUE_ROLE))
        if mode == "Missing / duplicate":
            return not item.data(SOURCE_ROLE)
        return True

    def _filter_available_mods(self, query: str) -> None:
        mode = self.inactive_filter.currentText()
        visible = 0
        for index in range(self.available_list.count()):
            item = self.available_list.item(index)
            match = self._matches_list_filter(item, query, mode)
            item.setHidden(not match)
            visible += match
        self.available_list.visible_count = visible
        self.available_list.empty_text = (
            "No mods match this search or filter"
            if query or mode != "All sources"
            else "No inactive mods found in the scanned folders"
        )
        self.available_list.viewport().update()

    def _filter_active_mods(self, query: str) -> None:
        mode = self.active_filter.currentText()
        visible = 0
        for index in range(self.active_list.count()):
            item = self.active_list.item(index)
            match = self._matches_list_filter(item, query, mode)
            item.setHidden(not match)
            visible += match
        self.active_list.visible_count = visible
        self.active_list.empty_text = (
            "No active mods match this search or filter"
            if query or mode != "All active"
            else "No active Mod IDs in the global list"
        )
        self.active_list.viewport().update()
        unfiltered = not query.strip() and self.active_filter.currentIndex() == 0
        self.active_list.setDragEnabled(unfiltered)
        self.move_up_button.setEnabled(unfiltered)
        self.move_down_button.setEnabled(unfiltered)

    def _show_management_item(self, current, _previous) -> None:
        if current is None:
            return
        mod_id = current.data(Qt.ItemDataRole.UserRole)
        matches = [
            entry
            for entry in (self._last_result.entries if self._last_result else ())
            if entry.mod_id == mod_id
        ]
        if len(matches) == 1:
            self._display_entry(matches[0])
        else:
            self._clear_preview(
                "NO PREVIEW AVAILABLE", "No unique installed entry is available."
            )
            self.open_workshop_button.setProperty("workshopId", None)
            self.open_workshop_button.setEnabled(False)
            self.open_folder_button.setProperty("entryPath", None)
            self.open_folder_button.setEnabled(False)
            self.details.setPlainText(
                f"Mod ID: {mod_id}\n"
                + (
                    "Multiple installed entries use this ID."
                    if matches
                    else "This Mod ID is not installed."
                )
            )

    def _install_workspace_shortcuts(self) -> None:
        def shortcut(keys: str, parent: QWidget, callback: Callable[[], None]) -> None:
            action = QShortcut(QKeySequence(keys), parent)
            action.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.activated.connect(callback)

        shortcut("Ctrl+F", self, self._focus_workspace_search)
        shortcut("Delete", self.active_list, self._stage_deactivate)
        for widget in (self.available_list, self.active_list):
            shortcut(
                "Return", widget, lambda widget=widget: self._focus_list_details(widget)
            )
            shortcut(
                "Enter", widget, lambda widget=widget: self._focus_list_details(widget)
            )
            shortcut("Escape", widget, widget.clearSelection)
            shortcut(
                "Ctrl+A",
                widget,
                lambda widget=widget: self._select_visible_items(widget),
            )
        for search in (self.manage_search, self.active_search):
            shortcut("Escape", search, search.clear)

    def _focus_workspace_search(self) -> None:
        focused = QApplication.focusWidget()
        search = (
            self.manage_search
            if focused in (self.available_list, self.manage_search)
            else self.active_search
        )
        self.main_tabs.setCurrentIndex(0)
        search.setFocus()
        search.selectAll()

    def _focus_list_details(self, widget: QListWidget) -> None:
        item = widget.currentItem()
        if item is not None and not item.isHidden():
            self._show_management_item(item, None)
            self.details.setFocus()

    @staticmethod
    def _select_visible_items(widget: QListWidget) -> None:
        for row in range(widget.count()):
            item = widget.item(row)
            if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setSelected(True)

    @staticmethod
    def _actionable_items(widget: QListWidget) -> list[QListWidgetItem]:
        items = [
            item
            for item in widget.selectedItems()
            if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsEnabled
        ]
        current = widget.currentItem()
        if (
            not items
            and current is not None
            and not current.isHidden()
            and current.flags() & Qt.ItemFlag.ItemIsEnabled
        ):
            items = [current]
        return items

    def _show_list_context_menu(self, widget: QListWidget, point) -> None:
        clicked = widget.itemAt(point)
        if (
            clicked is not None
            and clicked.flags() & Qt.ItemFlag.ItemIsEnabled
            and not clicked.isSelected()
        ):
            widget.clearSelection()
            widget.setCurrentItem(clicked)
        menu = self._build_list_context_menu(widget)
        menu.exec(widget.viewport().mapToGlobal(point))

    def _build_list_context_menu(self, widget: QListWidget) -> QMenu:
        menu = QMenu(self)
        items = self._actionable_items(widget)
        if items:
            if widget is self.available_list:
                menu.addAction("Enable selected", self._stage_activate)
            else:
                menu.addAction("Disable selected", self._stage_deactivate)
            if len(items) == 1:
                mod_id = items[0].data(Qt.ItemDataRole.UserRole)
                matches = [
                    entry
                    for entry in (
                        self._last_result.entries if self._last_result else ()
                    )
                    if entry.mod_id == mod_id
                ]
                menu.addSeparator()
                menu.addAction(
                    "Copy Mod ID",
                    lambda mod_id=mod_id: QApplication.clipboard().setText(mod_id),
                )
                if len(matches) == 1:
                    entry = matches[0]
                    menu.addAction(
                        "Open mod folder",
                        lambda entry=entry: QDesktopServices.openUrl(
                            QUrl.fromLocalFile(str(entry.entry_path))
                        ),
                    )
                    if entry.workshop_id:
                        menu.addAction(
                            "Copy Workshop ID",
                            lambda entry=entry: QApplication.clipboard().setText(
                                entry.workshop_id
                            ),
                        )
                        menu.addAction(
                            "Open Workshop page",
                            lambda entry=entry: QDesktopServices.openUrl(
                                QUrl(
                                    "https://steamcommunity.com/sharedfiles/"
                                    f"filedetails/?id={entry.workshop_id}"
                                )
                            ),
                        )
        if items:
            menu.addSeparator()
        menu.addAction("Select all visible", lambda: self._select_visible_items(widget))
        return menu

    def _select_filtered_available(self) -> None:
        self.available_list.clearSelection()
        self._select_visible_items(self.available_list)

    def _stage_activate(self) -> None:
        items = self._actionable_items(self.available_list)
        mod_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in sorted(items, key=self.available_list.row)
            if item is not None
        ]
        additions = [
            mod_id
            for mod_id in mod_ids
            if mod_id and mod_id not in self._staged_mod_ids
        ]
        if additions:
            self._staged_mod_ids.extend(additions)
            self._refresh_management_lists()
            self._update_apply_enabled()

    def _stage_deactivate(self) -> None:
        items = self._actionable_items(self.active_list)
        removed = {
            item.data(Qt.ItemDataRole.UserRole) for item in items if item is not None
        }
        remaining = [mod_id for mod_id in self._staged_mod_ids if mod_id not in removed]
        if remaining != self._staged_mod_ids:
            self._staged_mod_ids = remaining
            self._refresh_management_lists()
            self._update_apply_enabled()

    def _handle_mod_list_drop(
        self,
        source: QListWidget,
        target: QListWidget,
        mod_ids: list[str],
        target_row: int,
    ) -> None:
        if source is self.available_list and target is self.active_list:
            known_ids = set(self._staged_mod_ids)
            additions = []
            for mod_id in mod_ids:
                if mod_id not in known_ids:
                    additions.append(mod_id)
                    known_ids.add(mod_id)
            if not additions:
                return
            active_is_filtered = bool(self.active_search.text().strip()) or (
                self.active_filter.currentIndex() != 0
            )
            insertion_row = (
                len(self._staged_mod_ids)
                if active_is_filtered
                else max(0, min(target_row, len(self._staged_mod_ids)))
            )
            self._staged_mod_ids[insertion_row:insertion_row] = additions
        elif source is self.active_list and target is self.available_list:
            removed = set(mod_ids)
            remaining = [
                mod_id for mod_id in self._staged_mod_ids if mod_id not in removed
            ]
            if remaining == self._staged_mod_ids:
                return
            self._staged_mod_ids = remaining
        else:
            return
        self._refresh_management_lists()
        self._update_apply_enabled()

    def _active_list_reordered(self) -> None:
        reordered = [
            self.active_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.active_list.count())
        ]
        if len(reordered) == len(self._staged_mod_ids) and all(
            isinstance(item, str) for item in reordered
        ):
            self._staged_mod_ids = reordered
            self._update_apply_enabled()
            self._update_diagnostics()

    def _move_active(self, offset: int) -> None:
        row = self.active_list.currentRow()
        destination = row + offset
        if row < 0 or not 0 <= destination < len(self._staged_mod_ids):
            return
        self._staged_mod_ids[row], self._staged_mod_ids[destination] = (
            self._staged_mod_ids[destination],
            self._staged_mod_ids[row],
        )
        self._refresh_management_lists()
        self.active_list.setCurrentRow(destination)
        self._update_apply_enabled()

    def _suggest_dependency_order(self) -> None:
        if self._last_result is None:
            self.configuration_status.setText(
                "Scan the mod library before requesting an order suggestion."
            )
            return
        try:
            proposal = propose_dependency_order(
                self._last_result.entries,
                self._staged_mod_ids,
                self._user_order_rules,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Could not suggest order", str(exc))
            return
        if proposal.cycles:
            explanation = "No order was staged because the active constraints contain a cycle:\n\n"
            explanation += "\n".join(
                " → ".join(cycle + (cycle[0],)) for cycle in proposal.cycles
            )
            if proposal.unresolved:
                explanation += "\n\nOther unresolved metadata:\n" + "\n".join(
                    proposal.unresolved[:8]
                )
            self.configuration_status.setText(
                "Order suggestion stopped: active dependency/order cycle."
            )
            QMessageBox.warning(self, "No safe order suggestion", explanation)
            return
        if not proposal.constraints:
            message = "No verified active ordering constraints were found. Your current order is unchanged."
            if proposal.unresolved:
                message += "\n\nUnresolved metadata:\n" + "\n".join(
                    proposal.unresolved[:8]
                )
            self.configuration_status.setText(
                "No verified constraints; current order retained."
            )
            QMessageBox.information(self, "Order suggestion", message)
            return
        if not proposal.changed:
            self.configuration_status.setText(
                f"Current order already satisfies {len(proposal.constraints)} verified constraints."
            )
            QMessageBox.information(
                self,
                "Order suggestion",
                "The current order already satisfies the verified constraints. No change was staged.",
            )
            return

        original_positions = {
            mod_id: index for index, mod_id in enumerate(proposal.original)
        }
        moved = [
            f"{index + 1}. {mod_id}"
            for index, mod_id in enumerate(proposal.suggested)
            if original_positions[mod_id] != index
        ]
        reasons = [
            f"{constraint.before} before {constraint.after}: {constraint.reason}"
            for constraint in proposal.constraints[:12]
        ]
        message = "Stage this deterministic order? It keeps the current order as the tie-breaker.\n\n"
        message += "Changed positions:\n" + "\n".join(moved[:12])
        message += "\n\nConstraints:\n" + "\n".join(reasons)
        if len(proposal.constraints) > 12:
            message += f"\n…and {len(proposal.constraints) - 12} more constraints."
        if proposal.unresolved:
            message += "\n\nUnresolved metadata (not used to order):\n" + "\n".join(
                proposal.unresolved[:8]
            )
        message += "\n\nThis only stages the order. Applying to the global game list is a separate action."
        answer = QMessageBox.question(
            self,
            "Stage suggested order",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._staged_mod_ids = list(proposal.suggested)
        self._refresh_management_lists()
        self._update_apply_enabled()
        self.configuration_status.setText(
            f"Staged an order satisfying {len(proposal.constraints)} verified constraints. "
            "Apply separately to update Project Zomboid."
        )

    def _manage_sort_rules(self) -> None:
        dialog = SortRulesDialog(self._user_order_rules, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rules = dialog.rules()
        self._user_order_rules = rules
        self._user_rule_settings_error = None
        if self._persist_settings:
            self._settings.setValue(
                "sorting/user_rules", serialize_user_order_rules(rules)
            )
            self._settings.sync()
        self._update_diagnostics()

    def _update_apply_enabled(self) -> None:
        if not hasattr(self, "apply_config_button"):
            return
        same_target = False
        if self._active_config is not None:
            try:
                same_target = Path(self.active_config_path.text()).expanduser().resolve(
                    strict=False
                ) == self._active_config.path.resolve(strict=False)
            except OSError:
                same_target = False
        dirty = (
            self._active_config is not None
            and tuple(self._staged_mod_ids) != self._active_config.config.mods
        )
        self.apply_config_button.setEnabled(bool(same_target and dirty))
        self.launch_game_button.setText(
            "Apply & Launch…" if dirty else "Launch Project Zomboid"
        )
        launch_block = self._launch_block_message(same_target)
        self.launch_game_button.setEnabled(launch_block is None)
        if launch_block is None:
            self.launch_readiness.clear()
            self.launch_readiness.hide()
            if dirty:
                self.launch_game_button.setToolTip(
                    "Save the staged global mod-list changes, then launch Project Zomboid through Steam."
                )
            else:
                self.launch_game_button.setToolTip(
                    "Launch Project Zomboid through Steam using the loaded global mod list."
                )
        else:
            message, explanation = launch_block
            self.launch_readiness.setText(message)
            self.launch_readiness.setToolTip(explanation)
            self.launch_readiness.show()
            self.launch_game_button.setToolTip(explanation)
        self.revert_button.setEnabled(bool(dirty))
        if self._active_config is None:
            message = (
                "Changes; global list unavailable"
                if self._staged_mod_ids
                else "Global list unavailable"
            )
        elif not same_target:
            message = "Target path differs from loaded list"
        elif dirty:
            message = "● Unapplied changes"
        else:
            message = "No unapplied changes"
        self.dirty_indicator.setText(message)
        self.dirty_indicator.setStyleSheet(
            "color: #f2c978; font-weight: 700;"
            if dirty or not same_target
            else "color: #a4b2ab;"
        )

    def _launch_block_message(self, same_target: bool) -> tuple[str, str] | None:
        snapshot = self._active_config
        if snapshot is None:
            return (
                "Load global list",
                "Load a valid global Zomboid/mods/default.txt file to enable Launch.",
            )
        if not same_target:
            return (
                "Load selected list",
                "The selected path differs from the loaded mod list. Load the selected global list before launching.",
            )
        if not is_global_default_mod_list(snapshot.path):
            return (
                "Choose global default.txt",
                "Launch supports only the global Zomboid/mods/default.txt target. Save and server mod lists are not changed.",
            )
        try:
            read_unchanged_active_configuration(snapshot)
        except ConcurrentConfigChangeError:
            return (
                "Reload changed list",
                "The global mod list changed outside this app. Reload it before launching so the current list is clear.",
            )
        except OSError, ActiveModConfigError:
            return (
                "Reload global list",
                "The loaded global mod list can no longer be read. Load it again before launching.",
            )
        return None

    def _revert_staged_configuration(self) -> None:
        if self._active_config is None:
            return
        if tuple(self._staged_mod_ids) == self._active_config.config.mods:
            return
        answer = QMessageBox.question(
            self,
            "Discard changes",
            "Discard unapplied changes and restore the last loaded global mod list? "
            "Project Zomboid's files will not be changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._staged_mod_ids = list(self._active_config.config.mods)
        self._profile_workshop_ids = ()
        self._refresh_management_lists()
        self._update_apply_enabled()
        self.configuration_status.setText(
            "Changes discarded; restored the last loaded global mod list."
        )

    def _apply_active_configuration(self) -> bool:
        return self._apply_staged_configuration(require_confirmation=True)

    def _apply_staged_configuration(
        self, *, require_confirmation: bool, launch_after_apply: bool = False
    ) -> bool:
        if self._active_config is None:
            return False
        if not self._active_config_matches_selected_path():
            QMessageBox.warning(
                self,
                "Could Not Apply Mod List",
                "Load the selected global default mod list before applying it.",
            )
            return False
        if tuple(self._staged_mod_ids) == self._active_config.config.mods:
            return True
        if require_confirmation:
            title = (
                "Apply Mod List and Launch"
                if launch_after_apply
                else "Apply Global Mod List"
            )
            confirmation = (
                "Save the staged list to Project Zomboid's global default mod list? A timestamped backup will be created. "
                "After the saved list is verified, Project Zomboid will open through Steam. "
                "Per-save mod lists will not be changed."
                if launch_after_apply
                else "Update the global Project Zomboid default mod list? A timestamped backup will be created. "
                "Per-save mod lists will not be changed."
            )
            answer = QMessageBox.question(
                self,
                title,
                confirmation,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            backup = apply_active_configuration(
                self._active_config,
                self.active_config_path.text(),
                tuple(self._staged_mod_ids),
            )
        except SelectedConfigurationPathMismatch:
            QMessageBox.warning(
                self,
                "Could Not Apply Mod List",
                "Load the selected global default mod list before applying it.",
            )
            return False
        except (OSError, ActiveModConfigError) as exc:
            self.configuration_status.setText(f"Apply failed safely: {exc}")
            QMessageBox.warning(self, "Could not apply mod list", str(exc))
            self._update_apply_enabled()
            return False
        self._load_active_configuration_impl(force=True)
        if self._active_config is None or tuple(
            self._active_config.config.mods
        ) != tuple(self._staged_mod_ids):
            self.configuration_status.setText(
                "Apply could not be verified after reloading the global mod list."
            )
            QMessageBox.warning(
                self,
                "Could Not Verify Mod List",
                "The saved global mod list did not match the staged list after reload. The game was not launched.",
            )
            self._update_apply_enabled()
            return False
        self.configuration_status.setText(
            f"Applied {len(self._staged_mod_ids)} active Mod IDs. Backup: {backup}"
        )
        return True

    def _active_config_matches_selected_path(self) -> bool:
        if self._active_config is None:
            return False
        return selected_path_matches_configuration(
            self._active_config, self.active_config_path.text()
        )

    def _launch_project_zomboid(self) -> None:
        snapshot = self._active_config
        if snapshot is None:
            QMessageBox.warning(
                self,
                "Global Mod List Unavailable",
                "Load a valid global Zomboid/mods/default.txt file before launching.",
            )
            return
        if not self._active_config_matches_selected_path():
            QMessageBox.warning(
                self,
                "Global Mod List Changed",
                "Load the selected global default mod list before launching so the game uses the intended mods.",
            )
            return
        if not is_global_default_mod_list(snapshot.path):
            QMessageBox.warning(
                self,
                "Unsupported Mod List Target",
                "Launching from this app requires the global Zomboid/mods/default.txt target. Save and server mod lists are not changed.",
            )
            return
        if tuple(self._staged_mod_ids) != snapshot.config.mods:
            if not self._apply_staged_configuration(
                require_confirmation=True, launch_after_apply=True
            ):
                return
            snapshot = self._active_config
            if snapshot is None:
                return
        try:
            read_unchanged_active_configuration(snapshot)
        except ConcurrentConfigChangeError:
            QMessageBox.warning(
                self,
                "Global Mod List Changed",
                "The global mod list changed outside this app. Reload it before launching so the current list is clear.",
            )
            return
        except (OSError, ActiveModConfigError) as exc:
            QMessageBox.warning(
                self,
                "Could Not Verify Global Mod List",
                f"The global mod list could not be verified. Reload it before launching.\n\n{exc}",
            )
            return
        if not QDesktopServices.openUrl(QUrl("steam://run/108600")):
            QMessageBox.warning(
                self,
                "Could Not Launch Project Zomboid",
                "Windows could not open the Steam launch link. Make sure Steam is installed and its steam:// links are registered.",
            )
        else:
            self.status.setText(
                "Windows accepted the Steam launch link. Project Zomboid startup is not confirmed."
            )

    @staticmethod
    def _browse_into(field: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(
            field.window(), "Choose folder", field.text()
        )
        if selected:
            field.setText(selected)

    def _add_workshop_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Project Zomboid Workshop content folder",
            self.workshop_paths.text(),
        )
        if not selected:
            return
        current = [
            part.strip()
            for part in self.workshop_paths.text().split(";")
            if part.strip()
        ]
        if selected not in current:
            current.append(selected)
        self.workshop_paths.setText(";".join(current))

    def _selected_roots(self) -> tuple[list[Path], list[Path]]:
        local_text = self.local_path.text().strip()
        local_roots = [Path(local_text).expanduser()] if local_text else []
        workshop_roots = [
            Path(part.strip()).expanduser()
            for part in self.workshop_paths.text().split(";")
            if part.strip()
        ]
        return local_roots, workshop_roots

    def _start_scan(self) -> None:
        if self._shutdown_requested:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        local_roots, workshop_roots = self._selected_roots()
        self.scan_button.setEnabled(False)
        self.workspace_scan_button.setEnabled(False)
        self.status.setText("Scanning selected folders…")
        if self._last_result is None:
            self.available_list.empty_text = "Scanning installed mods…"
            self.available_list.viewport().update()
        self.progress.show()
        self._worker = ScanWorker(local_roots, workshop_roots)
        self._worker.result_ready.connect(self._show_result)
        self._worker.failed.connect(self._show_failure)
        self._worker.progress.connect(self._scan_progress)
        self._worker.cancelled.connect(self._scan_cancelled)
        self._worker.finished.connect(self._finish_scan)
        self.cancel_scan_button.setEnabled(True)
        self.cancel_scan_button.show()
        self._worker.start()

    def _scan_progress(self, message: str) -> None:
        worker = self._worker
        if (
            self._shutdown_requested
            or worker is None
            or worker.isInterruptionRequested()
        ):
            return
        self.status.setText(message)

    def _cancel_scan(self) -> None:
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        self._scan_again_after_current = False
        self.cancel_scan_button.setEnabled(False)
        self.status.setText("Cancelling scan…")
        worker.requestInterruption()

    def _scan_cancelled(self) -> None:
        if self._shutdown_requested:
            return
        self._scan_again_after_current = False
        if self._last_result is None:
            self.available_list.empty_text = (
                "Scan cancelled · select Refresh to try again"
            )
            self.available_list.viewport().update()
        self.status.setText("Scan cancelled; previous results are unchanged.")

    def _finish_scan(self) -> None:
        self._worker = None
        self.cancel_scan_button.hide()
        self.cancel_scan_button.setEnabled(True)
        if self._shutdown_requested:
            return
        self.scan_button.setEnabled(True)
        self.workspace_scan_button.setEnabled(True)
        self._update_busy_indicator()
        if self._scan_again_after_current:
            self._scan_again_after_current = False
            self._start_scan()

    def _update_busy_indicator(self) -> None:
        scan_busy = self._worker is not None and self._worker.isRunning()
        diagnostic_busy = (
            self._diagnostic_worker is not None and self._diagnostic_worker.isRunning()
        )
        self.progress.setVisible(scan_busy or diagnostic_busy)

    def _background_workers(self) -> tuple[QThread, ...]:
        return tuple(
            worker
            for worker in (
                self._worker,
                self._diagnostic_worker,
                self._workshop_description_worker,
                self._preview_worker,
                self._update_check_worker,
                self._update_download_worker,
            )
            if worker is not None
        )

    def _continue_shutdown(self) -> None:
        if not self._shutdown_requested:
            return
        if any(worker.isRunning() for worker in self._shutdown_workers):
            if not self._shutdown_timer.isActive():
                self._shutdown_timer.start(25)
            return
        self._shutdown_timer.stop()
        self._shutdown_workers = ()
        self.close()

    def _show_result(self, result: ScanResult) -> None:
        if self._shutdown_requested:
            return
        if self._worker is not None and self._worker.isInterruptionRequested():
            self._scan_cancelled()
            return
        self.scan_button.setEnabled(True)
        self.workspace_scan_button.setEnabled(True)
        self.import_workshop_collection_button.setEnabled(True)
        previous_result = self._last_result
        previous_workshop_ids = (
            {item.workshop_id for item in previous_result.workshop_items}
            if previous_result is not None
            else set()
        )
        previous_entry_keys = (
            {entry.key for entry in previous_result.entries}
            if previous_result is not None
            else set()
        )
        new_workshop_ids = (
            {item.workshop_id for item in result.workshop_items} - previous_workshop_ids
            if previous_result is not None
            else set()
        )
        self._recently_added_workshop_item_count = len(new_workshop_ids)
        self._recently_added_workshop_entry_keys = {
            entry.key
            for entry in result.entries
            if entry.source == "workshop"
            and previous_result is not None
            and (
                entry.key not in previous_entry_keys
                or entry.workshop_id in new_workshop_ids
            )
        }
        self.collection_import_status.setText(
            f"Library ready: {len(result.workshop_items)} Workshop items and "
            f"{len(result.entries)} mod entries."
        )
        self._preview_generation += 1
        self._preview_cache.clear()
        self._last_result = result
        self._entries = {entry.key: entry for entry in result.entries}
        self.table_model.removeRows(0, self.table_model.rowCount())
        for entry in result.entries:
            values = (
                entry.name,
                entry.mod_id or "(missing ID)",
                entry.workshop_id or "—",
                "Workshop" if entry.source == "workshop" else "Local",
                entry.layout_summary,
                str(len(entry.candidates)),
                str(entry.entry_path),
            )
            row = [QStandardItem(value) for value in values]
            row[0].setData(entry.key, Qt.ItemDataRole.UserRole)
            self.table_model.appendRow(row)

        self.details.setPlainText(
            "Select a mod entry to inspect its metadata candidates.\n\n"
            f"Workshop items: {len(result.workshop_items)}\n"
            f"Mod entries: {len(result.entries)}\n"
            f"Metadata files: {result.metadata_candidate_count}\n"
            "No active Build 42 metadata candidate was selected."
        )
        self._clear_preview(
            "PROJECT ZOMBOID\nMOD DETAILS", "Select a mod to view its declared poster."
        )
        self._refresh_management_lists()
        self._update_apply_enabled()
        warning_count = self._update_diagnostics()
        new_content = []
        if self._recently_added_workshop_item_count:
            count = self._recently_added_workshop_item_count
            new_content.append(f"{count} new Workshop item{'s' if count != 1 else ''}")
        if self._recently_added_workshop_entry_keys:
            count = len(self._recently_added_workshop_entry_keys)
            new_content.append(f"{count} new mod entr{'y' if count == 1 else 'ies'}")
        addition_summary = (
            f" New since the previous scan: {', '.join(new_content)}; marked NEW."
            if new_content
            else ""
        )
        self.status.setText(
            f"Read-only scan complete — {len(result.entries)} mod entries, "
            f"{len(result.workshop_items)} Workshop items, "
            f"{result.metadata_candidate_count} metadata files, "
            f"{warning_count} warnings, {self._issue_error_count} errors."
            f"{addition_summary}"
        )

    def _update_diagnostics(self) -> int:
        lines = [f"INFO: {message}" for message in self._detected.diagnostics]
        warning_count = 0
        error_count = 0
        if self._user_rule_settings_error:
            lines.append(
                "WARNING [invalid-user-order-rules]: Stored rules were ignored: "
                + self._user_rule_settings_error
            )
            warning_count += 1
        result = self._last_result
        if result is not None:
            for diagnostic in result.diagnostics:
                lines.append(
                    f"{diagnostic.level.upper()}: {diagnostic.message}"
                    + (f"\n  {diagnostic.path}" if diagnostic.path else "")
                )
                if diagnostic.level == "warning":
                    warning_count += 1
                elif diagnostic.level == "error":
                    error_count += 1
            for item in result.workshop_items:
                for diagnostic in item.diagnostics:
                    if diagnostic not in result.diagnostics:
                        lines.append(
                            f"{diagnostic.level.upper()}: {diagnostic.message}\n  {diagnostic.path}"
                        )
                        if diagnostic.level == "warning":
                            warning_count += 1
                        elif diagnostic.level == "error":
                            error_count += 1
            for entry in result.entries:
                lines.extend(f"WARNING: {message}" for message in entry.diagnostics)
                warning_count += len(entry.diagnostics)

            installed_workshop_ids = {
                item.workshop_id for item in result.workshop_items
            }
            missing_workshop_ids = [
                workshop_id
                for workshop_id in self._profile_workshop_ids
                if workshop_id not in installed_workshop_ids
            ]
            if missing_workshop_ids:
                lines.append(
                    "WARNING [missing-workshop-items]: Profile references Workshop items not installed locally: "
                    + ", ".join(missing_workshop_ids)
                )
                warning_count += 1

            if self._active_config is not None:
                report = analyze_dependencies(result.entries, self._staged_mod_ids)
                for finding in report.findings:
                    level = "INFO" if finding.kind == "normalization" else "WARNING"
                    lines.append(
                        f"{level} [{finding.kind}]: {finding.message}"
                        + (
                            f"\n  {finding.candidate_path}"
                            if finding.candidate_path
                            else ""
                        )
                    )
                    if level == "WARNING":
                        warning_count += 1
        self._issue_error_count = error_count
        self.issue_summary.setText(
            f"⚠ {warning_count} warning(s)  ·  ● {error_count} error(s)"
        )
        self.diagnostics.setPlainText("\n".join(lines) or "No diagnostics.")
        if self._extra_diagnostics:
            extra = "\n\n".join(
                self._extra_diagnostics[key] for key in sorted(self._extra_diagnostics)
            )
            self.diagnostics.appendPlainText(extra)
        return warning_count

    def _analyze_file_overlaps(self) -> None:
        if self._last_result is None:
            self.status.setText("Scan the mod library before analyzing file overlaps.")
            return
        result = self._last_result
        self._start_diagnostic(
            "file-overlaps",
            lambda: format_file_overlap_report(analyze_file_overlaps(result)),
        )

    def _analyze_console_log(self) -> None:
        initial = Path.home() / "Zomboid" / "console.txt"
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a Project Zomboid console log",
            str(initial),
            "Text logs (*.txt *.log);;All files (*.*)",
        )
        if not selected:
            return
        path = Path(selected)

        def operation() -> str:
            report = analyze_console_log(path)
            return format_console_log_report(path, report)

        self._start_diagnostic("console-log", operation)

    def _start_diagnostic(self, key: str, operation: Callable[[], str]) -> None:
        if self._diagnostic_worker is not None and self._diagnostic_worker.isRunning():
            self.status.setText("A diagnostic analysis is already running.")
            return
        self.file_overlap_button.setEnabled(False)
        self.console_log_button.setEnabled(False)
        self.status.setText("Running read-only diagnostic analysis…")
        self.progress.show()
        worker = DiagnosticWorker(operation)
        self._diagnostic_worker = worker
        worker.result_ready.connect(
            lambda value: self._show_extra_diagnostic(key, value)
        )
        worker.failed.connect(
            lambda message: self._show_extra_diagnostic(
                key, f"Analysis failed: {message}"
            )
        )
        worker.finished.connect(self._finish_diagnostic)
        worker.start()

    def _show_extra_diagnostic(self, key: str, text: str) -> None:
        self._extra_diagnostics[key] = text
        self._update_diagnostics()
        self.status.setText("Read-only diagnostic analysis complete.")

    def _finish_diagnostic(self) -> None:
        self.file_overlap_button.setEnabled(True)
        self.console_log_button.setEnabled(True)
        self._diagnostic_worker = None
        self._update_busy_indicator()

    def _show_selected_entry(self, current, _previous) -> None:
        if not current.isValid():
            self.open_workshop_button.setProperty("workshopId", None)
            self.open_workshop_button.setEnabled(False)
            self.open_folder_button.setProperty("entryPath", None)
            self.open_folder_button.setEnabled(False)
            return
        key = current.sibling(current.row(), 0).data(Qt.ItemDataRole.UserRole)
        entry = self._entries.get(key)
        if entry is None:
            self.open_workshop_button.setProperty("workshopId", None)
            self.open_workshop_button.setEnabled(False)
            self.open_folder_button.setProperty("entryPath", None)
            self.open_folder_button.setEnabled(False)
            return
        self._display_entry(entry)

    def _metadata_preview_target_changed(self, _index: int) -> None:
        if self._selected_entry is not None:
            self._display_entry(self._selected_entry)

    def _display_entry(self, entry: ModEntry) -> None:
        self._selected_entry = entry
        self.open_workshop_button.setProperty("workshopId", entry.workshop_id)
        self.open_workshop_button.setEnabled(bool(entry.workshop_id))
        self.open_folder_button.setProperty("entryPath", str(entry.entry_path))
        self.open_folder_button.setEnabled(True)
        entries = self._last_result.entries if self._last_result else (entry,)
        target_build = self.metadata_preview_target.currentData()
        candidates = candidates_for_build(entry, target_build)
        self.details.setPlainText(
            format_entry_details(
                entry,
                entries,
                self._staged_mod_ids,
                target_build,
                include_description=False,
            )
        )
        if entry.workshop_id:
            self._request_workshop_description(entry, target_build)
        else:
            self._workshop_description_requested_id = None
            self._workshop_description_pending = None
            self._show_local_description(
                entry, target_build, "Local mod.info description"
            )
        choice = find_preview_for_candidates(entry, candidates)
        if choice is None:
            if target_build == "41":
                description = "Build 41 root-style"
            elif target_build == "42":
                description = "Build 42 shared/versioned"
            else:
                description = "selected"
            self._clear_preview(
                "NO PREVIEW AVAILABLE",
                f"No local poster or icon was found in {description} metadata.",
            )
            return
        self._preview_requested = str(choice.path)
        if target_build == "all":
            caption = (
                f"Illustration from {choice.candidate.layout}; "
                "this does not select a game build."
            )
        else:
            caption = (
                f"Illustration from {choice.candidate.layout}; "
                "layout-filtered preview only, not a compatibility check."
            )
        self.preview_caption.setText(f"{caption} Click the image to enlarge it.")
        cached = self._preview_cache.get(self._preview_requested)
        if cached is not None:
            self._preview_cache.move_to_end(self._preview_requested)
            self.preview.show_image(cached)
            self._preview_pending = None
            return
        self.preview.show_placeholder("LOADING PREVIEW…")
        if self._preview_worker is None:
            self._start_preview_worker(choice.path)
        else:
            self._preview_pending = choice.path

    def _show_local_description(
        self, entry: ModEntry, target_build: str, source: str
    ) -> None:
        self.description.setHtml(format_entry_description_html(entry, target_build))
        self.description_source.setText(source)
        self.description_source.setToolTip("")

    def _request_workshop_description(self, entry: ModEntry, target_build: str) -> None:
        workshop_id = entry.workshop_id
        if not workshop_id:
            self._show_local_description(
                entry, target_build, "Local mod.info description"
            )
            return
        self._workshop_description_requested_id = workshop_id
        cached = self._workshop_description_cache.get(workshop_id)
        if cached is not None:
            self._workshop_description_cache.move_to_end(workshop_id)
            self._workshop_description_pending = None
            self._show_loaded_workshop_description(
                entry, target_build, cached[0], cached[1]
            )
            return
        self._show_local_description(
            entry,
            target_build,
            "Loading Workshop description; showing local metadata for now…",
        )
        worker = self._workshop_description_worker
        if worker is not None and worker.workshop_id == workshop_id:
            self._workshop_description_pending = None
            return
        if worker is not None:
            self._workshop_description_pending = workshop_id
            return
        self._start_workshop_description_worker(workshop_id)

    def _start_workshop_description_worker(self, workshop_id: str) -> None:
        worker = WorkshopDescriptionWorker(workshop_id)
        self._workshop_description_worker = worker
        worker.result_ready.connect(self._workshop_description_loaded)
        worker.failed.connect(self._workshop_description_failed)
        worker.finished.connect(self._workshop_description_worker_finished)
        worker.start()

    def _workshop_description_loaded(
        self, workshop_id: str, title: str, description: str
    ) -> None:
        self._workshop_description_cache[workshop_id] = (title, description)
        self._workshop_description_cache.move_to_end(workshop_id)
        if len(self._workshop_description_cache) > 24:
            self._workshop_description_cache.popitem(last=False)
        if (
            self._workshop_description_requested_id != workshop_id
            or self._selected_entry is None
        ):
            return
        self._show_loaded_workshop_description(
            self._selected_entry,
            self.metadata_preview_target.currentData(),
            title,
            description,
        )

    def _show_loaded_workshop_description(
        self, entry: ModEntry, target_build: str, title: str, description: str
    ) -> None:
        if not description.strip():
            self._show_local_description(
                entry,
                target_build,
                "Workshop has no description; showing local mod.info metadata.",
            )
            return
        self.description.setHtml(format_workshop_description_html(description))
        self.description_source.setText(f"Steam Workshop · {title}")
        self.description_source.setToolTip(
            "Full published description fetched read-only from Steam."
        )

    def _workshop_description_failed(self, workshop_id: str, message: str) -> None:
        if (
            self._workshop_description_requested_id == workshop_id
            and self._selected_entry is not None
        ):
            self._show_local_description(
                self._selected_entry,
                self.metadata_preview_target.currentData(),
                "Workshop description unavailable; showing local metadata.",
            )
            self.description_source.setToolTip(message)

    def _workshop_description_worker_finished(self) -> None:
        self._workshop_description_worker = None
        if self._shutdown_requested:
            self._workshop_description_pending = None
            return
        pending = self._workshop_description_pending
        self._workshop_description_pending = None
        if pending and pending == self._workshop_description_requested_id:
            self._start_workshop_description_worker(pending)

    def _clear_preview(self, text: str, caption: str) -> None:
        self._preview_requested = None
        self._preview_pending = None
        self.preview.show_placeholder(text)
        self.preview_caption.setText(caption)

    def _show_enlarged_preview(self) -> None:
        image = self.preview.image
        if image.isNull():
            return
        self.preview_overlay.show_image(image)

    def _start_preview_worker(self, path: Path) -> None:
        self._preview_worker = PreviewWorker(path, self._preview_generation)
        self._preview_worker.loaded.connect(self._preview_loaded)
        self._preview_worker.finished.connect(self._preview_worker_finished)
        self._preview_worker.start()

    def _preview_loaded(self, path: str, generation: int, image: QImage) -> None:
        if generation != self._preview_generation:
            return
        if not image.isNull():
            self._preview_cache[path] = image
            self._preview_cache.move_to_end(path)
            if len(self._preview_cache) > 16:
                self._preview_cache.popitem(last=False)
        if self._preview_requested == path:
            if image.isNull():
                self.preview.show_placeholder("PREVIEW UNAVAILABLE")
            else:
                self.preview.show_image(image)

    def _preview_worker_finished(self) -> None:
        self._preview_worker = None
        if self._shutdown_requested:
            self._preview_pending = None
            return
        pending = self._preview_pending
        self._preview_pending = None
        if (
            pending is not None
            and str(pending) == self._preview_requested
            and str(pending) not in self._preview_cache
        ):
            self._start_preview_worker(pending)

    def _open_selected_folder(self) -> None:
        path = self.open_folder_button.property("entryPath")
        if isinstance(path, str) and Path(path).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_selected_workshop_page(self) -> None:
        workshop_id = self.open_workshop_button.property("workshopId")
        if isinstance(workshop_id, str) and workshop_id.isdecimal():
            QDesktopServices.openUrl(
                QUrl(
                    f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                )
            )

    def _check_for_updates(self) -> None:
        if (
            self._update_check_worker is not None
            and self._update_check_worker.isRunning()
        ):
            return
        if (
            self._update_download_worker is not None
            and self._update_download_worker.isRunning()
        ):
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("Checking…")
        self.status.setText("Checking GitHub for updates…")
        worker = UpdateCheckWorker(self)
        self._update_check_worker = worker
        worker.result_ready.connect(self._update_check_complete)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(self._update_check_worker_finished)
        worker.start()

    def _update_check_complete(self, release: UpdateRelease | None) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        if release is None:
            self.status.setText(f"ZomboidSorter {__version__} is up to date.")
            QMessageBox.information(
                self,
                "No Updates Available",
                f"You are using the latest release of ZomboidSorter ({__version__}).",
            )
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Update Available")
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setText(f"ZomboidSorter {release.version} is available.")
        message.setInformativeText(
            f"Installed version: {__version__}\n"
            "The verified Windows installer will open to complete the update."
        )
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message.setDefaultButton(QMessageBox.StandardButton.No)
        message.button(QMessageBox.StandardButton.Yes).setText("Download and Install")
        answer = message.exec()
        if self._shutdown_requested:
            return
        if answer == QMessageBox.StandardButton.Yes:
            self._download_update(release)
        else:
            self.status.setText(f"ZomboidSorter {release.version} is available.")

    def _update_check_failed(self, error: str) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        self.status.setText("Could not check for updates.")
        QMessageBox.warning(self, "Update Check Failed", error)

    def _update_check_worker_finished(self) -> None:
        if (
            self._update_check_worker is not None
            and not self._update_check_worker.isRunning()
        ):
            self._update_check_worker = None

    def _download_update(self, release: UpdateRelease) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText("Downloading…")
        self.status.setText(f"Downloading ZomboidSorter {release.version}…")
        worker = UpdateDownloadWorker(release)
        self._update_download_worker = worker
        worker.progress.connect(self._update_download_progress)
        worker.installer_ready.connect(self._launch_update_installer)
        worker.failed.connect(self._update_download_failed)
        worker.cancelled.connect(self._update_download_cancelled)
        worker.finished.connect(self._update_download_worker_finished)
        worker.start()

    def _update_download_progress(self, downloaded: int, total: int) -> None:
        if self._shutdown_requested:
            return
        percent = min(100, int(downloaded * 100 / total)) if total else 0
        self.status.setText(f"Downloading update… {percent}%")

    def _update_download_failed(self, error: str) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        self.status.setText("Update download failed.")
        QMessageBox.warning(self, "Update Download Failed", error)

    def _update_download_cancelled(self) -> None:
        if self._shutdown_requested:
            return
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        self.status.setText("Update download cancelled.")

    def _update_download_worker_finished(self) -> None:
        if (
            self._update_download_worker is not None
            and not self._update_download_worker.isRunning()
        ):
            self._update_download_worker = None

    def _launch_update_installer(self, installer_path: str) -> None:
        installer = Path(installer_path)
        if self._shutdown_requested:
            try:
                installer.unlink(missing_ok=True)
            except OSError:
                pass
            return
        try:
            subprocess.Popen([str(installer)], close_fds=True, cwd=installer.parent)
        except OSError as exc:
            self.update_button.setEnabled(True)
            self.update_button.setText("Check for Updates")
            self.status.setText("Could not launch the update installer.")
            QMessageBox.warning(
                self,
                "Could Not Start Installer",
                f"The installer was downloaded and verified, but Windows could not open it:\n{exc}",
            )
            return
        self.status.setText(
            "Installer opened. Follow its prompts to complete the update."
        )
        QApplication.quit()

    def _show_failure(self, message: str) -> None:
        if self._shutdown_requested:
            return
        self.scan_button.setEnabled(True)
        self.workspace_scan_button.setEnabled(True)
        self.status.setText(message)
        if self._last_result is None:
            self.available_list.empty_text = "Scan failed · check Paths & Settings"
            self.available_list.viewport().update()
        self.diagnostics.setPlainText(message)

    def closeEvent(self, event) -> None:
        if self._persist_settings:
            self._settings.setValue("window/geometry", self.saveGeometry())
            self._settings.setValue(
                "window/workspace_splitter", self.workspace_splitter.saveState()
            )
            self._settings.setValue("paths/game", self.game_path.text())
            self._settings.setValue("paths/local", self.local_path.text())
            self._settings.setValue("paths/workshop", self.workshop_paths.text())
            self._settings.setValue(
                "paths/active_config", self.active_config_path.text()
            )
            self._settings.sync()
        workers = tuple(
            worker for worker in self._background_workers() if worker.isRunning()
        )
        if workers:
            if not self._shutdown_requested:
                self._shutdown_requested = True
                self._shutdown_workers = workers
                self._scan_again_after_current = False
                self._workshop_description_pending = None
                self._preview_pending = None
                self.status.setText("Closing after background work stops…")
                self.progress.show()
                self.centralWidget().setEnabled(False)
                self.cancel_scan_button.hide()
                for worker in workers:
                    worker.finished.connect(self._continue_shutdown)
                    worker.requestInterruption()
            event.ignore()
            QTimer.singleShot(0, self._continue_shutdown)
            return
        event.accept()

    def _apply_theme(self) -> None:
        apply_theme(self)
