from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QDate, QDateTime, QSize, Qt, QTime
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.models import AvailabilityRule, Event, Preference, Task
from app.services.scheduler import Scheduler, week_start_for
from app.storage.database import ScheduleRepository


WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
ROW_INTERVAL_MINUTES = 30
ROW_COUNT = 24 * 60 // ROW_INTERVAL_MINUTES


class MainWindow(QMainWindow):
    def __init__(self, repository: ScheduleRepository) -> None:
        super().__init__()
        self.repository = repository
        self.scheduler = Scheduler()
        self.week_start = week_start_for(date.today())
        self.selected_task_id: int | None = None
        self.selected_event_id: int | None = None
        self.cell_event_ids: dict[tuple[int, int], list[int]] = {}
        self._loading = False

        self.setWindowTitle("Schedule Helper")
        self.setMinimumSize(QSize(1120, 720))
        self.setStatusBar(QStatusBar(self))
        self._build_ui()
        self._apply_style()
        self.refresh_all()

    def _build_ui(self) -> None:
        self._build_toolbar()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_task_panel())
        splitter.addWidget(self._build_calendar_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setSizes([320, 620, 340])
        self.setCentralWidget(splitter)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        previous_button = QPushButton("이전 주")
        previous_button.clicked.connect(self.previous_week)
        toolbar.addWidget(previous_button)

        today_button = QPushButton("오늘")
        today_button.clicked.connect(self.go_today)
        toolbar.addWidget(today_button)

        next_button = QPushButton("다음 주")
        next_button.clicked.connect(self.next_week)
        toolbar.addWidget(next_button)

        toolbar.addSeparator()

        schedule_button = QPushButton("자동 배치")
        schedule_button.clicked.connect(self.run_scheduler)
        toolbar.addWidget(schedule_button)

        sample_button = QPushButton("샘플 데이터")
        sample_button.clicked.connect(self.create_sample_data)
        toolbar.addWidget(sample_button)

    def _build_task_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 10, 14)
        layout.setSpacing(12)

        form_group = QGroupBox("작업")
        form = QFormLayout(form_group)

        self.task_title_edit = QLineEdit()
        self.task_title_edit.setPlaceholderText("예: 보고서 초안")
        form.addRow("이름", self.task_title_edit)

        self.task_duration_spin = QSpinBox()
        self.task_duration_spin.setRange(15, 720)
        self.task_duration_spin.setSingleStep(15)
        self.task_duration_spin.setValue(60)
        self.task_duration_spin.setSuffix("분")
        form.addRow("소요", self.task_duration_spin)

        due_box = QWidget()
        due_layout = QHBoxLayout(due_box)
        due_layout.setContentsMargins(0, 0, 0, 0)
        self.task_due_check = QCheckBox()
        self.task_due_edit = QDateTimeEdit()
        self.task_due_edit.setCalendarPopup(True)
        self.task_due_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.task_due_edit.setDateTime(_to_qdatetime(datetime.now() + timedelta(days=1)))
        due_layout.addWidget(self.task_due_check)
        due_layout.addWidget(self.task_due_edit, 1)
        form.addRow("마감", due_box)

        self.task_priority_spin = QSpinBox()
        self.task_priority_spin.setRange(1, 5)
        self.task_priority_spin.setValue(3)
        form.addRow("우선순위", self.task_priority_spin)

        self.task_category_edit = QLineEdit()
        self.task_category_edit.setPlaceholderText("예: 업무")
        form.addRow("카테고리", self.task_category_edit)

        button_row = QHBoxLayout()
        new_button = QPushButton("새 작업")
        new_button.clicked.connect(self.clear_task_form)
        save_button = QPushButton("작업 저장")
        save_button.clicked.connect(self.save_task)
        complete_button = QPushButton("완료 전환")
        complete_button.clicked.connect(self.toggle_selected_task_completed)
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(self.delete_selected_task)
        button_row.addWidget(new_button)
        button_row.addWidget(save_button)
        button_row.addWidget(complete_button)
        button_row.addWidget(delete_button)
        form.addRow(button_row)
        layout.addWidget(form_group)

        self.task_table = QTableWidget(0, 5)
        self.task_table.setHorizontalHeaderLabels(["상태", "작업", "마감", "분", "우선"])
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.itemSelectionChanged.connect(self.on_task_selection_changed)
        layout.addWidget(self.task_table, 1)

        return panel

    def _build_calendar_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(10)

        self.week_label = QLabel()
        self.week_label.setObjectName("weekLabel")
        layout.addWidget(self.week_label)

        self.calendar_table = QTableWidget(ROW_COUNT, 7)
        self.calendar_table.setVerticalHeaderLabels(_time_row_labels())
        self.calendar_table.verticalHeader().setDefaultSectionSize(34)
        self.calendar_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calendar_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.calendar_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.calendar_table.cellClicked.connect(self.on_calendar_cell_clicked)
        layout.addWidget(self.calendar_table, 1)

        return panel

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 14, 14, 14)

        tabs = QTabWidget()
        tabs.addTab(self._build_event_tab(), "일정")
        tabs.addTab(self._build_availability_tab(), "시간")
        layout.addWidget(tabs)
        return panel

    def _build_event_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        form_group = QGroupBox("일정 편집")
        form = QFormLayout(form_group)

        self.event_title_edit = QLineEdit()
        self.event_title_edit.setPlaceholderText("예: 회의")
        form.addRow("제목", self.event_title_edit)

        self.event_start_edit = QDateTimeEdit()
        self.event_start_edit.setCalendarPopup(True)
        self.event_start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("시작", self.event_start_edit)

        self.event_end_edit = QDateTimeEdit()
        self.event_end_edit.setCalendarPopup(True)
        self.event_end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("종료", self.event_end_edit)

        self.event_fixed_check = QCheckBox("고정 일정")
        form.addRow("", self.event_fixed_check)

        self.event_category_edit = QLineEdit()
        self.event_category_edit.setPlaceholderText("예: 개인")
        form.addRow("카테고리", self.event_category_edit)

        button_row = QHBoxLayout()
        new_button = QPushButton("새 일정")
        new_button.clicked.connect(self.clear_event_form)
        save_button = QPushButton("일정 저장")
        save_button.clicked.connect(self.save_event)
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(self.delete_selected_event)
        button_row.addWidget(new_button)
        button_row.addWidget(save_button)
        button_row.addWidget(delete_button)
        form.addRow(button_row)

        layout.addWidget(form_group)

        info = QLabel("선택한 칸에 고정 일정을 만들거나, 자동 배치된 일정을 조정할 수 있습니다.")
        info.setWordWrap(True)
        info.setObjectName("mutedLabel")
        layout.addWidget(info)
        layout.addStretch(1)
        return panel

    def _build_availability_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        self.availability_table = QTableWidget(0, 3)
        self.availability_table.setHorizontalHeaderLabels(["요일", "시작", "종료"])
        self.availability_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.availability_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.availability_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.availability_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.availability_table, 1)

        form_group = QGroupBox("사용 가능 시간")
        form = QFormLayout(form_group)

        self.availability_day_combo = QComboBox()
        for index, label in enumerate(WEEKDAY_LABELS):
            self.availability_day_combo.addItem(label, index)
        form.addRow("요일", self.availability_day_combo)

        self.availability_start_edit = QTimeEdit()
        self.availability_start_edit.setDisplayFormat("HH:mm")
        self.availability_start_edit.setTime(QTime(9, 0))
        form.addRow("시작", self.availability_start_edit)

        self.availability_end_edit = QTimeEdit()
        self.availability_end_edit.setDisplayFormat("HH:mm")
        self.availability_end_edit.setTime(QTime(17, 0))
        form.addRow("종료", self.availability_end_edit)

        row = QHBoxLayout()
        add_button = QPushButton("추가")
        add_button.clicked.connect(self.add_availability_rule)
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(self.delete_selected_availability_rule)
        reset_button = QPushButton("기본값")
        reset_button.clicked.connect(self.reset_availability)
        row.addWidget(add_button)
        row.addWidget(delete_button)
        row.addWidget(reset_button)
        form.addRow(row)
        layout.addWidget(form_group)

        settings_group = QGroupBox("자동 배치")
        settings_form = QFormLayout(settings_group)
        self.day_max_spin = QSpinBox()
        self.day_max_spin.setRange(30, 960)
        self.day_max_spin.setSingleStep(30)
        self.day_max_spin.setSuffix("분")
        settings_form.addRow("하루 최대", self.day_max_spin)

        self.break_spin = QSpinBox()
        self.break_spin.setRange(0, 120)
        self.break_spin.setSingleStep(5)
        self.break_spin.setSuffix("분")
        settings_form.addRow("휴식", self.break_spin)

        save_button = QPushButton("설정 저장")
        save_button.clicked.connect(self.save_preferences)
        settings_form.addRow(save_button)
        layout.addWidget(settings_group)

        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f6f7f8;
            }
            QGroupBox {
                border: 1px solid #d7dce1;
                border-radius: 6px;
                margin-top: 10px;
                padding: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                border: 1px solid #b9c2cc;
                border-radius: 5px;
                background: #ffffff;
                padding: 6px 8px;
            }
            QPushButton:hover {
                background: #eef3f6;
            }
            QLineEdit, QSpinBox, QDateTimeEdit, QTimeEdit, QComboBox {
                border: 1px solid #c9d0d7;
                border-radius: 4px;
                padding: 4px;
                background: #ffffff;
            }
            QTableWidget {
                background: #ffffff;
                gridline-color: #e0e5e9;
                selection-background-color: #cfe3f5;
                selection-color: #17212b;
            }
            QLabel#weekLabel {
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#mutedLabel {
                color: #5c6670;
            }
            """
        )

    def refresh_all(self) -> None:
        self._loading = True
        try:
            self.refresh_tasks()
            self.refresh_calendar()
            self.refresh_availability()
            self.refresh_preferences()
        finally:
            self._loading = False

    def refresh_tasks(self) -> None:
        tasks = self.repository.list_tasks(include_completed=True)
        self.task_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            status = "완료" if task.completed else "대기"
            due = task.due_at.strftime("%m-%d %H:%M") if task.due_at else "-"
            values = [status, task.title, due, str(task.duration_minutes), str(task.priority)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, task.id)
                if column in (0, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if task.completed:
                    item.setForeground(QBrush(QColor("#7a828a")))
                self.task_table.setItem(row, column, item)

    def refresh_calendar(self) -> None:
        start_at, end_at = self.week_window()
        self.cell_event_ids.clear()
        self.calendar_table.clearContents()
        self.calendar_table.setHorizontalHeaderLabels(self._calendar_headers())
        self.week_label.setText(f"{start_at:%Y-%m-%d} - {(end_at - timedelta(days=1)):%Y-%m-%d}")

        for event in self.repository.list_events(start_at, end_at):
            self._paint_event(event)

    def refresh_availability(self) -> None:
        rules = self.repository.list_availability_rules()
        self.availability_table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            values = [
                WEEKDAY_LABELS[rule.weekday],
                rule.start_time.strftime("%H:%M"),
                rule.end_time.strftime("%H:%M"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, rule.id)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.availability_table.setItem(row, column, item)

    def refresh_preferences(self) -> None:
        preferences = self.repository.get_preferences()
        self.day_max_spin.setValue(preferences.day_max_minutes)
        self.break_spin.setValue(preferences.break_minutes)

    def week_window(self) -> tuple[datetime, datetime]:
        start_at = datetime.combine(self.week_start, time.min)
        return start_at, start_at + timedelta(days=7)

    def previous_week(self) -> None:
        self.week_start -= timedelta(days=7)
        self.refresh_calendar()

    def next_week(self) -> None:
        self.week_start += timedelta(days=7)
        self.refresh_calendar()

    def go_today(self) -> None:
        self.week_start = week_start_for(date.today())
        self.refresh_calendar()

    def save_task(self) -> None:
        title = self.task_title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "작업 저장", "작업 이름을 입력하세요.")
            return

        due_at = _from_qdatetime(self.task_due_edit.dateTime()) if self.task_due_check.isChecked() else None
        existing = self.repository.get_task(self.selected_task_id) if self.selected_task_id else None
        task = existing or Task(title=title, duration_minutes=self.task_duration_spin.value())
        task.title = title
        task.duration_minutes = self.task_duration_spin.value()
        task.due_at = due_at
        task.priority = self.task_priority_spin.value()
        task.category = self.task_category_edit.text().strip()
        self.repository.save_task(task)
        self.selected_task_id = task.id
        self.refresh_tasks()
        self.statusBar().showMessage("작업을 저장했습니다.", 3500)

    def clear_task_form(self) -> None:
        self.selected_task_id = None
        self.task_table.clearSelection()
        self.task_title_edit.clear()
        self.task_duration_spin.setValue(60)
        self.task_due_check.setChecked(False)
        self.task_due_edit.setDateTime(_to_qdatetime(datetime.now() + timedelta(days=1)))
        self.task_priority_spin.setValue(3)
        self.task_category_edit.clear()

    def on_task_selection_changed(self) -> None:
        if self._loading:
            return
        task_id = self._selected_id(self.task_table)
        if task_id is None:
            return
        task = self.repository.get_task(task_id)
        if not task:
            return
        self.selected_task_id = task.id
        self.task_title_edit.setText(task.title)
        self.task_duration_spin.setValue(task.duration_minutes)
        self.task_due_check.setChecked(task.due_at is not None)
        if task.due_at:
            self.task_due_edit.setDateTime(_to_qdatetime(task.due_at))
        self.task_priority_spin.setValue(task.priority)
        self.task_category_edit.setText(task.category)

    def toggle_selected_task_completed(self) -> None:
        task_id = self._selected_id(self.task_table) or self.selected_task_id
        if task_id is None:
            QMessageBox.information(self, "완료 전환", "작업을 선택하세요.")
            return
        task = self.repository.get_task(task_id)
        if not task:
            return
        self.repository.mark_task_completed(task_id, not task.completed)
        self.refresh_tasks()
        self.statusBar().showMessage("작업 상태를 변경했습니다.", 3500)

    def delete_selected_task(self) -> None:
        task_id = self._selected_id(self.task_table) or self.selected_task_id
        if task_id is None:
            QMessageBox.information(self, "작업 삭제", "작업을 선택하세요.")
            return
        if QMessageBox.question(self, "작업 삭제", "선택한 작업을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_task(task_id)
        self.clear_task_form()
        self.refresh_all()

    def on_calendar_cell_clicked(self, row: int, column: int) -> None:
        event_ids = self.cell_event_ids.get((row, column), [])
        if event_ids:
            event = self.repository.get_event(event_ids[0])
            if event:
                self.load_event_form(event)
            return

        start_at = datetime.combine(self.week_start + timedelta(days=column), time.min)
        start_at += timedelta(minutes=row * ROW_INTERVAL_MINUTES)
        self.clear_event_form(start_at)

    def clear_event_form(self, start_at: datetime | None = None) -> None:
        self.selected_event_id = None
        start_at = start_at or datetime.now().replace(second=0, microsecond=0)
        minute = 30 if start_at.minute >= 30 else 0
        start_at = start_at.replace(minute=minute)
        end_at = start_at + timedelta(hours=1)
        self.event_title_edit.clear()
        self.event_start_edit.setDateTime(_to_qdatetime(start_at))
        self.event_end_edit.setDateTime(_to_qdatetime(end_at))
        self.event_fixed_check.setChecked(True)
        self.event_category_edit.clear()

    def load_event_form(self, event: Event) -> None:
        self.selected_event_id = event.id
        self.event_title_edit.setText(event.title)
        self.event_start_edit.setDateTime(_to_qdatetime(event.start_at))
        self.event_end_edit.setDateTime(_to_qdatetime(event.end_at))
        self.event_fixed_check.setChecked(event.fixed)
        self.event_category_edit.setText(event.category)
        self.statusBar().showMessage("일정을 선택했습니다.", 2500)

    def save_event(self) -> None:
        title = self.event_title_edit.text().strip() or "일정"
        start_at = _from_qdatetime(self.event_start_edit.dateTime())
        end_at = _from_qdatetime(self.event_end_edit.dateTime())
        if end_at <= start_at:
            QMessageBox.warning(self, "일정 저장", "종료 시각은 시작 시각보다 늦어야 합니다.")
            return

        existing = self.repository.get_event(self.selected_event_id) if self.selected_event_id else None
        if self._has_conflict(start_at, end_at, self.selected_event_id):
            answer = QMessageBox.question(
                self,
                "충돌 경고",
                "겹치는 일정이 있습니다. 그래도 저장할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        event = existing or Event(title=title, start_at=start_at, end_at=end_at)
        event.title = title
        event.start_at = start_at
        event.end_at = end_at
        event.fixed = self.event_fixed_check.isChecked()
        event.category = self.event_category_edit.text().strip()
        self.repository.save_event(event)
        self.selected_event_id = event.id
        self.refresh_calendar()
        self.statusBar().showMessage("일정을 저장했습니다.", 3500)

    def delete_selected_event(self) -> None:
        if self.selected_event_id is None:
            QMessageBox.information(self, "일정 삭제", "일정을 선택하세요.")
            return
        if QMessageBox.question(self, "일정 삭제", "선택한 일정을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_event(self.selected_event_id)
        self.clear_event_form()
        self.refresh_calendar()

    def add_availability_rule(self) -> None:
        start_time = _from_qtime(self.availability_start_edit.time())
        end_time = _from_qtime(self.availability_end_edit.time())
        if end_time <= start_time:
            QMessageBox.warning(self, "사용 가능 시간", "종료 시각은 시작 시각보다 늦어야 합니다.")
            return

        rule = AvailabilityRule(
            weekday=int(self.availability_day_combo.currentData()),
            start_time=start_time,
            end_time=end_time,
        )
        self.repository.save_availability_rule(rule)
        self.refresh_availability()
        self.statusBar().showMessage("사용 가능 시간을 추가했습니다.", 3500)

    def delete_selected_availability_rule(self) -> None:
        rule_id = self._selected_id(self.availability_table)
        if rule_id is None:
            QMessageBox.information(self, "사용 가능 시간", "삭제할 행을 선택하세요.")
            return
        self.repository.delete_availability_rule(rule_id)
        self.refresh_availability()

    def reset_availability(self) -> None:
        self.repository.reset_default_availability()
        self.refresh_availability()
        self.statusBar().showMessage("기본 사용 가능 시간으로 되돌렸습니다.", 3500)

    def save_preferences(self) -> None:
        self.repository.save_preferences(
            Preference(
                day_max_minutes=self.day_max_spin.value(),
                break_minutes=self.break_spin.value(),
            )
        )
        self.statusBar().showMessage("자동 배치 설정을 저장했습니다.", 3500)

    def run_scheduler(self) -> None:
        start_at, end_at = self.week_window()
        self.repository.delete_generated_events_between(start_at, end_at)
        tasks = self.repository.list_tasks(include_completed=False)
        fixed_events = [event for event in self.repository.list_events(start_at, end_at) if event.fixed]
        rules = self.repository.list_availability_rules()
        preferences = self.repository.get_preferences()
        result = self.scheduler.schedule(tasks, fixed_events, rules, preferences, start_at, end_at)
        for event in result.events:
            self.repository.save_event(event)

        self.refresh_calendar()
        if result.failures:
            lines = [f"- {failure.task.title}: {failure.reason}" for failure in result.failures[:8]]
            extra = "" if len(result.failures) <= 8 else f"\n외 {len(result.failures) - 8}개"
            QMessageBox.information(
                self,
                "자동 배치",
                f"{len(result.events)}개 일정을 만들었습니다.\n\n미배치 작업:\n" + "\n".join(lines) + extra,
            )
        else:
            QMessageBox.information(self, "자동 배치", f"{len(result.events)}개 일정을 만들었습니다.")

    def create_sample_data(self) -> None:
        if self.repository.list_tasks(include_completed=True) or self.repository.list_events():
            answer = QMessageBox.question(
                self,
                "샘플 데이터",
                "현재 데이터가 있습니다. 샘플 작업과 일정을 추가할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        now = datetime.now().replace(second=0, microsecond=0)
        monday = week_start_for(now.date())
        samples = [
            Task("주간 계획 정리", 60, datetime.combine(monday + timedelta(days=0), time(18, 0)), 5, "업무"),
            Task("보고서 초안", 120, datetime.combine(monday + timedelta(days=2), time(17, 0)), 4, "업무"),
            Task("운동", 45, datetime.combine(monday + timedelta(days=4), time(20, 0)), 3, "개인"),
            Task("자료 읽기", 90, None, 2, "학습"),
        ]
        for task in samples:
            self.repository.save_task(task)

        self.repository.save_event(
            Event(
                "팀 회의",
                datetime.combine(monday + timedelta(days=1), time(10, 0)),
                datetime.combine(monday + timedelta(days=1), time(11, 0)),
                fixed=True,
                category="업무",
            )
        )
        self.refresh_all()
        self.statusBar().showMessage("샘플 데이터를 추가했습니다.", 3500)

    def _paint_event(self, event: Event) -> None:
        start_at, end_at = self.week_window()
        visible_start = max(event.start_at, start_at)
        visible_end = min(event.end_at, end_at)
        cursor = _floor_to_interval(visible_start, ROW_INTERVAL_MINUTES)
        color = QColor("#d9eaf8") if event.fixed else QColor("#dff0df")

        while cursor < visible_end:
            day_offset = (cursor.date() - self.week_start).days
            row = cursor.hour * 2 + (1 if cursor.minute >= 30 else 0)
            if 0 <= day_offset < 7 and 0 <= row < ROW_COUNT:
                item = self.calendar_table.item(row, day_offset)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                    self.calendar_table.setItem(row, day_offset, item)
                label = f"{event.start_at:%H:%M} {event.title}" if cursor <= event.start_at else f"  {event.title}"
                item.setText(label if not item.text() else item.text() + "\n" + label)
                item.setBackground(QBrush(color))
                item.setData(Qt.ItemDataRole.UserRole, event.id)
                if event.id is not None:
                    self.cell_event_ids.setdefault((row, day_offset), []).append(event.id)
            cursor += timedelta(minutes=ROW_INTERVAL_MINUTES)

    def _has_conflict(self, start_at: datetime, end_at: datetime, ignored_event_id: int | None) -> bool:
        for event in self.repository.list_events(start_at, end_at):
            if ignored_event_id is not None and event.id == ignored_event_id:
                continue
            return True
        return False

    def _calendar_headers(self) -> list[str]:
        return [
            f"{WEEKDAY_LABELS[index]}\n{(self.week_start + timedelta(days=index)):%m/%d}"
            for index in range(7)
        ]

    @staticmethod
    def _selected_id(table: QTableWidget) -> int | None:
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None


def _to_qdatetime(value: datetime) -> QDateTime:
    return QDateTime(
        QDate(value.year, value.month, value.day),
        QTime(value.hour, value.minute, value.second),
    )


def _from_qdatetime(value: QDateTime) -> datetime:
    qdate = value.date()
    qtime = value.time()
    return datetime(
        qdate.year(),
        qdate.month(),
        qdate.day(),
        qtime.hour(),
        qtime.minute(),
        qtime.second(),
    )


def _from_qtime(value: QTime) -> time:
    return time(value.hour(), value.minute(), value.second())


def _time_row_labels() -> list[str]:
    labels = []
    current = datetime.combine(date.today(), time.min)
    for _ in range(ROW_COUNT):
        labels.append(current.strftime("%H:%M"))
        current += timedelta(minutes=ROW_INTERVAL_MINUTES)
    return labels


def _floor_to_interval(value: datetime, interval_minutes: int) -> datetime:
    total_minutes = value.hour * 60 + value.minute
    floored = total_minutes - (total_minutes % interval_minutes)
    return value.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)

