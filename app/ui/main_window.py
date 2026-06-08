from __future__ import annotations

import json
import os
import webbrowser
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QMimeData, QPoint, QSize, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import QColor, QDrag, QIcon, QKeySequence, QPixmap, QShortcut, QTextCursor, QTextImageFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.models import Event, FocusSession, LayoutProfile, LinkFavorite, Preference, QuickNote, Task
from app.services.app_usage import WindowsActiveWindowProvider
from app.services.focus_timer import FocusTimerService, decode_focus_targets
from app.storage.database import ScheduleRepository


FEATURE_MIME_TYPE = "application/x-schedule-helper-feature"


class FeatureDragHandle(QLabel):
    def __init__(self, feature_key: str, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.feature_key = feature_key
        self.drag_start: QPoint | None = None
        self.setObjectName("featureDragHandle")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(QSize(20, 22))
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("드래그해서 위치 변경")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self.drag_start is None:
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self.drag_start).manhattanLength()
        if distance < QApplication.startDragDistance():
            return

        mime = QMimeData()
        mime.setData(FEATURE_MIME_TYPE, self.feature_key.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_start = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class DraggableFeatureBox(QWidget):
    def __init__(
        self,
        feature_key: str,
        title: str,
        content: QWidget,
        swap_callback: Callable[[str, str, str], None],
        expand_content: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.feature_key = feature_key
        self.swap_callback = swap_callback
        self.setObjectName("featureBox")
        self.setAcceptDrops(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        bar = QWidget()
        bar.setObjectName("featureMoveBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        bar_layout.addWidget(FeatureDragHandle(feature_key, bar))
        title_label = QLabel(title)
        title_label.setObjectName("featureMoveTitle")
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bar_layout.addWidget(title_label)
        bar_layout.addStretch(1)
        layout.addWidget(bar)

        layout.addWidget(content, 1 if expand_content else 0)

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
        placement = "before" if drop_position.y() < max(1, self.height() // 2) else "after"
        self.swap_callback(source_key, self.feature_key, placement)
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
        self.selected_task_id: int | None = None
        self.compact_auto = False
        self.changing_mode = False
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

        self.setWindowTitle("Schedule Helper")
        self.setMinimumSize(QSize(430, 320))
        self.setStatusBar(QStatusBar(self))
        self._initialize_focus_timer()
        self._build_ui()
        self._apply_style()
        self.apply_preferences()
        self.refresh_all()

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
        page.setMinimumWidth(980)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)

        top_row = QHBoxLayout()
        title_box = QVBoxLayout()
        self.date_label = QLabel()
        self.date_label.setObjectName("mutedLabel")
        title = QLabel("Focus Desk")
        title.setObjectName("screenTitle")
        title_box.addWidget(self.date_label)
        title_box.addWidget(title)
        top_row.addLayout(title_box)
        top_row.addStretch(1)

        date_review_button = QPushButton("날짜별 보기")
        _stabilize_control(date_review_button, 106)
        date_review_button.clicked.connect(self.show_date_review_window)
        top_row.addWidget(date_review_button)

        settings_button = QPushButton("설정")
        _stabilize_control(settings_button, 78)
        settings_button.clicked.connect(self.show_settings_window)
        top_row.addWidget(settings_button)

        self.compact_button = QPushButton("위젯 모드")
        _stabilize_control(self.compact_button, 94)
        self.compact_button.clicked.connect(lambda: self.set_compact_mode(True))
        top_row.addWidget(self.compact_button)
        layout.addLayout(top_row)

        self.feature_boxes: dict[str, DraggableFeatureBox] = {}

        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setObjectName("bodySplitter")
        self.body_splitter.setChildrenCollapsible(False)

        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter.setObjectName("leftFeatureSplitter")
        self.left_splitter.setChildrenCollapsible(False)
        self.focus_panel = self._wrap_feature("focus", "집중", self._build_focus_panel())
        self.left_splitter.addWidget(self.focus_panel)
        self.pomodoro_panel = self._wrap_feature("pomodoro", "뽀모도로", self._build_pomodoro_panel())
        self.left_splitter.addWidget(self.pomodoro_panel)
        self.today_checklist_widget = TodayChecklistWidget(self.repository, self.refresh_today, self)
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

        self.left_splitter.setStretchFactor(0, 3)
        self.left_splitter.setStretchFactor(1, 1)
        self.left_splitter.setStretchFactor(2, 2)
        self.left_splitter.setStretchFactor(3, 4)
        self.left_splitter.setSizes([330, 130, 220, 360])
        self.body_splitter.addWidget(self.left_splitter)

        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setObjectName("rightFeatureSplitter")
        self.right_splitter.setChildrenCollapsible(False)

        self.inline_timeline_widget = TodayTimelineWidget(
            self.repository,
            self,
            on_changed=self.refresh_today,
            on_focus_task=self.load_task_by_id,
            on_delete_focus_session=self.delete_focus_session_by_id,
        )
        self.inline_timeline_widget.setMinimumWidth(520)
        self.inline_timeline_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.timeline_panel = self._wrap_feature("today_timeline", "오늘 시간표", self.inline_timeline_widget)
        self.right_splitter.addWidget(self.timeline_panel)
        self.link_favorites_panel = self._wrap_feature("link_favorites", "즐겨찾기", self._build_link_favorites_panel())
        self.right_splitter.addWidget(self.link_favorites_panel)
        self.right_splitter.setStretchFactor(0, 3)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([620, 220])
        self.body_splitter.addWidget(self.right_splitter)
        self.body_splitter.setStretchFactor(0, 2)
        self.body_splitter.setStretchFactor(1, 3)
        self.body_splitter.setSizes([560, 760])
        layout.addWidget(self.body_splitter, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _wrap_feature(self, feature_key: str, title: str, content: QWidget) -> DraggableFeatureBox:
        expand_content = feature_key not in {"today_checklist"}
        box = DraggableFeatureBox(feature_key, title, content, self.swap_feature_panels, expand_content)
        self.feature_boxes[feature_key] = box
        return box

    def swap_feature_panels(self, source_key: str, target_key: str, placement: str = "after") -> None:
        if source_key == target_key:
            return
        source = self.feature_boxes.get(source_key)
        target = self.feature_boxes.get(target_key)
        if source is None or target is None:
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
        source.setParent(None)
        if source_parent is target_parent and source_index < insert_index:
            insert_index -= 1
        target_parent.insertWidget(insert_index, source)
        self._restore_splitter_after_move(source_parent, source_sizes)
        if target_parent is not source_parent:
            self._restore_splitter_after_move(target_parent, target_sizes)

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
        panel = QWidget()
        panel.setObjectName("focusPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, 78)
        form.setColumnMinimumWidth(1, 170)
        form.setColumnMinimumWidth(2, 150)
        form.setColumnMinimumWidth(3, 150)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(2, 2)
        form.setColumnStretch(3, 2)

        self.focus_title_edit = QLineEdit()
        self.focus_title_edit.setPlaceholderText("지금 집중할 일")
        _stabilize_control(self.focus_title_edit, 220)
        form.addWidget(QLabel("집중"), 0, 0)
        form.addWidget(self.focus_title_edit, 0, 1, 1, 3)

        self.target_combo = QComboBox()
        self.target_combo.setMinimumContentsLength(28)
        self.target_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        _stabilize_control(self.target_combo, 320)
        self.add_target_button = QPushButton("추가")
        _stabilize_control(self.add_target_button, 62)
        self.add_target_button.clicked.connect(self.add_focus_target)
        self.target_refresh_button = QPushButton("목록 갱신")
        _stabilize_control(self.target_refresh_button, 82)
        self.target_refresh_button.clicked.connect(self.refresh_targets)
        target_action_box = QWidget()
        target_action_layout = QHBoxLayout(target_action_box)
        target_action_layout.setContentsMargins(0, 0, 0, 0)
        target_action_layout.setSpacing(6)
        target_action_layout.addWidget(self.add_target_button)
        target_action_layout.addWidget(self.target_refresh_button)
        form.addWidget(QLabel("화면"), 1, 0)
        form.addWidget(self.target_combo, 1, 1, 1, 2)
        form.addWidget(target_action_box, 1, 3)

        self.focus_targets_list = QListWidget()
        self.focus_targets_list.setMaximumHeight(72)
        self.focus_targets_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.remove_target_button = QPushButton("삭제")
        _stabilize_control(self.remove_target_button, 82)
        self.remove_target_button.clicked.connect(self.remove_selected_focus_target)
        form.addWidget(QLabel("지정 창"), 2, 0)
        form.addWidget(self.focus_targets_list, 2, 1, 1, 2)
        form.addWidget(self.remove_target_button, 2, 3)

        self.planned_minutes_spin = QSpinBox()
        self.planned_minutes_spin.setRange(1, 240)
        self.planned_minutes_spin.setValue(25)
        self.planned_minutes_spin.setSuffix("분")
        _stabilize_control(self.planned_minutes_spin, 120)
        self.idle_cutoff_spin = QSpinBox()
        self.idle_cutoff_spin.setRange(10, 600)
        self.idle_cutoff_spin.setValue(60)
        self.idle_cutoff_spin.setSuffix("초")
        _stabilize_control(self.idle_cutoff_spin, 120)
        form.addWidget(QLabel("목표 시간"), 3, 0)
        form.addWidget(self.planned_minutes_spin, 3, 1)
        form.addWidget(QLabel("자리 비움"), 4, 0)
        form.addWidget(self.idle_cutoff_spin, 4, 1)
        layout.addLayout(form)

        meter_row = QHBoxLayout()
        meter_box = QVBoxLayout()
        self.focus_status_label = QLabel("대기 중")
        self.focus_status_label.setObjectName("statusLabel")
        self.remaining_time_label = QLabel("25:00")
        self.remaining_time_label.setObjectName("timeLabel")
        self.focus_detail_label = QLabel("집중할 일과 화면을 고른 뒤 시작하세요.")
        self.focus_detail_label.setObjectName("mutedLabel")
        meter_box.addWidget(self.focus_status_label)
        meter_box.addWidget(self.remaining_time_label)
        meter_box.addWidget(self.focus_detail_label)
        meter_row.addLayout(meter_box, 2)

        self.focus_ratio_label = QLabel("유지율 100%")
        self.focus_ratio_label.setObjectName("ratioLabel")
        self.focus_ratio_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meter_row.addWidget(self.focus_ratio_label, 1)
        layout.addLayout(meter_row)

        self.focus_progress = QProgressBar()
        self.focus_progress.setRange(0, 1000)
        self.focus_progress.setTextVisible(False)
        layout.addWidget(self.focus_progress)

        button_row = QHBoxLayout()
        self.start_focus_button = QPushButton("시작")
        self.start_focus_button.clicked.connect(self.start_focus)
        self.pause_focus_button = QPushButton("일시정지")
        self.pause_focus_button.clicked.connect(self.pause_or_resume_focus)
        self.complete_focus_button = QPushButton("완료")
        self.complete_focus_button.clicked.connect(self.complete_focus)
        button_row.addWidget(self.start_focus_button)
        button_row.addWidget(self.pause_focus_button)
        button_row.addWidget(self.complete_focus_button)
        layout.addLayout(button_row)

        return panel

    def _build_pomodoro_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("pomodoroPanel")
        self.pomodoro_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        heading_row = QHBoxLayout()
        heading = QLabel("뽀모도로")
        heading.setObjectName("sectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.pomodoro_status_label = QLabel("대기")
        self.pomodoro_status_label.setObjectName("pomodoroStatus")
        self.pomodoro_time_label = QLabel("25:00")
        self.pomodoro_time_label.setObjectName("pomodoroTime")
        self.pomodoro_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_row.addWidget(self.pomodoro_status_label)
        heading_row.addWidget(self.pomodoro_time_label)
        layout.addLayout(heading_row)

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
        _stabilize_control(self.start_pomodoro_button, 68)
        self.start_pomodoro_button.clicked.connect(self.start_pomodoro)
        self.pause_pomodoro_button = QPushButton("일시정지")
        _stabilize_control(self.pause_pomodoro_button, 82)
        self.pause_pomodoro_button.clicked.connect(self.pause_or_resume_pomodoro)
        self.reset_pomodoro_button = QPushButton("초기화")
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
        self.quick_task_edit = QLineEdit()
        self.quick_task_edit.setPlaceholderText("오늘 할 일 빠르게 추가")
        _stabilize_control(self.quick_task_edit, 180)
        self.quick_task_minutes = QSpinBox()
        self.quick_task_minutes.setRange(5, 240)
        self.quick_task_minutes.setValue(25)
        self.quick_task_minutes.setSuffix("분")
        _stabilize_control(self.quick_task_minutes, 92)
        add_task_button = QPushButton("추가")
        _stabilize_control(add_task_button, 78)
        add_task_button.clicked.connect(self.add_quick_task)
        task_row.addWidget(self.quick_task_edit, 1)
        task_row.addWidget(self.quick_task_minutes)
        task_row.addWidget(add_task_button)
        layout.addLayout(task_row)

        event_row = QHBoxLayout()
        self.quick_event_edit = QLineEdit()
        self.quick_event_edit.setPlaceholderText("오늘 일정")
        _stabilize_control(self.quick_event_edit, 180)
        self.quick_event_time = QTimeEdit()
        self.quick_event_time.setDisplayFormat(_time_edit_display_format(self.preferences))
        self.quick_event_time.setTime(QTime.currentTime())
        _stabilize_control(self.quick_event_time, 92)
        add_event_button = QPushButton("일정 추가")
        _stabilize_control(add_event_button, 94)
        add_event_button.clicked.connect(self.add_quick_event)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("빠른 메모")
        heading.setObjectName("sectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        layout.addLayout(heading_row)

        self.memo_splitter = QSplitter(Qt.Orientation.Vertical)
        self.memo_splitter.setObjectName("memoSplitter")
        self.memo_splitter.setChildrenCollapsible(False)

        memo_editor = QWidget()
        memo_editor_layout = QVBoxLayout(memo_editor)
        memo_editor_layout.setContentsMargins(0, 0, 0, 0)
        memo_editor_layout.setSpacing(8)

        self.quick_note_editor = RichNoteEditor(self.repository, self)
        self.quick_note_editor.text_edit.setPlaceholderText("생각나는 것을 적고 Ctrl+Enter로 저장")
        memo_editor_layout.addWidget(self.quick_note_editor, 1)

        editor_actions_layout = QHBoxLayout()
        editor_actions_layout.setContentsMargins(0, 0, 0, 0)
        editor_actions_layout.setSpacing(6)
        editor_actions_layout.addStretch(1)
        attach_note_button = QPushButton("첨부")
        attach_note_button.clicked.connect(self.select_quick_note_attachments)
        _stabilize_control(attach_note_button, 72)
        attach_note_button.setMaximumWidth(84)
        save_note_button = QPushButton("저장")
        save_note_button.clicked.connect(self.save_quick_note)
        _stabilize_control(save_note_button, 72)
        save_note_button.setMaximumWidth(84)
        editor_actions_layout.addWidget(attach_note_button)
        editor_actions_layout.addWidget(save_note_button)
        memo_editor_layout.addLayout(editor_actions_layout)

        self.pending_attachments_label = QLabel("")
        self.pending_attachments_label.setObjectName("mutedLabel")
        self.pending_attachments_label.setWordWrap(True)
        self.pending_attachments_label.hide()
        memo_editor_layout.addWidget(self.pending_attachments_label)
        self.memo_splitter.addWidget(memo_editor)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.quick_note_editor.text_edit)
        shortcut.activated.connect(self.save_quick_note)
        shortcut_enter = QShortcut(QKeySequence("Ctrl+Enter"), self.quick_note_editor.text_edit)
        shortcut_enter.activated.connect(self.save_quick_note)

        self.notes_list = QListWidget()
        self.notes_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.notes_list.itemDoubleClicked.connect(self.show_quick_note_detail_from_item)
        self.notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_note_context_menu)
        self.memo_splitter.addWidget(self.notes_list)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("즐겨찾기")
        heading.setObjectName("sectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        favorites_settings_button = QPushButton("설정")
        _stabilize_control(favorites_settings_button, 68)
        favorites_settings_button.setMaximumWidth(78)
        favorites_settings_button.clicked.connect(self.show_favorites_settings)
        heading_row.addWidget(favorites_settings_button)
        layout.addLayout(heading_row)

        self.link_favorites_area = QScrollArea()
        self.link_favorites_area.setWidgetResizable(True)
        self.link_favorites_area.setFrameShape(QFrame.Shape.NoFrame)
        self.link_favorites_area.setMinimumHeight(120)

        favorites_widget = QWidget()
        favorites_widget.setMinimumWidth(0)
        self.link_favorites_layout = QVBoxLayout(favorites_widget)
        self.link_favorites_layout.setContentsMargins(0, 0, 0, 0)
        self.link_favorites_layout.setSpacing(8)
        self.link_favorites_area.setWidget(favorites_widget)
        layout.addWidget(self.link_favorites_area, 1)

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

        self.compact_favorites_panel = self._build_compact_favorites_panel()
        layout.addWidget(self.compact_favorites_panel)

        self.always_on_top_check = QCheckBox("항상 위")
        self.always_on_top_check.toggled.connect(self.toggle_always_on_top)
        layout.addWidget(self.always_on_top_check)
        layout.addStretch(1)
        return page

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f7f8f6;
                color: #182026;
                font-size: 13px;
            }
            QLabel {
                background: transparent;
            }
            QLabel#screenTitle {
                font-size: 28px;
                font-weight: 700;
            }
            QLabel#sectionTitle {
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#statusLabel {
                font-size: 16px;
                font-weight: 700;
                color: #36524b;
            }
            QLabel#timeLabel {
                font-size: 56px;
                font-weight: 800;
            }
            QLabel#ratioLabel {
                font-size: 22px;
                font-weight: 700;
                color: #2f5d62;
            }
            QLabel#compactTitle {
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#compactTime {
                font-size: 36px;
                font-weight: 800;
            }
            QLabel#mutedLabel {
                color: #66727a;
            }
            QLabel#pomodoroStatus {
                color: #36524b;
                font-weight: 700;
            }
            QLabel#pomodoroTime {
                font-size: 20px;
                font-weight: 800;
            }
            QWidget#focusPanel, QWidget#pomodoroPanel, QWidget#timelinePanel, QWidget#checklistPanel {
                background: #ffffff;
                border: 1px solid #dfe5e2;
                border-radius: 8px;
            }
            QWidget#featureBox {
                background: transparent;
            }
            QWidget#featureMoveBar {
                background: transparent;
            }
            QLabel#featureMoveTitle {
                color: #66727a;
                font-weight: 600;
            }
            QLabel#featureDragHandle {
                background: #d8e2de;
                border: 1px solid #9fb1ac;
                border-radius: 4px;
            }
            QCheckBox#completedChecklistItem {
                color: #66727a;
            }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
                background: #ffffff;
                border: 1px solid #c9d2d0;
                border-radius: 5px;
                min-height: 30px;
                padding: 4px 8px;
            }
            QSpinBox, QTimeEdit {
                background: #ffffff;
                border: 1px solid #c9d2d0;
                border-radius: 5px;
                min-height: 34px;
                padding: 4px 30px 4px 8px;
            }
            QSpinBox::up-button, QTimeEdit::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #c9d2d0;
                border-bottom: 1px solid #dbe2df;
                border-top-right-radius: 5px;
                background: #f8faf8;
            }
            QSpinBox::down-button, QTimeEdit::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 24px;
                border-left: 1px solid #c9d2d0;
                border-bottom-right-radius: 5px;
                background: #f8faf8;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover,
            QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {
                background: #eef4f1;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #b8c4c0;
                border-radius: 5px;
                min-height: 30px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background: #eef4f1;
            }
            QListWidget {
                background: #ffffff;
                border: 1px solid #d7dfdc;
                border-radius: 6px;
                padding: 4px;
            }
            QTableWidget#timeBlockTable {
                background: #ffffff;
                border: 1px solid #d7dfdc;
                gridline-color: #c7d0cc;
            }
            QSplitter::handle {
                background: #d7dfdc;
            }
            QSplitter::handle:horizontal {
                width: 8px;
            }
            QSplitter::handle:vertical {
                height: 8px;
            }
            QSplitter::handle:hover {
                background: #9fb1ac;
            }
            QProgressBar {
                background: #edf1ee;
                border: none;
                border-radius: 5px;
                min-height: 10px;
            }
            QProgressBar::chunk {
                background: #4d7c74;
                border-radius: 5px;
            }
            """
        )

    def refresh_all(self) -> None:
        self.date_label.setText(datetime.now().strftime("%Y년 %m월 %d일"))
        self.refresh_targets()
        self.refresh_today()
        self.refresh_notes()
        self.refresh_link_favorites()
        self.refresh_compact_favorites()
        self.refresh_history()
        self.update_focus_display()

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

    def add_focus_target(self) -> None:
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

    def refresh_today(self) -> None:
        if hasattr(self, "today_list"):
            self.today_list.clear()
            start_at, end_at = _today_window()

            for event in self.repository.list_events(start_at, end_at):
                item = QListWidgetItem(f"{_format_time(event.start_at, self.preferences)}  {event.title}")
                item.setData(Qt.ItemDataRole.UserRole, {"type": "event", "id": event.id})
                self.today_list.addItem(item)

            for task in self.repository.list_tasks(include_completed=False):
                due = _format_time(task.due_at, self.preferences) if task.due_at and task.due_at.date() == date.today() else ""
                prefix = f"{due}  " if due else ""
                item = QListWidgetItem(f"{prefix}{task.title}{_task_duration_suffix(task)}")
                item.setData(Qt.ItemDataRole.UserRole, {"type": "task", "id": task.id})
                self.today_list.addItem(item)
        self.refresh_today_checklist()
        self.refresh_inline_timeline()

    def refresh_notes(self) -> None:
        self.notes_list.clear()
        for note in self.repository.list_quick_notes(limit=12):
            body = " ".join(note.body.split())
            attachments = self.repository.list_quick_note_attachments(note.id) if note.id is not None else []
            attachment_label = f" · 첨부 {len(attachments)}개" if attachments else ""
            item = QListWidgetItem(f"{_format_datetime(note.created_at, self.preferences)}  {body}{attachment_label}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.notes_list.addItem(item)

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
            return

        for favorite in favorites:
            button = self._build_favorite_button(favorite)
            self.link_favorites_layout.addWidget(button)
        self.link_favorites_layout.addStretch(1)

    def _build_favorite_button(self, favorite: LinkFavorite) -> QWidget:
        mode = self.preferences.favorite_display_mode
        if mode == "text":
            button = QPushButton(favorite.title)
            button.setMinimumHeight(34)
        else:
            button = QToolButton()
            button.setText("" if mode == "icon_only" else favorite.title)
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if mode == "icon_only"
                else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            )
            button.setIconSize(QSize(34, 34))
            button.setMinimumHeight(54 if mode == "icon_only" else 72)
            icon = _favorite_qicon(favorite)
            if icon is not None:
                button.setIcon(icon)
            elif mode == "icon_only":
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                button.setText(_favorite_icon_text(favorite))
            else:
                button.setText(f"{_favorite_icon_text(favorite)}\n{favorite.title}")
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
            button.setMinimumWidth(70)
            button.setMaximumWidth(98)
            button.setMinimumHeight(34)
        else:
            button = QToolButton()
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
        self.statusBar().showMessage("즐겨찾기 설정을 저장했습니다.", 2500)

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
        if not self.preferences.show_today_timeline_inline:
            return
        self.inline_timeline_widget.set_date(date.today())

    def refresh_today_checklist(self) -> None:
        if not hasattr(self, "today_checklist_widget"):
            return
        if not self.preferences.show_today_checklist_inline:
            return
        self.today_checklist_widget.refresh_checklist()

    def add_quick_task(self) -> None:
        title = self.quick_task_edit.text().strip()
        if not title:
            return
        task = Task(title=title, duration_minutes=self.quick_task_minutes.value())
        self.repository.save_task(task)
        self.quick_task_edit.clear()
        self.refresh_today()
        self.statusBar().showMessage("오늘 할 일을 추가했습니다.", 2500)

    def add_quick_event(self) -> None:
        title = self.quick_event_edit.text().strip()
        if not title:
            return
        qtime = self.quick_event_time.time()
        start_at = datetime.combine(date.today(), time(qtime.hour(), qtime.minute()))
        event = Event(title=title, start_at=start_at, end_at=start_at + timedelta(minutes=30), fixed=True)
        self.repository.save_event(event)
        self.quick_event_edit.clear()
        self.refresh_today()
        self.statusBar().showMessage("오늘 일정을 추가했습니다.", 2500)

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
        dialog = SettingsDialog(self.preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.preferences = self.repository.save_preferences(dialog.preferences())
        self.apply_preferences()
        self.statusBar().showMessage("설정을 저장했습니다.", 2500)

    def apply_preferences(self) -> None:
        show_pomodoro = self.preferences.show_pomodoro_controls
        if hasattr(self, "pomodoro_panel"):
            self.pomodoro_panel.setVisible(show_pomodoro)
        if hasattr(self, "timeline_panel"):
            self.timeline_panel.setVisible(self.preferences.show_today_timeline_inline)
            if self.preferences.show_today_timeline_inline:
                self.inline_timeline_widget.set_date(date.today())
        if hasattr(self, "today_checklist_panel"):
            self.today_checklist_panel.setVisible(self.preferences.show_today_checklist_inline)
            if self.preferences.show_today_checklist_inline:
                self.today_checklist_widget.refresh_checklist()
        if hasattr(self, "memo_panel"):
            self.memo_panel.setVisible(self.preferences.show_quick_memo_panel)
        if hasattr(self, "link_favorites_panel"):
            self.link_favorites_panel.setVisible(self.preferences.show_link_favorites_panel)
            if self.preferences.show_link_favorites_panel:
                self.refresh_link_favorites()
        self.apply_time_display_format()
        if hasattr(self, "compact_favorites_panel"):
            self.compact_favorites_panel.setVisible(self.preferences.show_compact_favorites_panel)
            if self.preferences.show_compact_favorites_panel:
                self.refresh_compact_favorites()
        if not show_pomodoro:
            self.reset_pomodoro()
        else:
            self.update_pomodoro_display()

    def apply_time_display_format(self) -> None:
        display_format = _time_edit_display_format(self.preferences)
        for editor_name in ("quick_event_time",):
            editor = getattr(self, editor_name, None)
            if isinstance(editor, QTimeEdit):
                editor.setDisplayFormat(display_format)
        if hasattr(self, "notes_list"):
            self.refresh_notes()
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
        self.apply_layout_state(self.default_layout_state(), include_visibility=False)
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
                "lower": self._splitter_sizes("lower_splitter"),
                "right": self._splitter_sizes("right_splitter"),
                "memo": self._splitter_sizes("memo_splitter"),
            },
            "layout": {
                "body": self._splitter_child_tokens(self.body_splitter),
                "left": self._splitter_child_tokens(self.left_splitter),
                "lower": self._splitter_child_tokens(self.lower_splitter),
                "right": self._splitter_child_tokens(self.right_splitter),
            },
            "visible": {
                "pomodoro": self.preferences.show_pomodoro_controls,
                "today_timeline": self.preferences.show_today_timeline_inline,
                "today_checklist": self.preferences.show_today_checklist_inline,
                "quick_memo": self.preferences.show_quick_memo_panel,
                "link_favorites": self.preferences.show_link_favorites_panel,
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
                "body": [560, 760],
                "left": [330, 130, 220, 360],
                "lower": [640],
                "right": [620, 220],
                "memo": [220, 220],
            },
            "layout": self.default_feature_layout(),
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
            self._set_splitter_sizes("lower_splitter", splitters.get("lower"))
            self._set_splitter_sizes("right_splitter", splitters.get("right"))
            self._set_splitter_sizes("memo_splitter", splitters.get("memo"))

        QTimer.singleShot(0, apply_sizes)

    def _apply_layout_visibility(self, visible_state: object) -> None:
        if not isinstance(visible_state, dict):
            return

        mapping = {
            "pomodoro": "show_pomodoro_controls",
            "today_timeline": "show_today_timeline_inline",
            "today_checklist": "show_today_checklist_inline",
            "quick_memo": "show_quick_memo_panel",
            "link_favorites": "show_link_favorites_panel",
            "compact_favorites": "show_compact_favorites_panel",
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
        return {
            "body": ["group:left", "group:right"],
            "left": ["focus", "pomodoro", "today_checklist", "group:lower"],
            "lower": ["quick_memo"],
            "right": ["today_timeline", "link_favorites"],
        }

    def _apply_feature_layout(self, layout_state: object) -> None:
        layout_tokens = self._normalized_feature_layout(layout_state)
        self._reorder_splitter("body_splitter", layout_tokens["body"])
        self._reorder_splitter("left_splitter", layout_tokens["left"])
        self._reorder_splitter("lower_splitter", layout_tokens["lower"])
        self._reorder_splitter("right_splitter", layout_tokens["right"])

    def _normalized_feature_layout(self, layout_state: object) -> dict[str, list[str]]:
        default_layout = self.default_feature_layout()
        if not isinstance(layout_state, dict):
            return default_layout

        feature_keys = set(self.feature_boxes)
        result = {"body": [], "left": [], "lower": [], "right": []}
        seen_features: set[str] = set()

        for splitter_name in ("body", "left", "lower", "right"):
            raw_tokens = layout_state.get(splitter_name)
            if not isinstance(raw_tokens, list):
                raw_tokens = default_layout[splitter_name]
            for token in raw_tokens:
                if not isinstance(token, str):
                    continue
                if token == "group:left" and splitter_name == "body" and token not in result["body"]:
                    result["body"].append(token)
                elif token == "group:right" and splitter_name == "body" and token not in result["body"]:
                    result["body"].append(token)
                elif token == "group:lower" and splitter_name == "left" and token not in result["left"]:
                    result["left"].append(token)
                elif splitter_name == "body" and token in feature_keys and token not in seen_features:
                    result["right"].append(str(token))
                    seen_features.add(str(token))
                elif token in feature_keys and token not in seen_features:
                    result[splitter_name].append(str(token))
                    seen_features.add(str(token))

        if "group:left" not in result["body"]:
            result["body"].insert(0, "group:left")
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
        if token == "group:right":
            return self.right_splitter
        if token == "group:lower":
            return self.lower_splitter
        return self.feature_boxes.get(token)

    def _splitter_child_tokens(self, splitter: QSplitter) -> list[str]:
        tokens: list[str] = []
        for index in range(splitter.count()):
            widget = splitter.widget(index)
            if widget is self.left_splitter:
                tokens.append("group:left")
            elif widget is self.right_splitter:
                tokens.append("group:right")
            elif widget is self.lower_splitter:
                tokens.append("group:lower")
            else:
                feature_key = self._feature_key_for_widget(widget)
                if feature_key:
                    tokens.append(feature_key)
        return tokens

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
            QMessageBox.information(self, "오늘 흐름 삭제", "삭제할 할 일 또는 일정을 선택하세요.")
            return

        item_type = str(data["type"])
        item_id = int(data["id"])
        title = self._today_item_title(item_type, item_id)
        kind = "할 일" if item_type == "task" else "일정"
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
            return task.title if task else "선택한 할 일"
        event = self.repository.get_event(item_id)
        return event.title if event else "선택한 일정"

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
            detail = "집중할 일과 화면을 고른 뒤 시작하세요."
            ratio = 1.0
            progress = 0
            pause_text = "일시정지"
            controls_enabled = False
        else:
            remaining = self._display_remaining_seconds(session)
            status = _status_label(session.status)
            title = session.title
            ratio = self.focus_timer.focus_ratio() if self.focus_timer else 1.0
            progress = int(1000 * min(1.0, session.focused_seconds / max(1, session.planned_seconds)))
            pause_text = "재개" if session.status in {"paused", "break"} else "일시정지"
            controls_enabled = session.status in {"running", "paused", "break"}
            target = _focus_target_summary(session.target_process_name, session.target_window_title)
            detail = (
                f"집중 {_format_duration(session.focused_seconds)} · "
                f"이탈 {_format_duration(session.away_seconds)} · "
                f"일시정지 {_format_duration(session.paused_seconds)} · 화면 {target}"
            )

        self.focus_status_label.setText(status)
        self.remaining_time_label.setText(_format_clock(remaining))
        self.focus_detail_label.setText(detail)
        self.focus_ratio_label.setText(f"유지율 {int(ratio * 100)}%")
        self.focus_progress.setValue(progress)
        self.pause_focus_button.setText(pause_text)
        self.pause_focus_button.setEnabled(controls_enabled)
        self.complete_focus_button.setEnabled(controls_enabled)

        self.compact_title_label.setText(title)
        self.compact_time_label.setText(_format_clock(remaining))
        self.compact_status_label.setText(f"{status} · 유지율 {int(ratio * 100)}%")
        self.compact_progress.setValue(progress)
        self.compact_pause_button.setText(pause_text)
        self.compact_pause_button.setEnabled(controls_enabled)
        self.compact_done_button.setEnabled(controls_enabled)

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
        else:
            phase = "집중" if self.pomodoro_mode == "focus" else "휴식"
            status = f"{phase} 일시정지" if self.pomodoro_paused else f"{phase} 중"
            remaining = self.pomodoro_remaining_seconds
        self.pomodoro_status_label.setText(status)
        self.pomodoro_time_label.setText(_format_clock(remaining))
        self.update_pomodoro_controls()

    def save_quick_note(self) -> None:
        body = self.quick_note_editor.to_plain_text()
        attachment_paths = list(self.pending_quick_note_attachments)
        if not self.quick_note_editor.has_content() and not attachment_paths:
            return
        if not body:
            body = "이미지 메모" if self.quick_note_editor.has_content() else "첨부 메모"
        self._save_note_body(body, attachment_paths, self.quick_note_editor.to_html())
        self.quick_note_editor.set_content("", "")
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
    ) -> None:
        session = self.focus_timer.session if self.focus_timer else None
        process_name = ""
        if session is not None:
            process_name = session.target_process_name
        if self.focus_timer is not None and self.focus_timer.current_process_name:
            process_name = self.focus_timer.current_process_name
        note = self.repository.save_quick_note(
            QuickNote(
                body=body,
                content_html=content_html,
                created_at=datetime.now(),
                focus_session_id=session.id if session else None,
                task_id=session.task_id if session else self.selected_task_id,
                process_name=process_name,
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
        dialog = QuickNoteDetailDialog(self.repository, int(note_id), self)
        dialog.exec()
        self.refresh_notes()

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
        self.statusBar().showMessage("메모를 삭제했습니다.", 2500)

    def set_compact_mode(self, compact: bool, auto: bool = False) -> None:
        if self.changing_mode:
            return
        self.changing_mode = True
        try:
            self.compact_auto = auto
            self.stack.setCurrentWidget(self.compact_page if compact else self.full_page)
            if compact:
                self.setWindowTitle("Focus Widget")
                self.setMinimumSize(QSize(340, 230))
                self.resize(360, 260 if not self.preferences.show_compact_favorites_panel else 320)
            else:
                self.setWindowTitle("Schedule Helper")
                self.setMinimumSize(QSize(430, 320))
                self.resize(1120, 760)
        finally:
            self.changing_mode = False

    def toggle_always_on_top(self, enabled: bool) -> None:
        flags = self.windowFlags()
        if enabled:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.changing_mode:
            return
        if self.stack.currentWidget() == self.full_page and (self.width() < 900 or self.height() < 560):
            self.set_compact_mode(True, auto=True)
        elif self.stack.currentWidget() == self.compact_page and self.compact_auto and self.width() > 980 and self.height() > 640:
            self.set_compact_mode(False, auto=True)

    def closeEvent(self, event) -> None:
        if self.focus_timer is not None and self.focus_timer.session is not None:
            if self.focus_timer.session.status in {"running", "paused"}:
                self.focus_timer.stop(status="interrupted")
        super().closeEvent(event)


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

        self.created_label.setText(
            f"작성 시간 {_format_datetime(note.created_at, _preferences_from_widget(self), '%Y-%m-%d')}"
        )

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
        clear_icon_button = QPushButton("비우기")
        _stabilize_control(clear_icon_button, 72)
        clear_icon_button.clicked.connect(self.clear_favorite_icon)
        icon_file_row.addWidget(choose_icon_button)
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
        self.favorite_title_edit.setText(favorite.title)
        self.favorite_target_edit.setText(favorite.target)
        self.favorite_icon_text_edit.setText(favorite.icon_text)
        self.favorite_icon_path_edit.setText(favorite.icon_path)

    def clear_editor(self) -> None:
        self.selected_favorite_id = None
        self.selected_icon_source_path = ""
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
        self.favorite_icon_path_edit.setText(file_path)

    def clear_favorite_icon(self) -> None:
        self.selected_icon_source_path = ""
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
        favorite.icon_path = self.favorite_icon_path_edit.text().strip() if not self.selected_icon_source_path else favorite.icon_path
        favorite = self.repository.save_link_favorite(favorite)
        if self.selected_icon_source_path and favorite.id is not None:
            favorite.icon_path = self.repository.copy_link_favorite_icon(favorite.id, self.selected_icon_source_path)
            favorite = self.repository.save_link_favorite(favorite)
        self.selected_icon_source_path = ""
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
    def __init__(self, item_type: str, item: Task | Event, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item_type = item_type
        self.item = item
        self.item_date = self._item_date()
        item_label = "할 일" if item_type == "task" else "일정"
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
        selected_date: date,
        preferences: Preference,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle("할 일 추가")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(420, 500))
        self.resize(500, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel("할 일 추가")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("추가할 할 일")
        _stabilize_control(self.title_edit, 260)
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
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setFirstDayOfWeek(_qt_week_start_day(preferences.week_start_day))
        self.calendar.setSelectedDate(QDate(selected_date.year, selected_date.month, selected_date.day))
        self.calendar.setMinimumHeight(220)
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
            QMessageBox.information(self, "할 일 추가", "추가할 제목을 입력하세요.")
            return
        super().accept()


class TodayChecklistWidget(QWidget):
    def __init__(
        self,
        repository: ScheduleRepository,
        on_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
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
        title = QLabel("오늘 체크리스트")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedLabel")
        title_row.addWidget(self.summary_label)
        layout.addLayout(title_row)

        self.items_area = QScrollArea()
        self.items_area.setWidgetResizable(True)
        self.items_area.setFrameShape(QFrame.Shape.NoFrame)
        self.items_area.setMinimumWidth(0)
        self.items_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items_area.setMinimumHeight(160)
        self.items_area.setMaximumHeight(300)

        items_widget = QWidget()
        items_widget.setMinimumWidth(0)
        self.items_layout = QVBoxLayout(items_widget)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(10)

        self.active_label = QLabel()
        self.active_label.setObjectName("mutedLabel")
        self.items_layout.addWidget(self.active_label)
        self.active_items_layout = QVBoxLayout()
        self.active_items_layout.setContentsMargins(0, 0, 0, 0)
        self.active_items_layout.setSpacing(6)
        self.items_layout.addLayout(self.active_items_layout)

        self.completed_label = QLabel()
        self.completed_label.setObjectName("mutedLabel")
        self.items_layout.addWidget(self.completed_label)
        self.completed_items_layout = QVBoxLayout()
        self.completed_items_layout.setContentsMargins(0, 0, 0, 0)
        self.completed_items_layout.setSpacing(6)
        self.items_layout.addLayout(self.completed_items_layout)
        self.items_layout.addStretch(1)

        self.items_area.setWidget(items_widget)
        layout.addWidget(self.items_area)

        add_row = QHBoxLayout()
        self.new_task_edit = QLineEdit()
        self.new_task_edit.setPlaceholderText("오늘 할 일 추가")
        _stabilize_control(self.new_task_edit, 160)
        self.new_task_edit.returnPressed.connect(self.add_today_task)
        add_button = QPushButton("추가")
        _stabilize_control(add_button, 72)
        add_button.clicked.connect(self.add_today_task)
        add_row.addWidget(self.new_task_edit, 1)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.refresh_checklist()

    def refresh_checklist(self) -> None:
        self._refreshing = True
        try:
            self._clear_layout(self.active_items_layout)
            self._clear_layout(self.completed_items_layout)

            items = self._collect_items()
            active_items = [item for item in items if not item["completed"]]
            completed_items = [item for item in items if item["completed"]]

            active_items.sort(key=lambda item: (item["sort_at"] is None, item["sort_at"] or datetime.max, str(item["label"])))
            completed_items.sort(
                key=lambda item: item["completed_at"] or item["sort_at"] or datetime.min,
                reverse=True,
            )

            self.summary_label.setText(f"진행 중 {len(active_items)}개 · 완료 {len(completed_items)}개")
            self.active_label.setText(f"진행 중 {len(active_items)}")
            self.completed_label.setText(f"완료됨 {len(completed_items)}")

            if active_items:
                for item in active_items:
                    self._add_checkbox(self.active_items_layout, item)
            else:
                self._add_empty_label(self.active_items_layout, "진행 중인 할 일이나 일정이 없습니다.")

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
            items.append(
                {
                    "type": "event",
                    "id": event.id,
                    "completed": event.completed,
                    "completed_at": event.completed_at,
                    "sort_at": event.start_at,
                    "label": self._event_label(event, selected_date),
                }
            )

        for event in self.repository.list_completed_events():
            if event.id is None or event.id in listed_event_ids:
                continue
            if event.completed_at is None or event.completed_at.date() != selected_date:
                continue
            items.append(
                {
                    "type": "event",
                    "id": event.id,
                    "completed": True,
                    "completed_at": event.completed_at,
                    "sort_at": event.completed_at,
                    "label": self._event_label(event, selected_date),
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
            items.append(
                {
                    "type": "task",
                    "id": task.id,
                    "completed": task.completed,
                    "completed_at": task.completed_at,
                    "sort_at": sort_at,
                    "label": self._task_label(task, selected_date),
                }
            )

        return items

    def _add_checkbox(self, layout: QVBoxLayout, item: dict[str, object]) -> None:
        checkbox = QCheckBox(str(item["label"]))
        checkbox.setObjectName("completedChecklistItem" if item["completed"] else "todayChecklistItem")
        checkbox.setMinimumWidth(0)
        checkbox.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        checkbox.setToolTip(str(item["label"]))
        checkbox.setChecked(bool(item["completed"]))
        checkbox.toggled.connect(
            lambda checked, item_type=str(item["type"]), item_id=int(item["id"]): self.set_completed(
                item_type,
                item_id,
                checked,
            )
        )
        checkbox.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        checkbox.customContextMenuRequested.connect(
            lambda position, widget=checkbox, item_type=str(item["type"]), item_id=int(item["id"]), label=str(item["label"]): self.show_item_context_menu(
                widget,
                position,
                item_type,
                item_id,
                label,
            )
        )
        layout.addWidget(checkbox)

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

        dialog = ChecklistItemEditDialog(item_type, item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if item_type == "task" and isinstance(item, Task):
            item.title = dialog.item_title()
            item.duration_minutes = dialog.duration_minutes()
            item.due_at = dialog.selected_datetime() if dialog.uses_time() else None
            self.repository.save_task(item)
        elif item_type == "event" and isinstance(item, Event):
            start_at = dialog.selected_datetime()
            item.title = dialog.item_title()
            item.start_at = start_at
            item.end_at = start_at + timedelta(minutes=dialog.duration_minutes())
            self.repository.save_event(item)

        self.refresh_after_change()

    def refresh_after_change(self) -> None:
        if self.on_changed is not None:
            self.on_changed()
        else:
            self.refresh_checklist()

    def delete_item(self, item_type: str, item_id: int, label: str) -> None:
        kind = "할 일" if item_type == "task" else "일정"
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
        if task.due_at is None:
            time_label = "시간 없음"
        elif task.due_at.date() == selected_date:
            time_label = _format_time(task.due_at, preferences)
        else:
            time_label = f"마감 {_format_datetime(task.due_at, preferences)}"
        label = f"{time_label}  할 일  {task.title}{_task_duration_suffix(task)}"
        if task.completed:
            label += self._completed_suffix(task.completed_at, selected_date)
        return label

    def _event_label(self, event: Event, selected_date: date) -> str:
        preferences = _preferences_from_widget(self)
        label = f"{_format_time_range(event.start_at, event.end_at, preferences)}  일정  {event.title}"
        if event.completed:
            label += self._completed_suffix(event.completed_at, selected_date)
        return label

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
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.selected_date = date.today()
        self.on_changed = on_changed
        self.on_focus_task = on_focus_task
        self.on_delete_focus_session = on_delete_focus_session
        self.show_waiting_panel = show_waiting_panel
        self.setObjectName("timelinePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.date_label = QLabel()
        self.date_label.setObjectName("mutedLabel")
        title_row.addWidget(self.date_label)
        layout.addLayout(title_row)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedLabel")

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setObjectName("timelineContentSplitter")
        content_splitter.setChildrenCollapsible(False)

        time_panel = QWidget()
        time_layout = QVBoxLayout(time_panel)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(10)
        time_layout.addWidget(self.summary_label)

        self.block_table = QTableWidget(24, 7)
        self.block_table.setObjectName("timeBlockTable")
        self.block_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.block_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.block_table.setHorizontalHeaderLabels(["시간", "00", "10", "20", "30", "40", "50"])
        self.block_table.horizontalHeader().setVisible(True)
        self.block_table.verticalHeader().setVisible(False)
        self.block_table.setShowGrid(True)
        self.block_table.setMinimumHeight(390)
        self.block_table.setMaximumHeight(520)
        self.block_table.setMinimumWidth(390)
        self.block_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.block_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.block_table.setColumnWidth(0, 70)
        for column in range(1, 7):
            self.block_table.setColumnWidth(column, 48)
        for row in range(24):
            self.block_table.setRowHeight(row, 32)
        time_layout.addWidget(self.block_table)

        legend_row = QHBoxLayout()
        legend_row.setSpacing(14)
        for label, color in (
            ("일정", "#8fb9dd"),
            ("할 일", "#f1d16b"),
            ("완료", "#a8cf9d"),
            ("집중", "#b9a7e8"),
        ):
            chip = QLabel(f"■ {label}")
            chip.setStyleSheet(f"color: {color}; background: transparent;")
            legend_row.addWidget(chip)
        legend_row.addStretch(1)
        time_layout.addLayout(legend_row)

        self.timeline_list = QListWidget()
        self.timeline_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.timeline_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.timeline_list.customContextMenuRequested.connect(self.show_timeline_context_menu)
        time_layout.addWidget(self.timeline_list, 1)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("새로고침")
        _stabilize_control(refresh_button, 92)
        refresh_button.clicked.connect(self.refresh_timeline)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        time_layout.addLayout(button_row)

        content_splitter.addWidget(time_panel)
        if show_waiting_panel:
            self.waiting_panel = self._build_waiting_panel()
            content_splitter.addWidget(self.waiting_panel)
            content_splitter.setStretchFactor(0, 3)
            content_splitter.setStretchFactor(1, 1)
            content_splitter.setSizes([680, 260])
        else:
            content_splitter.setStretchFactor(0, 1)
        layout.addWidget(content_splitter, 1)

        self.refresh_timeline()

    def _build_waiting_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("timelineWaitingPanel")
        panel.setMinimumWidth(210)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("대기함")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.waiting_summary_label = QLabel()
        self.waiting_summary_label.setObjectName("mutedLabel")
        title_row.addWidget(self.waiting_summary_label)
        layout.addLayout(title_row)

        task_row = QHBoxLayout()
        add_task_button = QPushButton("할 일 추가")
        _stabilize_control(add_task_button, 96)
        add_task_button.clicked.connect(self.add_waiting_task)
        task_row.addWidget(add_task_button)
        task_row.addStretch(1)
        layout.addLayout(task_row)

        event_row = QHBoxLayout()
        self.timeline_event_edit = QLineEdit()
        self.timeline_event_edit.setPlaceholderText("일정 추가")
        _stabilize_control(self.timeline_event_edit, 120)
        self.timeline_event_time = QTimeEdit()
        self.timeline_event_time.setDisplayFormat(_time_edit_display_format(_preferences_from_widget(self)))
        self.timeline_event_time.setTime(QTime.currentTime())
        _stabilize_control(self.timeline_event_time, 78)
        add_event_button = QPushButton("등록")
        _stabilize_control(add_event_button, 64)
        add_event_button.clicked.connect(self.add_timeline_event)
        event_row.addWidget(self.timeline_event_edit, 1)
        event_row.addWidget(self.timeline_event_time)
        event_row.addWidget(add_event_button)
        layout.addLayout(event_row)

        self.waiting_list = QListWidget()
        self.waiting_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.waiting_list.itemDoubleClicked.connect(self.focus_waiting_item)
        self.waiting_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.waiting_list.customContextMenuRequested.connect(self.show_waiting_context_menu)
        layout.addWidget(self.waiting_list, 1)

        hint = QLabel("시간 없는 할 일이 여기에 모입니다.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return panel

    def add_waiting_task(self) -> None:
        preferences = _preferences_from_widget(self)
        dialog = TaskAddDialog(self.selected_date, preferences, self)
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
        self.repository.save_event(
            Event(
                title=title,
                start_at=start_at,
                end_at=start_at + timedelta(minutes=30),
                fixed=True,
            )
        )
        self.timeline_event_edit.clear()
        self.refresh_after_change()

    def refresh_after_change(self) -> None:
        self.refresh_timeline()
        if self.on_changed is not None:
            self.on_changed()

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
        if not tasks:
            empty = QListWidgetItem("대기 중인 할 일이 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.waiting_list.addItem(empty)
            return

        for task in tasks:
            item = QListWidgetItem(task.title)
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

        dialog = ChecklistItemEditDialog(item_type, item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if item_type == "task" and isinstance(item, Task):
            item.title = dialog.item_title()
            item.duration_minutes = dialog.duration_minutes()
            item.due_at = dialog.selected_datetime() if dialog.uses_time() else None
            self.repository.save_task(item)
        elif item_type == "event" and isinstance(item, Event):
            start_at = dialog.selected_datetime()
            item.title = dialog.item_title()
            item.start_at = start_at
            item.end_at = start_at + timedelta(minutes=dialog.duration_minutes())
            self.repository.save_event(item)
        self.refresh_after_change()

    def set_timeline_item_completed(self, item_type: str, item_id: int, completed: bool) -> None:
        if item_type == "task":
            self.repository.mark_task_completed(item_id, completed)
        elif item_type == "event":
            self.repository.mark_event_completed(item_id, completed)
        self.refresh_after_change()

    def delete_timeline_item(self, item_type: str, item_id: int, title: str) -> None:
        kind = "할 일" if item_type == "task" else "일정"
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
        self.date_label.setText(selected_date.strftime("%Y년 %m월 %d일"))
        items = _today_timeline_items(self.repository, selected_date, preferences)
        blocks = _today_timeline_blocks(self.repository, selected_date)
        schedule_count = sum(1 for item in items if item[2] in {"schedule", "task"})
        completed_count = sum(1 for item in items if item[2] == "completed")
        focus_count = sum(1 for item in items if item[2] == "focus")
        self.summary_label.setText(
            f"일정/할 일 {schedule_count}개 · 완료 {completed_count}개 · 집중 기록 {focus_count}개"
        )
        _fill_time_block_table(self.block_table, selected_date, blocks, preferences)
        _fill_timeline_list(self.timeline_list, items, preferences)
        self.refresh_waiting()
        self._resize_time_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_time_columns()

    def _resize_time_columns(self) -> None:
        available_width = max(0, self.block_table.viewport().width() - self.block_table.columnWidth(0) - 4)
        block_width = max(42, available_width // 6)
        for column in range(1, 7):
            self.block_table.setColumnWidth(column, block_width)


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
        self.setWindowTitle("오늘 시간표")
        self.resize(920, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.timeline_widget = TodayTimelineWidget(
            repository,
            self,
            on_changed=on_changed,
            on_focus_task=on_focus_task,
            on_delete_focus_session=on_delete_focus_session,
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


class CompletedTasksDialog(QDialog):
    def __init__(self, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("완료 목록")
        self.resize(560, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("완료된 일정")
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
            f"할 일 {len(tasks)}개 · 일정 {len(events)}개"
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
                due = _format_datetime(completed_item.due_at, preferences) if completed_item.due_at else "마감 없음"
                text = f"{completed_at}  [할 일] {completed_item.title}{_task_duration_suffix(completed_item)} · {due}"
            else:
                text = (
                    f"{completed_at}  [일정] {completed_item.title} · "
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
            title = selected.title if selected else "선택한 할 일"
            kind = "할 일"
        else:
            selected = self.repository.get_event(item_id)
            title = selected.title if selected else "선택한 일정"
            kind = "일정"
        answer = QMessageBox.question(self, "완료 목록 삭제", f"'{title}' {kind}을 완전히 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if item_type == "task":
            self.repository.delete_task(item_id)
        else:
            self.repository.delete_event(item_id)
        self.refresh_completed_tasks()


class DateItemDialog(QDialog):
    def __init__(self, selected_date: date, item_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selected_date = selected_date
        self.item_type = item_type
        item_label = "할 일" if item_type == "task" else "일정"
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
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setFirstDayOfWeek(_qt_week_start_day(preferences.week_start_day))
        self.calendar.setSelectedDate(QDate(selected_date.year, selected_date.month, selected_date.day))
        self.calendar.setMinimumHeight(220)
        layout.addWidget(self.calendar, 1)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(f"추가할 {item_label}")
        _stabilize_control(self.title_edit, 260)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat(_time_edit_display_format(preferences))
        self.time_edit.setTime(QTime.currentTime())
        _stabilize_control(self.time_edit, 96)
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(5, 240)
        self.minutes_spin.setValue(25 if item_type == "task" else 30)
        self.minutes_spin.setSuffix("분")
        _stabilize_control(self.minutes_spin, 96)
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
        self.calendar.setGridVisible(True)
        self.calendar.setMinimumWidth(300)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setFirstDayOfWeek(_qt_week_start_day(preferences.week_start_day))
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

        detail_column.addWidget(QLabel("일정"))
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
            f"일정 {len(schedule_items)}개 · 기록 {len(record_items)}개 · 메모 {len(quick_note_items)}개"
        )
        _fill_list(self.schedule_list, schedule_items, "이 날짜에 표시할 일정이 없습니다.")
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
        task_action = menu.addAction(f"{selected_date:%m/%d} 할 일 추가")
        task_action.triggered.connect(lambda _checked=False, day=selected_date: self.show_date_item_dialog("task", day))
        event_action = menu.addAction(f"{selected_date:%m/%d} 일정 추가")
        event_action.triggered.connect(lambda _checked=False, day=selected_date: self.show_date_item_dialog("event", day))
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

    def show_date_item_dialog(self, item_type: str, selected_date: date) -> None:
        dialog = DateItemDialog(selected_date, item_type, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.save_selected_date_item(
            item_type,
            dialog.item_title(),
            dialog.selected_time(),
            dialog.duration_minutes(),
            dialog.selected_date_value(),
        )

    def save_selected_date_item(
        self,
        item_type: str,
        title: str,
        selected_time: QTime,
        duration_minutes: int,
        selected_date: date | None = None,
    ) -> None:
        target_date = selected_date or _date_from_qdate(self.calendar.selectedDate())
        starts_at = datetime.combine(target_date, time(selected_time.hour(), selected_time.minute()))
        if item_type == "task":
            self.repository.save_task(Task(title=title, duration_minutes=duration_minutes, due_at=starts_at))
        else:
            self.repository.save_event(
                Event(title=title, start_at=starts_at, end_at=starts_at + timedelta(minutes=duration_minutes), fixed=True)
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


class SettingsDialog(QDialog):
    def __init__(self, preferences: Preference, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(480, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        self.week_start_combo = QComboBox()
        self.week_start_combo.addItem("월요일", 0)
        self.week_start_combo.addItem("일요일", 6)
        index = self.week_start_combo.findData(6 if preferences.week_start_day == 6 else 0)
        self.week_start_combo.setCurrentIndex(max(0, index))
        form.addRow("한 주의 시작", self.week_start_combo)

        self.time_format_combo = QComboBox()
        self.time_format_combo.addItem("24시간 (13:30)", "24h")
        self.time_format_combo.addItem("12시간 (PM 1:30)", "12h")
        time_index = self.time_format_combo.findData(preferences.time_format)
        self.time_format_combo.setCurrentIndex(max(0, time_index))
        form.addRow("시간 표시", self.time_format_combo)

        self.show_pomodoro_check = QCheckBox("표시")
        self.show_pomodoro_check.setChecked(preferences.show_pomodoro_controls)
        form.addRow("뽀모도로", self.show_pomodoro_check)

        self.show_today_timeline_inline_check = QCheckBox("메인 화면에 표시")
        self.show_today_timeline_inline_check.setChecked(preferences.show_today_timeline_inline)
        form.addRow("오늘 시간표", self.show_today_timeline_inline_check)

        self.show_today_checklist_inline_check = QCheckBox("메인 화면에 표시")
        self.show_today_checklist_inline_check.setChecked(preferences.show_today_checklist_inline)
        form.addRow("오늘 체크리스트", self.show_today_checklist_inline_check)

        self.show_quick_memo_panel_check = QCheckBox("메인 화면에 표시")
        self.show_quick_memo_panel_check.setChecked(preferences.show_quick_memo_panel)
        form.addRow("빠른 메모", self.show_quick_memo_panel_check)
        layout.addLayout(form)

        self.show_link_favorites_panel_check = QCheckBox("메인 화면에 표시")
        self.show_link_favorites_panel_check.setChecked(preferences.show_link_favorites_panel)
        form.addRow("즐겨찾기", self.show_link_favorites_panel_check)

        self.show_compact_favorites_panel_check = QCheckBox("위젯 모드에 표시")
        self.show_compact_favorites_panel_check.setChecked(preferences.show_compact_favorites_panel)
        form.addRow("위젯 즐겨찾기", self.show_compact_favorites_panel_check)

        layout_tools_row = QHBoxLayout()
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
        layout.addLayout(layout_tools_row)

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

    def run_parent_layout_action(self, action_name: str) -> None:
        parent = self.parent()
        action = getattr(parent, action_name, None)
        if action is None:
            return
        action()
        preferences = getattr(parent, "preferences", self._source)
        self.sync_from_preferences(preferences)

    def sync_from_preferences(self, preferences: Preference) -> None:
        time_index = self.time_format_combo.findData(preferences.time_format)
        self.time_format_combo.setCurrentIndex(max(0, time_index))
        self.show_pomodoro_check.setChecked(preferences.show_pomodoro_controls)
        self.show_today_timeline_inline_check.setChecked(preferences.show_today_timeline_inline)
        self.show_today_checklist_inline_check.setChecked(preferences.show_today_checklist_inline)
        self.show_quick_memo_panel_check.setChecked(preferences.show_quick_memo_panel)
        self.show_link_favorites_panel_check.setChecked(preferences.show_link_favorites_panel)
        self.show_compact_favorites_panel_check.setChecked(preferences.show_compact_favorites_panel)
        self._source = preferences

    def preferences(self) -> Preference:
        return Preference(
            day_max_minutes=self._source.day_max_minutes,
            break_minutes=self._source.break_minutes,
            strategy=self._source.strategy,
            week_start_day=int(self.week_start_combo.currentData()),
            time_format=str(self.time_format_combo.currentData()),
            show_pomodoro_controls=self.show_pomodoro_check.isChecked(),
            show_today_timeline_inline=self.show_today_timeline_inline_check.isChecked(),
            show_today_checklist_inline=self.show_today_checklist_inline_check.isChecked(),
            show_today_flow_panel=False,
            show_quick_memo_panel=self.show_quick_memo_panel_check.isChecked(),
            show_link_favorites_panel=self.show_link_favorites_panel_check.isChecked(),
            show_compact_favorites_panel=self.show_compact_favorites_panel_check.isChecked(),
            favorite_display_mode=self._source.favorite_display_mode,
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
        items.append(
            (
                event.start_at,
                f"{_format_time_range(event.start_at, event.end_at, preferences)}  [일정] {event.title}{status}",
                {"type": "event", "id": event.id, "kind": "일정", "title": event.title},
            )
        )

    for task in repository.list_tasks(include_completed=True):
        if not _task_belongs_to_date(task, selected_date):
            continue
        reference_at = task.due_at or task.created_at
        time_label = _format_time(task.due_at, preferences) if task.due_at and task.due_at.date() == selected_date else "시간 없음"
        status = "완료" if task.completed else "진행 중"
        items.append(
            (
                reference_at,
                f"{time_label}  [할 일] {task.title}{_task_duration_suffix(task)} · {status}",
                {"type": "task", "id": task.id, "kind": "할 일", "title": task.title},
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
        items.append(
            (
                task.completed_at,
                f"{_format_time(task.completed_at, preferences)}  [완료] 할 일 · {task.title}",
                {"type": "task", "id": task.id, "kind": "할 일", "title": task.title},
            )
        )

    for event in repository.list_completed_events():
        if event.completed_at is None or event.completed_at.date() != selected_date:
            continue
        items.append(
            (
                event.completed_at,
                f"{_format_time(event.completed_at, preferences)}  [완료] 일정 · {event.title}",
                {"type": "event", "id": event.id, "kind": "일정", "title": event.title},
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
        items.append(
            (
                event.start_at,
                f"{_format_time_range(event.start_at, event.end_at, preferences)}  일정  {event.title}{status}",
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
        items.append(
            (
                reference_at,
                f"{time_label}  할 일  {task.title}{_task_duration_suffix(task)} · {status}",
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
                f"완료 {_format_time(task.completed_at, preferences)}  할 일  {task.title}{_task_duration_suffix(task)}",
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
                f"완료 {_format_time(event.completed_at, preferences)}  일정  {event.title}",
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
            f"일정 {event.title}",
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
            f"할 일 {task.title}",
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
            f"완료 일정 {event.title}",
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
    day_start = datetime.combine(selected_date, time.min)
    table.clearContents()
    for row in range(24):
        hour_item = QTableWidgetItem(_format_time(time(row, 0), preferences))
        hour_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        hour_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        hour_item.setBackground(QColor("#f3f6f4"))
        table.setItem(row, 0, hour_item)
        for column in range(1, 7):
            item = QTableWidgetItem("")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip(_format_time(time(row, (column - 1) * 10), preferences))
            item.setBackground(QColor("#ffffff"))
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
            item.setBackground(QColor("#5d6f78" if current_color != "#ffffff" else _timeline_block_color(category)))
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
        empty = QListWidgetItem("오늘 표시할 일정이나 완료 기록이 없습니다.")
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


def _favorite_qicon(favorite: LinkFavorite) -> QIcon | None:
    icon_path = favorite.icon_path.strip()
    if not icon_path:
        return None
    path = Path(icon_path)
    if not path.exists():
        return None
    return QIcon(str(path))


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
