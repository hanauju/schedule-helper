from __future__ import annotations

import json
import os
import webbrowser
from html.parser import HTMLParser
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import QDate, QEvent, QMimeData, QPoint, QRectF, QSize, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDrag,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QMovie,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
    QTextCursor,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QBoxLayout,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QColorDialog,
    QFormLayout,
    QFontComboBox,
    QFrame,
    QGridLayout,
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
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.models import Event, FocusSession, ItemType, LayoutProfile, LinkFavorite, Preference, QuickNote, QuickNoteFolder, Task
from app.services.app_usage import WindowsActiveWindowProvider
from app.services.focus_timer import FocusTimerService, decode_focus_targets
from app.storage.database import ScheduleRepository


FEATURE_MIME_TYPE = "application/x-schedule-helper-feature"
NOTE_IDS_MIME_TYPE = "application/x-schedule-helper-note-ids"
FEATURE_ROW_MAX_COLUMNS = 6
DASHBOARD_GRID_COLUMNS = 6
DASHBOARD_GRID_ROW_HEIGHT = 58
DASHBOARD_GRID_GAP = 16
PASTEL_COLOR_PRESETS = ("#f3d9dc", "#f6e6c8", "#dcebd7", "#d9e7f5", "#e7def5")
MONOTONE_COLOR_PRESETS = ("#fafafa", "#e9ecef", "#adb5bd", "#495057", "#111315")


def _start_feature_drag(source: QWidget, feature_key: str) -> None:
    return


def _hidden_reparent_bin_for(widget: QWidget) -> QWidget | None:
    window = widget.window()
    owner = window if isinstance(window, QWidget) and window is not widget else QApplication.instance()
    if owner is None:
        return None
    bin_widget = getattr(owner, "_feature_reparent_bin", None)
    if not isinstance(bin_widget, QWidget):
        bin_widget = QWidget(owner if isinstance(owner, QWidget) else None)
        bin_widget.setObjectName("featureReparentBin")
        bin_widget.setFixedSize(1, 1)
        bin_widget.hide()
        setattr(owner, "_feature_reparent_bin", bin_widget)
    return bin_widget


def _park_widget_for_reparent(widget: QWidget) -> None:
    widget.hide()
    bin_widget = _hidden_reparent_bin_for(widget)
    if bin_widget is not None and widget is not bin_widget:
        widget.setParent(bin_widget)


def _set_window_always_on_top(window: QWidget, enabled: bool) -> None:
    was_visible = window.isVisible()
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
    if was_visible:
        window.show()
        window.raise_()


def _add_always_on_top_checkbox(window: QWidget, row: QHBoxLayout) -> QCheckBox:
    checkbox = QCheckBox("항상 위")
    checkbox.toggled.connect(lambda enabled, target=window: _set_window_always_on_top(target, enabled))
    row.addWidget(checkbox)
    return checkbox


def _decode_note_ids(mime_data: QMimeData) -> list[int]:
    if not mime_data.hasFormat(NOTE_IDS_MIME_TYPE):
        return []
    try:
        payload = bytes(mime_data.data(NOTE_IDS_MIME_TYPE)).decode("utf-8")
        note_ids = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(note_ids, list):
        return []
    decoded: list[int] = []
    for note_id in note_ids:
        try:
            decoded.append(int(note_id))
        except (TypeError, ValueError):
            continue
    return decoded


class FeatureMoveBar(QWidget):
    def __init__(self, feature_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.feature_key = feature_key
        self.drag_start: QPoint | None = None
        self.setObjectName("featureMoveBar")
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            parent = self.parentWidget()
            begin = getattr(parent, "begin_feature_reposition_gesture", None)
            if callable(begin):
                begin(event.globalPosition().toPoint(), self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self.drag_start is None:
            super().mouseMoveEvent(event)
            return
        parent = self.parentWidget()
        update = getattr(parent, "update_feature_reposition_gesture", None)
        if callable(update) and update(event.globalPosition().toPoint(), self):
            event.accept()
            return
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.drag_start = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        parent = self.parentWidget()
        finish = getattr(parent, "finish_feature_reposition_gesture", None)
        if callable(finish) and finish(event.globalPosition().toPoint(), self):
            event.accept()
            return
        super().mouseReleaseEvent(event)


class QuickNoteDragList(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)

    def checked_note_ids(self) -> list[int]:
        note_ids: list[int] = []
        for row in range(self.count()):
            item = self.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            note_id = item.data(Qt.ItemDataRole.UserRole)
            if note_id is not None:
                note_ids.append(int(note_id))
        return note_ids

    def selected_note_ids(self) -> list[int]:
        note_ids: list[int] = []
        for item in self.selectedItems():
            note_id = item.data(Qt.ItemDataRole.UserRole)
            if note_id is not None:
                note_ids.append(int(note_id))
        return note_ids

    def note_ids_for_action(self) -> list[int]:
        note_ids = self.checked_note_ids() or self.selected_note_ids()
        if note_ids:
            return note_ids
        current = self.currentItem()
        if current is None:
            return []
        note_id = current.data(Qt.ItemDataRole.UserRole)
        return [int(note_id)] if note_id is not None else []

    def startDrag(self, supported_actions) -> None:
        note_ids = self.note_ids_for_action()
        if not note_ids:
            return
        mime = QMimeData()
        mime.setData(NOTE_IDS_MIME_TYPE, json.dumps(note_ids).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class QuickNoteFolderDropList(QListWidget):
    def __init__(self, move_callback: Callable[[list[int], int], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.move_callback = move_callback
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(NOTE_IDS_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(NOTE_IDS_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        note_ids = _decode_note_ids(event.mimeData())
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        item = self.itemAt(position)
        folder_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if note_ids and folder_id is not None:
            self.move_callback(note_ids, int(folder_id))
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class ResizeAwareWidget(QWidget):
    def __init__(self, resize_callback: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize_callback = resize_callback

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resize_callback()


class FocusRateRing(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ratio = 1.0
        self.accent_color = "#4f8c6b"
        self.track_color = "#dde6e0"
        self.text_color = "#18201b"
        self.setMinimumSize(72, 72)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        return QSize(104, 104)

    def set_ratio(self, ratio: float) -> None:
        self.ratio = min(1.0, max(0.0, ratio))
        self.update()

    def set_theme(self, accent: str, track: str, text: str) -> None:
        self.accent_color = accent
        self.track_color = track
        self.text_color = text
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - 16
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        pen_width = 8

        track_pen = QPen(QColor(self.track_color), pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        accent_pen = QPen(QColor(self.accent_color), pen_width)
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(accent_pen)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self.ratio))

        painter.setPen(QColor(self.text_color))
        font = painter.font()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{int(self.ratio * 100)}%")


class HeaderBannerWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image_path = ""
        self.pixmap = QPixmap()
        self.accent_color = "#4f8c6b"
        self.border_color = "#dbe5df"
        self.surface_color = "#f3f6f4"
        self.set_banner_height(132)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_banner_image(self, image_path: str) -> None:
        normalized_path = image_path.strip()
        if normalized_path == self.image_path:
            return
        self.image_path = normalized_path
        self.pixmap = QPixmap(normalized_path) if normalized_path and Path(normalized_path).exists() else QPixmap()
        self.update()

    def set_theme(self, accent: str, border: str, surface: str) -> None:
        self.accent_color = accent
        self.border_color = border
        self.surface_color = surface
        self.update()

    def set_banner_height(self, height: int) -> None:
        normalized_height = _normalize_header_banner_height(height)
        self.setMinimumHeight(normalized_height)
        self.setMaximumHeight(16777215)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)

        painter.fillPath(path, QColor(self.surface_color))
        if self.pixmap.isNull():
            accent = QColor(self.accent_color)
            accent.setAlpha(30)
            painter.fillPath(path, accent)
        else:
            target = rect.toRect()
            scaled = self.pixmap.scaled(
                target.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = target.x() + (target.width() - scaled.width()) // 2
            y = target.y() + (target.height() - scaled.height()) // 2
            painter.setClipPath(path)
            painter.drawPixmap(x, y, scaled)
            painter.setClipping(False)

        painter.setPen(QPen(QColor(self.border_color), 1))
        painter.drawPath(path)


class MediaPreviewLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._source_movie: QMovie | None = None
        self.select_callback: Callable[[], None] | None = None
        self.context_callback: Callable[[QWidget, QPoint], None] | None = None
        self._select_press_position: QPoint | None = None
        self.setObjectName("mediaPreviewLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(QSize(96, 120))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def clear_media(self, message: str) -> None:
        self._stop_movie()
        self._source_pixmap = QPixmap()
        self.clear()
        self.setText(message)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_pixmap_source(self, pixmap: QPixmap) -> None:
        self._stop_movie()
        self._source_pixmap = pixmap
        self.setText("")
        self.unsetCursor()
        self._apply_scaled_pixmap()

    def set_movie_source(self, movie: QMovie) -> None:
        self._stop_movie()
        self._source_pixmap = QPixmap()
        self._source_movie = movie
        self.setText("")
        self.unsetCursor()
        self.setMovie(movie)
        self._apply_movie_size()
        movie.start()

    def has_media(self) -> bool:
        return self._source_movie is not None or not self._source_pixmap.isNull()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton and self.context_callback is not None:
            self.context_callback(self, event.position().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.has_media() and self.select_callback is not None:
            self._select_press_position = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._select_press_position is not None
            and not self.has_media()
            and self.select_callback is not None
        ):
            distance = (event.position().toPoint() - self._select_press_position).manhattanLength()
            self._select_press_position = None
            if distance < QApplication.startDragDistance():
                self.select_callback()
                event.accept()
                return
        self._select_press_position = None
        super().mouseReleaseEvent(event)

    def _stop_movie(self) -> None:
        movie = self._source_movie
        if movie is not None:
            movie.stop()
        self._source_movie = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._source_movie is not None:
            self._apply_movie_size()
        elif not self._source_pixmap.isNull():
            self._apply_scaled_pixmap()

    def _available_size(self) -> QSize:
        size = self.contentsRect().size()
        return QSize(max(1, size.width()), max(1, size.height()))

    def _apply_scaled_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(
            self._available_size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def _apply_movie_size(self) -> None:
        movie = self._source_movie
        if movie is None:
            return
        source_size = movie.frameRect().size()
        if source_size.isEmpty() and not movie.currentPixmap().isNull():
            source_size = movie.currentPixmap().size()
        if source_size.isEmpty():
            movie.setScaledSize(self._available_size())
            return
        movie.setScaledSize(source_size.scaled(self._available_size(), Qt.AspectRatioMode.KeepAspectRatio))


class SwitchCheckBox(QCheckBox):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)
        self.toggled.connect(lambda _checked=False: self.update())

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(max(64, 54 + text_width), 28)

    def paintEvent(self, event) -> None:
        event.accept()
        preferences = _preferences_from_widget(self)
        palette = _resolved_theme_palette(preferences)
        accent = _normalize_accent_color(getattr(preferences, "accent_color", "#4f8c6b"))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        checked = self.isChecked()
        enabled = self.isEnabled()
        track_rect = QRectF(0, 3, 40, 22)
        track_color = accent if checked else palette["track"]
        if not enabled:
            track_color = palette["border_2"]
        painter.setPen(QPen(QColor(accent if checked else palette["border"]), 1))
        painter.setBrush(QColor(track_color))
        painter.drawRoundedRect(track_rect, 11, 11)

        knob_x = 20 if checked else 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette["surface"] if enabled else palette["disabled"]))
        painter.drawEllipse(QRectF(knob_x, 5, 18, 18))

        text_rect = QRectF(52, 0, max(0, self.width() - 52), self.height())
        painter.setPen(QColor(palette["text"] if enabled else palette["disabled"]))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class DashboardGridGuideOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview_rect = QRectF()
        self.setObjectName("dashboardGridGuideOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_preview_rect(self, rect: QRectF) -> None:
        self.preview_rect = rect
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        preferences = _preferences_from_widget(self)
        palette = _resolved_theme_palette(preferences)
        accent = _normalize_accent_color(getattr(preferences, "accent_color", "#4f8c6b"))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = max(1, self.width())
        height = max(1, self.height())
        usable_width = max(1, width - DASHBOARD_GRID_GAP * (DASHBOARD_GRID_COLUMNS - 1))
        column_width = usable_width / DASHBOARD_GRID_COLUMNS

        guide_color = QColor(accent)
        guide_color.setAlpha(72)
        guide_pen = QPen(guide_color, 1)
        guide_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(guide_pen)
        for column in range(DASHBOARD_GRID_COLUMNS + 1):
            x = column * (column_width + DASHBOARD_GRID_GAP)
            if column == DASHBOARD_GRID_COLUMNS:
                x = width - 1
            painter.drawLine(int(round(x)), 0, int(round(x)), height)

        row_color = QColor(palette["border"])
        row_color.setAlpha(150)
        row_pen = QPen(row_color, 1)
        row_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(row_pen)
        row_step = DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP
        y = DASHBOARD_GRID_ROW_HEIGHT
        while y < height:
            painter.drawLine(0, int(y), width, int(y))
            y += row_step

        if self.preview_rect.isValid() and not self.preview_rect.isNull():
            highlight = QColor(accent)
            highlight.setAlpha(34)
            painter.setBrush(highlight)
            painter.setPen(QPen(QColor(accent), 2))
            painter.drawRoundedRect(self.preview_rect.adjusted(1, 1, -1, -1), 14, 14)


class DraggableFeatureBox(QWidget):
    def __init__(
        self,
        feature_key: str,
        title: str,
        content: QWidget,
        swap_callback: Callable[[str, str, str], None],
        expand_content: bool = True,
        widget_callback: Callable[[str], None] | None = None,
        hide_callback: Callable[[str], None] | None = None,
        show_title_bar: bool = True,
        content_drag_enabled: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.feature_key = feature_key
        self.swap_callback = swap_callback
        self.widget_callback = widget_callback
        self.hide_callback = hide_callback
        self.content_drag_enabled = content_drag_enabled
        self.resize_callback: Callable[[str, int], None] | None = None
        self.span_provider: Callable[[str], int] | None = None
        self.height_callback: Callable[[str, int], None] | None = None
        self.height_provider: Callable[[str], int] | None = None
        self.panel_drag_start: QPoint | None = None
        self.panel_drag_active = False
        self.panel_drag_source: QWidget | None = None
        self.resizing_span = False
        self.resizing_height = False
        self.resize_start_x = 0
        self.resize_start_width = 0
        self.resize_start_y = 0
        self.resize_start_height = 0
        self.setObjectName("featureBox")
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6 if show_title_bar else 0)

        self.title_label: QLabel | None = None
        if show_title_bar:
            bar = FeatureMoveBar(feature_key, self)
            bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            bar.customContextMenuRequested.connect(self.show_feature_context_menu)
            bar.installEventFilter(self)
            bar_layout = QHBoxLayout(bar)
            bar_layout.setContentsMargins(8, 0, 8, 2)
            bar_layout.setSpacing(6)
            title_label = QLabel(title)
            self.title_label = title_label
            title_label.setObjectName("featureMoveTitle")
            title_label.setToolTip(title)
            title_label.setMinimumWidth(min(170, max(72, title_label.fontMetrics().horizontalAdvance(title) + 16)))
            title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            bar_layout.addWidget(title_label)
            bar_layout.addStretch(1)
            layout.addWidget(bar)

        self._relax_horizontal_minimums(content)
        content.setAcceptDrops(True)
        self._install_panel_event_filters(content)
        layout.addWidget(content, 1 if expand_content else 0)

    def set_title(self, title: str) -> None:
        if self.title_label is None:
            return
        title = title.strip() or "기능"
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.title_label.setMinimumWidth(min(260, max(72, self.title_label.fontMetrics().horizontalAdvance(title) + 16)))

    def _install_panel_event_filters(self, root: QWidget) -> None:
        root.setMouseTracking(True)
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def _relax_horizontal_minimums(self, root: QWidget) -> None:
        for widget in (root, *root.findChildren(QWidget)):
            widget.setMinimumWidth(0)

    def eventFilter(self, watched, event) -> bool:
        if isinstance(watched, QWidget):
            event_type = event.type()
            if event_type in {
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
                QEvent.Type.Drop,
            }:
                return self._handle_filtered_drop_event(watched, event)
            if event_type == QEvent.Type.MouseButtonPress:
                return self._handle_filtered_mouse_press(watched, event)
            if event_type == QEvent.Type.MouseMove:
                return self._handle_filtered_mouse_move(watched, event)
            if event_type == QEvent.Type.MouseButtonRelease:
                return self._handle_filtered_mouse_release(watched, event)
            if event_type == QEvent.Type.Leave and self._should_reset_cursor(watched):
                watched.unsetCursor()
        return super().eventFilter(watched, event)

    def _handle_filtered_drop_event(self, watched: QWidget, event) -> bool:
        source_key = self._source_key(event)
        if not source_key or source_key == self.feature_key:
            return False
        if event.type() in {QEvent.Type.DragEnter, QEvent.Type.DragMove}:
            event.acceptProposedAction()
            return True
        drop_position = self._map_event_position(watched, event)
        placement = self._drop_placement(drop_position)
        self.swap_callback(source_key, self.feature_key, placement)
        event.acceptProposedAction()
        return True

    def _handle_filtered_mouse_press(self, watched: QWidget, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        box_position = self._map_event_position(watched, event)
        if self._is_height_resize_edge(box_position) and self.height_callback is not None:
            self._begin_height_resize(event.globalPosition().toPoint().y())
            event.accept()
            return True
        if isinstance(watched, FeatureMoveBar) or self._is_interactive_child(watched):
            return False
        if self._is_resize_edge(box_position) and self.resize_callback is not None:
            self._begin_span_resize(event.globalPosition().toPoint().x())
            event.accept()
            return True
        if not self.content_drag_enabled:
            return False
        self.begin_feature_reposition_gesture(event.globalPosition().toPoint(), watched)
        watched.setCursor(Qt.CursorShape.ClosedHandCursor)
        return False

    def _handle_filtered_mouse_move(self, watched: QWidget, event) -> bool:
        box_position = self._map_event_position(watched, event)
        if self.resizing_span:
            self._resize_span_from_global_x(event.globalPosition().toPoint().x())
            event.accept()
            return True
        if self.resizing_height:
            self._resize_height_from_global_y(event.globalPosition().toPoint().y())
            event.accept()
            return True
        if (
            self.content_drag_enabled
            and self.panel_drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self.update_feature_reposition_gesture(event.globalPosition().toPoint(), watched)
        ):
            event.accept()
            return True
        if self._is_height_resize_edge(box_position) and self.height_callback is not None:
            watched.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._is_resize_edge(box_position) and self.resize_callback is not None:
            watched.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._should_reset_cursor(watched):
            watched.unsetCursor()
        return False

    def _handle_filtered_mouse_release(self, watched: QWidget, event) -> bool:
        if self.finish_feature_reposition_gesture(event.globalPosition().toPoint(), watched):
            event.accept()
            return True
        self.panel_drag_start = None
        if self.resizing_span:
            self.resizing_span = False
            watched.unsetCursor()
            event.accept()
            return True
        if self.resizing_height:
            self.resizing_height = False
            watched.unsetCursor()
            event.accept()
            return True
        if self._should_reset_cursor(watched):
            watched.unsetCursor()
        return False

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.height_callback is not None
            and self._is_height_resize_edge(event.position().toPoint())
        ):
            self._begin_height_resize(event.globalPosition().toPoint().y())
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.resize_callback is not None
            and self._is_resize_edge(event.position().toPoint())
        ):
            self._begin_span_resize(event.globalPosition().toPoint().x())
            event.accept()
            return
        if self.content_drag_enabled:
            self.begin_feature_reposition_gesture(event.globalPosition().toPoint(), self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.resizing_span:
            self._resize_span_from_global_x(event.globalPosition().toPoint().x())
            event.accept()
            return
        if self.resizing_height:
            self._resize_height_from_global_y(event.globalPosition().toPoint().y())
            event.accept()
            return
        if (
            self.content_drag_enabled
            and self.panel_drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self.update_feature_reposition_gesture(event.globalPosition().toPoint(), self)
        ):
            event.accept()
            return
        if self._is_height_resize_edge(event.position().toPoint()) and self.height_callback is not None:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._is_resize_edge(event.position().toPoint()) and self.resize_callback is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.finish_feature_reposition_gesture(event.globalPosition().toPoint(), self):
            event.accept()
            return
        self.panel_drag_start = None
        if self.resizing_span:
            self.resizing_span = False
            self.unsetCursor()
            event.accept()
            return
        if self.resizing_height:
            self.resizing_height = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _map_event_position(self, watched: QWidget, event) -> QPoint:
        point = event.position().toPoint()
        return watched.mapTo(self, point) if watched is not self else point

    def _drop_placement(self, point: QPoint) -> str:
        width = max(1, self.width())
        height = max(1, self.height())
        x_ratio = point.x() / width
        y_ratio = point.y() / height
        if x_ratio <= 0.28:
            return "left"
        if x_ratio >= 0.72:
            return "right"
        return "before" if y_ratio < 0.45 else "after"

    def _is_resize_edge(self, point: QPoint) -> bool:
        return self.width() >= 160 and point.x() >= self.width() - 12

    def _is_height_resize_edge(self, point: QPoint) -> bool:
        return self.height() >= 96 and point.y() >= self.height() - 20

    def _begin_span_resize(self, global_x: int) -> None:
        self.resizing_span = True
        self.panel_drag_start = None
        self.panel_drag_active = False
        self.panel_drag_source = None
        self.resize_start_x = global_x
        self.resize_start_width = self._current_width()
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def _begin_height_resize(self, global_y: int) -> None:
        self.resizing_height = True
        self.panel_drag_start = None
        self.panel_drag_active = False
        self.panel_drag_source = None
        self.resize_start_y = global_y
        self.resize_start_height = self._current_height()
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def begin_feature_reposition_gesture(self, global_position: QPoint, source: QWidget | None = None) -> None:
        self.panel_drag_start = global_position
        self.panel_drag_active = False
        self.panel_drag_source = source or self

    def update_feature_reposition_gesture(self, global_position: QPoint, source: QWidget | None = None) -> bool:
        if self.panel_drag_start is None:
            return False
        if self.resizing_span or self.resizing_height:
            return False
        if not self.panel_drag_active:
            distance = (global_position - self.panel_drag_start).manhattanLength()
            if distance < QApplication.startDragDistance():
                return False
            self.panel_drag_active = True
            drag_source = source or self.panel_drag_source or self
            drag_source.setCursor(Qt.CursorShape.ClosedHandCursor)
        controller = self._feature_drag_controller()
        preview = getattr(controller, "preview_feature_reposition", None)
        if callable(preview):
            preview(self.feature_key, global_position)
        return True

    def finish_feature_reposition_gesture(self, global_position: QPoint, source: QWidget | None = None) -> bool:
        was_active = self.panel_drag_active
        self.panel_drag_start = None
        self.panel_drag_active = False
        drag_source = source or self.panel_drag_source
        self.panel_drag_source = None
        if isinstance(drag_source, QWidget):
            drag_source.unsetCursor()
        if not was_active:
            return False
        controller = self._feature_drag_controller()
        finish = getattr(controller, "finish_feature_reposition", None)
        if callable(finish):
            finish(self.feature_key, global_position)
        return True

    def _feature_drag_controller(self) -> QWidget | None:
        window = self.window()
        return window if isinstance(window, QWidget) else None

    def _resize_span_from_global_x(self, global_x: int) -> None:
        if self.resize_callback is None:
            return
        new_width = max(120, self.resize_start_width + (global_x - self.resize_start_x))
        if abs(new_width - self._current_width()) >= 2:
            self.resize_callback(self.feature_key, int(new_width))

    def _resize_height_from_global_y(self, global_y: int) -> None:
        if self.height_callback is None:
            return
        new_height = max(80, self.resize_start_height + (global_y - self.resize_start_y))
        if abs(new_height - self._current_height()) >= 2:
            self.height_callback(self.feature_key, int(new_height))

    def _current_span(self) -> int:
        if self.span_provider is None:
            return 1
        return min(3, max(1, int(self.span_provider(self.feature_key))))

    def _current_height(self) -> int:
        if self.height_provider is not None:
            return max(80, int(self.height_provider(self.feature_key)))
        return max(80, self.height())

    def _current_width(self) -> int:
        return max(120, self.width())

    def _grid_column_width(self) -> float:
        widget = self.parentWidget()
        while widget is not None:
            if widget.objectName() == "featureGrid":
                spacing = 0
                layout = widget.layout()
                if isinstance(layout, QGridLayout):
                    spacing = layout.horizontalSpacing() * 2
                return max(90.0, (widget.width() - spacing) / 3.0)
            widget = widget.parentWidget()
        return max(90.0, self.window().width() / 3.0 if isinstance(self.window(), QWidget) else 160.0)

    def _is_interactive_child(self, widget: QWidget) -> bool:
        cursor: QWidget | None = widget
        while cursor is not None and cursor is not self:
            if isinstance(
                cursor,
                (
                    QAbstractItemView,
                    QAbstractSpinBox,
                    QCheckBox,
                    QComboBox,
                    QLineEdit,
                    QPlainTextEdit,
                    QPushButton,
                    QTextEdit,
                ),
            ):
                return True
            cursor = cursor.parentWidget()
        return False

    def _should_reset_cursor(self, widget: QWidget) -> bool:
        return not isinstance(widget, FeatureMoveBar) and not self._is_interactive_child(widget)

    def show_feature_context_menu(self, position: QPoint) -> None:
        if self.widget_callback is None and self.hide_callback is None:
            return
        source = self.sender()
        source_widget = source if isinstance(source, QWidget) else self
        menu = QMenu(source_widget)
        if self.widget_callback is not None:
            widget_action = menu.addAction("새창으로 열기")
            widget_action.triggered.connect(lambda _checked=False: self.widget_callback(self.feature_key))
        if self.hide_callback is not None:
            if not menu.isEmpty():
                menu.addSeparator()
            hide_action = menu.addAction("메인창에서 숨기기")
            hide_action.triggered.connect(lambda _checked=False: self.hide_callback(self.feature_key))
        menu.exec(source_widget.mapToGlobal(position))

    def dragEnterEvent(self, event) -> None:
        source_key = self._source_key(event)
        if source_key and source_key != self.feature_key:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        source_key = self._source_key(event)
        if source_key and source_key != self.feature_key:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        source_key = self._source_key(event)
        if not source_key or source_key == self.feature_key:
            return
        drop_position = event.position().toPoint()
        placement = self._drop_placement(drop_position)
        self.swap_callback(source_key, self.feature_key, placement)
        event.acceptProposedAction()

    def _source_key(self, event) -> str:
        mime = event.mimeData()
        if not mime.hasFormat(FEATURE_MIME_TYPE):
            return ""
        return bytes(mime.data(FEATURE_MIME_TYPE)).decode("utf-8")


class FeatureCell(QWidget):
    def __init__(self, feature_key: str, feature_box: DraggableFeatureBox, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.feature_key = feature_key
        self.feature_box = feature_box
        self.panel_height = 0
        self.panel_width = 0
        self.setObjectName("featureCell")
        self.setAcceptDrops(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(feature_box, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def set_panel_height(self, height: int) -> None:
        normalized_height = max(80, int(height))
        self.panel_height = normalized_height
        self.setMinimumHeight(normalized_height)
        self.setMaximumHeight(normalized_height)
        self.feature_box.setMinimumHeight(normalized_height)
        self.feature_box.setMaximumHeight(normalized_height)

    def set_panel_width(self, width: int, fixed: bool = True) -> None:
        normalized_width = max(120, int(width))
        self.panel_width = normalized_width
        self.setMinimumWidth(min(normalized_width, 360))
        self.setMaximumWidth(normalized_width if fixed else 16777215)
        self.feature_box.setMinimumWidth(0)
        self.feature_box.setMaximumWidth(normalized_width if fixed else 16777215)
        alignment = Qt.AlignmentFlag.AlignTop
        if fixed:
            alignment |= Qt.AlignmentFlag.AlignHCenter
        self.layout().setAlignment(self.feature_box, alignment)
        self.feature_box.updateGeometry()
        self.updateGeometry()

    def detach_feature_box(self) -> None:
        self.feature_box.hide()
        self.layout().removeWidget(self.feature_box)
        self.setMaximumWidth(16777215)
        self.feature_box.setMaximumWidth(16777215)
        _park_widget_for_reparent(self.feature_box)

    def dragEnterEvent(self, event) -> None:
        if self._source_key(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._source_key(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        source_key = self._source_key(event)
        if not source_key or source_key == self.feature_key:
            return
        drop_position = event.position().toPoint()
        placement = self.feature_box._drop_placement(drop_position)
        self.feature_box.swap_callback(source_key, self.feature_key, placement)
        event.acceptProposedAction()

    def _source_key(self, event) -> str:
        mime = event.mimeData()
        if not mime.hasFormat(FEATURE_MIME_TYPE):
            return ""
        return bytes(mime.data(FEATURE_MIME_TYPE)).decode("utf-8")


class FeatureColumn(QWidget):
    def __init__(
        self,
        items: list[str],
        drop_callback: Callable[[str, str, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.items = items
        self.drop_callback = drop_callback
        self.setObjectName("featureColumn")
        self.setAcceptDrops(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.column_layout = QVBoxLayout(self)
        self.column_layout.setContentsMargins(0, 0, 0, 0)
        self.column_layout.setSpacing(14)

    def add_cell(self, cell: FeatureCell) -> None:
        self.column_layout.addWidget(cell, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

    def finish(self) -> None:
        self.column_layout.addStretch(1)

    def detach_feature_boxes(self) -> None:
        while self.column_layout.count():
            item = self.column_layout.takeAt(0)
            widget = item.widget()
            if isinstance(widget, FeatureCell):
                widget.detach_feature_box()
                widget.hide()
                _park_widget_for_reparent(widget)
                widget.deleteLater()
            elif widget is not None:
                widget.hide()
                _park_widget_for_reparent(widget)
                widget.deleteLater()

    def dragEnterEvent(self, event) -> None:
        if self._source_key(event) and self.items:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._source_key(event) and self.items:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        source_key = self._source_key(event)
        if not source_key or not self.items:
            return
        target_key = self.items[-1]
        if source_key == target_key:
            return
        self.drop_callback(source_key, target_key, "after")
        event.acceptProposedAction()

    def _source_key(self, event) -> str:
        mime = event.mimeData()
        if not mime.hasFormat(FEATURE_MIME_TYPE):
            return ""
        return bytes(mime.data(FEATURE_MIME_TYPE)).decode("utf-8")


class FeatureColumnDropZone(QWidget):
    def __init__(
        self,
        column_key: str,
        title: str,
        drop_callback: Callable[[str, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.column_key = column_key
        self.drop_callback = drop_callback
        self.setObjectName("columnDropZone")
        self.setAcceptDrops(True)
        self.setMinimumSize(96, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        label = QLabel(f"{title}\n여기에 놓기")
        label.setObjectName("columnDropZoneLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(1)

    def dragEnterEvent(self, event) -> None:
        if self._source_key(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._source_key(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        source_key = self._source_key(event)
        if not source_key:
            return
        self.drop_callback(source_key, self.column_key)
        event.acceptProposedAction()

    def _source_key(self, event) -> str:
        mime = event.mimeData()
        if not mime.hasFormat(FEATURE_MIME_TYPE):
            return ""
        return bytes(mime.data(FEATURE_MIME_TYPE)).decode("utf-8")


class RichNoteEditor(QWidget):
    def __init__(self, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.font_combo = QFontComboBox()
        _stabilize_control(self.font_combo, 120)
        self.font_combo.currentFontChanged.connect(lambda font: self.text_edit.setCurrentFont(font))
        toolbar.addWidget(self.font_combo, 1)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 72)
        self.size_spin.setValue(12)
        self.size_spin.setSuffix("pt")
        _stabilize_control(self.size_spin, 78)
        self.size_spin.valueChanged.connect(lambda size: self.text_edit.setFontPointSize(float(size)))
        toolbar.addWidget(self.size_spin)

        self.italic_button = QPushButton("I")
        self.italic_button.setCheckable(True)
        _stabilize_control(self.italic_button, 38)
        self.italic_button.setMaximumWidth(42)
        self.italic_button.clicked.connect(lambda checked: self.text_edit.setFontItalic(checked))
        toolbar.addWidget(self.italic_button)

        self.underline_button = QPushButton("U")
        self.underline_button.setCheckable(True)
        _stabilize_control(self.underline_button, 38)
        self.underline_button.setMaximumWidth(42)
        self.underline_button.clicked.connect(lambda checked: self.text_edit.setFontUnderline(checked))
        toolbar.addWidget(self.underline_button)

        color_button = QPushButton("색")
        _stabilize_control(color_button, 48)
        color_button.setMaximumWidth(52)
        color_button.clicked.connect(self.choose_text_color)
        toolbar.addWidget(color_button)

        image_button = QPushButton("이미지")
        _stabilize_control(image_button, 64)
        image_button.setMaximumWidth(76)
        image_button.clicked.connect(self.insert_image)
        toolbar.addWidget(image_button)

        self.image_width_spin = QSpinBox()
        self.image_width_spin.setRange(80, 1200)
        self.image_width_spin.setValue(360)
        self.image_width_spin.setSuffix("px")
        _stabilize_control(self.image_width_spin, 88)
        toolbar.addWidget(self.image_width_spin)

        resize_button = QPushButton("적용")
        _stabilize_control(resize_button, 58)
        resize_button.setMaximumWidth(66)
        resize_button.clicked.connect(self.resize_current_image)
        toolbar.addWidget(resize_button)
        layout.addLayout(toolbar)

        self.text_edit = QTextEdit()
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setMinimumHeight(120)
        layout.addWidget(self.text_edit, 1)

    def set_content(self, plain_text: str, content_html: str = "") -> None:
        if content_html.strip():
            self.text_edit.setHtml(content_html)
        else:
            self.text_edit.setPlainText(plain_text)

    def to_plain_text(self) -> str:
        return self.text_edit.toPlainText().strip()

    def to_html(self) -> str:
        return self.text_edit.toHtml()

    def has_content(self) -> bool:
        return bool(self.to_plain_text()) or "<img" in self.to_html().casefold()

    def choose_text_color(self) -> None:
        color = QColorDialog.getColor(self.text_edit.textColor(), self, "글자 색")
        if color.isValid():
            self.text_edit.setTextColor(color)

    def insert_image(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "이미지 삽입",
            "",
            "이미지 파일 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;모든 파일 (*)",
        )
        if not file_path:
            return
        try:
            stored_path = self.repository.copy_inline_note_image(file_path)
        except OSError as exc:
            QMessageBox.warning(self, "이미지 삽입", f"이미지를 복사할 수 없습니다.\n{exc}")
            return
        self.insert_image_path(stored_path, self.image_width_spin.value())

    def insert_image_path(self, image_path: str, width: int) -> None:
        pixmap = QPixmap(image_path)
        image_format = QTextImageFormat()
        image_format.setName(QUrl.fromLocalFile(image_path).toString())
        image_format.setWidth(float(width))
        if not pixmap.isNull() and pixmap.width() > 0:
            image_format.setHeight(float(width) * pixmap.height() / pixmap.width())
        cursor = self.text_edit.textCursor()
        cursor.insertImage(image_format)
        cursor.insertBlock()
        self.text_edit.setTextCursor(cursor)

    def resize_current_image(self) -> None:
        cursor = self.text_edit.textCursor()
        image_cursor, image_format = self._image_cursor_near(cursor)
        if image_cursor is None or image_format is None:
            return

        width = self.image_width_spin.value()
        image_format.setWidth(float(width))
        local_path = QUrl(image_format.name()).toLocalFile()
        pixmap = QPixmap(local_path) if local_path else QPixmap()
        if not pixmap.isNull() and pixmap.width() > 0:
            image_format.setHeight(float(width) * pixmap.height() / pixmap.width())
        image_cursor.setCharFormat(image_format)

    def _image_cursor_near(self, cursor: QTextCursor) -> tuple[QTextCursor | None, QTextImageFormat | None]:
        image_format = cursor.charFormat().toImageFormat()
        if image_format.isValid():
            return QTextCursor(cursor), image_format

        for steps in range(0, 6):
            left_cursor = QTextCursor(cursor)
            if steps and not left_cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, steps):
                continue
            if left_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1):
                image_format = left_cursor.charFormat().toImageFormat()
                if image_format.isValid():
                    return left_cursor, image_format

            right_cursor = QTextCursor(cursor)
            if steps and not right_cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.MoveAnchor,
                steps,
            ):
                continue
            if right_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1):
                image_format = right_cursor.charFormat().toImageFormat()
                if image_format.isValid():
                    return right_cursor, image_format

        return None, None


class MainWindow(QMainWindow):
    def __init__(self, repository: ScheduleRepository) -> None:
        super().__init__()
        self.repository = repository
        self.window_provider: WindowsActiveWindowProvider | None = None
        self.focus_timer: FocusTimerService | None = None
        self.focus_tick_timer = QTimer(self)
        self.focus_tick_timer.setInterval(1000)
        self.focus_tick_timer.timeout.connect(self.on_focus_tick)
        self.current_datetime_timer = QTimer(self)
        self.current_datetime_timer.setInterval(1000)
        self.current_datetime_timer.timeout.connect(self.update_current_datetime_display)
        self.selected_task_id: int | None = None
        self.compact_auto = False
        self.changing_mode = False
        self.closing = False
        self.break_until: datetime | None = None
        self.preferences = self.repository.get_preferences()
        if self.preferences.show_today_flow_panel:
            self.preferences.show_today_flow_panel = False
            self.preferences.show_today_timeline_inline = True
            self.preferences = self.repository.save_preferences(self.preferences)
        self.pending_quick_note_attachments: list[str] = []
        self.pomodoro_tick_timer = QTimer(self)
        self.pomodoro_tick_timer.setInterval(1000)
        self.pomodoro_tick_timer.timeout.connect(self.on_pomodoro_tick)
        self.pomodoro_mode = "focus"
        self.pomodoro_remaining_seconds = 0
        self.pomodoro_total_seconds = 0
        self.pomodoro_paused = False
        self.quick_note_folders: list[QuickNoteFolder] = []
        self.feature_widget_windows: dict[str, QDialog] = {}
        self.quick_note_detail_windows: dict[int, QDialog] = {}
        self.quick_note_folder_notes_window: QDialog | None = None
        self.compact_widget_window: QDialog | None = None
        self.startup_refresh_pending = False

        self.setWindowTitle(self.preferences.app_title)
        self.setMinimumSize(QSize(430, 320))
        self.setStatusBar(QStatusBar(self))
        self._initialize_focus_timer()
        self._build_ui()
        self.restore_last_window_size()
        self.apply_preferences(refresh_content=False)
        self.restore_last_layout_state()
        self.schedule_startup_refresh()

    def _initialize_focus_timer(self) -> None:
        try:
            self.window_provider = WindowsActiveWindowProvider()
        except RuntimeError:
            self.window_provider = None
        self.focus_timer = FocusTimerService(self.repository, self.window_provider, idle_cutoff_seconds=60)

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.full_page = self._build_full_page()
        self.compact_page = self._build_compact_page()
        self.stack.addWidget(self.full_page)
        self.stack.addWidget(self.compact_page)
        self.setCentralWidget(self.stack)

    def _build_full_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("appShell")
        page.setMinimumWidth(1080)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_app_bar())

        body = QWidget()
        body.setObjectName("appBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(30, 26, 30, 30)
        workspace_layout.setSpacing(16)
        self.workspace_layout = workspace_layout

        self.feature_boxes: dict[str, DraggableFeatureBox] = {}
        self.feature_grid_order: list[str] = []
        self.feature_grid_spans: dict[str, int] = {}
        self.feature_layout_rows: list[dict[str, object]] = []
        self.feature_dashboard_items: list[dict[str, object]] = []
        self.feature_row_splitters: list[QSplitter] = []
        self.feature_cells: dict[str, FeatureCell] = {}
        self.header_banner_widget = HeaderBannerWidget()
        self.header_banner_panel = self._wrap_feature("header_banner", "배너", self.header_banner_widget)

        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setObjectName("bodySplitter")
        self.body_splitter.setChildrenCollapsible(False)

        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter.setObjectName("leftFeatureSplitter")
        self.left_splitter.setChildrenCollapsible(False)
        self.datetime_panel = self._wrap_feature("datetime", "날짜/시간", self._build_datetime_panel())
        self.left_splitter.addWidget(self.datetime_panel)
        self.focus_panel = self._wrap_feature("focus", "집중", self._build_focus_panel())
        self.left_splitter.addWidget(self.focus_panel)
        self.pomodoro_panel = self._wrap_feature("pomodoro", "뽀모도로", self._build_pomodoro_panel())
        self.left_splitter.addWidget(self.pomodoro_panel)
        self.today_checklist_widget = TodayChecklistWidget(self.repository, self.refresh_today, self, show_title=False)
        self.today_checklist_panel = self._wrap_feature("today_checklist", "오늘 체크리스트", self.today_checklist_widget)
        self.left_splitter.addWidget(self.today_checklist_panel)

        self.lower_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.lower_splitter.setObjectName("lowerFeatureSplitter")
        self.lower_splitter.setChildrenCollapsible(False)
        self.memo_panel = self._wrap_feature("quick_memo", "빠른 메모", self._build_memo_panel())
        self.lower_splitter.addWidget(self.memo_panel)
        self.lower_splitter.setStretchFactor(0, 1)
        self.lower_splitter.setSizes([640])
        self.left_splitter.addWidget(self.lower_splitter)

        self.left_splitter.setStretchFactor(0, 0)
        self.left_splitter.setStretchFactor(1, 3)
        self.left_splitter.setStretchFactor(2, 1)
        self.left_splitter.setStretchFactor(3, 2)
        self.left_splitter.setStretchFactor(4, 4)
        self.left_splitter.setSizes([96, 330, 130, 220, 360])
        self.body_splitter.addWidget(self.left_splitter)

        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self.center_splitter.setObjectName("centerFeatureSplitter")
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.addWidget(self.header_banner_panel)

        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setObjectName("rightFeatureSplitter")
        self.right_splitter.setChildrenCollapsible(False)

        self.inline_timeline_widget = TodayTimelineWidget(
            self.repository,
            self,
            title_text="",
            on_changed=self.refresh_today,
            on_focus_task=self.load_task_by_id,
            on_delete_focus_session=self.delete_focus_session_by_id,
            show_waiting_panel=self.preferences.show_today_timeline_waiting_panel,
            waiting_panel_pinned=self.preferences.show_today_timeline_waiting_pinned,
            on_waiting_pinned_changed=self.set_today_timeline_waiting_pinned,
        )
        self.inline_timeline_widget.setMinimumWidth(0)
        self.inline_timeline_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.timeline_panel = self._wrap_feature("today_timeline", "오늘 시간표", self.inline_timeline_widget)
        self.center_splitter.addWidget(self.timeline_panel)
        self.center_splitter.setStretchFactor(0, 0)
        self.center_splitter.setStretchFactor(1, 1)
        self.center_splitter.setSizes([180, 620])
        self.body_splitter.addWidget(self.center_splitter)

        self.link_favorites_panel = self._wrap_feature("link_favorites", "즐겨찾기", self._build_link_favorites_panel())
        self.right_splitter.addWidget(self.link_favorites_panel)
        self.media_panel = self._wrap_feature("media_panel", "이미지", self._build_media_panel())
        self.right_splitter.addWidget(self.media_panel)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([320, 320])
        self.body_splitter.addWidget(self.right_splitter)
        self.body_splitter.setStretchFactor(0, 2)
        self.body_splitter.setStretchFactor(1, 3)
        self.body_splitter.setStretchFactor(2, 2)
        self.body_splitter.setSizes([560, 760, 420])
        self.feature_grid_container = QWidget()
        self.feature_grid_container.setObjectName("featureGrid")
        self.feature_dashboard_layout = QGridLayout(self.feature_grid_container)
        self.feature_dashboard_layout.setContentsMargins(0, 0, 0, 0)
        self.feature_dashboard_layout.setHorizontalSpacing(DASHBOARD_GRID_GAP)
        self.feature_dashboard_layout.setVerticalSpacing(DASHBOARD_GRID_GAP)
        for column in range(DASHBOARD_GRID_COLUMNS):
            self.feature_dashboard_layout.setColumnStretch(column, 1)
            self.feature_dashboard_layout.setColumnMinimumWidth(column, 52)
        self.dashboard_guide_overlay = DashboardGridGuideOverlay(self.feature_grid_container)
        workspace_layout.addWidget(self.feature_grid_container, 1)
        self._apply_feature_layout(self.default_layout_state().get("layout"))

        body_layout.addWidget(workspace, 1)
        layout.addWidget(body, 1)

        scroll = QScrollArea()
        scroll.setObjectName("fullScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.full_scroll_area = scroll
        return scroll

    def _build_app_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("appChromeBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        dots = QWidget()
        dots_layout = QHBoxLayout(dots)
        dots_layout.setContentsMargins(0, 0, 0, 0)
        dots_layout.setSpacing(7)
        for _index in range(3):
            dot = QFrame()
            dot.setObjectName("windowDot")
            dot.setFixedSize(11, 11)
            dots_layout.addWidget(dot)
        layout.addWidget(dots)

        self.chrome_title_label = QLabel(self.preferences.app_title or "Schedule Helper")
        self.chrome_title_label.setObjectName("chromeTitle")
        self.chrome_title_label.setMinimumWidth(0)
        layout.addWidget(self.chrome_title_label)
        self.header_focus_card = self._build_header_focus_card()
        layout.addWidget(self.header_focus_card)
        layout.addStretch(1)

        theme_segment = QWidget()
        theme_segment.setObjectName("themeSegment")
        theme_layout = QHBoxLayout(theme_segment)
        theme_layout.setContentsMargins(3, 3, 3, 3)
        theme_layout.setSpacing(3)
        self.light_theme_button = QPushButton("라이트")
        self.light_theme_button.setObjectName("segmentButton")
        self.light_theme_button.setCheckable(True)
        _stabilize_control(self.light_theme_button, 58)
        self.light_theme_button.clicked.connect(lambda _checked=False: self.set_appearance_theme("light"))
        self.dark_theme_button = QPushButton("다크")
        self.dark_theme_button.setObjectName("segmentButton")
        self.dark_theme_button.setCheckable(True)
        _stabilize_control(self.dark_theme_button, 50)
        self.dark_theme_button.clicked.connect(lambda _checked=False: self.set_appearance_theme("dark"))
        theme_layout.addWidget(self.light_theme_button)
        theme_layout.addWidget(self.dark_theme_button)
        layout.addWidget(theme_segment)

        date_review_button = QPushButton("날짜별 보기")
        date_review_button.setObjectName("topBarButton")
        _stabilize_control(date_review_button, 106)
        date_review_button.clicked.connect(self.show_date_review_window)
        layout.addWidget(date_review_button)

        task_folder_button = QPushButton("할 일 폴더")
        task_folder_button.setObjectName("topBarButton")
        _stabilize_control(task_folder_button, 104)
        task_folder_button.clicked.connect(self.show_task_folder_settings)
        layout.addWidget(task_folder_button)

        settings_button = QPushButton("설정")
        settings_button.setObjectName("topBarButton")
        _stabilize_control(settings_button, 78)
        settings_button.clicked.connect(self.show_settings_window)
        layout.addWidget(settings_button)

        self.main_always_on_top_check = QCheckBox("항상 위")
        self.main_always_on_top_check.setObjectName("pinCheck")
        self.main_always_on_top_check.setChecked(self.preferences.main_always_on_top)
        self.main_always_on_top_check.toggled.connect(lambda enabled: self.set_main_always_on_top(enabled, persist=True))
        layout.addWidget(self.main_always_on_top_check)

        self.compact_button = QPushButton("통합 위젯")
        self.compact_button.setObjectName("topBarButton")
        _stabilize_control(self.compact_button, 94)
        self.compact_button.clicked.connect(self.open_compact_widget)
        layout.addWidget(self.compact_button)
        return bar

    def _build_header_focus_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("headerFocusCard")
        card.setMinimumWidth(126)
        card.setMaximumWidth(168)
        card.setToolTip("현재 집중 상태")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(13, 8, 13, 8)
        layout.setSpacing(10)

        dot = QFrame()
        dot.setObjectName("statusDot")
        dot.setFixedSize(7, 7)
        layout.addWidget(dot)
        self.header_focus_status_label = QLabel("대기 중")
        self.header_focus_status_label.setObjectName("headerFocusStatus")
        self.header_focus_status_label.setMinimumWidth(0)
        self.header_focus_time_label = QLabel("25:00")
        self.header_focus_time_label.setObjectName("headerFocusTime")
        self.header_focus_time_label.setMinimumWidth(0)
        layout.addWidget(self.header_focus_status_label)
        layout.addWidget(self.header_focus_time_label)
        return card

    def _wrap_feature(self, feature_key: str, title: str, content: QWidget) -> DraggableFeatureBox:
        expand_content = feature_key not in {"datetime", "today_checklist"}
        widget_callback = (
            self.open_feature_widget
            if feature_key
            in {
                "focus",
                "pomodoro",
                "today_checklist",
                "quick_memo",
                "today_timeline",
                "link_favorites",
                "media_panel",
            }
            else None
        )
        box = DraggableFeatureBox(
            feature_key,
            title,
            content,
            self.swap_feature_panels,
            expand_content,
            widget_callback,
            self.hide_feature_from_main,
            show_title_bar=feature_key not in {"header_banner", "media_panel"},
            content_drag_enabled=feature_key in {"header_banner", "media_panel"},
        )
        box.resize_callback = self.resize_feature_panel_width
        box.height_callback = self.resize_feature_panel_height
        box.height_provider = self.feature_panel_height
        self.feature_boxes[feature_key] = box
        return box

    def _build_datetime_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("dateTimePanel")
        panel.setFixedHeight(0)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.current_date_label = QLabel()
        self.current_date_label.setObjectName("currentDateLabel")
        self.current_date_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.current_date_label)

        self.current_time_label = QLabel()
        self.current_time_label.setObjectName("currentTimeLabel")
        self.current_time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.current_time_label)

        self.current_datetime_empty_label = QLabel("표시할 날짜/시간이 없습니다.")
        self.current_datetime_empty_label.setObjectName("mutedLabel")
        self.current_datetime_empty_label.setWordWrap(True)
        layout.addWidget(self.current_datetime_empty_label)
        return panel

    def _initialize_column_drop_zones(self) -> None:
        self.column_drop_zones = {
            "left": FeatureColumnDropZone("left", "왼쪽 칸", self.move_feature_to_column),
            "center": FeatureColumnDropZone("center", "가운데 칸", self.move_feature_to_column),
            "right": FeatureColumnDropZone("right", "오른쪽 칸", self.move_feature_to_column),
        }

    def _column_splitter(self, column_key: str) -> QSplitter | None:
        splitter = {
            "left": getattr(self, "left_splitter", None),
            "center": getattr(self, "center_splitter", None),
            "right": getattr(self, "right_splitter", None),
        }.get(column_key)
        return splitter if isinstance(splitter, QSplitter) else None

    def refresh_empty_feature_columns(self) -> None:
        for column_key, zone in getattr(self, "column_drop_zones", {}).items():
            splitter = self._column_splitter(column_key)
            if splitter is None:
                continue
            has_real_widget = any(splitter.widget(index) is not zone for index in range(splitter.count()))
            if has_real_widget:
                if zone.parentWidget() is splitter:
                    _park_widget_for_reparent(zone)
                splitter.setMinimumWidth(0)
            else:
                if zone.parentWidget() is not splitter:
                    splitter.addWidget(zone)
                zone.show()
                splitter.setMinimumWidth(96)
        self._keep_empty_columns_reachable()

    def _keep_empty_columns_reachable(self) -> None:
        body_splitter = getattr(self, "body_splitter", None)
        if not isinstance(body_splitter, QSplitter) or body_splitter.count() < 3:
            return
        sizes = body_splitter.sizes()
        if len(sizes) != 3:
            return
        total = sum(sizes) or max(1, body_splitter.width())
        minimum = min(120, max(72, total // 8))
        changed = False
        for index, column_key in enumerate(("left", "center", "right")):
            splitter = self._column_splitter(column_key)
            zone = self.column_drop_zones.get(column_key)
            if splitter is None or zone is None:
                continue
            if zone.parentWidget() is splitter and sizes[index] < minimum:
                sizes[index] = minimum
                changed = True
        if not changed:
            return
        overflow = max(0, sum(sizes) - total)
        for index in sorted(range(3), key=lambda item: sizes[item], reverse=True):
            zone = self.column_drop_zones.get(("left", "center", "right")[index])
            splitter = self._column_splitter(("left", "center", "right")[index])
            is_empty_zone = splitter is not None and zone is not None and zone.parentWidget() is splitter
            floor = minimum if is_empty_zone else 140
            reduction = min(overflow, max(0, sizes[index] - floor))
            sizes[index] -= reduction
            overflow -= reduction
            if overflow <= 0:
                break
        body_splitter.setSizes([max(1, size) for size in sizes])

    def move_feature_to_column(self, source_key: str, column_key: str) -> None:
        source = self.feature_boxes.get(source_key)
        target_splitter = self._column_splitter(column_key)
        if source is None or target_splitter is None:
            return
        source_parent = source.parentWidget()
        if not isinstance(source_parent, QSplitter):
            return
        target_zone = self.column_drop_zones.get(column_key)
        source_sizes = source_parent.sizes()
        target_sizes = target_splitter.sizes()
        if target_zone is not None and target_zone.parentWidget() is target_splitter:
            target_zone.hide()
            _park_widget_for_reparent(target_zone)
        source.hide()
        _park_widget_for_reparent(source)
        target_splitter.insertWidget(0, source)
        source.setVisible(self._feature_should_be_visible(source_key))
        self._restore_splitter_after_move(source_parent, source_sizes)
        if target_splitter is not source_parent:
            self._restore_splitter_after_move(target_splitter, target_sizes)
        self.refresh_empty_feature_columns()
        self.statusBar().showMessage("패널을 빈 칸으로 옮겼습니다.", 1800)

    def swap_feature_panels(self, source_key: str, target_key: str, placement: str = "after") -> None:
        if source_key == target_key:
            return
        source = self.feature_boxes.get(source_key)
        target = self.feature_boxes.get(target_key)
        if source is None or target is None:
            return
        if hasattr(self, "feature_dashboard_layout"):
            self._move_feature_in_dashboard(source_key, target_key, placement)
            return
        if hasattr(self, "feature_rows_layout"):
            self._move_feature_in_rows(source_key, target_key, placement)
            return
        if hasattr(self, "feature_grid_layout"):
            self._move_feature_in_grid(source_key, target_key, placement)
            return

        source_parent = source.parentWidget()
        target_parent = target.parentWidget()
        if not isinstance(source_parent, QSplitter) or not isinstance(target_parent, QSplitter):
            return
        source_index = source_parent.indexOf(source)
        target_index = target_parent.indexOf(target)
        if source_index < 0 or target_index < 0:
            return

        source_sizes = source_parent.sizes()
        target_sizes = target_parent.sizes()
        insert_index = target_index if placement == "before" else target_index + 1
        source.hide()
        _park_widget_for_reparent(source)
        if source_parent is target_parent and source_index < insert_index:
            insert_index -= 1
        target_parent.insertWidget(insert_index, source)
        source.setVisible(self._feature_should_be_visible(source_key))
        self._restore_splitter_after_move(source_parent, source_sizes)
        if target_parent is not source_parent:
            self._restore_splitter_after_move(target_parent, target_sizes)

        self.statusBar().showMessage("패널 위치를 바꿨습니다.", 1800)

    def preview_feature_reposition(self, source_key: str, global_position: QPoint) -> None:
        if hasattr(self, "feature_dashboard_layout"):
            self._show_dashboard_drag_guides(source_key, global_position)
            return
        return

    def finish_feature_reposition(self, source_key: str, global_position: QPoint) -> None:
        if hasattr(self, "feature_dashboard_layout"):
            self._hide_dashboard_drag_guides()
        target = self._feature_drop_target_at(global_position, source_key)
        if target is None:
            if hasattr(self, "feature_dashboard_layout"):
                if self._move_feature_to_dashboard_position(source_key, global_position):
                    return
                self.statusBar().showMessage("옮길 위치를 찾지 못했습니다.", 1400)
                return
            self.statusBar().showMessage("옮길 위치를 찾지 못했습니다.", 1400)
            return
        target_kind, target_key, placement = target
        if target_kind == "column":
            self.move_feature_to_column(source_key, target_key)
            return
        self.swap_feature_panels(source_key, target_key, placement)

    def _feature_drop_target_at(self, global_position: QPoint, source_key: str) -> tuple[str, str, str] | None:
        widget = QApplication.widgetAt(global_position)
        target = self._feature_drop_target_from_widget(widget, global_position, source_key)
        if target is not None:
            return target

        for key, box in self.feature_boxes.items():
            if key == source_key or not box.isVisible():
                continue
            local_position = box.mapFromGlobal(global_position)
            if box.rect().contains(local_position):
                return ("feature", key, box._drop_placement(local_position))

        for column in self._visible_feature_columns():
            local_position = column.mapFromGlobal(global_position)
            if column.rect().contains(local_position):
                fallback_key = next((str(key) for key in reversed(column.items) if str(key) != source_key), "")
                if fallback_key:
                    return ("feature", fallback_key, "after")
        return None

    def _feature_drop_target_from_widget(
        self,
        widget: QWidget | None,
        global_position: QPoint,
        source_key: str,
    ) -> tuple[str, str, str] | None:
        cursor = widget
        while cursor is not None:
            if isinstance(cursor, DraggableFeatureBox):
                if cursor.feature_key != source_key:
                    local_position = cursor.mapFromGlobal(global_position)
                    return ("feature", cursor.feature_key, cursor._drop_placement(local_position))
            elif isinstance(cursor, FeatureCell):
                if cursor.feature_key != source_key:
                    box = cursor.feature_box
                    local_position = box.mapFromGlobal(global_position)
                    return ("feature", cursor.feature_key, box._drop_placement(local_position))
            elif isinstance(cursor, FeatureColumn):
                fallback_key = next((str(key) for key in reversed(cursor.items) if str(key) != source_key), "")
                if fallback_key:
                    return ("feature", fallback_key, "after")
            elif isinstance(cursor, FeatureColumnDropZone):
                return ("column", cursor.column_key, "after")
            cursor = cursor.parentWidget()
        return None

    def _visible_feature_columns(self) -> list[FeatureColumn]:
        columns: list[FeatureColumn] = []
        for splitter in getattr(self, "feature_row_splitters", []):
            if not isinstance(splitter, QSplitter) or not splitter.isVisible():
                continue
            for column_index in range(splitter.count()):
                widget = splitter.widget(column_index)
                if isinstance(widget, FeatureColumn) and widget.isVisible():
                    columns.append(widget)
        return columns

    def _move_feature_in_grid(self, source_key: str, target_key: str, placement: str = "after") -> None:
        order = [key for key in self.feature_grid_order if key in self.feature_boxes]
        for key in self.feature_boxes:
            if key not in order:
                order.append(key)
        if source_key not in order or target_key not in order:
            return
        order.remove(source_key)
        target_index = order.index(target_key)
        insert_index = target_index if placement == "before" else target_index + 1
        order.insert(insert_index, source_key)
        self.feature_grid_order = order
        self._render_feature_grid()
        self.save_last_layout_state()
        self.statusBar().showMessage("패널 위치를 바꿨습니다.", 1800)

    def _move_feature_in_rows(self, source_key: str, target_key: str, placement: str = "after") -> None:
        rows = self._current_feature_rows_layout()
        source_height = self.feature_panel_height(source_key)
        source_width = self.feature_panel_width(source_key)
        cleaned_rows: list[dict[str, object]] = []
        target_location: tuple[int, int, int] | None = None

        for row in rows:
            columns = self._normalized_row_columns(row)
            sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
            cleaned_columns: list[dict[str, object]] = []
            cleaned_sizes: list[int] = []
            for column_index, column in enumerate(columns):
                items = [str(key) for key in column.get("items", [])]
                heights = self._normalized_item_heights(column.get("heights"), items)
                widths = self._normalized_item_widths(
                    column.get("widths"),
                    items,
                    fallback=sizes[column_index] if column_index < len(sizes) else 1000,
                )
                next_items: list[str] = []
                next_heights: list[int] = []
                next_widths: list[int] = []
                for item_index, key in enumerate(items):
                    if key == source_key:
                        source_height = heights[item_index]
                        source_width = widths[item_index]
                        continue
                    if key == target_key:
                        target_location = (len(cleaned_rows), len(cleaned_columns), len(next_items))
                    next_items.append(key)
                    next_heights.append(heights[item_index])
                    next_widths.append(widths[item_index])
                if next_items:
                    cleaned_columns.append({"items": next_items, "heights": next_heights, "widths": next_widths})
                    cleaned_sizes.append(sizes[column_index] if column_index < len(sizes) else 1000)
            if cleaned_columns:
                cleaned_rows.append(self._row_from_columns(cleaned_columns, cleaned_sizes, row.get("height")))

        if target_location is None:
            cleaned_rows.append(
                self._row_from_columns(
                    [{"items": [source_key], "heights": [source_height], "widths": [source_width]}],
                    [source_width],
                    source_height,
                )
            )
            self.feature_layout_rows = cleaned_rows
            self._render_feature_rows()
            self.save_last_layout_state()
            return

        placement = placement if placement in {"left", "right", "before", "after"} else "after"
        row_index, column_index, item_index = target_location
        target_row = cleaned_rows[row_index]
        columns = self._normalized_row_columns(target_row)
        sizes = self._normalized_row_sizes(target_row.get("sizes"), len(columns))

        if placement in {"left", "right"}:
            insert_column_index = column_index if placement == "left" else column_index + 1
            if len(columns) < FEATURE_ROW_MAX_COLUMNS:
                columns.insert(insert_column_index, {"items": [source_key], "heights": [source_height], "widths": [source_width]})
                sizes.insert(insert_column_index, source_width)
                cleaned_rows[row_index] = self._row_from_columns(columns, sizes, target_row.get("height"))
            else:
                row_offset = 0 if placement == "left" else 1
                cleaned_rows.insert(
                    row_index + row_offset,
                    self._row_from_columns(
                        [{"items": [source_key], "heights": [source_height], "widths": [source_width]}],
                        [source_width],
                        source_height,
                    ),
                )
        else:
            target_column = columns[column_index]
            items = [str(key) for key in target_column.get("items", [])]
            heights = self._normalized_item_heights(target_column.get("heights"), items)
            widths = self._normalized_item_widths(
                target_column.get("widths"),
                items,
                fallback=sizes[column_index] if column_index < len(sizes) else 1000,
            )
            insert_item_index = item_index if placement == "before" else item_index + 1
            items.insert(insert_item_index, source_key)
            heights.insert(insert_item_index, source_height)
            widths.insert(insert_item_index, source_width)
            columns[column_index] = {"items": items, "heights": heights, "widths": widths}
            cleaned_rows[row_index] = self._row_from_columns(columns, sizes, target_row.get("height"))

        self.feature_layout_rows = cleaned_rows
        self._render_feature_rows()
        self.save_last_layout_state()
        self.statusBar().showMessage("패널 위치를 바꿨습니다.", 1800)

    def _restore_splitter_after_move(self, splitter: QSplitter, previous_sizes: list[int]) -> None:
        if splitter.count() <= 0:
            return
        if len(previous_sizes) == splitter.count() and any(previous_sizes):
            splitter.setSizes(previous_sizes)
            return
        current_sizes = splitter.sizes()
        if any(current_sizes):
            splitter.setSizes([max(120, size) for size in current_sizes])

    def _build_focus_panel(self) -> QWidget:
        panel = ResizeAwareWidget(self.update_focus_panel_responsive_layout)
        panel.setObjectName("focusPanel")
        self.focus_content_panel = panel
        panel.setMinimumHeight(0)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        focus_header = QLabel("현재 집중")
        focus_header.setObjectName("eyebrowLabel")
        layout.addWidget(focus_header)

        form_panel = QWidget()
        form_panel.setObjectName("softControlPanel")
        form = QGridLayout(form_panel)
        self.focus_form = form
        self.focus_form_panel = form_panel
        form.setContentsMargins(14, 12, 14, 12)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setColumnMinimumWidth(0, 58)
        form.setColumnMinimumWidth(1, 90)
        form.setColumnMinimumWidth(2, 70)
        form.setColumnMinimumWidth(3, 70)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(2, 2)
        form.setColumnStretch(3, 2)

        self.focus_title_edit = QLineEdit()
        self.focus_title_edit.setPlaceholderText("지금 집중할 일")
        _stabilize_control(self.focus_title_edit, 120)
        self.focus_title_edit.setMinimumWidth(0)
        form.addWidget(QLabel("집중"), 0, 0)
        form.addWidget(self.focus_title_edit, 0, 1, 1, 3)
        self.focus_title_label = form.itemAtPosition(0, 0).widget()

        self.target_combo = QComboBox()
        self.target_combo.setMinimumContentsLength(12)
        self.target_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        _stabilize_control(self.target_combo, 120)
        self.target_combo.setMinimumWidth(0)
        self.use_focus_target_check = QCheckBox("화면 지정 사용")
        self.use_focus_target_check.setChecked(False)
        self.use_focus_target_check.toggled.connect(self.toggle_focus_target_controls)
        self.add_target_button = QPushButton("추가")
        self.add_target_button.setObjectName("softButton")
        _stabilize_control(self.add_target_button, 62)
        self.add_target_button.clicked.connect(self.add_focus_target)
        self.target_refresh_button = QPushButton("목록 갱신")
        self.target_refresh_button.setObjectName("ghostButton")
        _stabilize_control(self.target_refresh_button, 64)
        self.target_refresh_button.clicked.connect(self.refresh_targets)
        self.target_action_box = QWidget()
        target_action_layout = QHBoxLayout(self.target_action_box)
        self.target_action_layout = target_action_layout
        target_action_layout.setContentsMargins(0, 0, 0, 0)
        target_action_layout.setSpacing(6)
        target_action_layout.addWidget(self.add_target_button)
        target_action_layout.addWidget(self.target_refresh_button)
        form.addWidget(self.use_focus_target_check, 1, 0)
        form.addWidget(self.target_combo, 1, 1, 1, 2)
        form.addWidget(self.target_action_box, 1, 3)

        self.focus_targets_list = QListWidget()
        self.focus_targets_list.setMinimumHeight(0)
        self.focus_targets_list.setMaximumHeight(52)
        self.focus_targets_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.remove_target_button = QPushButton("삭제")
        self.remove_target_button.setObjectName("ghostButton")
        _stabilize_control(self.remove_target_button, 64)
        self.remove_target_button.clicked.connect(self.remove_selected_focus_target)
        self.focus_targets_label = QLabel("지정 창")
        form.addWidget(self.focus_targets_label, 2, 0)
        form.addWidget(self.focus_targets_list, 2, 1, 1, 2)
        form.addWidget(self.remove_target_button, 2, 3)

        self.planned_minutes_spin = QSpinBox()
        self.planned_minutes_spin.setRange(1, 240)
        self.planned_minutes_spin.setValue(25)
        self.planned_minutes_spin.setSuffix("분")
        _stabilize_control(self.planned_minutes_spin, 88)
        self.planned_minutes_spin.setMinimumWidth(72)
        self.idle_cutoff_spin = QSpinBox()
        self.idle_cutoff_spin.setRange(10, 600)
        self.idle_cutoff_spin.setValue(60)
        self.idle_cutoff_spin.setSuffix("초")
        _stabilize_control(self.idle_cutoff_spin, 88)
        self.idle_cutoff_spin.setMinimumWidth(72)
        form.addWidget(QLabel("목표 시간"), 3, 0)
        form.addWidget(self.planned_minutes_spin, 3, 1)
        form.addWidget(QLabel("자리 비움"), 4, 0)
        form.addWidget(self.idle_cutoff_spin, 4, 1)
        self.planned_minutes_label = form.itemAtPosition(3, 0).widget()
        self.idle_cutoff_label = form.itemAtPosition(4, 0).widget()
        layout.addWidget(form_panel)

        focus_dashboard = QWidget()
        focus_dashboard.setObjectName("focusDashboardCard")
        self.focus_dashboard_card = focus_dashboard
        focus_dashboard_layout = QVBoxLayout(focus_dashboard)
        self.focus_dashboard_layout = focus_dashboard_layout
        focus_dashboard_layout.setContentsMargins(18, 16, 18, 16)
        focus_dashboard_layout.setSpacing(12)

        meter_row = QHBoxLayout()
        self.focus_meter_row = meter_row
        meter_row.setSpacing(16)
        meter_box = QVBoxLayout()
        meter_box.setSpacing(6)
        self.focus_status_label = QLabel("대기 중")
        self.focus_status_label.setObjectName("statusLabel")
        self.remaining_time_label = QLabel("25:00")
        self.remaining_time_label.setObjectName("timeLabel")
        self.remaining_time_label.setMinimumWidth(0)
        self.remaining_time_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.focus_detail_label = QLabel("집중할 일을 고른 뒤 시작하세요. 화면 지정은 선택입니다.")
        self.focus_detail_label.setObjectName("mutedLabel")
        self.focus_detail_label.setWordWrap(True)
        self.focus_detail_label.setMinimumWidth(0)
        meter_box.addWidget(self.focus_status_label, 0, Qt.AlignmentFlag.AlignLeft)
        meter_box.addWidget(self.remaining_time_label)
        meter_box.addWidget(self.focus_detail_label)
        meter_row.addLayout(meter_box, 2)

        ratio_card = QWidget()
        ratio_card.setObjectName("focusRateCard")
        self.focus_ratio_card = ratio_card
        ratio_layout = QVBoxLayout(ratio_card)
        ratio_layout.setContentsMargins(16, 14, 16, 14)
        ratio_layout.setSpacing(8)

        self.focus_ratio_stack = QStackedWidget()
        ring_page = QWidget()
        ring_layout = QVBoxLayout(ring_page)
        ring_layout.setContentsMargins(0, 0, 0, 0)
        ring_layout.setSpacing(0)
        self.focus_ratio_ring = FocusRateRing()
        ring_layout.addWidget(self.focus_ratio_ring, 0, Qt.AlignmentFlag.AlignCenter)

        bar_page = QWidget()
        bar_layout = QVBoxLayout(bar_page)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        self.focus_ratio_label = QLabel("100%")
        self.focus_ratio_label.setObjectName("ratioLabel")
        self.focus_ratio_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_ratio_bar = QProgressBar()
        self.focus_ratio_bar.setObjectName("focusRateBar")
        self.focus_ratio_bar.setRange(0, 1000)
        self.focus_ratio_bar.setTextVisible(False)
        bar_layout.addWidget(self.focus_ratio_label)
        bar_layout.addWidget(self.focus_ratio_bar)

        self.focus_ratio_stack.addWidget(ring_page)
        self.focus_ratio_stack.addWidget(bar_page)
        ratio_caption = QLabel("집중률")
        ratio_caption.setObjectName("metricCaption")
        ratio_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ratio_layout.addWidget(self.focus_ratio_stack)
        ratio_layout.addWidget(ratio_caption)
        meter_row.addWidget(ratio_card, 1)
        focus_dashboard_layout.addLayout(meter_row)

        self.focus_progress = QProgressBar()
        self.focus_progress.setObjectName("focusProgress")
        self.focus_progress.setRange(0, 1000)
        self.focus_progress.setTextVisible(False)
        focus_dashboard_layout.addWidget(self.focus_progress)

        focus_metrics = QHBoxLayout()
        self.focus_metrics_layout = focus_metrics
        focus_metrics.setSpacing(10)
        self.focus_focused_metric_label = QLabel("0초")
        self.focus_away_metric_label = QLabel("0초")
        self.focus_paused_metric_label = QLabel("0초")
        focus_metrics.addWidget(self._build_metric_card("집중", self.focus_focused_metric_label))
        focus_metrics.addWidget(self._build_metric_card("이탈", self.focus_away_metric_label))
        focus_metrics.addWidget(self._build_metric_card("일시정지", self.focus_paused_metric_label))
        focus_dashboard_layout.addLayout(focus_metrics)

        button_row = QHBoxLayout()
        self.focus_button_row = button_row
        button_row.setSpacing(10)
        self.start_focus_button = QPushButton("시작")
        self.start_focus_button.setObjectName("primaryButton")
        self.start_focus_button.clicked.connect(self.start_focus)
        self.pause_focus_button = QPushButton("일시정지")
        self.pause_focus_button.setObjectName("primaryButton")
        self.pause_focus_button.clicked.connect(self.pause_or_resume_focus)
        self.complete_focus_button = QPushButton("완료")
        self.complete_focus_button.setObjectName("ghostButton")
        self.complete_focus_button.clicked.connect(self.complete_focus)
        for button in (self.start_focus_button, self.pause_focus_button, self.complete_focus_button):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button_row.addWidget(self.start_focus_button)
        button_row.addWidget(self.pause_focus_button)
        button_row.addWidget(self.complete_focus_button)
        focus_dashboard_layout.addLayout(button_row)
        layout.addWidget(focus_dashboard, 1)

        self.toggle_focus_target_controls(False)
        self.update_focus_panel_responsive_layout()

        return panel

    def update_focus_panel_responsive_layout(self) -> None:
        required = (
            "focus_content_panel",
            "focus_form",
            "focus_title_label",
            "focus_title_edit",
            "use_focus_target_check",
            "target_combo",
            "target_action_box",
            "focus_targets_label",
            "focus_targets_list",
            "remove_target_button",
            "planned_minutes_label",
            "planned_minutes_spin",
            "idle_cutoff_label",
            "idle_cutoff_spin",
            "focus_meter_row",
            "focus_metrics_layout",
            "focus_button_row",
        )
        if any(not hasattr(self, name) for name in required):
            return

        panel = self.focus_content_panel
        width = panel.width() if isinstance(panel, QWidget) else 0
        if width <= 0:
            width = self.focus_form_panel.width() if hasattr(self, "focus_form_panel") else 0
        compact = width > 0 and width < 520
        dense = width > 0 and width < 360

        form = self.focus_form
        if getattr(self, "_focus_responsive_compact", None) != compact:
            for column in range(4):
                form.setColumnMinimumWidth(column, 0)
                form.setColumnStretch(column, 0)
            if compact:
                form.setColumnStretch(0, 0)
                form.setColumnStretch(1, 1)
                form.addWidget(self.focus_title_label, 0, 0, 1, 2)
                form.addWidget(self.focus_title_edit, 1, 0, 1, 2)
                form.addWidget(self.use_focus_target_check, 2, 0, 1, 2)
                form.addWidget(self.target_combo, 3, 0, 1, 2)
                form.addWidget(self.target_action_box, 4, 0, 1, 2)
                form.addWidget(self.focus_targets_label, 5, 0, 1, 2)
                form.addWidget(self.focus_targets_list, 6, 0, 1, 2)
                form.addWidget(self.remove_target_button, 7, 0, 1, 2)
                form.addWidget(self.planned_minutes_label, 8, 0)
                form.addWidget(self.planned_minutes_spin, 8, 1)
                form.addWidget(self.idle_cutoff_label, 9, 0)
                form.addWidget(self.idle_cutoff_spin, 9, 1)
            else:
                form.setColumnMinimumWidth(0, 58)
                form.setColumnMinimumWidth(1, 90)
                form.setColumnMinimumWidth(2, 70)
                form.setColumnMinimumWidth(3, 70)
                form.setColumnStretch(0, 0)
                form.setColumnStretch(1, 3)
                form.setColumnStretch(2, 2)
                form.setColumnStretch(3, 2)
                form.addWidget(self.focus_title_label, 0, 0)
                form.addWidget(self.focus_title_edit, 0, 1, 1, 3)
                form.addWidget(self.use_focus_target_check, 1, 0)
                form.addWidget(self.target_combo, 1, 1, 1, 2)
                form.addWidget(self.target_action_box, 1, 3)
                form.addWidget(self.focus_targets_label, 2, 0)
                form.addWidget(self.focus_targets_list, 2, 1, 1, 2)
                form.addWidget(self.remove_target_button, 2, 3)
                form.addWidget(self.planned_minutes_label, 3, 0)
                form.addWidget(self.planned_minutes_spin, 3, 1)
                form.addWidget(self.idle_cutoff_label, 4, 0)
                form.addWidget(self.idle_cutoff_spin, 4, 1)
            self._focus_responsive_compact = compact

        if compact:
            form.setContentsMargins(10, 10, 10, 10)
        else:
            form.setContentsMargins(14, 12, 14, 12)
        form.setHorizontalSpacing(8 if compact else 10)
        form.setVerticalSpacing(7 if compact else 6)

        if hasattr(self, "focus_dashboard_layout"):
            if compact:
                self.focus_dashboard_layout.setContentsMargins(12, 12, 12, 12)
            else:
                self.focus_dashboard_layout.setContentsMargins(18, 16, 18, 16)
            self.focus_dashboard_layout.setSpacing(10 if compact else 12)

        for label in (
            self.focus_title_label,
            self.focus_targets_label,
            self.planned_minutes_label,
            self.idle_cutoff_label,
        ):
            if isinstance(label, QLabel):
                label.setWordWrap(True)
                label.setMinimumWidth(0)

        main_direction = QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        for layout in (self.focus_meter_row, self.focus_metrics_layout, self.focus_button_row):
            layout.setDirection(main_direction)
        if hasattr(self, "target_action_layout"):
            self.target_action_layout.setDirection(
                QBoxLayout.Direction.TopToBottom if dense else QBoxLayout.Direction.LeftToRight
            )

        self.remaining_time_label.setStyleSheet("font-size: 32px;" if dense else "font-size: 40px;" if compact else "")
        if hasattr(self, "focus_ratio_ring"):
            self.focus_ratio_ring.setMinimumSize(64 if dense else 72, 64 if dense else 72)

    def _build_metric_card(self, caption: str, value_label: QLabel) -> QWidget:
        card = QWidget()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        value_label.setObjectName("metricValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_label.setMinimumWidth(0)
        caption_label = QLabel(caption)
        caption_label.setObjectName("metricCaption")
        caption_label.setWordWrap(True)
        caption_label.setMinimumWidth(0)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        return card

    def _build_pomodoro_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("pomodoroPanel")
        self.pomodoro_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        heading_row = QHBoxLayout()
        heading_row.setSpacing(8)
        self.pomodoro_status_dot = QFrame()
        self.pomodoro_status_dot.setObjectName("pomodoroStatusDot")
        self.pomodoro_status_dot.setFixedSize(7, 7)
        heading_row.addWidget(self.pomodoro_status_dot)
        self.pomodoro_status_label = QLabel("대기")
        self.pomodoro_status_label.setObjectName("pomodoroStatus")
        self.pomodoro_status_label.setMinimumWidth(0)
        self.pomodoro_time_label = QLabel("25:00")
        self.pomodoro_time_label.setObjectName("pomodoroTime")
        self.pomodoro_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_row.addWidget(self.pomodoro_status_label)
        heading_row.addStretch(1)
        heading_row.addWidget(self.pomodoro_time_label)
        layout.addLayout(heading_row)

        self.pomodoro_progress = QProgressBar()
        self.pomodoro_progress.setObjectName("pomodoroProgress")
        self.pomodoro_progress.setRange(0, 1000)
        self.pomodoro_progress.setTextVisible(False)
        layout.addWidget(self.pomodoro_progress)

        self.pomodoro_detail_label = QLabel()
        self.pomodoro_detail_label.setObjectName("pomodoroDetail")
        self.pomodoro_detail_label.setWordWrap(True)
        layout.addWidget(self.pomodoro_detail_label)

        control_row = QHBoxLayout()
        control_row.setSpacing(8)
        self.pomodoro_minutes_spin = QSpinBox()
        self.pomodoro_minutes_spin.setRange(5, 90)
        self.pomodoro_minutes_spin.setValue(25)
        self.pomodoro_minutes_spin.setSuffix("분 집중")
        _stabilize_control(self.pomodoro_minutes_spin, 120)
        self.pomodoro_minutes_spin.valueChanged.connect(lambda _value: self.update_pomodoro_display())
        self.break_minutes_spin = QSpinBox()
        self.break_minutes_spin.setRange(1, 60)
        self.break_minutes_spin.setValue(5)
        self.break_minutes_spin.setSuffix("분 휴식")
        _stabilize_control(self.break_minutes_spin, 120)
        self.break_minutes_spin.valueChanged.connect(lambda _value: self.update_pomodoro_display())
        self.start_pomodoro_button = QPushButton("시작")
        self.start_pomodoro_button.setObjectName("primaryButton")
        _stabilize_control(self.start_pomodoro_button, 68)
        self.start_pomodoro_button.clicked.connect(self.start_pomodoro)
        self.pause_pomodoro_button = QPushButton("일시정지")
        self.pause_pomodoro_button.setObjectName("ghostButton")
        _stabilize_control(self.pause_pomodoro_button, 82)
        self.pause_pomodoro_button.clicked.connect(self.pause_or_resume_pomodoro)
        self.reset_pomodoro_button = QPushButton("초기화")
        self.reset_pomodoro_button.setObjectName("ghostButton")
        _stabilize_control(self.reset_pomodoro_button, 72)
        self.reset_pomodoro_button.clicked.connect(self.reset_pomodoro)

        control_row.addWidget(self.pomodoro_minutes_spin)
        control_row.addWidget(self.break_minutes_spin)
        control_row.addStretch(1)
        control_row.addWidget(self.start_pomodoro_button)
        control_row.addWidget(self.pause_pomodoro_button)
        control_row.addWidget(self.reset_pomodoro_button)
        layout.addLayout(control_row)

        self.update_pomodoro_display()
        return panel

    def _build_today_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("plainPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("오늘 흐름")
        heading.setObjectName("sectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        timeline_button = QPushButton("오늘 시간표")
        _stabilize_control(timeline_button, 100)
        timeline_button.clicked.connect(self.show_today_timeline_window)
        heading_row.addWidget(timeline_button)
        completed_tasks_button = QPushButton("완료 목록")
        _stabilize_control(completed_tasks_button, 96)
        completed_tasks_button.clicked.connect(self.show_completed_tasks_window)
        heading_row.addWidget(completed_tasks_button)
        layout.addLayout(heading_row)

        task_row = QHBoxLayout()
        self.quick_task_type_combo = QComboBox()
        _populate_item_type_combo(self.quick_task_type_combo, self.repository, "task")
        _stabilize_control(self.quick_task_type_combo, 110)
        self.quick_task_edit = QLineEdit()
        self.quick_task_edit.setPlaceholderText("오늘 항목 빠르게 추가")
        _stabilize_control(self.quick_task_edit, 180)
        self.quick_task_minutes = QSpinBox()
        self.quick_task_minutes.setRange(5, 240)
        self.quick_task_minutes.setValue(25)
        self.quick_task_minutes.setSuffix("분")
        _stabilize_control(self.quick_task_minutes, 92)
        add_task_button = QPushButton("추가")
        _stabilize_control(add_task_button, 78)
        add_task_button.clicked.connect(self.add_quick_task)
        task_row.addWidget(self.quick_task_type_combo)
        task_row.addWidget(self.quick_task_edit, 1)
        task_row.addWidget(self.quick_task_minutes)
        task_row.addWidget(add_task_button)
        layout.addLayout(task_row)

        event_row = QHBoxLayout()
        self.quick_event_type_combo = QComboBox()
        _populate_item_type_combo(self.quick_event_type_combo, self.repository, "task")
        _stabilize_control(self.quick_event_type_combo, 110)
        self.quick_event_edit = QLineEdit()
        self.quick_event_edit.setPlaceholderText("오늘 시간 있는 할 일")
        _stabilize_control(self.quick_event_edit, 180)
        self.quick_event_time = QTimeEdit()
        self.quick_event_time.setDisplayFormat(_time_edit_display_format(self.preferences))
        self.quick_event_time.setTime(QTime.currentTime())
        _stabilize_control(self.quick_event_time, 92)
        add_event_button = QPushButton("할 일 추가")
        _stabilize_control(add_event_button, 94)
        add_event_button.clicked.connect(self.add_quick_event)
        event_row.addWidget(self.quick_event_type_combo)
        event_row.addWidget(self.quick_event_edit, 1)
        event_row.addWidget(self.quick_event_time)
        event_row.addWidget(add_event_button)
        layout.addLayout(event_row)

        self.today_list = QListWidget()
        self.today_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.today_list.itemDoubleClicked.connect(self.load_task_from_item)
        self.today_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.today_list.customContextMenuRequested.connect(self.show_today_context_menu)
        layout.addWidget(self.today_list, 1)
        delete_shortcut = QShortcut(QKeySequence("Delete"), self.today_list)
        delete_shortcut.activated.connect(self.delete_selected_today_item)

        action_row = QHBoxLayout()
        focus_selected = QPushButton("선택 집중")
        focus_selected.clicked.connect(self.focus_selected_task)
        complete_selected = QPushButton("완료 처리")
        complete_selected.clicked.connect(self.complete_selected_today_item)
        delete_selected = QPushButton("삭제")
        delete_selected.clicked.connect(self.delete_selected_today_item)
        action_row.addWidget(focus_selected)
        action_row.addWidget(complete_selected)
        action_row.addWidget(delete_selected)
        layout.addLayout(action_row)

        history_heading = QHBoxLayout()
        history_heading.addWidget(QLabel("최근 집중 기록"))
        history_heading.addStretch(1)
        delete_history_button = QPushButton("삭제")
        _stabilize_control(delete_history_button, 72)
        delete_history_button.clicked.connect(self.delete_selected_focus_history)
        history_heading.addWidget(delete_history_button)
        layout.addLayout(history_heading)

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(110)
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        layout.addWidget(self.history_list)
        delete_history_shortcut = QShortcut(QKeySequence("Delete"), self.history_list)
        delete_history_shortcut.activated.connect(self.delete_selected_focus_history)

        return panel

    def _build_memo_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("plainPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        folder_strip = QWidget()
        folder_strip.setObjectName("memoFolderStrip")
        note_meta_row = QHBoxLayout(folder_strip)
        note_meta_row.setContentsMargins(10, 8, 10, 8)
        note_meta_row.setSpacing(8)
        folder_label = QLabel("폴더")
        folder_label.setObjectName("eyebrowLabel")
        note_meta_row.addWidget(folder_label)
        self.quick_note_folder_combo = QComboBox()
        _stabilize_control(self.quick_note_folder_combo, 150)
        self.quick_note_folder_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_note_folder_combo.customContextMenuRequested.connect(
            lambda position: self.show_note_folder_combo_context_menu(self.quick_note_folder_combo, position)
        )
        note_meta_row.addWidget(self.quick_note_folder_combo, 1)
        folder_view_button = QPushButton("폴더 보기")
        folder_view_button.setObjectName("ghostButton")
        _stabilize_control(folder_view_button, 92)
        folder_view_button.setMaximumWidth(104)
        folder_view_button.clicked.connect(lambda: self.open_note_folder_window(self._folder_id_from_combo("note_filter_combo")))
        note_meta_row.addWidget(folder_view_button)
        folder_settings_button = QPushButton("폴더 관리")
        folder_settings_button.setObjectName("ghostButton")
        _stabilize_control(folder_settings_button, 92)
        folder_settings_button.setMaximumWidth(104)
        folder_settings_button.clicked.connect(self.show_note_folder_settings)
        note_meta_row.addWidget(folder_settings_button)
        layout.addWidget(folder_strip)

        self.memo_splitter = QSplitter(Qt.Orientation.Vertical)
        self.memo_splitter.setObjectName("memoSplitter")
        self.memo_splitter.setChildrenCollapsible(False)

        memo_editor = QWidget()
        memo_editor.setObjectName("memoEditorCard")
        memo_editor_layout = QVBoxLayout(memo_editor)
        memo_editor_layout.setContentsMargins(12, 11, 12, 11)
        memo_editor_layout.setSpacing(9)

        memo_editor_header_widget = QWidget()
        memo_editor_header_widget.setObjectName("memoEditorHeader")
        memo_editor_header = QHBoxLayout(memo_editor_header_widget)
        memo_editor_header.setContentsMargins(0, 0, 0, 0)
        memo_editor_header.setSpacing(6)
        memo_editor_title = QLabel("메모 작성")
        memo_editor_title.setObjectName("eyebrowLabel")
        memo_editor_header.addWidget(memo_editor_title)
        memo_editor_header.addStretch(1)
        memo_shortcut_label = QLabel("Ctrl + Enter")
        memo_shortcut_label.setObjectName("memoHintLabel")
        memo_editor_header.addWidget(memo_shortcut_label)
        attach_note_button = QPushButton("첨부")
        attach_note_button.setObjectName("memoAttachButton")
        attach_note_button.clicked.connect(self.select_quick_note_attachments)
        _stabilize_control(attach_note_button, 64)
        attach_note_button.setMaximumWidth(76)
        self.memo_attach_button = attach_note_button
        memo_editor_header.addWidget(attach_note_button)
        save_note_button = QPushButton("저장")
        save_note_button.setObjectName("memoSaveButton")
        save_note_button.clicked.connect(self.save_quick_note)
        _stabilize_control(save_note_button, 64)
        save_note_button.setMaximumWidth(76)
        self.memo_save_button = save_note_button
        memo_editor_header.addWidget(save_note_button)
        self.memo_editor_header = memo_editor_header_widget
        memo_editor_layout.addWidget(memo_editor_header_widget)

        self.quick_note_editor = QPlainTextEdit()
        self.quick_note_editor.setObjectName("memoInput")
        self.quick_note_editor.setPlaceholderText("생각나는 것을 적고 Ctrl+Enter로 저장")
        self.quick_note_editor.setMinimumHeight(72)
        memo_editor_layout.addWidget(self.quick_note_editor, 1)

        self.pending_attachments_label = QLabel("")
        self.pending_attachments_label.setObjectName("memoAttachmentBadge")
        self.pending_attachments_label.setWordWrap(True)
        self.pending_attachments_label.hide()
        memo_editor_layout.addWidget(self.pending_attachments_label)
        self.memo_splitter.addWidget(memo_editor)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.quick_note_editor)
        shortcut.activated.connect(self.save_quick_note)
        shortcut_enter = QShortcut(QKeySequence("Ctrl+Enter"), self.quick_note_editor)
        shortcut_enter.activated.connect(self.save_quick_note)

        notes_container = QWidget()
        notes_container.setObjectName("memoHistoryCard")
        notes_layout = QVBoxLayout(notes_container)
        notes_layout.setContentsMargins(12, 11, 12, 11)
        notes_layout.setSpacing(10)
        notes_filter_row = QHBoxLayout()
        saved_notes_label = QLabel("저장된 메모")
        saved_notes_label.setObjectName("eyebrowLabel")
        notes_filter_row.addWidget(saved_notes_label)
        notes_filter_row.addStretch(1)
        self.note_filter_combo = QComboBox()
        _stabilize_control(self.note_filter_combo, 150)
        self.note_filter_combo.currentIndexChanged.connect(lambda _index: self.refresh_notes())
        notes_filter_row.addWidget(self.note_filter_combo)
        notes_layout.addLayout(notes_filter_row)

        self.notes_list = QListWidget()
        self.notes_list.setObjectName("notesList")
        self.notes_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.notes_list.setUniformItemSizes(False)
        self.notes_list.itemDoubleClicked.connect(self.show_quick_note_detail_from_item)
        self.notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_note_context_menu)
        notes_layout.addWidget(self.notes_list, 1)
        self.memo_splitter.addWidget(notes_container)
        self.memo_splitter.setStretchFactor(0, 1)
        self.memo_splitter.setStretchFactor(1, 1)
        self.memo_splitter.setSizes([220, 220])
        layout.addWidget(self.memo_splitter, 1)
        delete_note_shortcut = QShortcut(QKeySequence("Delete"), self.notes_list)
        delete_note_shortcut.activated.connect(self.delete_selected_quick_note)
        return panel

    def _build_link_favorites_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("plainPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        title = QLabel("바로가기")
        title.setObjectName("eyebrowLabel")
        heading_row.addWidget(title)
        heading_row.addStretch(1)
        favorites_settings_button = QPushButton("설정")
        favorites_settings_button.setObjectName("softButton")
        _stabilize_control(favorites_settings_button, 68)
        favorites_settings_button.setMaximumWidth(78)
        favorites_settings_button.clicked.connect(self.show_favorites_settings)
        heading_row.addWidget(favorites_settings_button)
        layout.addLayout(heading_row)

        self.link_favorites_area = QScrollArea()
        self.link_favorites_area.setObjectName("favoritesShelfArea")
        self.link_favorites_area.setWidgetResizable(True)
        self.link_favorites_area.setFrameShape(QFrame.Shape.NoFrame)
        self.link_favorites_area.setMinimumHeight(120)

        favorites_widget = QWidget()
        favorites_widget.setObjectName("favoritesShelf")
        favorites_widget.setMinimumWidth(0)
        self.link_favorites_layout = QVBoxLayout(favorites_widget)
        self.link_favorites_layout.setContentsMargins(0, 0, 0, 0)
        self.link_favorites_layout.setSpacing(8)
        self.link_favorites_area.setWidget(favorites_widget)
        layout.addWidget(self.link_favorites_area, 1)

        return panel

    def _build_media_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("mediaPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.media_preview_label = MediaPreviewLabel()
        self.media_preview_label.select_callback = self.choose_media_panel_file
        self.media_preview_label.context_callback = self.show_media_panel_context_menu
        layout.addWidget(self.media_preview_label, 1)
        self.refresh_media_panel()
        return panel

    def _build_compact_favorites_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("compactFavoritesPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("즐겨찾기")
        title.setObjectName("mutedLabel")
        header.addWidget(title)
        header.addStretch(1)
        settings_button = QPushButton("설정")
        _stabilize_control(settings_button, 58)
        settings_button.setMaximumWidth(66)
        settings_button.clicked.connect(self.show_favorites_settings)
        header.addWidget(settings_button)
        layout.addLayout(header)

        self.compact_favorites_area = QScrollArea()
        self.compact_favorites_area.setWidgetResizable(True)
        self.compact_favorites_area.setFrameShape(QFrame.Shape.NoFrame)
        self.compact_favorites_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.compact_favorites_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.compact_favorites_area.setMaximumHeight(72)

        favorites_widget = QWidget()
        favorites_widget.setMinimumWidth(0)
        self.compact_favorites_layout = QHBoxLayout(favorites_widget)
        self.compact_favorites_layout.setContentsMargins(0, 0, 0, 0)
        self.compact_favorites_layout.setSpacing(6)
        self.compact_favorites_area.setWidget(favorites_widget)
        layout.addWidget(self.compact_favorites_area)

        return panel

    def _build_compact_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        top = QHBoxLayout()
        self.compact_title_label = QLabel("집중 대기")
        self.compact_title_label.setObjectName("compactTitle")
        top.addWidget(self.compact_title_label, 1)
        full_button = QPushButton("전체")
        full_button.clicked.connect(lambda: self.set_compact_mode(False))
        top.addWidget(full_button)
        layout.addLayout(top)

        self.compact_time_label = QLabel("25:00")
        self.compact_time_label.setObjectName("compactTime")
        self.compact_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.compact_time_label)

        self.compact_status_label = QLabel("대기 중")
        self.compact_status_label.setObjectName("mutedLabel")
        self.compact_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.compact_status_label)

        self.compact_progress = QProgressBar()
        self.compact_progress.setRange(0, 1000)
        self.compact_progress.setTextVisible(False)
        layout.addWidget(self.compact_progress)

        controls = QHBoxLayout()
        self.compact_pause_button = QPushButton("일시정지")
        self.compact_pause_button.clicked.connect(self.pause_or_resume_focus)
        self.compact_done_button = QPushButton("완료")
        self.compact_done_button.clicked.connect(self.complete_focus)
        controls.addWidget(self.compact_pause_button)
        controls.addWidget(self.compact_done_button)
        layout.addLayout(controls)

        memo_row = QHBoxLayout()
        self.compact_note_edit = QLineEdit()
        self.compact_note_edit.setPlaceholderText("빠른 메모")
        self.compact_note_edit.returnPressed.connect(self.save_compact_note)
        memo_button = QPushButton("저장")
        memo_button.clicked.connect(self.save_compact_note)
        memo_row.addWidget(self.compact_note_edit, 1)
        memo_row.addWidget(memo_button)
        layout.addLayout(memo_row)

        compact_notes_header = QHBoxLayout()
        compact_notes_title = QLabel("최근 메모")
        compact_notes_title.setObjectName("mutedLabel")
        compact_notes_header.addWidget(compact_notes_title)
        compact_notes_header.addStretch(1)
        layout.addLayout(compact_notes_header)

        self.compact_notes_list = QListWidget()
        self.compact_notes_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.compact_notes_list.setMaximumHeight(96)
        self.compact_notes_list.itemDoubleClicked.connect(self.show_compact_note_detail_from_item)
        self.compact_notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.compact_notes_list.customContextMenuRequested.connect(self.show_compact_note_context_menu)
        layout.addWidget(self.compact_notes_list)

        self.compact_favorites_panel = self._build_compact_favorites_panel()
        layout.addWidget(self.compact_favorites_panel)

        self.always_on_top_check = QCheckBox("항상 위")
        self.always_on_top_check.setChecked(self.preferences.main_always_on_top)
        self.always_on_top_check.toggled.connect(lambda enabled: self.set_main_always_on_top(enabled, persist=True))
        layout.addWidget(self.always_on_top_check)
        layout.addStretch(1)
        delete_compact_note_shortcut = QShortcut(QKeySequence("Delete"), self.compact_notes_list)
        delete_compact_note_shortcut.activated.connect(self.delete_selected_compact_note)
        return page

    def _apply_style(self) -> None:
        accent = _normalize_accent_color(getattr(self.preferences, "accent_color", "#4f8c6b"))
        accent_hover = _accent_hover_color(accent)
        accent_soft = _accent_rgba(accent, 0.10)
        button_color = _normalize_accent_color(getattr(self.preferences, "button_color", "#4f8c6b"))
        button_hover = _accent_hover_color(button_color)
        is_dark_theme = _normalize_theme(getattr(self.preferences, "appearance_theme", "light")) == "dark"
        palette = _resolved_theme_palette(self.preferences)
        button_palette = _button_theme_palette(
            button_color,
            palette,
            is_dark_theme,
        )
        action_button_palette = _action_button_theme_palette(
            button_color,
            button_hover,
            is_dark_theme,
        )
        _apply_qt_palette(accent, palette)
        style = (
            """
            QMainWindow {
                background: #ececed;
                color: #1b1b20;
                font-family: "Pretendard", "Segoe UI", "Malgun Gothic", sans-serif;
                font-size: 13px;
            }
            QWidget {
                color: #1b1b20;
                font-family: "Pretendard", "Segoe UI", "Malgun Gothic", sans-serif;
                font-size: 13px;
            }
            QDialog {
                background: #ffffff;
                color: #1b1b20;
                font-family: "Pretendard", "Segoe UI", "Malgun Gothic", sans-serif;
            }
            QLabel {
                background: transparent;
            }
            QFrame {
                color: #1b1b20;
            }
            QAbstractScrollArea {
                background: #ffffff;
                color: #1b1b20;
                border: 1px solid #e7e7ec;
                selection-background-color: #5a5ad6;
                selection-color: #ffffff;
            }
            QAbstractScrollArea::viewport {
                background: #ffffff;
                color: #1b1b20;
            }
            QScrollArea#fullScrollArea {
                background: #ececed;
                border: none;
            }
            QScrollArea#fullScrollArea::viewport {
                background: #ececed;
            }
            QWidget#appShell, QWidget#appBody, QWidget#workspace {
                background: #fbfbfc;
            }
            QWidget#appChromeBar {
                background: #fbfbfc;
                border-bottom: 1px solid #f0f0f3;
            }
            QWidget#featureGrid {
                background: transparent;
            }
            QFrame#windowDot {
                background: #e7e7ec;
                border-radius: 5px;
            }
            QFrame#statusDot {
                background: #5a5ad6;
                border-radius: 3px;
            }
            QLabel#chromeTitle {
                color: #1b1b20;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#eyebrowLabel {
                color: #9c9ca6;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
            }
            QWidget#headerFocusCard {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 13px;
            }
            QLabel#headerFocusStatus {
                color: #5a5ad6;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#headerFocusTime {
                color: #1b1b20;
                font-size: 19px;
                font-weight: 600;
            }
            QWidget#softControlPanel {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 14px;
            }
            QWidget#metricCard {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 14px;
            }
            QWidget#focusDashboardCard {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 18px;
            }
            QWidget#focusRateCard {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 18px;
            }
            QWidget#focusDashboardCard QWidget#metricCard {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 14px;
            }
            QWidget#focusDashboardCard QLabel#statusLabel {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #5a5ad6;
                border-radius: 9px;
                color: #5a5ad6;
                padding: 5px 10px;
            }
            QWidget#focusDashboardCard QPushButton {
                min-height: 36px;
            }
            QWidget#memoEditorCard, QWidget#memoHistoryCard {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 16px;
            }
            QWidget#memoEditorHeader {
                background: transparent;
                border: none;
            }
            QWidget#checklistAddPanel {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 14px;
            }
            QWidget#memoFolderStrip {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 13px;
            }
            QScrollArea#checklistItemsArea, QScrollArea#favoritesShelfArea {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 14px;
            }
            QScrollArea#checklistItemsArea::viewport, QScrollArea#favoritesShelfArea::viewport {
                background: #f4f4f6;
                border-radius: 14px;
            }
            QScrollArea#checklistItemsArea QWidget, QScrollArea#favoritesShelfArea QWidget {
                background: transparent;
            }
            QLabel#memoHintLabel {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 8px;
                color: #5c5c66;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 8px;
            }
            QLabel#memoAttachmentBadge {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #5a5ad6;
                border-radius: 9px;
                color: #5a5ad6;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 8px;
            }
            QLabel#screenTitle {
                color: #1b1b20;
                font-size: 23px;
                font-weight: 600;
            }
            QLabel#sectionTitle {
                color: #1b1b20;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#statusLabel {
                font-size: 14px;
                font-weight: 600;
                color: #5a5ad6;
            }
            QLabel#timeLabel {
                color: #1b1b20;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 54px;
                font-weight: 600;
            }
            QLabel#ratioLabel {
                color: #5a5ad6;
                font-size: 21px;
                font-weight: 600;
            }
            QLabel#metricValue {
                color: #1b1b20;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 20px;
                font-weight: 600;
            }
            QLabel#metricCaption {
                color: #9c9ca6;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 11px;
                font-weight: 500;
            }
            QLabel#compactTitle {
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#compactTime {
                color: #1b1b20;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 36px;
                font-weight: 600;
            }
            QLabel#mutedLabel {
                color: #5c5c66;
            }
            QLabel#pomodoroStatus {
                color: #5a5ad6;
                font-weight: 600;
            }
            QFrame#pomodoroStatusDot {
                background: #5a5ad6;
                border-radius: 3px;
            }
            QLabel#pomodoroTime {
                color: #1b1b20;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 24px;
                font-weight: 600;
            }
            QLabel#pomodoroDetail {
                color: #9c9ca6;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 11px;
                font-weight: 500;
            }
            QProgressBar#pomodoroProgress {
                background: #e9e9ef;
                border: none;
                border-radius: 4px;
                max-height: 8px;
                min-height: 8px;
            }
            QProgressBar#pomodoroProgress::chunk {
                background: #5a5ad6;
                border-radius: 4px;
            }
            QLabel#currentDateLabel {
                color: #5c5c66;
                font-size: 13px;
                font-weight: 500;
            }
            QLabel#currentTimeLabel {
                color: #1b1b20;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 24px;
                font-weight: 600;
            }
            QLabel#timelineDateBadge {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 9px;
                color: #5c5c66;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 10px;
            }
            QLabel#timelineSummaryBadge {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 9px;
                color: #5c5c66;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 10px;
            }
            QWidget#timelineToolbar {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 13px;
            }
            QWidget#timelineStatStrip {
                background: transparent;
            }
            QLabel#timelineStatChip {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 10px;
                color: #5c5c66;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 11px;
                font-weight: 700;
                padding: 5px 10px;
            }
            QWidget#timelineLegendBar {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 13px;
            }
            QLabel#waitingSummaryBadge {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #5a5ad6;
                border-radius: 8px;
                color: #5a5ad6;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 10px;
                font-weight: 700;
                padding: 3px 7px;
            }
            QLabel#checklistSummaryBadge {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #5a5ad6;
                border-radius: 8px;
                color: #5a5ad6;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 10px;
                font-weight: 700;
                padding: 3px 7px;
            }
            QProgressBar#checklistProgress {
                background: #e9e9ef;
                border: none;
                border-radius: 4px;
                max-height: 8px;
                min-height: 8px;
            }
            QProgressBar#checklistProgress::chunk {
                background: #5a5ad6;
                border-radius: 4px;
            }
            QWidget#focusPanel, QWidget#pomodoroPanel, QWidget#timelinePanel, QWidget#checklistPanel,
            QWidget#plainPanel, QWidget#compactFavoritesPanel {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 16px;
            }
            QWidget#dateTimePanel {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 16px;
            }
            QWidget#mediaToolbar {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 14px;
            }
            QLabel#mediaFileLabel {
                color: #5c5c66;
                font-size: 12px;
            }
            QLabel#mediaPreviewLabel {
                background: transparent;
                border: none;
                border-radius: 0px;
                color: #5c5c66;
                padding: 0px;
            }
            QWidget#mediaPanel {
                background: transparent;
                border: none;
            }
            QWidget#featureBox {
                background: transparent;
            }
            QWidget#featureCell {
                background: transparent;
            }
            QWidget#featureColumn {
                background: transparent;
            }
            QSplitter#featureRowsSplitter {
                background: transparent;
            }
            QSplitter#featureRowsSplitter::handle:vertical {
                background: transparent;
                height: 10px;
                margin: 0px 16px;
            }
            QSplitter#featureRowsSplitter::handle:vertical:hover {
                background: rgba(90, 90, 214, 0.16);
                border-radius: 5px;
            }
            QSplitter#featureRowSplitter {
                background: transparent;
            }
            QSplitter#featureRowSplitter::handle:horizontal {
                background: transparent;
                width: 8px;
                margin: 10px 0px;
            }
            QSplitter#featureRowSplitter::handle:horizontal:hover {
                background: rgba(90, 90, 214, 0.18);
                border-radius: 4px;
            }
            QSplitter#bodySplitter, QSplitter#leftFeatureSplitter, QSplitter#centerFeatureSplitter, QSplitter#rightFeatureSplitter,
            QSplitter#lowerFeatureSplitter, QSplitter#timelineContentSplitter, QWidget#timelineTimePanel {
                background: transparent;
            }
            QWidget#featureMoveBar {
                background: transparent;
                border: none;
                border-radius: 9px;
            }
            QWidget#featureMoveBar:hover {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #f0f0f3;
            }
            QWidget#columnDropZone {
                background: rgba(90, 90, 214, 0.05);
                border: 1px dashed #c8c8d2;
                border-radius: 12px;
            }
            QLabel#columnDropZoneLabel {
                color: #7a7a86;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#featureMoveTitle {
                color: #1b1b20;
                font-size: 13px;
                font-weight: 700;
            }
            QWidget#themeSegment {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 10px;
            }
            QTabWidget#settingsTabs::pane {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 14px;
                top: -1px;
            }
            QTabWidget#settingsTabs QTabBar::tab {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-bottom: none;
                border-top-left-radius: 9px;
                border-top-right-radius: 9px;
                color: #5c5c66;
                font-weight: 600;
                min-width: 64px;
                padding: 8px 14px;
                margin-right: 4px;
            }
            QTabWidget#settingsTabs QTabBar::tab:hover {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
            }
            QTabWidget#settingsTabs QTabBar::tab:selected {
                background: #ffffff;
                color: #5a5ad6;
                border-color: #e7e7ec;
            }
            QScrollArea#settingsTabScroll, QScrollArea#settingsTabScroll::viewport, QWidget#settingsTabPage {
                background: #ffffff;
                border: none;
            }
            QWidget#settingsColorGroup {
                background: #f4f4f6;
                border: 1px solid #e7e7ec;
                border-radius: 14px;
            }
            QWidget#settingsColorItem {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 12px;
            }
            QLabel#settingsGroupTitle {
                color: #1b1b20;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#settingsColorLabel {
                color: #1b1b20;
                font-weight: 700;
            }
            QWidget#timelineWaitingRail {
                background: #f4f4f6;
                border-left: 1px solid #e7e7ec;
            }
            QWidget#timelineWaitingPanel {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 14px;
            }
            QWidget#timelineWaitingAddPanel {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 13px;
            }
            QToolButton {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                border-radius: 8px;
                color: __BUTTON_TEXT__;
                min-height: 26px;
                padding: 3px 8px;
            }
            QToolButton:hover {
                background: __BUTTON_HOVER_BG__;
                color: __BUTTON_HOVER_TEXT__;
                border-color: #5a5ad6;
            }
            QToolButton#subtleToolButton {
                background: transparent;
                border: 1px solid #e7e7ec;
                border-radius: 9px;
                color: #5c5c66;
                padding: 4px 8px;
            }
            QToolButton#subtleToolButton:hover {
                background: rgba(90, 90, 214, 0.10);
                border-color: #5a5ad6;
                color: #5a5ad6;
            }
            QCheckBox#completedChecklistItem {
                color: #9c9ca6;
            }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
                background: #f4f4f6;
                border: 1px solid #e7e7ec;
                border-radius: 11px;
                color: #1b1b20;
                min-height: 28px;
                padding: 5px 10px;
                selection-background-color: #5a5ad6;
                selection-color: #ffffff;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {
                border-color: #5a5ad6;
                background: #ffffff;
            }
            QPlainTextEdit#memoInput {
                background: #f4f4f6;
                border: 1px solid #e7e7ec;
                border-radius: 11px;
                min-height: 72px;
                padding: 9px 10px;
            }
            QComboBox {
                padding-right: 32px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid #e7e7ec;
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
                background: #fbfbfc;
            }
            QComboBox::drop-down:hover {
                background: rgba(90, 90, 214, 0.10);
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                color: #1b1b20;
                selection-background-color: rgba(90, 90, 214, 0.10);
                selection-color: #5a5ad6;
                outline: 0;
                padding: 4px;
            }
            QSpinBox, QTimeEdit {
                background: #f4f4f6;
                border: 1px solid #e7e7ec;
                border-radius: 11px;
                color: #1b1b20;
                min-height: 30px;
                padding: 4px 30px 4px 8px;
                selection-background-color: #5a5ad6;
                selection-color: #ffffff;
            }
            QSpinBox:focus, QTimeEdit:focus {
                border-color: #5a5ad6;
                background: #ffffff;
            }
            QSpinBox::up-button, QTimeEdit::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #e7e7ec;
                border-bottom: 1px solid #f0f0f3;
                border-top-right-radius: 10px;
                background: #fbfbfc;
            }
            QSpinBox::down-button, QTimeEdit::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 24px;
                border-left: 1px solid #e7e7ec;
                border-bottom-right-radius: 10px;
                background: #fbfbfc;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover,
            QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {
                background: rgba(90, 90, 214, 0.10);
            }
            QPushButton {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                border-radius: 12px;
                color: __BUTTON_TEXT__;
                font-weight: 600;
                min-height: 28px;
                padding: 5px 11px;
            }
            QPushButton:hover {
                background: __BUTTON_HOVER_BG__;
                border-color: #5a5ad6;
                color: __BUTTON_HOVER_TEXT__;
            }
            QPushButton:pressed {
                background: __ACTION_BUTTON_BG__;
                border-color: __ACTION_BUTTON_BG__;
                color: __ACTION_BUTTON_TEXT__;
            }
            QPushButton:disabled {
                background: #e9e9ef;
                border-color: #e9e9ef;
                color: #9c9ca6;
            }
            QPushButton#topBarButton {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                border-radius: 9px;
                color: __BUTTON_TEXT__;
                font-size: 12px;
                min-height: 26px;
                padding: 4px 11px;
            }
            QPushButton#segmentButton {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #9c9ca6;
                font-size: 12px;
                font-weight: 600;
                min-height: 24px;
                padding: 3px 9px;
            }
            QPushButton#segmentButton:hover {
                color: #5c5c66;
                background: transparent;
            }
            QPushButton#segmentButton:checked {
                background: #ffffff;
                color: #1b1b20;
                border: 1px solid #e7e7ec;
            }
            QPushButton#primaryButton {
                background: __ACTION_BUTTON_BG__;
                border: 1px solid __ACTION_BUTTON_BORDER__;
                color: __ACTION_BUTTON_TEXT__;
            }
            QPushButton#primaryButton:hover {
                background: __ACTION_BUTTON_HOVER_BG__;
                border-color: __ACTION_BUTTON_HOVER_BG__;
                color: __ACTION_BUTTON_TEXT__;
            }
            QPushButton#primaryButton:disabled {
                background: #e9e9ef;
                border-color: #e9e9ef;
                color: #9c9ca6;
            }
            QPushButton#ghostButton {
                background: transparent;
                border: 1px solid #e7e7ec;
                color: #5c5c66;
            }
            QPushButton#ghostButton:hover {
                background: rgba(90, 90, 214, 0.10);
                border-color: #5a5ad6;
                color: #5a5ad6;
            }
            QPushButton#ghostButton:disabled {
                background: #fbfbfc;
                border-color: #f0f0f3;
                color: #c3c3cc;
            }
            QPushButton#softButton {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                color: __BUTTON_TEXT__;
            }
            QPushButton#softButton:hover {
                background: __ACTION_BUTTON_BG__;
                border-color: __ACTION_BUTTON_BG__;
                color: __ACTION_BUTTON_TEXT__;
            }
            QPushButton#softButton:disabled {
                background: #f4f4f6;
                border-color: #f4f4f6;
                color: #c3c3cc;
            }
            QPushButton#memoAttachButton {
                background: transparent;
                border: 1px solid #e7e7ec;
                border-radius: 9px;
                color: #5c5c66;
                font-size: 12px;
                min-height: 26px;
                padding: 3px 9px;
            }
            QPushButton#memoAttachButton:hover {
                background: rgba(90, 90, 214, 0.10);
                border-color: #5a5ad6;
                color: #5a5ad6;
            }
            QPushButton#memoSaveButton {
                background: __ACTION_BUTTON_BG__;
                border: 1px solid __ACTION_BUTTON_BORDER__;
                border-radius: 9px;
                color: __ACTION_BUTTON_TEXT__;
                font-size: 12px;
                min-height: 26px;
                padding: 3px 9px;
            }
            QPushButton#memoSaveButton:hover {
                background: __ACTION_BUTTON_HOVER_BG__;
                border-color: __ACTION_BUTTON_HOVER_BG__;
                color: __ACTION_BUTTON_TEXT__;
            }
            QPushButton#memoSaveButton:disabled {
                background: #e9e9ef;
                border-color: #e9e9ef;
                color: #9c9ca6;
            }
            QPushButton#favoriteButton, QToolButton#favoriteButton {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                border-radius: 14px;
                color: __BUTTON_TEXT__;
                font-weight: 600;
                min-height: 56px;
                padding: 10px 12px;
                text-align: left;
            }
            QPushButton#favoriteButton:hover, QToolButton#favoriteButton:hover {
                background: __BUTTON_HOVER_BG__;
                border-color: #5a5ad6;
                color: __BUTTON_HOVER_TEXT__;
            }
            QPushButton#compactFavoriteButton, QToolButton#compactFavoriteButton {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                border-radius: 10px;
                color: __BUTTON_TEXT__;
                font-weight: 600;
                padding: 5px 8px;
            }
            QPushButton#compactFavoriteButton:hover, QToolButton#compactFavoriteButton:hover {
                background: __BUTTON_HOVER_BG__;
                border-color: #5a5ad6;
                color: __BUTTON_HOVER_TEXT__;
            }
            QCheckBox#pinCheck {
                background: transparent;
                border: 1px solid #e7e7ec;
                border-radius: 9px;
                color: #5c5c66;
                font-size: 12px;
                font-weight: 600;
                min-height: 28px;
                padding: 4px 11px;
                spacing: 0px;
            }
            QCheckBox#pinCheck:hover {
                color: #1b1b20;
                border-color: #9c9ca6;
            }
            QCheckBox#pinCheck:checked {
                background: rgba(90, 90, 214, 0.10);
                border-color: #5a5ad6;
                color: #5a5ad6;
            }
            QCheckBox {
                background: transparent;
                color: #5c5c66;
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 5px;
                border: 1px solid #e7e7ec;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border-color: #5a5ad6;
                background: rgba(90, 90, 214, 0.10);
            }
            QCheckBox::indicator:checked {
                background: #5a5ad6;
                border-color: #5a5ad6;
            }
            QCheckBox#pinCheck::indicator {
                width: 0px;
                height: 0px;
                border: none;
                background: transparent;
            }
            QCheckBox#todayChecklistItem, QCheckBox#completedChecklistItem {
                background: transparent;
                border-bottom: 1px solid #f0f0f3;
                border-radius: 0px;
                color: #1b1b20;
                min-height: 30px;
                padding: 7px 4px;
                spacing: 10px;
            }
            QCheckBox#todayChecklistItem:hover, QCheckBox#completedChecklistItem:hover {
                background: #f4f4f6;
                border-radius: 8px;
            }
            QCheckBox#completedChecklistItem {
                color: #9c9ca6;
            }
            QCheckBox#todayChecklistItem::indicator, QCheckBox#completedChecklistItem::indicator {
                width: 17px;
                height: 17px;
                border-radius: 5px;
                border: 2px solid #e7e7ec;
                background: transparent;
            }
            QCheckBox#todayChecklistItem::indicator:checked,
            QCheckBox#completedChecklistItem::indicator:checked {
                background: #5a5ad6;
                border-color: #5a5ad6;
            }
            QWidget#checklistRow, QWidget#checklistRowCompleted {
                background: transparent;
                border: none;
                border-bottom: 1px solid #f0f0f3;
                border-radius: 0px;
            }
            QWidget#checklistRow:hover, QWidget#checklistRowCompleted:hover {
                background: #f4f4f6;
                border-radius: 10px;
            }
            QWidget#checklistRowCompleted {
                background: transparent;
            }
            QCheckBox#checklistItemCheck, QCheckBox#checklistItemCheckDone {
                background: transparent;
                border: none;
                min-height: 22px;
                padding: 0px;
                spacing: 0px;
            }
            QCheckBox#checklistItemCheck::indicator, QCheckBox#checklistItemCheckDone::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #e7e7ec;
                background: #ffffff;
            }
            QCheckBox#checklistItemCheck::indicator:hover,
            QCheckBox#checklistItemCheckDone::indicator:hover {
                border-color: #5a5ad6;
                background: rgba(90, 90, 214, 0.10);
            }
            QCheckBox#checklistItemCheck::indicator:checked,
            QCheckBox#checklistItemCheckDone::indicator:checked {
                background: #5a5ad6;
                border-color: #5a5ad6;
            }
            QWidget#checklistMetaRow {
                background: transparent;
                border: none;
            }
            QLabel#checklistItemTitle {
                color: #1b1b20;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#checklistItemTitleDone {
                color: #9c9ca6;
                font-size: 14px;
                font-weight: 600;
                text-decoration: line-through;
            }
            QLabel#checklistTimeBadge, QLabel#checklistKindBadge, QLabel#checklistDetailBadge {
                border-radius: 8px;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 7px;
            }
            QLabel#checklistTimeBadge {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #5a5ad6;
                color: #5a5ad6;
            }
            QLabel#checklistKindBadge {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                color: #5c5c66;
            }
            QLabel#checklistDetailBadge {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                color: #9c9ca6;
            }
            QMenu {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 11px;
                padding: 6px;
                color: #1b1b20;
            }
            QMenu::item {
                border-radius: 8px;
                padding: 7px 24px 7px 12px;
            }
            QMenu::item:selected {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
            }
            QCalendarWidget {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 16px;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background: #f5f5f5;
                border-top-left-radius: 16px;
                border-top-right-radius: 16px;
                border-bottom: 1px solid #eeeeee;
            }
            QCalendarWidget QToolButton {
                background: transparent;
                border: none;
                border-radius: 9px;
                color: #1b1b20;
                font-weight: 700;
                min-height: 28px;
                padding: 4px 8px;
                margin: 5px 2px;
            }
            QCalendarWidget QToolButton:hover {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
            }
            QCalendarWidget QToolButton#qt_calendar_prevmonth,
            QCalendarWidget QToolButton#qt_calendar_nextmonth {
                background: __BUTTON_BG__;
                border: 1px solid __BUTTON_BORDER__;
                border-radius: 10px;
                min-width: 28px;
                max-width: 28px;
            }
            QCalendarWidget QToolButton::menu-indicator {
                image: none;
                width: 0px;
            }
            QCalendarWidget QMenu {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 10px;
                padding: 5px;
                color: #1b1b20;
            }
            QCalendarWidget QMenu::item {
                border-radius: 7px;
                padding: 5px 18px;
            }
            QCalendarWidget QMenu::item:selected {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
            }
            QCalendarWidget QSpinBox {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 9px;
                min-height: 26px;
                padding: 3px 24px 3px 8px;
            }
            QCalendarWidget QAbstractItemView {
                background: #fdfdfd;
                border: none;
                border-bottom-left-radius: 16px;
                border-bottom-right-radius: 16px;
                color: #1b1b20;
                outline: 0;
                padding: 8px;
                selection-background-color: #5a5ad6;
                selection-color: #ffffff;
            }
            QCalendarWidget QAbstractItemView::item {
                border-radius: 9px;
                margin: 2px;
                padding: 6px;
            }
            QCalendarWidget QAbstractItemView::item:hover {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
            }
            QCalendarWidget QAbstractItemView::item:selected {
                background: #5a5ad6;
                color: #ffffff;
            }
            QListWidget {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 12px;
                color: #1b1b20;
                outline: 0;
                padding: 5px;
            }
            QListWidget::viewport {
                background: #ffffff;
            }
            QListWidget::item {
                border-bottom: 1px solid #f0f0f3;
                padding: 7px 6px;
            }
            QListWidget::item:hover {
                background: #f4f4f6;
                border-radius: 8px;
            }
            QListWidget::item:selected {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
                border-radius: 8px;
            }
            QListWidget#notesList {
                background: #ffffff;
                border-color: #f0f0f3;
                padding: 4px;
            }
            QListWidget#notesList::item {
                border-bottom: 1px solid #f0f0f3;
                padding: 0px;
                margin: 2px 0px;
            }
            QListWidget#notesList::item:hover {
                background: #f4f4f6;
                border-radius: 10px;
            }
            QListWidget#notesList::item:selected {
                background: rgba(90, 90, 214, 0.10);
                border-radius: 10px;
            }
            QWidget#noteListRow {
                background: transparent;
            }
            QWidget#noteTimelineRail, QWidget#noteTimelineContent {
                background: transparent;
            }
            QFrame#noteTimelineDot {
                background: #ffffff;
                border: 2px solid #5a5ad6;
                border-radius: 5px;
            }
            QFrame#noteTimelineLine {
                background: #f0f0f3;
                border: none;
                border-radius: 1px;
            }
            QLabel#noteTimeBadge {
                background: #f4f4f6;
                border: 1px solid #f0f0f3;
                border-radius: 8px;
                color: #5c5c66;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 7px;
            }
            QLabel#noteFolderBadge {
                background: #ffffff;
                border: 1px solid #e7e7ec;
                border-radius: 8px;
                color: #5c5c66;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 7px;
            }
            QLabel#noteAttachmentBadge {
                background: rgba(90, 90, 214, 0.10);
                border: 1px solid #5a5ad6;
                border-radius: 8px;
                color: #5a5ad6;
                font-size: 10px;
                font-weight: 700;
                padding: 3px 7px;
            }
            QLabel#noteBodyLabel {
                color: #1b1b20;
                font-size: 12px;
                font-weight: 500;
            }
            QListWidget#waitingList {
                background: #ffffff;
                border-color: #e7e7ec;
                padding: 4px;
            }
            QListWidget#waitingList::item {
                border-bottom: 1px solid #f0f0f3;
                padding: 7px 6px;
                margin: 1px 0px;
            }
            QListWidget#waitingList::item:hover {
                background: #f4f4f6;
                border-radius: 8px;
            }
            QListWidget#waitingList::item:selected {
                background: rgba(90, 90, 214, 0.10);
                color: #5a5ad6;
                border-radius: 8px;
            }
            QTableWidget#timeBlockTable {
                background: #fdfdfd;
                border: 1px solid #e7e7ec;
                border-radius: 12px;
                color: #1b1b20;
                font-family: "IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace;
                gridline-color: #eeeeee;
                selection-background-color: rgba(90, 90, 214, 0.10);
                selection-color: #1b1b20;
            }
            QTableWidget#timeBlockTable::viewport {
                background: #fdfdfd;
            }
            QTableWidget#timeBlockTable::item {
                padding: 2px;
            }
            QHeaderView::section {
                background: #f5f5f5;
                border: none;
                border-right: 1px solid #eeeeee;
                border-bottom: 1px solid #eeeeee;
                color: #5c5c66;
                font-size: 11px;
                font-weight: 600;
                padding: 6px 4px;
            }
            QTableCornerButton::section {
                background: #f5f5f5;
                border: none;
                border-right: 1px solid #eeeeee;
                border-bottom: 1px solid #eeeeee;
            }
            QSplitter::handle {
                background: #e7e7ec;
            }
            QSplitter::handle:horizontal {
                width: 4px;
            }
            QSplitter::handle:vertical {
                height: 4px;
            }
            QSplitter::handle:hover {
                background: #5a5ad6;
            }
            QProgressBar {
                background: #e9e9ef;
                border: none;
                border-radius: 5px;
                min-height: 10px;
            }
            QProgressBar#focusProgress, QProgressBar#focusRateBar {
                border-radius: 4px;
                max-height: 8px;
                min-height: 8px;
            }
            QProgressBar::chunk {
                background: #5a5ad6;
                border-radius: 5px;
            }
            QProgressBar#focusProgress::chunk, QProgressBar#focusRateBar::chunk {
                border-radius: 4px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #e7e7ec;
                border-radius: 4px;
                min-height: 32px;
            }
            QScrollBar::handle:vertical:hover {
                background: #9c9ca6;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
                height: 0px;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 10px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: #e7e7ec;
                border-radius: 4px;
                min-width: 32px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #9c9ca6;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
                border: none;
                width: 0px;
            }
            QStatusBar {
                background: #fbfbfc;
                color: #5c5c66;
                border-top: 1px solid #f0f0f3;
            }
            """
        )
        self.setStyleSheet(
            _replace_style_tokens(
                style,
                (
                    ("__BUTTON_BG__", button_palette["bg"]),
                    ("__BUTTON_HOVER_BG__", button_palette["hover_bg"]),
                    ("__BUTTON_BORDER__", button_palette["border"]),
                    ("__BUTTON_TEXT__", button_palette["text"]),
                    ("__BUTTON_HOVER_TEXT__", button_palette["hover_text"]),
                    ("__ACTION_BUTTON_BG__", action_button_palette["bg"]),
                    ("__ACTION_BUTTON_HOVER_BG__", action_button_palette["hover_bg"]),
                    ("__ACTION_BUTTON_BORDER__", action_button_palette["border"]),
                    ("__ACTION_BUTTON_TEXT__", action_button_palette["text"]),
                    ("#5a5ad6", accent),
                    ("#7676e8", accent_hover),
                    ("rgba(90, 90, 214, 0.10)", accent_soft),
                    ("#ececed", palette["bg"]),
                    ("#fbfbfc", palette["app"]),
                    ("#ffffff", palette["surface"]),
                    ("#f4f4f6", palette["surface_2"]),
                    ("#fdfdfd", palette["table"]),
                    ("#f5f5f5", palette["table_header"]),
                    ("#eeeeee", palette["table_grid"]),
                    ("#e7e7ec", palette["border"]),
                    ("#f0f0f3", palette["border_2"]),
                    ("#1b1b20", palette["text"]),
                    ("#5c5c66", palette["muted"]),
                    ("#9c9ca6", palette["secondary"]),
                    ("#c3c3cc", palette["disabled"]),
                    ("#e9e9ef", palette["track"]),
                ),
            )
        )
        if hasattr(self, "focus_ratio_ring"):
            self.focus_ratio_ring.set_theme(accent, palette["track"], palette["text"])
        if hasattr(self, "header_banner_widget"):
            self.header_banner_widget.set_theme(accent, palette["border"], palette["surface_2"])
        self.update_focus_rate_display_mode()
        self.sync_theme_segment()

    def update_focus_rate_display_mode(self) -> None:
        stack = getattr(self, "focus_ratio_stack", None)
        if not isinstance(stack, QStackedWidget):
            return
        stack.setCurrentIndex(1 if _normalize_focus_rate_display(self.preferences.focus_rate_display) == "bar" else 0)

    def sync_theme_segment(self) -> None:
        theme = _normalize_theme(getattr(self.preferences, "appearance_theme", "light"))
        for button_name, button_theme in (("light_theme_button", "light"), ("dark_theme_button", "dark")):
            button = getattr(self, button_name, None)
            if isinstance(button, QPushButton):
                button.blockSignals(True)
                button.setChecked(theme == button_theme)
                button.blockSignals(False)

    def set_appearance_theme(self, theme: str) -> None:
        normalized_theme = _normalize_theme(theme)
        if self.preferences.appearance_theme == normalized_theme:
            self.sync_theme_segment()
            return
        self.preferences.appearance_theme = normalized_theme
        self.preferences = self.repository.save_preferences(self.preferences)
        self.apply_preferences()
        self.statusBar().showMessage("테마를 변경했습니다.", 1600)

    def refresh_all(self) -> None:
        self.update_current_datetime_display()
        self.refresh_targets()
        self.refresh_note_folders()
        self.refresh_today()
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_link_favorites()
        self.refresh_compact_favorites()
        self.refresh_media_panel()
        self.refresh_history()
        self.update_focus_display()

    def schedule_startup_refresh(self) -> None:
        if self.startup_refresh_pending:
            return
        self.startup_refresh_pending = True
        self.update_current_datetime_display()
        self.update_focus_display()
        startup_steps: list[Callable[[], None]] = [
            self.refresh_note_folders,
            self.refresh_today,
            self.refresh_notes,
            self.refresh_link_favorites,
            self.refresh_media_panel,
            self.refresh_compact_notes,
            self.refresh_compact_favorites,
            self.refresh_history,
            self.refresh_targets,
        ]

        def run_step(index: int = 0) -> None:
            if self.closing:
                self.startup_refresh_pending = False
                return
            if index >= len(startup_steps):
                self.startup_refresh_pending = False
                return
            startup_steps[index]()
            QTimer.singleShot(20, lambda next_index=index + 1: run_step(next_index))

        QTimer.singleShot(0, run_step)

    def restore_last_window_size(self) -> None:
        width = min(4000, max(430, int(self.preferences.last_window_width or 1280)))
        height = min(3000, max(320, int(self.preferences.last_window_height or 820)))
        self.resize(width, height)

    def save_last_window_size(self) -> None:
        geometry = self.normalGeometry() if self.isMaximized() or self.isFullScreen() else self.geometry()
        width = geometry.width() if geometry.isValid() else self.width()
        height = geometry.height() if geometry.isValid() else self.height()
        width = min(4000, max(430, int(width)))
        height = min(3000, max(320, int(height)))
        if width == self.preferences.last_window_width and height == self.preferences.last_window_height:
            return
        self.preferences.last_window_width = width
        self.preferences.last_window_height = height
        self.preferences = self.repository.save_preferences(self.preferences)

    def restore_last_layout_state(self) -> None:
        raw_state = self.preferences.last_layout_state.strip()
        if not raw_state:
            return
        try:
            state = json.loads(raw_state)
        except json.JSONDecodeError:
            return
        if not isinstance(state, dict):
            return
        state = dict(state)
        state.pop("window", None)
        self.apply_layout_state(state, include_visibility=False)

    def save_last_layout_state(self) -> None:
        state = self.current_layout_state()
        state.pop("window", None)
        data = json.dumps(state, ensure_ascii=False)
        if data == self.preferences.last_layout_state:
            return
        self.preferences.last_layout_state = data
        self.preferences = self.repository.save_preferences(self.preferences)

    def update_current_datetime_display(self) -> None:
        if not hasattr(self, "current_date_label"):
            return
        now = datetime.now()
        show_date = self.preferences.show_current_date
        show_time = self.preferences.show_current_time
        show_seconds = self.preferences.show_current_seconds
        self.current_date_label.setText(now.strftime("%Y년 %m월 %d일"))
        self.current_date_label.setVisible(show_date)
        self.current_time_label.setText(_format_clock_time(now, self.preferences, show_seconds))
        self.current_time_label.setVisible(show_time)
        self.current_datetime_empty_label.setVisible(not show_date and not show_time)
        self.set_feature_title("datetime", self.current_datetime_title(now))

    def current_datetime_title(self, value: datetime | None = None) -> str:
        value = value or datetime.now()
        parts: list[str] = []
        if self.preferences.show_current_date:
            parts.append(value.strftime("%Y년 %m월 %d일"))
        if self.preferences.show_current_time:
            parts.append(_format_clock_time(value, self.preferences, self.preferences.show_current_seconds))
        return " ".join(parts) or "날짜/시간"

    def set_feature_title(self, feature_key: str, title: str) -> None:
        feature_box = getattr(self, "feature_boxes", {}).get(feature_key)
        if feature_box is not None:
            feature_box.set_title(title)

    def refresh_targets(self) -> None:
        self.target_combo.clear()
        self.target_combo.addItem("화면 지정 안 함", None)
        if self.window_provider is None:
            self.target_combo.addItem("열린 창 감지 불가", None)
            return

        for snapshot in self.window_provider.list_open_windows():
            label = _target_label(snapshot.process_name, snapshot.window_title)
            self.target_combo.addItem(
                label,
                {
                    "process_name": snapshot.process_name,
                    "window_title": snapshot.window_title,
                    "display_name": _display_name_from_process(snapshot.process_name),
                },
            )

    def toggle_focus_target_controls(self, enabled: bool) -> None:
        for widget_name in (
            "target_combo",
            "add_target_button",
            "target_refresh_button",
            "target_action_box",
            "focus_targets_label",
            "focus_targets_list",
            "remove_target_button",
        ):
            widget = getattr(self, widget_name, None)
            if isinstance(widget, QWidget):
                widget.setEnabled(enabled)
                widget.setVisible(enabled)
        if not enabled and hasattr(self, "focus_targets_list"):
            self.focus_targets_list.clear()

    def add_focus_target(self) -> None:
        if hasattr(self, "use_focus_target_check") and not self.use_focus_target_check.isChecked():
            return
        target = self.target_combo.currentData()
        if not target:
            return
        if self._has_focus_target(target):
            self.statusBar().showMessage("이미 지정된 창입니다.", 1800)
            return
        item = QListWidgetItem(_target_label(target["process_name"], target["window_title"]))
        item.setData(Qt.ItemDataRole.UserRole, dict(target))
        self.focus_targets_list.addItem(item)
        self.statusBar().showMessage("지정 창을 추가했습니다.", 1800)

    def remove_selected_focus_target(self) -> None:
        row = self.focus_targets_list.currentRow()
        if row < 0:
            return
        self.focus_targets_list.takeItem(row)
        self.statusBar().showMessage("지정 창을 삭제했습니다.", 1800)

    def _selected_focus_targets(self) -> list[dict[str, str]]:
        if hasattr(self, "use_focus_target_check") and not self.use_focus_target_check.isChecked():
            return []
        targets: list[dict[str, str]] = []
        for index in range(self.focus_targets_list.count()):
            data = self.focus_targets_list.item(index).data(Qt.ItemDataRole.UserRole)
            if data:
                targets.append(dict(data))
        if targets:
            return targets
        target = self.target_combo.currentData()
        return [dict(target)] if target else []

    def _has_focus_target(self, target: dict[str, str]) -> bool:
        target_key = (target["process_name"].casefold(), target["window_title"].casefold())
        for index in range(self.focus_targets_list.count()):
            data = self.focus_targets_list.item(index).data(Qt.ItemDataRole.UserRole)
            if not data:
                continue
            item_key = (data["process_name"].casefold(), data["window_title"].casefold())
            if item_key == target_key:
                return True
        return False

    def refresh_note_folders(self, selected_folder_id: int | None = None) -> None:
        self.quick_note_folders = self.repository.list_quick_note_folders()
        self._populate_note_folder_combo("quick_note_folder_combo", include_all=False, selected_folder_id=selected_folder_id)
        self._populate_note_folder_combo("note_filter_combo", include_all=True)
        self._populate_note_folder_combo(
            "quick_note_widget_folder_combo",
            include_all=False,
            selected_folder_id=selected_folder_id,
        )
        folder_window = self.quick_note_folder_notes_window
        if folder_window is not None:
            try:
                refresh_folders = getattr(folder_window, "refresh_folders", None)
                if callable(refresh_folders):
                    refresh_folders(selected_folder_id)
            except RuntimeError:
                self.quick_note_folder_notes_window = None

    def _populate_note_folder_combo(
        self,
        combo_name: str,
        include_all: bool,
        selected_folder_id: int | None = None,
    ) -> None:
        combo = getattr(self, combo_name, None)
        if not isinstance(combo, QComboBox):
            return
        current_id = selected_folder_id if selected_folder_id is not None else combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if include_all:
            combo.addItem("전체", None)
        for folder in self.quick_note_folders:
            combo.addItem(folder.name, folder.id)
        if current_id is not None:
            index = combo.findData(current_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _folder_id_from_combo(self, combo_name: str) -> int | None:
        combo = getattr(self, combo_name, None)
        if not isinstance(combo, QComboBox):
            return None
        folder_id = combo.currentData()
        return int(folder_id) if folder_id is not None else None

    def _folder_name(self, folder_id: int | None) -> str:
        for folder in self.quick_note_folders:
            if folder.id == folder_id:
                return folder.name
        folder = self.repository.get_quick_note_folder(folder_id) if folder_id is not None else None
        return folder.name if folder is not None else "메모함"

    def show_note_folder_combo_context_menu(self, combo: QComboBox, position: QPoint) -> None:
        folder_id = combo.currentData()
        if folder_id is None:
            return
        folder = self.repository.get_quick_note_folder(int(folder_id))
        if folder is None:
            self.refresh_note_folders()
            return
        menu = QMenu(combo)
        open_action = menu.addAction("폴더 보기")
        open_action.triggered.connect(lambda _checked=False: self.open_note_folder_window(folder.id))
        default_action = menu.addAction("기본 메모함으로 지정")
        default_action.setEnabled(not folder.is_default)
        default_action.triggered.connect(lambda _checked=False: self.set_default_quick_note_folder(folder.id))
        menu.exec(combo.mapToGlobal(position))

    def set_default_quick_note_folder(self, folder_id: int | None) -> None:
        if folder_id is None:
            return
        folder = self.repository.set_default_quick_note_folder(int(folder_id))
        if folder is None:
            self.refresh_note_folders()
            return
        self.refresh_note_folders(selected_folder_id=folder.id)
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        widget = self.feature_widget_windows.get("quick_memo")
        folder_combo = getattr(widget, "folder_combo", None)
        if isinstance(folder_combo, QComboBox):
            index = folder_combo.findData(folder.id)
            if index >= 0:
                folder_combo.setCurrentIndex(index)
        self.statusBar().showMessage(f"'{folder.name}'을 기본 메모함으로 지정했습니다.", 2200)

    def refresh_today(self) -> None:
        if hasattr(self, "today_list"):
            if hasattr(self, "quick_task_type_combo"):
                current_type_id = _selected_item_type_id(self.quick_task_type_combo)
                _populate_item_type_combo(self.quick_task_type_combo, self.repository, "task", current_type_id)
            if hasattr(self, "quick_event_type_combo"):
                current_type_id = _selected_item_type_id(self.quick_event_type_combo)
                _populate_item_type_combo(self.quick_event_type_combo, self.repository, "task", current_type_id)
            self.today_list.clear()
            start_at, end_at = _today_window()

            for event in self.repository.list_events(start_at, end_at):
                kind = _item_type_label(self.repository, "event", event.item_type_id)
                item = QListWidgetItem(f"{_format_time(event.start_at, self.preferences)}  {kind}  {event.title}")
                item.setData(Qt.ItemDataRole.UserRole, {"type": "event", "id": event.id})
                self.today_list.addItem(item)

            for task in self.repository.list_tasks(include_completed=False):
                due = _format_time(task.due_at, self.preferences) if task.due_at and task.due_at.date() == date.today() else ""
                prefix = f"{due}  " if due else ""
                kind = _item_type_label(self.repository, "task", task.item_type_id)
                item = QListWidgetItem(f"{prefix}{kind}  {task.title}{_task_duration_suffix(task)}")
                item.setData(Qt.ItemDataRole.UserRole, {"type": "task", "id": task.id})
                self.today_list.addItem(item)
        self.refresh_today_checklist()
        self.refresh_inline_timeline()

    def refresh_notes(self) -> None:
        self.notes_list.clear()
        folder_id = self._folder_id_from_combo("note_filter_combo")
        for note in self.repository.list_quick_notes(limit=12, folder_id=folder_id):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setToolTip(self._note_list_label(note, compact=False))
            item.setSizeHint(QSize(0, 78))
            self.notes_list.addItem(item)
            self.notes_list.setItemWidget(item, self._build_note_list_row(note))

    def _build_note_list_row(self, note: QuickNote) -> QWidget:
        row = QWidget()
        row.setObjectName("noteListRow")
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)

        timeline_rail = QWidget()
        timeline_rail.setObjectName("noteTimelineRail")
        timeline_rail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        timeline_rail.setFixedWidth(12)
        timeline_layout = QVBoxLayout(timeline_rail)
        timeline_layout.setContentsMargins(0, 4, 0, 0)
        timeline_layout.setSpacing(3)
        timeline_dot = QFrame()
        timeline_dot.setObjectName("noteTimelineDot")
        timeline_dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        timeline_dot.setFixedSize(9, 9)
        timeline_line = QFrame()
        timeline_line.setObjectName("noteTimelineLine")
        timeline_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        timeline_line.setFixedWidth(2)
        timeline_layout.addWidget(timeline_dot, 0, Qt.AlignmentFlag.AlignHCenter)
        timeline_layout.addWidget(timeline_line, 1, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(timeline_rail)

        content = QWidget()
        content.setObjectName("noteTimelineContent")
        content.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(5)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)
        time_label = _format_time(note.created_at, self.preferences)
        if note.created_at.date() != date.today():
            time_label = _format_datetime(note.created_at, self.preferences)
        time_badge = QLabel(time_label)
        time_badge.setObjectName("noteTimeBadge")
        time_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        meta_row.addWidget(time_badge)

        folder_badge = QLabel(self._folder_name(note.folder_id))
        folder_badge.setObjectName("noteFolderBadge")
        folder_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        meta_row.addWidget(folder_badge)

        attachments = self.repository.list_quick_note_attachments(note.id) if note.id is not None else []
        if attachments:
            attachment_badge = QLabel(f"첨부 {len(attachments)}")
            attachment_badge.setObjectName("noteAttachmentBadge")
            attachment_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            meta_row.addWidget(attachment_badge)
        meta_row.addStretch(1)
        content_layout.addLayout(meta_row)

        body = _shorten(" ".join(note.body.split()) or "빈 메모", 110)
        body_label = QLabel(body)
        body_label.setObjectName("noteBodyLabel")
        body_label.setWordWrap(True)
        body_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        content_layout.addWidget(body_label)
        layout.addWidget(content, 1)
        return row

    def refresh_compact_notes(self) -> None:
        if not hasattr(self, "compact_notes_list"):
            return
        self.compact_notes_list.clear()
        notes = self.repository.list_quick_notes(limit=5)
        if not notes:
            empty = QListWidgetItem("저장된 메모가 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.compact_notes_list.addItem(empty)
            return
        for note in notes:
            item = QListWidgetItem(self._note_list_label(note, compact=True))
            item.setToolTip(self._note_list_label(note, compact=False))
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.compact_notes_list.addItem(item)

    def _note_list_label(self, note: QuickNote, compact: bool = False) -> str:
        body = _shorten(" ".join(note.body.split()), 34 if compact else 96)
        attachments = self.repository.list_quick_note_attachments(note.id) if note.id is not None else []
        attachment_label = f" · 첨부 {len(attachments)}개" if attachments and not compact else ""
        folder_label = "" if compact else f" · {self._folder_name(note.folder_id)}"
        if note.created_at.date() == date.today():
            time_label = _format_time(note.created_at, self.preferences)
        else:
            time_label = _format_datetime(note.created_at, self.preferences)
        return f"{time_label}  {body}{folder_label}{attachment_label}"

    def choose_media_panel_file(self) -> None:
        image_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "이미지/GIF 선택",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*.*)",
        )
        if image_path:
            self.set_media_panel_file_path(image_path)

    def clear_media_panel_file(self) -> None:
        self.set_media_panel_file_path("")

    def show_media_panel_context_menu(self, source_widget: QWidget, position: QPoint) -> None:
        menu = QMenu(source_widget)
        change_action = menu.addAction("이미지 변경")
        change_action.triggered.connect(lambda _checked=False: self.choose_media_panel_file())
        clear_action = menu.addAction("비우기")
        clear_action.setEnabled(bool(self.preferences.media_panel_file_path.strip()))
        clear_action.triggered.connect(lambda _checked=False: self.clear_media_panel_file())
        menu.exec(source_widget.mapToGlobal(position))

    def set_media_panel_file_path(self, image_path: str) -> None:
        self.preferences.media_panel_file_path = image_path.strip()
        self.preferences = self.repository.save_preferences(self.preferences)
        self.refresh_media_panel()
        self.refresh_feature_widget("media_panel")
        message = "이미지 패널을 비웠습니다." if not self.preferences.media_panel_file_path else "이미지 패널을 업데이트했습니다."
        self.statusBar().showMessage(message, 1800)

    def refresh_media_panel(self) -> None:
        preview = getattr(self, "media_preview_label", None)
        if not isinstance(preview, MediaPreviewLabel):
            return
        file_label = getattr(self, "media_file_label", None)
        self._load_media_preview(self.preferences.media_panel_file_path, preview, file_label)

    def _load_media_preview(
        self,
        image_path: str,
        preview: MediaPreviewLabel,
        file_label: QLabel | None = None,
    ) -> None:
        normalized_path = image_path.strip()
        if not normalized_path:
            if file_label is not None:
                file_label.setText("선택된 이미지/GIF 없음")
                file_label.setToolTip("")
            preview.clear_media("이미지 선택")
            return

        path = Path(normalized_path)
        if file_label is not None:
            file_label.setText(path.name)
            file_label.setToolTip(normalized_path)
        if not path.exists():
            preview.clear_media("파일을 찾을 수 없습니다.")
            return

        if path.suffix.lower() == ".gif":
            movie = QMovie(str(path))
            movie.setCacheMode(QMovie.CacheMode.CacheAll)
            if not movie.isValid():
                preview.clear_media("GIF를 열 수 없습니다.")
                return
            preview.set_movie_source(movie)
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            preview.clear_media("이미지를 열 수 없습니다.")
            return
        preview.set_pixmap_source(pixmap)

    def refresh_link_favorites(self) -> None:
        if not hasattr(self, "link_favorites_layout"):
            return
        while self.link_favorites_layout.count():
            item = self.link_favorites_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        favorites = self.repository.list_link_favorites()
        if not favorites:
            empty_label = QLabel("저장된 즐겨찾기가 없습니다. 설정에서 추가하세요.")
            empty_label.setObjectName("mutedLabel")
            empty_label.setWordWrap(True)
            self.link_favorites_layout.addWidget(empty_label)
            self.link_favorites_layout.addStretch(1)
            self.refresh_compact_widget()
            return

        for favorite in favorites:
            button = self._build_favorite_button(favorite)
            self.link_favorites_layout.addWidget(button)
        self.link_favorites_layout.addStretch(1)
        self.refresh_compact_widget()

    def _build_favorite_button(self, favorite: LinkFavorite) -> QWidget:
        mode = self.preferences.favorite_display_mode
        secondary_label = _favorite_secondary_label(favorite)
        if mode == "text":
            button = QPushButton(f"{favorite.title}\n{secondary_label}" if secondary_label else favorite.title)
            button.setObjectName("favoriteButton")
            button.setMinimumHeight(56 if secondary_label else 40)
        else:
            button = QToolButton()
            button.setObjectName("favoriteButton")
            if mode == "icon_only":
                button.setText("")
            else:
                button.setText(f"{favorite.title}\n{secondary_label}" if secondary_label else favorite.title)
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if mode == "icon_only"
                else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            )
            button.setIconSize(QSize(34, 34))
            button.setMinimumHeight(54 if mode == "icon_only" else 88 if secondary_label else 74)
            icon = _favorite_qicon(favorite)
            if icon is not None:
                button.setIcon(icon)
            elif mode == "icon_only":
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                button.setText(_favorite_icon_text(favorite))
            else:
                title_text = f"{favorite.title}\n{secondary_label}" if secondary_label else favorite.title
                button.setText(f"{_favorite_icon_text(favorite)}\n{title_text}")
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        button.setToolTip(f"{favorite.title}\n{favorite.target}")
        button.clicked.connect(lambda _checked=False, favorite_id=favorite.id: self.open_link_favorite(favorite_id))
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda position, source=button, favorite_id=favorite.id: self.show_link_favorite_context_menu(
                source, position, favorite_id
            )
        )
        return button

    def refresh_compact_favorites(self) -> None:
        if not hasattr(self, "compact_favorites_layout"):
            return
        while self.compact_favorites_layout.count():
            item = self.compact_favorites_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        favorites = self.repository.list_link_favorites()
        if not favorites:
            empty_label = QLabel("없음")
            empty_label.setObjectName("mutedLabel")
            self.compact_favorites_layout.addWidget(empty_label)
            self.compact_favorites_layout.addStretch(1)
            return

        for favorite in favorites:
            button = self._build_compact_favorite_button(favorite)
            self.compact_favorites_layout.addWidget(button)
        self.compact_favorites_layout.addStretch(1)

    def _build_compact_favorite_button(self, favorite: LinkFavorite) -> QWidget:
        mode = self.preferences.favorite_display_mode
        if mode == "text":
            button = QPushButton(_shorten(favorite.title, 12))
            button.setObjectName("compactFavoriteButton")
            button.setMinimumWidth(70)
            button.setMaximumWidth(98)
            button.setMinimumHeight(34)
        else:
            button = QToolButton()
            button.setObjectName("compactFavoriteButton")
            button.setMinimumWidth(54)
            button.setMaximumWidth(76 if mode == "icon_only" else 92)
            button.setMinimumHeight(48 if mode == "icon_only" else 60)
            button.setIconSize(QSize(26, 26))
            icon = _favorite_qicon(favorite)
            if icon is not None:
                button.setIcon(icon)
                button.setText("" if mode == "icon_only" else _shorten(favorite.title, 10))
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly
                    if mode == "icon_only"
                    else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                )
            elif mode == "icon_only":
                button.setText(_favorite_icon_text(favorite))
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            else:
                button.setText(f"{_favorite_icon_text(favorite)}\n{_shorten(favorite.title, 10)}")
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setToolTip(f"{favorite.title}\n{favorite.target}")
        button.clicked.connect(lambda _checked=False, favorite_id=favorite.id: self.open_link_favorite(favorite_id))
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda position, source=button, favorite_id=favorite.id: self.show_link_favorite_context_menu(
                source, position, favorite_id
            )
        )
        return button

    def show_favorites_settings(self) -> None:
        dialog = FavoritesSettingsDialog(self.repository, self.preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.refresh_link_favorites()
            self.refresh_compact_favorites()
            return
        self.preferences.favorite_display_mode = dialog.favorite_display_mode()
        self.preferences = self.repository.save_preferences(self.preferences)
        self.refresh_link_favorites()
        self.refresh_compact_favorites()
        self.refresh_feature_widget("link_favorites")
        self.statusBar().showMessage("즐겨찾기 설정을 저장했습니다.", 2500)

    def show_note_folder_settings(self) -> None:
        dialog = QuickNoteFolderDialog(self.repository, self)
        dialog.exec()
        self.refresh_note_folders()
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.statusBar().showMessage("메모 폴더를 갱신했습니다.", 1800)

    def open_note_folder_window(self, folder_id: int | None = None) -> None:
        if folder_id is None:
            default_folder = self.repository.default_quick_note_folder()
            folder_id = default_folder.id
        existing = self.quick_note_folder_notes_window
        if existing is not None:
            try:
                if existing.isVisible():
                    select_folder = getattr(existing, "select_folder", None)
                    if callable(select_folder) and folder_id is not None:
                        select_folder(folder_id)
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                self.quick_note_folder_notes_window = None

        dialog = QuickNoteFolderNotesDialog(
            self.repository,
            self,
            initial_folder_id=folder_id,
            on_changed=self.refresh_quick_note_views,
        )
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda _obj=None: setattr(self, "quick_note_folder_notes_window", None))
        self.quick_note_folder_notes_window = dialog
        dialog.show()

    def show_link_favorite_context_menu(self, source: QWidget, position: QPoint, favorite_id: int | None) -> None:
        if favorite_id is None:
            return
        menu = QMenu(source)
        open_action = menu.addAction("열기")
        open_action.triggered.connect(lambda _checked=False: self.open_link_favorite(favorite_id))
        settings_action = menu.addAction("설정")
        settings_action.triggered.connect(self.show_favorites_settings)
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(lambda _checked=False: self.delete_link_favorite(favorite_id))
        menu.exec(source.mapToGlobal(position))

    def open_link_favorite(self, favorite_id: int | None) -> None:
        if favorite_id is None:
            return
        favorite = self.repository.get_link_favorite(int(favorite_id))
        if favorite is None:
            self.refresh_link_favorites()
            return

        target = favorite.target.strip()
        try:
            if _is_probable_url(target):
                webbrowser.open(_normalized_url(target))
            else:
                startfile = getattr(os, "startfile", None)
                if startfile is None:
                    webbrowser.open(target)
                else:
                    startfile(target)
        except OSError as exc:
            QMessageBox.warning(self, "즐겨찾기", f"열 수 없습니다.\n{exc}")
            return

        self.statusBar().showMessage(f"'{favorite.title}'을 열었습니다.", 2500)

    def edit_link_favorite(self, favorite_id: int) -> None:
        favorite = self.repository.get_link_favorite(int(favorite_id))
        if favorite is None:
            self.refresh_link_favorites()
            return

        dialog = LinkFavoriteEditDialog(favorite, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        favorite.title = dialog.favorite_title()
        favorite.target = dialog.favorite_target()
        self.repository.save_link_favorite(favorite)
        self.refresh_link_favorites()
        self.refresh_compact_favorites()
        self.refresh_feature_widget("link_favorites")
        self.statusBar().showMessage("즐겨찾기를 수정했습니다.", 2500)

    def delete_link_favorite(self, favorite_id: int) -> None:
        favorite = self.repository.get_link_favorite(int(favorite_id))
        if favorite is None:
            self.refresh_link_favorites()
            return

        answer = QMessageBox.question(self, "즐겨찾기 삭제", f"'{favorite.title}' 즐겨찾기를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.repository.delete_link_favorite(int(favorite_id))
        self.refresh_link_favorites()
        self.refresh_compact_favorites()
        self.refresh_feature_widget("link_favorites")
        self.statusBar().showMessage("즐겨찾기를 삭제했습니다.", 2500)

    def refresh_history(self) -> None:
        if hasattr(self, "history_list"):
            self.history_list.clear()
            for session in self.repository.list_focus_sessions(limit=8):
                item = QListWidgetItem(
                    f"{_focus_session_time_label(session, include_date=True, preferences=self.preferences)}  {session.title} · "
                    f"집중 {_format_duration(session.focused_seconds)} · {_status_label(session.status)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, session.id)
                self.history_list.addItem(item)
        self.refresh_inline_timeline()

    def refresh_inline_timeline(self) -> None:
        if not hasattr(self, "inline_timeline_widget"):
            return
        if self.preferences.show_today_timeline_inline:
            self.inline_timeline_widget.set_date(date.today())
        self.refresh_feature_widget("today_timeline")

    def refresh_today_checklist(self) -> None:
        if not hasattr(self, "today_checklist_widget"):
            return
        if self.preferences.show_today_checklist_inline:
            self.today_checklist_widget.refresh_checklist()
        self.refresh_feature_widget("today_checklist")

    def add_quick_task(self) -> None:
        title = self.quick_task_edit.text().strip()
        if not title:
            return
        task = Task(
            title=title,
            duration_minutes=self.quick_task_minutes.value(),
            item_type_id=_selected_item_type_id(self.quick_task_type_combo),
        )
        self.repository.save_task(task)
        self.quick_task_edit.clear()
        self.refresh_today()
        self.statusBar().showMessage("오늘 항목을 추가했습니다.", 2500)

    def add_quick_event(self) -> None:
        title = self.quick_event_edit.text().strip()
        if not title:
            return
        qtime = self.quick_event_time.time()
        start_at = datetime.combine(date.today(), time(qtime.hour(), qtime.minute()))
        task = Task(
            title=title,
            duration_minutes=30,
            due_at=start_at,
            item_type_id=_selected_item_type_id(self.quick_event_type_combo),
        )
        self.repository.save_task(task)
        self.quick_event_edit.clear()
        self.refresh_today()
        self.statusBar().showMessage("오늘 시간 있는 할 일을 추가했습니다.", 2500)

    def load_task_from_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "task":
            return
        self.load_task_by_id(int(data["id"]))

    def load_task_by_id(self, task_id: int) -> None:
        task = self.repository.get_task(task_id)
        if not task:
            return
        self.selected_task_id = task.id
        self.focus_title_edit.setText(task.title)
        self.planned_minutes_spin.setValue(max(1, task.duration_minutes))

    def focus_selected_task(self) -> None:
        item = self.today_list.currentItem()
        if item is None:
            return
        self.load_task_from_item(item)

    def complete_selected_today_item(self) -> None:
        item = self.today_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") not in {"task", "event"}:
            return
        item_type = str(data["type"])
        if item_type == "task":
            self.repository.mark_task_completed(int(data["id"]), True)
        else:
            self.repository.mark_event_completed(int(data["id"]), True)
        self.refresh_today()
        self.statusBar().showMessage("완료 목록으로 이동했습니다.", 2500)

    def show_completed_tasks_window(self) -> None:
        dialog = CompletedTasksDialog(self.repository, self)
        dialog.exec()
        self.refresh_today()

    def show_today_timeline_window(self) -> None:
        dialog = TodayTimelineDialog(
            self.repository,
            self,
            on_changed=self.refresh_today,
            on_focus_task=self.load_task_by_id,
            on_delete_focus_session=self.delete_focus_session_by_id,
        )
        dialog.exec()
        self.refresh_today()
        self.refresh_history()

    def show_date_review_window(self) -> None:
        dialog = DateReviewDialog(self.repository, self.preferences, self)
        dialog.exec()
        self.refresh_today()
        self.refresh_history()
        self.refresh_notes()
        self.refresh_inline_timeline()

    def show_settings_window(self) -> None:
        previous_banner_position = _normalize_header_banner_position(self.preferences.header_banner_position)
        dialog = SettingsDialog(self.preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.preferences = self.repository.save_preferences(dialog.preferences())
        self.apply_preferences()
        banner_position = _normalize_header_banner_position(self.preferences.header_banner_position)
        if previous_banner_position != banner_position:
            self.move_header_banner_to_preferred_column()
        self.statusBar().showMessage("설정을 저장했습니다.", 2500)

    def show_task_folder_settings(self) -> None:
        dialog = ItemTypeSettingsDialog(self.repository, self)
        dialog.exec()
        self.refresh_all()
        self.statusBar().showMessage("할 일 폴더 설정을 반영했습니다.", 2200)

    def show_item_type_settings(self) -> None:
        self.show_task_folder_settings()

    def apply_preferences(self, refresh_content: bool = True) -> None:
        self._apply_style()
        if self.stack.currentWidget() == self.full_page:
            self.setWindowTitle(self.preferences.app_title)
        if hasattr(self, "chrome_title_label"):
            self.chrome_title_label.setText(self.preferences.app_title or "Schedule Helper")
            self.chrome_title_label.setToolTip(self.preferences.app_title or "Schedule Helper")
        self.set_main_always_on_top(self.preferences.main_always_on_top, persist=False)
        self._sync_always_on_top_checks()
        if hasattr(self, "datetime_panel"):
            self.datetime_panel.setVisible(self.preferences.show_datetime_panel)
            self.update_current_datetime_display()
            if self.preferences.show_datetime_panel and (self.preferences.show_current_time or self.preferences.show_current_date):
                if not self.current_datetime_timer.isActive():
                    self.current_datetime_timer.start()
            else:
                self.current_datetime_timer.stop()
        if hasattr(self, "header_banner_widget"):
            self.header_banner_widget.set_banner_image(self.preferences.header_banner_image_path)
            self.apply_header_banner_preferences()
        if hasattr(self, "focus_panel"):
            self.focus_panel.setVisible(self.preferences.show_focus_panel)
        show_pomodoro = self.preferences.show_pomodoro_controls
        if hasattr(self, "pomodoro_panel"):
            self.pomodoro_panel.setVisible(show_pomodoro)
        if hasattr(self, "timeline_panel"):
            self.timeline_panel.setVisible(self.preferences.show_today_timeline_inline)
            self.inline_timeline_widget.set_waiting_panel_visible(
                self.preferences.show_today_timeline_waiting_panel,
                self.preferences.show_today_timeline_waiting_pinned,
            )
            if refresh_content and self.preferences.show_today_timeline_inline:
                self.inline_timeline_widget.set_date(date.today())
        if hasattr(self, "today_checklist_panel"):
            self.today_checklist_panel.setVisible(self.preferences.show_today_checklist_inline)
            if refresh_content and self.preferences.show_today_checklist_inline:
                self.today_checklist_widget.refresh_checklist()
        if hasattr(self, "memo_panel"):
            self.memo_panel.setVisible(self.preferences.show_quick_memo_panel)
        if hasattr(self, "link_favorites_panel"):
            self.link_favorites_panel.setVisible(self.preferences.show_link_favorites_panel)
            if refresh_content and self.preferences.show_link_favorites_panel:
                self.refresh_link_favorites()
        if hasattr(self, "media_panel"):
            self.media_panel.setVisible(self.preferences.show_media_panel)
            if refresh_content and self.preferences.show_media_panel:
                self.refresh_media_panel()
        self.apply_time_display_format(refresh_content=refresh_content)
        if hasattr(self, "compact_favorites_panel"):
            self.compact_favorites_panel.setVisible(self.preferences.show_compact_favorites_panel)
            if refresh_content and self.preferences.show_compact_favorites_panel:
                self.refresh_compact_favorites()
        if not show_pomodoro:
            self.reset_pomodoro()
        else:
            self.update_pomodoro_display()
        if hasattr(self, "feature_dashboard_layout"):
            self._sync_feature_dashboard_visibility()
        elif hasattr(self, "feature_rows_layout"):
            self._sync_feature_row_visibility()

    def apply_header_banner_preferences(self) -> None:
        if not hasattr(self, "header_banner_widget"):
            return
        banner = self.header_banner_widget
        height = _normalize_header_banner_height(self.preferences.header_banner_height)
        banner.set_banner_height(height)
        panel = getattr(self, "header_banner_panel", None)
        if isinstance(panel, QWidget):
            panel.setMinimumHeight(height + 40)
            panel.setMaximumHeight(16777215)
            panel.setVisible(self.preferences.show_header_banner)
        else:
            banner.setVisible(self.preferences.show_header_banner)

    def move_header_banner_to_preferred_column(self) -> None:
        panel = getattr(self, "header_banner_panel", None)
        if not isinstance(panel, QWidget):
            return
        if hasattr(self, "feature_dashboard_layout"):
            self._render_feature_dashboard()
            self.save_last_layout_state()
            return
        target_splitter = {
            "left": getattr(self, "left_splitter", None),
            "center": getattr(self, "center_splitter", None),
            "right": getattr(self, "right_splitter", None),
        }.get(_normalize_header_banner_position(self.preferences.header_banner_position))
        if not isinstance(target_splitter, QSplitter):
            return
        current_parent = panel.parentWidget()
        if current_parent is target_splitter:
            return
        old_sizes = current_parent.sizes() if isinstance(current_parent, QSplitter) else []
        target_sizes = target_splitter.sizes()
        panel.hide()
        _park_widget_for_reparent(panel)
        target_splitter.insertWidget(0, panel)
        panel.setVisible(self.preferences.show_header_banner)
        if isinstance(current_parent, QSplitter):
            self._restore_splitter_after_move(current_parent, old_sizes)
        self._restore_splitter_after_move(target_splitter, target_sizes)

    def _sync_always_on_top_checks(self) -> None:
        for widget_name in ("main_always_on_top_check", "always_on_top_check"):
            widget = getattr(self, widget_name, None)
            if isinstance(widget, QCheckBox):
                widget.blockSignals(True)
                widget.setChecked(self.preferences.main_always_on_top)
                widget.blockSignals(False)

    def set_main_always_on_top(self, enabled: bool, persist: bool = False) -> None:
        if self.closing:
            return
        if persist and self.preferences.main_always_on_top != enabled:
            self.preferences.main_always_on_top = enabled
            self.preferences = self.repository.save_preferences(self.preferences)
        flags = self.windowFlags()
        current_enabled = bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        if current_enabled != enabled:
            was_visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
            if was_visible and not self.closing:
                self.show()
        self._sync_always_on_top_checks()

    def hide_feature_from_main(self, feature_key: str) -> None:
        attribute = self._feature_visibility_attribute(feature_key)
        if attribute is None:
            return
        if not getattr(self.preferences, attribute):
            return
        setattr(self.preferences, attribute, False)
        self.preferences = self.repository.save_preferences(self.preferences)
        self.apply_preferences()
        self.statusBar().showMessage(f"{self._feature_display_name(feature_key)}을 메인창에서 숨겼습니다.", 2200)

    def _feature_visibility_attribute(self, feature_key: str) -> str | None:
        return {
            "datetime": "show_datetime_panel",
            "focus": "show_focus_panel",
            "pomodoro": "show_pomodoro_controls",
            "header_banner": "show_header_banner",
            "today_timeline": "show_today_timeline_inline",
            "today_timeline_waiting": "show_today_timeline_waiting_panel",
            "today_timeline_waiting_pinned": "show_today_timeline_waiting_pinned",
            "today_checklist": "show_today_checklist_inline",
            "quick_memo": "show_quick_memo_panel",
            "link_favorites": "show_link_favorites_panel",
            "media_panel": "show_media_panel",
            "compact_favorites": "show_compact_favorites_panel",
        }.get(feature_key)

    def _feature_display_name(self, feature_key: str) -> str:
        return {
            "datetime": "날짜/시간",
            "focus": "집중",
            "pomodoro": "뽀모도로",
            "header_banner": "배너",
            "today_checklist": "오늘 체크리스트",
            "quick_memo": "빠른 메모",
            "today_timeline": "오늘 시간표",
            "link_favorites": "즐겨찾기",
            "media_panel": "이미지",
        }.get(feature_key, "기능")

    def set_today_timeline_waiting_pinned(self, pinned: bool) -> None:
        if self.preferences.show_today_timeline_waiting_pinned != pinned:
            self.preferences.show_today_timeline_waiting_pinned = pinned
            self.preferences = self.repository.save_preferences(self.preferences)
        if hasattr(self, "inline_timeline_widget"):
            self.inline_timeline_widget.set_waiting_panel_visible(
                self.preferences.show_today_timeline_waiting_panel,
                pinned,
                notify=False,
            )
        for key, dialog in list(self.feature_widget_windows.items()):
            if key != "today_timeline":
                continue
            try:
                refresh = getattr(dialog, "refresh", None)
                if callable(refresh):
                    refresh()
            except RuntimeError:
                self.feature_widget_windows.pop(key, None)

    def apply_time_display_format(self, refresh_content: bool = True) -> None:
        display_format = _time_edit_display_format(self.preferences)
        for editor_name in ("quick_event_time",):
            editor = getattr(self, editor_name, None)
            if isinstance(editor, QTimeEdit):
                editor.setDisplayFormat(display_format)
        if not refresh_content:
            return
        if hasattr(self, "notes_list"):
            self.refresh_notes()
        if hasattr(self, "compact_notes_list"):
            self.refresh_compact_notes()
        if hasattr(self, "today_checklist_widget"):
            self.today_checklist_widget.refresh_checklist()
        if hasattr(self, "history_list"):
            self.refresh_history()
        if hasattr(self, "inline_timeline_widget"):
            self.inline_timeline_widget.refresh_timeline()

    def save_layout_profile(self) -> None:
        default_name = f"화면 설정 {datetime.now():%m%d %H%M}"
        name, accepted = QInputDialog.getText(
            self,
            "화면 설정 저장",
            "설정 이름",
            QLineEdit.EchoMode.Normal,
            default_name,
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "화면 설정 저장", "저장할 설정 이름을 입력하세요.")
            return

        data = json.dumps(self.current_layout_state(), ensure_ascii=False)
        self.repository.save_layout_profile(LayoutProfile(name=name, data=data))
        self.statusBar().showMessage(f"'{name}' 화면 설정을 저장했습니다.", 2500)

    def load_layout_profile(self) -> None:
        profiles = self.repository.list_layout_profiles()
        if not profiles:
            QMessageBox.information(self, "화면 설정 불러오기", "저장된 화면 설정이 없습니다.")
            return

        names = [profile.name for profile in profiles]
        name, accepted = QInputDialog.getItem(
            self,
            "화면 설정 불러오기",
            "불러올 설정",
            names,
            0,
            False,
        )
        if not accepted or not name:
            return

        profile = next((item for item in profiles if item.name == name), None)
        if profile is None:
            return
        try:
            state = json.loads(profile.data)
        except json.JSONDecodeError:
            QMessageBox.warning(self, "화면 설정 불러오기", "저장된 화면 설정을 읽을 수 없습니다.")
            return

        self.apply_layout_state(state)
        self.statusBar().showMessage(f"'{name}' 화면 설정을 불러왔습니다.", 2500)

    def reset_main_layout(self) -> None:
        state = self.default_layout_state()
        default_window = state.get("window") if isinstance(state.get("window"), dict) else {}
        state["window"] = {
            "width": max(self.width(), int(default_window.get("width", 1120))),
            "height": max(self.height(), int(default_window.get("height", 760))),
        }
        self.apply_layout_state(state, include_visibility=False)
        self.statusBar().showMessage("기본 배치로 되돌렸습니다.", 2500)

    def current_layout_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "window": {
                "width": self.width(),
                "height": self.height(),
            },
            "splitters": {
                "body": self._splitter_sizes("body_splitter"),
                "left": self._splitter_sizes("left_splitter"),
                "center": self._splitter_sizes("center_splitter"),
                "lower": self._splitter_sizes("lower_splitter"),
                "right": self._splitter_sizes("right_splitter"),
                "memo": self._splitter_sizes("memo_splitter"),
            },
            "layout": {
                "dashboard": self._current_feature_dashboard_layout(),
                "rows": self._current_feature_rows_layout(),
                "grid": self._current_feature_grid_layout(),
                "body": self._splitter_child_tokens(self.body_splitter),
                "left": self._splitter_child_tokens(self.left_splitter),
                "center": self._splitter_child_tokens(self.center_splitter),
                "lower": self._splitter_child_tokens(self.lower_splitter),
                "right": self._splitter_child_tokens(self.right_splitter),
            },
            "visible": {
                "datetime": self.preferences.show_datetime_panel,
                "focus": self.preferences.show_focus_panel,
                "pomodoro": self.preferences.show_pomodoro_controls,
                "header_banner": self.preferences.show_header_banner,
                "today_timeline": self.preferences.show_today_timeline_inline,
                "today_timeline_waiting": self.preferences.show_today_timeline_waiting_panel,
                "today_timeline_waiting_pinned": self.preferences.show_today_timeline_waiting_pinned,
                "today_checklist": self.preferences.show_today_checklist_inline,
                "quick_memo": self.preferences.show_quick_memo_panel,
                "link_favorites": self.preferences.show_link_favorites_panel,
                "media_panel": self.preferences.show_media_panel,
                "compact_favorites": self.preferences.show_compact_favorites_panel,
            },
        }

    def default_layout_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "window": {
                "width": 1120,
                "height": 760,
            },
            "splitters": {
                "body": [560, 760, 420],
                "left": [96, 330, 130, 220, 360],
                "center": [180, 620],
                "lower": [640],
                "right": [320, 320],
                "memo": [220, 220],
            },
            "layout": {
                "dashboard": self.default_feature_dashboard_layout(),
                "rows": self.default_feature_rows_layout(),
                "grid": self.default_feature_grid_layout(),
                **self.default_feature_layout(),
            },
        }

    def apply_layout_state(self, state: dict[str, object], include_visibility: bool = True) -> None:
        if self.stack.currentWidget() == self.compact_page:
            self.set_compact_mode(False)

        window_state = state.get("window")
        if isinstance(window_state, dict):
            width = int(window_state.get("width", self.width()))
            height = int(window_state.get("height", self.height()))
            self.resize(max(980, width), max(640, height))

        if include_visibility:
            self._apply_layout_visibility(state.get("visible"))

        self._apply_feature_layout(state.get("layout"))

        splitters = state.get("splitters")
        if not isinstance(splitters, dict):
            return

        def apply_sizes() -> None:
            self._set_splitter_sizes("body_splitter", splitters.get("body"))
            self._set_splitter_sizes("left_splitter", splitters.get("left"))
            self._set_splitter_sizes("center_splitter", splitters.get("center"))
            self._set_splitter_sizes("lower_splitter", splitters.get("lower"))
            self._set_splitter_sizes("right_splitter", splitters.get("right"))
            self._set_splitter_sizes("memo_splitter", splitters.get("memo"))

        QTimer.singleShot(0, apply_sizes)

    def _apply_layout_visibility(self, visible_state: object) -> None:
        if not isinstance(visible_state, dict):
            return

        mapping = {
            key: attribute
            for key in (
                "datetime",
                "focus",
                "pomodoro",
                "header_banner",
                "today_timeline",
                "today_timeline_waiting",
                "today_timeline_waiting_pinned",
                "today_checklist",
                "quick_memo",
                "link_favorites",
                "media_panel",
                "compact_favorites",
            )
            if (attribute := self._feature_visibility_attribute(key)) is not None
        }
        changed = False
        for key, attribute in mapping.items():
            if key not in visible_state:
                continue
            value = bool(visible_state[key])
            if getattr(self.preferences, attribute) != value:
                setattr(self.preferences, attribute, value)
                changed = True

        if changed:
            self.preferences = self.repository.save_preferences(self.preferences)
            self.apply_preferences()

    def default_feature_layout(self) -> dict[str, list[str]]:
        layout = {
            "body": ["group:left", "group:center", "group:right"],
            "left": ["datetime", "focus", "pomodoro", "today_checklist", "group:lower"],
            "center": ["today_timeline"],
            "lower": ["quick_memo"],
            "right": ["link_favorites", "media_panel"],
        }
        banner_position = _normalize_header_banner_position(self.preferences.header_banner_position)
        target_column = {
            "left": layout["left"],
            "center": layout["center"],
            "right": layout["right"],
        }[banner_position]
        target_column.insert(0, "header_banner")
        return layout

    def default_feature_grid_layout(self) -> list[dict[str, object]]:
        return [
            {"key": "focus", "span": 3},
            {"key": "pomodoro", "span": 1},
            {"key": "quick_memo", "span": 2},
            {"key": "today_timeline", "span": 3},
            {"key": "today_checklist", "span": 1},
            {"key": "link_favorites", "span": 1},
            {"key": "media_panel", "span": 1},
            {"key": "header_banner", "span": 3},
            {"key": "datetime", "span": 1},
        ]

    def default_feature_dashboard_layout(self) -> list[dict[str, object]]:
        return [
            {"key": "header_banner", "x": 0, "y": 0, "w": 6, "h": 2},
            {"key": "today_checklist", "x": 0, "y": 2, "w": 2, "h": 5},
            {"key": "today_timeline", "x": 2, "y": 2, "w": 4, "h": 10},
            {"key": "focus", "x": 0, "y": 7, "w": 3, "h": 5},
            {"key": "quick_memo", "x": 3, "y": 12, "w": 3, "h": 5},
            {"key": "pomodoro", "x": 0, "y": 17, "w": 2, "h": 2},
            {"key": "link_favorites", "x": 2, "y": 17, "w": 2, "h": 4},
            {"key": "media_panel", "x": 4, "y": 17, "w": 2, "h": 4},
            {"key": "datetime", "x": 0, "y": 21, "w": 2, "h": 1},
        ]

    def default_feature_rows_layout(self) -> list[dict[str, object]]:
        return self._rows_from_grid_items(self.default_feature_grid_layout())

    def _apply_feature_layout(self, layout_state: object) -> None:
        if hasattr(self, "feature_dashboard_layout"):
            self._apply_feature_dashboard_layout(layout_state)
            return
        if hasattr(self, "feature_rows_layout"):
            self._apply_feature_rows_layout(layout_state)
            return
        if hasattr(self, "feature_grid_layout"):
            self._apply_feature_grid_layout(layout_state)
            return
        layout_tokens = self._normalized_feature_layout(layout_state)
        self._reorder_splitter("body_splitter", layout_tokens["body"])
        self._reorder_splitter("left_splitter", layout_tokens["left"])
        self._reorder_splitter("center_splitter", layout_tokens["center"])
        self._reorder_splitter("lower_splitter", layout_tokens["lower"])
        self._reorder_splitter("right_splitter", layout_tokens["right"])

    def _current_feature_dashboard_layout(self) -> list[dict[str, object]]:
        items = getattr(self, "feature_dashboard_items", [])
        if not items:
            items = self.default_feature_dashboard_layout()
        return self._normalized_feature_dashboard_layout({"dashboard": items})

    def _apply_feature_dashboard_layout(self, layout_state: object) -> None:
        self.feature_dashboard_items = self._normalized_feature_dashboard_layout(layout_state)
        self._render_feature_dashboard()

    def _normalized_feature_dashboard_layout(self, layout_state: object) -> list[dict[str, object]]:
        raw_items: object = None
        if isinstance(layout_state, dict):
            raw_items = layout_state.get("dashboard")
        elif isinstance(layout_state, list):
            raw_items = layout_state

        feature_keys = set(self.feature_boxes)
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                key = str(raw_item.get("key", ""))
                if key not in feature_keys or key in seen:
                    continue
                width = self._normalized_feature_dashboard_width(
                    key,
                    raw_item.get("w", self._default_feature_dashboard_width(key)),
                )
                item = {
                    "key": key,
                    "w": width,
                    "h": self._normalized_feature_dashboard_height(
                        key,
                        raw_item.get("h", self._default_feature_dashboard_height(key)),
                    ),
                }
                if "x" in raw_item and "y" in raw_item:
                    item["x"] = self._normalized_dashboard_x(raw_item.get("x"), width)
                    item["y"] = self._normalized_dashboard_y(raw_item.get("y"))
                items.append(item)
                seen.add(key)

        if not items:
            items = self._dashboard_items_from_legacy_layout(layout_state)
            seen = {str(item.get("key", "")) for item in items}

        for default_item in self.default_feature_dashboard_layout():
            key = str(default_item.get("key", ""))
            if key in feature_keys and key not in seen:
                width = self._normalized_feature_dashboard_width(key, default_item.get("w"))
                items.append(
                    {
                        "key": key,
                        "x": self._normalized_dashboard_x(
                            default_item.get("x", 0),
                            width,
                        ),
                        "y": self._normalized_dashboard_y(default_item.get("y", 0)),
                        "w": width,
                        "h": self._normalized_feature_dashboard_height(key, default_item.get("h")),
                    }
                )
                seen.add(key)
        return self._pack_feature_dashboard_items(items)

    def _dashboard_items_from_legacy_layout(self, layout_state: object) -> list[dict[str, object]]:
        feature_keys = set(self.feature_boxes)
        items: list[dict[str, object]] = []
        seen: set[str] = set()

        def add_item(key: str, width: object = None, height: object = None) -> None:
            if key not in feature_keys or key in seen:
                return
            items.append(
                {
                    "key": key,
                    "w": self._normalized_feature_dashboard_width(
                        key,
                        width if width is not None else self._default_feature_dashboard_width(key),
                    ),
                    "h": self._normalized_feature_dashboard_height(
                        key,
                        height if height is not None else self._default_feature_dashboard_height(key),
                    ),
                }
            )
            seen.add(key)

        if isinstance(layout_state, dict):
            rows = layout_state.get("rows")
            if isinstance(rows, list):
                for row in rows:
                    columns = self._normalized_row_columns(row, seen=None)
                    sizes = self._normalized_row_sizes(row.get("sizes") if isinstance(row, dict) else [], len(columns))
                    for column_index, column in enumerate(columns):
                        column_items = [str(key) for key in column.get("items", [])]
                        heights = self._normalized_item_heights(column.get("heights"), column_items)
                        fallback_width = sizes[column_index] if column_index < len(sizes) else 1000
                        widths = self._normalized_item_widths(column.get("widths"), column_items, fallback=fallback_width)
                        for key, _item_width, item_height in zip(column_items, widths, heights, strict=False):
                            add_item(
                                key,
                                self._default_feature_dashboard_width(key),
                                self._dashboard_height_from_pixels(item_height),
                            )
            grid = layout_state.get("grid")
            if isinstance(grid, list):
                for raw_item in grid:
                    if isinstance(raw_item, dict):
                        key = str(raw_item.get("key", ""))
                        span = raw_item.get("span", 1)
                    else:
                        key = str(raw_item)
                        span = 1
                    width = self._dashboard_width_from_legacy_span(span)
                    add_item(key, width, self._default_feature_dashboard_height(key))

        if not items:
            for default_item in self.default_feature_dashboard_layout():
                add_item(
                    str(default_item.get("key", "")),
                    default_item.get("w"),
                    default_item.get("h"),
                )
        return items

    def _pack_feature_dashboard_items(self, raw_items: list[dict[str, object]]) -> list[dict[str, object]]:
        packed: list[dict[str, object]] = []
        occupied: set[tuple[int, int]] = set()
        for raw_item in raw_items:
            key = str(raw_item.get("key", ""))
            if key not in self.feature_boxes:
                continue
            width = self._normalized_feature_dashboard_width(
                key,
                raw_item.get("w", self._default_feature_dashboard_width(key)),
            )
            height = self._normalized_feature_dashboard_height(
                key,
                raw_item.get("h", self._default_feature_dashboard_height(key)),
            )
            preferred_x = raw_item.get("x")
            preferred_y = raw_item.get("y")
            if preferred_x is not None and preferred_y is not None:
                column = self._normalized_dashboard_x(preferred_x, width)
                row = self._normalized_dashboard_y(preferred_y)
                if self._dashboard_slot_is_free(column, row, width, height, occupied):
                    occupied.update(self._dashboard_cells(column, row, width, height))
                    packed.append({"key": key, "x": column, "y": row, "w": width, "h": height})
                    continue

            column, row = self._first_free_dashboard_slot(width, height, occupied, preferred_x, preferred_y)
            occupied.update(self._dashboard_cells(column, row, width, height))
            packed.append({"key": key, "x": column, "y": row, "w": width, "h": height})
        return packed

    def _dashboard_cells(self, column: int, row: int, width: int, height: int) -> set[tuple[int, int]]:
        return {
            (cell_column, cell_row)
            for cell_column in range(column, column + width)
            for cell_row in range(row, row + height)
        }

    def _dashboard_slot_is_free(
        self,
        column: int,
        row: int,
        width: int,
        height: int,
        occupied: set[tuple[int, int]],
    ) -> bool:
        if column < 0 or row < 0 or column + width > DASHBOARD_GRID_COLUMNS:
            return False
        return occupied.isdisjoint(self._dashboard_cells(column, row, width, height))

    def _first_free_dashboard_slot(
        self,
        width: int,
        height: int,
        occupied: set[tuple[int, int]],
        preferred_x: object = None,
        preferred_y: object = None,
    ) -> tuple[int, int]:
        if preferred_x is not None and preferred_y is not None:
            start_column = self._normalized_dashboard_x(preferred_x, width)
            start_row = self._normalized_dashboard_y(preferred_y)
            max_radius = max(24, len(occupied) + height + 4)
            for radius in range(max_radius + 1):
                candidates: list[tuple[int, int]] = []
                for row in range(max(0, start_row - radius), start_row + radius + 1):
                    for column in range(
                        max(0, start_column - radius),
                        min(DASHBOARD_GRID_COLUMNS - width, start_column + radius) + 1,
                    ):
                        if abs(column - start_column) + abs(row - start_row) == radius:
                            candidates.append((column, row))
                candidates.sort(key=lambda point: (abs(point[1] - start_row), abs(point[0] - start_column), point[1], point[0]))
                for column, row in candidates:
                    if self._dashboard_slot_is_free(column, row, width, height, occupied):
                        return column, row

        row = 0
        while True:
            for column in range(0, DASHBOARD_GRID_COLUMNS - width + 1):
                if self._dashboard_slot_is_free(column, row, width, height, occupied):
                    return column, row
            row += 1

    def _default_feature_dashboard_width(self, feature_key: str) -> int:
        return {
            "header_banner": 6,
            "today_timeline": 4,
            "focus": 3,
            "quick_memo": 3,
            "today_checklist": 2,
            "link_favorites": 2,
            "media_panel": 2,
            "pomodoro": 2,
            "datetime": 2,
        }.get(feature_key, 3)

    def _default_feature_dashboard_height(self, feature_key: str) -> int:
        return {
            "header_banner": 2,
            "today_timeline": 10,
            "focus": 5,
            "quick_memo": 5,
            "today_checklist": 4,
            "link_favorites": 4,
            "media_panel": 4,
            "pomodoro": 2,
            "datetime": 1,
        }.get(feature_key, 3)

    def _normalized_dashboard_width(self, width: object) -> int:
        try:
            value = int(width)
        except (TypeError, ValueError):
            value = 3
        return min(DASHBOARD_GRID_COLUMNS, max(1, value))

    def _minimum_feature_dashboard_width(self, feature_key: str) -> int:
        return {
            "focus": 2,
            "quick_memo": 2,
            "today_timeline": 2,
            "today_checklist": 2,
            "link_favorites": 1,
            "pomodoro": 1,
            "datetime": 1,
            "media_panel": 1,
            "header_banner": 1,
        }.get(feature_key, 2)

    def _minimum_feature_dashboard_height(self, feature_key: str) -> int:
        return {
            "focus": 4,
            "quick_memo": 4,
            "today_timeline": 6,
            "today_checklist": 3,
            "link_favorites": 3,
            "pomodoro": 2,
            "datetime": 1,
            "media_panel": 2,
            "header_banner": 1,
        }.get(feature_key, 2)

    def _normalized_feature_dashboard_width(self, feature_key: str, width: object) -> int:
        minimum = self._minimum_feature_dashboard_width(feature_key)
        return max(minimum, self._normalized_dashboard_width(width))

    def _normalized_feature_dashboard_height(self, feature_key: str, height: object) -> int:
        minimum = self._minimum_feature_dashboard_height(feature_key)
        return max(minimum, self._normalized_dashboard_height(height))

    def _normalized_dashboard_x(self, column: object, width: int = 1) -> int:
        try:
            value = int(column)
        except (TypeError, ValueError):
            value = 0
        max_column = max(0, DASHBOARD_GRID_COLUMNS - self._normalized_dashboard_width(width))
        return min(max_column, max(0, value))

    def _normalized_dashboard_y(self, row: object) -> int:
        try:
            value = int(row)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _normalized_dashboard_height(self, height: object) -> int:
        try:
            value = int(height)
        except (TypeError, ValueError):
            value = 3
        return min(18, max(1, value))

    def _dashboard_width_from_legacy_span(self, span: object) -> int:
        try:
            span_value = int(span)
        except (TypeError, ValueError):
            span_value = 1
        unit_width = max(1, DASHBOARD_GRID_COLUMNS / 3)
        return self._normalized_dashboard_width(round(min(3, max(1, span_value)) * unit_width))

    def _legacy_span_from_dashboard_width(self, width: object) -> int:
        try:
            width_value = int(width)
        except (TypeError, ValueError):
            width_value = self._default_feature_dashboard_width("")
        unit_width = max(1, DASHBOARD_GRID_COLUMNS / 3)
        return min(3, max(1, round(width_value / unit_width)))

    def _dashboard_width_from_pixels(self, width: object) -> int:
        try:
            pixel_width = int(width)
        except (TypeError, ValueError):
            return 3
        container_width = max(720, self.feature_grid_container.width())
        usable_width = max(1, container_width - DASHBOARD_GRID_GAP * (DASHBOARD_GRID_COLUMNS - 1))
        column_width = max(1, usable_width / DASHBOARD_GRID_COLUMNS)
        return self._normalized_dashboard_width(round((pixel_width + DASHBOARD_GRID_GAP) / (column_width + DASHBOARD_GRID_GAP)))

    def _dashboard_height_from_pixels(self, height: object) -> int:
        try:
            pixel_height = int(height)
        except (TypeError, ValueError):
            return 3
        return self._normalized_dashboard_height(round(pixel_height / DASHBOARD_GRID_ROW_HEIGHT))

    def _dashboard_column_width(self) -> float:
        container_width = max(720, self.feature_grid_container.width())
        usable_width = max(1, container_width - DASHBOARD_GRID_GAP * (DASHBOARD_GRID_COLUMNS - 1))
        return usable_width / DASHBOARD_GRID_COLUMNS

    def _dashboard_item_pixel_width(self, width: int) -> int:
        column_width = self._dashboard_column_width()
        return int(round(column_width * width + DASHBOARD_GRID_GAP * max(0, width - 1)))

    def _dashboard_item_pixel_height(self, height: int) -> int:
        return int(DASHBOARD_GRID_ROW_HEIGHT * height + DASHBOARD_GRID_GAP * max(0, height - 1))

    def _resize_feature_dashboard_item(
        self,
        feature_key: str,
        width: object | None = None,
        height: object | None = None,
    ) -> None:
        items = [dict(item) for item in self._current_feature_dashboard_layout()]
        changed = False
        for item in items:
            if str(item.get("key", "")) != feature_key:
                continue
            if width is not None:
                item["w"] = self._normalized_feature_dashboard_width(
                    feature_key,
                    self._dashboard_width_from_pixels(width),
                )
                changed = True
            if height is not None:
                item["h"] = self._normalized_feature_dashboard_height(
                    feature_key,
                    self._dashboard_height_from_pixels(height),
                )
                changed = True
            break
        if not changed:
            return
        self.feature_dashboard_items = self._pack_feature_dashboard_items(items)
        self._render_feature_dashboard()
        self.save_last_layout_state()

    def _move_feature_in_dashboard(self, source_key: str, target_key: str, placement: str = "after") -> None:
        items = [dict(item) for item in self._current_feature_dashboard_layout()]
        source_item = next((item for item in items if str(item.get("key", "")) == source_key), None)
        target_item = next((item for item in items if str(item.get("key", "")) == target_key), None)
        if source_item is None or target_item is None:
            return
        source_slot = {
            "x": self._normalized_dashboard_x(source_item.get("x"), self._normalized_dashboard_width(source_item.get("w"))),
            "y": self._normalized_dashboard_y(source_item.get("y")),
            "w": self._normalized_dashboard_width(source_item.get("w")),
            "h": self._normalized_dashboard_height(source_item.get("h")),
        }
        target_slot = {
            "x": self._normalized_dashboard_x(target_item.get("x"), self._normalized_dashboard_width(target_item.get("w"))),
            "y": self._normalized_dashboard_y(target_item.get("y")),
            "w": self._normalized_dashboard_width(target_item.get("w")),
            "h": self._normalized_dashboard_height(target_item.get("h")),
        }
        source_item.update(target_slot)
        target_item.update(source_slot)
        self.feature_dashboard_items = self._pack_feature_dashboard_items(items)
        self._render_feature_dashboard()
        self.save_last_layout_state()
        self.statusBar().showMessage("패널 위치를 바꿨습니다.", 1800)

    def _move_feature_to_dashboard_end(self, source_key: str) -> None:
        items = [dict(item) for item in self._current_feature_dashboard_layout()]
        source_item = next((item for item in items if str(item.get("key", "")) == source_key), None)
        if source_item is None:
            return
        items = [item for item in items if str(item.get("key", "")) != source_key]
        items.append(source_item)
        self.feature_dashboard_items = self._pack_feature_dashboard_items(items)
        self._render_feature_dashboard()
        self.save_last_layout_state()

    def _move_feature_to_dashboard_position(self, source_key: str, global_position: QPoint) -> bool:
        items = [dict(item) for item in self._current_feature_dashboard_layout()]
        source_item = next((item for item in items if str(item.get("key", "")) == source_key), None)
        if source_item is None:
            return False
        position = self._dashboard_grid_position_from_global(
            global_position,
            self._normalized_dashboard_width(source_item.get("w")),
        )
        if position is None:
            return False
        source_item["x"], source_item["y"] = position
        self.feature_dashboard_items = self._pack_feature_dashboard_items(items)
        self._render_feature_dashboard()
        self.save_last_layout_state()
        self.statusBar().showMessage("패널 위치를 바꿨습니다.", 1800)
        return True

    def _dashboard_grid_position_from_global(self, global_position: QPoint, width: int = 1) -> tuple[int, int] | None:
        container = getattr(self, "feature_grid_container", None)
        if not isinstance(container, QWidget):
            return None
        local_position = container.mapFromGlobal(global_position)
        if not container.rect().contains(local_position):
            return None
        column_step = self._dashboard_column_width() + DASHBOARD_GRID_GAP
        row_step = DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP
        column = round(local_position.x() / max(1, column_step))
        row = round(local_position.y() / max(1, row_step))
        return self._normalized_dashboard_x(column, width), self._normalized_dashboard_y(row)

    def _show_dashboard_drag_guides(self, source_key: str, global_position: QPoint) -> None:
        overlay = getattr(self, "dashboard_guide_overlay", None)
        container = getattr(self, "feature_grid_container", None)
        if not isinstance(overlay, DashboardGridGuideOverlay) or not isinstance(container, QWidget):
            return
        overlay.hide()
        overlay.setGeometry(container.rect())
        preview_item = self._dashboard_preview_item(source_key, global_position)
        overlay.set_preview_rect(self._dashboard_item_rect(preview_item) if preview_item else QRectF())
        overlay.raise_()
        overlay.show()

    def _hide_dashboard_drag_guides(self) -> None:
        overlay = getattr(self, "dashboard_guide_overlay", None)
        if isinstance(overlay, DashboardGridGuideOverlay):
            overlay.hide()
            overlay.set_preview_rect(QRectF())

    def _dashboard_preview_item(self, source_key: str, global_position: QPoint) -> dict[str, object] | None:
        target = self._feature_drop_target_at(global_position, source_key)
        items = [dict(item) for item in self._current_feature_dashboard_layout()]
        source_item = next((item for item in items if str(item.get("key", "")) == source_key), None)
        if source_item is None:
            return None
        if target is not None:
            target_kind, target_key, _placement = target
            if target_kind == "feature":
                target_item = next((item for item in items if str(item.get("key", "")) == target_key), None)
                if target_item is not None:
                    return {
                        "key": source_key,
                        "x": self._normalized_dashboard_x(
                            target_item.get("x"),
                            self._normalized_dashboard_width(target_item.get("w")),
                        ),
                        "y": self._normalized_dashboard_y(target_item.get("y")),
                        "w": self._normalized_dashboard_width(target_item.get("w")),
                        "h": self._normalized_dashboard_height(target_item.get("h")),
                    }

        position = self._dashboard_grid_position_from_global(
            global_position,
            self._normalized_dashboard_width(source_item.get("w")),
        )
        if position is None:
            return source_item
        column, row = position
        return {
            "key": source_key,
            "x": column,
            "y": row,
            "w": self._normalized_dashboard_width(source_item.get("w")),
            "h": self._normalized_dashboard_height(source_item.get("h")),
        }

    def _dashboard_item_rect(self, item: dict[str, object]) -> QRectF:
        width = self._normalized_dashboard_width(item.get("w"))
        height = self._normalized_dashboard_height(item.get("h"))
        column = int(item.get("x", 0))
        row = int(item.get("y", 0))
        return QRectF(
            column * (self._dashboard_column_width() + DASHBOARD_GRID_GAP),
            row * (DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP),
            self._dashboard_item_pixel_width(width),
            self._dashboard_item_pixel_height(height),
        )

    def _render_feature_dashboard(self) -> None:
        layout = getattr(self, "feature_dashboard_layout", None)
        if not isinstance(layout, QGridLayout):
            return

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if isinstance(widget, FeatureCell):
                widget.detach_feature_box()
                widget.hide()
                _park_widget_for_reparent(widget)
                widget.deleteLater()
            elif widget is not None:
                widget.hide()
                _park_widget_for_reparent(widget)
                widget.deleteLater()
        self.feature_cells = {}
        overlay = getattr(self, "dashboard_guide_overlay", None)
        if isinstance(overlay, DashboardGridGuideOverlay):
            overlay.setGeometry(self.feature_grid_container.rect())
            overlay.raise_()

        all_items = self._normalized_feature_dashboard_layout({"dashboard": self.feature_dashboard_items})
        self.feature_dashboard_items = all_items
        visible_items = self._pack_feature_dashboard_items(
            [dict(item) for item in all_items if self._feature_should_be_visible(str(item.get("key", "")))]
        )

        previous_rows = int(getattr(self, "feature_dashboard_row_count", 0) or 0)
        max_row = max((int(item.get("y", 0)) + int(item.get("h", 1)) for item in visible_items), default=1)
        for row in range(max(previous_rows, max_row + 1) + 1):
            layout.setRowMinimumHeight(row, 0)
            layout.setRowStretch(row, 0)
        for row in range(max_row):
            layout.setRowMinimumHeight(row, DASHBOARD_GRID_ROW_HEIGHT)
        layout.setRowStretch(max_row, 1)
        self.feature_dashboard_row_count = max_row + 1

        for item in visible_items:
            key = str(item.get("key", ""))
            widget = self.feature_boxes.get(key)
            if widget is None:
                continue
            width = self._normalized_dashboard_width(item.get("w"))
            height = self._normalized_dashboard_height(item.get("h"))
            widget.hide()
            cell = FeatureCell(key, widget)
            cell.hide()
            cell.set_panel_height(self._dashboard_item_pixel_height(height))
            cell.set_panel_width(self._dashboard_item_pixel_width(width), fixed=False)
            self.feature_cells[key] = cell
            layout.addWidget(
                cell,
                int(item.get("y", 0)),
                int(item.get("x", 0)),
                height,
                width,
            )
            cell.show()
            widget.show()
        overlay = getattr(self, "dashboard_guide_overlay", None)
        if isinstance(overlay, DashboardGridGuideOverlay):
            overlay.setGeometry(self.feature_grid_container.rect())
            overlay.raise_()

    def _sync_feature_dashboard_visibility(self) -> None:
        self._render_feature_dashboard()

    def _current_feature_grid_layout(self) -> list[dict[str, object]]:
        if hasattr(self, "feature_dashboard_layout"):
            items = []
            for item in self._current_feature_dashboard_layout():
                key = str(item.get("key", ""))
                width = int(item.get("w", self._default_feature_dashboard_width(key)))
                span = self._legacy_span_from_dashboard_width(width)
                items.append({"key": key, "span": span})
            return items
        if hasattr(self, "feature_rows_layout"):
            items: list[dict[str, object]] = []
            for row in self._current_feature_rows_layout():
                columns = self._normalized_row_columns(row)
                sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
                total = max(1, sum(sizes))
                for column, size in zip(columns, sizes, strict=False):
                    span = min(3, max(1, int(round((size / total) * 3))))
                    for key in column.get("items", []):
                        items.append({"key": str(key), "span": span})
            return items
        order = [key for key in self.feature_grid_order if key in self.feature_boxes]
        for key in self.feature_boxes:
            if key not in order:
                order.append(key)
        return [{"key": key, "span": self.feature_grid_span(key)} for key in order]

    def feature_grid_span(self, feature_key: str) -> int:
        if hasattr(self, "feature_dashboard_layout"):
            for item in self._current_feature_dashboard_layout():
                if str(item.get("key", "")) == feature_key:
                    width = int(item.get("w", self._default_feature_dashboard_width(feature_key)))
                    return self._legacy_span_from_dashboard_width(width)
            return 1
        if hasattr(self, "feature_rows_layout"):
            for row in self._current_feature_rows_layout():
                columns = self._normalized_row_columns(row)
                target_column_index = next(
                    (index for index, column in enumerate(columns) if feature_key in [str(key) for key in column.get("items", [])]),
                    -1,
                )
                if target_column_index < 0:
                    continue
                if len(columns) == 1:
                    return 3
                sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
                total = max(1, sum(sizes))
                return min(3, max(1, int(round((sizes[target_column_index] / total) * 3))))
            return 1
        return min(3, max(1, int(self.feature_grid_spans.get(feature_key, 1))))

    def feature_panel_height(self, feature_key: str) -> int:
        cell = getattr(self, "feature_cells", {}).get(feature_key)
        if isinstance(cell, FeatureCell):
            return cell.panel_height
        if hasattr(self, "feature_dashboard_layout"):
            for item in self._current_feature_dashboard_layout():
                if str(item.get("key", "")) == feature_key:
                    return self._dashboard_item_pixel_height(self._normalized_dashboard_height(item.get("h")))
        for row in getattr(self, "feature_layout_rows", []):
            keys = [str(key) for key in row.get("items", [])]
            if feature_key not in keys:
                continue
            heights = self._normalized_item_heights(row.get("heights"), keys)
            return heights[keys.index(feature_key)]
        return self._default_feature_panel_height(feature_key)

    def feature_panel_width(self, feature_key: str) -> int:
        cell = getattr(self, "feature_cells", {}).get(feature_key)
        if isinstance(cell, FeatureCell):
            return cell.panel_width
        if hasattr(self, "feature_dashboard_layout"):
            for item in self._current_feature_dashboard_layout():
                if str(item.get("key", "")) == feature_key:
                    return self._dashboard_item_pixel_width(self._normalized_dashboard_width(item.get("w")))
        for row in getattr(self, "feature_layout_rows", []):
            columns = self._normalized_row_columns(row)
            sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
            for column_index, column in enumerate(columns):
                keys = [str(key) for key in column.get("items", [])]
                if feature_key not in keys:
                    continue
                widths = self._normalized_item_widths(
                    column.get("widths"),
                    keys,
                    fallback=sizes[column_index] if column_index < len(sizes) else 1000,
                )
                return widths[keys.index(feature_key)]
        return self._default_feature_panel_width(feature_key)

    def resize_feature_panel_height(self, feature_key: str, height: int) -> None:
        if feature_key not in self.feature_boxes:
            return
        if hasattr(self, "feature_dashboard_layout"):
            self._resize_feature_dashboard_item(feature_key, height=height)
            return
        normalized_height = self._normalized_item_height(height)
        cell = getattr(self, "feature_cells", {}).get(feature_key)
        if isinstance(cell, FeatureCell):
            cell.set_panel_height(normalized_height)
        self._ensure_row_can_show_feature_height(feature_key, normalized_height)
        self.feature_layout_rows = self._current_feature_rows_layout()
        self.save_last_layout_state()

    def resize_feature_panel_width(self, feature_key: str, width: int) -> None:
        if feature_key not in self.feature_boxes:
            return
        if hasattr(self, "feature_dashboard_layout"):
            self._resize_feature_dashboard_item(feature_key, width=width)
            return
        normalized_width = self._normalized_item_width(width)
        cell = getattr(self, "feature_cells", {}).get(feature_key)
        if isinstance(cell, FeatureCell):
            cell.set_panel_width(normalized_width)

        location = self._feature_row_column_location(feature_key)
        if location is None:
            self.feature_layout_rows = self._current_feature_rows_layout()
            self.save_last_layout_state()
            return

        row_splitter, _column_index = location
        self._sync_feature_row_splitter_widths(row_splitter)
        self.feature_layout_rows = self._current_feature_rows_layout()
        self.save_last_layout_state()

    def _feature_row_column_location(self, feature_key: str) -> tuple[QSplitter, int] | None:
        for row_splitter in getattr(self, "feature_row_splitters", []):
            if not isinstance(row_splitter, QSplitter):
                continue
            for column_index in range(row_splitter.count()):
                column_widget = row_splitter.widget(column_index)
                if isinstance(column_widget, FeatureColumn) and feature_key in [str(key) for key in column_widget.items]:
                    return row_splitter, column_index
        return None

    def _column_preferred_width(self, column: dict[str, object]) -> int:
        items = [str(key) for key in column.get("items", []) if str(key) in self.feature_boxes]
        if not items:
            return 240
        widths = self._normalized_item_widths(column.get("widths"), items)
        return max(160, max(widths, default=240))

    def _feature_column_widget_preferred_width(self, column_widget: FeatureColumn) -> int:
        widths: list[int] = []
        for key in column_widget.items:
            key = str(key)
            cell = getattr(self, "feature_cells", {}).get(key)
            if isinstance(cell, FeatureCell):
                widths.append(self._normalized_item_width(cell.panel_width))
            else:
                widths.append(self._default_feature_panel_width(key))
        return max(160, max(widths, default=240))

    def _sync_feature_row_splitter_widths(self, splitter: QSplitter) -> None:
        sizes: list[int] = []
        spacer_indices: list[int] = []
        feature_total = 0
        for index in range(splitter.count()):
            widget = splitter.widget(index)
            if isinstance(widget, FeatureColumn):
                preferred_width = self._feature_column_widget_preferred_width(widget)
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(preferred_width)
                sizes.append(preferred_width)
                feature_total += preferred_width
            else:
                spacer_indices.append(index)
                sizes.append(1)
        if not sizes:
            return
        available_width = max(0, self.feature_grid_container.width())
        spacer_width = max(1, available_width - feature_total)
        for spacer_index in spacer_indices:
            sizes[spacer_index] = spacer_width
        splitter.setSizes(sizes)

    def resize_feature_grid_span(self, feature_key: str, span: int) -> None:
        if hasattr(self, "feature_dashboard_layout"):
            normalized_span = min(3, max(1, int(span)))
            items = [dict(item) for item in self._current_feature_dashboard_layout()]
            for item in items:
                if str(item.get("key", "")) == feature_key:
                    item["w"] = self._normalized_feature_dashboard_width(
                        feature_key,
                        self._dashboard_width_from_legacy_span(normalized_span),
                    )
                    break
            self.feature_dashboard_items = self._pack_feature_dashboard_items(items)
            self._render_feature_dashboard()
            self.save_last_layout_state()
            return
        if hasattr(self, "feature_rows_layout"):
            normalized_span = min(3, max(1, int(span)))
            rows = self._current_feature_rows_layout()
            next_rows: list[dict[str, object]] = []
            moved = False
            moved_height = self.feature_panel_height(feature_key)
            moved_width = self.feature_panel_width(feature_key)
            for row in rows:
                columns = self._normalized_row_columns(row)
                sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
                next_columns: list[dict[str, object]] = []
                next_sizes: list[int] = []
                row_had_feature = False
                for column_index, column in enumerate(columns):
                    items = [str(key) for key in column.get("items", [])]
                    heights = self._normalized_item_heights(column.get("heights"), items)
                    widths = self._normalized_item_widths(
                        column.get("widths"),
                        items,
                        fallback=sizes[column_index] if column_index < len(sizes) else 1000,
                    )
                    kept_items: list[str] = []
                    kept_heights: list[int] = []
                    kept_widths: list[int] = []
                    for key, item_height, item_width in zip(items, heights, widths, strict=False):
                        if key == feature_key:
                            row_had_feature = True
                            moved = True
                            moved_height = item_height
                            moved_width = item_width
                            continue
                        kept_items.append(key)
                        kept_heights.append(item_height)
                        kept_widths.append(item_width)
                    if kept_items:
                        next_columns.append({"items": kept_items, "heights": kept_heights, "widths": kept_widths})
                        next_sizes.append(max(kept_widths, default=sizes[column_index] if column_index < len(sizes) else 1000))
                if next_columns:
                    next_rows.append(self._row_from_columns(next_columns, next_sizes, row.get("height")))
                if row_had_feature:
                    next_rows.append(
                        self._row_from_columns(
                            [{"items": [feature_key], "heights": [moved_height], "widths": [moved_width]}],
                            [moved_width],
                            moved_height,
                        )
                    )
            if not moved:
                moved_height = self.feature_panel_height(feature_key)
                moved_width = self.feature_panel_width(feature_key)
                next_rows.append(
                    self._row_from_columns(
                        [{"items": [feature_key], "heights": [moved_height], "widths": [moved_width]}],
                        [moved_width],
                        moved_height,
                    )
                )
            self.feature_layout_rows = next_rows
            self._render_feature_rows()
            self.save_last_layout_state()
            return
        if feature_key not in self.feature_boxes:
            return
        normalized_span = min(3, max(1, int(span)))
        if self.feature_grid_span(feature_key) == normalized_span:
            return
        self.feature_grid_spans[feature_key] = normalized_span
        if feature_key not in self.feature_grid_order:
            self.feature_grid_order.append(feature_key)
        self._render_feature_grid()
        self.save_last_layout_state()

    def _apply_feature_grid_layout(self, layout_state: object) -> None:
        grid_items = self._normalized_feature_grid_layout(layout_state)
        self.feature_grid_order = [str(item["key"]) for item in grid_items]
        self.feature_grid_spans = {str(item["key"]): int(item["span"]) for item in grid_items}
        self._render_feature_grid()

    def _apply_feature_rows_layout(self, layout_state: object) -> None:
        self.feature_layout_rows = self._normalized_feature_rows_layout(layout_state)
        self._render_feature_rows()

    def _current_feature_rows_layout(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        if getattr(self, "feature_row_splitters", None):
            row_heights = []
            rows_splitter = getattr(self, "feature_rows_splitter", None)
            if isinstance(rows_splitter, QSplitter):
                row_heights = self._normalized_row_sizes(rows_splitter.sizes(), len(self.feature_row_splitters))
            for row_index, splitter in enumerate(self.feature_row_splitters):
                columns: list[dict[str, object]] = []
                for column_index in range(splitter.count()):
                    column_widget = splitter.widget(column_index)
                    if not isinstance(column_widget, FeatureColumn):
                        continue
                    items = [str(key) for key in column_widget.items if str(key) in self.feature_boxes]
                    if not items:
                        continue
                    heights = [
                        self.feature_cells[key].panel_height
                        if key in getattr(self, "feature_cells", {})
                        else self._default_feature_panel_height(key)
                        for key in items
                    ]
                    widths = [
                        self.feature_cells[key].panel_width
                        if key in getattr(self, "feature_cells", {})
                        else self._default_feature_panel_width(key)
                        for key in items
                    ]
                    columns.append({"items": items, "heights": heights, "widths": widths})
                if not columns:
                    continue
                sizes = [self._column_preferred_width(column) for column in columns]
                stack_height = max(self._column_stack_height(column) for column in columns)
                height = row_heights[row_index] if row_index < len(row_heights) else stack_height
                rows.append(self._row_from_columns(columns, sizes, max(height, stack_height)))
        else:
            for row in getattr(self, "feature_layout_rows", []):
                columns = self._normalized_row_columns(row)
                if columns:
                    sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
                    rows.append(self._row_from_columns(columns, sizes, row.get("height")))

        seen = {key for row in rows for key in row.get("items", [])}
        for default_row in self.default_feature_rows_layout():
            missing = [str(key) for key in default_row.get("items", []) if str(key) in self.feature_boxes and str(key) not in seen]
            if missing:
                heights = [self._default_feature_panel_height(key) for key in missing]
                columns = [
                    {"items": [key], "heights": [height], "widths": [self._default_feature_panel_width(key)]}
                    for key, height in zip(missing, heights, strict=False)
                ]
                rows.append(self._row_from_columns(columns, [self._default_feature_panel_width(key) for key in missing], max(heights)))
                seen.update(missing)
        return rows

    def _normalized_feature_rows_layout(self, layout_state: object) -> list[dict[str, object]]:
        raw_rows: object = None
        if isinstance(layout_state, dict):
            raw_rows = layout_state.get("rows")
        elif isinstance(layout_state, list) and any(isinstance(item, (dict, list, tuple)) for item in layout_state):
            raw_rows = layout_state

        feature_keys = set(self.feature_boxes)
        rows: list[dict[str, object]] = []
        seen: set[str] = set()

        if isinstance(raw_rows, list):
            for raw_row in raw_rows:
                if isinstance(raw_row, dict):
                    raw_columns = self._normalized_row_columns(raw_row, seen)
                    raw_sizes = raw_row.get("sizes", [])
                    raw_height = raw_row.get("height", 0)
                else:
                    raw_columns = self._columns_from_flat_items(raw_row, [], seen)
                    raw_sizes = []
                    raw_height = 0
                raw_columns = [
                    column
                    for column in raw_columns
                    if any(str(key) in feature_keys for key in column.get("items", []))
                ]
                if not raw_columns:
                    continue
                for column in raw_columns:
                    seen.update(str(key) for key in column.get("items", []))
                sizes = self._normalized_row_sizes(raw_sizes, len(raw_columns))
                for start in range(0, len(raw_columns), FEATURE_ROW_MAX_COLUMNS):
                    row_columns = raw_columns[start : start + FEATURE_ROW_MAX_COLUMNS]
                    row_sizes = sizes[start : start + FEATURE_ROW_MAX_COLUMNS]
                    rows.append(self._row_from_columns(row_columns, row_sizes, raw_height))

        if not rows:
            rows = self._rows_from_grid_items(self._normalized_feature_grid_layout(layout_state))
            seen = {key for row in rows for key in row.get("items", [])}

        for default_row in self.default_feature_rows_layout():
            missing = [str(key) for key in default_row.get("items", []) if str(key) in feature_keys and str(key) not in seen]
            if missing:
                for start in range(0, len(missing), FEATURE_ROW_MAX_COLUMNS):
                    row_items = missing[start : start + FEATURE_ROW_MAX_COLUMNS]
                    heights = [self._default_feature_panel_height(key) for key in row_items]
                    columns = [
                        {"items": [key], "heights": [height], "widths": [self._default_feature_panel_width(key)]}
                        for key, height in zip(row_items, heights, strict=False)
                    ]
                    rows.append(
                        self._row_from_columns(
                            columns,
                            [self._default_feature_panel_width(key) for key in row_items],
                            max(heights),
                        )
                    )
                    seen.update(row_items)
        return rows

    def _rows_from_grid_items(self, grid_items: list[dict[str, object]]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        current_columns: list[dict[str, object]] = []
        current_sizes: list[int] = []
        current_width = 0

        def flush_current() -> None:
            nonlocal current_columns, current_sizes, current_width
            if current_columns:
                rows.append(self._row_from_columns(current_columns, current_sizes, 0))
            current_columns = []
            current_sizes = []
            current_width = 0

        for item in grid_items:
            key = str(item.get("key", ""))
            if key not in self.feature_boxes:
                continue
            try:
                span = int(item.get("span", 1))
            except (TypeError, ValueError):
                span = 1
            span = min(3, max(1, span))
            default_width = self._default_feature_panel_width(key)
            if span >= 3:
                flush_current()
                height = self._default_feature_panel_height(key)
                rows.append(
                    self._row_from_columns(
                        [{"items": [key], "heights": [height], "widths": [default_width]}],
                        [default_width],
                        height,
                    )
                )
                continue
            if current_columns and current_width + span > 3:
                flush_current()
            current_columns.append(
                {
                    "items": [key],
                    "heights": [self._default_feature_panel_height(key)],
                    "widths": [default_width],
                }
            )
            current_sizes.append(default_width)
            current_width += span
            if current_width >= 3 or len(current_columns) >= FEATURE_ROW_MAX_COLUMNS:
                flush_current()
        flush_current()
        return rows

    def _row_from_columns(
        self,
        columns: list[dict[str, object]],
        sizes: object,
        height: object = 0,
    ) -> dict[str, object]:
        normalized_columns: list[dict[str, object]] = []
        flattened_items: list[str] = []
        flattened_heights: list[int] = []
        flattened_widths: list[int] = []
        column_sizes: list[int] = []
        normalized_sizes = self._normalized_row_sizes(sizes, len(columns))
        for column_index, column in enumerate(columns):
            items = [str(key) for key in column.get("items", []) if str(key) in self.feature_boxes]
            if not items:
                continue
            heights = self._normalized_item_heights(column.get("heights"), items)
            fallback_width = normalized_sizes[column_index] if column_index < len(normalized_sizes) else 1000
            widths = self._normalized_item_widths(column.get("widths"), items, fallback=fallback_width)
            normalized_columns.append({"items": items, "heights": heights, "widths": widths})
            column_sizes.append(max(160, max(widths, default=fallback_width)))
            flattened_items.extend(items)
            flattened_heights.extend(heights)
            flattened_widths.extend(widths)

        stack_height = max((self._column_stack_height(column) for column in normalized_columns), default=1000)
        normalized_height = max(self._normalized_row_height(height), stack_height)
        return {
            "columns": normalized_columns,
            "sizes": column_sizes,
            "height": normalized_height,
            # Kept for old layout-profile readers and tests.
            "items": flattened_items,
            "heights": flattened_heights,
            "widths": flattened_widths,
        }

    def _normalized_row_columns(
        self,
        row: object,
        seen: set[str] | None = None,
    ) -> list[dict[str, object]]:
        if not isinstance(row, dict):
            return self._columns_from_flat_items(row, [], seen)

        raw_columns = row.get("columns")
        if isinstance(raw_columns, list):
            columns: list[dict[str, object]] = []
            for raw_column in raw_columns:
                if isinstance(raw_column, dict):
                    raw_items = raw_column.get("items", [])
                    raw_heights = raw_column.get("heights", [])
                    raw_widths = raw_column.get("widths", [])
                else:
                    raw_items = raw_column
                    raw_heights = []
                    raw_widths = []
                columns.extend(
                    self._columns_from_flat_items(
                        [raw_items],
                        [raw_heights],
                        seen,
                        preserve_stack=True,
                        raw_widths=[raw_widths],
                    )
                )
            return columns

        return self._columns_from_flat_items(row.get("items", []), row.get("heights", []), seen, raw_widths=row.get("widths", []))

    def _columns_from_flat_items(
        self,
        raw_items: object,
        raw_heights: object,
        seen: set[str] | None = None,
        preserve_stack: bool = False,
        raw_widths: object = (),
    ) -> list[dict[str, object]]:
        if not isinstance(raw_items, (list, tuple)):
            return []
        if preserve_stack:
            columns: list[dict[str, object]] = []
            for index, raw_stack in enumerate(raw_items):
                stack_items = raw_stack if isinstance(raw_stack, (list, tuple)) else [raw_stack]
                stack_raw_heights = []
                if isinstance(raw_heights, (list, tuple)) and index < len(raw_heights):
                    stack_raw_heights = raw_heights[index] if isinstance(raw_heights[index], (list, tuple)) else [raw_heights[index]]
                stack_raw_widths = []
                if isinstance(raw_widths, (list, tuple)) and index < len(raw_widths):
                    stack_raw_widths = raw_widths[index] if isinstance(raw_widths[index], (list, tuple)) else [raw_widths[index]]
                items = [
                    str(key)
                    for key in stack_items
                    if str(key) in self.feature_boxes and (seen is None or str(key) not in seen)
                ]
                if not items:
                    continue
                heights = self._normalized_item_heights(stack_raw_heights, items)
                widths = self._normalized_item_widths(stack_raw_widths, items)
                columns.append({"items": items, "heights": heights, "widths": widths})
            return columns

        items = [
            str(key)
            for key in raw_items
            if str(key) in self.feature_boxes and (seen is None or str(key) not in seen)
        ]
        heights = self._normalized_item_heights(raw_heights, items)
        widths = self._normalized_item_widths(raw_widths, items)
        return [
            {"items": [key], "heights": [height], "widths": [width]}
            for key, height, width in zip(items, heights, widths, strict=False)
        ]

    def _column_stack_height(self, column: dict[str, object]) -> int:
        items = [str(key) for key in column.get("items", []) if str(key) in self.feature_boxes]
        if not items:
            return 80
        heights = self._normalized_item_heights(column.get("heights"), items)
        spacing = 14 * max(0, len(items) - 1)
        return sum(heights) + spacing

    def _normalized_row_sizes(self, sizes: object, count: int) -> list[int]:
        if count <= 0:
            return []
        parsed: list[int] = []
        if isinstance(sizes, (list, tuple)):
            for size in sizes[:count]:
                try:
                    parsed.append(max(1, int(size)))
                except (TypeError, ValueError):
                    parsed.append(1000)
        if len(parsed) < count:
            parsed.extend([1000] * (count - len(parsed)))
        return parsed[:count]

    def _normalized_row_height(self, height: object) -> int:
        try:
            return max(80, int(height))
        except (TypeError, ValueError):
            return 1000

    def _normalized_item_height(self, height: object) -> int:
        try:
            return min(1400, max(80, int(height)))
        except (TypeError, ValueError):
            return 280

    def _normalized_item_width(self, width: object) -> int:
        try:
            raw_width = int(width)
        except (TypeError, ValueError):
            return 320
        snapped_width = int(round(raw_width / 20) * 20)
        return min(1800, max(160, snapped_width))

    def _normalized_item_widths(self, widths: object, keys: list[str], fallback: int = 1000) -> list[int]:
        parsed: list[int] = []
        if isinstance(widths, (list, tuple)):
            for raw_width in widths[: len(keys)]:
                parsed.append(self._normalized_item_width(raw_width))
        for key in keys[len(parsed) :]:
            fallback_width = fallback if fallback != 1000 else self._default_feature_panel_width(key)
            parsed.append(self._normalized_item_width(fallback_width))
        return parsed[: len(keys)]

    def _normalized_item_heights(self, heights: object, keys: list[str]) -> list[int]:
        parsed: list[int] = []
        if isinstance(heights, (list, tuple)):
            for raw_height in heights[: len(keys)]:
                parsed.append(self._normalized_item_height(raw_height))
        for key in keys[len(parsed) :]:
            parsed.append(self._default_feature_panel_height(key))
        return parsed[: len(keys)]

    def _default_feature_panel_height(self, feature_key: str) -> int:
        if feature_key == "header_banner":
            return _normalize_header_banner_height(self.preferences.header_banner_height) + 40
        return {
            "datetime": 110,
            "focus": 560,
            "pomodoro": 190,
            "quick_memo": 440,
            "today_timeline": 620,
            "today_checklist": 430,
            "link_favorites": 320,
        }.get(feature_key, 280)

    def _default_feature_panel_width(self, feature_key: str) -> int:
        return {
            "header_banner": 1040,
            "today_timeline": 920,
            "focus": 760,
            "quick_memo": 680,
            "today_checklist": 460,
            "link_favorites": 420,
            "pomodoro": 360,
            "datetime": 280,
        }.get(feature_key, 420)

    def _default_inserted_column_size(self, current_sizes: list[int]) -> int:
        if not current_sizes:
            return 1000
        return max(320, int(sum(current_sizes) / max(1, len(current_sizes))))

    def _ensure_row_can_show_feature_height(self, feature_key: str, height: int) -> None:
        rows_splitter = getattr(self, "feature_rows_splitter", None)
        if not isinstance(rows_splitter, QSplitter):
            return
        for row_index, splitter in enumerate(getattr(self, "feature_row_splitters", [])):
            keys = splitter.property("featureKeys")
            if not isinstance(keys, list) or feature_key not in keys:
                continue
            row_sizes = rows_splitter.sizes()
            if len(row_sizes) != rows_splitter.count():
                return
            stack_heights: list[int] = []
            for column_index in range(splitter.count()):
                column_widget = splitter.widget(column_index)
                if not isinstance(column_widget, FeatureColumn):
                    continue
                stack_heights.append(
                    sum(
                        self.feature_cells[key].panel_height
                        if key in getattr(self, "feature_cells", {})
                        else self._default_feature_panel_height(str(key))
                        for key in column_widget.items
                    )
                    + 14 * max(0, len(column_widget.items) - 1)
                )
            target_height = max(80, max(stack_heights, default=80), int(height))
            if row_index < len(row_sizes):
                row_sizes[row_index] = target_height
                rows_splitter.setSizes(row_sizes)
            return

    def _render_feature_rows(self) -> None:
        layout = getattr(self, "feature_rows_layout", None)
        if not isinstance(layout, QVBoxLayout):
            return
        rows_splitter = getattr(self, "feature_rows_splitter", None)
        if not isinstance(rows_splitter, QSplitter):
            return

        for splitter in getattr(self, "feature_row_splitters", []):
            splitter.hide()
            while splitter.count():
                widget = splitter.widget(0)
                if widget is None:
                    break
                if isinstance(widget, FeatureColumn):
                    widget.detach_feature_boxes()
                elif isinstance(widget, FeatureCell):
                    widget.detach_feature_box()
                widget.hide()
                _park_widget_for_reparent(widget)
                widget.deleteLater()
            splitter.hide()
            _park_widget_for_reparent(splitter)
            splitter.deleteLater()
        self.feature_row_splitters = []
        self.feature_cells = {}

        while rows_splitter.count():
            widget = rows_splitter.widget(0)
            if widget is None:
                break
            widget.hide()
            _park_widget_for_reparent(widget)

        normalized_rows = self._normalized_feature_rows_layout({"rows": self.feature_layout_rows})
        self.feature_layout_rows = normalized_rows
        row_heights: list[int] = []
        for row in normalized_rows:
            columns = self._normalized_row_columns(row)[:FEATURE_ROW_MAX_COLUMNS]
            if not columns:
                continue
            sizes = self._normalized_row_sizes(row.get("sizes"), len(columns))
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.hide()
            splitter.setObjectName("featureRowSplitter")
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(8)
            row_keys = [str(key) for column in columns for key in column.get("items", [])]
            splitter.setProperty("featureKeys", row_keys)
            splitter.setMinimumHeight(60)
            splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            stack_heights: list[int] = []
            splitter_sizes: list[int] = []
            for column_index, column in enumerate(columns):
                column_items = [str(key) for key in column.get("items", []) if str(key) in self.feature_boxes]
                column_heights = self._normalized_item_heights(column.get("heights"), column_items)
                column_widths = self._normalized_item_widths(
                    column.get("widths"),
                    column_items,
                    fallback=sizes[column_index] if column_index < len(sizes) else 1000,
                )
                column_preferred_width = max(160, max(column_widths, default=240))
                column_widget = FeatureColumn(column_items, self.swap_feature_panels)
                column_widget.hide()
                column_widget.setMinimumWidth(0)
                column_widget.setMaximumWidth(column_preferred_width)
                for key, item_height, item_width in zip(column_items, column_heights, column_widths, strict=False):
                    widget = self.feature_boxes[key]
                    widget.hide()
                    cell = FeatureCell(key, widget)
                    cell.hide()
                    cell.set_panel_height(item_height)
                    cell.set_panel_width(item_width)
                    self.feature_cells[key] = cell
                    column_widget.add_cell(cell)
                column_widget.finish()
                column_widget.setMinimumHeight(sum(column_heights) + 14 * max(0, len(column_items) - 1))
                splitter.addWidget(column_widget)
                splitter.setStretchFactor(splitter.count() - 1, 0)
                splitter_sizes.append(column_preferred_width)
                stack_heights.append(sum(column_heights) + 14 * max(0, len(column_items) - 1))
            spacer = QWidget()
            spacer.setObjectName("featureWidthSpacer")
            spacer.setMinimumWidth(0)
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            splitter.addWidget(spacer)
            splitter.setStretchFactor(splitter.count() - 1, 1)
            splitter_sizes.append(max(1, self.feature_grid_container.width() - sum(splitter_sizes)))
            splitter.setSizes(splitter_sizes)
            splitter.splitterMoved.connect(
                lambda _pos, _index, row_splitter=splitter: self._on_feature_row_splitter_moved(row_splitter)
            )
            self.feature_row_splitters.append(splitter)
            rows_splitter.addWidget(splitter)
            row_heights.append(max(self._normalized_row_height(row.get("height")), max(stack_heights, default=80)))
            QTimer.singleShot(0, lambda row_splitter=splitter, row_sizes=splitter_sizes: row_splitter.setSizes(row_sizes))

        rows_splitter.setSizes(row_heights)
        QTimer.singleShot(0, lambda row_sizes=row_heights: rows_splitter.setSizes(row_sizes))
        self._sync_feature_row_visibility()

    def _on_feature_row_splitter_moved(self, splitter: QSplitter) -> None:
        keys = splitter.property("featureKeys")
        if not isinstance(keys, list):
            return
        self.feature_layout_rows = self._current_feature_rows_layout()
        self.save_last_layout_state()

    def _on_feature_rows_splitter_moved(self, _position: int, _index: int) -> None:
        self.feature_layout_rows = self._current_feature_rows_layout()
        self.save_last_layout_state()

    def _sync_feature_row_visibility(self) -> None:
        for splitter in getattr(self, "feature_row_splitters", []):
            keys = splitter.property("featureKeys")
            if isinstance(keys, list):
                for key in keys:
                    key = str(key)
                    visible = self._feature_should_be_visible(key)
                    cell = getattr(self, "feature_cells", {}).get(key)
                    if isinstance(cell, FeatureCell):
                        cell.setVisible(visible)
                    widget = self.feature_boxes.get(key)
                    if isinstance(widget, QWidget):
                        widget.setVisible(visible)
                for column_index in range(splitter.count()):
                    column_widget = splitter.widget(column_index)
                    if isinstance(column_widget, FeatureColumn):
                        column_widget.setVisible(
                            any(self._feature_should_be_visible(str(key)) for key in column_widget.items)
                        )
            visible = (
                any(self._feature_should_be_visible(str(key)) for key in keys)
                if isinstance(keys, list)
                else any(not splitter.widget(index).isHidden() for index in range(splitter.count()))
            )
            splitter.setVisible(visible)

    def _feature_should_be_visible(self, feature_key: str) -> bool:
        attribute = self._feature_visibility_attribute(feature_key)
        return True if attribute is None else bool(getattr(self.preferences, attribute))

    def _normalized_feature_grid_layout(self, layout_state: object) -> list[dict[str, object]]:
        raw_grid: object = None
        if isinstance(layout_state, list):
            raw_grid = layout_state
        elif isinstance(layout_state, dict):
            raw_grid = layout_state.get("grid")

        feature_keys = set(self.feature_boxes)
        default_spans = {
            str(item["key"]): min(3, max(1, int(item["span"])))
            for item in self.default_feature_grid_layout()
            if str(item.get("key", "")) in feature_keys
        }
        items: list[dict[str, object]] = []
        seen: set[str] = set()

        if isinstance(raw_grid, list):
            for raw_item in raw_grid:
                if isinstance(raw_item, dict):
                    key = str(raw_item.get("key", ""))
                    span_value = raw_item.get("span", default_spans.get(key, 1))
                else:
                    key = str(raw_item)
                    span_value = default_spans.get(key, 1)
                if key not in feature_keys or key in seen:
                    continue
                try:
                    span = int(span_value)
                except (TypeError, ValueError):
                    span = default_spans.get(key, 1)
                items.append({"key": key, "span": min(3, max(1, span))})
                seen.add(key)
        elif isinstance(layout_state, dict):
            legacy_layout = self._normalized_feature_layout(layout_state)
            for section in ("left", "center", "right", "lower"):
                for token in legacy_layout.get(section, []):
                    if token in feature_keys and token not in seen:
                        items.append({"key": token, "span": default_spans.get(token, 1)})
                        seen.add(token)

        for raw_item in self.default_feature_grid_layout():
            key = str(raw_item["key"])
            if key in feature_keys and key not in seen:
                items.append({"key": key, "span": default_spans.get(key, 1)})
                seen.add(key)
        return items

    def _render_feature_grid(self) -> None:
        layout = getattr(self, "feature_grid_layout", None)
        if not isinstance(layout, QGridLayout):
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                _park_widget_for_reparent(widget)

        row = 0
        column = 0
        for key in self.feature_grid_order:
            widget = self.feature_boxes.get(key)
            if widget is None:
                continue
            span = self.feature_grid_span(key)
            if column and column + span > 3:
                row += 1
                column = 0
            layout.addWidget(widget, row, column, 1, span)
            widget.setVisible(self._feature_should_be_visible(key))
            column += span
            if column >= 3:
                row += 1
                column = 0
        for index in range(max(1, row + 1)):
            layout.setRowStretch(index, 0)
        layout.setRowStretch(max(1, row + 1), 1)

    def _normalized_feature_layout(self, layout_state: object) -> dict[str, list[str]]:
        default_layout = self.default_feature_layout()
        if not isinstance(layout_state, dict):
            return default_layout

        feature_keys = set(self.feature_boxes)
        result = {"body": [], "left": [], "center": [], "lower": [], "right": []}
        seen_features: set[str] = set()

        for splitter_name in ("body", "left", "center", "lower", "right"):
            raw_tokens = layout_state.get(splitter_name)
            if not isinstance(raw_tokens, list):
                raw_tokens = default_layout[splitter_name]
            for token in raw_tokens:
                if not isinstance(token, str):
                    continue
                if token == "group:left" and splitter_name == "body" and token not in result["body"]:
                    result["body"].append(token)
                elif token == "group:center" and splitter_name == "body" and token not in result["body"]:
                    result["body"].append(token)
                elif token == "group:right" and splitter_name == "body" and token not in result["body"]:
                    result["body"].append(token)
                elif token == "group:lower" and splitter_name == "left" and token not in result["left"]:
                    result["left"].append(token)
                elif splitter_name == "body" and token in feature_keys and token not in seen_features:
                    result["center"].append(str(token))
                    seen_features.add(str(token))
                elif token in feature_keys and token not in seen_features:
                    result[splitter_name].append(str(token))
                    seen_features.add(str(token))

        if "group:left" not in result["body"]:
            result["body"].insert(0, "group:left")
        if "group:center" not in result["body"]:
            insert_at = 1 if "group:left" in result["body"] else 0
            result["body"].insert(insert_at, "group:center")
        if "group:right" not in result["body"]:
            result["body"].append("group:right")
        if "group:lower" not in result["left"]:
            result["left"].append("group:lower")

        for splitter_name, tokens in default_layout.items():
            for token in tokens:
                if token in feature_keys and token not in seen_features:
                    result[splitter_name].append(token)
                    seen_features.add(token)

        return result

    def _reorder_splitter(self, splitter_name: str, tokens: list[str]) -> None:
        splitter = getattr(self, splitter_name, None)
        if splitter is None:
            return
        for index, token in enumerate(tokens):
            widget = self._widget_for_layout_token(token)
            if widget is None:
                continue
            splitter.insertWidget(index, widget)

    def _widget_for_layout_token(self, token: str) -> QWidget | None:
        if token == "group:left":
            return self.left_splitter
        if token == "group:center":
            return self.center_splitter
        if token == "group:right":
            return self.right_splitter
        if token == "group:lower":
            return self.lower_splitter
        return self.feature_boxes.get(token)

    def _splitter_child_tokens(self, splitter: QSplitter) -> list[str]:
        tokens: list[str] = []
        drop_zones = set(getattr(self, "column_drop_zones", {}).values())
        for index in range(splitter.count()):
            widget = splitter.widget(index)
            if widget in drop_zones:
                continue
            if widget is self.left_splitter:
                tokens.append("group:left")
            elif widget is self.center_splitter:
                tokens.append("group:center")
            elif widget is self.right_splitter:
                tokens.append("group:right")
            elif widget is self.lower_splitter:
                tokens.append("group:lower")
            else:
                feature_key = self._feature_key_for_widget(widget)
                if feature_key:
                    tokens.append(feature_key)
        return tokens

    def _remove_column_drop_zones(self) -> None:
        for zone in getattr(self, "column_drop_zones", {}).values():
            if isinstance(zone.parentWidget(), QSplitter):
                _park_widget_for_reparent(zone)
        for column_key in ("left", "center", "right"):
            splitter = self._column_splitter(column_key)
            if splitter is not None:
                splitter.setMinimumWidth(0)

    def _feature_key_for_widget(self, widget: QWidget) -> str:
        for feature_key, feature_widget in self.feature_boxes.items():
            if feature_widget is widget:
                return feature_key
        return ""

    def _splitter_sizes(self, splitter_name: str) -> list[int]:
        splitter = getattr(self, splitter_name, None)
        if splitter is None:
            return []
        return [int(size) for size in splitter.sizes()]

    def _set_splitter_sizes(self, splitter_name: str, sizes: object) -> None:
        splitter = getattr(self, splitter_name, None)
        if splitter is None or not isinstance(sizes, list):
            return
        parsed_sizes = [max(0, int(size)) for size in sizes if isinstance(size, (int, float))]
        if len(parsed_sizes) != splitter.count() or not any(parsed_sizes):
            return
        splitter.setSizes(parsed_sizes)

    def show_today_context_menu(self, position: QPoint) -> None:
        item = self.today_list.itemAt(position)
        if item is None:
            return
        self.today_list.setCurrentItem(item)

        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") not in {"task", "event"}:
            return

        menu = QMenu(self.today_list)
        complete_action = menu.addAction("완료 처리")
        complete_action.triggered.connect(self.complete_selected_today_item)

        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_today_item)
        menu.exec(self.today_list.mapToGlobal(position))

    def delete_selected_today_item(self) -> None:
        item = self.today_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") not in {"task", "event"}:
            QMessageBox.information(self, "오늘 흐름 삭제", "삭제할 항목을 선택하세요.")
            return

        item_type = str(data["type"])
        item_id = int(data["id"])
        title = self._today_item_title(item_type, item_id)
        kind = self._today_item_kind(item_type, item_id)
        answer = QMessageBox.question(self, "오늘 흐름 삭제", f"'{title}' {kind}을 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return

        if item_type == "task":
            self.repository.delete_task(item_id)
            if self.selected_task_id == item_id:
                self.selected_task_id = None
        else:
            self.repository.delete_event(item_id)

        self.refresh_today()
        self.statusBar().showMessage(f"{kind}을 삭제했습니다.", 2500)

    def _today_item_title(self, item_type: str, item_id: int) -> str:
        if item_type == "task":
            task = self.repository.get_task(item_id)
            return task.title if task else "선택한 항목"
        event = self.repository.get_event(item_id)
        return event.title if event else "선택한 항목"

    def _today_item_kind(self, item_type: str, item_id: int) -> str:
        if item_type == "task":
            task = self.repository.get_task(item_id)
            return _item_type_label(self.repository, "task", task.item_type_id if task else None)
        event = self.repository.get_event(item_id)
        return _item_type_label(self.repository, "event", event.item_type_id if event else None)

    def show_history_context_menu(self, position: QPoint) -> None:
        item = self.history_list.itemAt(position)
        if item is None:
            return
        self.history_list.setCurrentItem(item)
        if item.data(Qt.ItemDataRole.UserRole) is None:
            return

        menu = QMenu(self.history_list)
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_focus_history)
        menu.exec(self.history_list.mapToGlobal(position))

    def delete_selected_focus_history(self) -> None:
        item = self.history_list.currentItem()
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id is None:
            QMessageBox.information(self, "집중 기록 삭제", "삭제할 집중 기록을 선택하세요.")
            return

        self.delete_focus_session_by_id(int(session_id))

    def delete_focus_session_by_id(self, session_id: int) -> bool:
        session = self.repository.get_focus_session(session_id)
        title = session.title if session else "선택한 집중 기록"
        current_session = self.focus_timer.session if self.focus_timer else None
        is_active_session = current_session is not None and current_session.id == session_id
        message = f"'{title}' 집중 기록을 삭제할까요?"
        if is_active_session and current_session.status in {"running", "paused", "break"}:
            message += "\n진행 중인 타이머도 함께 중단됩니다."

        answer = QMessageBox.question(self, "집중 기록 삭제", message)
        if answer != QMessageBox.StandardButton.Yes:
            return False

        if is_active_session and self.focus_timer is not None:
            if current_session.status in {"running", "paused", "break"}:
                self.focus_timer.stop(status="cancelled")
            self.focus_timer.session = None
            self.focus_timer.last_tick_at = None
            self.focus_timer.segment_type = None
            self.focus_timer.segment_started_at = None
            self.break_until = None
            self.focus_tick_timer.stop()
            self.update_focus_display()

        self.repository.delete_focus_session(session_id)
        self.refresh_history()
        self.statusBar().showMessage("집중 기록을 삭제했습니다.", 2500)
        return True

    def start_focus(self) -> None:
        if self.focus_timer is None:
            return
        current = self.focus_timer.session
        if current is not None and current.status in {"running", "paused"}:
            answer = QMessageBox.question(self, "집중 세션", "현재 세션을 중단하고 새로 시작할까요?")
            if answer != QMessageBox.StandardButton.Yes:
                return

        targets = self._selected_focus_targets()
        primary_target = targets[0] if targets else None
        process_name = primary_target["process_name"] if primary_target else ""
        window_title = primary_target["window_title"] if primary_target else ""
        self.focus_timer.idle_cutoff_seconds = self.idle_cutoff_spin.value()
        self.focus_timer.start(
            title=self.focus_title_edit.text().strip() or "집중 세션",
            planned_seconds=self.planned_minutes_spin.value() * 60,
            target_process_name=process_name,
            target_window_title=window_title,
            target_windows=targets,
            task_id=self.selected_task_id,
        )
        self.break_until = None
        self.focus_tick_timer.start()
        self.update_focus_display()

    def pause_or_resume_focus(self) -> None:
        if self.focus_timer is None or self.focus_timer.session is None:
            return
        if self.focus_timer.session.status == "running":
            self.focus_timer.pause()
        elif self.focus_timer.session.status == "paused":
            self.focus_timer.resume()
        elif self.focus_timer.session.status == "break":
            self.focus_timer.end_break()
            self.break_until = None
        self.update_focus_display()

    def complete_focus(self) -> None:
        if self.focus_timer is None or self.focus_timer.session is None:
            return
        self.focus_timer.complete()
        self.break_until = None
        self.focus_tick_timer.stop()
        self.update_focus_display()
        self.refresh_history()

    def on_focus_tick(self) -> None:
        if self.focus_timer is None:
            return
        self.focus_timer.idle_cutoff_seconds = self.idle_cutoff_spin.value()
        session = self.focus_timer.tick()
        if session is not None and session.status == "break":
            now = datetime.now()
            if self.break_until is not None and now >= self.break_until:
                self.focus_timer.end_break(now)
                self.break_until = None
                session = self.focus_timer.session
        if session is not None and session.status == "completed":
            self.focus_tick_timer.stop()
            self.refresh_history()
        self.update_focus_display()

    def update_focus_display(self) -> None:
        session = self.focus_timer.session if self.focus_timer else None
        if session is None:
            planned = self.planned_minutes_spin.value() * 60
            remaining = planned
            status = "대기 중"
            title = self.focus_title_edit.text().strip() or "집중 대기"
            detail = "집중할 일을 고른 뒤 시작하세요. 화면 지정은 선택입니다."
            ratio = 1.0
            progress = 0
            pause_text = "일시정지"
            controls_enabled = False
            focused_seconds = 0
            away_seconds = 0
            paused_seconds = 0
        else:
            remaining = self._display_remaining_seconds(session)
            status = _status_label(session.status)
            title = session.title
            ratio = self.focus_timer.focus_ratio() if self.focus_timer else 1.0
            progress = int(1000 * min(1.0, session.focused_seconds / max(1, session.planned_seconds)))
            pause_text = "재개" if session.status in {"paused", "break"} else "일시정지"
            controls_enabled = session.status in {"running", "paused", "break"}
            focused_seconds = session.focused_seconds
            away_seconds = session.away_seconds
            paused_seconds = session.paused_seconds
            target = _focus_target_summary(session.target_process_name, session.target_window_title)
            detail = (
                f"집중 {_format_duration(session.focused_seconds)} · "
                f"이탈 {_format_duration(session.away_seconds)} · "
                f"일시정지 {_format_duration(session.paused_seconds)} · 화면 {target}"
            )

        self.focus_status_label.setText(status)
        self.remaining_time_label.setText(_format_clock(remaining))
        self.focus_detail_label.setText(detail)
        self.focus_ratio_label.setText(f"{int(ratio * 100)}%")
        self.focus_ratio_bar.setValue(int(ratio * 1000))
        self.focus_ratio_ring.set_ratio(ratio)
        self.update_focus_rate_display_mode()
        self.focus_progress.setValue(progress)
        if hasattr(self, "focus_focused_metric_label"):
            self.focus_focused_metric_label.setText(_format_duration(focused_seconds))
            self.focus_away_metric_label.setText(_format_duration(away_seconds))
            self.focus_paused_metric_label.setText(_format_duration(paused_seconds))
        if hasattr(self, "header_focus_status_label"):
            self.header_focus_status_label.setText(status)
            self.header_focus_time_label.setText(_format_clock(remaining))
            if hasattr(self, "header_focus_card"):
                self.header_focus_card.setToolTip(f"{title}\n{detail}")
        self.pause_focus_button.setText(pause_text)
        self.pause_focus_button.setEnabled(controls_enabled)
        self.complete_focus_button.setEnabled(controls_enabled)

        self.compact_title_label.setText(title)
        self.compact_time_label.setText(_format_clock(remaining))
        self.compact_status_label.setText(f"{status} · 집중률 {int(ratio * 100)}%")
        self.compact_progress.setValue(progress)
        self.compact_pause_button.setText(pause_text)
        self.compact_pause_button.setEnabled(controls_enabled)
        self.compact_done_button.setEnabled(controls_enabled)
        self.refresh_feature_widget("focus")
        self.refresh_compact_widget()

    def _display_remaining_seconds(self, session) -> int:
        if session.status == "break" and self.break_until is not None:
            return max(0, int((self.break_until - datetime.now()).total_seconds()))
        return session.remaining_seconds

    def update_pomodoro_controls(self) -> None:
        visible = self.preferences.show_pomodoro_controls
        active = self.pomodoro_total_seconds > 0
        self.pomodoro_minutes_spin.setEnabled(visible and not active)
        self.break_minutes_spin.setEnabled(visible and not active)
        self.start_pomodoro_button.setEnabled(visible and not active)
        self.pause_pomodoro_button.setEnabled(visible and active)
        self.reset_pomodoro_button.setEnabled(visible and active)
        self.pause_pomodoro_button.setText("재개" if self.pomodoro_paused else "일시정지")

    def start_pomodoro(self) -> None:
        if not self.preferences.show_pomodoro_controls:
            return
        self.pomodoro_mode = "focus"
        self.pomodoro_total_seconds = self.pomodoro_minutes_spin.value() * 60
        self.pomodoro_remaining_seconds = self.pomodoro_total_seconds
        self.pomodoro_paused = False
        self.pomodoro_tick_timer.start()
        self.update_pomodoro_display()

    def pause_or_resume_pomodoro(self) -> None:
        if self.pomodoro_total_seconds <= 0:
            return
        if self.pomodoro_tick_timer.isActive():
            self.pomodoro_tick_timer.stop()
            self.pomodoro_paused = True
        else:
            self.pomodoro_tick_timer.start()
            self.pomodoro_paused = False
        self.update_pomodoro_display()

    def reset_pomodoro(self) -> None:
        self.pomodoro_tick_timer.stop()
        self.pomodoro_mode = "focus"
        self.pomodoro_remaining_seconds = 0
        self.pomodoro_total_seconds = 0
        self.pomodoro_paused = False
        self.update_pomodoro_display()

    def on_pomodoro_tick(self) -> None:
        if self.pomodoro_total_seconds <= 0:
            self.reset_pomodoro()
            return
        self.pomodoro_remaining_seconds = max(0, self.pomodoro_remaining_seconds - 1)
        if self.pomodoro_remaining_seconds <= 0:
            self.switch_pomodoro_phase()
        self.update_pomodoro_display()

    def switch_pomodoro_phase(self) -> None:
        if self.pomodoro_mode == "focus":
            self.pomodoro_mode = "break"
            self.pomodoro_total_seconds = self.break_minutes_spin.value() * 60
            self.pomodoro_remaining_seconds = self.pomodoro_total_seconds
            self.statusBar().showMessage("뽀모도로 휴식 시간입니다.", 2500)
        else:
            self.pomodoro_mode = "focus"
            self.pomodoro_total_seconds = self.pomodoro_minutes_spin.value() * 60
            self.pomodoro_remaining_seconds = self.pomodoro_total_seconds
            self.statusBar().showMessage("뽀모도로 집중 시간이 시작됐습니다.", 2500)

    def update_pomodoro_display(self) -> None:
        if self.pomodoro_total_seconds <= 0:
            status = "대기"
            remaining = self.pomodoro_minutes_spin.value() * 60
            progress = 0
            detail = f"집중 {self.pomodoro_minutes_spin.value()}분 · 휴식 {self.break_minutes_spin.value()}분"
        else:
            phase = "집중" if self.pomodoro_mode == "focus" else "휴식"
            status = f"{phase} 일시정지" if self.pomodoro_paused else f"{phase} 중"
            remaining = self.pomodoro_remaining_seconds
            elapsed = max(0, self.pomodoro_total_seconds - self.pomodoro_remaining_seconds)
            progress = int(1000 * min(1.0, elapsed / max(1, self.pomodoro_total_seconds)))
            detail = f"{phase} · 남은 {_format_clock(remaining)} / 전체 {_format_clock(self.pomodoro_total_seconds)}"
        self.pomodoro_status_label.setText(status)
        self.pomodoro_time_label.setText(_format_clock(remaining))
        if hasattr(self, "pomodoro_progress"):
            self.pomodoro_progress.setValue(progress)
        if hasattr(self, "pomodoro_detail_label"):
            self.pomodoro_detail_label.setText(detail)
        self.update_pomodoro_controls()
        self.refresh_feature_widget("pomodoro")

    def save_quick_note(self) -> None:
        body = self.quick_note_editor.toPlainText().strip()
        attachment_paths = list(self.pending_quick_note_attachments)
        if not body and not attachment_paths:
            return
        if not body:
            body = "첨부 메모"
        self._save_note_body(
            body,
            attachment_paths,
            folder_id=self._folder_id_from_combo("quick_note_folder_combo"),
        )
        self.quick_note_editor.setPlainText("")
        self.pending_quick_note_attachments.clear()
        self.update_pending_attachments_label()

    def save_compact_note(self) -> None:
        body = self.compact_note_edit.text().strip()
        if not body:
            return
        self._save_note_body(body)
        self.compact_note_edit.clear()

    def select_quick_note_attachments(self) -> None:
        files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "첨부파일 선택",
            "",
            "모든 파일 (*);;이미지 파일 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)",
        )
        if not files:
            return

        known_paths = {str(Path(path)) for path in self.pending_quick_note_attachments}
        for file_path in files:
            normalized_path = str(Path(file_path))
            if normalized_path not in known_paths:
                self.pending_quick_note_attachments.append(normalized_path)
                known_paths.add(normalized_path)
        self.update_pending_attachments_label()

    def update_pending_attachments_label(self) -> None:
        if not hasattr(self, "pending_attachments_label"):
            return
        if not self.pending_quick_note_attachments:
            self.pending_attachments_label.clear()
            self.pending_attachments_label.hide()
            return
        names = [Path(path).name for path in self.pending_quick_note_attachments]
        self.pending_attachments_label.setText("첨부 대기: " + ", ".join(_shorten(name, 28) for name in names))
        self.pending_attachments_label.show()

    def _save_note_body(
        self,
        body: str,
        attachment_paths: list[str] | None = None,
        content_html: str = "",
        folder_id: int | None = None,
    ) -> None:
        session = self.focus_timer.session if self.focus_timer else None
        note = self.repository.save_quick_note(
            QuickNote(
                body=body,
                content_html=content_html,
                created_at=datetime.now(),
                focus_session_id=session.id if session else None,
                task_id=session.task_id if session else self.selected_task_id,
                folder_id=folder_id,
            )
        )
        failed_paths: list[str] = []
        if note.id is None:
            failed_paths.extend(attachment_paths or [])
        else:
            for attachment_path in attachment_paths or []:
                try:
                    self.repository.add_quick_note_attachment(note.id, attachment_path)
                except (OSError, ValueError):
                    failed_paths.append(attachment_path)
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.refresh_compact_widget()
        attachment_count = len(attachment_paths or []) - len(failed_paths)
        suffix = f" · 첨부 {attachment_count}개" if attachment_count else ""
        self.statusBar().showMessage(f"메모를 저장했습니다.{suffix}", 2500)
        if failed_paths:
            failed_names = ", ".join(Path(path).name for path in failed_paths[:3])
            QMessageBox.warning(self, "빠른 메모 첨부", f"첨부하지 못한 파일이 있습니다.\n{failed_names}")

    def show_note_context_menu(self, position: QPoint) -> None:
        item = self.notes_list.itemAt(position)
        if item is None:
            return
        self.notes_list.setCurrentItem(item)
        if item.data(Qt.ItemDataRole.UserRole) is None:
            return

        note_id = int(item.data(Qt.ItemDataRole.UserRole))
        attachments = self.repository.list_quick_note_attachments(note_id)
        menu = QMenu(self.notes_list)
        edit_action = menu.addAction("수정")
        edit_action.triggered.connect(self.edit_selected_quick_note)
        self._add_note_folder_menu(menu, note_id)
        if attachments:
            attachment_menu = menu.addMenu("첨부 열기")
            for attachment in attachments:
                action = attachment_menu.addAction(_shorten(attachment.file_name, 42))
                action.triggered.connect(
                    lambda _checked=False, attachment_id=attachment.id: self.open_quick_note_attachment(attachment_id)
                )
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_quick_note)
        menu.exec(self.notes_list.mapToGlobal(position))

    def open_quick_note_attachment(self, attachment_id: int | None) -> None:
        if attachment_id is None:
            return
        attachment = self.repository.get_quick_note_attachment(int(attachment_id))
        if attachment is None:
            QMessageBox.information(self, "빠른 메모 첨부", "첨부 파일 정보를 찾을 수 없습니다.")
            return
        path = Path(attachment.stored_path)
        if not path.exists():
            QMessageBox.warning(self, "빠른 메모 첨부", "첨부 파일을 찾을 수 없습니다.")
            return

        try:
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                webbrowser.open(str(path))
            else:
                startfile(str(path))
        except OSError as exc:
            QMessageBox.warning(self, "빠른 메모 첨부", f"첨부 파일을 열 수 없습니다.\n{exc}")

    def show_quick_note_detail_from_item(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        self.open_quick_note_detail(int(note_id))

    def show_compact_note_detail_from_item(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        self.open_quick_note_detail(int(note_id))

    def open_quick_note_detail(self, note_id: int) -> None:
        existing = self.quick_note_detail_windows.get(note_id)
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                self.quick_note_detail_windows.pop(note_id, None)

        dialog = QuickNoteDetailDialog(self.repository, note_id, self)
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result=0: self.refresh_quick_note_views())
        dialog.destroyed.connect(lambda _obj=None, target_id=note_id: self.quick_note_detail_windows.pop(target_id, None))
        self.quick_note_detail_windows[note_id] = dialog
        dialog.show()

    def refresh_quick_note_views(self) -> None:
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.refresh_compact_widget()
        folder_window = self.quick_note_folder_notes_window
        if folder_window is not None:
            try:
                refresh = getattr(folder_window, "refresh", None)
                if callable(refresh):
                    refresh()
            except RuntimeError:
                self.quick_note_folder_notes_window = None

    def show_compact_note_context_menu(self, position: QPoint) -> None:
        item = self.compact_notes_list.itemAt(position)
        if item is None:
            return
        self.compact_notes_list.setCurrentItem(item)
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return

        menu = QMenu(self.compact_notes_list)
        open_action = menu.addAction("열기")
        open_action.triggered.connect(lambda _checked=False, target=item: self.show_compact_note_detail_from_item(target))
        edit_action = menu.addAction("수정")
        edit_action.triggered.connect(self.edit_selected_compact_note)
        self._add_note_folder_menu(menu, int(note_id))
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_compact_note)
        menu.exec(self.compact_notes_list.mapToGlobal(position))

    def _add_note_folder_menu(self, menu: QMenu, note_id: int) -> None:
        folders = self.repository.list_quick_note_folders()
        if not folders:
            return
        folder_menu = menu.addMenu("폴더 이동")
        for folder in folders:
            action = folder_menu.addAction(folder.name)
            action.triggered.connect(
                lambda _checked=False, folder_id=folder.id: self.move_quick_note_to_folder(note_id, folder_id)
            )

    def move_quick_note_to_folder(self, note_id: int, folder_id: int | None) -> None:
        if folder_id is None:
            return
        note = self.repository.get_quick_note(note_id)
        if note is None:
            self.refresh_notes()
            self.refresh_compact_notes()
            return
        note.folder_id = folder_id
        self.repository.save_quick_note(note)
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.statusBar().showMessage("메모를 이동했습니다.", 1800)

    def edit_selected_quick_note(self) -> None:
        item = self.notes_list.currentItem()
        if item is None:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            QMessageBox.information(self, "빠른 메모 수정", "수정할 메모를 선택하세요.")
            return

        note = self.repository.get_quick_note(int(note_id))
        if note is None:
            QMessageBox.information(self, "빠른 메모 수정", "선택한 메모를 찾을 수 없습니다.")
            self.refresh_notes()
            return

        dialog = QuickNoteEditDialog(note, self.repository, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        note.body = dialog.body() or "이미지 메모"
        note.content_html = dialog.content_html()
        self.repository.save_quick_note(note)
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.statusBar().showMessage("메모를 수정했습니다.", 2500)

    def edit_selected_compact_note(self) -> None:
        item = self.compact_notes_list.currentItem()
        if item is None:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            QMessageBox.information(self, "빠른 메모 수정", "수정할 메모를 선택하세요.")
            return

        note = self.repository.get_quick_note(int(note_id))
        if note is None:
            QMessageBox.information(self, "빠른 메모 수정", "선택한 메모를 찾을 수 없습니다.")
            self.refresh_compact_notes()
            return

        dialog = QuickNoteEditDialog(note, self.repository, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        note.body = dialog.body() or "이미지 메모"
        note.content_html = dialog.content_html()
        self.repository.save_quick_note(note)
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.statusBar().showMessage("메모를 수정했습니다.", 2500)

    def delete_selected_quick_note(self) -> None:
        item = self.notes_list.currentItem()
        if item is None:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            QMessageBox.information(self, "빠른 메모 삭제", "삭제할 메모를 선택하세요.")
            return

        preview = item.text()
        answer = QMessageBox.question(self, "빠른 메모 삭제", f"'{_shorten(preview, 40)}' 메모를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.repository.delete_quick_note(int(note_id))
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.statusBar().showMessage("메모를 삭제했습니다.", 2500)

    def delete_selected_compact_note(self) -> None:
        item = self.compact_notes_list.currentItem()
        if item is None:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            QMessageBox.information(self, "빠른 메모 삭제", "삭제할 메모를 선택하세요.")
            return

        preview = item.text()
        answer = QMessageBox.question(self, "빠른 메모 삭제", f"'{_shorten(preview, 40)}' 메모를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.repository.delete_quick_note(int(note_id))
        self.refresh_notes()
        self.refresh_compact_notes()
        self.refresh_feature_widget("quick_memo")
        self.statusBar().showMessage("메모를 삭제했습니다.", 2500)

    def open_compact_widget(self) -> None:
        existing = self.compact_widget_window
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                self.compact_widget_window = None
        dialog = IntegratedWidgetDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda _obj=None: setattr(self, "compact_widget_window", None))
        self.compact_widget_window = dialog
        dialog.show()
        dialog.refresh()

    def refresh_compact_widget(self) -> None:
        widget = self.compact_widget_window
        if widget is None:
            return
        try:
            refresh = getattr(widget, "refresh", None)
            if callable(refresh):
                refresh()
        except RuntimeError:
            self.compact_widget_window = None

    def open_feature_widget(self, feature_key: str) -> None:
        existing = self.feature_widget_windows.get(feature_key)
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                self.feature_widget_windows.pop(feature_key, None)

        if feature_key == "focus":
            dialog = FocusWidgetDialog(self)
        elif feature_key == "pomodoro":
            dialog = PomodoroWidgetDialog(self)
        elif feature_key == "today_checklist":
            dialog = TodayChecklistWidgetDialog(self)
        elif feature_key == "quick_memo":
            dialog = QuickMemoWidgetDialog(self)
        elif feature_key == "today_timeline":
            dialog = TodayTimelineDialog(
                self.repository,
                self,
                on_changed=self.refresh_today,
                on_focus_task=self.load_task_by_id,
                on_delete_focus_session=self.delete_focus_session_by_id,
            )
        elif feature_key == "link_favorites":
            dialog = FavoritesWidgetDialog(self)
        elif feature_key == "media_panel":
            dialog = MediaPanelWidgetDialog(self)
        else:
            return

        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda _obj=None, key=feature_key: self.feature_widget_windows.pop(key, None))
        self.feature_widget_windows[feature_key] = dialog
        dialog.show()
        self.refresh_feature_widget(feature_key)

    def refresh_feature_widget(self, feature_key: str | None = None) -> None:
        for key, dialog in list(self.feature_widget_windows.items()):
            if feature_key is not None and key != feature_key:
                continue
            try:
                refresh = getattr(dialog, "refresh", None)
                if callable(refresh):
                    refresh()
            except RuntimeError:
                self.feature_widget_windows.pop(key, None)

    def set_compact_mode(self, compact: bool, auto: bool = False) -> None:
        if self.changing_mode:
            return
        self.changing_mode = True
        try:
            self.compact_auto = auto
            self.stack.setCurrentWidget(self.compact_page if compact else self.full_page)
            if compact:
                self.setWindowTitle("Focus Widget")
                self.refresh_compact_notes()
                self.refresh_compact_favorites()
                self.setMinimumSize(QSize(340, 330))
                self.resize(380, 380 if not self.preferences.show_compact_favorites_panel else 450)
            else:
                self.setWindowTitle(self.preferences.app_title)
                self.setMinimumSize(QSize(430, 320))
                self.resize(1120, 760)
        finally:
            self.changing_mode = False

    def toggle_always_on_top(self, enabled: bool) -> None:
        self.set_main_always_on_top(enabled, persist=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        return

    def closeEvent(self, event) -> None:
        self.save_last_window_size()
        self.save_last_layout_state()
        self.closing = True
        self.current_datetime_timer.stop()
        self.focus_tick_timer.stop()
        self.pomodoro_tick_timer.stop()
        if self.compact_widget_window is not None:
            try:
                self.compact_widget_window.close()
            except RuntimeError:
                pass
        if self.focus_timer is not None and self.focus_timer.session is not None:
            if self.focus_timer.session.status in {"running", "paused"}:
                self.focus_timer.stop(status="interrupted")
        for dialog in list(self.feature_widget_windows.values()):
            try:
                dialog.close()
            except RuntimeError:
                pass
        for dialog in list(self.quick_note_detail_windows.values()):
            try:
                dialog.close()
            except RuntimeError:
                pass
        if self.quick_note_folder_notes_window is not None:
            try:
                self.quick_note_folder_notes_window.close()
            except RuntimeError:
                pass
        super().closeEvent(event)
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)


class IntegratedWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("통합 위젯")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(300, 300))
        self.resize(380, 440 if owner.preferences.show_compact_favorites_panel else 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        top = QHBoxLayout()
        self.title_label = QLabel("집중 대기")
        self.title_label.setObjectName("compactTitle")
        top.addWidget(self.title_label, 1)
        self.always_on_top_check = QCheckBox("항상 위")
        self.always_on_top_check.toggled.connect(self.toggle_always_on_top)
        top.addWidget(self.always_on_top_check)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 62)
        close_button.clicked.connect(self.close)
        top.addWidget(close_button)
        layout.addLayout(top)

        self.time_label = QLabel("25:00")
        self.time_label.setObjectName("compactTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        controls = QHBoxLayout()
        self.pause_button = QPushButton("일시정지")
        self.pause_button.clicked.connect(owner.pause_or_resume_focus)
        self.done_button = QPushButton("완료")
        self.done_button.clicked.connect(owner.complete_focus)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.done_button)
        layout.addLayout(controls)

        memo_row = QHBoxLayout()
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("빠른 메모")
        self.note_edit.returnPressed.connect(self.save_note)
        memo_button = QPushButton("저장")
        memo_button.clicked.connect(self.save_note)
        memo_row.addWidget(self.note_edit, 1)
        memo_row.addWidget(memo_button)
        layout.addLayout(memo_row)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setChildrenCollapsible(False)

        notes_panel = QWidget()
        notes_layout = QVBoxLayout(notes_panel)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(4)
        notes_header = QLabel("최근 메모")
        notes_header.setObjectName("mutedLabel")
        notes_layout.addWidget(notes_header)

        self.notes_list = QListWidget()
        self.notes_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.notes_list.setMinimumHeight(80)
        self.notes_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.notes_list.itemDoubleClicked.connect(self.open_note)
        self.notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_note_context_menu)
        notes_layout.addWidget(self.notes_list, 1)
        self.content_splitter.addWidget(notes_panel)

        self.favorites_panel = QWidget()
        favorites_layout = QVBoxLayout(self.favorites_panel)
        favorites_layout.setContentsMargins(0, 0, 0, 0)
        favorites_layout.setSpacing(4)
        favorites_header = QLabel("즐겨찾기")
        favorites_header.setObjectName("mutedLabel")
        favorites_layout.addWidget(favorites_header)
        self.favorites_area = QScrollArea()
        self.favorites_area.setWidgetResizable(True)
        self.favorites_area.setFrameShape(QFrame.Shape.NoFrame)
        self.favorites_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.favorites_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.favorites_area.setMaximumHeight(72)
        favorites_widget = QWidget()
        self.favorites_layout = QHBoxLayout(favorites_widget)
        self.favorites_layout.setContentsMargins(0, 0, 0, 0)
        self.favorites_layout.setSpacing(6)
        self.favorites_area.setWidget(favorites_widget)
        favorites_layout.addWidget(self.favorites_area)
        self.content_splitter.addWidget(self.favorites_panel)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([190, 82])
        layout.addWidget(self.content_splitter, 1)

        delete_shortcut = QShortcut(QKeySequence("Delete"), self.notes_list)
        delete_shortcut.activated.connect(self.delete_selected_note)

    def refresh(self) -> None:
        self.refresh_focus()
        self.refresh_notes()
        self.refresh_favorites()

    def refresh_focus(self) -> None:
        session = self.owner.focus_timer.session if self.owner.focus_timer else None
        if session is None:
            planned = self.owner.planned_minutes_spin.value() * 60
            remaining = planned
            status = "대기 중"
            title = self.owner.focus_title_edit.text().strip() or "집중 대기"
            ratio = 1.0
            progress = 0
            pause_text = "일시정지"
            controls_enabled = False
        else:
            remaining = self.owner._display_remaining_seconds(session)
            status = _status_label(session.status)
            title = session.title
            ratio = self.owner.focus_timer.focus_ratio() if self.owner.focus_timer else 1.0
            progress = int(1000 * min(1.0, session.focused_seconds / max(1, session.planned_seconds)))
            pause_text = "재개" if session.status in {"paused", "break"} else "일시정지"
            controls_enabled = session.status in {"running", "paused", "break"}
        self.title_label.setText(title)
        self.time_label.setText(_format_clock(remaining))
        self.status_label.setText(f"{status} · 집중률 {int(ratio * 100)}%")
        self.progress.setValue(progress)
        self.pause_button.setText(pause_text)
        self.pause_button.setEnabled(controls_enabled)
        self.done_button.setEnabled(controls_enabled)

    def refresh_notes(self) -> None:
        self.notes_list.clear()
        notes = self.owner.repository.list_quick_notes(limit=5)
        if not notes:
            empty = QListWidgetItem("저장된 메모가 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.notes_list.addItem(empty)
            return
        for note in notes:
            item = QListWidgetItem(self.owner._note_list_label(note, compact=True))
            item.setToolTip(self.owner._note_list_label(note, compact=False))
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.notes_list.addItem(item)

    def refresh_favorites(self) -> None:
        self.favorites_panel.setVisible(self.owner.preferences.show_compact_favorites_panel)
        while self.favorites_layout.count():
            item = self.favorites_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self.owner.preferences.show_compact_favorites_panel:
            return
        favorites = self.owner.repository.list_link_favorites()
        if not favorites:
            empty = QLabel("없음")
            empty.setObjectName("mutedLabel")
            self.favorites_layout.addWidget(empty)
            self.favorites_layout.addStretch(1)
            return
        for favorite in favorites:
            self.favorites_layout.addWidget(self.owner._build_compact_favorite_button(favorite))
        self.favorites_layout.addStretch(1)

    def save_note(self) -> None:
        body = self.note_edit.text().strip()
        if not body:
            return
        self.owner._save_note_body(body)
        self.note_edit.clear()
        self.refresh_notes()

    def open_note(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is not None:
            self.owner.open_quick_note_detail(int(note_id))

    def show_note_context_menu(self, position: QPoint) -> None:
        item = self.notes_list.itemAt(position)
        if item is None:
            return
        self.notes_list.setCurrentItem(item)
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        menu = QMenu(self.notes_list)
        open_action = menu.addAction("열기")
        open_action.triggered.connect(lambda _checked=False, target=item: self.open_note(target))
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_note)
        menu.exec(self.notes_list.mapToGlobal(position))

    def delete_selected_note(self) -> None:
        item = self.notes_list.currentItem()
        if item is None:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        preview = item.text()
        answer = QMessageBox.question(self, "빠른 메모 삭제", f"'{_shorten(preview, 40)}' 메모를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.owner.repository.delete_quick_note(int(note_id))
        self.owner.refresh_quick_note_views()
        self.refresh_notes()

    def toggle_always_on_top(self, enabled: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()


class FocusWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("집중 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(220, 150))
        self.resize(320, 190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        self.title_label = QLabel("집중 대기")
        self.title_label.setObjectName("compactTitle")
        title_row.addWidget(self.title_label, 1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, title_row)
        layout.addLayout(title_row)

        self.time_label = QLabel("25:00")
        self.time_label.setObjectName("compactTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        button_row = QHBoxLayout()
        self.pause_button = QPushButton("일시정지")
        self.pause_button.clicked.connect(owner.pause_or_resume_focus)
        self.done_button = QPushButton("완료")
        self.done_button.clicked.connect(owner.complete_focus)
        button_row.addWidget(self.pause_button)
        button_row.addWidget(self.done_button)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self) -> None:
        session = self.owner.focus_timer.session if self.owner.focus_timer else None
        if session is None:
            planned = self.owner.planned_minutes_spin.value() * 60
            self.title_label.setText(self.owner.focus_title_edit.text().strip() or "집중 대기")
            self.time_label.setText(_format_clock(planned))
            self.status_label.setText("대기 중")
            self.progress.setValue(0)
            self.pause_button.setText("일시정지")
            self.pause_button.setEnabled(False)
            self.done_button.setEnabled(False)
            return

        ratio = self.owner.focus_timer.focus_ratio() if self.owner.focus_timer else 1.0
        progress = int(1000 * min(1.0, session.focused_seconds / max(1, session.planned_seconds)))
        self.title_label.setText(session.title)
        self.time_label.setText(_format_clock(self.owner._display_remaining_seconds(session)))
        self.status_label.setText(f"{_status_label(session.status)} · 집중률 {int(ratio * 100)}%")
        self.progress.setValue(progress)
        controls_enabled = session.status in {"running", "paused", "break"}
        self.pause_button.setText("재개" if session.status in {"paused", "break"} else "일시정지")
        self.pause_button.setEnabled(controls_enabled)
        self.done_button.setEnabled(controls_enabled)


class PomodoroWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("뽀모도로 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(220, 150))
        self.resize(300, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.status_label = QLabel("대기")
        self.status_label.setObjectName("mutedLabel")
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, status_row)
        layout.addLayout(status_row)

        self.time_label = QLabel("25:00")
        self.time_label.setObjectName("compactTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label, 1)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("시작")
        self.start_button.clicked.connect(owner.start_pomodoro)
        self.pause_button = QPushButton("일시정지")
        self.pause_button.clicked.connect(owner.pause_or_resume_pomodoro)
        self.reset_button = QPushButton("초기화")
        self.reset_button.clicked.connect(owner.reset_pomodoro)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.pause_button)
        button_row.addWidget(self.reset_button)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self) -> None:
        active = self.owner.pomodoro_total_seconds > 0
        if not active:
            status = "대기"
            remaining = self.owner.pomodoro_minutes_spin.value() * 60
        else:
            phase = "집중" if self.owner.pomodoro_mode == "focus" else "휴식"
            status = f"{phase} 일시정지" if self.owner.pomodoro_paused else f"{phase} 중"
            remaining = self.owner.pomodoro_remaining_seconds
        self.status_label.setText(status)
        self.time_label.setText(_format_clock(remaining))
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.pause_button.setText("재개" if self.owner.pomodoro_paused else "일시정지")
        self.reset_button.setEnabled(active)


class QuickMemoWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("빠른 메모 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(260, 220))
        self.resize(380, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, top_row)
        layout.addLayout(top_row)

        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("폴더"))
        self.folder_combo = QComboBox()
        _stabilize_control(self.folder_combo, 130)
        self.folder_combo.currentIndexChanged.connect(lambda _index: self.refresh_notes())
        self.folder_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_combo.customContextMenuRequested.connect(
            lambda position: self.owner.show_note_folder_combo_context_menu(self.folder_combo, position)
        )
        meta_row.addWidget(self.folder_combo, 1)
        layout.addLayout(meta_row)

        input_row = QHBoxLayout()
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("빠른 메모")
        self.note_edit.returnPressed.connect(self.save_note)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 68)
        save_button.clicked.connect(self.save_note)
        input_row.addWidget(self.note_edit, 1)
        input_row.addWidget(save_button)
        layout.addLayout(input_row)

        header = QLabel("최근 메모")
        header.setObjectName("mutedLabel")
        layout.addWidget(header)

        self.notes_list = QListWidget()
        self.notes_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.notes_list.itemDoubleClicked.connect(self.open_note)
        self.notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.notes_list, 1)

        self.refresh()

    def refresh(self) -> None:
        self.refresh_folders()
        self.refresh_notes()

    def refresh_folders(self) -> None:
        current_id = self.folder_combo.currentData()
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        for folder in self.owner.repository.list_quick_note_folders():
            self.folder_combo.addItem(folder.name, folder.id)
        if current_id is not None:
            index = self.folder_combo.findData(current_id)
            if index >= 0:
                self.folder_combo.setCurrentIndex(index)
        self.folder_combo.blockSignals(False)

    def refresh_notes(self) -> None:
        self.notes_list.clear()
        folder_id = self.folder_combo.currentData()
        notes = self.owner.repository.list_quick_notes(
            limit=8,
            folder_id=int(folder_id) if folder_id is not None else None,
        )
        if not notes:
            empty = QListWidgetItem("저장된 메모가 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.notes_list.addItem(empty)
            return
        for note in notes:
            item = QListWidgetItem(self.owner._note_list_label(note, compact=True))
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setToolTip(self.owner._note_list_label(note, compact=False))
            self.notes_list.addItem(item)

    def save_note(self) -> None:
        body = self.note_edit.text().strip()
        if not body:
            return
        folder_id = self.folder_combo.currentData()
        self.owner._save_note_body(
            body,
            folder_id=int(folder_id) if folder_id is not None else None,
        )
        self.note_edit.clear()
        self.refresh_notes()

    def open_note(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        self.owner.open_quick_note_detail(int(note_id))
        self.refresh_notes()

    def show_context_menu(self, position: QPoint) -> None:
        item = self.notes_list.itemAt(position)
        if item is None:
            return
        self.notes_list.setCurrentItem(item)
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        menu = QMenu(self.notes_list)
        open_action = menu.addAction("열기")
        open_action.triggered.connect(lambda _checked=False, target=item: self.open_note(target))
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(lambda _checked=False: self.delete_note(int(note_id)))
        menu.exec(self.notes_list.mapToGlobal(position))

    def delete_note(self, note_id: int) -> None:
        note = self.owner.repository.get_quick_note(note_id)
        if note is None:
            self.refresh_notes()
            return
        preview = _shorten(" ".join(note.body.split()), 40)
        answer = QMessageBox.question(self, "빠른 메모 삭제", f"'{preview}' 메모를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.owner.repository.delete_quick_note(note_id)
        self.owner.refresh_notes()
        self.owner.refresh_compact_notes()
        self.refresh_notes()


class FavoritesWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("즐겨찾기 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(220, 160))
        self.resize(340, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("즐겨찾기")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, header)
        settings_button = QPushButton("설정")
        _stabilize_control(settings_button, 68)
        settings_button.clicked.connect(self.show_settings)
        header.addWidget(settings_button)
        layout.addLayout(header)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.items_layout = QVBoxLayout(content)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(8)
        self.area.setWidget(content)
        layout.addWidget(self.area, 1)

        self.refresh()

    def refresh(self) -> None:
        _clear_layout(self.items_layout)
        favorites = self.owner.repository.list_link_favorites()
        if not favorites:
            empty = QLabel("저장된 즐겨찾기가 없습니다.")
            empty.setObjectName("mutedLabel")
            self.items_layout.addWidget(empty)
            self.items_layout.addStretch(1)
            return
        for favorite in favorites:
            self.items_layout.addWidget(self.owner._build_compact_favorite_button(favorite))
        self.items_layout.addStretch(1)

    def show_settings(self) -> None:
        self.owner.show_favorites_settings()
        self.refresh()


class MediaPanelWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("이미지 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(260, 220))
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addStretch(1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, header)
        layout.addLayout(header)

        self.preview_label = MediaPreviewLabel()
        self.preview_label.select_callback = self.owner.choose_media_panel_file
        self.preview_label.context_callback = self.owner.show_media_panel_context_menu
        layout.addWidget(self.preview_label, 1)
        self.refresh()

    def refresh(self) -> None:
        self.owner._load_media_preview(self.owner.preferences.media_panel_file_path, self.preview_label)


class TodayChecklistWidgetDialog(QDialog):
    def __init__(self, owner: MainWindow) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("오늘 체크리스트 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(280, 220))
        self.resize(420, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, top_row)
        layout.addLayout(top_row)

        self.checklist = TodayChecklistWidget(owner.repository, owner.refresh_today, self)
        self.checklist.items_area.setMaximumHeight(16777215)
        layout.addWidget(self.checklist, 1)

    def refresh(self) -> None:
        self.checklist.refresh_checklist()


class QuickNoteEditDialog(QDialog):
    def __init__(self, note: QuickNote, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("빠른 메모 수정")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(520, 420))
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        created_label = QLabel(
            f"작성 시간 {_format_datetime(note.created_at, _preferences_from_widget(self), '%Y-%m-%d')}"
        )
        created_label.setObjectName("mutedLabel")
        layout.addWidget(created_label)

        self.body_edit = RichNoteEditor(self.repository, self)
        self.body_edit.set_content(note.body, note.content_html)
        self.body_edit.text_edit.setMinimumHeight(280)
        layout.addWidget(self.body_edit, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소")
        _stabilize_control(cancel_button, 84)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def body(self) -> str:
        return self.body_edit.to_plain_text()

    def content_html(self) -> str:
        return self.body_edit.to_html()

    def accept(self) -> None:
        if not self.body_edit.has_content():
            QMessageBox.information(self, "빠른 메모 수정", "메모 내용을 입력하세요.")
            return
        super().accept()


class QuickNoteDetailDialog(QDialog):
    def __init__(self, repository: ScheduleRepository, note_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.note_id = note_id
        self.setWindowTitle("빠른 메모")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(520, 420))
        self.resize(900, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.created_label = QLabel()
        self.created_label.setObjectName("mutedLabel")
        layout.addWidget(self.created_label)

        self.body_view = QTextEdit()
        self.body_view.setReadOnly(True)
        self.body_view.setMinimumHeight(280)
        self.body_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.body_view, 1)

        self.attachments_area = QScrollArea()
        self.attachments_area.setWidgetResizable(True)
        self.attachments_area.setFrameShape(QFrame.Shape.NoFrame)
        self.attachments_area.setMinimumHeight(120)
        self.attachments_area.setMaximumHeight(260)
        self.attachments_widget = QWidget()
        self.attachments_layout = QVBoxLayout(self.attachments_widget)
        self.attachments_layout.setContentsMargins(0, 0, 0, 0)
        self.attachments_layout.setSpacing(10)
        self.attachments_area.setWidget(self.attachments_widget)
        layout.addWidget(self.attachments_area)

        button_row = QHBoxLayout()
        self.edit_button = QPushButton("수정")
        _stabilize_control(self.edit_button, 84)
        self.edit_button.clicked.connect(self.edit_note)
        self.delete_button = QPushButton("삭제")
        _stabilize_control(self.delete_button, 84)
        self.delete_button.clicked.connect(self.delete_note)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.refresh_note()

    def refresh_note(self) -> None:
        _clear_layout(self.attachments_layout)
        note = self.repository.get_quick_note(self.note_id)
        if note is None:
            self.created_label.setText("")
            self.body_view.setPlainText("메모를 찾을 수 없습니다.")
            self.attachments_area.setVisible(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)

        meta = [f"작성 시간 {_format_datetime(note.created_at, _preferences_from_widget(self), '%Y-%m-%d')}"]
        folder = self.repository.get_quick_note_folder(note.folder_id) if note.folder_id is not None else None
        if folder is not None:
            meta.append(f"폴더 {folder.name}")
        self.created_label.setText(" · ".join(meta))

        if note.content_html.strip():
            self.body_view.setHtml(note.content_html)
        else:
            self.body_view.setPlainText(note.body)

        attachments = self.repository.list_quick_note_attachments(self.note_id)
        self.attachments_area.setVisible(bool(attachments))
        if attachments:
            attachment_title = QLabel("첨부")
            attachment_title.setObjectName("sectionTitle")
            self.attachments_layout.addWidget(attachment_title)

        for attachment in attachments:
            self._add_attachment_view(attachment)

    def _add_attachment_view(self, attachment) -> None:
        path = Path(attachment.stored_path)
        name_label = QLabel(attachment.file_name)
        name_label.setObjectName("mutedLabel")
        self.attachments_layout.addWidget(name_label)

        if _is_image_file(path) and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                image_label = QLabel()
                image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image_label.setPixmap(
                    pixmap.scaled(
                        QSize(540, 340),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.attachments_layout.addWidget(image_label)
                return

        open_button = QPushButton(f"첨부 열기 · {attachment.file_name}")
        open_button.clicked.connect(lambda _checked=False, target=str(path): _open_local_path(target, self))
        self.attachments_layout.addWidget(open_button)

    def edit_note(self) -> None:
        note = self.repository.get_quick_note(self.note_id)
        if note is None:
            self.refresh_note()
            return
        dialog = QuickNoteEditDialog(note, self.repository, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        note.body = dialog.body() or "이미지 메모"
        note.content_html = dialog.content_html()
        self.repository.save_quick_note(note)
        self.refresh_note()

    def delete_note(self) -> None:
        note = self.repository.get_quick_note(self.note_id)
        if note is None:
            self.accept()
            return
        preview = _shorten(" ".join(note.body.split()), 42)
        answer = QMessageBox.question(self, "빠른 메모 삭제", f"'{preview}' 메모를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_quick_note(self.note_id)
        self.accept()


class QuickNoteFolderDialog(QDialog):
    def __init__(self, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("메모 폴더 관리")
        self.resize(420, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.folder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.show_folder_context_menu)
        layout.addWidget(self.folder_list, 1)

        action_row = QHBoxLayout()
        open_button = QPushButton("폴더 보기")
        _stabilize_control(open_button, 92)
        open_button.clicked.connect(self.open_folder_window)
        new_button = QPushButton("새 폴더")
        _stabilize_control(new_button, 88)
        new_button.clicked.connect(self.add_folder)
        rename_button = QPushButton("이름 변경")
        _stabilize_control(rename_button, 88)
        rename_button.clicked.connect(self.rename_folder)
        delete_button = QPushButton("삭제")
        _stabilize_control(delete_button, 76)
        delete_button.clicked.connect(self.delete_folder)
        action_row.addWidget(open_button)
        action_row.addWidget(new_button)
        action_row.addWidget(rename_button)
        action_row.addWidget(delete_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.refresh_folders()

    def refresh_folders(self) -> None:
        self.folder_list.clear()
        for folder in self.repository.list_quick_note_folders():
            suffix = " · 기본" if folder.is_default else ""
            item = QListWidgetItem(f"{folder.name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, folder.id)
            self.folder_list.addItem(item)

    def selected_folder(self) -> QuickNoteFolder | None:
        item = self.folder_list.currentItem()
        if item is None:
            return None
        folder_id = item.data(Qt.ItemDataRole.UserRole)
        return self.repository.get_quick_note_folder(int(folder_id)) if folder_id is not None else None

    def show_folder_context_menu(self, position: QPoint) -> None:
        item = self.folder_list.itemAt(position)
        if item is None:
            return
        self.folder_list.setCurrentItem(item)
        folder = self.selected_folder()
        if folder is None:
            return
        menu = QMenu(self.folder_list)
        open_action = menu.addAction("폴더 보기")
        open_action.triggered.connect(self.open_folder_window)
        menu.addSeparator()
        default_action = menu.addAction("기본 메모함으로 지정")
        default_action.setEnabled(not folder.is_default)
        default_action.triggered.connect(lambda _checked=False: self.set_default_folder(folder.id))
        menu.addSeparator()
        rename_action = menu.addAction("이름 변경")
        rename_action.triggered.connect(self.rename_folder)
        delete_action = menu.addAction("삭제")
        delete_action.setEnabled(not folder.is_default)
        delete_action.triggered.connect(self.delete_folder)
        menu.exec(self.folder_list.mapToGlobal(position))

    def open_folder_window(self) -> None:
        folder = self.selected_folder()
        if folder is None or folder.id is None:
            QMessageBox.information(self, "폴더 보기", "열 폴더를 선택하세요.")
            return
        parent = self.parent()
        if hasattr(parent, "open_note_folder_window"):
            parent.open_note_folder_window(folder.id)

    def set_default_folder(self, folder_id: int | None) -> None:
        if folder_id is None:
            return
        parent = self.parent()
        if hasattr(parent, "set_default_quick_note_folder"):
            parent.set_default_quick_note_folder(folder_id)
        else:
            self.repository.set_default_quick_note_folder(folder_id)
        self.refresh_folders()

    def add_folder(self) -> None:
        name, accepted = QInputDialog.getText(self, "새 폴더", "폴더 이름")
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "새 폴더", "폴더 이름을 입력하세요.")
            return
        self.repository.save_quick_note_folder(QuickNoteFolder(name=name))
        self.refresh_folders()

    def rename_folder(self) -> None:
        folder = self.selected_folder()
        if folder is None:
            QMessageBox.information(self, "폴더 이름 변경", "이름을 바꿀 폴더를 선택하세요.")
            return
        name, accepted = QInputDialog.getText(
            self,
            "폴더 이름 변경",
            "폴더 이름",
            QLineEdit.EchoMode.Normal,
            folder.name,
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "폴더 이름 변경", "폴더 이름을 입력하세요.")
            return
        folder.name = name
        self.repository.save_quick_note_folder(folder)
        self.refresh_folders()

    def delete_folder(self) -> None:
        folder = self.selected_folder()
        if folder is None:
            QMessageBox.information(self, "폴더 삭제", "삭제할 폴더를 선택하세요.")
            return
        if folder.is_default:
            QMessageBox.information(self, "폴더 삭제", "기본 메모함은 삭제할 수 없습니다.")
            return
        answer = QMessageBox.question(
            self,
            "폴더 삭제",
            f"'{folder.name}' 폴더를 삭제할까요?\n안의 메모는 기본 메모함으로 이동됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if folder.id is not None:
            self.repository.delete_quick_note_folder(folder.id)
        self.refresh_folders()


class QuickNoteFolderNotesDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        parent: QWidget | None = None,
        initial_folder_id: int | None = None,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.on_changed = on_changed
        self.folders: list[QuickNoteFolder] = []
        self.setWindowTitle("메모 폴더 보기")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(720, 460))
        self.resize(980, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("메모 폴더")
        title.setObjectName("sectionTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedLabel")
        header_row.addWidget(self.summary_label)
        layout.addLayout(header_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        folder_panel = QWidget()
        folder_layout = QVBoxLayout(folder_panel)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(8)
        folder_layout.addWidget(QLabel("폴더"))
        self.folder_list = QuickNoteFolderDropList(self.move_notes_to_folder, self)
        self.folder_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.folder_list.currentItemChanged.connect(lambda _current, _previous: self.refresh_notes())
        folder_layout.addWidget(self.folder_list, 1)

        folder_button_row = QHBoxLayout()
        add_folder_button = QPushButton("새 폴더")
        _stabilize_control(add_folder_button, 82)
        add_folder_button.clicked.connect(self.add_folder)
        rename_folder_button = QPushButton("이름 변경")
        _stabilize_control(rename_folder_button, 88)
        rename_folder_button.clicked.connect(self.rename_folder)
        folder_button_row.addWidget(add_folder_button)
        folder_button_row.addWidget(rename_folder_button)
        folder_button_row.addStretch(1)
        folder_layout.addLayout(folder_button_row)
        splitter.addWidget(folder_panel)

        note_panel = QWidget()
        note_layout = QVBoxLayout(note_panel)
        note_layout.setContentsMargins(0, 0, 0, 0)
        note_layout.setSpacing(8)

        note_header = QHBoxLayout()
        self.folder_title_label = QLabel()
        self.folder_title_label.setObjectName("sectionTitle")
        note_header.addWidget(self.folder_title_label)
        note_header.addStretch(1)
        self.select_all_check = QCheckBox("전체 선택")
        self.select_all_check.stateChanged.connect(
            lambda _state: self.set_all_notes_checked(self.select_all_check.isChecked())
        )
        note_header.addWidget(self.select_all_check)
        note_layout.addLayout(note_header)

        move_row = QHBoxLayout()
        move_row.addWidget(QLabel("선택한 메모 이동"))
        self.target_folder_combo = QComboBox()
        _stabilize_control(self.target_folder_combo, 160)
        move_row.addWidget(self.target_folder_combo, 1)
        move_button = QPushButton("이동")
        _stabilize_control(move_button, 72)
        move_button.clicked.connect(self.move_selected_notes)
        move_row.addWidget(move_button)
        note_layout.addLayout(move_row)

        self.notes_list = QuickNoteDragList(self)
        self.notes_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.notes_list.itemDoubleClicked.connect(self.open_note_from_item)
        self.notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_note_context_menu)
        note_layout.addWidget(self.notes_list, 1)

        hint = QLabel("메모를 체크한 뒤 이동하거나, 메모를 왼쪽 폴더로 끌어 놓아 이동할 수 있습니다.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        note_layout.addWidget(hint)
        splitter.addWidget(note_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 720])
        layout.addWidget(splitter, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.close)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.refresh_folders(initial_folder_id)

    def refresh(self) -> None:
        self.refresh_folders(self.current_folder_id())

    def refresh_folders(self, selected_folder_id: int | None = None) -> None:
        current_id = selected_folder_id if selected_folder_id is not None else self.current_folder_id()
        self.folders = self.repository.list_quick_note_folders()
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        for folder in self.folders:
            suffix = " · 기본" if folder.is_default else ""
            item = QListWidgetItem(f"{folder.name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, folder.id)
            self.folder_list.addItem(item)
        self.folder_list.blockSignals(False)
        if current_id is not None:
            self.select_folder(current_id)
        elif self.folder_list.count() > 0:
            self.folder_list.setCurrentRow(0)
        self.refresh_target_folders()
        self.refresh_notes()

    def refresh_target_folders(self) -> None:
        current_target = self.target_folder_combo.currentData()
        self.target_folder_combo.blockSignals(True)
        self.target_folder_combo.clear()
        for folder in self.folders:
            self.target_folder_combo.addItem(folder.name, folder.id)
        if current_target is not None:
            index = self.target_folder_combo.findData(current_target)
            if index >= 0:
                self.target_folder_combo.setCurrentIndex(index)
        self.target_folder_combo.blockSignals(False)

    def current_folder_id(self) -> int | None:
        item = self.folder_list.currentItem()
        if item is None:
            return None
        folder_id = item.data(Qt.ItemDataRole.UserRole)
        return int(folder_id) if folder_id is not None else None

    def select_folder(self, folder_id: int) -> None:
        for row in range(self.folder_list.count()):
            item = self.folder_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == folder_id:
                self.folder_list.setCurrentRow(row)
                return

    def selected_folder(self) -> QuickNoteFolder | None:
        folder_id = self.current_folder_id()
        return self.repository.get_quick_note_folder(folder_id) if folder_id is not None else None

    def refresh_notes(self) -> None:
        folder = self.selected_folder()
        self.notes_list.clear()
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(False)
        self.select_all_check.blockSignals(False)
        if folder is None or folder.id is None:
            self.folder_title_label.setText("폴더")
            self.summary_label.setText("")
            return
        notes = self.repository.list_quick_notes(folder_id=folder.id)
        self.folder_title_label.setText(folder.name)
        self.summary_label.setText(f"{len(notes)}개 메모")
        if not notes:
            empty = QListWidgetItem("이 폴더에 메모가 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.notes_list.addItem(empty)
            return
        for note in notes:
            item = QListWidgetItem(self.note_label(note))
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            self.notes_list.addItem(item)

    def note_label(self, note: QuickNote) -> str:
        body = _shorten(" ".join(note.body.split()) or "이미지 메모", 100)
        time_label = _format_datetime(note.created_at, _preferences_from_widget(self))
        attachments = self.repository.list_quick_note_attachments(note.id) if note.id is not None else []
        attachment_label = f" · 첨부 {len(attachments)}개" if attachments else ""
        return f"{time_label}  {body}{attachment_label}"

    def set_all_notes_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.notes_list.count()):
            item = self.notes_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                item.setCheckState(state)

    def move_selected_notes(self) -> None:
        note_ids = self.notes_list.note_ids_for_action()
        if not note_ids:
            QMessageBox.information(self, "메모 이동", "이동할 메모를 선택하세요.")
            return
        folder_id = self.target_folder_combo.currentData()
        if folder_id is None:
            QMessageBox.information(self, "메모 이동", "이동할 폴더를 선택하세요.")
            return
        self.move_notes_to_folder(note_ids, int(folder_id))

    def move_notes_to_folder(self, note_ids: list[int], folder_id: int) -> None:
        moved_count = self.repository.move_quick_notes_to_folder(note_ids, folder_id)
        if moved_count == 0:
            self.refresh()
            return
        self.select_folder(folder_id)
        self.refresh()
        self.emit_changed()
        self.show_status(f"메모 {moved_count}개를 이동했습니다.")

    def show_note_context_menu(self, position: QPoint) -> None:
        item = self.notes_list.itemAt(position)
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        self.notes_list.setCurrentItem(item)
        note_ids = self.notes_list.note_ids_for_action()
        if not note_ids:
            return
        menu = QMenu(self.notes_list)
        if len(note_ids) == 1:
            open_action = menu.addAction("열기")
            open_action.triggered.connect(lambda _checked=False, target=item: self.open_note_from_item(target))
            edit_action = menu.addAction("수정")
            edit_action.triggered.connect(lambda _checked=False, note_id=note_ids[0]: self.edit_note(note_id))
        self.add_move_menu(menu, note_ids)
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(lambda _checked=False: self.delete_selected_notes())
        menu.exec(self.notes_list.mapToGlobal(position))

    def add_move_menu(self, menu: QMenu, note_ids: list[int]) -> None:
        folder_menu = menu.addMenu("폴더 이동")
        for folder in self.folders:
            if folder.id is None:
                continue
            action = folder_menu.addAction(folder.name)
            action.triggered.connect(
                lambda _checked=False, target_ids=list(note_ids), folder_id=folder.id: self.move_notes_to_folder(
                    target_ids,
                    int(folder_id),
                )
            )

    def open_note_from_item(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        parent = self.parent()
        if hasattr(parent, "open_quick_note_detail"):
            parent.open_quick_note_detail(int(note_id))
            return
        dialog = QuickNoteDetailDialog(self.repository, int(note_id), self)
        dialog.exec()
        self.refresh()

    def edit_note(self, note_id: int) -> None:
        note = self.repository.get_quick_note(note_id)
        if note is None:
            self.refresh()
            return
        dialog = QuickNoteEditDialog(note, self.repository, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        note.body = dialog.body() or "이미지 메모"
        note.content_html = dialog.content_html()
        self.repository.save_quick_note(note)
        self.refresh()
        self.emit_changed()
        self.show_status("메모를 수정했습니다.")

    def delete_selected_notes(self) -> None:
        note_ids = self.notes_list.note_ids_for_action()
        if not note_ids:
            QMessageBox.information(self, "메모 삭제", "삭제할 메모를 선택하세요.")
            return
        answer = QMessageBox.question(self, "메모 삭제", f"선택한 메모 {len(note_ids)}개를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        for note_id in note_ids:
            self.repository.delete_quick_note(note_id)
        self.refresh()
        self.emit_changed()
        self.show_status(f"메모 {len(note_ids)}개를 삭제했습니다.")

    def add_folder(self) -> None:
        name, accepted = QInputDialog.getText(self, "새 폴더", "폴더 이름")
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "새 폴더", "폴더 이름을 입력하세요.")
            return
        folder = self.repository.save_quick_note_folder(QuickNoteFolder(name=name))
        self.refresh_folders(folder.id)
        self.emit_changed()

    def rename_folder(self) -> None:
        folder = self.selected_folder()
        if folder is None:
            QMessageBox.information(self, "폴더 이름 변경", "이름을 바꿀 폴더를 선택하세요.")
            return
        name, accepted = QInputDialog.getText(
            self,
            "폴더 이름 변경",
            "폴더 이름",
            QLineEdit.EchoMode.Normal,
            folder.name,
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "폴더 이름 변경", "폴더 이름을 입력하세요.")
            return
        folder.name = name
        self.repository.save_quick_note_folder(folder)
        self.refresh_folders(folder.id)
        self.emit_changed()

    def emit_changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def show_status(self, message: str) -> None:
        parent = self.parent()
        if hasattr(parent, "statusBar"):
            parent.statusBar().showMessage(message, 2200)


class LinkFavoriteEditDialog(QDialog):
    def __init__(self, favorite: LinkFavorite, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("즐겨찾기 수정")
        self.resize(520, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setText(favorite.title)
        _stabilize_control(self.title_edit, 280)
        self.target_edit = QLineEdit()
        self.target_edit.setText(favorite.target)
        _stabilize_control(self.target_edit, 280)
        form.addRow("표시 제목", self.title_edit)
        form.addRow("URL / 프로그램", self.target_edit)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소")
        _stabilize_control(cancel_button, 84)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def favorite_title(self) -> str:
        title = self.title_edit.text().strip()
        return title or self.favorite_target()

    def favorite_target(self) -> str:
        return self.target_edit.text().strip()

    def accept(self) -> None:
        if not self.favorite_target():
            QMessageBox.information(self, "즐겨찾기 수정", "열 URL이나 프로그램 경로를 입력하세요.")
            return
        super().accept()


class FavoritesSettingsDialog(QDialog):
    def __init__(self, repository: ScheduleRepository, preferences: Preference, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.selected_favorite_id: int | None = None
        self.selected_icon_source_path = ""
        self.selected_site_icon_data: bytes = b""
        self.selected_site_icon_file_name = ""
        self.setWindowTitle("즐겨찾기 설정")
        self.resize(660, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        display_form = QFormLayout()
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItem("글자만 표시", "text")
        self.display_mode_combo.addItem("아이콘과 이름 표시", "icon_with_label")
        self.display_mode_combo.addItem("아이콘만 표시", "icon_only")
        mode_index = self.display_mode_combo.findData(_normalized_favorite_display_mode(preferences.favorite_display_mode))
        self.display_mode_combo.setCurrentIndex(max(0, mode_index))
        display_form.addRow("표시 방식", self.display_mode_combo)
        layout.addLayout(display_form)

        body_row = QHBoxLayout()
        self.favorites_list = QListWidget()
        self.favorites_list.setMinimumWidth(190)
        self.favorites_list.currentItemChanged.connect(self.load_selected_favorite)
        body_row.addWidget(self.favorites_list, 1)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)

        form = QFormLayout()
        self.favorite_title_edit = QLineEdit()
        self.favorite_title_edit.setPlaceholderText("화면에 보일 이름")
        self.favorite_target_edit = QLineEdit()
        self.favorite_target_edit.setPlaceholderText("https://... 또는 프로그램 경로")
        self.favorite_icon_text_edit = QLineEdit()
        self.favorite_icon_text_edit.setPlaceholderText("아이콘 파일이 없을 때 보여줄 짧은 표시")
        self.favorite_icon_text_edit.setMaxLength(12)
        self.favorite_icon_path_edit = QLineEdit()
        self.favorite_icon_path_edit.setReadOnly(True)
        self.favorite_icon_path_edit.setPlaceholderText("아이콘 이미지 파일")

        icon_file_row = QHBoxLayout()
        icon_file_row.addWidget(self.favorite_icon_path_edit, 1)
        choose_icon_button = QPushButton("선택")
        _stabilize_control(choose_icon_button, 72)
        choose_icon_button.clicked.connect(self.choose_favorite_icon)
        site_icon_button = QPushButton("사이트 아이콘")
        _stabilize_control(site_icon_button, 104)
        site_icon_button.clicked.connect(self.fetch_favorite_site_icon)
        clear_icon_button = QPushButton("비우기")
        _stabilize_control(clear_icon_button, 72)
        clear_icon_button.clicked.connect(self.clear_favorite_icon)
        icon_file_row.addWidget(choose_icon_button)
        icon_file_row.addWidget(site_icon_button)
        icon_file_row.addWidget(clear_icon_button)

        form.addRow("이름", self.favorite_title_edit)
        form.addRow("실행 대상", self.favorite_target_edit)
        form.addRow("대체 아이콘", self.favorite_icon_text_edit)
        form.addRow("아이콘 파일", icon_file_row)
        editor_layout.addLayout(form)

        action_row = QHBoxLayout()
        new_button = QPushButton("새 즐겨찾기")
        _stabilize_control(new_button, 104)
        new_button.clicked.connect(self.clear_editor)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.save_favorite)
        delete_button = QPushButton("삭제")
        _stabilize_control(delete_button, 84)
        delete_button.clicked.connect(self.delete_selected_favorite)
        action_row.addWidget(new_button)
        action_row.addStretch(1)
        action_row.addWidget(delete_button)
        action_row.addWidget(save_button)
        editor_layout.addLayout(action_row)
        editor_layout.addStretch(1)

        body_row.addWidget(editor, 2)
        layout.addLayout(body_row, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        done_button = QPushButton("완료")
        _stabilize_control(done_button, 84)
        done_button.clicked.connect(self.accept)
        button_row.addWidget(done_button)
        layout.addLayout(button_row)

        self.refresh_favorites()

    def favorite_display_mode(self) -> str:
        return _normalized_favorite_display_mode(str(self.display_mode_combo.currentData()))

    def refresh_favorites(self, selected_id: int | None = None) -> None:
        self.favorites_list.blockSignals(True)
        self.favorites_list.clear()
        selected_row = -1
        for row, favorite in enumerate(self.repository.list_link_favorites()):
            item = QListWidgetItem(favorite.title)
            item.setData(Qt.ItemDataRole.UserRole, favorite.id)
            item.setToolTip(favorite.target)
            self.favorites_list.addItem(item)
            if favorite.id == selected_id:
                selected_row = row
        self.favorites_list.blockSignals(False)
        if selected_row >= 0:
            self.favorites_list.setCurrentRow(selected_row)
        elif self.favorites_list.count():
            self.favorites_list.setCurrentRow(0)
        else:
            self.clear_editor()

    def load_selected_favorite(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        if current is None:
            self.clear_editor()
            return
        favorite_id = current.data(Qt.ItemDataRole.UserRole)
        favorite = self.repository.get_link_favorite(int(favorite_id)) if favorite_id is not None else None
        if favorite is None:
            self.clear_editor()
            return
        self.selected_favorite_id = favorite.id
        self.selected_icon_source_path = ""
        self.selected_site_icon_data = b""
        self.selected_site_icon_file_name = ""
        self.favorite_title_edit.setText(favorite.title)
        self.favorite_target_edit.setText(favorite.target)
        self.favorite_icon_text_edit.setText(favorite.icon_text)
        self.favorite_icon_path_edit.setText(favorite.icon_path)

    def clear_editor(self) -> None:
        self.selected_favorite_id = None
        self.selected_icon_source_path = ""
        self.selected_site_icon_data = b""
        self.selected_site_icon_file_name = ""
        self.favorites_list.setCurrentRow(-1)
        self.favorite_title_edit.clear()
        self.favorite_target_edit.clear()
        self.favorite_icon_text_edit.clear()
        self.favorite_icon_path_edit.clear()

    def choose_favorite_icon(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "아이콘 파일 선택",
            "",
            "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.ico *.webp);;모든 파일 (*)",
        )
        if not file_path:
            return
        self.selected_icon_source_path = file_path
        self.selected_site_icon_data = b""
        self.selected_site_icon_file_name = ""
        self.favorite_icon_path_edit.setText(file_path)

    def fetch_favorite_site_icon(self) -> None:
        target = self.favorite_target_edit.text().strip()
        if not target:
            QMessageBox.information(self, "사이트 아이콘", "먼저 URL을 입력하세요.")
            return
        try:
            file_name, data = _download_site_icon(target)
        except ValueError as exc:
            QMessageBox.information(self, "사이트 아이콘", str(exc))
            return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            QMessageBox.warning(self, "사이트 아이콘", f"사이트 아이콘을 가져오지 못했습니다.\n{exc}")
            return
        self.selected_icon_source_path = ""
        self.selected_site_icon_file_name = file_name
        self.selected_site_icon_data = data
        self.favorite_icon_path_edit.setText(f"사이트 아이콘: {file_name}")

    def clear_favorite_icon(self) -> None:
        self.selected_icon_source_path = ""
        self.selected_site_icon_data = b""
        self.selected_site_icon_file_name = ""
        self.favorite_icon_path_edit.clear()

    def save_favorite(self) -> None:
        target = self.favorite_target_edit.text().strip()
        if not target:
            QMessageBox.information(self, "즐겨찾기 설정", "열 URL이나 프로그램 경로를 입력하세요.")
            return
        title = self.favorite_title_edit.text().strip() or target
        existing = self.repository.get_link_favorite(self.selected_favorite_id) if self.selected_favorite_id else None
        favorite = existing or LinkFavorite(title=title, target=target, created_at=datetime.now())
        favorite.title = title
        favorite.target = target
        favorite.icon_text = self.favorite_icon_text_edit.text().strip()
        has_pending_icon = bool(self.selected_icon_source_path or self.selected_site_icon_data)
        favorite.icon_path = self.favorite_icon_path_edit.text().strip() if not has_pending_icon else favorite.icon_path
        favorite = self.repository.save_link_favorite(favorite)
        if self.selected_icon_source_path and favorite.id is not None:
            favorite.icon_path = self.repository.copy_link_favorite_icon(favorite.id, self.selected_icon_source_path)
            favorite = self.repository.save_link_favorite(favorite)
        elif self.selected_site_icon_data and favorite.id is not None:
            favorite.icon_path = self.repository.save_link_favorite_icon_bytes(
                favorite.id,
                self.selected_site_icon_file_name,
                self.selected_site_icon_data,
            )
            favorite = self.repository.save_link_favorite(favorite)
        self.selected_icon_source_path = ""
        self.selected_site_icon_data = b""
        self.selected_site_icon_file_name = ""
        self.refresh_favorites(favorite.id)

    def delete_selected_favorite(self) -> None:
        if self.selected_favorite_id is None:
            return
        favorite = self.repository.get_link_favorite(self.selected_favorite_id)
        if favorite is None:
            self.refresh_favorites()
            return
        answer = QMessageBox.question(self, "즐겨찾기 삭제", f"'{favorite.title}' 즐겨찾기를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_link_favorite(self.selected_favorite_id)
        self.refresh_favorites()


class ChecklistItemEditDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        item_type: str,
        item: Task | Event,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.item_type = item_type
        self.item = item
        self.item_date = self._item_date()
        item_label = _item_type_label(repository, item_type, item.item_type_id)
        self.setWindowTitle(f"{item_label} 수정")
        self.resize(420, 250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel(f"{item_label} 수정")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setText(item.title)
        _stabilize_control(self.title_edit, 260)

        self.item_type_combo = QComboBox()
        _populate_item_type_combo(self.item_type_combo, repository, item_type, item.item_type_id)
        _stabilize_control(self.item_type_combo, 150)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat(_time_edit_display_format(_preferences_from_widget(parent)))
        self.time_edit.setTime(self._item_time())
        _stabilize_control(self.time_edit, 96)

        self.use_time_check: QCheckBox | None = None
        if item_type == "task":
            task = item if isinstance(item, Task) else None
            self.use_time_check = QCheckBox("시간 지정")
            self.use_time_check.setChecked(task is not None and task.due_at is not None)
            self.use_time_check.toggled.connect(self.time_edit.setEnabled)
            self.time_edit.setEnabled(self.use_time_check.isChecked())

        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 240)
        self.minutes_spin.setValue(max(0, item.duration_minutes))
        self.minutes_spin.setSuffix("분")
        _stabilize_control(self.minutes_spin, 96)

        form.addRow("폴더", self.item_type_combo)
        form.addRow("제목", self.title_edit)
        if self.use_time_check is not None:
            form.addRow("", self.use_time_check)
        form.addRow("시간", self.time_edit)
        form.addRow("소요", self.minutes_spin)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소")
        _stabilize_control(cancel_button, 84)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def item_title(self) -> str:
        return self.title_edit.text().strip()

    def selected_time(self) -> QTime:
        return self.time_edit.time()

    def duration_minutes(self) -> int:
        return self.minutes_spin.value()

    def item_type_id(self) -> int | None:
        return _selected_item_type_id(self.item_type_combo)

    def uses_time(self) -> bool:
        return self.use_time_check is None or self.use_time_check.isChecked()

    def selected_datetime(self) -> datetime:
        qtime = self.selected_time()
        return datetime.combine(self.item_date, time(qtime.hour(), qtime.minute()))

    def accept(self) -> None:
        if not self.item_title():
            QMessageBox.information(self, "오늘 체크리스트 수정", "제목을 입력하세요.")
            return
        super().accept()

    def _item_date(self) -> date:
        if isinstance(self.item, Event):
            return self.item.start_at.date()
        if self.item.due_at is not None:
            return self.item.due_at.date()
        return date.today()

    def _item_time(self) -> QTime:
        if isinstance(self.item, Event):
            return QTime(self.item.start_at.hour, self.item.start_at.minute)
        if self.item.due_at is not None:
            return QTime(self.item.due_at.hour, self.item.due_at.minute)
        return QTime.currentTime()


class TaskAddDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        selected_date: date,
        preferences: Preference,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.preferences = preferences
        self.setWindowTitle("항목 추가")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(420, 500))
        self.resize(500, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel("항목 추가")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("추가할 항목")
        _stabilize_control(self.title_edit, 260)
        self.item_type_combo = QComboBox()
        _populate_item_type_combo(self.item_type_combo, repository, "task")
        _stabilize_control(self.item_type_combo, 150)
        form.addRow("폴더", self.item_type_combo)
        form.addRow("제목", self.title_edit)

        duration_row = QHBoxLayout()
        self.use_duration_check = QCheckBox("집중 시간 지정")
        self.use_duration_check.setChecked(False)
        duration_row.addWidget(self.use_duration_check)

        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(5, 240)
        self.minutes_spin.setValue(25)
        self.minutes_spin.setSuffix("분")
        _stabilize_control(self.minutes_spin, 96)
        self.minutes_spin.setEnabled(False)
        self.use_duration_check.toggled.connect(self.minutes_spin.setEnabled)
        duration_row.addWidget(self.minutes_spin)
        duration_row.addStretch(1)
        form.addRow("집중 시간", duration_row)
        layout.addLayout(form)

        self.use_time_check = QCheckBox("날짜와 시간 지정")
        self.use_time_check.setChecked(False)
        layout.addWidget(self.use_time_check)

        self.calendar = QCalendarWidget()
        _polish_calendar_widget(self.calendar, preferences)
        self.calendar.setSelectedDate(QDate(selected_date.year, selected_date.month, selected_date.day))
        layout.addWidget(self.calendar, 1)

        clock_row = QHBoxLayout()
        clock_row.addWidget(QLabel("시간"))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat(_time_edit_display_format(preferences))
        self.time_edit.setTime(QTime.currentTime())
        _stabilize_control(self.time_edit, 112)
        clock_row.addWidget(self.time_edit)
        clock_row.addStretch(1)
        layout.addLayout(clock_row)

        self.use_time_check.toggled.connect(self.calendar.setEnabled)
        self.use_time_check.toggled.connect(self.time_edit.setEnabled)
        self.calendar.setEnabled(False)
        self.time_edit.setEnabled(False)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소")
        _stabilize_control(cancel_button, 84)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("추가")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def item_title(self) -> str:
        return self.title_edit.text().strip()

    def duration_minutes(self) -> int:
        return self.minutes_spin.value() if self.use_duration_check.isChecked() else 0

    def item_type_id(self) -> int | None:
        return _selected_item_type_id(self.item_type_combo)

    def uses_due_time(self) -> bool:
        return self.use_time_check.isChecked()

    def selected_datetime(self) -> datetime | None:
        if not self.uses_due_time():
            return None
        selected_date = _date_from_qdate(self.calendar.selectedDate())
        selected_time = self.time_edit.time()
        return datetime.combine(selected_date, time(selected_time.hour(), selected_time.minute()))

    def accept(self) -> None:
        if not self.item_title():
            QMessageBox.information(self, "항목 추가", "추가할 제목을 입력하세요.")
            return
        super().accept()


class TodayChecklistWidget(QWidget):
    def __init__(
        self,
        repository: ScheduleRepository,
        on_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
        show_title: bool = True,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.on_changed = on_changed
        self._refreshing = False
        self.setObjectName("checklistPanel")
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        if show_title:
            title = QLabel("오늘 체크리스트")
            title.setObjectName("sectionTitle")
            title_row.addWidget(title)
        title_row.addStretch(1)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("checklistSummaryBadge")
        title_row.addWidget(self.summary_label)
        layout.addLayout(title_row)

        self.checklist_progress = QProgressBar()
        self.checklist_progress.setObjectName("checklistProgress")
        self.checklist_progress.setRange(0, 1000)
        self.checklist_progress.setTextVisible(False)
        layout.addWidget(self.checklist_progress)

        self.items_area = QScrollArea()
        self.items_area.setObjectName("checklistItemsArea")
        self.items_area.setWidgetResizable(True)
        self.items_area.setFrameShape(QFrame.Shape.NoFrame)
        self.items_area.setMinimumWidth(0)
        self.items_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items_area.setMinimumHeight(160)
        self.items_area.setMaximumHeight(16777215)

        items_widget = QWidget()
        items_widget.setMinimumWidth(0)
        self.items_layout = QVBoxLayout(items_widget)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(10)

        self.active_label = QLabel()
        self.active_label.setObjectName("eyebrowLabel")
        self.items_layout.addWidget(self.active_label)
        self.active_items_layout = QVBoxLayout()
        self.active_items_layout.setContentsMargins(0, 0, 0, 0)
        self.active_items_layout.setSpacing(6)
        self.items_layout.addLayout(self.active_items_layout)

        self.completed_label = QLabel()
        self.completed_label.setObjectName("eyebrowLabel")
        self.items_layout.addWidget(self.completed_label)
        self.completed_items_layout = QVBoxLayout()
        self.completed_items_layout.setContentsMargins(0, 0, 0, 0)
        self.completed_items_layout.setSpacing(6)
        self.items_layout.addLayout(self.completed_items_layout)
        self.items_layout.addStretch(1)

        self.items_area.setWidget(items_widget)
        layout.addWidget(self.items_area, 1)

        add_panel = QWidget()
        add_panel.setObjectName("checklistAddPanel")
        add_row = QHBoxLayout(add_panel)
        add_row.setContentsMargins(10, 9, 10, 9)
        add_row.setSpacing(8)
        self.new_task_type_combo = QComboBox()
        _populate_item_type_combo(self.new_task_type_combo, self.repository, "task")
        _stabilize_control(self.new_task_type_combo, 110)
        self.new_task_edit = QLineEdit()
        self.new_task_edit.setPlaceholderText("오늘 항목 추가")
        _stabilize_control(self.new_task_edit, 160)
        self.new_task_edit.returnPressed.connect(self.add_today_task)
        add_button = QPushButton("추가")
        add_button.setObjectName("softButton")
        _stabilize_control(add_button, 72)
        add_button.clicked.connect(self.add_today_task)
        add_row.addWidget(self.new_task_type_combo)
        add_row.addWidget(self.new_task_edit, 1)
        add_row.addWidget(add_button)
        layout.addWidget(add_panel)

        self.refresh_checklist()

    def refresh_checklist(self) -> None:
        self._refreshing = True
        try:
            self._clear_layout(self.active_items_layout)
            self._clear_layout(self.completed_items_layout)
            if hasattr(self, "new_task_type_combo"):
                current_type_id = _selected_item_type_id(self.new_task_type_combo)
                _populate_item_type_combo(self.new_task_type_combo, self.repository, "task", current_type_id)

            items = self._collect_items()
            active_items = [item for item in items if not item["completed"]]
            completed_items = [item for item in items if item["completed"]]

            active_items.sort(key=lambda item: (item["sort_at"] is None, item["sort_at"] or datetime.max, str(item["label"])))
            completed_items.sort(
                key=lambda item: item["completed_at"] or item["sort_at"] or datetime.min,
                reverse=True,
            )

            total_count = len(active_items) + len(completed_items)
            completed_ratio = 0 if total_count <= 0 else int(1000 * len(completed_items) / total_count)
            completed_percent = 0 if total_count <= 0 else round(100 * len(completed_items) / total_count)
            self.summary_label.setText(
                f"진행 중 {len(active_items)}개 · 완료 {len(completed_items)}개 · {completed_percent}%"
            )
            self.checklist_progress.setValue(completed_ratio)
            self.active_label.setText(f"진행 중 {len(active_items)}")
            self.completed_label.setText(f"완료됨 {len(completed_items)}")

            if active_items:
                for item in active_items:
                    self._add_checkbox(self.active_items_layout, item)
            else:
                self._add_empty_label(self.active_items_layout, "진행 중인 항목이 없습니다.")

            if completed_items:
                for item in completed_items:
                    self._add_checkbox(self.completed_items_layout, item)
            else:
                self._add_empty_label(self.completed_items_layout, "완료된 항목이 없습니다.")
        finally:
            self._refreshing = False

    def _collect_items(self) -> list[dict[str, object]]:
        selected_date = date.today()
        start_at, end_at = _day_window(selected_date)
        items: list[dict[str, object]] = []
        listed_event_ids: set[int] = set()

        for event in self.repository.list_events(start_at, end_at, include_completed=True):
            if event.id is None:
                continue
            listed_event_ids.add(event.id)
            display_parts = self._event_display_parts(event, selected_date)
            items.append(
                {
                    "type": "event",
                    "id": event.id,
                    "completed": event.completed,
                    "completed_at": event.completed_at,
                    "sort_at": event.start_at,
                    "label": self._event_label(event, selected_date),
                    **display_parts,
                }
            )

        for event in self.repository.list_completed_events():
            if event.id is None or event.id in listed_event_ids:
                continue
            if event.completed_at is None or event.completed_at.date() != selected_date:
                continue
            display_parts = self._event_display_parts(event, selected_date)
            items.append(
                {
                    "type": "event",
                    "id": event.id,
                    "completed": True,
                    "completed_at": event.completed_at,
                    "sort_at": event.completed_at,
                    "label": self._event_label(event, selected_date),
                    **display_parts,
                }
            )

        for task in self.repository.list_tasks(include_completed=True):
            if task.id is None:
                continue
            due_today = task.due_at is not None and task.due_at.date() == selected_date
            completed_today = task.completed_at is not None and task.completed_at.date() == selected_date
            created_today = task.created_at.date() == selected_date
            if task.completed and not (due_today or completed_today or created_today):
                continue
            sort_at = task.due_at or task.completed_at or task.created_at
            display_parts = self._task_display_parts(task, selected_date)
            items.append(
                {
                    "type": "task",
                    "id": task.id,
                    "completed": task.completed,
                    "completed_at": task.completed_at,
                    "sort_at": sort_at,
                    "label": self._task_label(task, selected_date),
                    **display_parts,
                }
            )

        return items

    def _add_checkbox(self, layout: QVBoxLayout, item: dict[str, object]) -> None:
        completed = bool(item["completed"])
        label = str(item["label"])
        row = QWidget()
        row.setObjectName("checklistRowCompleted" if completed else "checklistRow")
        row.setMinimumWidth(0)
        row.setToolTip(label)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 9, 4, 9)
        row_layout.setSpacing(12)

        checkbox = QCheckBox()
        checkbox.setObjectName("checklistItemCheckDone" if completed else "checklistItemCheck")
        checkbox.setToolTip(label)
        checkbox.setMinimumSize(22, 22)
        checkbox.setMaximumSize(22, 22)
        checkbox.setMinimumWidth(22)
        checkbox.setMaximumWidth(22)
        checkbox.setFixedHeight(22)
        checkbox.setChecked(bool(item["completed"]))
        checkbox.toggled.connect(
            lambda checked, item_type=str(item["type"]), item_id=int(item["id"]): self.set_completed(
                item_type,
                item_id,
                checked,
            )
        )
        row_layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(6)

        title_label = QLabel(str(item.get("title") or label))
        title_label.setObjectName("checklistItemTitleDone" if completed else "checklistItemTitle")
        title_label.setWordWrap(True)
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_box.addWidget(title_label)

        meta_widget = QWidget()
        meta_widget.setObjectName("checklistMetaRow")
        meta_widget.setMinimumWidth(0)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)
        meta_widget.setLayout(meta_row)
        for key, object_name in (
            ("time_label", "checklistTimeBadge"),
            ("kind", "checklistKindBadge"),
            ("detail", "checklistDetailBadge"),
        ):
            value = str(item.get(key) or "").strip()
            if not value:
                continue
            badge = QLabel(value)
            badge.setObjectName(object_name)
            badge.setMinimumWidth(0)
            badge.setMaximumWidth(170)
            badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            meta_row.addWidget(badge)
        meta_row.addStretch(1)
        text_box.addWidget(meta_widget)
        row_layout.addLayout(text_box, 1)

        for menu_widget in (row, checkbox):
            menu_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            menu_widget.customContextMenuRequested.connect(
                lambda position, widget=menu_widget, item_type=str(item["type"]), item_id=int(item["id"]), label=label: self.show_item_context_menu(
                    widget,
                    position,
                    item_type,
                    item_id,
                    label,
                )
            )
        layout.addWidget(row)

    def _task_display_parts(self, task: Task, selected_date: date) -> dict[str, str]:
        preferences = _preferences_from_widget(self)
        kind = _item_type_label(self.repository, "task", task.item_type_id)
        if task.due_at is None:
            time_label = "시간 없음"
        elif task.due_at.date() == selected_date:
            time_label = _format_time(task.due_at, preferences)
        else:
            time_label = f"마감 {_format_datetime(task.due_at, preferences)}"
        detail_parts: list[str] = []
        if task.duration_minutes > 0:
            detail_parts.append(f"{task.duration_minutes}분")
        if task.completed:
            detail_parts.append(self._completed_detail(task.completed_at, selected_date))
        return {
            "title": task.title,
            "kind": kind,
            "time_label": time_label,
            "detail": " · ".join(detail_parts),
        }

    def _event_display_parts(self, event: Event, selected_date: date) -> dict[str, str]:
        preferences = _preferences_from_widget(self)
        detail = self._completed_detail(event.completed_at, selected_date) if event.completed else ""
        return {
            "title": event.title,
            "kind": _item_type_label(self.repository, "event", event.item_type_id),
            "time_label": _format_time_range(event.start_at, event.end_at, preferences),
            "detail": detail,
        }

    def _completed_detail(self, completed_at: datetime | None, selected_date: date) -> str:
        preferences = _preferences_from_widget(self)
        if completed_at is None:
            return "완료"
        if completed_at.date() == selected_date:
            return f"완료 {_format_time(completed_at, preferences)}"
        return f"완료 {_format_datetime(completed_at, preferences)}"

    def _add_empty_label(self, layout: QVBoxLayout, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("mutedLabel")
        layout.addWidget(label)

    def add_today_task(self) -> None:
        title = self.new_task_edit.text().strip()
        if not title:
            return
        self.repository.save_task(
            Task(
                title=title,
                duration_minutes=0,
                category="today_checklist",
                created_at=datetime.now(),
                item_type_id=_selected_item_type_id(self.new_task_type_combo),
            )
        )
        self.new_task_edit.clear()
        self.refresh_after_change()

    def set_completed(self, item_type: str, item_id: int, completed: bool) -> None:
        if self._refreshing:
            return
        if item_type == "task":
            self.repository.mark_task_completed(item_id, completed)
        elif item_type == "event":
            self.repository.mark_event_completed(item_id, completed)
        if self.on_changed is not None:
            self.on_changed()
        else:
            self.refresh_checklist()

    def show_item_context_menu(
        self,
        widget: QWidget,
        position: QPoint,
        item_type: str,
        item_id: int,
        label: str,
    ) -> None:
        menu = QMenu(widget)
        edit_action = menu.addAction("수정")
        edit_action.triggered.connect(lambda _checked=False: self.edit_item(item_type, item_id))
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(lambda _checked=False: self.delete_item(item_type, item_id, label))
        menu.exec(widget.mapToGlobal(position))

    def edit_item(self, item_type: str, item_id: int) -> None:
        item: Task | Event | None
        if item_type == "task":
            item = self.repository.get_task(item_id)
        elif item_type == "event":
            item = self.repository.get_event(item_id)
        else:
            return
        if item is None:
            QMessageBox.information(self, "오늘 체크리스트 수정", "선택한 항목을 찾을 수 없습니다.")
            self.refresh_after_change()
            return

        dialog = ChecklistItemEditDialog(self.repository, item_type, item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if item_type == "task" and isinstance(item, Task):
            item.title = dialog.item_title()
            item.duration_minutes = dialog.duration_minutes()
            item.due_at = dialog.selected_datetime() if dialog.uses_time() else None
            item.item_type_id = dialog.item_type_id()
            self.repository.save_task(item)
        elif item_type == "event" and isinstance(item, Event):
            start_at = dialog.selected_datetime()
            item.title = dialog.item_title()
            item.start_at = start_at
            item.end_at = start_at + timedelta(minutes=dialog.duration_minutes())
            item.item_type_id = dialog.item_type_id()
            self.repository.save_event(item)

        self.refresh_after_change()

    def refresh_after_change(self) -> None:
        if self.on_changed is not None:
            self.on_changed()
        else:
            self.refresh_checklist()

    def delete_item(self, item_type: str, item_id: int, label: str) -> None:
        kind = self._item_kind(item_type, item_id)
        answer = QMessageBox.question(
            self,
            "오늘 체크리스트 삭제",
            f"'{_shorten(label, 48)}' {kind}을 삭제할까요?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if item_type == "task":
            self.repository.delete_task(item_id)
            owner = self.window()
            if hasattr(owner, "selected_task_id") and owner.selected_task_id == item_id:
                owner.selected_task_id = None
        elif item_type == "event":
            self.repository.delete_event(item_id)

        self.refresh_after_change()

    def _task_label(self, task: Task, selected_date: date) -> str:
        preferences = _preferences_from_widget(self)
        kind = _item_type_label(self.repository, "task", task.item_type_id)
        if task.due_at is None:
            time_label = "시간 없음"
        elif task.due_at.date() == selected_date:
            time_label = _format_time(task.due_at, preferences)
        else:
            time_label = f"마감 {_format_datetime(task.due_at, preferences)}"
        label = f"{time_label}  {kind}  {task.title}{_task_duration_suffix(task)}"
        if task.completed:
            label += self._completed_suffix(task.completed_at, selected_date)
        return label

    def _event_label(self, event: Event, selected_date: date) -> str:
        preferences = _preferences_from_widget(self)
        kind = _item_type_label(self.repository, "event", event.item_type_id)
        label = f"{_format_time_range(event.start_at, event.end_at, preferences)}  {kind}  {event.title}"
        if event.completed:
            label += self._completed_suffix(event.completed_at, selected_date)
        return label

    def _item_kind(self, item_type: str, item_id: int) -> str:
        if item_type == "task":
            task = self.repository.get_task(item_id)
            return _item_type_label(self.repository, "task", task.item_type_id if task else None)
        event = self.repository.get_event(item_id)
        return _item_type_label(self.repository, "event", event.item_type_id if event else None)

    def _completed_suffix(self, completed_at: datetime | None, selected_date: date) -> str:
        preferences = _preferences_from_widget(self)
        if completed_at is None:
            return " · 완료"
        if completed_at.date() == selected_date:
            return f" · 완료 {_format_time(completed_at, preferences)}"
        return f" · 완료 {_format_datetime(completed_at, preferences)}"

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)


class TodayTimelineWidget(QWidget):
    def __init__(
        self,
        repository: ScheduleRepository,
        parent: QWidget | None = None,
        title_text: str = "오늘 시간표",
        on_changed: Callable[[], None] | None = None,
        on_focus_task: Callable[[int], None] | None = None,
        on_delete_focus_session: Callable[[int], bool] | None = None,
        show_waiting_panel: bool = True,
        waiting_panel_pinned: bool = True,
        on_waiting_pinned_changed: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.selected_date = date.today()
        self.on_changed = on_changed
        self.on_focus_task = on_focus_task
        self.on_delete_focus_session = on_delete_focus_session
        self.show_waiting_panel = show_waiting_panel
        self.waiting_panel_pinned = waiting_panel_pinned
        self.on_waiting_pinned_changed = on_waiting_pinned_changed
        self.setObjectName("timelinePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        if title_text:
            title = QLabel(title_text)
            title.setObjectName("sectionTitle")
            title_row.addWidget(title)
        title_row.addStretch(1)
        self.date_label = QLabel()
        self.date_label.setObjectName("timelineDateBadge")
        title_row.addWidget(self.date_label)
        layout.addLayout(title_row)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("timelineSummaryBadge")
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumWidth(0)

        stat_strip = QWidget()
        stat_strip.setObjectName("timelineStatStrip")
        stat_layout = QHBoxLayout(stat_strip)
        stat_layout.setContentsMargins(0, 0, 0, 0)
        stat_layout.setSpacing(8)
        self.timeline_item_stat_label = self._build_timeline_stat_chip("항목", "0개")
        self.timeline_completed_stat_label = self._build_timeline_stat_chip("완료", "0개")
        self.timeline_focus_stat_label = self._build_timeline_stat_chip("집중 기록", "0개")
        stat_layout.addWidget(self.timeline_item_stat_label)
        stat_layout.addWidget(self.timeline_completed_stat_label)
        stat_layout.addWidget(self.timeline_focus_stat_label)
        stat_layout.addStretch(1)
        layout.addWidget(stat_strip)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("timelineContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        time_panel = QWidget()
        time_panel.setObjectName("timelineTimePanel")
        time_layout = QVBoxLayout(time_panel)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(10)

        toolbar = QWidget()
        toolbar.setObjectName("timelineToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(8)
        toolbar_layout.addWidget(self.summary_label, 0, Qt.AlignmentFlag.AlignVCenter)
        toolbar_layout.addStretch(1)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        filter_label = QLabel("보기")
        filter_label.setObjectName("mutedLabel")
        filter_row.addWidget(filter_label)
        self.timeline_filter_combo = QComboBox()
        self.timeline_filter_combo.setObjectName("timelineFilterCombo")
        self.timeline_filter_combo.addItem("전체", "all")
        self.timeline_filter_combo.addItem("항목", "schedule_task")
        self.timeline_filter_combo.addItem("완료", "completed")
        self.timeline_filter_combo.addItem("집중 기록", "focus")
        _stabilize_control(self.timeline_filter_combo, 88)
        self.timeline_filter_combo.setMinimumWidth(72)
        self.timeline_filter_combo.currentIndexChanged.connect(lambda _index: self.refresh_timeline())
        filter_row.addWidget(self.timeline_filter_combo)
        toolbar_layout.addLayout(filter_row)
        time_layout.addWidget(toolbar)

        self.block_table = QTableWidget(24, 7)
        self.block_table.setObjectName("timeBlockTable")
        self.block_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.block_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.block_table.setHorizontalHeaderLabels(["시간", "00", "10", "20", "30", "40", "50"])
        self.block_table.horizontalHeader().setVisible(True)
        self.block_table.verticalHeader().setVisible(False)
        self.block_table.setShowGrid(True)
        self.block_table.setMinimumHeight(390)
        self.block_table.setMinimumWidth(0)
        self.block_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.block_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.block_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.block_table.customContextMenuRequested.connect(
            lambda position, source=self.block_table: self.show_time_block_context_menu(position, source)
        )
        self.block_table.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.block_table.viewport().customContextMenuRequested.connect(
            lambda position, source=self.block_table.viewport(): self.show_time_block_context_menu(position, source)
        )
        self.block_table.setColumnWidth(0, 70)
        for column in range(1, 7):
            self.block_table.setColumnWidth(column, 48)
        for row in range(24):
            self.block_table.setRowHeight(row, 32)
        time_layout.addWidget(self.block_table)

        legend_bar = QWidget()
        legend_bar.setObjectName("timelineLegendBar")
        legend_row = QHBoxLayout(legend_bar)
        legend_row.setContentsMargins(10, 7, 10, 7)
        legend_row.setSpacing(14)
        for label, color in (
            ("시간 항목", "#8fb9dd"),
            ("대기 항목", "#f1d16b"),
            ("완료", "#a8cf9d"),
            ("집중", "#b9a7e8"),
        ):
            chip = QLabel(label)
            chip.setObjectName("timelineLegendChip")
            chip.setStyleSheet(
                "QLabel#timelineLegendChip {"
                f"color: {color};"
                f"background: {_color_rgba(color, 0.16)};"
                f"border: 1px solid {_color_rgba(color, 0.34)};"
                "border-radius: 8px;"
                "font-family: \"IBM Plex Mono\", \"Consolas\", \"Pretendard\", \"Segoe UI\", \"Malgun Gothic\", monospace;"
                "font-size: 11px;"
                "font-weight: 600;"
                "padding: 4px 9px;"
                "}"
            )
            legend_row.addWidget(chip)
        legend_row.addStretch(1)
        time_layout.addWidget(legend_bar)

        self.timeline_list = QListWidget(self)
        self.timeline_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.timeline_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.timeline_list.customContextMenuRequested.connect(self.show_timeline_context_menu)
        self.timeline_list.hide()

        self.content_splitter.addWidget(time_panel)
        self.waiting_rail = self._build_waiting_rail()
        self.content_splitter.addWidget(self.waiting_rail)
        self.waiting_panel = self._build_waiting_panel()
        self.content_splitter.addWidget(self.waiting_panel)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setStretchFactor(2, 1)
        self.content_splitter.setSizes([680, 42, 260])
        self.set_waiting_panel_visible(show_waiting_panel, waiting_panel_pinned, notify=False)
        layout.addWidget(self.content_splitter, 1)

        self.refresh_timeline()

    def _build_timeline_stat_chip(self, label: str, value: str) -> QLabel:
        chip = QLabel(f"{label} {value}")
        chip.setObjectName("timelineStatChip")
        chip.setMinimumWidth(0)
        return chip

    def set_waiting_panel_visible(
        self,
        visible: bool,
        pinned: bool | None = None,
        notify: bool = True,
    ) -> None:
        self.show_waiting_panel = visible
        if pinned is not None:
            self.waiting_panel_pinned = pinned
        rail_visible = visible and not self.waiting_panel_pinned
        panel_visible = visible and self.waiting_panel_pinned
        if hasattr(self, "waiting_rail"):
            self.waiting_rail.setVisible(rail_visible)
        if hasattr(self, "waiting_panel"):
            self.waiting_panel.setVisible(panel_visible)
        if hasattr(self, "waiting_pin_button"):
            self.waiting_pin_button.setText("접기" if self.waiting_panel_pinned else "고정")
            self.waiting_pin_button.setToolTip("대기함을 사이드바로 접기" if self.waiting_panel_pinned else "대기함을 펼쳐 고정")
        if visible and self.waiting_panel_pinned:
            self.content_splitter.setStretchFactor(0, 3)
            self.content_splitter.setStretchFactor(1, 0)
            self.content_splitter.setStretchFactor(2, 1)
            current_sizes = self.content_splitter.sizes()
            if len(current_sizes) == 3 and (current_sizes[2] <= 0 or current_sizes[0] <= 0):
                self.content_splitter.setSizes([680, 42, 260])
        elif visible:
            self.content_splitter.setStretchFactor(0, 1)
            self.content_splitter.setStretchFactor(1, 0)
            self.content_splitter.setStretchFactor(2, 0)
            self.content_splitter.setSizes([900, 42, 0])
        else:
            self.content_splitter.setStretchFactor(0, 1)
            self.content_splitter.setStretchFactor(1, 0)
            self.content_splitter.setStretchFactor(2, 0)
        if notify and self.on_waiting_pinned_changed is not None and pinned is not None:
            self.on_waiting_pinned_changed(self.waiting_panel_pinned)

    def set_waiting_panel_pinned(self, pinned: bool, notify: bool = True) -> None:
        self.set_waiting_panel_visible(self.show_waiting_panel, pinned, notify=notify)

    def toggle_waiting_panel_pinned(self) -> None:
        self.set_waiting_panel_pinned(not self.waiting_panel_pinned)

    def _build_waiting_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("timelineWaitingRail")
        rail.setFixedWidth(42)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(6)
        self.waiting_rail_button = QToolButton()
        self.waiting_rail_button.setObjectName("subtleToolButton")
        self.waiting_rail_button.setText("대기함")
        self.waiting_rail_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.waiting_rail_button.setMinimumHeight(64)
        self.waiting_rail_button.setToolTip("대기함을 펼쳐 고정")
        self.waiting_rail_button.clicked.connect(lambda: self.set_waiting_panel_pinned(True))
        layout.addWidget(self.waiting_rail_button)
        self.waiting_rail_label = QLabel()
        self.waiting_rail_label.setObjectName("mutedLabel")
        self.waiting_rail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.waiting_rail_label)
        layout.addStretch(1)
        return rail

    def _build_waiting_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("timelineWaitingPanel")
        panel.setMinimumWidth(0)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("대기함")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.waiting_summary_label = QLabel()
        self.waiting_summary_label.setObjectName("waitingSummaryBadge")
        title_row.addWidget(self.waiting_summary_label)
        self.waiting_pin_button = QToolButton()
        self.waiting_pin_button.setObjectName("subtleToolButton")
        self.waiting_pin_button.setText("접기")
        self.waiting_pin_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.waiting_pin_button.clicked.connect(self.toggle_waiting_panel_pinned)
        title_row.addWidget(self.waiting_pin_button)
        layout.addLayout(title_row)

        add_panel = QWidget()
        add_panel.setObjectName("timelineWaitingAddPanel")
        add_panel_layout = QVBoxLayout(add_panel)
        add_panel_layout.setContentsMargins(10, 9, 10, 9)
        add_panel_layout.setSpacing(8)

        task_row = QHBoxLayout()
        task_row.setContentsMargins(0, 0, 0, 0)
        add_task_button = QPushButton("항목 추가")
        add_task_button.setObjectName("softButton")
        _stabilize_control(add_task_button, 96)
        add_task_button.clicked.connect(self.add_waiting_task)
        task_row.addWidget(add_task_button)
        task_row.addStretch(1)
        add_panel_layout.addLayout(task_row)

        event_meta_row = QHBoxLayout()
        event_meta_row.setContentsMargins(0, 0, 0, 0)
        event_meta_row.setSpacing(6)
        self.timeline_event_type_combo = QComboBox()
        _populate_item_type_combo(self.timeline_event_type_combo, self.repository, "task")
        _stabilize_control(self.timeline_event_type_combo, 96)
        self.timeline_event_edit = QLineEdit()
        self.timeline_event_edit.setMinimumWidth(0)
        self.timeline_event_edit.setPlaceholderText("시간 있는 할 일 추가")
        _stabilize_control(self.timeline_event_edit, 120)
        self.timeline_event_time = QTimeEdit()
        self.timeline_event_time.setDisplayFormat(_time_edit_display_format(_preferences_from_widget(self)))
        self.timeline_event_time.setTime(QTime.currentTime())
        _stabilize_control(self.timeline_event_time, 76)
        add_event_button = QPushButton("추가")
        add_event_button.setObjectName("softButton")
        _stabilize_control(add_event_button, 58)
        add_event_button.clicked.connect(self.add_timeline_event)
        event_meta_row.addWidget(self.timeline_event_type_combo, 1)
        event_meta_row.addWidget(self.timeline_event_time)
        add_panel_layout.addLayout(event_meta_row)

        event_title_row = QHBoxLayout()
        event_title_row.setContentsMargins(0, 0, 0, 0)
        event_title_row.setSpacing(6)
        event_title_row.addWidget(self.timeline_event_edit, 1)
        event_title_row.addWidget(add_event_button)
        add_panel_layout.addLayout(event_title_row)
        layout.addWidget(add_panel)

        self.waiting_list = QListWidget()
        self.waiting_list.setObjectName("waitingList")
        self.waiting_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.waiting_list.itemDoubleClicked.connect(self.focus_waiting_item)
        self.waiting_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.waiting_list.customContextMenuRequested.connect(self.show_waiting_context_menu)
        layout.addWidget(self.waiting_list, 1)

        hint = QLabel("시간 없는 항목이 여기에 모입니다.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return panel

    def add_waiting_task(self) -> None:
        preferences = _preferences_from_widget(self)
        dialog = TaskAddDialog(self.repository, self.selected_date, preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        now = datetime.now()
        created_at = datetime.combine(self.selected_date, now.time().replace(microsecond=0))
        self.repository.save_task(
            Task(
                title=dialog.item_title(),
                duration_minutes=dialog.duration_minutes(),
                due_at=dialog.selected_datetime(),
                created_at=created_at,
                item_type_id=dialog.item_type_id(),
            )
        )
        self.refresh_after_change()

    def add_timeline_event(self) -> None:
        if not hasattr(self, "timeline_event_edit"):
            return
        title = self.timeline_event_edit.text().strip()
        if not title:
            return
        qtime = self.timeline_event_time.time()
        start_at = datetime.combine(self.selected_date, time(qtime.hour(), qtime.minute()))
        self.repository.save_task(
            Task(
                title=title,
                duration_minutes=30,
                due_at=start_at,
                item_type_id=_selected_item_type_id(self.timeline_event_type_combo),
            )
        )
        self.timeline_event_edit.clear()
        self.refresh_after_change()

    def show_time_block_context_menu(self, position: QPoint, source: QWidget | None = None) -> None:
        source_widget = source or self.block_table.viewport()
        block_time = self._time_for_block_position(position, source_widget)
        if block_time is None:
            return
        menu = QMenu(self.block_table)
        time_label = _format_time(block_time, _preferences_from_widget(self))
        for item_type in self.repository.list_item_types("task"):
            action = menu.addAction(f"{time_label} {item_type.name} 추가")
            action.triggered.connect(
                lambda _checked=False, target_time=block_time, type_id=item_type.id: self.add_timeline_item_from_block(
                    "task",
                    target_time,
                    type_id,
                )
            )
        menu.exec(source_widget.mapToGlobal(position))

    def _time_for_block_position(self, position: QPoint, source: QWidget | None = None) -> datetime | None:
        source_widget = source or self.block_table.viewport()
        if source_widget is self.block_table or source_widget is self.block_table.viewport():
            viewport_position = position
        else:
            viewport_position = self.block_table.viewport().mapFromGlobal(source_widget.mapToGlobal(position))
        row = self.block_table.rowAt(viewport_position.y())
        column = self.block_table.columnAt(viewport_position.x())
        if row < 0 or column < 0:
            return None
        minute = max(0, column - 1) * 10
        return datetime.combine(self.selected_date, time(row, minute))

    def add_timeline_item_from_block(
        self,
        item_type: str,
        starts_at: datetime,
        selected_item_type_id: int | None = None,
    ) -> None:
        dialog = DateItemDialog(self.repository, starts_at.date(), item_type, self, selected_item_type_id)
        dialog.time_edit.setTime(QTime(starts_at.hour, starts_at.minute))
        dialog.minutes_spin.setValue(25 if item_type == "task" else 30)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_date = dialog.selected_date_value()
        selected_time = dialog.selected_time()
        start_at = datetime.combine(selected_date, time(selected_time.hour(), selected_time.minute()))
        if item_type == "task":
            self.repository.save_task(
                Task(
                    title=dialog.item_title(),
                    duration_minutes=dialog.duration_minutes(),
                    due_at=start_at,
                    item_type_id=dialog.item_type_id(),
                )
            )
        else:
            self.repository.save_event(
                Event(
                    title=dialog.item_title(),
                    start_at=start_at,
                    end_at=start_at + timedelta(minutes=dialog.duration_minutes()),
                    fixed=True,
                    item_type_id=dialog.item_type_id(),
                )
            )
        self.refresh_after_change()

    def refresh_after_change(self) -> None:
        self.refresh_timeline()
        if self.on_changed is not None:
            self.on_changed()
        else:
            parent = self.parent()
            if hasattr(parent, "refresh_selected_date"):
                parent.refresh_selected_date()

    def refresh_waiting(self) -> None:
        if not hasattr(self, "waiting_list"):
            return
        self.waiting_list.clear()
        tasks = [
            task
            for task in self.repository.list_tasks(include_completed=False)
            if task.id is not None and task.due_at is None
        ]
        tasks.sort(key=lambda task: (task.created_at, task.title.casefold()))
        self.waiting_summary_label.setText(f"{len(tasks)}개")
        if hasattr(self, "waiting_rail_label"):
            self.waiting_rail_label.setText(str(len(tasks)))
        if not tasks:
            empty = QListWidgetItem("대기 중인 항목이 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.waiting_list.addItem(empty)
            return

        for task in tasks:
            kind = _item_type_label(self.repository, "task", task.item_type_id)
            item = QListWidgetItem(f"{kind}  {task.title}")
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "type": "task",
                    "id": task.id,
                    "title": task.title,
                    "completed": task.completed,
                },
            )
            self.waiting_list.addItem(item)

    def focus_waiting_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "task" or self.on_focus_task is None:
            return
        self.on_focus_task(int(data["id"]))

    def show_waiting_context_menu(self, position: QPoint) -> None:
        item = self.waiting_list.itemAt(position)
        if item is None:
            return
        self.waiting_list.setCurrentItem(item)
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "task":
            return

        task_id = int(data["id"])
        menu = QMenu(self.waiting_list)
        if self.on_focus_task is not None:
            focus_action = menu.addAction("집중으로 가져오기")
            focus_action.triggered.connect(lambda _checked=False: self.on_focus_task(task_id))
        edit_action = menu.addAction("수정 / 시간 지정")
        edit_action.triggered.connect(lambda _checked=False: self.edit_timeline_item("task", task_id))
        complete_action = menu.addAction("완료 처리")
        complete_action.triggered.connect(lambda _checked=False: self.set_timeline_item_completed("task", task_id, True))
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(
            lambda _checked=False: self.delete_timeline_item("task", task_id, str(data.get("title", "")))
        )
        menu.exec(self.waiting_list.mapToGlobal(position))

    def show_timeline_context_menu(self, position: QPoint) -> None:
        item = self.timeline_list.itemAt(position)
        if item is None:
            return
        self.timeline_list.setCurrentItem(item)
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = str(data.get("type", ""))
        item_id = int(data.get("id", 0))
        title = str(data.get("title", ""))
        menu = QMenu(self.timeline_list)

        if item_type == "focus_session":
            delete_action = menu.addAction("집중 기록 삭제")
            delete_action.triggered.connect(lambda _checked=False: self.delete_focus_session(item_id))
            menu.exec(self.timeline_list.mapToGlobal(position))
            return

        if item_type not in {"task", "event"}:
            return

        if item_type == "task" and self.on_focus_task is not None:
            focus_action = menu.addAction("집중으로 가져오기")
            focus_action.triggered.connect(lambda _checked=False: self.on_focus_task(item_id))
        edit_action = menu.addAction("수정")
        edit_action.triggered.connect(lambda _checked=False: self.edit_timeline_item(item_type, item_id))
        completed = bool(data.get("completed", False))
        complete_action = menu.addAction("완료 취소" if completed else "완료 처리")
        complete_action.triggered.connect(
            lambda _checked=False: self.set_timeline_item_completed(item_type, item_id, not completed)
        )
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(lambda _checked=False: self.delete_timeline_item(item_type, item_id, title))
        menu.exec(self.timeline_list.mapToGlobal(position))

    def edit_timeline_item(self, item_type: str, item_id: int) -> None:
        item: Task | Event | None
        if item_type == "task":
            item = self.repository.get_task(item_id)
        elif item_type == "event":
            item = self.repository.get_event(item_id)
        else:
            return
        if item is None:
            self.refresh_after_change()
            return

        dialog = ChecklistItemEditDialog(self.repository, item_type, item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if item_type == "task" and isinstance(item, Task):
            item.title = dialog.item_title()
            item.duration_minutes = dialog.duration_minutes()
            item.due_at = dialog.selected_datetime() if dialog.uses_time() else None
            item.item_type_id = dialog.item_type_id()
            self.repository.save_task(item)
        elif item_type == "event" and isinstance(item, Event):
            start_at = dialog.selected_datetime()
            item.title = dialog.item_title()
            item.start_at = start_at
            item.end_at = start_at + timedelta(minutes=dialog.duration_minutes())
            item.item_type_id = dialog.item_type_id()
            self.repository.save_event(item)
        self.refresh_after_change()

    def set_timeline_item_completed(self, item_type: str, item_id: int, completed: bool) -> None:
        if item_type == "task":
            self.repository.mark_task_completed(item_id, completed)
        elif item_type == "event":
            self.repository.mark_event_completed(item_id, completed)
        self.refresh_after_change()

    def delete_timeline_item(self, item_type: str, item_id: int, title: str) -> None:
        kind = self.timeline_item_kind(item_type, item_id)
        answer = QMessageBox.question(
            self,
            f"{kind} 삭제",
            f"'{_shorten(title or kind, 48)}' {kind}을 삭제할까요?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if item_type == "task":
            self.repository.delete_task(item_id)
            owner = self.window()
            if hasattr(owner, "selected_task_id") and owner.selected_task_id == item_id:
                owner.selected_task_id = None
        elif item_type == "event":
            self.repository.delete_event(item_id)
        self.refresh_after_change()

    def timeline_item_kind(self, item_type: str, item_id: int) -> str:
        if item_type == "task":
            task = self.repository.get_task(item_id)
            return _item_type_label(self.repository, "task", task.item_type_id if task else None)
        event = self.repository.get_event(item_id)
        return _item_type_label(self.repository, "event", event.item_type_id if event else None)

    def delete_focus_session(self, session_id: int) -> None:
        if self.on_delete_focus_session is not None:
            deleted = self.on_delete_focus_session(session_id)
            if deleted:
                self.refresh_after_change()
            return

        session = self.repository.get_focus_session(session_id)
        title = session.title if session else "선택한 집중 기록"
        answer = QMessageBox.question(self, "집중 기록 삭제", f"'{title}' 집중 기록을 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_focus_session(session_id)
        self.refresh_after_change()

    def set_date(self, selected_date: date) -> None:
        self.selected_date = selected_date
        self.refresh_timeline()

    def refresh_timeline(self) -> None:
        selected_date = self.selected_date
        preferences = _preferences_from_widget(self)
        if hasattr(self, "timeline_event_time"):
            self.timeline_event_time.setDisplayFormat(_time_edit_display_format(preferences))
        if hasattr(self, "timeline_event_type_combo"):
            current_type_id = _selected_item_type_id(self.timeline_event_type_combo)
            _populate_item_type_combo(self.timeline_event_type_combo, self.repository, "task", current_type_id)
        self.date_label.setText(selected_date.strftime("%Y년 %m월 %d일"))
        all_items = _today_timeline_items(self.repository, selected_date, preferences)
        all_blocks = _today_timeline_blocks(self.repository, selected_date)
        filter_key = str(self.timeline_filter_combo.currentData()) if hasattr(self, "timeline_filter_combo") else "all"
        items = [item for item in all_items if _timeline_filter_matches(item[2], filter_key)]
        blocks = [block for block in all_blocks if _timeline_filter_matches(block[2], filter_key)]
        schedule_count = sum(1 for item in all_items if item[2] in {"schedule", "task"})
        completed_count = sum(1 for item in all_items if item[2] == "completed")
        focus_count = sum(1 for item in all_items if item[2] == "focus")
        self.timeline_item_stat_label.setText(f"항목 {schedule_count}개")
        self.timeline_completed_stat_label.setText(f"완료 {completed_count}개")
        self.timeline_focus_stat_label.setText(f"집중 기록 {focus_count}개")
        visible_suffix = "" if filter_key == "all" else f" · 표시 {len(items)}개"
        self.summary_label.setText(
            f"항목 {schedule_count}개 · 완료 {completed_count}개 · 집중 기록 {focus_count}개{visible_suffix}"
        )
        _fill_time_block_table(self.block_table, selected_date, blocks, preferences)
        list_items = [item for item in items if item[2] != "completed"] if filter_key == "all" else items
        _fill_timeline_list(self.timeline_list, list_items, preferences)
        self.timeline_list.hide()
        self.refresh_waiting()
        self._resize_time_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_time_columns()

    def _resize_time_columns(self) -> None:
        viewport_width = max(0, self.block_table.viewport().width() - 4)
        if viewport_width < 260:
            hour_width = 42
        elif viewport_width < 360:
            hour_width = 50
        else:
            hour_width = 64
        self.block_table.setColumnWidth(0, hour_width)
        available_width = max(0, viewport_width - hour_width)
        block_width = max(24, available_width // 6)
        for column in range(1, 7):
            self.block_table.setColumnWidth(column, block_width)
        available_height = max(0, self.block_table.viewport().height() - 4)
        row_height = max(24, available_height // 24)
        for row in range(24):
            self.block_table.setRowHeight(row, row_height)


class TodayTimelineDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        parent: QWidget | None = None,
        on_changed: Callable[[], None] | None = None,
        on_focus_task: Callable[[int], None] | None = None,
        on_delete_focus_session: Callable[[int], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("오늘 시간표 새창")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(560, 420))
        self.resize(920, 760)
        preferences = _preferences_from_widget(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        self.always_on_top_check = _add_always_on_top_checkbox(self, top_row)
        layout.addLayout(top_row)

        self.timeline_widget = TodayTimelineWidget(
            repository,
            self,
            on_changed=on_changed,
            on_focus_task=on_focus_task,
            on_delete_focus_session=on_delete_focus_session,
            show_waiting_panel=preferences.show_today_timeline_waiting_panel,
            waiting_panel_pinned=preferences.show_today_timeline_waiting_pinned,
            on_waiting_pinned_changed=getattr(parent, "set_today_timeline_waiting_pinned", None),
        )
        layout.addWidget(self.timeline_widget, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.date_label = self.timeline_widget.date_label
        self.summary_label = self.timeline_widget.summary_label
        self.block_table = self.timeline_widget.block_table
        self.timeline_list = self.timeline_widget.timeline_list

    def refresh_timeline(self) -> None:
        self.timeline_widget.refresh_timeline()

    def refresh(self) -> None:
        preferences = _preferences_from_widget(self.parent())
        self.timeline_widget.set_waiting_panel_visible(
            preferences.show_today_timeline_waiting_panel,
            preferences.show_today_timeline_waiting_pinned,
            notify=False,
        )
        self.refresh_timeline()


class CompletedTasksDialog(QDialog):
    def __init__(self, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("완료 목록")
        self.resize(560, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("완료된 항목")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedLabel")
        layout.addWidget(self.summary_label)

        self.completed_list = QListWidget()
        self.completed_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.completed_list, 1)

        action_row = QHBoxLayout()
        self.restore_button = QPushButton("미완료로 되돌리기")
        _stabilize_control(self.restore_button, 140)
        self.restore_button.clicked.connect(self.restore_selected_task)
        self.delete_button = QPushButton("삭제")
        _stabilize_control(self.delete_button, 84)
        self.delete_button.clicked.connect(self.delete_selected_task)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.accept)
        action_row.addWidget(self.restore_button)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        action_row.addWidget(close_button)
        layout.addLayout(action_row)

        self.refresh_completed_tasks()

    def refresh_completed_tasks(self) -> None:
        self.completed_list.clear()
        tasks = self.repository.list_completed_tasks()
        events = self.repository.list_completed_events()
        completed_items = [
            ("task", task.completed_at or task.created_at, task)
            for task in tasks
        ] + [
            ("event", event.completed_at or event.start_at, event)
            for event in events
        ]
        completed_items.sort(key=lambda item: item[1], reverse=True)

        self.summary_label.setText(
            f"{len(completed_items)}개의 완료 항목이 정리되어 있습니다. "
            f"대기 항목 {len(tasks)}개 · 시간 항목 {len(events)}개"
        )

        if not completed_items:
            item = QListWidgetItem("완료 처리된 항목이 없습니다.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.completed_list.addItem(item)
            self.restore_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        self.restore_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        preferences = _preferences_from_widget(self)
        for item_type, _, completed_item in completed_items:
            completed_at = (
                _format_datetime(completed_item.completed_at, preferences)
                if completed_item.completed_at
                else "완료 시각 없음"
            )
            if item_type == "task":
                kind = _item_type_label(self.repository, "task", completed_item.item_type_id)
                due = _format_datetime(completed_item.due_at, preferences) if completed_item.due_at else "마감 없음"
                text = f"{completed_at}  [{kind}] {completed_item.title}{_task_duration_suffix(completed_item)} · {due}"
            else:
                kind = _item_type_label(self.repository, "event", completed_item.item_type_id)
                text = (
                    f"{completed_at}  [{kind}] {completed_item.title} · "
                    f"{_format_time_range(completed_item.start_at, completed_item.end_at, preferences, include_start_date=True)}"
                )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, {"type": item_type, "id": completed_item.id})
            self.completed_list.addItem(item)

    def selected_completed_item(self) -> dict[str, object] | None:
        item = self.completed_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if data else None

    def restore_selected_task(self) -> None:
        data = self.selected_completed_item()
        if data is None:
            return
        item_type = str(data["type"])
        item_id = int(data["id"])
        if item_type == "task":
            self.repository.mark_task_completed(item_id, False)
        else:
            self.repository.mark_event_completed(item_id, False)
        self.refresh_completed_tasks()

    def delete_selected_task(self) -> None:
        data = self.selected_completed_item()
        if data is None:
            return
        item_type = str(data["type"])
        item_id = int(data["id"])
        if item_type == "task":
            selected = self.repository.get_task(item_id)
            title = selected.title if selected else "선택한 항목"
            kind = _item_type_label(self.repository, "task", selected.item_type_id if selected else None)
        else:
            selected = self.repository.get_event(item_id)
            title = selected.title if selected else "선택한 항목"
            kind = _item_type_label(self.repository, "event", selected.item_type_id if selected else None)
        answer = QMessageBox.question(self, "완료 목록 삭제", f"'{title}' {kind}을 완전히 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if item_type == "task":
            self.repository.delete_task(item_id)
        else:
            self.repository.delete_event(item_id)
        self.refresh_completed_tasks()


class DateItemDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        selected_date: date,
        item_type: str,
        parent: QWidget | None = None,
        selected_item_type_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.selected_date = selected_date
        self.item_type = item_type
        item_label = _item_type_label(repository, item_type, selected_item_type_id)
        self.setWindowTitle(f"{item_label} 추가")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(420, 500))
        self.resize(500, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel(f"{selected_date:%Y년 %m월 %d일} {item_label} 추가")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        preferences = _preferences_from_widget(parent)
        self.calendar = QCalendarWidget()
        _polish_calendar_widget(self.calendar, preferences)
        self.calendar.setSelectedDate(QDate(selected_date.year, selected_date.month, selected_date.day))
        layout.addWidget(self.calendar, 1)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(f"추가할 {item_label}")
        _stabilize_control(self.title_edit, 260)
        self.item_type_combo = QComboBox()
        _populate_item_type_combo(self.item_type_combo, repository, item_type, selected_item_type_id)
        _stabilize_control(self.item_type_combo, 150)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat(_time_edit_display_format(preferences))
        self.time_edit.setTime(QTime.currentTime())
        _stabilize_control(self.time_edit, 96)
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(5, 240)
        self.minutes_spin.setValue(25 if item_type == "task" else 30)
        self.minutes_spin.setSuffix("분")
        _stabilize_control(self.minutes_spin, 96)
        form.addRow("폴더", self.item_type_combo)
        form.addRow("제목", self.title_edit)
        form.addRow("시간", self.time_edit)
        form.addRow("소요", self.minutes_spin)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소")
        _stabilize_control(cancel_button, 84)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("추가")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def item_title(self) -> str:
        return self.title_edit.text().strip()

    def selected_time(self) -> QTime:
        return self.time_edit.time()

    def selected_date_value(self) -> date:
        return _date_from_qdate(self.calendar.selectedDate())

    def duration_minutes(self) -> int:
        return self.minutes_spin.value()

    def item_type_id(self) -> int | None:
        return _selected_item_type_id(self.item_type_combo)

    def accept(self) -> None:
        if not self.item_title():
            QMessageBox.information(self, "날짜별 보기", "추가할 제목을 입력하세요.")
            return
        super().accept()


class DateReviewDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        preferences: Preference,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.preferences = preferences
        self.setWindowTitle("날짜별 보기")
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(1040, 640))
        self.resize(1500, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("날짜별 보기")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)
        content.setHandleWidth(14)

        self.calendar = QCalendarWidget()
        _polish_calendar_widget(self.calendar, preferences)
        self.calendar.setMinimumWidth(340)
        self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.selectionChanged.connect(self.refresh_selected_date)
        self._enable_calendar_context_menu()
        content.addWidget(self.calendar)

        detail_panel = QWidget()
        detail_panel.setMinimumWidth(560)
        detail_column = QVBoxLayout()
        detail_column.setContentsMargins(0, 0, 0, 0)
        detail_column.setSpacing(10)

        self.selected_date_label = QLabel()
        self.selected_date_label.setObjectName("statusLabel")
        detail_column.addWidget(self.selected_date_label)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedLabel")
        detail_column.addWidget(self.summary_label)

        detail_column.addWidget(QLabel("항목"))
        self.schedule_list = QListWidget()
        self.schedule_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.schedule_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.schedule_list.customContextMenuRequested.connect(self.show_schedule_context_menu)
        detail_column.addWidget(self.schedule_list, 1)

        detail_column.addWidget(QLabel("기록"))
        self.record_list = QListWidget()
        self.record_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.record_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.record_list.customContextMenuRequested.connect(self.show_record_context_menu)
        detail_column.addWidget(self.record_list, 2)

        detail_column.addWidget(QLabel("빠른 메모"))
        self.quick_note_list = QListWidget()
        self.quick_note_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.quick_note_list.itemDoubleClicked.connect(self.show_quick_note_detail_from_item)
        self.quick_note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_note_list.customContextMenuRequested.connect(self.show_quick_note_context_menu)
        detail_column.addWidget(self.quick_note_list, 1)

        detail_panel.setLayout(detail_column)
        content.addWidget(detail_panel)

        self.timeline_widget = TodayTimelineWidget(
            self.repository,
            self,
            title_text="선택 날짜 시간표",
            show_waiting_panel=False,
        )
        self.timeline_widget.setMinimumWidth(420)
        content.addWidget(self.timeline_widget)
        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 3)
        content.setStretchFactor(2, 2)
        content.setSizes([320, 680, 520])
        layout.addWidget(content, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.refresh_selected_date()

    def refresh_selected_date(self) -> None:
        selected_date = _date_from_qdate(self.calendar.selectedDate())
        start_at, end_at = _day_window(selected_date)
        schedule_items = _schedule_items_for_date(self.repository, selected_date, start_at, end_at, self.preferences)
        record_items = _record_items_for_date(self.repository, selected_date, start_at, end_at, self.preferences)
        quick_note_items = _quick_note_items_for_date(self.repository, start_at, end_at, self.preferences)

        self.selected_date_label.setText(selected_date.strftime("%Y년 %m월 %d일"))
        self.summary_label.setText(
            f"항목 {len(schedule_items)}개 · 기록 {len(record_items)}개 · 메모 {len(quick_note_items)}개"
        )
        _fill_list(self.schedule_list, schedule_items, "이 날짜에 표시할 항목이 없습니다.")
        _fill_list(self.record_list, record_items, "이 날짜에 표시할 기록이 없습니다.")
        _fill_list(self.quick_note_list, quick_note_items, "이 날짜에 작성한 빠른 메모가 없습니다.")
        self.timeline_widget.set_date(selected_date)

    def _enable_calendar_context_menu(self) -> None:
        self.calendar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.calendar.customContextMenuRequested.connect(self.show_calendar_context_menu)
        calendar_view = self._calendar_view()
        if calendar_view is None:
            return
        calendar_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        calendar_view.customContextMenuRequested.connect(
            lambda position, source=calendar_view: self.show_calendar_context_menu(position, source)
        )
        calendar_view.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        calendar_view.viewport().customContextMenuRequested.connect(
            lambda position, source=calendar_view.viewport(): self.show_calendar_context_menu(position, source)
        )

    def show_calendar_context_menu(self, position: QPoint, source: QWidget | None = None) -> None:
        selected_date = self._calendar_date_at(position, source) or _date_from_qdate(self.calendar.selectedDate())
        self.calendar.setSelectedDate(QDate(selected_date.year, selected_date.month, selected_date.day))
        menu = QMenu(self.calendar)
        for item_type in self.repository.list_item_types("task"):
            action = menu.addAction(f"{selected_date:%m/%d} {item_type.name} 추가")
            action.triggered.connect(
                lambda _checked=False, day=selected_date, type_id=item_type.id: self.show_date_item_dialog(
                    "task",
                    day,
                    type_id,
                )
            )
        widget = source or self.calendar
        menu.exec(widget.mapToGlobal(position))

    def _calendar_view(self) -> QAbstractItemView | None:
        for view in self.calendar.findChildren(QAbstractItemView):
            if view.objectName() == "qt_calendar_calendarview":
                return view
        return None

    def _calendar_date_at(self, position: QPoint, source: QWidget | None = None) -> date | None:
        calendar_view = self._calendar_view()
        if calendar_view is None:
            return None

        widget = source or self.calendar
        view_position = calendar_view.viewport().mapFromGlobal(widget.mapToGlobal(position))
        index = calendar_view.indexAt(view_position)
        if not index.isValid() or index.row() <= 0:
            return None

        date_column = index.column() - self._calendar_date_column_offset()
        if date_column < 0 or date_column > 6:
            return None

        year = self.calendar.yearShown()
        month = self.calendar.monthShown()
        first_day = QDate(year, month, 1)
        first_weekday = _qt_day_value(self.calendar.firstDayOfWeek())
        offset = (first_day.dayOfWeek() - first_weekday) % 7
        extra_previous_week = 7 if offset == 0 else 0
        first_visible_day = first_day.addDays(-offset - extra_previous_week)
        clicked_day = first_visible_day.addDays((index.row() - 1) * 7 + date_column)
        return _date_from_qdate(clicked_day)

    def _calendar_date_column_offset(self) -> int:
        if self.calendar.verticalHeaderFormat() == QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader:
            return 0
        return 1

    def show_date_item_dialog(
        self,
        item_type: str,
        selected_date: date,
        selected_item_type_id: int | None = None,
    ) -> None:
        dialog = DateItemDialog(self.repository, selected_date, item_type, self, selected_item_type_id)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.save_selected_date_item(
            item_type,
            dialog.item_title(),
            dialog.selected_time(),
            dialog.duration_minutes(),
            dialog.selected_date_value(),
            dialog.item_type_id(),
        )

    def save_selected_date_item(
        self,
        item_type: str,
        title: str,
        selected_time: QTime,
        duration_minutes: int,
        selected_date: date | None = None,
        item_type_id: int | None = None,
    ) -> None:
        target_date = selected_date or _date_from_qdate(self.calendar.selectedDate())
        starts_at = datetime.combine(target_date, time(selected_time.hour(), selected_time.minute()))
        if item_type == "task":
            self.repository.save_task(
                Task(title=title, duration_minutes=duration_minutes, due_at=starts_at, item_type_id=item_type_id)
            )
        else:
            self.repository.save_event(
                Event(
                    title=title,
                    start_at=starts_at,
                    end_at=starts_at + timedelta(minutes=duration_minutes),
                    fixed=True,
                    item_type_id=item_type_id,
                )
            )
        self.refresh_selected_date()

    def show_schedule_context_menu(self, position: QPoint) -> None:
        self._show_delete_context_menu(self.schedule_list, position)

    def show_record_context_menu(self, position: QPoint) -> None:
        self._show_delete_context_menu(self.record_list, position)

    def show_quick_note_context_menu(self, position: QPoint) -> None:
        self._show_delete_context_menu(self.quick_note_list, position)

    def show_quick_note_detail_from_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "quick_note":
            return
        dialog = QuickNoteDetailDialog(self.repository, int(data["id"]), self)
        dialog.exec()
        self.refresh_selected_date()
        parent = self.parent()
        if hasattr(parent, "refresh_all"):
            parent.refresh_all()

    def _show_delete_context_menu(self, list_widget: QListWidget, position: QPoint) -> None:
        item = list_widget.itemAt(position)
        if item is None:
            return
        list_widget.setCurrentItem(item)
        if item.data(Qt.ItemDataRole.UserRole) is None:
            return

        menu = QMenu(list_widget)
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(lambda _checked=False, target=list_widget: self.delete_selected_date_item(target))
        menu.exec(list_widget.mapToGlobal(position))

    def delete_selected_date_item(self, list_widget: QListWidget) -> None:
        item = list_widget.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            QMessageBox.information(self, "날짜별 보기 삭제", "삭제할 항목을 선택하세요.")
            return

        item_type = str(data["type"])
        item_id = int(data["id"])
        kind = str(data["kind"])
        title = str(data["title"])
        message = f"'{title}' {kind}을 삭제할까요?"
        if item_type == "focus_session" and self._is_active_focus_session(item_id):
            message += "\n진행 중인 타이머도 함께 중단됩니다."

        answer = QMessageBox.question(self, "날짜별 보기 삭제", message)
        if answer != QMessageBox.StandardButton.Yes:
            return

        if item_type == "task":
            self.repository.delete_task(item_id)
        elif item_type == "event":
            self.repository.delete_event(item_id)
        elif item_type == "focus_session":
            self._stop_active_focus_session_if_needed(item_id)
            self.repository.delete_focus_session(item_id)
        elif item_type == "quick_note":
            self.repository.delete_quick_note(item_id)
        else:
            return

        self.refresh_selected_date()
        parent = self.parent()
        if hasattr(parent, "refresh_all"):
            parent.refresh_all()

    def _is_active_focus_session(self, session_id: int) -> bool:
        parent = self.parent()
        focus_timer = getattr(parent, "focus_timer", None)
        session = focus_timer.session if focus_timer else None
        return session is not None and session.id == session_id

    def _stop_active_focus_session_if_needed(self, session_id: int) -> None:
        parent = self.parent()
        focus_timer = getattr(parent, "focus_timer", None)
        session = focus_timer.session if focus_timer else None
        if session is None or session.id != session_id:
            return
        if session.status in {"running", "paused", "break"}:
            focus_timer.stop(status="cancelled")
        focus_timer.session = None
        focus_timer.last_tick_at = None
        focus_timer.segment_type = None
        focus_timer.segment_started_at = None
        if hasattr(parent, "break_until"):
            parent.break_until = None
        if hasattr(parent, "focus_tick_timer"):
            parent.focus_tick_timer.stop()
        if hasattr(parent, "update_focus_display"):
            parent.update_focus_display()


class ItemTypeSettingsDialog(QDialog):
    def __init__(self, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.selected_type_id: int | None = None
        self.setWindowTitle("할 일 폴더 관리")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(520, 420))
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel("할 일 폴더")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        body = QHBoxLayout()
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)
        list_title = QLabel("폴더 목록")
        list_title.setObjectName("mutedLabel")
        list_layout.addWidget(list_title)
        self.type_list = QListWidget()
        self.type_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.type_list.currentItemChanged.connect(self.load_selected_type)
        list_layout.addWidget(self.type_list, 1)
        body.addWidget(list_panel, 1)

        form_panel = QWidget()
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)

        form = QFormLayout()
        self.type_name_edit = QLineEdit()
        self.type_name_edit.setPlaceholderText("예: 업무, 개인, 공부")
        _stabilize_control(self.type_name_edit, 220)
        form.addRow("폴더 이름", self.type_name_edit)

        self.default_check = QCheckBox("기본 폴더로 사용")
        form.addRow("", self.default_check)
        form_layout.addLayout(form)

        hint = QLabel("할 일 폴더는 오늘 체크리스트, 대기함, 날짜별 보기에서 같은 묶음으로 사용됩니다. 폴더를 삭제하면 그 안의 할 일은 기본 폴더로 옮겨집니다.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        form_layout.addWidget(hint)

        action_row = QHBoxLayout()
        new_button = QPushButton("새 폴더")
        _stabilize_control(new_button, 88)
        new_button.clicked.connect(self.clear_form)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.save_current_type)
        delete_button = QPushButton("삭제")
        _stabilize_control(delete_button, 84)
        delete_button.clicked.connect(self.delete_selected_type)
        action_row.addWidget(new_button)
        action_row.addWidget(save_button)
        action_row.addWidget(delete_button)
        form_layout.addLayout(action_row)
        form_layout.addStretch(1)
        body.addWidget(form_panel, 1)
        layout.addLayout(body, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("닫기")
        _stabilize_control(close_button, 84)
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.refresh_types()

    def refresh_types(self, selected_type_id: int | None = None) -> None:
        self.type_list.clear()
        selected_row = 0
        task_counts = self._task_counts_by_type()
        for row_index, item_type in enumerate(self.repository.list_item_types("task")):
            item = QListWidgetItem(self._item_type_label(item_type, task_counts.get(item_type.id or -1, 0)))
            item.setData(Qt.ItemDataRole.UserRole, item_type.id)
            self.type_list.addItem(item)
            if selected_type_id is not None and item_type.id == selected_type_id:
                selected_row = row_index
        if self.type_list.count():
            self.type_list.setCurrentRow(selected_row)
        else:
            self.clear_form()

    def load_selected_type(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            self.clear_form()
            return
        item_type_id = current.data(Qt.ItemDataRole.UserRole)
        item_type = self.repository.get_item_type(int(item_type_id)) if item_type_id is not None else None
        if item_type is None:
            self.clear_form()
            return
        self.selected_type_id = item_type.id
        self.type_name_edit.setText(item_type.name)
        self.default_check.setChecked(item_type.is_default)

    def clear_form(self) -> None:
        self.selected_type_id = None
        self.type_list.clearSelection()
        self.type_name_edit.clear()
        self.default_check.setChecked(False)
        self.type_name_edit.setFocus()

    def save_current_type(self) -> None:
        name = self.type_name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "할 일 폴더 관리", "폴더 이름을 입력하세요.")
            return
        if self.selected_type_id is None:
            item_type = ItemType(
                name=name,
                base_kind="task",
                is_default=self.default_check.isChecked(),
            )
        else:
            item_type = self.repository.get_item_type(self.selected_type_id)
            if item_type is None:
                self.refresh_types()
                return
            item_type.name = name
            item_type.is_default = self.default_check.isChecked()
        try:
            saved = self.repository.save_item_type(item_type)
        except ValueError as exc:
            QMessageBox.warning(self, "할 일 폴더 관리", str(exc))
            return
        self.refresh_types(saved.id)

    def delete_selected_type(self) -> None:
        if self.selected_type_id is None:
            return
        item_type = self.repository.get_item_type(self.selected_type_id)
        if item_type is None:
            self.refresh_types()
            return
        answer = QMessageBox.question(self, "할 일 폴더 삭제", f"'{item_type.name}' 폴더를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.repository.delete_item_type(self.selected_type_id):
            QMessageBox.information(self, "할 일 폴더 삭제", "기본 폴더는 삭제할 수 없습니다. 이름을 바꾸거나 다른 폴더를 기본으로 지정하세요.")
            return
        self.refresh_types()

    def _task_counts_by_type(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        default_id = self.repository.default_item_type("task").id
        for task in self.repository.list_tasks(include_completed=True):
            item_type_id = task.item_type_id or default_id
            if item_type_id is None:
                continue
            counts[item_type_id] = counts.get(item_type_id, 0) + 1
        return counts

    def _item_type_label(self, item_type: ItemType, task_count: int = 0) -> str:
        default = " · 기본" if item_type.is_default else ""
        return f"{item_type.name} · {task_count}개{default}"


class SettingsDialog(QDialog):
    def __init__(self, preferences: Preference, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(700, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")
        layout.addWidget(self.settings_tabs, 1)

        general_form = self._add_settings_tab("기본")
        color_form = self._add_settings_tab("색상")
        display_form = self._add_settings_tab("화면")
        feature_form = self._add_settings_tab("기능")
        layout_form = self._add_settings_tab("배치")

        self.week_start_combo = QComboBox()
        self.week_start_combo.addItem("월요일", 0)
        self.week_start_combo.addItem("일요일", 6)
        index = self.week_start_combo.findData(6 if preferences.week_start_day == 6 else 0)
        self.week_start_combo.setCurrentIndex(max(0, index))
        general_form.addRow("한 주의 시작", self.week_start_combo)

        self.app_title_edit = QLineEdit()
        self.app_title_edit.setText(preferences.app_title)
        self.app_title_edit.setPlaceholderText("예: Focus Desk")
        general_form.addRow("창 제목", self.app_title_edit)

        self.main_always_on_top_check = SwitchCheckBox("메인창 항상 위")
        self.main_always_on_top_check.setChecked(preferences.main_always_on_top)
        general_form.addRow("메인창 표시", self.main_always_on_top_check)

        self.accent_color = _normalize_accent_color(preferences.accent_color)
        self.button_color = _normalize_accent_color(getattr(preferences, "button_color", "#4f8c6b"))
        self.background_color = _normalize_optional_color(preferences.background_color)
        self.inner_background_color = _normalize_optional_color(preferences.inner_background_color)
        self.panel_color = _normalize_optional_color(preferences.panel_color)
        self.table_color = _normalize_optional_color(preferences.table_color)
        self.text_color = _normalize_optional_color(preferences.text_color)
        color_form.addRow(
            self._build_color_group(
                "전체 색",
                "바깥 배경을 바꾸면 따로 지정하지 않은 안쪽 배경, 카드, 표 색까지 같은 톤으로 맞춥니다.",
                (
                    ("background", "바깥 배경", "", "앱 전체 바탕"),
                    ("accent", "강조", "#4f8c6b", "선택과 진행률"),
                    ("button", "버튼", "#4f8c6b", "버튼 배경"),
                    ("text", "글자", "", "전체 글자"),
                ),
            )
        )
        color_form.addRow(
            self._build_color_group(
                "내용 색",
                "필요할 때만 개별 영역을 덮어씁니다. 비워두면 전체 색을 따라갑니다.",
                (
                    ("inner_background", "안쪽 배경", "", "메인 작업 영역"),
                    ("panel", "카드/입력", "", "패널과 입력칸"),
                    ("table", "시간표", "", "표와 시간칸"),
                ),
            )
        )

        self.time_format_combo = QComboBox()
        self.time_format_combo.addItem("24시간 (13:30)", "24h")
        self.time_format_combo.addItem("12시간 (PM 1:30)", "12h")
        time_index = self.time_format_combo.findData(preferences.time_format)
        self.time_format_combo.setCurrentIndex(max(0, time_index))
        general_form.addRow("시간 표시", self.time_format_combo)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("라이트", "light")
        self.theme_combo.addItem("다크", "dark")
        theme_index = self.theme_combo.findData(_normalize_theme(preferences.appearance_theme))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        general_form.addRow("테마", self.theme_combo)

        self.focus_rate_display_combo = QComboBox()
        self.focus_rate_display_combo.addItem("링", "ring")
        self.focus_rate_display_combo.addItem("막대", "bar")
        focus_rate_index = self.focus_rate_display_combo.findData(
            _normalize_focus_rate_display(preferences.focus_rate_display)
        )
        self.focus_rate_display_combo.setCurrentIndex(max(0, focus_rate_index))
        general_form.addRow("집중률 표시", self.focus_rate_display_combo)

        self.show_datetime_panel_check = SwitchCheckBox("메인 화면에 표시")
        self.show_datetime_panel_check.setChecked(preferences.show_datetime_panel)
        display_form.addRow("날짜/시간 패널", self.show_datetime_panel_check)

        self.show_current_date_check = SwitchCheckBox("날짜 표시")
        self.show_current_date_check.setChecked(preferences.show_current_date)
        display_form.addRow("현재 날짜", self.show_current_date_check)

        self.show_current_time_check = SwitchCheckBox("시간 표시")
        self.show_current_time_check.setChecked(preferences.show_current_time)
        display_form.addRow("현재 시간", self.show_current_time_check)

        self.show_current_seconds_check = SwitchCheckBox("초 표시")
        self.show_current_seconds_check.setChecked(preferences.show_current_seconds)
        display_form.addRow("현재 초", self.show_current_seconds_check)

        self.show_header_banner_check = SwitchCheckBox("메인 화면에 표시")
        self.show_header_banner_check.setChecked(preferences.show_header_banner)
        display_form.addRow("헤더 배너", self.show_header_banner_check)

        header_image_row = QHBoxLayout()
        self.header_banner_path_edit = QLineEdit()
        self.header_banner_path_edit.setReadOnly(True)
        self.header_banner_path_edit.setPlaceholderText("이미지를 선택하지 않음")
        self.header_banner_path_edit.setText(preferences.header_banner_image_path)
        _stabilize_control(self.header_banner_path_edit, 260)
        header_image_row.addWidget(self.header_banner_path_edit, 1)
        choose_header_image_button = QPushButton("이미지 선택")
        _stabilize_control(choose_header_image_button, 96)
        choose_header_image_button.clicked.connect(self.choose_header_banner_image)
        header_image_row.addWidget(choose_header_image_button)
        clear_header_image_button = QPushButton("지우기")
        _stabilize_control(clear_header_image_button, 72)
        clear_header_image_button.clicked.connect(lambda: self.set_header_banner_image_path(""))
        header_image_row.addWidget(clear_header_image_button)
        display_form.addRow("배너 이미지", header_image_row)

        self.header_banner_height_spin = QSpinBox()
        self.header_banner_height_spin.setRange(72, 360)
        self.header_banner_height_spin.setValue(_normalize_header_banner_height(preferences.header_banner_height))
        self.header_banner_height_spin.setSuffix("px")
        _stabilize_control(self.header_banner_height_spin, 110)
        display_form.addRow("배너 높이", self.header_banner_height_spin)

        self.header_banner_position_combo = QComboBox()
        self.header_banner_position_combo.addItem("왼쪽 칸", "left")
        self.header_banner_position_combo.addItem("가운데 칸", "center")
        self.header_banner_position_combo.addItem("오른쪽 칸", "right")
        banner_position_index = self.header_banner_position_combo.findData(
            _normalize_header_banner_position(preferences.header_banner_position)
        )
        self.header_banner_position_combo.setCurrentIndex(max(0, banner_position_index))
        _stabilize_control(self.header_banner_position_combo, 130)

        self.show_pomodoro_check = SwitchCheckBox("표시")
        self.show_focus_panel_check = SwitchCheckBox("메인 화면에 표시")
        self.show_focus_panel_check.setChecked(preferences.show_focus_panel)
        feature_form.addRow("집중", self.show_focus_panel_check)

        self.show_pomodoro_check.setChecked(preferences.show_pomodoro_controls)
        feature_form.addRow("뽀모도로", self.show_pomodoro_check)

        self.show_today_timeline_inline_check = SwitchCheckBox("메인 화면에 표시")
        self.show_today_timeline_inline_check.setChecked(preferences.show_today_timeline_inline)
        feature_form.addRow("오늘 시간표", self.show_today_timeline_inline_check)

        self.show_today_timeline_waiting_check = SwitchCheckBox("대기함 표시")
        self.show_today_timeline_waiting_check.setChecked(preferences.show_today_timeline_waiting_panel)
        feature_form.addRow("시간표 대기함", self.show_today_timeline_waiting_check)

        self.show_today_timeline_waiting_pinned_check = SwitchCheckBox("대기함을 펼쳐서 고정")
        self.show_today_timeline_waiting_pinned_check.setChecked(preferences.show_today_timeline_waiting_pinned)
        feature_form.addRow("대기함 고정", self.show_today_timeline_waiting_pinned_check)

        self.show_today_checklist_inline_check = SwitchCheckBox("메인 화면에 표시")
        self.show_today_checklist_inline_check.setChecked(preferences.show_today_checklist_inline)
        feature_form.addRow("오늘 체크리스트", self.show_today_checklist_inline_check)

        self.show_quick_memo_panel_check = SwitchCheckBox("메인 화면에 표시")
        self.show_quick_memo_panel_check.setChecked(preferences.show_quick_memo_panel)
        feature_form.addRow("빠른 메모", self.show_quick_memo_panel_check)

        self.show_link_favorites_panel_check = SwitchCheckBox("메인 화면에 표시")
        self.show_link_favorites_panel_check.setChecked(preferences.show_link_favorites_panel)
        feature_form.addRow("즐겨찾기", self.show_link_favorites_panel_check)

        self.show_media_panel_check = SwitchCheckBox("메인 화면에 표시")
        self.show_media_panel_check.setChecked(preferences.show_media_panel)
        feature_form.addRow("이미지", self.show_media_panel_check)

        self.show_compact_favorites_panel_check = SwitchCheckBox("통합 위젯에 표시")
        self.show_compact_favorites_panel_check.setChecked(preferences.show_compact_favorites_panel)
        feature_form.addRow("위젯 즐겨찾기", self.show_compact_favorites_panel_check)

        layout_tools_panel = QWidget()
        layout_tools_row = QHBoxLayout(layout_tools_panel)
        layout_tools_row.setContentsMargins(0, 0, 0, 0)
        layout_tools_row.setSpacing(8)
        save_layout_button = QPushButton("화면 저장")
        _stabilize_control(save_layout_button, 88)
        save_layout_button.clicked.connect(lambda: self.run_parent_layout_action("save_layout_profile"))
        load_layout_button = QPushButton("화면 불러오기")
        _stabilize_control(load_layout_button, 104)
        load_layout_button.clicked.connect(lambda: self.run_parent_layout_action("load_layout_profile"))
        reset_layout_button = QPushButton("기본 배치")
        _stabilize_control(reset_layout_button, 88)
        reset_layout_button.clicked.connect(lambda: self.run_parent_layout_action("reset_main_layout"))
        layout_tools_row.addWidget(save_layout_button)
        layout_tools_row.addWidget(load_layout_button)
        layout_tools_row.addWidget(reset_layout_button)
        layout_tools_row.addStretch(1)
        layout_form.addRow("화면 배치", layout_tools_panel)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소")
        _stabilize_control(cancel_button, 84)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("저장")
        _stabilize_control(save_button, 84)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

        self._source = preferences

    def _add_settings_tab(self, title: str) -> QFormLayout:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsTabScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        page = QWidget()
        page.setObjectName("settingsTabPage")
        form = QFormLayout(page)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        scroll_area.setWidget(page)
        self.settings_tabs.addTab(scroll_area, title)
        return form

    def _build_color_group(
        self,
        title: str,
        description: str,
        controls: tuple[tuple[str, str, str, str], ...],
    ) -> QWidget:
        group = QWidget()
        group.setObjectName("settingsColorGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(9)

        title_label = QLabel(title)
        title_label.setObjectName("settingsGroupTitle")
        layout.addWidget(title_label)

        description_label = QLabel(description)
        description_label.setObjectName("mutedLabel")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, (key, label, default_color, hint) in enumerate(controls):
            item = QWidget()
            item.setObjectName("settingsColorItem")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(10, 9, 10, 10)
            item_layout.setSpacing(6)

            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(6)
            name_label = QLabel(label)
            name_label.setObjectName("settingsColorLabel")
            label_row.addWidget(name_label)
            hint_label = QLabel(hint)
            hint_label.setObjectName("mutedLabel")
            hint_label.setWordWrap(True)
            label_row.addWidget(hint_label, 1)
            item_layout.addLayout(label_row)
            item_layout.addWidget(self._build_color_control(key, default_color, label))
            grid.addWidget(item, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return group

    def run_parent_layout_action(self, action_name: str) -> None:
        parent = self.parent()
        action = getattr(parent, action_name, None)
        if action is None:
            return
        action()
        preferences = getattr(parent, "preferences", self._source)
        self.sync_from_preferences(preferences)

    def _build_color_control(self, key: str, default_color: str, title: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        control_row = QHBoxLayout()
        control_row.setSpacing(6)
        swatch = QLabel()
        swatch.setFixedSize(38, 24)
        setattr(self, f"{key}_swatch", swatch)
        control_row.addWidget(swatch)

        choose_button = QPushButton("색 선택")
        _stabilize_control(choose_button, 68)
        choose_button.clicked.connect(lambda _checked=False, name=key, label=title, default=default_color: self.choose_setting_color(name, label, default))
        control_row.addWidget(choose_button)

        picker_button = QPushButton("스포이트")
        _stabilize_control(picker_button, 72)
        picker_button.clicked.connect(lambda _checked=False, name=key: self.pick_screen_color(name))
        control_row.addWidget(picker_button)

        reset_button = QPushButton("기본값")
        _stabilize_control(reset_button, 62)
        reset_button.clicked.connect(lambda _checked=False, name=key, default=default_color: self.set_setting_color(name, default))
        control_row.addWidget(reset_button)
        control_row.addStretch(1)
        layout.addLayout(control_row)

        for label, colors in (("파스텔", PASTEL_COLOR_PRESETS), ("모노톤", MONOTONE_COLOR_PRESETS)):
            preset_row = QHBoxLayout()
            preset_row.setSpacing(5)
            preset_label = QLabel(label)
            preset_label.setObjectName("mutedLabel")
            preset_label.setFixedWidth(38)
            preset_row.addWidget(preset_label)
            for color in colors:
                button = QPushButton("")
                button.setFixedSize(21, 21)
                button.setToolTip(color)
                button.setStyleSheet(f"background: {color}; border: 1px solid #d0d7d2; border-radius: 6px;")
                button.clicked.connect(lambda _checked=False, name=key, value=color: self.set_setting_color(name, value))
                preset_row.addWidget(button)
            preset_row.addStretch(1)
            layout.addLayout(preset_row)

        self.update_setting_color_swatch(key)
        return container

    def choose_setting_color(self, key: str, title: str, default_color: str = "") -> None:
        current_color = self.setting_color_value(key) or default_color or _theme_palette(str(self.theme_combo.currentData()))["bg"]
        color = QColorDialog.getColor(QColor(current_color), self, title)
        if color.isValid():
            self.set_setting_color(key, color.name())

    def pick_screen_color(self, key: str) -> None:
        self.statusBarMessage("마우스를 원하는 색 위에 올려두세요. 잠시 뒤 색을 가져옵니다.")
        QTimer.singleShot(1200, lambda name=key: self.apply_screen_color_sample(name))

    def apply_screen_color_sample(self, key: str) -> None:
        position = QCursor.pos()
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        if screen is None:
            self.statusBarMessage("스포이트로 색을 가져오지 못했습니다.")
            return
        pixmap = screen.grabWindow(0, position.x(), position.y(), 1, 1)
        if pixmap.isNull():
            self.statusBarMessage("스포이트로 색을 가져오지 못했습니다.")
            return
        color = pixmap.toImage().pixelColor(0, 0)
        if color.isValid():
            self.set_setting_color(key, color.name())
            self.statusBarMessage(f"{color.name()} 색을 가져왔습니다.")

    def statusBarMessage(self, message: str) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "statusBar"):
            parent.statusBar().showMessage(message, 2200)

    def setting_color_value(self, key: str) -> str:
        return str(getattr(self, f"{key}_color", ""))

    def set_setting_color(self, key: str, color: str) -> None:
        normalized = _normalize_accent_color(color) if key in {"accent", "button"} else _normalize_optional_color(color)
        setattr(self, f"{key}_color", normalized)
        self.update_setting_color_swatch(key)

    def update_setting_color_swatch(self, key: str) -> None:
        swatch = getattr(self, f"{key}_swatch", None)
        if not isinstance(swatch, QLabel):
            return
        color = self.setting_color_value(key)
        swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            swatch.setText("")
            swatch.setStyleSheet(f"background: {color}; border: 1px solid #d0d7d2; border-radius: 8px;")
        else:
            swatch.setText("기본")
            swatch.setStyleSheet(
                "background: transparent; border: 1px solid #d0d7d2; border-radius: 8px; color: #5c5c66;"
            )

    def choose_accent_color(self) -> None:
        self.choose_setting_color("accent", "강조색", "#4f8c6b")

    def set_accent_color(self, color: str) -> None:
        self.set_setting_color("accent", color)

    def choose_background_color(self) -> None:
        self.choose_setting_color("background", "바깥 배경색")

    def set_background_color(self, color: str) -> None:
        self.set_setting_color("background", color)

    def choose_header_banner_image(self) -> None:
        image_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "헤더 배너 이미지 선택",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*.*)",
        )
        if image_path:
            self.set_header_banner_image_path(image_path)

    def set_header_banner_image_path(self, image_path: str) -> None:
        if hasattr(self, "header_banner_path_edit"):
            self.header_banner_path_edit.setText(image_path.strip())

    def sync_from_preferences(self, preferences: Preference) -> None:
        self.app_title_edit.setText(preferences.app_title)
        self.set_accent_color(preferences.accent_color)
        self.set_setting_color("button", getattr(preferences, "button_color", "#4f8c6b"))
        self.set_background_color(preferences.background_color)
        self.set_setting_color("inner_background", preferences.inner_background_color)
        self.set_setting_color("panel", preferences.panel_color)
        self.set_setting_color("table", preferences.table_color)
        self.set_setting_color("text", preferences.text_color)
        time_index = self.time_format_combo.findData(preferences.time_format)
        self.time_format_combo.setCurrentIndex(max(0, time_index))
        theme_index = self.theme_combo.findData(_normalize_theme(preferences.appearance_theme))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        focus_rate_index = self.focus_rate_display_combo.findData(
            _normalize_focus_rate_display(preferences.focus_rate_display)
        )
        self.focus_rate_display_combo.setCurrentIndex(max(0, focus_rate_index))
        self.main_always_on_top_check.setChecked(preferences.main_always_on_top)
        self.show_datetime_panel_check.setChecked(preferences.show_datetime_panel)
        self.show_current_date_check.setChecked(preferences.show_current_date)
        self.show_current_time_check.setChecked(preferences.show_current_time)
        self.show_current_seconds_check.setChecked(preferences.show_current_seconds)
        self.show_header_banner_check.setChecked(preferences.show_header_banner)
        self.set_header_banner_image_path(preferences.header_banner_image_path)
        self.header_banner_height_spin.setValue(_normalize_header_banner_height(preferences.header_banner_height))
        banner_position_index = self.header_banner_position_combo.findData(
            _normalize_header_banner_position(preferences.header_banner_position)
        )
        self.header_banner_position_combo.setCurrentIndex(max(0, banner_position_index))
        self.show_focus_panel_check.setChecked(preferences.show_focus_panel)
        self.show_pomodoro_check.setChecked(preferences.show_pomodoro_controls)
        self.show_today_timeline_inline_check.setChecked(preferences.show_today_timeline_inline)
        self.show_today_timeline_waiting_check.setChecked(preferences.show_today_timeline_waiting_panel)
        self.show_today_timeline_waiting_pinned_check.setChecked(preferences.show_today_timeline_waiting_pinned)
        self.show_today_checklist_inline_check.setChecked(preferences.show_today_checklist_inline)
        self.show_quick_memo_panel_check.setChecked(preferences.show_quick_memo_panel)
        self.show_link_favorites_panel_check.setChecked(preferences.show_link_favorites_panel)
        self.show_media_panel_check.setChecked(preferences.show_media_panel)
        self.show_compact_favorites_panel_check.setChecked(preferences.show_compact_favorites_panel)
        self._source = preferences

    def preferences(self) -> Preference:
        return Preference(
            day_max_minutes=self._source.day_max_minutes,
            break_minutes=self._source.break_minutes,
            strategy=self._source.strategy,
            week_start_day=int(self.week_start_combo.currentData()),
            app_title=self.app_title_edit.text().strip() or "Focus Desk",
            main_always_on_top=self.main_always_on_top_check.isChecked(),
            time_format=str(self.time_format_combo.currentData()),
            show_datetime_panel=self.show_datetime_panel_check.isChecked(),
            show_current_date=self.show_current_date_check.isChecked(),
            show_current_time=self.show_current_time_check.isChecked(),
            show_current_seconds=self.show_current_seconds_check.isChecked(),
            show_focus_panel=self.show_focus_panel_check.isChecked(),
            show_pomodoro_controls=self.show_pomodoro_check.isChecked(),
            show_today_timeline_inline=self.show_today_timeline_inline_check.isChecked(),
            show_today_timeline_waiting_panel=self.show_today_timeline_waiting_check.isChecked(),
            show_today_timeline_waiting_pinned=self.show_today_timeline_waiting_pinned_check.isChecked(),
            show_today_checklist_inline=self.show_today_checklist_inline_check.isChecked(),
            show_today_flow_panel=False,
            show_quick_memo_panel=self.show_quick_memo_panel_check.isChecked(),
            show_link_favorites_panel=self.show_link_favorites_panel_check.isChecked(),
            show_media_panel=self.show_media_panel_check.isChecked(),
            media_panel_file_path=self._source.media_panel_file_path,
            show_compact_favorites_panel=self.show_compact_favorites_panel_check.isChecked(),
            favorite_display_mode=self._source.favorite_display_mode,
            appearance_theme=str(self.theme_combo.currentData()),
            accent_color=self.accent_color,
            button_color=self.button_color,
            background_color=self.background_color,
            inner_background_color=self.inner_background_color,
            panel_color=self.panel_color,
            table_color=self.table_color,
            text_color=self.text_color,
            show_header_banner=self.show_header_banner_check.isChecked(),
            header_banner_image_path=self.header_banner_path_edit.text().strip(),
            header_banner_height=self.header_banner_height_spin.value(),
            header_banner_position=str(self.header_banner_position_combo.currentData()),
            header_banner_span=self._source.header_banner_span,
            focus_rate_display=str(self.focus_rate_display_combo.currentData()),
            last_window_width=self._source.last_window_width,
            last_window_height=self._source.last_window_height,
            last_layout_state=self._source.last_layout_state,
            id=self._source.id,
        )


def _schedule_items_for_date(
    repository: ScheduleRepository,
    selected_date: date,
    start_at: datetime,
    end_at: datetime,
    preferences: Preference | None = None,
) -> list[tuple[datetime, str, dict[str, object]]]:
    items: list[tuple[datetime, str, dict[str, object]]] = []

    for event in repository.list_events(start_at, end_at, include_completed=True):
        status = " · 완료" if event.completed else ""
        kind = _item_type_label(repository, "event", event.item_type_id)
        items.append(
            (
                event.start_at,
                f"{_format_time_range(event.start_at, event.end_at, preferences)}  [{kind}] {event.title}{status}",
                {"type": "event", "id": event.id, "kind": kind, "title": event.title},
            )
        )

    for task in repository.list_tasks(include_completed=True):
        if not _task_belongs_to_date(task, selected_date):
            continue
        reference_at = task.due_at or task.created_at
        time_label = _format_time(task.due_at, preferences) if task.due_at and task.due_at.date() == selected_date else "시간 없음"
        status = "완료" if task.completed else "진행 중"
        kind = _item_type_label(repository, "task", task.item_type_id)
        items.append(
            (
                reference_at,
                f"{time_label}  [{kind}] {task.title}{_task_duration_suffix(task)} · {status}",
                {"type": "task", "id": task.id, "kind": kind, "title": task.title},
            )
        )

    return sorted(items, key=lambda item: item[0])


def _record_items_for_date(
    repository: ScheduleRepository,
    selected_date: date,
    start_at: datetime,
    end_at: datetime,
    preferences: Preference | None = None,
) -> list[tuple[datetime, str, dict[str, object]]]:
    items: list[tuple[datetime, str, dict[str, object]]] = []

    for session in repository.list_focus_sessions(start_at, end_at):
        reference_at = session.started_at or session.ended_at or start_at
        items.append(
            (
                reference_at,
                f"{_focus_session_time_label(session, preferences=preferences)}  [집중] {session.title} · "
                f"집중 {_format_duration(session.focused_seconds)} · {_status_label(session.status)}",
                {"type": "focus_session", "id": session.id, "kind": "집중 기록", "title": session.title},
            )
        )

    for task in repository.list_completed_tasks():
        if task.completed_at is None or task.completed_at.date() != selected_date:
            continue
        kind = _item_type_label(repository, "task", task.item_type_id)
        items.append(
            (
                task.completed_at,
                f"{_format_time(task.completed_at, preferences)}  [완료] {kind} · {task.title}",
                {"type": "task", "id": task.id, "kind": kind, "title": task.title},
            )
        )

    for event in repository.list_completed_events():
        if event.completed_at is None or event.completed_at.date() != selected_date:
            continue
        kind = _item_type_label(repository, "event", event.item_type_id)
        items.append(
            (
                event.completed_at,
                f"{_format_time(event.completed_at, preferences)}  [완료] {kind} · {event.title}",
                {"type": "event", "id": event.id, "kind": kind, "title": event.title},
            )
        )

    return sorted(items, key=lambda item: item[0], reverse=True)


def _today_timeline_items(
    repository: ScheduleRepository,
    selected_date: date,
    preferences: Preference | None = None,
) -> list[tuple[datetime | None, str, str, dict[str, object]]]:
    start_at, end_at = _day_window(selected_date)
    items: list[tuple[datetime | None, str, str, dict[str, object]]] = []
    listed_task_ids: set[int] = set()
    listed_event_ids: set[int] = set()

    for event in repository.list_events(start_at, end_at, include_completed=True):
        if event.id is not None:
            listed_event_ids.add(event.id)
        status = _completion_suffix(event.completed, event.completed_at, selected_date, preferences)
        kind = _item_type_label(repository, "event", event.item_type_id)
        items.append(
            (
                event.start_at,
                f"{_format_time_range(event.start_at, event.end_at, preferences)}  {kind}  {event.title}{status}",
                "completed" if event.completed else "schedule",
                {"type": "event", "id": event.id, "title": event.title, "completed": event.completed},
            )
        )

    for task in repository.list_tasks(include_completed=True):
        if task.due_at is None and not task.completed:
            continue
        due_today = task.due_at is not None and task.due_at.date() == selected_date
        completed_today = task.completed_at is not None and task.completed_at.date() == selected_date
        created_today = task.created_at.date() == selected_date
        if not due_today and not completed_today and not created_today:
            continue

        if task.id is not None:
            listed_task_ids.add(task.id)
        reference_at = task.due_at if due_today else task.completed_at if completed_today else None
        time_label = _format_time(task.due_at, preferences) if due_today and task.due_at else "시간 없음"
        if not due_today and completed_today and task.completed_at:
            time_label = f"완료 {_format_time(task.completed_at, preferences)}"
        status = _task_status_label(task, selected_date, preferences)
        kind = _item_type_label(repository, "task", task.item_type_id)
        items.append(
            (
                reference_at,
                f"{time_label}  {kind}  {task.title}{_task_duration_suffix(task)} · {status}",
                "completed" if task.completed else "task",
                {"type": "task", "id": task.id, "title": task.title, "completed": task.completed},
            )
        )

    for task in repository.list_completed_tasks():
        if task.id in listed_task_ids:
            continue
        if task.completed_at is None or task.completed_at.date() != selected_date:
            continue
        items.append(
            (
                task.completed_at,
                f"완료 {_format_time(task.completed_at, preferences)}  {_item_type_label(repository, 'task', task.item_type_id)}  {task.title}{_task_duration_suffix(task)}",
                "completed",
                {"type": "task", "id": task.id, "title": task.title, "completed": True},
            )
        )

    for event in repository.list_completed_events():
        if event.id in listed_event_ids:
            continue
        if event.completed_at is None or event.completed_at.date() != selected_date:
            continue
        items.append(
            (
                event.completed_at,
                f"완료 {_format_time(event.completed_at, preferences)}  {_item_type_label(repository, 'event', event.item_type_id)}  {event.title}",
                "completed",
                {"type": "event", "id": event.id, "title": event.title, "completed": True},
            )
        )

    for session in repository.list_focus_sessions(start_at, end_at):
        reference_at = session.started_at or session.ended_at
        items.append(
            (
                reference_at,
                f"{_focus_session_time_label(session, preferences=preferences)}  집중  {session.title} · "
                f"집중 {_format_duration(session.focused_seconds)} · {_status_label(session.status)}",
                "focus",
                {"type": "focus_session", "id": session.id, "title": session.title},
            )
        )

    return sorted(items, key=_timeline_sort_key)


def _today_timeline_blocks(
    repository: ScheduleRepository,
    selected_date: date,
) -> list[tuple[datetime, datetime, str, str]]:
    start_at, end_at = _day_window(selected_date)
    blocks: list[tuple[datetime, datetime, str, str]] = []
    listed_event_ids: set[int] = set()

    for event in repository.list_events(start_at, end_at, include_completed=True):
        if event.id is not None:
            listed_event_ids.add(event.id)
        category = "completed" if event.completed else "schedule"
        _append_timeline_block(
            blocks,
            start_at,
            end_at,
            event.start_at,
            event.end_at,
            category,
            f"{_item_type_label(repository, 'event', event.item_type_id)} {event.title}",
        )

    for task in repository.list_tasks(include_completed=True):
        if task.duration_minutes <= 0:
            continue
        task_start: datetime | None = None
        task_end: datetime | None = None
        if task.due_at is not None and task.due_at.date() == selected_date:
            task_start = task.due_at
            task_end = task.due_at + timedelta(minutes=task.duration_minutes)
        elif task.completed_at is not None and task.completed_at.date() == selected_date:
            task_end = task.completed_at
            task_start = task.completed_at - timedelta(minutes=task.duration_minutes)

        if task_start is None or task_end is None:
            continue
        _append_timeline_block(
            blocks,
            start_at,
            end_at,
            task_start,
            task_end,
            "completed" if task.completed else "task",
            f"{_item_type_label(repository, 'task', task.item_type_id)} {task.title}",
        )

    for event in repository.list_completed_events():
        if event.id in listed_event_ids:
            continue
        if event.completed_at is None or event.completed_at.date() != selected_date:
            continue
        _append_timeline_block(
            blocks,
            start_at,
            end_at,
            event.completed_at,
            event.completed_at + timedelta(minutes=10),
            "completed",
            f"완료 {_item_type_label(repository, 'event', event.item_type_id)} {event.title}",
        )

    for session in repository.list_focus_sessions(start_at, end_at):
        session_start = session.started_at or session.ended_at
        session_end = session.ended_at or datetime.now()
        if session_start is None:
            continue
        _append_timeline_block(
            blocks,
            start_at,
            end_at,
            session_start,
            session_end,
            "focus",
            f"집중 {session.title}",
        )

    return blocks


def _append_timeline_block(
    blocks: list[tuple[datetime, datetime, str, str]],
    day_start: datetime,
    day_end: datetime,
    started_at: datetime,
    ended_at: datetime,
    category: str,
    label: str,
) -> None:
    clipped_start = max(day_start, started_at)
    clipped_end = min(day_end, ended_at)
    if clipped_end <= clipped_start:
        clipped_end = min(day_end, clipped_start + timedelta(minutes=10))
    if clipped_end <= clipped_start:
        return
    blocks.append((clipped_start, clipped_end, category, label))


def _fill_time_block_table(
    table: QTableWidget,
    selected_date: date,
    blocks: list[tuple[datetime, datetime, str, str]],
    preferences: Preference | None = None,
) -> None:
    theme = preferences.appearance_theme if preferences is not None else "light"
    palette = _resolved_theme_palette(preferences) if preferences is not None else _theme_palette(theme)
    hour_background = QColor(palette.get("table_header", palette["surface_2"]))
    slot_background = QColor(palette.get("table", palette["surface"]))
    overlap_background = QColor("#355546" if _normalize_theme(theme) == "dark" else "#5d6f78")
    day_start = datetime.combine(selected_date, time.min)
    table.clearContents()
    for row in range(24):
        hour_item = QTableWidgetItem(_format_time(time(row, 0), preferences))
        hour_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        hour_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        hour_item.setBackground(hour_background)
        table.setItem(row, 0, hour_item)
        for column in range(1, 7):
            item = QTableWidgetItem("")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip(_format_time(time(row, (column - 1) * 10), preferences))
            item.setBackground(slot_background)
            table.setItem(row, column, item)

    first_filled_item: QTableWidgetItem | None = None
    for started_at, ended_at, category, label in blocks:
        start_seconds = int((started_at - day_start).total_seconds())
        end_seconds = int((ended_at - day_start).total_seconds())
        start_slot = max(0, start_seconds // 600)
        end_slot = min(144, max(start_slot + 1, (end_seconds + 599) // 600))
        for slot in range(start_slot, end_slot):
            row = slot // 6
            column = slot % 6 + 1
            item = table.item(row, column)
            if item is None:
                continue
            tooltip = item.toolTip()
            item.setToolTip(tooltip + f"\n{_format_time_range(started_at, ended_at, preferences)} {label}")
            current_color = item.background().color().name().lower()
            item.setBackground(overlap_background if current_color != slot_background.name().lower() else QColor(_timeline_block_color(category)))
            if first_filled_item is None:
                first_filled_item = item

    table.clearSelection()
    table.setCurrentCell(-1, -1)
    if first_filled_item is not None:
        table.scrollToItem(first_filled_item, QAbstractItemView.ScrollHint.PositionAtTop)


def _timeline_block_color(category: str) -> str:
    return {
        "schedule": "#8fb9dd",
        "task": "#f1d16b",
        "completed": "#a8cf9d",
        "focus": "#b9a7e8",
    }.get(category, "#d7dfdc")


def _fill_timeline_list(
    list_widget: QListWidget,
    items: list[tuple[datetime | None, str, str, dict[str, object]]],
    preferences: Preference | None = None,
) -> None:
    list_widget.clear()
    if not items:
        empty = QListWidgetItem("오늘 표시할 항목이나 완료 기록이 없습니다.")
        empty.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(empty)
        return

    current_group = ""
    for reference_at, text, _category, payload in items:
        group = _timeline_group_label(reference_at, preferences)
        if group != current_group:
            header = QListWidgetItem(group)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header)
            current_group = group
        item = QListWidgetItem(text)
        if payload.get("id") is not None:
            item.setData(Qt.ItemDataRole.UserRole, payload)
        list_widget.addItem(item)
    list_widget.clearSelection()
    list_widget.setCurrentRow(-1)


def _timeline_sort_key(item: tuple[datetime | None, str, str, dict[str, object]]) -> tuple[int, datetime, str]:
    reference_at, text, _category, _payload = item
    return (1 if reference_at is None else 0, reference_at or datetime.max, text.casefold())


def _timeline_filter_matches(category: str, filter_key: str) -> bool:
    if filter_key == "all":
        return True
    if filter_key == "schedule_task":
        return category in {"schedule", "task"}
    if filter_key == "completed":
        return category == "completed"
    if filter_key == "focus":
        return category == "focus"
    return True


def _timeline_group_label(reference_at: datetime | None, preferences: Preference | None = None) -> str:
    if reference_at is None:
        return "시간 없음"
    return _format_time(time(reference_at.hour, 0), preferences)


def _completion_suffix(
    completed: bool,
    completed_at: datetime | None,
    selected_date: date,
    preferences: Preference | None = None,
) -> str:
    if not completed:
        return " · 예정"
    if completed_at is not None and completed_at.date() == selected_date:
        return f" · 완료 {_format_time(completed_at, preferences)}"
    return " · 완료"


def _task_status_label(task: Task, selected_date: date, preferences: Preference | None = None) -> str:
    if not task.completed:
        return "진행 중"
    if task.completed_at is not None and task.completed_at.date() == selected_date:
        return f"완료 {_format_time(task.completed_at, preferences)}"
    return "완료"


def _quick_note_items_for_date(
    repository: ScheduleRepository,
    start_at: datetime,
    end_at: datetime,
    preferences: Preference | None = None,
) -> list[tuple[datetime, str, dict[str, object]]]:
    items: list[tuple[datetime, str, dict[str, object]]] = []
    for note in repository.list_quick_notes(start_at, end_at):
        body = _shorten(" ".join(note.body.split()), 96)
        attachments = repository.list_quick_note_attachments(note.id) if note.id is not None else []
        attachment_label = f" · 첨부 {len(attachments)}개" if attachments else ""
        items.append(
            (
                note.created_at,
                f"{_format_time(note.created_at, preferences)}  {body}{attachment_label}",
                {"type": "quick_note", "id": note.id, "kind": "메모", "title": body},
            )
        )
    return sorted(items, key=lambda item: item[0], reverse=True)


def _fill_list(
    list_widget: QListWidget,
    rows: list[tuple[datetime, str, dict[str, object]]],
    empty_message: str,
) -> None:
    list_widget.clear()
    if not rows:
        item = QListWidgetItem(empty_message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)
        return
    for _, text, data in rows:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, data)
        list_widget.addItem(item)


def _today_window() -> tuple[datetime, datetime]:
    return _day_window(date.today())


def _day_window(day: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(day, time.min)
    return start_at, start_at + timedelta(days=1)


def _date_from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def _qt_week_start_day(week_start_day: int) -> Qt.DayOfWeek:
    return Qt.DayOfWeek.Sunday if week_start_day == 6 else Qt.DayOfWeek.Monday


def _polish_calendar_widget(calendar: QCalendarWidget, preferences: Preference) -> None:
    calendar.setGridVisible(False)
    calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
    calendar.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
    calendar.setFirstDayOfWeek(_qt_week_start_day(preferences.week_start_day))
    calendar.setMinimumHeight(260)
    calendar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


def _qt_day_value(day: Qt.DayOfWeek) -> int:
    return int(day.value) if hasattr(day, "value") else int(day)


def _preferences_from_widget(widget: QWidget | None) -> Preference:
    current = widget
    while current is not None:
        preferences = getattr(current, "preferences", None)
        if isinstance(preferences, Preference):
            return preferences
        current = current.parentWidget()
    return Preference()


def _normalize_theme(value: object) -> str:
    theme = str(value or "").strip().lower()
    return theme if theme in {"light", "dark"} else "light"


def _normalize_focus_rate_display(value: object) -> str:
    display = str(value or "").strip().lower()
    return display if display in {"ring", "bar"} else "ring"


def _normalize_header_banner_position(value: object) -> str:
    position = str(value or "").strip().lower()
    if position in {"left", "center", "right"}:
        return position
    if position in {"top", "bottom"}:
        return "center"
    return "center"


def _normalize_header_banner_height(value: object) -> int:
    try:
        height = int(value)
    except (TypeError, ValueError):
        return 132
    return min(360, max(72, height))


def _normalize_header_banner_span(value: object) -> int:
    try:
        span = int(value)
    except (TypeError, ValueError):
        return 1
    return min(3, max(1, span))


def _theme_palette(value: object) -> dict[str, str]:
    if _normalize_theme(value) == "dark":
        return {
            "bg": "#090c0a",
            "app": "#101511",
            "surface": "#151c17",
            "surface_2": "#1c251f",
            "text": "#eef4ef",
            "muted": "#a6b3aa",
            "secondary": "#69766d",
            "border": "#26332a",
            "border_2": "#1c271f",
            "track": "#26332b",
            "disabled": "#59645d",
        }
    return {
        "bg": "#eaedeb",
        "app": "#fbfcfb",
        "surface": "#ffffff",
        "surface_2": "#f3f6f4",
        "text": "#18201b",
        "muted": "#53625a",
        "secondary": "#8a9890",
        "border": "#dbe5df",
        "border_2": "#e5ede8",
        "track": "#dde6e0",
        "disabled": "#b8c3bc",
    }


def _resolved_theme_palette(preferences: Preference | None) -> dict[str, str]:
    theme = _normalize_theme(preferences.appearance_theme if preferences is not None else "light")
    is_dark_theme = theme == "dark"
    palette = _theme_palette(theme)
    if preferences is None:
        return {
            **palette,
            "table": palette["surface"],
            "table_header": palette["surface_2"],
            "table_grid": palette["border_2"],
        }

    background_color = _normalize_optional_color(getattr(preferences, "background_color", ""))
    if background_color:
        is_dark = _is_dark_color(background_color)
        lift_target = "#ffffff"
        border_target = "#ffffff" if is_dark else "#000000"
        app_lift = 0.035 if is_dark else 0.70
        surface_lift = 0.065 if is_dark else 0.86
        soft_lift = 0.10 if is_dark else 0.58
        border_mix = 0.16 if is_dark else 0.12
        palette = {**palette, "bg": background_color}
        palette = {
            **palette,
            "app": _mix_hex_color(background_color, lift_target, app_lift),
            "surface": _mix_hex_color(background_color, lift_target, surface_lift),
            "surface_2": _mix_hex_color(background_color, lift_target, soft_lift),
            "border": _mix_hex_color(background_color, border_target, border_mix),
            "border_2": _mix_hex_color(background_color, border_target, border_mix * 0.65),
            "track": _mix_hex_color(background_color, border_target, border_mix * 0.80),
        }

    inner_background_color = _normalize_optional_color(getattr(preferences, "inner_background_color", ""))
    if inner_background_color:
        is_dark = _is_dark_color(inner_background_color)
        lift_target = "#ffffff"
        border_target = "#ffffff" if is_dark else "#000000"
        soft_lift = 0.10 if is_dark else 0.58
        border_mix = 0.16 if is_dark else 0.12
        palette = {
            **palette,
            "app": inner_background_color,
            "surface_2": _mix_hex_color(inner_background_color, lift_target, soft_lift),
            "border": _mix_hex_color(inner_background_color, border_target, border_mix),
            "border_2": _mix_hex_color(inner_background_color, border_target, border_mix * 0.65),
            "track": _mix_hex_color(inner_background_color, border_target, border_mix * 0.80),
        }

    panel_color = _normalize_optional_color(getattr(preferences, "panel_color", ""))
    if panel_color:
        is_dark = _is_dark_color(panel_color)
        lift_target = "#ffffff"
        border_target = "#ffffff" if is_dark else "#000000"
        soft_lift = 0.10 if is_dark else 0.58
        border_mix = 0.16 if is_dark else 0.12
        palette = {
            **palette,
            "surface": panel_color,
            "surface_2": _mix_hex_color(panel_color, lift_target, soft_lift),
            "border": _mix_hex_color(panel_color, border_target, border_mix),
            "border_2": _mix_hex_color(panel_color, border_target, border_mix * 0.65),
            "track": _mix_hex_color(panel_color, border_target, border_mix * 0.80),
        }
    elif inner_background_color:
        palette = {**palette, "surface": inner_background_color}

    table_color = _normalize_optional_color(getattr(preferences, "table_color", ""))
    if table_color:
        is_dark = _is_dark_color(table_color)
        lift_target = "#ffffff"
        border_target = "#ffffff" if is_dark else "#000000"
        header_lift = 0.10 if is_dark else 0.58
        grid_mix = 0.16 if is_dark else 0.12
        palette = {
            **palette,
            "table": table_color,
            "table_header": _mix_hex_color(table_color, lift_target, header_lift),
            "table_grid": _mix_hex_color(table_color, border_target, grid_mix),
        }
    else:
        palette = {
            **palette,
            "table": palette["surface"],
            "table_header": palette["surface_2"],
            "table_grid": palette["border_2"],
        }

    text_color = _normalize_optional_color(getattr(preferences, "text_color", ""))
    if text_color:
        palette = {**palette, **_text_role_palette(text_color, palette["surface"], is_dark_theme)}
    elif background_color or inner_background_color or panel_color:
        text_color = "#eef4ef" if is_dark_theme else "#18201b"
        palette = {**palette, **_text_role_palette(text_color, palette["surface"], is_dark_theme)}
    return palette


def _text_role_palette(text_color: str, surface: str, is_dark_theme: bool) -> dict[str, str]:
    if is_dark_theme:
        return {
            "text": text_color,
            "muted": _mix_hex_color(text_color, surface, 0.34),
            "secondary": _mix_hex_color(text_color, surface, 0.55),
            "disabled": _mix_hex_color(text_color, surface, 0.70),
        }

    text = _limit_light_theme_text(text_color, "#18201b", 138)
    return {
        "text": text,
        "muted": _limit_light_theme_text(_mix_hex_color(text, surface, 0.30), "#53625a", 150),
        "secondary": _limit_light_theme_text(_mix_hex_color(text, surface, 0.44), "#64736a", 164),
        "disabled": _limit_light_theme_text(_mix_hex_color(text, surface, 0.58), "#7f8a83", 178),
    }


def _limit_light_theme_text(color: str, fallback: str, max_luminance: float) -> str:
    return fallback if _color_luminance(color) > max_luminance else color


def _button_theme_palette(accent: str, palette: dict[str, str], is_dark_theme: bool = False) -> dict[str, str]:
    surface = palette.get("surface", "#ffffff")
    if is_dark_theme:
        background = _mix_hex_color(accent, surface, 0.42)
        hover_background = _mix_hex_color(accent, surface, 0.26)
        border = _mix_hex_color(accent, "#ffffff", 0.16)
        text = _contrast_text_for_background(background, palette.get("text", "#eef4ef"))
        hover_text = _contrast_text_for_background(hover_background, palette.get("text", "#eef4ef"))
    else:
        light_surface = surface if not _is_dark_color(surface) else "#ffffff"
        background = _mix_hex_color(accent, light_surface, 0.58)
        hover_background = _mix_hex_color(accent, light_surface, 0.44)
        if _is_dark_color(background):
            background = _mix_hex_color(background, "#ffffff", 0.52)
        if _is_dark_color(hover_background):
            hover_background = _mix_hex_color(hover_background, "#ffffff", 0.44)
        border = _mix_hex_color(accent, light_surface, 0.35)
        text = "#18201b"
        hover_text = "#18201b"
    return {
        "bg": background,
        "hover_bg": hover_background,
        "border": border,
        "text": text,
        "hover_text": hover_text,
    }


def _action_button_theme_palette(accent: str, accent_hover: str, is_dark_theme: bool = False) -> dict[str, str]:
    if is_dark_theme:
        return {
            "bg": accent,
            "hover_bg": accent_hover,
            "border": accent,
            "text": "#ffffff",
        }
    background = _mix_hex_color(accent, "#ffffff", 0.22)
    hover_background = _mix_hex_color(accent, "#ffffff", 0.12)
    if _is_dark_color(background):
        background = _mix_hex_color(background, "#ffffff", 0.48)
    if _is_dark_color(hover_background):
        hover_background = _mix_hex_color(hover_background, "#ffffff", 0.40)
    return {
        "bg": background,
        "hover_bg": hover_background,
        "border": _mix_hex_color(accent, "#ffffff", 0.10),
        "text": "#18201b",
    }


def _contrast_text_for_background(background: str, preferred_text: str) -> str:
    if _is_dark_color(background):
        return "#ffffff"
    if _is_dark_color(preferred_text):
        return preferred_text
    return "#111315"


def _apply_qt_palette(accent: str, palette: dict[str, str]) -> None:
    application = QApplication.instance()
    if application is None:
        return
    qt_palette = QPalette()
    qt_palette.setColor(QPalette.ColorRole.Window, QColor(palette["app"]))
    qt_palette.setColor(QPalette.ColorRole.WindowText, QColor(palette["text"]))
    qt_palette.setColor(QPalette.ColorRole.Base, QColor(palette["surface"]))
    qt_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(palette["surface_2"]))
    qt_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette["surface"]))
    qt_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(palette["text"]))
    qt_palette.setColor(QPalette.ColorRole.Text, QColor(palette["text"]))
    qt_palette.setColor(QPalette.ColorRole.Button, QColor(palette["surface"]))
    qt_palette.setColor(QPalette.ColorRole.ButtonText, QColor(palette["text"]))
    qt_palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    qt_palette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
    qt_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    qt_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(palette["secondary"]))
    disabled_group = QPalette.ColorGroup.Disabled
    qt_palette.setColor(disabled_group, QPalette.ColorRole.WindowText, QColor(palette["disabled"]))
    qt_palette.setColor(disabled_group, QPalette.ColorRole.Text, QColor(palette["disabled"]))
    qt_palette.setColor(disabled_group, QPalette.ColorRole.ButtonText, QColor(palette["disabled"]))
    qt_palette.setColor(disabled_group, QPalette.ColorRole.Base, QColor(palette["surface_2"]))
    qt_palette.setColor(disabled_group, QPalette.ColorRole.Button, QColor(palette["track"]))
    application.setPalette(qt_palette)


def _replace_style_tokens(style: str, replacements: tuple[tuple[str, str], ...]) -> str:
    placeholders: list[tuple[str, str]] = []
    for index, (token, value) in enumerate(replacements):
        placeholder = f"__SCHEDULE_HELPER_STYLE_TOKEN_{index}__"
        style = style.replace(token, placeholder)
        placeholders.append((placeholder, value))
    for placeholder, value in placeholders:
        style = style.replace(placeholder, value)
    return style


def _hex_to_rgb(value: object) -> tuple[int, int, int]:
    color = _normalize_optional_color(value) or "#000000"
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _mix_hex_color(start: object, end: object, ratio: float) -> str:
    ratio = min(1.0, max(0.0, ratio))
    start_rgb = _hex_to_rgb(start)
    end_rgb = _hex_to_rgb(end)
    mixed = tuple(round(start_channel + (end_channel - start_channel) * ratio) for start_channel, end_channel in zip(start_rgb, end_rgb))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _is_dark_color(value: object) -> bool:
    return _color_luminance(value) < 128


def _color_luminance(value: object) -> float:
    red, green, blue = _hex_to_rgb(value)
    return red * 0.299 + green * 0.587 + blue * 0.114


def _normalize_accent_color(value: object) -> str:
    color = str(value or "").strip()
    if len(color) == 7 and color.startswith("#") and all(
        character in "0123456789abcdefABCDEF" for character in color[1:]
    ):
        return color.lower()
    return "#4f8c6b"


def _normalize_optional_color(value: object) -> str:
    color = str(value or "").strip()
    if len(color) == 7 and color.startswith("#") and all(
        character in "0123456789abcdefABCDEF" for character in color[1:]
    ):
        return color.lower()
    return ""


def _accent_rgb(value: object) -> tuple[int, int, int]:
    color = _normalize_accent_color(value)
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _accent_hover_color(value: object) -> str:
    red, green, blue = _accent_rgb(value)
    mixed = tuple(round(channel + (255 - channel) * 0.16) for channel in (red, green, blue))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _accent_rgba(value: object, opacity: float) -> str:
    red, green, blue = _accent_rgb(value)
    alpha = min(1.0, max(0.0, opacity))
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


def _color_rgba(value: object, opacity: float) -> str:
    red, green, blue = _hex_to_rgb(value)
    alpha = min(1.0, max(0.0, opacity))
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


def _uses_12_hour_clock(preferences: Preference | None) -> bool:
    return preferences is not None and preferences.time_format == "12h"


def _time_edit_display_format(preferences: Preference | None) -> str:
    return "AP h:mm" if _uses_12_hour_clock(preferences) else "HH:mm"


def _format_time(value: datetime | time, preferences: Preference | None = None) -> str:
    hour = value.hour
    minute = value.minute
    if not _uses_12_hour_clock(preferences):
        return f"{hour:02d}:{minute:02d}"
    meridiem = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    return f"{meridiem} {hour_12}:{minute:02d}"


def _format_clock_time(
    value: datetime | time,
    preferences: Preference | None = None,
    show_seconds: bool = False,
) -> str:
    hour = value.hour
    minute = value.minute
    second = value.second
    if not _uses_12_hour_clock(preferences):
        suffix = f":{second:02d}" if show_seconds else ""
        return f"{hour:02d}:{minute:02d}{suffix}"
    meridiem = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    suffix = f":{second:02d}" if show_seconds else ""
    return f"{meridiem} {hour_12}:{minute:02d}{suffix}"


def _format_datetime(
    value: datetime,
    preferences: Preference | None = None,
    date_format: str = "%m/%d",
) -> str:
    return f"{value.strftime(date_format)} {_format_time(value, preferences)}"


def _format_time_range(
    started_at: datetime,
    ended_at: datetime,
    preferences: Preference | None = None,
    include_start_date: bool = False,
    include_end_date: bool = False,
) -> str:
    start_label = _format_datetime(started_at, preferences) if include_start_date else _format_time(started_at, preferences)
    end_label = _format_datetime(ended_at, preferences) if include_end_date else _format_time(ended_at, preferences)
    return f"{start_label}-{end_label}"


def _populate_item_type_combo(
    combo: QComboBox,
    repository: ScheduleRepository,
    base_kind: str,
    selected_item_type_id: int | None = None,
) -> None:
    combo.clear()
    item_types = repository.list_item_types(base_kind)
    default_type = repository.default_item_type(base_kind)
    for item_type in item_types:
        combo.addItem(item_type.name, item_type.id)
    target_id = selected_item_type_id or default_type.id
    index = combo.findData(target_id)
    if index >= 0:
        combo.setCurrentIndex(index)


def _selected_item_type_id(combo: QComboBox) -> int | None:
    item_type_id = combo.currentData()
    return int(item_type_id) if item_type_id is not None else None


def _item_type_label(
    repository: ScheduleRepository,
    base_kind: str,
    item_type_id: int | None,
    fallback: str | None = None,
) -> str:
    item_type = repository.get_item_type(item_type_id)
    if item_type is None:
        try:
            item_type = repository.default_item_type(base_kind)
        except ValueError:
            return fallback or ("일정" if base_kind == "event" else "할 일")
    return item_type.name


def _task_duration_suffix(task: Task) -> str:
    return f" · {task.duration_minutes}분" if task.duration_minutes > 0 else ""


def _task_belongs_to_date(task: Task, selected_date: date) -> bool:
    if task.due_at is not None:
        return task.due_at.date() == selected_date
    if task.completed_at is not None:
        return task.completed_at.date() == selected_date
    return task.created_at.date() == selected_date


def _target_label(process_name: str, window_title: str) -> str:
    title = _shorten(window_title, 48)
    return f"{_display_name_from_process(process_name)} ({process_name})" + (f" · {title}" if title else "")


def _focus_target_summary(target_process_name: str, target_window_title: str) -> str:
    targets = decode_focus_targets(target_process_name, target_window_title)
    if not targets:
        return "지정 없음"
    if len(targets) == 1:
        target = targets[0]
        return _target_label(target["process_name"], target["window_title"])
    return f"{len(targets)}개 지정"


def _focus_session_time_label(
    session: FocusSession,
    include_date: bool = False,
    preferences: Preference | None = None,
) -> str:
    started = _format_session_time(session.started_at, include_date=include_date, preferences=preferences)
    ended = _format_session_time(
        session.ended_at,
        include_date=include_date and _needs_end_date(session.started_at, session.ended_at),
        fallback="진행 중",
        preferences=preferences,
    )
    return f"시작 {started} · 완료 {ended}"


def _format_session_time(
    value: datetime | None,
    include_date: bool = False,
    fallback: str = "-",
    preferences: Preference | None = None,
) -> str:
    if value is None:
        return fallback
    return _format_datetime(value, preferences) if include_date else _format_time(value, preferences)


def _needs_end_date(started_at: datetime | None, ended_at: datetime | None) -> bool:
    if started_at is None or ended_at is None:
        return False
    return started_at.date() != ended_at.date()


def _display_name_from_process(process_name: str) -> str:
    base = process_name.strip().rsplit(".", 1)[0]
    if not base:
        return process_name
    return base.replace("_", " ").replace("-", " ").title()


def _shorten(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _is_image_file(path: Path) -> bool:
    return path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _open_local_path(path: str, parent: QWidget | None = None) -> None:
    try:
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            webbrowser.open(path)
        else:
            startfile(path)
    except OSError as exc:
        QMessageBox.warning(parent, "파일 열기", f"파일을 열 수 없습니다.\n{exc}")


def _is_probable_url(target: str) -> bool:
    value = target.strip()
    lower = value.casefold()
    if lower.startswith(("http://", "https://", "mailto:")) or "://" in lower:
        return True
    if "\\" in value or "/" in value or ":" in value or " " in value:
        return False
    return "." in value


def _normalized_favorite_display_mode(value: str) -> str:
    return value if value in {"text", "icon_with_label", "icon_only"} else "text"


def _favorite_icon_text(favorite: LinkFavorite) -> str:
    icon_text = favorite.icon_text.strip()
    if icon_text:
        return icon_text
    title = favorite.title.strip()
    return title[:1].upper() if title else "★"


def _favorite_secondary_label(favorite: LinkFavorite) -> str:
    target = favorite.target.strip()
    if not target:
        return ""
    parsed = urlparse(_normalized_url(target) if _is_probable_url(target) else target)
    if parsed.netloc:
        return parsed.netloc.removeprefix("www.")
    path = Path(target)
    if path.name:
        return _shorten(path.name, 32)
    return _shorten(target, 32)


def _favorite_qicon(favorite: LinkFavorite) -> QIcon | None:
    icon_path = favorite.icon_path.strip()
    if not icon_path:
        return None
    path = Path(icon_path)
    if not path.exists():
        return None
    return QIcon(str(path))


class _SiteIconParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.icon_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "link":
            return
        values = {name.casefold(): (value or "") for name, value in attrs}
        rel_values = {part.casefold() for part in values.get("rel", "").replace(",", " ").split()}
        href = values.get("href", "").strip()
        if href and "icon" in rel_values:
            self.icon_hrefs.append(href)


def _download_site_icon(target: str) -> tuple[str, bytes]:
    site_url = _favorite_target_site_url(target)
    if site_url is None:
        raise ValueError("URL 즐겨찾기에서만 사이트 아이콘을 가져올 수 있습니다.")

    candidates = _site_icon_candidates(site_url)
    errors: list[Exception] = []
    for icon_url in candidates:
        try:
            data, content_type = _download_binary(icon_url, limit=5 * 1024 * 1024)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(exc)
            continue
        if not data:
            continue
        return _icon_file_name_from_url(icon_url, content_type), data
    if errors:
        raise errors[-1]
    raise ValueError("사이트에서 사용할 수 있는 아이콘을 찾지 못했습니다.")


def _site_icon_candidates(site_url: str) -> list[str]:
    parsed = urlparse(site_url)
    root_url = f"{parsed.scheme}://{parsed.netloc}/"
    candidates: list[str] = []
    try:
        html_data, content_type = _download_binary(site_url, limit=1024 * 1024)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        html_data = b""
        content_type = ""
    if html_data and ("html" in content_type.casefold() or site_url.rstrip("/").endswith(parsed.netloc)):
        parser = _SiteIconParser()
        parser.feed(html_data.decode(_charset_from_content_type(content_type), errors="ignore"))
        candidates.extend(urljoin(site_url, href) for href in parser.icon_hrefs)
    candidates.append(urljoin(root_url, "favicon.ico"))

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_candidates.append(normalized)
    return unique_candidates


def _download_binary(url: str, limit: int = 1024 * 1024) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "ScheduleHelper/1.0",
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=8) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"아이콘 파일이 너무 큽니다. 최대 {max(1, limit // (1024 * 1024))}MB까지 사용할 수 있습니다.")
        content_type = response.headers.get("Content-Type", "")
    return data, content_type


def _favorite_target_site_url(target: str) -> str | None:
    value = target.strip()
    if not value:
        return None
    lower = value.casefold()
    if lower.startswith(("http://", "https://")):
        return value
    if "://" in value or "\\" in value or value[:2].endswith(":") or " " in value:
        return None
    if "." not in value:
        return None
    return f"https://{value}"


def _icon_file_name_from_url(icon_url: str, content_type: str) -> str:
    path_name = Path(urlparse(icon_url).path).name
    if path_name and "." in path_name:
        return path_name[:120]
    return f"site-icon{_icon_suffix_from_content_type(content_type)}"


def _icon_suffix_from_content_type(content_type: str) -> str:
    lowered = content_type.casefold()
    if "png" in lowered:
        return ".png"
    if "jpeg" in lowered or "jpg" in lowered:
        return ".jpg"
    if "webp" in lowered:
        return ".webp"
    if "svg" in lowered:
        return ".svg"
    return ".ico"


def _charset_from_content_type(content_type: str) -> str:
    for part in content_type.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.casefold() == "charset" and value.strip():
            return value.strip()
    return "utf-8"


def _normalized_url(target: str) -> str:
    value = target.strip()
    lower = value.casefold()
    if lower.startswith(("http://", "https://", "mailto:")) or "://" in lower:
        return value
    return f"https://{value}"


def _format_clock(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes:02d}분"
    if minutes:
        return f"{minutes}분 {seconds:02d}초"
    return f"{seconds}초"


def _status_label(status: str) -> str:
    return {
        "ready": "대기 중",
        "running": "집중 중",
        "paused": "일시정지",
        "break": "휴식",
        "completed": "완료",
        "interrupted": "중단됨",
        "cancelled": "취소됨",
    }.get(status, status)


def _stabilize_control(control: QWidget, minimum_width: int | None = None) -> None:
    control.setMinimumHeight(34)
    if minimum_width is not None:
        control.setMinimumWidth(minimum_width)
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    if isinstance(control, QAbstractSpinBox):
        control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        control.setMinimumHeight(38)
        control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
