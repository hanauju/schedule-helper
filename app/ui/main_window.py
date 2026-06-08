from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QDate, QPoint, QSize, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import Event, FocusSession, Preference, QuickNote, Task
from app.services.app_usage import WindowsActiveWindowProvider
from app.services.focus_timer import FocusTimerService, decode_focus_targets
from app.storage.database import ScheduleRepository


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

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setObjectName("bodySplitter")
        body_splitter.setChildrenCollapsible(False)

        left_column = QWidget()
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(16)
        left_column_layout.addWidget(self._build_focus_panel())
        left_column_layout.addWidget(self._build_pomodoro_panel())
        self.today_checklist_widget = TodayChecklistWidget(self.repository, self.refresh_today, self)
        left_column_layout.addWidget(self.today_checklist_widget)

        lower_row = QHBoxLayout()
        lower_row.setSpacing(16)
        self.today_panel = self._build_today_panel()
        self.memo_panel = self._build_memo_panel()
        lower_row.addWidget(self.today_panel, 1)
        lower_row.addWidget(self.memo_panel, 1)
        left_column_layout.addLayout(lower_row, 1)

        body_splitter.addWidget(left_column)

        self.inline_timeline_widget = TodayTimelineWidget(self.repository)
        self.inline_timeline_widget.setMinimumWidth(360)
        self.inline_timeline_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        body_splitter.addWidget(self.inline_timeline_widget)
        body_splitter.setStretchFactor(0, 3)
        body_splitter.setStretchFactor(1, 1)
        body_splitter.setSizes([900, 460])
        layout.addWidget(body_splitter, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

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
        self.quick_event_time.setDisplayFormat("HH:mm")
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
        delete_note_button = QPushButton("삭제")
        _stabilize_control(delete_note_button, 72)
        delete_note_button.clicked.connect(self.delete_selected_quick_note)
        heading_row.addWidget(delete_note_button)
        layout.addLayout(heading_row)

        self.quick_note_edit = QPlainTextEdit()
        self.quick_note_edit.setPlaceholderText("생각나는 것을 적고 Ctrl+Enter로 저장")
        self.quick_note_edit.setMinimumHeight(120)
        layout.addWidget(self.quick_note_edit)

        save_note_button = QPushButton("메모 저장")
        save_note_button.clicked.connect(self.save_quick_note)
        layout.addWidget(save_note_button)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.quick_note_edit)
        shortcut.activated.connect(self.save_quick_note)
        shortcut_enter = QShortcut(QKeySequence("Ctrl+Enter"), self.quick_note_edit)
        shortcut_enter.activated.connect(self.save_quick_note)

        self.notes_list = QListWidget()
        self.notes_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_note_context_menu)
        layout.addWidget(self.notes_list, 1)
        delete_note_shortcut = QShortcut(QKeySequence("Delete"), self.notes_list)
        delete_note_shortcut.activated.connect(self.delete_selected_quick_note)
        return panel

    def _build_compact_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

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
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#compactTime {
                font-size: 44px;
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
            QCheckBox#completedChecklistItem {
                color: #66727a;
            }
            QLineEdit, QPlainTextEdit, QComboBox {
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
        self.today_list.clear()
        start_at, end_at = _today_window()

        for event in self.repository.list_events(start_at, end_at):
            item = QListWidgetItem(f"{event.start_at:%H:%M}  {event.title}")
            item.setData(Qt.ItemDataRole.UserRole, {"type": "event", "id": event.id})
            self.today_list.addItem(item)

        for task in self.repository.list_tasks(include_completed=False):
            due = task.due_at.strftime("%H:%M") if task.due_at and task.due_at.date() == date.today() else ""
            prefix = f"{due}  " if due else ""
            item = QListWidgetItem(f"{prefix}{task.title} · {task.duration_minutes}분")
            item.setData(Qt.ItemDataRole.UserRole, {"type": "task", "id": task.id})
            self.today_list.addItem(item)
        self.refresh_today_checklist()
        self.refresh_inline_timeline()

    def refresh_notes(self) -> None:
        self.notes_list.clear()
        for note in self.repository.list_quick_notes(limit=12):
            body = " ".join(note.body.split())
            item = QListWidgetItem(f"{note.created_at:%m/%d %H:%M}  {body}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.notes_list.addItem(item)

    def refresh_history(self) -> None:
        self.history_list.clear()
        for session in self.repository.list_focus_sessions(limit=8):
            item = QListWidgetItem(
                f"{_focus_session_time_label(session, include_date=True)}  {session.title} · "
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
        task = self.repository.get_task(int(data["id"]))
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
        dialog = TodayTimelineDialog(self.repository, self)
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
        if hasattr(self, "inline_timeline_widget"):
            self.inline_timeline_widget.setVisible(self.preferences.show_today_timeline_inline)
            if self.preferences.show_today_timeline_inline:
                self.inline_timeline_widget.set_date(date.today())
        if hasattr(self, "today_checklist_widget"):
            self.today_checklist_widget.setVisible(self.preferences.show_today_checklist_inline)
            if self.preferences.show_today_checklist_inline:
                self.today_checklist_widget.refresh_checklist()
        if hasattr(self, "today_panel"):
            self.today_panel.setVisible(self.preferences.show_today_flow_panel)
        if hasattr(self, "memo_panel"):
            self.memo_panel.setVisible(self.preferences.show_quick_memo_panel)
        if not show_pomodoro:
            self.reset_pomodoro()
        else:
            self.update_pomodoro_display()

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

        session_id = int(session_id)
        session = self.repository.get_focus_session(session_id)
        title = session.title if session else "선택한 집중 기록"
        current_session = self.focus_timer.session if self.focus_timer else None
        is_active_session = current_session is not None and current_session.id == session_id
        message = f"'{title}' 집중 기록을 삭제할까요?"
        if is_active_session and current_session.status in {"running", "paused", "break"}:
            message += "\n진행 중인 타이머도 함께 중단됩니다."

        answer = QMessageBox.question(self, "집중 기록 삭제", message)
        if answer != QMessageBox.StandardButton.Yes:
            return

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
        body = self.quick_note_edit.toPlainText().strip()
        if not body:
            return
        self._save_note_body(body)
        self.quick_note_edit.clear()

    def save_compact_note(self) -> None:
        body = self.compact_note_edit.text().strip()
        if not body:
            return
        self._save_note_body(body)
        self.compact_note_edit.clear()

    def _save_note_body(self, body: str) -> None:
        session = self.focus_timer.session if self.focus_timer else None
        process_name = ""
        if session is not None:
            process_name = session.target_process_name
        if self.focus_timer is not None and self.focus_timer.current_process_name:
            process_name = self.focus_timer.current_process_name
        self.repository.save_quick_note(
            QuickNote(
                body=body,
                created_at=datetime.now(),
                focus_session_id=session.id if session else None,
                task_id=session.task_id if session else self.selected_task_id,
                process_name=process_name,
            )
        )
        self.refresh_notes()
        self.statusBar().showMessage("메모를 저장했습니다.", 2500)

    def show_note_context_menu(self, position: QPoint) -> None:
        item = self.notes_list.itemAt(position)
        if item is None:
            return
        self.notes_list.setCurrentItem(item)
        if item.data(Qt.ItemDataRole.UserRole) is None:
            return

        menu = QMenu(self.notes_list)
        edit_action = menu.addAction("수정")
        edit_action.triggered.connect(self.edit_selected_quick_note)
        menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_quick_note)
        menu.exec(self.notes_list.mapToGlobal(position))

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

        dialog = QuickNoteEditDialog(note, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        note.body = dialog.body()
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
                self.resize(430, 320)
            else:
                self.setWindowTitle("Schedule Helper")
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
    def __init__(self, note: QuickNote, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("빠른 메모 수정")
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        created_label = QLabel(f"작성 시간 {note.created_at:%Y-%m-%d %H:%M}")
        created_label.setObjectName("mutedLabel")
        layout.addWidget(created_label)

        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlainText(note.body)
        self.body_edit.setMinimumHeight(220)
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
        return self.body_edit.toPlainText().strip()

    def accept(self) -> None:
        if not self.body():
            QMessageBox.information(self, "빠른 메모 수정", "메모 내용을 입력하세요.")
            return
        super().accept()


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
        self.time_edit.setDisplayFormat("HH:mm")
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
        self.minutes_spin.setRange(5, 240)
        self.minutes_spin.setValue(max(5, item.duration_minutes))
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
        self.items_area.setMinimumHeight(160)
        self.items_area.setMaximumHeight(300)

        items_widget = QWidget()
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
        if task.due_at is None:
            time_label = "시간 없음"
        elif task.due_at.date() == selected_date:
            time_label = task.due_at.strftime("%H:%M")
        else:
            time_label = f"마감 {task.due_at:%m/%d %H:%M}"
        label = f"{time_label}  할 일  {task.title} · {task.duration_minutes}분"
        if task.completed:
            label += self._completed_suffix(task.completed_at, selected_date)
        return label

    def _event_label(self, event: Event, selected_date: date) -> str:
        label = f"{event.start_at:%H:%M}-{event.end_at:%H:%M}  일정  {event.title}"
        if event.completed:
            label += self._completed_suffix(event.completed_at, selected_date)
        return label

    def _completed_suffix(self, completed_at: datetime | None, selected_date: date) -> str:
        if completed_at is None:
            return " · 완료"
        if completed_at.date() == selected_date:
            return f" · 완료 {completed_at:%H:%M}"
        return f" · 완료 {completed_at:%m/%d %H:%M}"

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
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.selected_date = date.today()
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
        layout.addWidget(self.summary_label)

        self.block_table = QTableWidget(24, 7)
        self.block_table.setObjectName("timeBlockTable")
        self.block_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.block_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.block_table.setHorizontalHeaderLabels(["시간", "00", "10", "20", "30", "40", "50"])
        self.block_table.horizontalHeader().setVisible(True)
        self.block_table.verticalHeader().setVisible(False)
        self.block_table.setShowGrid(True)
        self.block_table.setMinimumHeight(390)
        self.block_table.setMaximumHeight(460)
        self.block_table.setMinimumWidth(390)
        self.block_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.block_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.block_table.setColumnWidth(0, 70)
        for column in range(1, 7):
            self.block_table.setColumnWidth(column, 48)
        for row in range(24):
            self.block_table.setRowHeight(row, 32)
        layout.addWidget(self.block_table)

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
        layout.addLayout(legend_row)

        self.timeline_list = QListWidget()
        self.timeline_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.timeline_list, 1)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("새로고침")
        _stabilize_control(refresh_button, 92)
        refresh_button.clicked.connect(self.refresh_timeline)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.refresh_timeline()

    def set_date(self, selected_date: date) -> None:
        self.selected_date = selected_date
        self.refresh_timeline()

    def refresh_timeline(self) -> None:
        selected_date = self.selected_date
        self.date_label.setText(selected_date.strftime("%Y년 %m월 %d일"))
        items = _today_timeline_items(self.repository, selected_date)
        blocks = _today_timeline_blocks(self.repository, selected_date)
        schedule_count = sum(1 for item in items if item[2] in {"schedule", "task"})
        completed_count = sum(1 for item in items if item[2] == "completed")
        focus_count = sum(1 for item in items if item[2] == "focus")
        self.summary_label.setText(
            f"일정/할 일 {schedule_count}개 · 완료 {completed_count}개 · 집중 기록 {focus_count}개"
        )
        _fill_time_block_table(self.block_table, selected_date, blocks)
        _fill_timeline_list(self.timeline_list, items)
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
    def __init__(self, repository: ScheduleRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("오늘 시간표")
        self.resize(760, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.timeline_widget = TodayTimelineWidget(repository, self)
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
        for item_type, _, completed_item in completed_items:
            completed_at = (
                completed_item.completed_at.strftime("%m/%d %H:%M")
                if completed_item.completed_at
                else "완료 시각 없음"
            )
            if item_type == "task":
                due = completed_item.due_at.strftime("%m/%d %H:%M") if completed_item.due_at else "마감 없음"
                text = f"{completed_at}  [할 일] {completed_item.title} · {completed_item.duration_minutes}분 · {due}"
            else:
                text = (
                    f"{completed_at}  [일정] {completed_item.title} · "
                    f"{completed_item.start_at:%m/%d %H:%M}-{completed_item.end_at:%H:%M}"
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
        self.resize(420, 210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel(f"{selected_date:%Y년 %m월 %d일} {item_label} 추가")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(f"추가할 {item_label}")
        _stabilize_control(self.title_edit, 260)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
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
        self.quick_note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_note_list.customContextMenuRequested.connect(self.show_quick_note_context_menu)
        detail_column.addWidget(self.quick_note_list, 1)

        detail_panel.setLayout(detail_column)
        content.addWidget(detail_panel)

        self.timeline_widget = TodayTimelineWidget(self.repository, self, title_text="선택 날짜 시간표")
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
        schedule_items = _schedule_items_for_date(self.repository, selected_date, start_at, end_at)
        record_items = _record_items_for_date(self.repository, selected_date, start_at, end_at)
        quick_note_items = _quick_note_items_for_date(self.repository, start_at, end_at)

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
        if not index.isValid() or index.row() <= 0 or index.column() <= 0:
            return None

        year = self.calendar.yearShown()
        month = self.calendar.monthShown()
        first_day = QDate(year, month, 1)
        first_weekday = _qt_day_value(self.calendar.firstDayOfWeek())
        offset = (first_day.dayOfWeek() - first_weekday) % 7
        first_visible_day = first_day.addDays(-offset)
        clicked_day = first_visible_day.addDays((index.row() - 1) * 7 + (index.column() - 1))
        return _date_from_qdate(clicked_day)

    def show_date_item_dialog(self, item_type: str, selected_date: date) -> None:
        dialog = DateItemDialog(selected_date, item_type, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.save_selected_date_item(
            item_type,
            dialog.item_title(),
            dialog.selected_time(),
            dialog.duration_minutes(),
            selected_date,
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
        self.resize(440, 290)

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

        self.show_pomodoro_check = QCheckBox("표시")
        self.show_pomodoro_check.setChecked(preferences.show_pomodoro_controls)
        form.addRow("뽀모도로", self.show_pomodoro_check)

        self.show_today_timeline_inline_check = QCheckBox("메인 화면에 표시")
        self.show_today_timeline_inline_check.setChecked(preferences.show_today_timeline_inline)
        form.addRow("오늘 시간표", self.show_today_timeline_inline_check)

        self.show_today_checklist_inline_check = QCheckBox("메인 화면에 표시")
        self.show_today_checklist_inline_check.setChecked(preferences.show_today_checklist_inline)
        form.addRow("오늘 체크리스트", self.show_today_checklist_inline_check)

        self.show_today_flow_panel_check = QCheckBox("메인 화면에 표시")
        self.show_today_flow_panel_check.setChecked(preferences.show_today_flow_panel)
        form.addRow("오늘 흐름", self.show_today_flow_panel_check)

        self.show_quick_memo_panel_check = QCheckBox("메인 화면에 표시")
        self.show_quick_memo_panel_check.setChecked(preferences.show_quick_memo_panel)
        form.addRow("빠른 메모", self.show_quick_memo_panel_check)
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

        self._source = preferences

    def preferences(self) -> Preference:
        return Preference(
            day_max_minutes=self._source.day_max_minutes,
            break_minutes=self._source.break_minutes,
            strategy=self._source.strategy,
            week_start_day=int(self.week_start_combo.currentData()),
            show_pomodoro_controls=self.show_pomodoro_check.isChecked(),
            show_today_timeline_inline=self.show_today_timeline_inline_check.isChecked(),
            show_today_checklist_inline=self.show_today_checklist_inline_check.isChecked(),
            show_today_flow_panel=self.show_today_flow_panel_check.isChecked(),
            show_quick_memo_panel=self.show_quick_memo_panel_check.isChecked(),
            id=self._source.id,
        )


def _schedule_items_for_date(
    repository: ScheduleRepository,
    selected_date: date,
    start_at: datetime,
    end_at: datetime,
) -> list[tuple[datetime, str, dict[str, object]]]:
    items: list[tuple[datetime, str, dict[str, object]]] = []

    for event in repository.list_events(start_at, end_at, include_completed=True):
        status = " · 완료" if event.completed else ""
        items.append(
            (
                event.start_at,
                f"{event.start_at:%H:%M}-{event.end_at:%H:%M}  [일정] {event.title}{status}",
                {"type": "event", "id": event.id, "kind": "일정", "title": event.title},
            )
        )

    for task in repository.list_tasks(include_completed=True):
        if not _task_belongs_to_date(task, selected_date):
            continue
        reference_at = task.due_at or task.created_at
        time_label = task.due_at.strftime("%H:%M") if task.due_at and task.due_at.date() == selected_date else "시간 없음"
        status = "완료" if task.completed else "진행 중"
        items.append(
            (
                reference_at,
                f"{time_label}  [할 일] {task.title} · {task.duration_minutes}분 · {status}",
                {"type": "task", "id": task.id, "kind": "할 일", "title": task.title},
            )
        )

    return sorted(items, key=lambda item: item[0])


def _record_items_for_date(
    repository: ScheduleRepository,
    selected_date: date,
    start_at: datetime,
    end_at: datetime,
) -> list[tuple[datetime, str, dict[str, object]]]:
    items: list[tuple[datetime, str, dict[str, object]]] = []

    for session in repository.list_focus_sessions(start_at, end_at):
        reference_at = session.started_at or session.ended_at or start_at
        items.append(
            (
                reference_at,
                f"{_focus_session_time_label(session)}  [집중] {session.title} · "
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
                f"{task.completed_at:%H:%M}  [완료] 할 일 · {task.title}",
                {"type": "task", "id": task.id, "kind": "할 일", "title": task.title},
            )
        )

    for event in repository.list_completed_events():
        if event.completed_at is None or event.completed_at.date() != selected_date:
            continue
        items.append(
            (
                event.completed_at,
                f"{event.completed_at:%H:%M}  [완료] 일정 · {event.title}",
                {"type": "event", "id": event.id, "kind": "일정", "title": event.title},
            )
        )

    return sorted(items, key=lambda item: item[0], reverse=True)


def _today_timeline_items(
    repository: ScheduleRepository,
    selected_date: date,
) -> list[tuple[datetime | None, str, str]]:
    start_at, end_at = _day_window(selected_date)
    items: list[tuple[datetime | None, str, str]] = []
    listed_task_ids: set[int] = set()
    listed_event_ids: set[int] = set()

    for event in repository.list_events(start_at, end_at, include_completed=True):
        if event.id is not None:
            listed_event_ids.add(event.id)
        status = _completion_suffix(event.completed, event.completed_at, selected_date)
        items.append(
            (
                event.start_at,
                f"{event.start_at:%H:%M}-{event.end_at:%H:%M}  일정  {event.title}{status}",
                "completed" if event.completed else "schedule",
            )
        )

    for task in repository.list_tasks(include_completed=True):
        due_today = task.due_at is not None and task.due_at.date() == selected_date
        completed_today = task.completed_at is not None and task.completed_at.date() == selected_date
        created_today = task.created_at.date() == selected_date
        if not due_today and not completed_today and not created_today:
            continue

        if task.id is not None:
            listed_task_ids.add(task.id)
        reference_at = task.due_at if due_today else task.completed_at if completed_today else None
        time_label = task.due_at.strftime("%H:%M") if due_today and task.due_at else "시간 없음"
        if not due_today and completed_today and task.completed_at:
            time_label = f"완료 {task.completed_at:%H:%M}"
        status = _task_status_label(task, selected_date)
        items.append(
            (
                reference_at,
                f"{time_label}  할 일  {task.title} · {task.duration_minutes}분 · {status}",
                "completed" if task.completed else "task",
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
                f"완료 {task.completed_at:%H:%M}  할 일  {task.title} · {task.duration_minutes}분",
                "completed",
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
                f"완료 {event.completed_at:%H:%M}  일정  {event.title}",
                "completed",
            )
        )

    for session in repository.list_focus_sessions(start_at, end_at):
        reference_at = session.started_at or session.ended_at
        items.append(
            (
                reference_at,
                f"{_focus_session_time_label(session)}  집중  {session.title} · "
                f"집중 {_format_duration(session.focused_seconds)} · {_status_label(session.status)}",
                "focus",
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
) -> None:
    day_start = datetime.combine(selected_date, time.min)
    table.clearContents()
    for row in range(24):
        hour_item = QTableWidgetItem(f"{row:02d}:00")
        hour_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        hour_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        hour_item.setBackground(QColor("#f3f6f4"))
        table.setItem(row, 0, hour_item)
        for column in range(1, 7):
            item = QTableWidgetItem("")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip(f"{row:02d}:{(column - 1) * 10:02d}")
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
            item.setToolTip(tooltip + f"\n{started_at:%H:%M}-{ended_at:%H:%M} {label}")
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
    items: list[tuple[datetime | None, str, str]],
) -> None:
    list_widget.clear()
    if not items:
        empty = QListWidgetItem("오늘 표시할 일정이나 완료 기록이 없습니다.")
        empty.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(empty)
        return

    current_group = ""
    for reference_at, text, _category in items:
        group = _timeline_group_label(reference_at)
        if group != current_group:
            header = QListWidgetItem(group)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header)
            current_group = group
        list_widget.addItem(QListWidgetItem(text))
    list_widget.clearSelection()
    list_widget.setCurrentRow(-1)


def _timeline_sort_key(item: tuple[datetime | None, str, str]) -> tuple[int, datetime, str]:
    reference_at, text, _category = item
    return (1 if reference_at is None else 0, reference_at or datetime.max, text.casefold())


def _timeline_group_label(reference_at: datetime | None) -> str:
    if reference_at is None:
        return "시간 없음"
    return reference_at.strftime("%H:00")


def _completion_suffix(completed: bool, completed_at: datetime | None, selected_date: date) -> str:
    if not completed:
        return " · 예정"
    if completed_at is not None and completed_at.date() == selected_date:
        return f" · 완료 {completed_at:%H:%M}"
    return " · 완료"


def _task_status_label(task: Task, selected_date: date) -> str:
    if not task.completed:
        return "진행 중"
    if task.completed_at is not None and task.completed_at.date() == selected_date:
        return f"완료 {task.completed_at:%H:%M}"
    return "완료"


def _quick_note_items_for_date(
    repository: ScheduleRepository,
    start_at: datetime,
    end_at: datetime,
) -> list[tuple[datetime, str, dict[str, object]]]:
    items: list[tuple[datetime, str, dict[str, object]]] = []
    for note in repository.list_quick_notes(start_at, end_at):
        body = _shorten(" ".join(note.body.split()), 96)
        items.append(
            (
                note.created_at,
                f"{note.created_at:%H:%M}  {body}",
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


def _focus_session_time_label(session: FocusSession, include_date: bool = False) -> str:
    started = _format_session_time(session.started_at, include_date=include_date)
    ended = _format_session_time(
        session.ended_at,
        include_date=include_date and _needs_end_date(session.started_at, session.ended_at),
        fallback="진행 중",
    )
    return f"시작 {started} · 완료 {ended}"


def _format_session_time(value: datetime | None, include_date: bool = False, fallback: str = "-") -> str:
    if value is None:
        return fallback
    return value.strftime("%m/%d %H:%M" if include_date else "%H:%M")


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
