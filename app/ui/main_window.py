from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QDate, QPoint, QSize, Qt, QTime, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
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
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import Event, Preference, QuickNote, Task
from app.services.app_usage import WindowsActiveWindowProvider
from app.services.focus_timer import FocusTimerService
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
        self.next_pomodoro_mark_seconds = 0
        self.break_until: datetime | None = None
        self.preferences = self.repository.get_preferences()

        self.setWindowTitle("Schedule Helper")
        self.setMinimumSize(QSize(430, 320))
        self.setStatusBar(QStatusBar(self))
        self._initialize_focus_timer()
        self._build_ui()
        self._apply_style()
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
        page.setMinimumWidth(1120)
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

        settings_button = QPushButton("설정")
        _stabilize_control(settings_button, 78)
        settings_button.clicked.connect(self.show_settings_window)
        top_row.addWidget(settings_button)

        self.compact_button = QPushButton("위젯 모드")
        _stabilize_control(self.compact_button, 94)
        self.compact_button.clicked.connect(lambda: self.set_compact_mode(True))
        top_row.addWidget(self.compact_button)
        layout.addLayout(top_row)

        layout.addWidget(self._build_focus_panel())

        lower_row = QHBoxLayout()
        lower_row.setSpacing(16)
        lower_row.addWidget(self._build_today_panel(), 1)
        lower_row.addWidget(self._build_memo_panel(), 1)
        lower_row.addWidget(self._build_date_review_panel(), 1)
        layout.addLayout(lower_row, 1)

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
        self.target_refresh_button = QPushButton("목록 갱신")
        _stabilize_control(self.target_refresh_button, 110)
        self.target_refresh_button.clicked.connect(self.refresh_targets)
        form.addWidget(QLabel("화면"), 1, 0)
        form.addWidget(self.target_combo, 1, 1, 1, 2)
        form.addWidget(self.target_refresh_button, 1, 3)

        self.planned_minutes_spin = QSpinBox()
        self.planned_minutes_spin.setRange(1, 240)
        self.planned_minutes_spin.setValue(25)
        self.planned_minutes_spin.setSuffix("분")
        _stabilize_control(self.planned_minutes_spin, 120)
        self.pomodoro_minutes_spin = QSpinBox()
        self.pomodoro_minutes_spin.setRange(5, 90)
        self.pomodoro_minutes_spin.setValue(25)
        self.pomodoro_minutes_spin.setSuffix("분")
        _stabilize_control(self.pomodoro_minutes_spin, 120)
        self.break_minutes_spin = QSpinBox()
        self.break_minutes_spin.setRange(1, 60)
        self.break_minutes_spin.setValue(5)
        self.break_minutes_spin.setSuffix("분")
        _stabilize_control(self.break_minutes_spin, 120)
        self.idle_cutoff_spin = QSpinBox()
        self.idle_cutoff_spin.setRange(10, 600)
        self.idle_cutoff_spin.setValue(60)
        self.idle_cutoff_spin.setSuffix("초")
        _stabilize_control(self.idle_cutoff_spin, 120)
        form.addWidget(QLabel("목표"), 2, 0)
        form.addWidget(self.planned_minutes_spin, 2, 1)
        form.addWidget(self.pomodoro_minutes_spin, 2, 2)
        form.addWidget(self.break_minutes_spin, 2, 3)
        form.addWidget(QLabel("자리 비움"), 3, 0)
        form.addWidget(self.idle_cutoff_spin, 3, 1)
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

    def _build_date_review_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("plainPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        heading = QLabel("날짜별 보기")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self.date_review_calendar = QCalendarWidget()
        self.date_review_calendar.setGridVisible(True)
        self.date_review_calendar.setFirstDayOfWeek(_qt_week_start_day(self.preferences.week_start_day))
        self.date_review_calendar.setSelectedDate(QDate.currentDate())
        self.date_review_calendar.selectionChanged.connect(self.refresh_date_review)
        layout.addWidget(self.date_review_calendar)

        self.date_review_label = QLabel()
        self.date_review_label.setObjectName("statusLabel")
        layout.addWidget(self.date_review_label)

        self.date_review_summary_label = QLabel()
        self.date_review_summary_label.setObjectName("mutedLabel")
        layout.addWidget(self.date_review_summary_label)

        self.date_schedule_list = QListWidget()
        self.date_schedule_list.setMaximumHeight(120)
        layout.addWidget(QLabel("일정"))
        layout.addWidget(self.date_schedule_list)

        self.date_record_list = QListWidget()
        layout.addWidget(QLabel("기록"))
        layout.addWidget(self.date_record_list, 1)
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
            QWidget#focusPanel {
                background: #ffffff;
                border: 1px solid #dfe5e2;
                border-radius: 8px;
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
        self.refresh_date_review()
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
            started = session.started_at.strftime("%m/%d %H:%M") if session.started_at else "-"
            item = QListWidgetItem(
                f"{started}  {session.title} · 집중 {_format_duration(session.focused_seconds)} · {_status_label(session.status)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self.history_list.addItem(item)

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

    def show_settings_window(self) -> None:
        dialog = SettingsDialog(self.preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.preferences = self.repository.save_preferences(dialog.preferences())
        self.apply_preferences()
        self.statusBar().showMessage("설정을 저장했습니다.", 2500)

    def apply_preferences(self) -> None:
        self.date_review_calendar.setFirstDayOfWeek(_qt_week_start_day(self.preferences.week_start_day))
        self.refresh_date_review()

    def refresh_date_review(self) -> None:
        selected_date = _date_from_qdate(self.date_review_calendar.selectedDate())
        start_at, end_at = _day_window(selected_date)
        schedule_items = _schedule_items_for_date(self.repository, selected_date, start_at, end_at)
        record_items = _record_items_for_date(self.repository, selected_date, start_at, end_at)

        self.date_review_label.setText(selected_date.strftime("%Y년 %m월 %d일"))
        self.date_review_summary_label.setText(f"일정 {len(schedule_items)}개 · 기록 {len(record_items)}개")
        _fill_list(self.date_schedule_list, [text for _, text in schedule_items], "이 날짜에 표시할 일정이 없습니다.")
        _fill_list(self.date_record_list, [text for _, text in record_items], "이 날짜에 표시할 기록이 없습니다.")

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

        target = self.target_combo.currentData()
        process_name = target["process_name"] if target else ""
        window_title = target["window_title"] if target else ""
        self.focus_timer.idle_cutoff_seconds = self.idle_cutoff_spin.value()
        self.focus_timer.start(
            title=self.focus_title_edit.text().strip() or "집중 세션",
            planned_seconds=self.planned_minutes_spin.value() * 60,
            target_process_name=process_name,
            target_window_title=window_title,
            task_id=self.selected_task_id,
        )
        self.next_pomodoro_mark_seconds = self.pomodoro_minutes_spin.value() * 60
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
        now = datetime.now()
        if session is not None and session.status == "running":
            if (
                self.next_pomodoro_mark_seconds > 0
                and session.focused_seconds >= self.next_pomodoro_mark_seconds
                and session.remaining_seconds > 0
            ):
                self.focus_timer.start_break(now)
                self.break_until = now + timedelta(minutes=self.break_minutes_spin.value())
                self.next_pomodoro_mark_seconds += self.pomodoro_minutes_spin.value() * 60
                session = self.focus_timer.session
        elif session is not None and session.status == "break":
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
            target = session.target_process_name or "지정 없음"
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
        delete_action = menu.addAction("삭제")
        delete_action.triggered.connect(self.delete_selected_quick_note)
        menu.exec(self.notes_list.mapToGlobal(position))

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


class SettingsDialog(QDialog):
    def __init__(self, preferences: Preference, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(360, 160)

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
            id=self._source.id,
        )


def _schedule_items_for_date(
    repository: ScheduleRepository,
    selected_date: date,
    start_at: datetime,
    end_at: datetime,
) -> list[tuple[datetime, str]]:
    items: list[tuple[datetime, str]] = []

    for event in repository.list_events(start_at, end_at, include_completed=True):
        status = " · 완료" if event.completed else ""
        items.append(
            (
                event.start_at,
                f"{event.start_at:%H:%M}-{event.end_at:%H:%M}  [일정] {event.title}{status}",
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
            )
        )

    return sorted(items, key=lambda item: item[0])


def _record_items_for_date(
    repository: ScheduleRepository,
    selected_date: date,
    start_at: datetime,
    end_at: datetime,
) -> list[tuple[datetime, str]]:
    items: list[tuple[datetime, str]] = []

    for session in repository.list_focus_sessions(start_at, end_at):
        reference_at = session.started_at or session.ended_at or start_at
        items.append(
            (
                reference_at,
                f"{reference_at:%H:%M}  [집중] {session.title} · 집중 {_format_duration(session.focused_seconds)} · {_status_label(session.status)}",
            )
        )

    for note in repository.list_quick_notes(start_at, end_at):
        body = _shorten(" ".join(note.body.split()), 64)
        items.append((note.created_at, f"{note.created_at:%H:%M}  [메모] {body}"))

    for task in repository.list_completed_tasks():
        if task.completed_at is None or task.completed_at.date() != selected_date:
            continue
        items.append(
            (
                task.completed_at,
                f"{task.completed_at:%H:%M}  [완료] 할 일 · {task.title}",
            )
        )

    for event in repository.list_completed_events():
        if event.completed_at is None or event.completed_at.date() != selected_date:
            continue
        items.append(
            (
                event.completed_at,
                f"{event.completed_at:%H:%M}  [완료] 일정 · {event.title}",
            )
        )

    return sorted(items, key=lambda item: item[0], reverse=True)


def _fill_list(list_widget: QListWidget, rows: list[str], empty_message: str) -> None:
    list_widget.clear()
    if not rows:
        item = QListWidgetItem(empty_message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)
        return
    for row in rows:
        list_widget.addItem(QListWidgetItem(row))


def _today_window() -> tuple[datetime, datetime]:
    return _day_window(date.today())


def _day_window(day: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(day, time.min)
    return start_at, start_at + timedelta(days=1)


def _date_from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def _qt_week_start_day(week_start_day: int) -> Qt.DayOfWeek:
    return Qt.DayOfWeek.Sunday if week_start_day == 6 else Qt.DayOfWeek.Monday


def _task_belongs_to_date(task: Task, selected_date: date) -> bool:
    if task.due_at is not None:
        return task.due_at.date() == selected_date
    if task.completed_at is not None:
        return task.completed_at.date() == selected_date
    return task.created_at.date() == selected_date


def _target_label(process_name: str, window_title: str) -> str:
    title = _shorten(window_title, 48)
    return f"{_display_name_from_process(process_name)} ({process_name})" + (f" · {title}" if title else "")


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
