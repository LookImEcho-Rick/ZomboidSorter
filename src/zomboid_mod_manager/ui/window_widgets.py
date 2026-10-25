"""Reusable Qt workers and list/preview widgets for the main window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QMovie,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SOURCE_ROLE = SEARCH_ROLE + 1
ISSUE_ROLE = SEARCH_ROLE + 2
NEW_WORKSHOP_ROLE = ISSUE_ROLE + 1
BUILD_41_ROLE = NEW_WORKSHOP_ROLE + 1
BUILD_42_ROLE = BUILD_41_ROLE + 1


class PreviewLabel(QLabel):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._movie: QMovie | None = None
        self._movie_source_size = QSize()
        self._movie_scaled_size = QSize()
        self._mouse_pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def show_placeholder(self, text: str) -> None:
        self._stop_movie()
        self._image = QImage()
        self._mouse_pressed = False
        self.clear()
        self.setText(text)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def show_image(self, image: QImage) -> None:
        self._stop_movie()
        self.clear()
        self._image = image
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click or press Enter to enlarge this image")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._refresh_image()

    def show_movie(self, path: Path) -> bool:
        """Play a local GIF, keeping its current frame available for enlargement."""
        self._stop_movie()
        movie = QMovie(str(path), parent=self)
        if not movie.isValid():
            movie.deleteLater()
            return False
        size = QImageReader(str(path)).size()
        if not size.isValid():
            movie.deleteLater()
            return False

        self.clear()
        self._image = QImage()
        self._movie = movie
        self._movie_source_size = size
        self._movie_scaled_size = QSize()
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        movie.frameChanged.connect(self._movie_frame_changed)
        self.setMovie(movie)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "Animated preview. Click or press Enter to enlarge the current frame"
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._refresh_image()
        movie.start()
        self._movie_frame_changed(movie.currentFrameNumber())
        return True

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
        if self._movie is not None:
            target = self._movie_source_size.scaled(
                self.contentsRect().size(), Qt.AspectRatioMode.KeepAspectRatio
            )
            if target.isValid() and target != self._movie_scaled_size:
                self._movie_scaled_size = target
                self._movie.setScaledSize(target)
            return
        if self._image.isNull():
            return
        self.setPixmap(
            QPixmap.fromImage(self._image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _movie_frame_changed(self, _frame_number: int) -> None:
        if self._movie is not None:
            self._image = self._movie.currentImage()

    def _stop_movie(self) -> None:
        movie = self._movie
        self._movie = None
        self._movie_source_size = QSize()
        self._movie_scaled_size = QSize()
        if movie is not None:
            movie.stop()
            movie.setFileName("")
            movie.deleteLater()


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
