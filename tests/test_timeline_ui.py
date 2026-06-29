import ctypes
import json
import os
import re
from ctypes import wintypes
from datetime import datetime, time, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTime, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QToolButton,
    QWidget,
)

from app.models import Event, FocusSession, ItemType, LayoutProfile, LinkFavorite, QuickNote, QuickNoteFolder, Task
from app.services.app_usage import ActiveWindowSnapshot
from app.storage.database import ScheduleRepository
from app.ui import main_window as main_window_module
from app.ui.quick_switch_config import QuickSwitchConfigDialog
from app.ui.main_window import (
    COMMISSION_SUMMARY_KEY,
    DASHBOARD_GRID_GAP,
    DASHBOARD_GRID_COLUMNS,
    DASHBOARD_GRID_ROW_HEIGHT,
    FLOATING_OVERLAY_FEATURE_KEYS,
    PANEL_CONTROL_HEIGHT,
    PANEL_CORNER_RADIUS,
    PANEL_HANDLE_CONTENT_GAP,
    PANEL_HEADER_HEIGHT,
    PANEL_MOVE_BAR_HEIGHT,
    WINDOW_RESIZE_MARGIN,
    WINDOW_FRAME_BORDER_COLOR,
    WINDOW_FRAME_CORNER_RADIUS,
    WEEKLY_PLAN_KEY,
    WRITING_EDITOR_KEY,
    WRITING_LIBRARY_KEY,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTCAPTION,
    HTCLIENT,
    HTLEFT,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    AppChromeBar,
    ChecklistItemEditDialog,
    CompletedAtEditDialog,
    DraggableFeatureBox,
    FavoritesSettingsDialog,
    FOCUS_STATUS_CELL_SHAPES,
    FOCUS_STATUS_EMPTY_COLOR,
    FOCUS_STATUS_MIN_ROWS,
    FOCUS_STATUS_ROW_HEIGHT,
    FocusActivitySettingsDialog,
    FocusStatusCellDelegate,
    FocusStatusGrid,
    FocusWidgetDialog,
    ItemTypeSettingsDialog,
    LayoutProfileLoadDialog,
    MainWindow,
    NoScrollFontComboBox,
    NoScrollSpinBox,
    OutlinedTextLabel,
    QuickNoteDetailDialog,
    QuickNoteFolderNotesDialog,
    QuickNoteTrashDialog,
    PinBadge,
    SettingsDialog,
    SortDirectionButton,
    TagAssignmentDialog,
    TagBadge,
    TaskFolderTasksDialog,
    TodayChecklistWidget,
    TodayTimelineWidget,
    WindowControlButton,
    WorkspaceManagerDialog,
    _hit_test_for_edges,
    _is_resize_eligible_widget,
    _resize_edges_for_point,
    _window_hit_test_result,
    _download_site_icon,
    _draw_image_viewport,
    _eyedropper_cursor,
    _fill_time_block_table,
    _focus_activity_cell_color,
    _format_time,
    _clip_media_corners,
    _record_items_for_date,
    _today_timeline_blocks,
)
from app.ui.orot_brand import OROT_RING_COLOR


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _margins_tuple(layout) -> tuple[int, int, int, int]:
    margins = layout.contentsMargins()
    return margins.left(), margins.top(), margins.right(), margins.bottom()


def _checklist_section_titles(layout, title_object_name: str) -> list[str]:
    titles: list[str] = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is None:
            continue
        title = widget.findChild(QLabel, title_object_name)
        if title is not None:
            titles.append(title.text())
    return titles


def _widget_span_in_parent(widget: QWidget, parent: QWidget) -> tuple[int, int]:
    top = widget.mapTo(parent, QPoint(0, 0)).y()
    return top, top + widget.height()


def _assert_visible_widget_within_parent(widget: QWidget, parent: QWidget) -> None:
    if not widget.isVisibleTo(parent):
        return
    top, bottom = _widget_span_in_parent(widget, parent)
    assert top >= 0
    assert bottom <= parent.height(), f"{widget.objectName() or widget.__class__.__name__} extends below parent"


def _click_light_popup_button(app: QApplication, text: str) -> None:
    popup = getattr(app, "_active_light_action_popup", None)
    assert popup is not None
    button = next(button for button in popup.findChildren(QPushButton) if button.text() == text)
    button.click()
    app.processEvents()


def _workspace_filters(show_completed: bool = True) -> dict[str, object]:
    return {
        "memo.folder_id": None,
        "memo.tag_ids": [],
        "checklist.item_type_ids": [],
        "checklist.tag_ids": [],
        "checklist.show_completed": show_completed,
    }


def _workspace_state(
    window: MainWindow,
    *,
    show_focus: bool,
    show_quick_memo: bool,
    show_completed: bool = True,
) -> dict[str, object]:
    state = window.current_layout_state()
    visible = dict(state["visible"])
    visible["focus"] = show_focus
    visible["quick_memo"] = show_quick_memo
    state["visible"] = visible
    state["filters"] = _workspace_filters(show_completed)
    return state


def _profile_data(repository: ScheduleRepository, name: str) -> str:
    profile = repository.get_layout_profile(name)
    assert profile is not None
    return profile.data


def _dashboard_support_items(start_y: int = 8, omit: set[str] | None = None) -> list[dict[str, object]]:
    omitted = omit or set()
    items = [
        {"key": "header_banner", "x": 0, "y": start_y, "w": 12, "h": 3},
        {"key": "today_timeline", "x": 0, "y": start_y + 3, "w": 5, "h": 6},
        {"key": "today_checklist", "x": 5, "y": start_y + 3, "w": 4, "h": 4},
        {"key": "pomodoro", "x": 9, "y": start_y + 3, "w": 3, "h": 4},
        {"key": "media_panel", "x": 0, "y": start_y + 9, "w": 3, "h": 4},
        {"key": "link_favorites", "x": 3, "y": start_y + 9, "w": 3, "h": 4},
        {"key": "datetime", "x": 6, "y": start_y + 9, "w": 3, "h": 1},
    ]
    return [item for item in items if str(item["key"]) not in omitted]


def test_main_window_ui_strings_do_not_contain_mojibake() -> None:
    source = Path("app/ui/main_window.py").read_text(encoding="utf-8")
    broken_tokens = (
        "硫",
        "吏",
        "諛",
        "湲",
        "蹂",
        "쨌",
        "氤",
        "旮",
        "歃",
        "凯",
        "路",
        "歆",
        "姤",
        "彀",
        "娟",
        "赴",
        "偓",
        "搓",
        "办",
        "爼",
        "半",
        "掣",
    )
    assert not [token for token in broken_tokens if token in source]
    assert 'QPushButton("날짜별 보기")' in source
    assert 'setText("재개"' in source


def test_time_block_context_uses_viewport_coordinates(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.time_format = "12h"
    repository.save_preferences(preferences)

    widget = TodayTimelineWidget(repository)
    widget.resize(900, 640)
    widget.show()
    app.processEvents()

    am_three_point = widget.block_table.visualItemRect(widget.block_table.item(3, 1)).center()
    am_three = widget._time_for_block_position(am_three_point, widget.block_table.viewport())
    assert am_three is not None
    assert am_three.time() == time(3, 0)

    table_signal_am_three = widget._time_for_block_position(am_three_point, widget.block_table)
    assert table_signal_am_three is not None
    assert table_signal_am_three.time() == time(3, 0)

    am_twelve_label_point = widget.block_table.visualItemRect(widget.block_table.item(0, 0)).center()
    am_twelve = widget._time_for_block_position(am_twelve_label_point, widget.block_table.viewport())
    assert am_twelve is not None
    assert am_twelve.time() == time(0, 0)
    assert _format_time(am_twelve, preferences) == "AM 12:00"

    assert widget._time_for_block_position(QPoint(0, -4), widget.block_table.viewport()) is None
    widget.close()


def test_time_block_context_signal_is_connected_for_table_and_viewport(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    widget.resize(900, 640)
    widget.show()
    app.processEvents()

    captured: list[tuple[QPoint, object]] = []

    def capture(position: QPoint, source=None) -> None:
        captured.append((position, source))

    widget.show_time_block_context_menu = capture
    point = widget.block_table.visualItemRect(widget.block_table.item(3, 1)).center()
    widget.block_table.customContextMenuRequested.emit(point)
    widget.block_table.viewport().customContextMenuRequested.emit(point)

    assert captured == [
        (point, widget.block_table),
        (point, widget.block_table.viewport()),
    ]
    widget.close()


def test_time_block_cells_keep_payload_for_existing_items(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    starts_at = datetime(2026, 6, 14, 10, 20)
    task = repository.save_task(Task("Review notes", 20, due_at=starts_at, created_at=starts_at))

    widget = TodayTimelineWidget(repository)
    widget.resize(900, 640)
    widget.set_date(starts_at.date())
    widget.show()
    app.processEvents()

    target_item = widget.block_table.item(10, 3)
    assert target_item is not None
    payloads = target_item.data(Qt.ItemDataRole.UserRole)
    assert isinstance(payloads, list)
    assert {
        "type": "task",
        "id": task.id,
        "title": "Review notes",
        "completed": False,
    } in payloads

    point = widget.block_table.visualItemRect(target_item).center()
    assert widget._payloads_for_block_position(point, widget.block_table.viewport()) == payloads
    widget.close()


def test_undated_completed_checklist_task_stays_out_of_timeline_grid_records_completion(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    completed_at = datetime(2026, 6, 14, 9, 30)
    task = repository.save_task(
        Task(
            "No due checklist",
            30,
            due_at=None,
            completed=True,
            completed_at=completed_at,
            created_at=completed_at - timedelta(days=1),
        )
    )

    blocks = _today_timeline_blocks(repository, completed_at.date())
    assert all(payload.get("id") != task.id for *_prefix, payload in blocks)

    start_at = datetime(2026, 6, 14)
    records = _record_items_for_date(repository, completed_at.date(), start_at, start_at + timedelta(days=1), repository.get_preferences())
    task_records = [record for record in records if record[2].get("type") == "task" and record[2].get("id") == task.id]
    assert len(task_records) == 1
    assert "06/14 09:30" in task_records[0][1]
    assert "[완료]" in task_records[0][1]
    assert task_records[0][2].get("record_kind") == "completed"


def test_timeline_deduplicates_same_focus_session_per_slot(tmp_path) -> None:
    app = _app()
    selected_date = datetime(2026, 6, 14).date()
    table = QTableWidget(24, 7)
    session_payload = {"type": "focus_session", "id": 7, "title": "Multi target focus"}
    start = datetime(2026, 6, 14, 9, 0)
    blocks = [
        (start, start + timedelta(minutes=10), "focus", "집중 Multi target focus", session_payload),
        (start, start + timedelta(minutes=10), "focus", "집중 Multi target focus", dict(session_payload)),
    ]

    _fill_time_block_table(table, selected_date, blocks)
    app.processEvents()

    item = table.item(9, 1)
    payloads = item.data(Qt.ItemDataRole.UserRole)
    assert isinstance(payloads, list)
    assert payloads == [session_payload]
    assert item.toolTip().count("Multi target focus") == 1
    assert item.background().color().name().lower() == "#b9a7e8"


def test_timeline_focus_block_without_session_color_uses_default_not_preference(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.focus_display_color = "#123456"
    selected_date = datetime(2026, 6, 14).date()
    table = QTableWidget(24, 7)
    session_payload = {"type": "focus_session", "id": 8, "title": "Colored focus"}
    start = datetime(2026, 6, 14, 9, 0)
    blocks = [
        (start, start + timedelta(minutes=10), "focus", "집중 Colored focus", session_payload),
    ]

    _fill_time_block_table(table, selected_date, blocks, preferences)
    app.processEvents()

    # Given a focus block with no saved per-session color, When the table renders, Then the cell
    # uses the default focus color, never the global focus_display_color swatch preference.
    assert table.item(9, 1).background().color().name().lower() == "#b9a7e8"


def test_timeline_focus_block_uses_session_color_over_display_color_preference(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.focus_display_color = "#123456"
    selected_date = datetime(2026, 6, 14).date()
    table = QTableWidget(24, 7)
    session_payload = {
        "type": "focus_session",
        "id": 9,
        "title": "Explicit",
        "color": "#abcdef",
    }
    start = datetime(2026, 6, 14, 9, 0)
    blocks = [
        (start, start + timedelta(minutes=10), "focus", "집중 Explicit", session_payload),
    ]

    _fill_time_block_table(table, selected_date, blocks, preferences)
    app.processEvents()

    # Given a focus payload carrying its own color, When the table renders, Then that color is
    # used directly and is not overridden by the global focus_display_color preference.
    assert table.item(9, 1).background().color().name().lower() == "#abcdef"


def test_timeline_repository_focus_block_uses_session_color_over_display_color_preference(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.focus_display_color = "#123456"
    selected_date = datetime(2026, 6, 14).date()
    started = datetime(2026, 6, 14, 9, 0)
    session = repository.save_focus_session(
        FocusSession(
            title="Repo focus",
            planned_seconds=600,
            focused_seconds=600,
            started_at=started,
            ended_at=started + timedelta(minutes=10),
            status="completed",
            color="#abcdef",
        )
    )

    # Given a saved session with its own color, When timeline blocks are built, Then each focus
    # block carries that session color and the table paints it, never focus_display_color.
    assert session.color == "#abcdef"
    blocks = _today_timeline_blocks(repository, selected_date)
    focus_blocks = [block for block in blocks if block[4].get("type") == "focus_session"]
    assert focus_blocks
    assert all(block[4].get("color") == "#abcdef" for block in focus_blocks)

    table = QTableWidget(24, 7)
    _fill_time_block_table(table, selected_date, blocks, preferences)
    app.processEvents()

    assert table.item(9, 1).background().color().name().lower() == "#abcdef"


def test_time_block_focus_session_menu_includes_color_change(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    app.processEvents()

    # Per-session colors now drive timetable focus blocks, so the block context menu offers a
    # per-session "색상 변경" alongside delete; it only recolors that one session.
    menu = QMenu(widget)
    payloads = [{"type": "focus_session", "id": 5, "title": "딥 워크"}]
    widget._add_time_block_item_actions(menu, payloads)

    action_texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert action_texts == ["색상 변경 - 딥 워크", "집중 기록 삭제 - 딥 워크"]
    widget.close()


def test_timeline_list_focus_session_menu_includes_color_change(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    started = datetime(2026, 6, 14, 9, 0)
    session = repository.save_focus_session(
        FocusSession(
            title="타임라인 집중",
            planned_seconds=600,
            focused_seconds=600,
            started_at=started,
            ended_at=started + timedelta(minutes=10),
            status="completed",
        )
    )
    assert session.id is not None

    captured_menus: list[QMenu] = []

    def capture_style(menu: QMenu, _parent: QWidget) -> QMenu:
        captured_menus.append(menu)
        return menu

    monkeypatch.setattr(main_window_module, "_style_popup_menu", capture_style)

    widget = TodayTimelineWidget(repository)
    widget.set_date(started.date())
    app.processEvents()

    focus_item = None
    for row in range(widget.timeline_list.count()):
        candidate = widget.timeline_list.item(row)
        data = candidate.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict) and data.get("type") == "focus_session":
            focus_item = candidate
            break
    assert focus_item is not None

    # itemAt depends on layout/visibility (the list is hidden after refresh), so resolve the
    # real focus_session item directly while still exercising show_timeline_context_menu's exec path.
    monkeypatch.setattr(widget.timeline_list, "itemAt", lambda _position: focus_item)

    QTimer.singleShot(0, lambda: captured_menus[-1].close() if captured_menus else None)
    widget.show_timeline_context_menu(QPoint(0, 0))

    assert captured_menus
    action_texts = [action.text() for action in captured_menus[-1].actions() if not action.isSeparator()]
    assert "집중 기록 삭제" in action_texts
    assert "색상 변경" in action_texts
    widget.close()


def _stub_focus_color_dialog(monkeypatch, hex_value: str) -> None:
    class _StubColorDialog:
        @staticmethod
        def getColor(*args, **kwargs):
            return QColor(hex_value)

    monkeypatch.setattr(main_window_module, "QColorDialog", _StubColorDialog)


def test_time_block_color_change_updates_only_that_session(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    started = datetime(2026, 6, 14, 9, 0)
    first = repository.save_focus_session(
        FocusSession(
            title="첫 집중",
            planned_seconds=600,
            started_at=started,
            ended_at=started + timedelta(minutes=10),
            status="completed",
            color="#111111",
        )
    )
    second = repository.save_focus_session(
        FocusSession(
            title="둘째 집중",
            planned_seconds=600,
            started_at=started + timedelta(minutes=20),
            ended_at=started + timedelta(minutes=30),
            status="completed",
            color="#222222",
        )
    )
    widget = TodayTimelineWidget(repository)
    app.processEvents()

    _stub_focus_color_dialog(monkeypatch, "#abcdef")
    widget.change_focus_session_color(first.id)
    app.processEvents()

    # Given two saved sessions, When one is recolored from the block menu, Then only that session
    # changes and the other keeps its saved color (no global focus repaint).
    assert repository.get_focus_session(first.id).color == "#abcdef"
    assert repository.get_focus_session(second.id).color == "#222222"
    widget.close()


def test_focus_picker_during_active_session_recolors_only_that_session(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    # A prior completed session keeps its own color and must not be repainted by the picker.
    earlier = repository.save_focus_session(
        FocusSession(
            title="이전 집중",
            planned_seconds=600,
            started_at=datetime(2026, 6, 14, 8, 0),
            ended_at=datetime(2026, 6, 14, 8, 10),
            status="completed",
            color="#111111",
        )
    )

    window.focus_title_edit.setText("리포트 작성")
    window.start_focus_button.click()
    app.processEvents()
    active = window.focus_timer.session
    assert active is not None and active.status == "running"

    _stub_focus_color_dialog(monkeypatch, "#abcdef")
    window._choose_focus_display_color()
    app.processEvents()

    # When the focus picker changes color during an active session, Then the active session and
    # the swatch/default both take the new color, while unrelated saved sessions stay untouched.
    assert window.focus_timer.session.color == "#abcdef"
    assert repository.get_focus_session(active.id).color == "#abcdef"
    assert window.preferences.focus_display_color == "#abcdef"
    assert repository.get_focus_session(earlier.id).color == "#111111"
    window.close()


def test_start_focus_captures_selected_focus_color(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.preferences.focus_display_color = "#abcdef"
    window.focus_title_edit.setText("리포트 작성")
    window.start_focus_button.click()
    app.processEvents()

    # Given a selected focus swatch color, When a focus session starts, Then the new session
    # stores that color rather than an auto-assigned-by-title color.
    session = window.focus_timer.session
    assert session is not None
    assert session.color == "#abcdef"
    assert repository.get_focus_session(session.id).color == "#abcdef"
    window.close()


def test_checklist_edit_dialog_can_select_past_date_time(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("Past editable", 20, created_at=datetime(2026, 6, 15, 12, 0)))

    dialog = ChecklistItemEditDialog(repository, "task", task)
    dialog.use_time_check.setChecked(True)
    dialog.date_edit.setDate(QDate(2026, 6, 1))
    dialog.time_edit.setTime(QTime(8, 15))

    assert dialog.selected_datetime() == datetime(2026, 6, 1, 8, 15)
    dialog.close()


def test_completed_at_edit_dialog_selects_revised_completion_datetime(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(
        Task(
            "Completion edit",
            0,
            completed=True,
            completed_at=datetime(2026, 6, 14, 9, 30),
        )
    )

    dialog = CompletedAtEditDialog(repository, "task", task, repository.get_preferences())
    dialog.date_edit.setDate(QDate(2026, 6, 12))
    dialog.time_edit.setTime(QTime(22, 5))

    assert dialog.selected_datetime() == datetime(2026, 6, 12, 22, 5)
    dialog.close()


def test_focus_target_checkbox_selects_first_detected_window(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)

    class Provider:
        def list_open_windows(self) -> list[ActiveWindowSnapshot]:
            return [
                ActiveWindowSnapshot("code.exe", "main.py"),
                ActiveWindowSnapshot("chrome.exe", "Schedule Helper"),
                ActiveWindowSnapshot("notion.exe", "Project notes"),
            ]

        def current_window(self) -> ActiveWindowSnapshot | None:
            return ActiveWindowSnapshot("code.exe", "main.py")

    window.window_provider = Provider()
    window.use_focus_target_check.setChecked(True)
    app.processEvents()

    assert window.target_combo.currentData()["process_name"] == "code.exe"
    assert window.focus_targets_list.count() == 0
    assert window.focus_targets_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    window.add_focus_target_from_combo_index(window.target_combo.model().index(window.target_combo.currentIndex(), 0))
    app.processEvents()
    assert window.focus_targets_list.count() == 1
    window.target_combo.activated.emit(window.target_combo.currentIndex())
    app.processEvents()
    assert window.focus_targets_list.count() == 1
    for index in range(2, 4):
        window.add_focus_target_from_combo_index(window.target_combo.model().index(index, 0))
    app.processEvents()
    assert window.focus_targets_list.count() == 3
    assert sum(window.focus_targets_list.item(index).sizeHint().height() for index in range(3)) <= window.focus_targets_list.maximumHeight()
    assert window.target_combo.view().objectName() == "focusTargetComboView"
    assert window.focus_targets_list.objectName() == "focusTargetsList"
    assert window.focus_targets_list.minimumHeight() >= 82
    assert window.focus_targets_list.maximumHeight() >= 100
    assert window._selected_focus_targets()[0]["window_title"] == "main.py"
    window.focus_targets_list.setCurrentRow(0)
    window.remove_selected_focus_target()
    assert window.focus_targets_list.count() == 2
    assert window._selected_focus_targets()[0]["window_title"] == "Schedule Helper"
    window.close()


def test_main_feature_titles_live_inside_panels_not_under_handles(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    for feature_key, title in (
        ("pomodoro", "뽀모도로"),
        ("today_checklist", "오늘 체크리스트"),
        ("today_timeline", "시간표"),
        ("quick_memo", "메모"),
        ("link_favorites", "즐겨찾기"),
    ):
        feature_box = window.feature_boxes[feature_key]
        assert feature_box.title_label is None
        assert feature_box.header_band is not None
        assert feature_box.header_band.minimumHeight() == PANEL_HEADER_HEIGHT
        assert feature_box.header_band.maximumHeight() == PANEL_HEADER_HEIGHT
        assert feature_box.move_bar is not None
        assert feature_box.move_bar.minimumHeight() == PANEL_MOVE_BAR_HEIGHT
        assert feature_box.move_bar.maximumHeight() == PANEL_MOVE_BAR_HEIGHT
        assert feature_box.move_bar.toolTip() == title
        internal_titles = [
            label.text()
            for label in feature_box.findChildren(QLabel)
            if label.text() == title and label.isVisibleTo(feature_box)
        ]
        assert internal_titles
    assert window.feature_boxes["media_panel"].title_label is None
    favorites_inner_labels = [
        label.text()
        for label in window.link_favorites_panel.findChildren(QLabel)
        if label.text() == "바로가기"
    ]
    assert favorites_inner_labels == []

    window.close()


def test_side_by_side_feature_handles_share_same_baseline(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1700, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "today_timeline", "x": 0, "y": 0, "w": 4, "h": 6},
        {"key": "quick_memo", "x": 4, "y": 0, "w": 4, "h": 6},
        {"key": "link_favorites", "x": 8, "y": 0, "w": 4, "h": 6},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    handle_tops = {
        key: window.feature_boxes[key].move_bar.mapTo(window, QPoint(0, 0)).y()
        for key in ("today_timeline", "quick_memo", "link_favorites")
    }
    assert len(set(handle_tops.values())) == 1

    window.close()


def test_feature_move_bar_uses_accent_when_dragging(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    move_bar = window.feature_boxes["focus"].findChild(QWidget, "featureMoveBar")
    assert move_bar is not None
    assert move_bar.testAttribute(Qt.WidgetAttribute.WA_Hover)
    assert move_bar.hasMouseTracking()
    assert "QWidget#featureMoveBar:hover" in window.styleSheet()
    assert "rgba(104, 168, 245, 0.18)" in window.styleSheet()
    assert "border: 1px solid rgba(104, 168, 245, 0.18)" in window.styleSheet()
    assert "QWidget#featureMoveBar[dragging=\"true\"]" in window.styleSheet()
    assert "background: #68a8f5" in window.styleSheet()
    assert "border: 1px solid #68a8f5" in window.styleSheet()

    QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Enter))
    assert move_bar.property("hovering") is True
    hover_pixmap = QPixmap(move_bar.size())
    hover_pixmap.fill(Qt.GlobalColor.transparent)
    move_bar.render(hover_pixmap)
    hover_color = hover_pixmap.toImage().pixelColor(move_bar.width() // 2, move_bar.height() // 2)
    assert hover_color.alpha() > 0
    assert hover_color.green() > hover_color.red()
    QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Leave))
    assert move_bar.property("hovering") is False

    set_dragging = getattr(move_bar, "set_dragging")
    set_dragging(True)
    assert move_bar.property("dragging") is True
    set_dragging(False)
    assert move_bar.property("dragging") is False

    QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Enter))
    set_dragging(True)
    reset_interaction_state = getattr(move_bar, "reset_interaction_state")
    reset_interaction_state()
    assert move_bar.property("hovering") is False
    assert move_bar.property("dragging") is False

    move_bar.set_hovering(True)
    move_bar.set_dragging(True)
    handled = window.feature_boxes["focus"].finish_feature_reposition_gesture(QPoint(1, 1), move_bar)
    assert handled is False
    assert move_bar.property("hovering") is False
    assert move_bar.property("dragging") is False
    window.close()


def test_feature_move_bar_shows_central_grip_affordance(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    move_bar = window.feature_boxes["focus"].move_bar
    assert move_bar is not None

    # The handle is more than a flat filled strip: it renders a central multi-mark grip.
    grip_marks = move_bar._grip_marks()
    assert len(grip_marks) >= 2
    bar_width = move_bar.width()
    bar_height = move_bar.height()
    assert bar_width > 0 and bar_height > 0
    assert all(0.0 <= mark.left() and mark.right() <= bar_width for mark in grip_marks)
    assert all(0.0 <= mark.top() and mark.bottom() <= bar_height for mark in grip_marks)

    # The grip is a compact central cluster, not a full-width fill.
    cluster_span = grip_marks[-1].right() - grip_marks[0].left()
    assert cluster_span < bar_width / 2
    cluster_center = (grip_marks[0].left() + grip_marks[-1].right()) / 2
    assert abs(cluster_center - bar_width / 2) <= 1.5

    # On hover the central grip paints more prominently than the surrounding accent wash.
    QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Enter))
    assert move_bar.property("hovering") is True
    pixmap = QPixmap(move_bar.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    move_bar.render(pixmap)
    image = pixmap.toImage()
    grip_pixel = image.pixelColor(bar_width // 2, bar_height // 2)
    wash_pixel = image.pixelColor(max(2, int(bar_width * 0.2)), bar_height // 2)
    assert grip_pixel.alpha() > 0
    assert wash_pixel.alpha() > 0
    assert grip_pixel.alpha() > wash_pixel.alpha()
    QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Leave))
    window.close()


def test_feature_panel_controls_share_consistent_alignment_metrics(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_today_checklist_inline = False
    repository.save_preferences(preferences)
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    header_heights = [
        window.feature_boxes[key].header_band.maximumHeight()
        for key in ("focus", "today_checklist", "pomodoro", "quick_memo", "link_favorites")
    ]
    assert set(header_heights) == {PANEL_HEADER_HEIGHT}

    controls = [
        window.focus_title_edit,
        window.planned_minutes_spin,
        window.idle_cutoff_spin,
        window.pomodoro_minutes_spin,
        window.break_minutes_spin,
        window.start_pomodoro_button,
        window.pause_pomodoro_button,
        window.reset_pomodoro_button,
        window.quick_note_folder_combo,
        window.note_filter_combo,
    ]
    assert all(control is not None for control in controls)
    assert {control.minimumHeight() for control in controls} == {PANEL_CONTROL_HEIGHT}
    assert {control.maximumHeight() for control in controls} == {PANEL_CONTROL_HEIGHT}
    window.close()


def test_feature_panel_titles_share_internal_title_style(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    titles = [
        window.focus_title_label,
        window.memo_editor_title,
        window.today_checklist_widget.findChild(QLabel, "panelTitleLabel"),
        window.inline_timeline_widget.findChild(QLabel, "panelTitleLabel"),
        window.pomodoro_panel.findChild(QLabel, "panelTitleLabel"),
        window.link_favorites_content_panel.findChild(QLabel, "panelTitleLabel"),
    ]
    assert all(title is not None for title in titles)
    assert {title.objectName() for title in titles} == {"panelTitleLabel"}
    assert {title.minimumHeight() for title in titles} == {PANEL_CONTROL_HEIGHT}
    assert {title.maximumHeight() for title in titles} == {PANEL_CONTROL_HEIGHT}
    assert "QLabel#panelTitleLabel" in window.styleSheet()
    pomodoro_content_panel = window.feature_boxes["pomodoro"].findChild(QWidget, "pomodoroPanel")
    assert pomodoro_content_panel is not None
    card_panels = [
        window.focus_content_panel,
        window.memo_content_panel,
        window.today_checklist_widget,
        window.inline_timeline_widget,
        pomodoro_content_panel,
        window.link_favorites_content_panel,
    ]
    assert {panel.objectName() for panel in card_panels} == {
        "focusPanel",
        "plainPanel",
        "checklistPanel",
        "timelinePanel",
        "pomodoroPanel",
        "favoritesPanel",
    }
    assert all(panel.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) for panel in card_panels)
    assert "QWidget#favoritesPanel" in window.styleSheet()
    window.close()


def test_card_panel_borders_fit_dashboard_grid_rhythm(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = False
    window.preferences.show_focus_panel = True
    window.preferences.show_header_banner = False
    window.preferences.show_quick_memo_panel = True
    window.preferences.show_media_panel = False
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = True
    window.preferences.show_today_timeline_inline = True
    window.preferences.show_today_checklist_inline = True
    window.preferences.show_link_favorites_panel = True

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 3, "h": 7},
        {"key": "quick_memo", "x": 3, "y": 0, "w": 3, "h": 5},
        {"key": "today_checklist", "x": 6, "y": 0, "w": 3, "h": 6},
        {"key": "pomodoro", "x": 9, "y": 0, "w": 3, "h": 4},
        {"key": "link_favorites", "x": 0, "y": 7, "w": 3, "h": 4},
        {"key": "today_timeline", "x": 3, "y": 7, "w": 3, "h": 8},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    card_widgets = {
        "focus": window.focus_content_panel,
        "quick_memo": window.memo_content_panel,
        "today_checklist": window.today_checklist_widget,
        "pomodoro": window.feature_boxes["pomodoro"].findChild(QWidget, "pomodoroPanel"),
        "link_favorites": window.link_favorites_content_panel,
        "today_timeline": window.inline_timeline_widget,
    }
    assert all(widget is not None for widget in card_widgets.values())

    heights = {
        "focus": 7,
        "quick_memo": 5,
        "today_checklist": 6,
        "pomodoro": 4,
        "link_favorites": 4,
        "today_timeline": 8,
    }
    title_offsets = []
    handle_to_card_offsets = []
    for key, widget in card_widgets.items():
        title = widget.findChild(QLabel, "panelTitleLabel")
        assert title is not None
        rect = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())
        # The grid cell (box) is now sized as card + header, so the visible card
        # itself equals the item pixel height. This keeps the vertical card-to-card
        # gap equal to the horizontal one (DASHBOARD_GRID_GAP) instead of being
        # widened by the header band's height.
        expected_card_height = window._dashboard_item_pixel_height(heights[key])
        assert rect.height() == expected_card_height
        move_bar = window.feature_boxes[key].move_bar
        assert move_bar is not None
        handle_to_card_offsets.append(rect.top() - move_bar.mapTo(window, QPoint(0, 0)).y())
        title_offsets.append(title.mapTo(widget, QPoint(0, 0)).y())

    assert set(handle_to_card_offsets) == {PANEL_HEADER_HEIGHT + PANEL_HANDLE_CONTENT_GAP}
    assert len(set(title_offsets)) == 1

    first_row_tops = {
        card_widgets[key].mapTo(window, QPoint(0, 0)).y()
        for key in ("focus", "quick_memo", "today_checklist", "pomodoro")
    }
    second_row_tops = {
        card_widgets[key].mapTo(window, QPoint(0, 0)).y()
        for key in ("link_favorites", "today_timeline")
    }
    assert len(first_row_tops) == 1
    assert all(top > next(iter(first_row_tops)) for top in second_row_tops)
    assert "border-radius: 16px;" in window.styleSheet()
    window.close()


def test_app_bar_ports_title_and_focus_status_card(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.app_title = "안녕"
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    assert window.windowTitle() == "안녕"
    assert window.chrome_title_label.text() == "안녕"
    orot_mark = window.findChild(QWidget, "orotMark")
    assert orot_mark is not None
    orot_wordmark = window.findChild(QLabel, "orotWordmark")
    assert orot_wordmark is not None
    assert orot_wordmark.text() == "OROT"
    assert window.header_focus_card.isHidden()
    assert window.header_focus_status_label.text() == "대기 중"
    assert window.header_focus_time_label.text() == "25:00"
    assert "집중할 일을 고른 뒤 시작하세요" in window.header_focus_card.toolTip()
    assert not window.findChildren(QWidget, "themeSegment")
    assert not hasattr(window, "light_theme_button")
    assert not hasattr(window, "dark_theme_button")
    window.close()


def test_app_bar_shows_workspace_selector_before_settings(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_layout_profile(LayoutProfile(name="업무", data='{"layout":{}}'))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    top_buttons = window.findChildren(QPushButton, "topBarButton")
    button_texts = [button.text() for button in top_buttons]

    assert "기본 ▾" in button_texts
    assert button_texts.index("기본 ▾") < button_texts.index("설정")
    workspace_button = next(button for button in top_buttons if button.text() == "기본 ▾")
    assert workspace_button.objectName() == "topBarButton"

    menu = window._build_workspace_menu()
    action_texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert action_texts[-1] == "워크스페이스 관리..."
    assert "업무" in action_texts
    window.close()


def test_workspace_button_shows_active_name(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profile = repository.save_layout_profile(LayoutProfile(name="업무", data='{"layout":{}}'))
    assert profile.id is not None

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.switch_workspace(int(profile.id))
    app.processEvents()

    assert window.workspace_button.text().startswith("업무")
    assert window.workspace_button.toolTip() == "업무"
    window.close()


def test_workspace_button_shows_default_when_none(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    assert window.preferences.active_workspace_id is None
    assert window.workspace_button.text() == "기본 ▾"
    assert window.workspace_button.toolTip() == ""
    window.close()


def test_long_workspace_name_ellipsized(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    long_name = "아주긴작업공간이름입니다이것은버튼에다안들어가야합니다" * 3
    profile = repository.save_layout_profile(LayoutProfile(name=long_name, data='{"layout":{}}'))
    assert profile.id is not None

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.switch_workspace(int(profile.id))
    app.processEvents()

    text = window.workspace_button.text()
    assert text.endswith("…") or text.endswith("… ▾") or "…" in text
    assert window.workspace_button.toolTip() == long_name
    window.close()


def test_app_bar_shows_default_orot_branding(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    assert repository.get_preferences().app_title == "오롯"

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    assert window.windowTitle() == "오롯"
    assert window.chrome_title_label.text() == "오롯"
    assert window.findChild(QWidget, "orotMark") is not None
    orot_wordmark = window.findChild(QLabel, "orotWordmark")
    assert orot_wordmark is not None
    assert orot_wordmark.text() == "OROT"
    style = window.styleSheet()
    chrome_bar_style = style[style.index("QWidget#appChromeBar {") : style.index("QWidget#featureGrid")]
    assert "background: #fafafa;" in chrome_bar_style
    chrome_title_style = style[style.index("QLabel#chromeTitle {") : style.index("QLabel#eyebrowLabel")]
    assert "color: #6fa8e0;" in chrome_title_style
    assert OROT_RING_COLOR == "#6fa8e0"
    assert window.orot_mark._color.name() == "#6fa8e0"
    assert window.compact_button.objectName() == "topBarButton"
    top_button_style = style[style.index("QPushButton#topBarButton {") : style.index("QPushButton#topBarAccentButton")]
    assert "background: #fafafa;" in top_button_style
    assert "__BUTTON_BG__" not in top_button_style
    pin_style = style[style.index("QCheckBox#pinCheck {") : style.index("QCheckBox#pinCheck::indicator")]
    assert "background: #fafafa;" in pin_style
    assert "__BUTTON_BG__" not in pin_style
    window.close()


def test_app_bar_has_custom_window_chrome(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # Native OS chrome is hidden; the OROT header bar IS the title bar.
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert isinstance(window.findChild(QWidget, "appChromeBar"), AppChromeBar)

    # Vertical divider with reference geometry sits before the controls.
    divider = window.findChild(QFrame, "chromeDivider")
    assert divider is not None
    assert divider.width() == 1
    assert divider.height() == 22

    # Three custom controls with stable object names and a 34x34 hit area.
    minimize = window.findChild(QPushButton, "windowMinButton")
    maximize = window.findChild(QPushButton, "windowMaxButton")
    close_button = window.findChild(QPushButton, "windowCloseButton")
    assert minimize is not None
    assert maximize is not None
    assert close_button is not None
    for control in (minimize, maximize, close_button):
        assert isinstance(control, WindowControlButton)
        assert control.size().width() == 34
        assert control.size().height() == 34
        # Real painted shapes, never a text glyph or emoji.
        assert control.text() == ""

    # Compact widget button stays a normal menu button, not a chrome control.
    assert window.compact_button.objectName() == "topBarButton"

    # Divider + control QSS is present (and theme-substituted, no raw placeholders).
    style = window.styleSheet()
    assert "QFrame#chromeDivider {" in style
    assert "QPushButton#windowCloseButton {" in style

    # The frameless window keeps a subtle visible border with native-ish rounded
    # corners; the chrome bar's top corners are rounded to match.
    appshell_style = style[style.index("QWidget#appShell {") : style.index("QWidget#appBody")]
    assert f"border: 1px solid {WINDOW_FRAME_BORDER_COLOR};" in appshell_style
    assert f"border-radius: {WINDOW_FRAME_CORNER_RADIUS}px;" in appshell_style
    chrome_bar_style = style[style.index("QWidget#appChromeBar {") : style.index("QWidget#featureGrid")]
    assert f"border-top-left-radius: {WINDOW_FRAME_CORNER_RADIUS}px;" in chrome_bar_style
    assert f"border-top-right-radius: {WINDOW_FRAME_CORNER_RADIUS}px;" in chrome_bar_style

    # Maximize control toggles between maximize and restore with window state.
    assert window.window_maximize_button.control_kind() == "maximize"
    window.toggle_max_restore()
    app.processEvents()
    assert window.isMaximized()
    assert window.window_maximize_button.control_kind() == "restore"
    window.toggle_max_restore()
    app.processEvents()
    assert not window.isMaximized()
    assert window.window_maximize_button.control_kind() == "maximize"

    window.close()


def test_toggle_max_restore_returns_to_tracked_normal_size(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.resize(1180, 760)
    app.processEvents()
    tracked = window._normal_window_size
    assert tracked is not None
    assert (tracked.width(), tracked.height()) == (1180, 760)

    window.toggle_max_restore()
    app.processEvents()
    assert window.isMaximized()
    # Maximizing must never overwrite the tracked normal size.
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1180, 760)

    window.toggle_max_restore()
    app.processEvents()
    assert not window.isMaximized()
    # Restore returns to the tracked normal size, not a maximized-sized geometry.
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1180, 760)
    assert (window.width(), window.height()) == (1180, 760)

    window.close()


def test_toggle_max_restore_uses_native_maximize_when_hwnd_exists(tmp_path, monkeypatch) -> None:
    class NativeMaximizeApi:
        def __init__(self) -> None:
            self.maximized_hwnd: int | None = None

        def is_maximized(self, hwnd: int) -> bool:
            return self.maximized_hwnd == hwnd

        def maximize_window(self, hwnd: int) -> None:
            self.maximized_hwnd = hwnd

    class NoQtMaximizeWindow(MainWindow):
        def showMaximized(self) -> None:
            raise AssertionError("native Windows chrome must not use Qt fullscreen-like maximize")

    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = NoQtMaximizeWindow(repository)
    window.show()
    app.processEvents()

    fake_api = NativeMaximizeApi()
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API", fake_api)
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API_READY", True)
    monkeypatch.setattr(window, "_native_window_handle", lambda: 4242)

    window.toggle_max_restore()
    app.processEvents()

    assert fake_api.maximized_hwnd == 4242
    assert window.window_maximize_button.control_kind() == "restore"
    window.close()


def test_apply_windows_native_chrome_pushes_orot_icon_to_hwnd(tmp_path, monkeypatch) -> None:
    # The frameless HWND can lose its native WM_SETICON association whenever Qt
    # recreates it, so applying native chrome must also (re)push the OROT .ico to
    # the HWND or the taskbar button and preview fall back to a generic icon.
    class IconRecordingChromeApi:
        def __init__(self) -> None:
            self.icon_calls: list[tuple[int, str]] = []

        def restore_window_styles(self, hwnd: int) -> None:
            pass

        def apply_rounded_frame(self, hwnd: int, border_color: str) -> None:
            pass

        def apply_window_icons(self, hwnd: int, icon_path: str) -> bool:
            self.icon_calls.append((hwnd, icon_path))
            return True

        def is_maximized(self, hwnd: int) -> bool:
            return False

    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    icon_pixmap = QPixmap(32, 32)
    icon_pixmap.fill(Qt.GlobalColor.red)
    window.setWindowIcon(QIcon(icon_pixmap))

    fake_api = IconRecordingChromeApi()
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API", fake_api)
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API_READY", True)
    monkeypatch.setattr(window, "_native_window_handle", lambda: 4242)

    window._apply_windows_native_chrome()

    assert len(fake_api.icon_calls) == 1
    applied_hwnd, applied_path = fake_api.icon_calls[0]
    assert applied_hwnd == 4242
    assert Path(applied_path).name == "orot.ico"
    assert Path(applied_path).exists()
    window.close()


def test_apply_windows_native_chrome_uses_orot_asset_without_qt_icon(tmp_path, monkeypatch) -> None:
    # Packaged Qt can fail to hydrate windowIcon() before the HWND exists. The
    # native taskbar/preview icon still comes from the bundled OROT .ico asset.
    class IconRecordingChromeApi:
        def __init__(self) -> None:
            self.icon_calls: list[tuple[int, str]] = []

        def restore_window_styles(self, hwnd: int) -> None:
            pass

        def apply_rounded_frame(self, hwnd: int, border_color: str) -> None:
            pass

        def apply_window_icons(self, hwnd: int, icon_path: str) -> bool:
            self.icon_calls.append((hwnd, icon_path))
            return True

        def is_maximized(self, hwnd: int) -> bool:
            return False

    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.setWindowIcon(QIcon())

    fake_api = IconRecordingChromeApi()
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API", fake_api)
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API_READY", True)
    monkeypatch.setattr(window, "_native_window_handle", lambda: 4242)

    window._apply_windows_native_chrome()

    assert len(fake_api.icon_calls) == 1
    applied_hwnd, applied_path = fake_api.icon_calls[0]
    assert applied_hwnd == 4242
    assert Path(applied_path).name == "orot.ico"
    assert Path(applied_path).exists()
    window.close()


def test_frameless_window_native_hit_test(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(900, 640)
    window.show()
    app.processEvents()

    # Pure edge detector: each border within the margin maps to its edge, adjacent
    # borders combine into corners, and the interior reports no edge.
    size = QSize(900, 640)
    inset = WINDOW_RESIZE_MARGIN - 2
    assert _resize_edges_for_point(QPoint(inset, 300), size) == Qt.Edge.LeftEdge
    assert _resize_edges_for_point(QPoint(900 - inset, 300), size) == Qt.Edge.RightEdge
    assert _resize_edges_for_point(QPoint(400, inset), size) == Qt.Edge.TopEdge
    assert _resize_edges_for_point(QPoint(400, 640 - inset), size) == Qt.Edge.BottomEdge
    assert _resize_edges_for_point(QPoint(inset, inset), size) == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge)
    assert _resize_edges_for_point(QPoint(900 - inset, 640 - inset), size) == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
    assert _resize_edges_for_point(QPoint(900 - inset, inset), size) == (Qt.Edge.TopEdge | Qt.Edge.RightEdge)
    assert _resize_edges_for_point(QPoint(inset, 640 - inset), size) == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge)
    assert not _resize_edges_for_point(QPoint(450, 320), size)

    # Each edge/corner maps to its Win32 WM_NCHITTEST border code so Windows owns
    # the native resize loop and resize cursors; the interior maps to nothing.
    assert _hit_test_for_edges(Qt.Edge.LeftEdge) == HTLEFT
    assert _hit_test_for_edges(Qt.Edge.RightEdge) == HTRIGHT
    assert _hit_test_for_edges(Qt.Edge.TopEdge) == HTTOP
    assert _hit_test_for_edges(Qt.Edge.BottomEdge) == HTBOTTOM
    assert _hit_test_for_edges(Qt.Edge.TopEdge | Qt.Edge.LeftEdge) == HTTOPLEFT
    assert _hit_test_for_edges(Qt.Edge.TopEdge | Qt.Edge.RightEdge) == HTTOPRIGHT
    assert _hit_test_for_edges(Qt.Edge.BottomEdge | Qt.Edge.LeftEdge) == HTBOTTOMLEFT
    assert _hit_test_for_edges(Qt.Edge.BottomEdge | Qt.Edge.RightEdge) == HTBOTTOMRIGHT
    assert _hit_test_for_edges(Qt.Edge(0)) is None
    assert _hit_test_for_edges(_resize_edges_for_point(QPoint(450, 320), size)) is None

    # Composite hit test: resize borders win over the caption so corners stay
    # grabbable; the caption strip maps to HTCAPTION (native move + Aero Snap);
    # the body falls through to HTCLIENT so Qt still delivers the child event.
    margin = WINDOW_RESIZE_MARGIN
    assert _window_hit_test_result(QPoint(inset, inset), size, margin=margin, on_caption=True, resizable=True) == HTTOPLEFT
    assert _window_hit_test_result(QPoint(450, inset), size, margin=margin, on_caption=True, resizable=True) == HTTOP
    assert _window_hit_test_result(QPoint(450, 28), size, margin=margin, on_caption=True, resizable=True) == HTCAPTION
    assert _window_hit_test_result(QPoint(450, 320), size, margin=margin, on_caption=False, resizable=True) == HTCLIENT
    # A maximized window is never resizable; borders fall back to caption/client.
    assert _window_hit_test_result(QPoint(inset, inset), size, margin=margin, on_caption=True, resizable=False) == HTCAPTION
    assert _window_hit_test_result(QPoint(inset, inset), size, margin=margin, on_caption=False, resizable=False) == HTCLIENT

    # Interactive controls are never caption/resize surfaces; plain chrome is.
    assert not _is_resize_eligible_widget(window.window_close_button)
    assert not _is_resize_eligible_widget(window.main_always_on_top_check)
    assert _is_resize_eligible_widget(window.findChild(QWidget, "appChromeBar"))

    # The brand lockup is a live caption (drag) surface, but the window controls
    # are not, so they keep receiving their own clicks instead of starting a move.
    title_label = window.chrome_title_label
    title_point = title_label.mapTo(window, QPoint(title_label.width() // 2, title_label.height() // 2))
    assert window._point_is_caption(title_point)
    close_button = window.window_close_button
    close_point = close_button.mapTo(window, QPoint(close_button.width() // 2, close_button.height() // 2))
    assert not window._point_is_caption(close_point)

    window.close()


def test_native_message_handler_does_not_reenter_winid(tmp_path, monkeypatch) -> None:
    class NoReentrantWinIdWindow(MainWindow):
        def winId(self):
            raise AssertionError("native message handling must use the message hWnd")

    class FakeChromeApi:
        def is_maximized(self, hwnd: int) -> bool:
            assert hwnd == 12345
            return False

        def window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
            assert hwnd == 12345
            return 0, 0, 900, 640

    class MessagePointer:
        def __init__(self, address: int) -> None:
            self._address = address

        def __int__(self) -> int:
            return self._address

    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = NoReentrantWinIdWindow(repository)

    message = wintypes.MSG()
    message.hWnd = 12345
    message.message = main_window_module._WM_NCHITTEST
    message.lParam = (300 << 16) | 3

    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API", FakeChromeApi())
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API_READY", True)

    result = window._handle_windows_native_message(MessagePointer(ctypes.addressof(message)))

    assert result == HTLEFT
    window.close()


def test_native_hit_test_blocks_resize_when_win32_reports_maximized(tmp_path) -> None:
    class FakeMaximizedChromeApi:
        def is_maximized(self, hwnd: int) -> bool:
            assert hwnd == 12345
            return True

        def window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
            assert hwnd == 12345
            return 0, 0, 900, 640

    class Message:
        lParam = (300 << 16) | 3

    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(900, 640)
    window.show()
    app.processEvents()

    assert not window.isMaximized()

    result = window._native_nchittest(FakeMaximizedChromeApi(), 12345, Message())

    assert result is None
    window.close()


def test_native_nccalcsize_reserves_auto_hide_taskbar_edge(tmp_path) -> None:
    class FakeChromeApi:
        def is_maximized(self, hwnd: int) -> bool:
            assert hwnd == 12345
            return True

        def resize_border_thickness(self, device_pixel_ratio: float) -> tuple[int, int]:
            assert device_pixel_ratio > 0
            return 8, 8

        def auto_hide_taskbar_edges(self, hwnd: int) -> Qt.Edge:
            assert hwnd == 12345
            return Qt.Edge.BottomEdge

    class Message:
        wParam = 1

        def __init__(self, address: int) -> None:
            self.lParam = address

    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)

    params = main_window_module._NCCALCSIZE_PARAMS()
    client = params.rgrc[0]
    client.left = 0
    client.top = 0
    client.right = 900
    client.bottom = 640

    result = window._native_nccalcsize(FakeChromeApi(), 12345, Message(ctypes.addressof(params)))

    assert result == 0
    assert client.left == 8
    assert client.top == 8
    assert client.right == 892
    assert client.bottom == 631
    window.close()


def test_native_maximized_state_detected_when_qt_reports_normal(tmp_path, monkeypatch) -> None:
    class FakeMaximizedChromeApi:
        def is_maximized(self, hwnd: int) -> bool:
            assert hwnd == 4242
            return True

    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.resize(1010, 620)
    app.processEvents()
    assert window._normal_window_size is not None
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    # Simulate the real Windows frameless-chrome bug: the Win32 placement is
    # maximized while Qt still reports a normal window. The stubbed handle keeps
    # winId() out of the path entirely.
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API", FakeMaximizedChromeApi())
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API_READY", True)
    monkeypatch.setattr(window, "_native_window_handle", lambda: 4242)

    assert not window.isMaximized()
    assert window._is_native_maximized()
    assert window._is_effectively_maximized()

    # The maximize/restore control reflects the native maximized state.
    window._sync_max_restore_button()
    assert window.window_maximize_button.control_kind() == "restore"

    # A resize arriving while natively maximized must not overwrite the tracked
    # normal size with the maximized geometry.
    window.resize(2560, 1440)
    app.processEvents()
    window._remember_normal_window_size()
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    # Saving while natively maximized persists the tracked normal size.
    window.save_last_window_size()
    saved = repository.get_preferences()
    assert saved.last_window_width == 1010
    assert saved.last_window_height == 620

    window.close()


def test_toggle_max_restore_restores_from_native_maximized(tmp_path, monkeypatch) -> None:
    class FakeMaximizedChromeApi:
        def __init__(self) -> None:
            self.restored_hwnd: int | None = None

        def is_maximized(self, hwnd: int) -> bool:
            return self.restored_hwnd != hwnd

        def restore_window(self, hwnd: int) -> None:
            self.restored_hwnd = hwnd

    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.resize(1010, 620)
    app.processEvents()
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    fake_api = FakeMaximizedChromeApi()
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API", fake_api)
    monkeypatch.setattr(main_window_module, "_WINDOWS_CHROME_API_READY", True)
    monkeypatch.setattr(window, "_native_window_handle", lambda: 4242)

    # Stand in for the maximized geometry while Qt still reports a normal window.
    window.resize(2560, 1440)
    app.processEvents()
    assert not window.isMaximized()
    assert window._is_effectively_maximized()

    # The toggle must take the RESTORE branch because the window is natively
    # maximized, returning to the tracked normal size instead of re-maximizing.
    window.toggle_max_restore()
    app.processEvents()
    assert fake_api.restored_hwnd == 4242
    assert not window._is_effectively_maximized()
    assert (window.width(), window.height()) == (1010, 620)
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    window.close()


def test_toggle_max_restore_restores_from_fullscreen_state(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.resize(1010, 620)
    app.processEvents()
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    # On real Windows the frameless showMaximized() lands the window in Qt's
    # WindowFullScreen state with isMaximized() False; showFullScreen() reproduces
    # that exact state offscreen.
    window.showFullScreen()
    app.processEvents()
    assert window.isFullScreen()
    assert not window.isMaximized()
    assert window._is_effectively_maximized()

    # The fullscreen geometry must not overwrite the tracked normal size.
    window._remember_normal_window_size()
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    # The restore branch collapses the window back to the tracked normal size.
    window.toggle_max_restore()
    app.processEvents()
    assert not window.isFullScreen()
    assert not window.isMaximized()
    assert (window.width(), window.height()) == (1010, 620)
    assert (window._normal_window_size.width(), window._normal_window_size.height()) == (1010, 620)

    window.close()


def test_settings_dialog_opens_roomy_with_minimum_size(tmp_path) -> None:
    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())

    # Opens larger than the old 700x720 and cannot shrink below a usable floor,
    # so the tabbed forms (storage row, color groups, fonts) are not clipped.
    assert (dialog.size().width(), dialog.size().height()) == (980, 760)
    assert (dialog.minimumSize().width(), dialog.minimumSize().height()) == (860, 680)
    dialog.close()


def test_settings_dialog_launches_workspace_manager(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    dialog = SettingsDialog(repository.get_preferences(), window)
    dialog.show()
    app.processEvents()

    button_texts = [button.text() for button in dialog.findChildren(QPushButton)]

    assert "워크스페이스 관리" in button_texts
    dialog.close()
    window.close()


def test_settings_dialog_non_modal_allows_main_scroll(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.show_settings_window()
    app.processEvents()

    dialog = window._settings_dialog
    assert isinstance(dialog, SettingsDialog)
    # Non-modal: show() was used, not exec(), so the dialog is not modal and
    # the main window remains the active window the user can scroll.
    assert not dialog.isModal()
    assert dialog.isVisible()
    assert window.isVisible()

    dialog.reject()
    app.processEvents()
    assert window._settings_dialog is None
    window.close()


def test_legacy_layout_buttons_removed(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    dialog = SettingsDialog(repository.get_preferences(), window)
    dialog.show()
    app.processEvents()

    button_texts = [button.text() for button in dialog.findChildren(QPushButton)]
    assert "화면 저장" not in button_texts
    assert "화면 불러오기" not in button_texts
    # Reset and workspace manager buttons remain.
    assert "기본 배치" in button_texts
    assert "워크스페이스 관리" in button_texts

    dialog.close()
    window.close()


def test_settings_color_picker_uses_eyedropper_cursor(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    eyedropper_buttons = dialog.findChildren(QPushButton, "eyedropperButton")
    assert eyedropper_buttons
    assert _eyedropper_cursor().shape() == Qt.CursorShape.BitmapCursor
    assert all(button.cursor().shape() == Qt.CursorShape.BitmapCursor for button in eyedropper_buttons)
    dialog.close()


def test_settings_control_main_window_font_and_size(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    default_check = dialog.findChild(QCheckBox, "mainFontDefaultCheck")
    font_combo = dialog.findChild(QComboBox, "mainFontCombo")
    size_spin = dialog.findChild(QSpinBox, "mainFontSizeSpin")
    label_size_spin = dialog.findChild(QSpinBox, "labelFontSizeSpin")
    content_size_spin = dialog.findChild(QSpinBox, "contentFontSizeSpin")

    assert default_check is not None
    assert font_combo is not None
    assert size_spin is not None
    assert label_size_spin is not None
    assert content_size_spin is not None
    assert default_check.isChecked()
    assert not font_combo.isEnabled()
    assert size_spin.value() == 13
    assert label_size_spin.value() == 13
    assert content_size_spin.value() == 13

    default_check.setChecked(False)
    size_spin.setValue(17)
    label_size_spin.setValue(15)
    content_size_spin.setValue(18)
    app.processEvents()

    preferences = dialog.preferences()
    assert preferences.main_font_family
    assert preferences.main_font_size == 17
    assert preferences.label_font_size == 15
    assert preferences.content_font_size == 18
    dialog.close()


def test_settings_control_datetime_panel_style(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    outline_thickness_spin = dialog.findChild(QSpinBox, "datetimeTextOutlineThicknessSpin")
    assert outline_thickness_spin is not None
    assert dialog.datetime_transparent_check.isChecked()
    assert not dialog.datetime_border_check.isChecked()
    assert dialog.use_default_datetime_font_check.isChecked()
    assert not dialog.datetime_font_combo.isEnabled()
    assert dialog.datetime_font_size_spin.value() == 24
    assert dialog.datetime_text_outline_color == ""
    assert outline_thickness_spin.value() == 0

    dialog.datetime_transparent_check.setChecked(False)
    dialog.datetime_border_check.setChecked(True)
    dialog.set_setting_color("datetime_text", "#123456")
    dialog.set_setting_color("datetime_text_outline", "#abcdef")
    outline_thickness_spin.setValue(5)
    dialog.use_default_datetime_font_check.setChecked(False)
    dialog.datetime_font_size_spin.setValue(40)
    dialog.set_datetime_background_image_path("C:/Images/time.gif")
    app.processEvents()

    preferences = dialog.preferences()
    assert not preferences.datetime_panel_transparent_background
    assert preferences.datetime_panel_border_enabled
    assert preferences.datetime_panel_text_color == "#123456"
    assert preferences.datetime_panel_text_outline_color == "#abcdef"
    assert preferences.datetime_panel_text_outline_thickness == 5
    assert preferences.datetime_panel_font_family
    assert preferences.datetime_panel_font_size == 40
    assert preferences.datetime_panel_background_image_path == "C:/Images/time.gif"
    dialog.close()


def test_settings_hide_banner_size_position_and_save_media_corner_choice(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "배너 높이" not in labels
    assert "배너 위치" not in labels
    assert not hasattr(dialog, "header_banner_height_spin")
    assert not hasattr(dialog, "header_banner_position_combo")

    dialog.media_rounded_corners_check.setChecked(False)
    preferences = dialog.preferences()
    assert not preferences.media_rounded_corners
    assert preferences.header_banner_height == 132
    assert preferences.header_banner_position == "center"
    dialog.close()


def test_layout_profile_load_dialog_deletes_selected_profile(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_layout_profile(LayoutProfile(name="작업 화면", data='{"layout":{}}'))
    repository.save_layout_profile(LayoutProfile(name="저녁 화면", data='{"layout":{"grid":[]}}'))

    dialog = LayoutProfileLoadDialog(repository)
    dialog.show()
    app.processEvents()

    assert dialog.profile_list.count() == 2
    first_item = dialog.profile_list.item(0)
    dialog.profile_list.setCurrentItem(first_item)
    deleted_name = first_item.text()
    dialog.delete_selected_profile(confirm=False)
    app.processEvents()

    names = [profile.name for profile in repository.list_layout_profiles()]
    assert deleted_name not in names
    assert dialog.profile_list.count() == 1
    dialog.close()


def test_main_window_applies_configured_font_and_scales_text(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.main_font_family = "Arial"
    preferences.main_font_size = 15
    preferences.label_font_size = 14
    preferences.content_font_size = 18
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    style = window.styleSheet()
    assert 'font-family: "Arial", ' in style
    assert '"Malgun Gothic"' in style
    assert '"Segoe UI"' in style
    assert "QWidget {\n                color: #111315;\n                font-family:" in style
    assert "font-size: 15px;" in style
    assert "QLabel#noteBodyLabel" in style
    assert "QLabel#sectionTitle," in style
    assert "font-size: 14px;" in style
    assert "font-size: 18px;" in style
    window.close()


def test_settings_live_preview_updates_main_window_without_saving(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    dialog = SettingsDialog(repository.get_preferences(), window)
    dialog.show()
    app.processEvents()

    dialog.content_font_size_spin.setValue(19)
    dialog.show_today_checklist_inline_check.setChecked(True)
    dialog.set_setting_color("accent", "#3366aa")
    app.processEvents()

    assert window.preferences.content_font_size == 19
    assert window.preferences.accent_color == "#3366aa"
    assert window.today_checklist_panel.isVisible()
    assert "font-size: 19px;" in window.styleSheet()
    assert repository.get_preferences().content_font_size == 13

    dialog.close()
    window.close()


def test_settings_background_live_preview_paints_main_shell_without_saving(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    dialog = SettingsDialog(repository.get_preferences(), window)
    dialog.show()
    app.processEvents()

    dialog.set_setting_color("background", "#112233")
    app.processEvents()

    style = window.styleSheet()
    shell_block = re.search(r"QWidget#appShell \{([^}]*)\}", style)
    body_block = re.search(r"QWidget#appBody, QWidget#workspace \{([^}]*)\}", style)
    main_block = re.search(r"QMainWindow \{([^}]*)\}", style)
    widget_block = re.search(r"QWidget \{([^}]*)\}", style)

    assert window.preferences.background_color == "#112233"
    assert shell_block is not None and "#112233" in shell_block.group(1)
    assert body_block is not None and "#112233" in body_block.group(1)
    assert main_block is not None and "#112233" in main_block.group(1)
    assert widget_block is not None and "color: #111315;" in widget_block.group(1)
    assert repository.get_preferences().background_color == "#d9e7f5"

    dialog.close()
    window.close()


def test_settings_inner_background_field_preserved_without_ui_control(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.inner_background_color = "#0a1b2c"
    repository.save_preferences(preferences)

    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    assert getattr(dialog, "inner_background_swatch", None) is None
    assert dialog.preferences().inner_background_color == "#0a1b2c"

    dialog.close()


def test_settings_accent_hex_field_applies_typed_color_live(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    dialog = SettingsDialog(repository.get_preferences(), window)
    dialog.show()
    app.processEvents()

    accent_hex = getattr(dialog, "accent_hex_edit", None)
    assert isinstance(accent_hex, QLineEdit)
    assert accent_hex.text().lower() == "#68a8f5"

    accent_hex.setText("#3366aa")
    accent_hex.textEdited.emit("#3366aa")
    app.processEvents()

    assert dialog.setting_color_value("accent") == "#3366aa"
    assert window.preferences.accent_color == "#3366aa"
    assert repository.get_preferences().accent_color == "#68a8f5"

    dialog.set_setting_color("accent", "#112233")
    assert accent_hex.text() == "#112233"

    accent_hex.setText("#11")
    accent_hex.textEdited.emit("#11")
    assert dialog.setting_color_value("accent") == "#112233"

    dialog.close()
    window.close()


def test_settings_optional_color_hex_field_clears_to_theme_default(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    panel_hex = getattr(dialog, "panel_hex_edit", None)
    assert isinstance(panel_hex, QLineEdit)
    assert panel_hex.text().lower() == "#fafafa"

    panel_hex.setText("#abcdef")
    panel_hex.textEdited.emit("#abcdef")
    assert dialog.setting_color_value("panel") == "#abcdef"

    panel_hex.setText("")
    panel_hex.textEdited.emit("")
    assert dialog.setting_color_value("panel") == ""
    assert dialog.preferences().panel_color == ""

    dialog.close()


def test_saved_inner_background_does_not_override_visible_background(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.background_color = "#112233"
    preferences.inner_background_color = "#0a1b2c"
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    style = window.styleSheet()
    shell_block = re.search(r"QWidget#appShell \{([^}]*)\}", style)
    body_block = re.search(r"QWidget#appBody, QWidget#workspace \{([^}]*)\}", style)

    assert window.preferences.inner_background_color == "#0a1b2c"
    assert shell_block is not None and "#112233" in shell_block.group(1)
    assert body_block is not None and "#112233" in body_block.group(1)
    assert "#0a1b2c" not in shell_block.group(1)
    assert "#0a1b2c" not in body_block.group(1)

    window.close()


def test_datetime_panel_live_preview_applies_text_style(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert isinstance(window.current_date_label, OutlinedTextLabel)
    assert isinstance(window.current_time_label, OutlinedTextLabel)
    assert not window.current_time_label.outline_enabled()

    dialog = SettingsDialog(repository.get_preferences(), window)
    dialog.show()
    app.processEvents()

    outline_thickness_spin = dialog.findChild(QSpinBox, "datetimeTextOutlineThicknessSpin")
    assert outline_thickness_spin is not None

    dialog.set_setting_color("datetime_text", "#123456")
    dialog.set_setting_color("datetime_text_outline", "#ff8800")
    outline_thickness_spin.setValue(6)
    dialog.datetime_font_size_spin.setValue(42)
    dialog.datetime_transparent_check.setChecked(False)
    dialog.datetime_border_check.setChecked(True)
    app.processEvents()

    style = window.styleSheet()
    assert window.preferences.datetime_panel_text_color == "#123456"
    assert window.preferences.datetime_panel_text_outline_color == "#ff8800"
    assert window.preferences.datetime_panel_text_outline_thickness == 6
    assert window.preferences.datetime_panel_font_size == 42
    assert "QLabel#currentTimeLabel" in style
    assert "color: #123456;" in style
    assert "font-size: 42px;" in style
    assert "QWidget#dateTimePanel" in style
    assert "border: 1px solid" in style
    assert window.current_time_label.outline_color == "#ff8800"
    assert window.current_time_label.outline_thickness == 6
    assert window.current_time_label.outline_enabled()
    assert window.current_date_label.outline_color == "#ff8800"

    dialog.close()
    window.close()


def test_outlined_text_label_renders_real_outline_pixels() -> None:
    _app()
    label = OutlinedTextLabel()
    label.setText("12:34")
    label.resize(220, 90)
    font = label.font()
    font.setPointSize(44)
    label.setFont(font)
    label.set_text_fill_color("#000000")

    def _render() -> QImage:
        target = QPixmap(label.size())
        target.fill(Qt.GlobalColor.black)
        label.render(target)
        return target.toImage()

    def _has_outline_pixel(image: QImage) -> bool:
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                color = image.pixelColor(x, y)
                if color.green() > 130 and color.red() < 90 and color.blue() < 90:
                    return True
        return False

    plain = _render()
    assert not label.outline_enabled()
    assert not _has_outline_pixel(plain)

    label.set_text_outline("#00aa00", 6)
    assert label.outline_enabled()
    assert label.outline_color == "#00aa00"
    assert label.outline_thickness == 6
    outlined = _render()
    assert _has_outline_pixel(outlined)


def test_main_window_opens_with_datetime_panel_border_enabled(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.datetime_panel_border_enabled = True
    preferences.datetime_panel_transparent_background = False
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert "QWidget#dateTimePanel" in window.styleSheet()
    assert "border: 1px solid" in window.styleSheet()
    window.close()


def test_settings_cancel_restores_live_preview_changes(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.show_settings_window()
    app.processEvents()
    dialog = window._settings_dialog
    assert isinstance(dialog, SettingsDialog)

    dialog.content_font_size_spin.setValue(20)
    dialog.show_quick_memo_panel_check.setChecked(False)
    dialog.set_setting_color("accent", "#aa3366")
    app.processEvents()

    # Live preview applied the edits to the running window without saving.
    assert window.preferences.content_font_size == 20
    assert window.preferences.accent_color == "#aa3366"

    dialog.reject()
    app.processEvents()

    assert window.preferences.content_font_size == 13
    assert window.preferences.accent_color == "#68a8f5"
    assert window.memo_panel.isVisible()
    assert repository.get_preferences().content_font_size == 13
    window.close()


def test_focus_panel_timer_dashboard_precedes_setup_form(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    layout = window.focus_panel_layout
    dashboard_index = layout.indexOf(window.focus_dashboard_card)
    title_index = layout.indexOf(window.focus_title_label)
    toggle_index = layout.indexOf(window.focus_form_toggle)
    assert dashboard_index != -1
    assert title_index != -1
    assert toggle_index != -1
    # Timer/countdown dashboard is the first content after the title; the form
    # now lives in a floating overlay dropdown, not inline in the panel layout.
    assert title_index < dashboard_index < toggle_index
    # The form panel is reparented into the overlay on first expand.
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    assert window.focus_form_overlay is not None
    assert window.focus_form_panel.parentWidget() is window.focus_form_overlay
    # Primary timer controls live inside the dashboard card, not the form.
    assert window.start_focus_button is not None
    assert window.pause_focus_button is not None
    assert window.complete_focus_button is not None
    assert window.remaining_time_label.text() != ""
    window.close()


def test_focus_panel_reorder_preserves_state_and_signals(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.focus_title_edit.setText("리포트 작성")
    window.planned_minutes_spin.setValue(45)
    window.idle_cutoff_spin.setValue(90)
    window.use_focus_target_check.setChecked(True)
    app.processEvents()

    # A responsive relayout (which the reorder must not disturb) keeps every value.
    window.focus_content_panel.setFixedSize(720, max(520, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    assert window.focus_title_edit.text() == "리포트 작성"
    assert window.planned_minutes_spin.value() == 45
    assert window.idle_cutoff_spin.value() == 90
    assert window.use_focus_target_check.isChecked()

    # Start button still drives the focus session through the live signal.
    window.start_focus_button.click()
    app.processEvents()
    assert window.focus_timer.session is not None
    assert window.focus_timer.session.status == "running"
    window.complete_focus_button.click()
    app.processEvents()
    assert window.focus_timer.session.status != "running"
    window.close()


def test_time_spinboxes_step_by_five_but_allow_free_text(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    # Button/step changes move in units of 5 for every time spinbox.
    assert window.planned_minutes_spin.singleStep() == 5
    assert window.idle_cutoff_spin.singleStep() == 5
    assert window.pomodoro_minutes_spin.singleStep() == 5
    assert window.break_minutes_spin.singleStep() == 5

    # stepBy uses the single step (what the +/- buttons do).
    window.pomodoro_minutes_spin.setValue(25)
    window.pomodoro_minutes_spin.stepBy(1)
    assert window.pomodoro_minutes_spin.value() == 30

    # Typing an arbitrary (non-multiple-of-5) value is still accepted.
    window.planned_minutes_spin.setValue(23)
    assert window.planned_minutes_spin.value() == 23
    window.close()


def test_focus_session_title_shows_beside_status_when_running(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    # Idle: no title beside the status box.
    assert not window.focus_session_title_label.isVisible()

    window.focus_title_edit.setText("리포트 작성")
    window.start_focus_button.click()
    app.processEvents()
    assert window.focus_session_title_label.isVisible()
    assert window.focus_session_title_label.text() == "리포트 작성"

    # After completion the title is hidden again.
    window.complete_focus_button.click()
    app.processEvents()
    assert not window.focus_session_title_label.isVisible()
    window.close()


def test_focus_form_can_be_collapsed_and_expanded(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(560, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    # Default: collapsed (form lives in a floating overlay that is hidden).
    assert not window.focus_form_panel.isVisible()
    assert window.focus_form_toggle.text().startswith("설정 펼치기")
    # With the show-grid preference on (default), the status grid is visible.
    assert window.preferences.show_focus_status_grid is True
    assert window.focus_status_grid.isVisible()

    # Expanding shows the floating overlay dropdown with the form.
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    assert window.focus_form_panel.isVisible()
    assert window.focus_form_overlay is not None
    assert window.focus_form_overlay.isVisible()
    assert window.focus_form_toggle.text().startswith("설정 접기")
    # The grid stays visible behind/above the floating overlay while expanded.
    assert window.focus_status_grid.isVisible()

    # Collapsing hides the overlay again; the grid remains visible.
    window.focus_form_toggle.setChecked(False)
    app.processEvents()
    assert not window.focus_form_overlay.isVisible()
    assert not window.focus_form_panel.isVisible()
    assert window.focus_status_grid.isVisible()
    window.close()


def test_auto_collapse_pref_persists_and_collapses_form_on_start(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(560, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    # Default off: starting focus leaves the form expanded.
    assert window.preferences.auto_collapse_focus_form is False

    # Enabling via the same path the context-menu action uses persists it.
    window._set_auto_collapse_focus_form(True)
    assert window.preferences.auto_collapse_focus_form is True
    assert repository.get_preferences().auto_collapse_focus_form is True

    # Expand the form first, then start focus.
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    assert window.focus_form_panel.isVisible()
    window.focus_title_edit.setText("집필")
    window.start_focus_button.click()
    app.processEvents()
    # Form auto-collapses on start when the preference is on.
    assert not window.focus_form_panel.isVisible()

    window.complete_focus_button.click()
    app.processEvents()
    window.close()


def test_focus_settings_dialog_exposes_keep_expanded_option(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    assert preferences.keep_focus_form_expanded is False

    dialog = FocusActivitySettingsDialog(preferences)
    app.processEvents()
    # Reflects the stored preference and reports the live checkbox state.
    assert dialog.keep_focus_form_expanded() is False
    dialog.keep_expanded_check.setChecked(True)
    assert dialog.keep_focus_form_expanded() is True
    dialog.close()


def test_keep_focus_form_expanded_pins_form_inline_and_hides_toggle(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(600, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    # Default (non-pinned): the toggle is shown and the form is hidden inline.
    assert window.focus_form_toggle.isVisible()
    assert not window.focus_form_panel.isVisible()

    def fake_exec(self) -> int:
        self.keep_expanded_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module.FocusActivitySettingsDialog, "exec", fake_exec)
    window.show_focus_activity_settings()
    app.processEvents()

    # Persisted to memory and SQLite.
    assert window.preferences.keep_focus_form_expanded is True
    assert repository.get_preferences().keep_focus_form_expanded is True
    # Toggle hidden; the setup form + color row are visible inline in the panel
    # (docked back into the panel, not a floating overlay).
    assert not window.focus_form_toggle.isVisible()
    assert window.focus_form_panel.isVisible()
    assert window.focus_color_row.isVisible()
    assert window.focus_form_panel.parentWidget() is window.focus_content_panel
    assert window.focus_color_row.parentWidget() is window.focus_content_panel
    assert window.focus_form_overlay is None
    # The status grid stays visible alongside the pinned inline setup form when
    # the show-grid preference is on (default True).
    assert window.preferences.show_focus_status_grid is True
    assert window.focus_status_grid.isVisible()
    window.close()


def test_keep_focus_form_expanded_after_overlay_reparents_back_without_leaks(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(600, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    # Open the overlay first (non-pinned), so the form lives in the overlay.
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    assert window.focus_form_overlay is not None
    assert window.focus_form_panel.parentWidget() is window.focus_form_overlay
    layout = window.focus_panel_layout

    def fake_exec(self) -> int:
        self.keep_expanded_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module.FocusActivitySettingsDialog, "exec", fake_exec)
    window.show_focus_activity_settings()
    app.processEvents()

    # Enabling pinned mode reparents the form back inline and drops the overlay,
    # leaving exactly one copy of the form in the panel layout.
    assert window.focus_form_overlay is None
    assert window.focus_form_panel.parentWidget() is window.focus_content_panel
    assert layout.indexOf(window.focus_form_panel) != -1
    assert layout.indexOf(window.focus_color_row) != -1
    assert window.focus_form_panel.isVisible()
    assert not window.focus_form_toggle.isVisible()
    window.close()


def test_keep_focus_form_expanded_keeps_color_row_usable_when_narrow(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    # Pin the setup form inline through the same dialog path the settings menu uses.
    def fake_exec(self) -> int:
        self.keep_expanded_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module.FocusActivitySettingsDialog, "exec", fake_exec)
    window.show_focus_activity_settings()
    app.processEvents()
    assert window.preferences.keep_focus_form_expanded is True

    # Squeeze the pinned panel down to the reported ~620px width and re-lay it out.
    window.focus_content_panel.setFixedSize(620, max(850, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    # The pinned setup form + color row stay docked inline; the toggle stays hidden.
    assert window.focus_form_panel.isVisible()
    assert window.focus_color_row.isVisible()
    assert not window.focus_form_toggle.isVisible()

    # Regression: at this narrow pinned width the enclosing FeatureCell relaxes
    # every descendant's minimum width to 0, which used to collapse the focus
    # color swatch to its 8px sizeHint and the "색 선택" button to its 68px
    # sizeHint beside the row stretch. The swatch must keep a real 40x24 size and
    # the button its stabilized width/height so the color row stays usable.
    assert window.focus_color_swatch.width() == 40
    assert window.focus_color_swatch.height() == 24
    assert window.focus_color_button.width() >= 96
    assert window.focus_color_button.height() == PANEL_CONTROL_HEIGHT

    # Showing the status grid stays honored while the form is pinned inline.
    assert window.preferences.show_focus_status_grid is True
    assert window.focus_status_grid.isVisible()
    window.close()


def test_keep_focus_form_expanded_keeps_focus_rate_bar_text_readable_when_short(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    def fake_exec(self) -> int:
        self.keep_expanded_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module.FocusActivitySettingsDialog, "exec", fake_exec)
    window.show_focus_activity_settings()
    app.processEvents()

    # Match the compact focus panel size from the screenshot: pinned settings make
    # the dashboard tight, and compact width forces the focus-rate display to bar mode.
    window.focus_content_panel.setFixedSize(620, 312)
    window.update_focus_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    assert window.preferences.keep_focus_form_expanded is True
    assert window.focus_ratio_stack.currentIndex() == 1
    assert window.focus_ratio_label.height() >= window.focus_ratio_label.sizeHint().height()
    assert window.focus_ratio_label.geometry().bottom() < window.focus_ratio_bar.geometry().top()
    window.close()


def test_collapsed_focus_panel_expands_status_grid_instead_of_blank_spacer(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(454, 960)
    window.update_focus_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    layout = window.focus_panel_layout
    toggle_index = layout.indexOf(window.focus_form_toggle)
    assert toggle_index != -1

    expanding_spacer_indices = [
        index
        for index in range(layout.count())
        if layout.itemAt(index).spacerItem() is not None
        and bool(layout.itemAt(index).spacerItem().expandingDirections() & Qt.Orientation.Vertical)
    ]
    # Tall collapsed focus panels should give the extra height to the status grid,
    # not to a meaningless blank stretch above the settings toggle.
    assert not expanding_spacer_indices
    assert window.focus_status_grid.rowCount() > FOCUS_STATUS_MIN_ROWS

    panel = window.focus_content_panel
    grid_bottom = (
        window.focus_status_grid.mapTo(panel, window.focus_status_grid.rect().topLeft()).y()
        + window.focus_status_grid.height()
    )
    toggle_top = window.focus_form_toggle.mapTo(panel, window.focus_form_toggle.rect().topLeft()).y()
    assert 0 <= toggle_top - grid_bottom <= 24
    window.close()


def test_focus_fade_cell_color_three_stages() -> None:
    base = QColor("#b9a7e8")
    expected_half = QColor((base.red() + 255) // 2, (base.green() + 255) // 2, (base.blue() + 255) // 2)
    # Little away time -> full focus color.
    assert _focus_activity_cell_color(0, "#b9a7e8").name().lower() == "#b9a7e8"
    assert _focus_activity_cell_color(2 * 60, "#b9a7e8").name().lower() == "#b9a7e8"
    # Past the half threshold (3 min away) -> halfway to white.
    assert _focus_activity_cell_color(4 * 60, "#b9a7e8").name().lower() == expected_half.name().lower()
    # Past the white threshold (6 min away) -> white.
    assert _focus_activity_cell_color(7 * 60, "#b9a7e8").name().lower() == "#ffffff"


def test_focus_fade_cell_color_respects_custom_thresholds() -> None:
    # half=2, white=5: 1 min away -> full, 4 min -> half (neither full nor white), 6 min -> white.
    assert _focus_activity_cell_color(60, "#b9a7e8", half_minutes=2, white_minutes=5).name().lower() == "#b9a7e8"
    mid = _focus_activity_cell_color(4 * 60, "#b9a7e8", half_minutes=2, white_minutes=5).name().lower()
    assert mid not in ("#b9a7e8", "#ffffff")
    assert _focus_activity_cell_color(6 * 60, "#b9a7e8", half_minutes=2, white_minutes=5).name().lower() == "#ffffff"


def test_focus_status_grid_fades_cells_and_grows_rows() -> None:
    app = _app()
    grid = FocusStatusGrid()
    # 20 minutes elapsed -> 2 reached cells. bucket0 away 1min (full), bucket1 away 4min (half).
    grid.update_status([1 * 60, 4 * 60], 20 * 60, "#b9a7e8")
    app.processEvents()
    assert grid.rowCount() == 3  # 3 hours (3 rows) visible by default
    assert grid.rowHeight(0) == FOCUS_STATUS_ROW_HEIGHT  # cells use the configured row height
    base = QColor("#b9a7e8")
    half = QColor((base.red() + 255) // 2, (base.green() + 255) // 2, (base.blue() + 255) // 2)
    assert grid.item(0, 0).background().color().name().lower() == "#b9a7e8"
    assert grid.item(0, 1).background().color().name().lower() == half.name().lower()
    # An unreached cell is the neutral empty color, not a focus shade.
    assert grid.item(0, 2).background().color().name().lower() == "#eef0f4"

    # 3h10m elapsed -> 19 reached buckets -> grid grows to 4 rows and scrolls.
    grid.update_status([], 190 * 60, "#b9a7e8")
    app.processEvents()
    assert grid.rowCount() == 4


def test_focus_away_buckets_count_only_away_time(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_title_edit.setText("집중")
    window.start_focus_button.click()
    app.processEvents()

    # Buckets reset on start.
    assert window._focus_away_buckets == []

    session = window.focus_timer.session
    # A focused tick advances elapsed but adds NO away time to the cell.
    session.focused_seconds = 30
    window.focus_timer.segment_type = "focused"
    window._record_focus_away(session)
    assert window._focus_away_buckets == [0]

    # An away tick adds away seconds to the current 10-minute bucket.
    session.away_seconds = 40
    window.focus_timer.segment_type = "away"
    window._record_focus_away(session)
    assert window._focus_away_buckets[0] == 40

    window.complete_focus_button.click()
    app.processEvents()
    window.close()


def test_focus_status_grid_visible_when_enabled_regardless_of_form_state(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(600, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    # Default: collapsed + preference on -> grid visible.
    assert window.preferences.show_focus_status_grid is True
    assert window.focus_status_grid.isVisible()

    # Expanding the form keeps the grid visible (it stays above the overlay).
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    assert window.focus_form_overlay is not None and window.focus_form_overlay.isVisible()
    assert window.focus_status_grid.isVisible()

    # Collapsing again keeps the grid visible.
    window.focus_form_toggle.setChecked(False)
    app.processEvents()
    assert window.focus_status_grid.isVisible()

    # Turning the preference off hides it regardless of form state.
    window.preferences.show_focus_status_grid = False
    window.update_focus_panel_responsive_layout()
    app.processEvents()
    assert not window.focus_status_grid.isVisible()
    window.close()


def test_focus_activity_settings_dialog_round_trips(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_focus_status_grid = False
    preferences.auto_collapse_focus_form = True
    preferences.focus_fade_half_minutes = 2
    preferences.focus_fade_white_minutes = 7

    dialog = FocusActivitySettingsDialog(preferences)
    app.processEvents()
    assert dialog.show_focus_status_grid() is False
    assert dialog.auto_collapse_focus_form() is True
    assert dialog.fade_half_minutes() == 2
    assert dialog.fade_white_minutes() == 7

    dialog.show_grid_check.setChecked(True)
    dialog.white_minutes_spin.setValue(5)
    assert dialog.show_focus_status_grid() is True
    assert dialog.fade_white_minutes() == 5
    dialog.close()


def test_focus_status_cell_delegate_reads_color_from_qbrush() -> None:
    # QTableWidgetItem.setBackground stores a QBrush, so the delegate must read the
    # brush's color instead of falling back to the empty shade (the invisible-color bug).
    _app()
    from_brush = FocusStatusCellDelegate._fill_color_from_data(QBrush(QColor("#3366cc")))
    assert from_brush.name().lower() == "#3366cc"
    from_color = FocusStatusCellDelegate._fill_color_from_data(QColor("#112233"))
    assert from_color.name().lower() == "#112233"
    # Missing/invalid data falls back to the neutral empty color, never a crash.
    assert FocusStatusCellDelegate._fill_color_from_data(None).name().lower() == FOCUS_STATUS_EMPTY_COLOR
    assert FocusStatusCellDelegate._fill_color_from_data(QColor()).name().lower() == FOCUS_STATUS_EMPTY_COLOR


def test_focus_status_grid_fills_first_cell_immediately_with_focus_color() -> None:
    app = _app()
    grid = FocusStatusGrid()
    # 1 second of elapsed time fills exactly the first cell with the focus color,
    # not only after a full 10-minute bucket.
    grid.update_status([], 1, "#3366cc")
    app.processEvents()
    assert grid.item(0, 0).background().color().name().lower() == "#3366cc"
    assert grid.item(0, 1).background().color().name().lower() == FOCUS_STATUS_EMPTY_COLOR

    # Ceil bucket math: 600s still fills exactly one cell; 601s fills two.
    grid.update_status([], 600, "#3366cc")
    app.processEvents()
    assert grid.item(0, 0).background().color().name().lower() == "#3366cc"
    assert grid.item(0, 1).background().color().name().lower() == FOCUS_STATUS_EMPTY_COLOR
    grid.update_status([], 601, "#3366cc")
    app.processEvents()
    assert grid.item(0, 1).background().color().name().lower() == "#3366cc"


def test_focus_status_grid_cells_are_enlarged() -> None:
    app = _app()
    grid = FocusStatusGrid()
    app.processEvents()
    # Cells are visibly taller than the previous 18px row height.
    assert FOCUS_STATUS_ROW_HEIGHT > 18
    assert grid.rowHeight(0) == FOCUS_STATUS_ROW_HEIGHT
    # Still a 6-column grid after enlarging the cells.
    assert grid.columnCount() == 6
    # The minimum chrome height keeps 3 rows visible, while the grid can expand
    # vertically when a taller focus panel has useful space to offer.
    expected_chrome = FOCUS_STATUS_ROW_HEIGHT * FOCUS_STATUS_MIN_ROWS + 2 * grid.frameWidth() + 1
    assert grid._chrome_height() == expected_chrome
    assert grid.minimumHeight() == expected_chrome
    assert grid.maximumHeight() > expected_chrome

    grid.resize(240, grid._chrome_height(7))
    grid.show()
    app.processEvents()
    assert grid.rowCount() >= 7
    grid.close()


def test_focus_status_cell_paints_focus_color_for_first_cell() -> None:
    app = _app()
    grid = FocusStatusGrid()
    grid.set_shape("dot")
    grid.setFixedSize(180, 80)
    grid.show()
    app.processEvents()
    grid.update_status([], 60, "#3366cc")  # 1 minute elapsed -> first cell reached
    app.processEvents()
    rect = grid.visualItemRect(grid.item(0, 0))
    assert rect.width() > 0 and rect.height() > 0
    pixmap = QPixmap(grid.viewport().size())
    pixmap.fill(QColor("#000000"))
    grid.viewport().render(pixmap)
    sampled = pixmap.toImage().pixelColor(rect.center())
    # The painted dot carries the focus color, proving the QBrush color is honored.
    assert sampled.name().lower() == "#3366cc"
    grid.close()


def test_focus_status_grid_set_and_get_shape() -> None:
    app = _app()
    grid = FocusStatusGrid()
    assert grid.shape() == "dot"  # initialized to the default shape
    for shape in FOCUS_STATUS_CELL_SHAPES:
        grid.set_shape(shape)
        assert grid.shape() == shape
    grid.set_shape("heart")
    grid.set_shape("triangle")  # unknown shapes normalize back to the default
    assert grid.shape() == "dot"
    app.processEvents()


def test_focus_activity_settings_dialog_round_trips_shape(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    assert preferences.focus_status_cell_shape == "dot"

    dialog = FocusActivitySettingsDialog(preferences)
    app.processEvents()
    assert dialog.focus_cell_shape() == "dot"

    wave_index = dialog.shape_combo.findData("wave")
    assert wave_index >= 0
    dialog.shape_combo.setCurrentIndex(wave_index)
    assert dialog.focus_cell_shape() == "wave"
    dialog.close()


def test_focus_activity_settings_persists_and_applies_shape(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    assert window.focus_status_grid.shape() == "dot"

    def fake_exec(self) -> int:
        index = self.shape_combo.findData("heart")
        self.shape_combo.setCurrentIndex(index)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module.FocusActivitySettingsDialog, "exec", fake_exec)
    window.show_focus_activity_settings()
    app.processEvents()

    # Selection is persisted to SQLite and applied to the live grid immediately.
    assert window.preferences.focus_status_cell_shape == "heart"
    assert window.focus_status_grid.shape() == "heart"
    assert repository.get_preferences().focus_status_cell_shape == "heart"
    window.close()


def test_focus_color_picker_in_form_and_grid_above_toggle(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(600, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    layout = window.focus_panel_layout
    grid_index = layout.indexOf(window.focus_status_grid)
    toggle_index = layout.indexOf(window.focus_form_toggle)
    assert grid_index != -1 and toggle_index != -1
    # The status grid sits ABOVE the collapse toggle.
    assert grid_index < toggle_index

    # The focus-color picker lives inside the floating overlay dropdown.
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    assert window.focus_color_row.isVisible()  # shown when expanded (overlay open)
    window.focus_form_toggle.setChecked(False)
    app.processEvents()
    assert not window.focus_color_row.isVisible()  # hidden when collapsed
    window.close()


def test_focus_handle_exposes_settings_callback(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    # The focus feature box routes the handle right-click to the settings dialog,
    # while ordinary panels do not get this entry.
    assert window.feature_boxes["focus"].settings_callback is not None
    assert window.feature_boxes["quick_memo"].settings_callback is None
    window.close()


def test_focus_panel_target_controls_start_collapsed_and_splitter_is_slim(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(520, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    assert not window.target_combo.isVisible()
    assert not window.focus_targets_list.isVisible()
    assert not window.remove_target_button.isVisible()
    assert "width: 4px;" in window.styleSheet()
    assert "height: 4px;" in window.styleSheet()

    # Target controls live in the floating overlay form; expand it first.
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    window.use_focus_target_check.setChecked(True)
    app.processEvents()
    assert window.target_combo.isVisible()
    assert window.focus_targets_list.isVisible()
    assert not window.remove_target_button.isVisible()
    assert window.focus_targets_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    window.close()


def test_focus_panel_reflows_controls_when_narrow(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()
    window.focus_content_panel.setFixedSize(720, max(520, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()
    app.processEvents()

    form = window.focus_form
    planned_position = form.getItemPosition(form.indexOf(window.planned_minutes_spin))
    idle_label_position = form.getItemPosition(form.indexOf(window.idle_cutoff_label))
    idle_spin_position = form.getItemPosition(form.indexOf(window.idle_cutoff_spin))
    assert planned_position[0] == idle_label_position[0] == idle_spin_position[0]
    assert planned_position[1] < idle_label_position[1] < idle_spin_position[1]

    window.focus_content_panel.setFixedSize(340, max(420, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()

    assert window.focus_meter_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window.focus_metrics_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert window.focus_button_row.direction() == QBoxLayout.Direction.TopToBottom
    assert "font-size" in window.remaining_time_label.styleSheet()

    window.focus_content_panel.setFixedSize(720, max(520, window.focus_content_panel.height()))
    window.update_focus_panel_responsive_layout()

    assert window.focus_meter_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window.focus_button_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window.remaining_time_label.styleSheet() == ""
    window.close()


def test_focus_panel_stacks_target_controls_when_compact(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    window.use_focus_target_check.setChecked(True)
    app.processEvents()
    window.focus_content_panel.setFixedSize(500, 620)
    window.update_focus_panel_responsive_layout()

    form = window.focus_form
    combo_position = form.getItemPosition(form.indexOf(window.target_combo))
    actions_position = form.getItemPosition(form.indexOf(window.target_action_box))
    list_position = form.getItemPosition(form.indexOf(window.focus_targets_list))

    assert window.target_combo.isVisible()
    assert window.focus_targets_list.isVisible()
    assert not window.remove_target_button.isVisible()
    assert window.focus_task_label.text() == ""
    assert window.focus_task_label.isHidden()
    assert window.focus_targets_label.text() == ""
    assert window.focus_targets_label.isHidden()
    assert combo_position[:4] == (2, 0, 1, 4)
    assert actions_position[:4] == (3, 0, 1, 4)
    assert list_position[:4] == (4, 0, 1, 4)
    assert window.focus_detail_label.isHidden()
    assert window.focus_ratio_card.isVisible()
    assert window.focus_ratio_card.maximumHeight() <= 108
    assert window.focus_ratio_stack.currentIndex() == 1
    assert window.focus_status_label.maximumHeight() <= 34
    assert not window.focus_status_label.wordWrap()
    assert all(card.isVisible() for card in window.focus_metric_cards)
    assert all(card.property("compactMetric") for card in window.focus_metric_cards)
    assert all(card.maximumHeight() <= 48 for card in window.focus_metric_cards)
    assert window.focus_header_label.text() == ""
    assert window.focus_header_label.isHidden()
    assert "font-size: 34px" in window.remaining_time_label.styleSheet()
    window.close()


def test_focus_panel_uses_compact_meter_before_it_gets_cramped(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.focus_content_panel.setFixedSize(620, 560)
    window.update_focus_panel_responsive_layout()

    assert window.focus_meter_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window.focus_ratio_card.isVisible()
    assert window.focus_ratio_card.maximumHeight() <= 108
    assert window.focus_ratio_stack.currentIndex() == 1
    assert window.focus_status_label.height() <= 34
    assert all(card.isVisible() for card in window.focus_metric_cards)
    assert window.focus_metrics_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert all(card.property("compactMetric") for card in window.focus_metric_cards)
    window.close()


def test_focus_panel_keeps_timer_usable_when_tiny(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.use_focus_target_check.setChecked(True)
    app.processEvents()
    window.focus_content_panel.setFixedSize(240, 300)
    window.update_focus_panel_responsive_layout()

    assert window.focus_form_panel.isHidden()
    assert window.focus_ratio_card.isHidden()
    assert all(card.isHidden() for card in window.focus_metric_cards)
    assert window.focus_detail_label.isHidden()
    assert window.remaining_time_label.isVisible()
    assert window.start_focus_button.isVisible()
    assert window.pause_focus_button.isVisible()
    assert window.complete_focus_button.isVisible()
    assert window.focus_button_row.direction() == QBoxLayout.Direction.TopToBottom
    assert "font-size: 22px" in window.remaining_time_label.styleSheet()

    window.focus_content_panel.setFixedSize(720, 620)
    window.focus_form_toggle.setChecked(True)
    app.processEvents()
    window.update_focus_panel_responsive_layout()
    assert window.focus_form_panel.isVisible()
    assert window.focus_ratio_card.isVisible()
    assert all(card.isVisible() for card in window.focus_metric_cards)
    window.close()


def test_focus_panel_pinned_target_controls_do_not_overlap_when_squeezed(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    # Pin the setup form inline (same path the settings dialog uses) and turn on
    # the 화면 지정 사용 target controls so the form grid carries the target
    # combo/action/list rows plus the duration spin row.
    def fake_exec(self) -> int:
        self.keep_expanded_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module.FocusActivitySettingsDialog, "exec", fake_exec)
    window.show_focus_activity_settings()
    app.processEvents()
    assert window.preferences.keep_focus_form_expanded is True
    window.use_focus_target_check.setChecked(True)
    app.processEvents()

    # Squeeze the pinned panel to the reported ~620x650. The form grid used to
    # compress below its content height so the target combo bled into the action
    # row, the list bled into the duration spins, and the action box collapsed.
    window.focus_content_panel.setFixedSize(620, 650)
    window.update_focus_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    panel = window.focus_content_panel

    def top_in(widget) -> int:
        return widget.mapTo(panel, QPoint(0, 0)).y()

    assert window.target_combo.isVisible()
    assert window.focus_targets_list.isVisible()
    # Stabilized control heights are retained, not crushed.
    assert window.target_combo.height() == PANEL_CONTROL_HEIGHT
    assert window.planned_minutes_spin.height() == PANEL_CONTROL_HEIGHT
    assert window.idle_cutoff_spin.height() == PANEL_CONTROL_HEIGHT
    assert window.target_action_box.height() >= PANEL_CONTROL_HEIGHT - 4

    # Rows stack top-to-bottom without overlapping: combo -> action -> list ->
    # duration spins; the planned/idle spins share one row side by side.
    combo_bottom = top_in(window.target_combo) + window.target_combo.height()
    action_top = top_in(window.target_action_box)
    action_bottom = action_top + window.target_action_box.height()
    list_top = top_in(window.focus_targets_list)
    list_bottom = list_top + window.focus_targets_list.height()
    spin_top = top_in(window.planned_minutes_spin)
    assert combo_bottom <= action_top
    assert action_bottom <= list_top
    assert list_bottom <= spin_top
    assert top_in(window.planned_minutes_spin) == top_in(window.idle_cutoff_spin)
    for widget in (
        window.focus_dashboard_card,
        window.focus_status_grid,
        window.focus_form_panel,
        window.focus_color_row,
        window.target_combo,
        window.target_action_box,
        window.focus_targets_list,
        window.planned_minutes_spin,
        window.idle_cutoff_spin,
    ):
        _assert_visible_widget_within_parent(widget, panel)
    window.close()


def test_focus_ratio_card_stays_readable_in_compact_path(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # Compact width (< 680 triggers the compact responsive path) but >= 420 so the
    # 집중률 ratio card is NOT in the dense path that hides it. A short panel used
    # to compress the timer dashboard so the ratio card overlapped the progress
    # bar, metric cards, and the 시작 button stacked below it.
    window.focus_content_panel.setFixedSize(500, 300)
    window.update_focus_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    panel = window.focus_content_panel
    ratio = window.focus_ratio_card
    assert ratio.isVisible()
    # The card and its ring/bar stack stay readable, not collapsed.
    assert ratio.height() >= 60
    assert window.focus_ratio_stack.height() >= 28

    def span(widget) -> tuple[int, int]:
        top = widget.mapTo(panel, QPoint(0, 0)).y()
        return top, top + widget.height()

    ratio_top, ratio_bottom = span(ratio)
    for widget in (window.focus_progress, window.focus_metric_cards[0], window.start_focus_button):
        if not widget.isVisible():
            continue
        widget_top, widget_bottom = span(widget)
        assert not (ratio_top < widget_bottom and widget_top < ratio_bottom), (
            f"ratio card overlaps {widget.objectName() or widget.__class__.__name__}"
        )
    for widget in (
        window.focus_dashboard_card,
        window.focus_status_grid,
        window.focus_form_toggle,
        window.focus_progress,
        window.focus_metric_cards[0],
        window.start_focus_button,
    ):
        _assert_visible_widget_within_parent(widget, panel)
    window.close()


def test_focus_widget_expands_from_timer_only_to_full_controls(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    dialog = FocusWidgetDialog(window)
    dialog.show()
    app.processEvents()

    dialog.resize(220, 130)
    dialog.update_responsive_layout()
    assert dialog.time_label.isVisible()
    assert dialog.title_label.isHidden()
    assert dialog.status_label.isHidden()
    assert dialog.progress.isHidden()
    assert dialog.start_panel.isHidden()
    assert dialog.pause_button.isVisible()
    assert dialog.done_button.isVisible()

    dialog.resize(520, 360)
    dialog.update_responsive_layout()
    assert dialog.title_label.isVisible()
    assert dialog.status_label.isVisible()
    assert dialog.progress.isVisible()
    assert dialog.detail_label.isVisible()
    assert dialog.start_panel.isVisible()
    assert dialog.dialog_use_target_check.isVisible()
    assert dialog.title_edit.isVisible()
    assert dialog.planned_spin.isVisible()
    assert dialog.idle_spin.isVisible()
    dialog.close()
    window.close()


def test_focus_widget_large_mode_controls_target_windows(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)

    class Provider:
        def list_open_windows(self) -> list[ActiveWindowSnapshot]:
            return [
                ActiveWindowSnapshot("code.exe", "main.py"),
                ActiveWindowSnapshot("chrome.exe", "Schedule Helper"),
                ActiveWindowSnapshot("notion.exe", "Project notes"),
            ]

        def current_window(self) -> ActiveWindowSnapshot | None:
            return ActiveWindowSnapshot("code.exe", "main.py")

    window.window_provider = Provider()
    dialog = FocusWidgetDialog(window)
    dialog.resize(560, 420)
    dialog.show()
    app.processEvents()

    dialog.dialog_use_target_check.setChecked(True)
    app.processEvents()

    assert window.use_focus_target_check.isChecked()
    assert dialog.dialog_target_combo.isVisible()
    assert dialog.dialog_targets_list.isVisible()
    assert not dialog.dialog_remove_target_button.isVisible()
    assert dialog.dialog_targets_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert dialog.dialog_targets_list.minimumHeight() >= 82
    assert dialog.dialog_targets_list.maximumHeight() >= 100
    assert dialog.dialog_target_combo.view().cursor().shape() == Qt.CursorShape.PointingHandCursor

    dialog.add_target_from_dialog_index(dialog.dialog_target_combo.model().index(dialog.dialog_target_combo.currentIndex(), 0))
    app.processEvents()
    assert window.focus_targets_list.count() == 1
    assert dialog.dialog_targets_list.count() == 1

    dialog.title_edit.setText("Draft plan")
    dialog.planned_spin.setValue(40)
    dialog.idle_spin.setValue(80)
    app.processEvents()
    assert window.focus_title_edit.text() == "Draft plan"
    assert window.planned_minutes_spin.value() == 40
    assert window.idle_cutoff_spin.value() == 80
    dialog.close()
    window.close()


def test_pomodoro_panel_ports_widget_progress_card(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    assert window.pomodoro_progress.value() == 0
    assert window.pomodoro_detail_label.text() == ""
    assert window.pomodoro_detail_label.isHidden()

    window.pomodoro_mode = "focus"
    window.pomodoro_total_seconds = 1500
    window.pomodoro_remaining_seconds = 900
    window.pomodoro_paused = False
    window.update_pomodoro_display()

    assert window.pomodoro_status_label.text() == "집중 중"
    assert window.pomodoro_time_label.text() == "15:00"
    assert window.pomodoro_progress.value() == 400
    assert window.pomodoro_detail_label.text() == ""
    assert window.pomodoro_detail_label.isHidden()
    window.close()


def test_pomodoro_panel_keeps_timer_and_controls_readable_when_short(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # A short pomodoro panel (the reported ~620x170 squeeze) used to crush the
    # time label to 0px and collapse the controls panel to ~43px so the 분 spin
    # rows overlapped the 시작/일시정지/초기화 button row.
    window.pomodoro_panel.setFixedSize(620, 170)
    window.update_pomodoro_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    timer_card = window.pomodoro_panel.findChild(QWidget, "pomodoroTimerCard")
    controls_panel = window.pomodoro_panel.findChild(QWidget, "pomodoroControlsPanel")
    assert timer_card is not None
    assert controls_panel is not None

    # Timer label stays readable (non-zero), not crushed to 0px.
    assert window.pomodoro_time_label.height() > 0
    # The short mode hides duration inputs first and keeps the primary action row
    # readable instead of painting half of the full control stack outside the card.
    assert not window.pomodoro_minutes_spin.isVisibleTo(window.pomodoro_panel)
    assert not window.break_minutes_spin.isVisibleTo(window.pomodoro_panel)
    assert window.start_pomodoro_button.isVisibleTo(window.pomodoro_panel)
    assert window.pomodoro_minutes_spin.height() == PANEL_CONTROL_HEIGHT
    assert window.break_minutes_spin.height() == PANEL_CONTROL_HEIGHT
    assert window.start_pomodoro_button.height() == PANEL_CONTROL_HEIGHT
    # The visible cards keep enough height to contain their content (no internal fold).
    assert timer_card.height() >= window.pomodoro_time_label.height()
    timer_bottom = (
        timer_card.mapTo(window.pomodoro_panel, QPoint(0, 0)).y()
        + timer_card.height()
    )
    controls_top = controls_panel.mapTo(window.pomodoro_panel, QPoint(0, 0)).y()
    assert timer_bottom <= controls_top
    for widget in (
        timer_card,
        controls_panel,
        window.pomodoro_time_label,
        window.pomodoro_minutes_spin,
        window.break_minutes_spin,
        window.start_pomodoro_button,
        window.pause_pomodoro_button,
        window.reset_pomodoro_button,
    ):
        _assert_visible_widget_within_parent(widget, window.pomodoro_panel)
    window.close()


def test_pomodoro_panel_compacts_duration_inputs_before_controls_clip(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # At the screenshot-like short height, the old full stack overlapped the timer
    # card and clipped the button row. Compact mode should keep timer and buttons
    # separate, hiding only the duration inputs until the panel is taller.
    window.pomodoro_panel.setFixedSize(620, 257)
    window.update_pomodoro_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    timer_bottom = (
        window.pomodoro_timer_card.mapTo(window.pomodoro_panel, QPoint(0, 0)).y()
        + window.pomodoro_timer_card.height()
    )
    controls_top = window.pomodoro_controls_panel.mapTo(window.pomodoro_panel, QPoint(0, 0)).y()
    assert timer_bottom <= controls_top
    assert not window.pomodoro_minutes_spin.isVisibleTo(window.pomodoro_panel)
    assert not window.break_minutes_spin.isVisibleTo(window.pomodoro_panel)
    assert window.start_pomodoro_button.isVisibleTo(window.pomodoro_panel)
    assert window.pause_pomodoro_button.isVisibleTo(window.pomodoro_panel)
    assert window.reset_pomodoro_button.isVisibleTo(window.pomodoro_panel)
    for widget in (
        window.pomodoro_timer_card,
        window.pomodoro_controls_panel,
        window.pomodoro_time_label,
        window.start_pomodoro_button,
        window.pause_pomodoro_button,
        window.reset_pomodoro_button,
    ):
        _assert_visible_widget_within_parent(widget, window.pomodoro_panel)

    window.pomodoro_panel.setFixedSize(620, 320)
    window.update_pomodoro_panel_responsive_layout()
    app.processEvents()
    assert window.pomodoro_minutes_spin.isVisibleTo(window.pomodoro_panel)
    assert window.break_minutes_spin.isVisibleTo(window.pomodoro_panel)
    window.close()


def test_pomodoro_status_badge_keeps_natural_height_when_timer_card_expands(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # When the timer card receives extra height, the status badge should remain a
    # compact badge; it should not stretch into a tall vertical box.
    window.pomodoro_panel.setFixedSize(433, 380)
    window.update_pomodoro_panel_responsive_layout()
    app.processEvents()
    app.processEvents()

    assert window.pomodoro_status_label.isVisibleTo(window.pomodoro_panel)
    assert window.pomodoro_status_label.height() <= 32
    assert window.pomodoro_status_label.height() >= window.pomodoro_status_label.sizeHint().height()
    window.close()


def test_same_size_feature_panels_share_inner_rhythm(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.focus_content_panel.setFixedSize(560, 420)
    window.update_focus_panel_responsive_layout()
    window.pomodoro_panel.setFixedSize(560, 320)
    window.update_pomodoro_panel_responsive_layout()
    window.memo_content_panel.setFixedSize(560, 420)
    window.update_memo_panel_responsive_layout()
    window.link_favorites_content_panel.setFixedSize(560, 260)
    window.update_link_favorites_responsive_layout()
    window.today_checklist_widget.setFixedSize(560, 420)
    window.timeline_panel.setFixedSize(760, 620)
    window.inline_timeline_widget.setFixedSize(700, 520)
    window.inline_timeline_widget.update_panel_rhythm()
    app.processEvents()

    layouts = [
        window.focus_panel_layout,
        window.pomodoro_panel_layout,
        window.memo_panel_layout,
        window.link_favorites_panel_layout,
        window.today_checklist_widget.panel_rhythm_layout,
        window.inline_timeline_widget.panel_rhythm_layout,
    ]
    assert [_margins_tuple(layout) for layout in layouts] == [(16, 14, 16, 14)] * len(layouts)
    assert [layout.spacing() for layout in layouts] == [10] * len(layouts)

    assert window.pomodoro_input_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window.pomodoro_button_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window.pomodoro_panel.findChild(QWidget, "pomodoroTimerCard") is not None
    assert window.pomodoro_panel.findChild(QWidget, "pomodoroControlsPanel") is not None
    assert _margins_tuple(window.pomodoro_timer_card_layout) == (16, 14, 16, 14)
    assert "QWidget#pomodoroTimerCard" in window.styleSheet()
    assert "QWidget#pomodoroControlsPanel" in window.styleSheet()

    window.pomodoro_panel.setFixedSize(240, 220)
    window.update_pomodoro_panel_responsive_layout()
    assert window.pomodoro_input_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window.pomodoro_button_row.direction() == QBoxLayout.Direction.TopToBottom
    assert _margins_tuple(window.pomodoro_timer_card_layout) == (12, 8, 12, 8)
    window.close()


def test_timeline_time_blocks_shrink_inside_narrow_width(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    widget.resize(360, 520)
    widget.show()
    app.processEvents()

    widget.block_table.resize(230, 390)
    widget._resize_time_columns()

    preferences = repository.get_preferences()
    labels = [_format_time(time(row, 0), preferences) for row in range(24)]
    required = max(widget.block_table.fontMetrics().horizontalAdvance(label) for label in labels) + 18
    assert widget.block_table.columnWidth(0) >= required
    assert widget.block_table.columnWidth(1) < 42
    total_width = sum(widget.block_table.columnWidth(column) for column in range(7))
    assert total_width <= widget.block_table.viewport().width() + 8
    widget.close()


def test_timeline_hour_column_fits_two_digit_12h_labels(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.time_format = "12h"
    repository.save_preferences(preferences)

    widget = TodayTimelineWidget(repository)
    widget.resize(420, 520)
    widget.show()
    app.processEvents()
    widget._resize_time_columns()

    labels = [_format_time(time(row, 0), preferences) for row in range(24)]
    required = max(widget.block_table.fontMetrics().horizontalAdvance(label) for label in labels) + 18
    assert widget.block_table.columnWidth(0) >= required
    assert widget.block_table.item(10, 0).text() == "AM 10:00"
    widget.close()


def test_spin_controls_have_arrows_and_consistent_right_corners(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    style = window.styleSheet()
    assert "QSpinBox::up-arrow, QTimeEdit::up-arrow" in style
    assert "QSpinBox::down-arrow, QTimeEdit::down-arrow" in style
    assert "QComboBox::down-arrow" in style
    assert "__COMBO_DOWN_ARROW__" not in style
    assert "__SPIN_UP_ARROW__" not in style
    assert "__SPIN_DOWN_ARROW__" not in style
    assert "QSpinBox#focusDurationSpin" in style
    assert "padding: 4px 22px 4px 10px;" in style
    assert "width: 18px;" in style
    assert "border-top-right-radius: 11px;" in style
    assert "border-bottom-right-radius: 11px;" in style
    assert "QScrollArea#checklistItemsArea, QScrollArea#favoritesShelfArea" in style
    assert "border-radius: 16px;" in style
    window.close()


def test_timeline_waiting_panel_auto_collapses_when_narrow(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository, show_waiting_panel=True, waiting_panel_pinned=True)
    widget.resize(980, 620)
    widget.show()
    app.processEvents()

    assert widget.waiting_panel.isVisible()
    assert not widget.waiting_rail.isVisible()
    initial_sizes = widget.content_splitter.sizes()
    assert initial_sizes[0] > initial_sizes[2]

    widget.resize(620, 620)
    app.processEvents()
    assert widget.waiting_auto_collapsed
    assert not widget.waiting_panel.isVisible()
    assert widget.waiting_rail.isVisible()

    widget.set_waiting_panel_pinned(True)
    app.processEvents()
    assert not widget.waiting_auto_collapsed
    assert widget.waiting_panel.isVisible()
    assert not widget.waiting_rail.isVisible()

    widget.resize(920, 620)
    app.processEvents()
    assert not widget.waiting_auto_collapsed
    assert widget.waiting_panel.isVisible()
    assert not widget.waiting_rail.isVisible()
    restored_sizes = widget.content_splitter.sizes()
    assert restored_sizes[0] > restored_sizes[2]
    assert restored_sizes[1] == 0
    assert widget.block_table.viewport().width() > 420

    widget.toggle_waiting_panel_pinned()
    app.processEvents()
    assert widget.waiting_rail.isVisible()
    collapsed_sizes = widget.content_splitter.sizes()
    assert collapsed_sizes[0] > collapsed_sizes[1]
    widget.toggle_waiting_panel_pinned()
    app.processEvents()
    expanded_sizes = widget.content_splitter.sizes()
    assert widget.waiting_panel.isVisible()
    assert expanded_sizes[0] > expanded_sizes[2]
    assert expanded_sizes[1] == 0
    assert widget.block_table.viewport().width() > 420
    widget.close()


def test_timeline_ports_filter_segment_buttons(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    widget.resize(900, 640)
    widget.show()
    app.processEvents()

    buttons = widget.findChildren(QToolButton, "timelineFilterButton")
    assert len(buttons) == 4
    assert widget.timeline_filter_combo.isHidden()
    assert widget.timeline_filter_buttons["all"].isChecked()
    assert widget.timeline_stat_strip.isHidden()
    assert widget.date_label.parentWidget().objectName() == "timelineToolbar"
    assert all("개" in button.text() for button in widget.timeline_filter_buttons.values())
    button_positions = [button.geometry().x() for button in widget.timeline_filter_buttons.values()]
    assert button_positions == sorted(button_positions)
    assert len(set(button_positions)) == len(button_positions)
    assert all(button.width() >= 82 for button in widget.timeline_filter_buttons.values())

    widget.timeline_filter_buttons["focus"].click()
    app.processEvents()

    checked_keys = [
        key
        for key, button in widget.timeline_filter_buttons.items()
        if button.isChecked()
    ]
    assert checked_keys == ["focus"]
    assert widget._current_timeline_filter_key() == "focus"
    assert widget.timeline_filter_combo.currentData() == "focus"
    widget.close()


def test_timeline_uses_compact_filter_combo_when_narrow(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    widget.set_date(datetime(2026, 6, 20).date())
    widget.resize(420, 640)
    widget.show()
    app.processEvents()

    assert widget.timeline_filter_segment.isHidden()
    assert widget.timeline_filter_combo.isVisible()
    assert widget.date_label.text() == "6월 20일"
    assert "/" not in widget.date_label.text()

    widget.timeline_filter_combo.setCurrentIndex(widget.timeline_filter_combo.findData("focus"))
    app.processEvents()
    assert widget.timeline_filter_key == "focus"
    widget.close()


def test_timeline_date_picker_calendar_keeps_full_grid_when_popup_opens(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    widget.set_date(datetime(2026, 6, 20).date())
    widget.resize(420, 640)
    widget.show()
    app.processEvents()

    opened_dialogs: list[QDialog] = []

    class CapturingDialog(QDialog):
        def __init__(self, *args) -> None:
            super().__init__(*args)
            opened_dialogs.append(self)

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "QDialog", CapturingDialog)

    widget.open_date_picker_from_label(None)
    app.processEvents()

    assert opened_dialogs
    dialog = opened_dialogs[0]
    calendar = dialog.findChild(QCalendarWidget)
    assert calendar is not None
    assert calendar.minimumWidth() >= 320
    assert calendar.minimumHeight() >= 300
    assert dialog.minimumWidth() >= 344
    assert dialog.minimumHeight() >= 344
    widget.close()


def test_timeline_ports_stat_chips(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    repository.save_task(Task("진행 항목", 0, due_at=today, created_at=today))
    repository.save_task(
        Task(
            "완료 항목",
            0,
            completed=True,
            completed_at=today + timedelta(minutes=20),
            created_at=today,
        )
    )
    repository.save_focus_session(
        FocusSession(
            title="집중 기록",
            planned_seconds=1500,
            focused_seconds=600,
            started_at=today,
            ended_at=today + timedelta(minutes=10),
            status="completed",
        )
    )

    widget = TodayTimelineWidget(repository)
    widget.resize(900, 640)
    widget.set_date(today.date())
    widget.show()
    app.processEvents()

    assert widget.timeline_filter_buttons["all"].text() == "전체 3개"
    assert widget.timeline_filter_buttons["schedule_task"].text() == "항목 1개"
    assert widget.timeline_filter_buttons["completed"].text() == "완료 1개"
    assert widget.timeline_filter_buttons["focus"].text() == "집중 1개"
    assert widget.timeline_item_stat_label.text() == "항목 1개"
    assert widget.timeline_completed_stat_label.text() == "완료 1개"
    assert widget.timeline_focus_stat_label.text() == "집중 1개"
    assert widget.summary_label.isHidden()
    assert widget.summary_label.text() == ""
    widget.close()


def test_integrated_widget_layout_and_memo_folder_actions(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert window.compact_button.text() == "통합 위젯"
    memo_buttons = {button.text() for button in window.memo_panel.findChildren(QPushButton)}
    assert "폴더 보기" in memo_buttons
    assert "폴더 관리" not in memo_buttons
    assert "쓰레기통" not in memo_buttons
    assert window.memo_panel.findChild(QWidget, "memoFolderStrip") is None

    window.open_compact_widget()
    app.processEvents()
    dialog = window.compact_widget_window
    assert dialog is not None
    assert dialog.windowTitle() == "통합 위젯"
    assert dialog.notes_list.maximumHeight() > 1000
    assert dialog.content_splitter.count() == 2
    assert dialog.always_on_top_check.y() <= dialog.time_label.y()

    dialog.close()
    window.close()


def test_quick_memo_rows_use_timeline_port_style(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_quick_note(QuickNote("포팅한 메모 타임라인", datetime(2026, 6, 14, 8, 5)))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.refresh_notes()
    app.processEvents()

    item = window.notes_list.item(0)
    row = window.notes_list.itemWidget(item)
    assert row is not None
    assert row.findChild(QFrame, "noteTimelineDot") is not None
    assert row.findChild(QFrame, "noteTimelineLine") is not None
    assert row.findChild(QLabel, "noteBodyLabel").text() == "포팅한 메모 타임라인"
    window.close()


def test_quick_memo_rows_keep_three_lines_with_large_content_font(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.content_font_size = 22
    repository.save_preferences(preferences)
    repository.save_quick_note(
        QuickNote(
            body="첫 줄 두 번째 줄 세 번째 줄 네 번째 줄까지 이어지는 긴 메모입니다.",
            created_at=datetime(2026, 6, 14, 8, 5),
        )
    )

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.refresh_notes()
    app.processEvents()

    item = window.notes_list.item(0)
    row = window.notes_list.itemWidget(item)
    body_label = row.findChild(QLabel, "noteBodyLabel") if row is not None else None

    assert body_label is not None
    assert item.sizeHint().height() >= window._quick_note_body_min_height() + 58
    assert body_label.minimumHeight() >= window._quick_note_body_min_height()
    window.close()


def test_quick_memo_context_copy_copies_note_body(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_quick_note(QuickNote("복사할 메모", datetime(2026, 6, 14, 8, 5)))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.refresh_notes()
    app.processEvents()

    window.notes_list.setCurrentRow(0)
    window.copy_selected_quick_note()

    assert QApplication.clipboard().text() == "복사할 메모"
    window.close()


def _note_row_bodies(window: MainWindow) -> list[str]:
    bodies: list[str] = []
    for row_index in range(window.notes_list.count()):
        item = window.notes_list.item(row_index)
        if item is None:
            continue
        row = window.notes_list.itemWidget(item)
        body_label = row.findChild(QLabel, "noteBodyLabel") if row is not None else None
        if body_label is not None:
            bodies.append(body_label.text())
    return bodies


def test_quick_memo_main_list_shows_all_notes_for_selected_folder(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    selected_folder = repository.save_quick_note_folder(QuickNoteFolder("프로젝트"))
    other_folder = repository.save_quick_note_folder(QuickNoteFolder("다른 폴더"))
    assert selected_folder.id is not None
    assert other_folder.id is not None
    expected_bodies = {f"선택 폴더 메모 {index:02d}" for index in range(15)}
    for index, body in enumerate(sorted(expected_bodies)):
        repository.save_quick_note(
            QuickNote(
                body,
                datetime(2026, 6, 14, 9, index),
                folder_id=selected_folder.id,
            )
        )
    repository.save_quick_note(
        QuickNote("다른 폴더 메모", datetime(2026, 6, 14, 10, 0), folder_id=other_folder.id)
    )

    window = MainWindow(repository)
    window.show()
    app.processEvents()
    folder_index = window.note_filter_combo.findData(selected_folder.id)
    assert folder_index >= 0
    window.note_filter_combo.setCurrentIndex(folder_index)
    window.refresh_notes()
    app.processEvents()

    assert window.notes_list.count() == 15
    assert set(_note_row_bodies(window)) == expected_bodies
    window.close()


def test_quick_memo_compact_notes_keep_five_item_limit_with_saved_sort(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.quick_note_sort_direction = "asc"
    repository.save_preferences(preferences)
    for index in range(7):
        repository.save_quick_note(QuickNote(f"compact memo {index}", datetime(2026, 6, 14, 9, index)))

    window = MainWindow(repository)
    window.refresh_compact_notes()
    app.processEvents()

    compact_texts = [window.compact_notes_list.item(index).text() for index in range(window.compact_notes_list.count())]
    assert window.compact_notes_list.count() == 5
    assert "compact memo 0" in compact_texts[0]
    assert "compact memo 4" in compact_texts[-1]
    assert all("compact memo 5" not in text for text in compact_texts)
    window.close()


def test_quick_memo_sort_toggle_persists_across_reload(tmp_path) -> None:
    app = _app()
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    repository.save_quick_note(QuickNote("오래된 정렬 메모", datetime(2026, 6, 14, 8, 0)))
    repository.save_quick_note(QuickNote("새 정렬 메모", datetime(2026, 6, 14, 9, 0)))

    window = MainWindow(repository)
    window.show()
    window.refresh_notes()
    app.processEvents()

    assert isinstance(window.memo_sort_button, SortDirectionButton)
    assert window.memo_sort_button.direction == "desc"
    assert _note_row_bodies(window)[:2] == ["새 정렬 메모", "오래된 정렬 메모"]

    window.memo_sort_button.click()
    app.processEvents()

    assert repository.get_preferences().quick_note_sort_direction == "asc"
    assert window.memo_sort_button.direction == "asc"
    assert _note_row_bodies(window)[:2] == ["오래된 정렬 메모", "새 정렬 메모"]
    window.close()

    reloaded_repository = ScheduleRepository(db_path)
    reloaded_window = MainWindow(reloaded_repository)
    reloaded_window.show()
    reloaded_window.refresh_notes()
    app.processEvents()

    assert reloaded_window.memo_sort_button.direction == "asc"
    assert _note_row_bodies(reloaded_window)[:2] == ["오래된 정렬 메모", "새 정렬 메모"]
    reloaded_window.close()


def test_quick_memo_pinned_notes_sort_above_unpinned_notes(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    pinned_old = repository.save_quick_note(QuickNote("고정된 오래된 메모", datetime(2026, 6, 14, 8, 0)))
    repository.save_quick_note(QuickNote("일반 최신 메모", datetime(2026, 6, 14, 9, 0)))
    assert pinned_old.id is not None
    assert repository.set_pinned_note(pinned_old.id, True)

    window = MainWindow(repository)
    window.show()
    window.refresh_notes()
    app.processEvents()

    assert _note_row_bodies(window)[:2] == ["고정된 오래된 메모", "일반 최신 메모"]
    first_item = window.notes_list.item(0)
    first_row = window.notes_list.itemWidget(first_item)
    assert first_row is not None
    assert first_row.findChild(PinBadge, "pinBadge") is not None
    window.close()


def test_quick_memo_tag_badges_render_in_note_rows(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(QuickNote("태그가 있는 메모", datetime(2026, 6, 14, 8, 0)))
    tag = repository.create_tag("집중")
    assert note.id is not None
    assert tag.id is not None
    repository.set_tags_for_target("quick_note", note.id, [tag.id])

    window = MainWindow(repository)
    window.show()
    window.refresh_notes()
    app.processEvents()

    item = window.notes_list.item(0)
    row = window.notes_list.itemWidget(item)
    assert row is not None
    assert [badge.text() for badge in row.findChildren(TagBadge, "tagBadge")] == ["집중"]
    window.close()


def test_quick_memo_context_menu_exposes_pin_and_tag_actions(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(QuickNote("메뉴 메모", datetime(2026, 6, 14, 8, 0)))
    assert note.id is not None
    captured_menus: list[QMenu] = []

    def capture_style(menu: QMenu, _parent: QWidget) -> QMenu:
        captured_menus.append(menu)
        return menu

    monkeypatch.setattr(main_window_module, "_style_popup_menu", capture_style)
    window = MainWindow(repository)
    window.show()
    window.refresh_notes()
    app.processEvents()

    item = window.notes_list.item(0)
    position = window.notes_list.visualItemRect(item).center()
    QTimer.singleShot(0, lambda: captured_menus[-1].close() if captured_menus else None)
    window.show_note_context_menu(position)

    actions = {action.text(): action for action in captured_menus[-1].actions() if not action.isSeparator()}
    assert "고정" in actions
    assert "태그 관리" in actions

    actions["고정"].trigger()
    app.processEvents()

    reloaded_note = repository.get_quick_note(note.id)
    assert reloaded_note is not None
    assert reloaded_note.pinned is True

    item = window.notes_list.item(0)
    position = window.notes_list.visualItemRect(item).center()
    QTimer.singleShot(0, lambda: captured_menus[-1].close() if captured_menus else None)
    window.show_note_context_menu(position)
    pinned_actions = {action.text(): action for action in captured_menus[-1].actions() if not action.isSeparator()}
    assert "고정 해제" in pinned_actions
    assert "태그 관리" in pinned_actions
    window.close()


def test_metadata_badges_use_expected_object_names() -> None:
    _app()

    tag_badge = TagBadge("집중")
    pin_badge = PinBadge()

    assert tag_badge.objectName() == "tagBadge"
    assert tag_badge.text() == "집중"
    assert pin_badge.objectName() == "pinBadge"
    assert pin_badge.text() == "PIN"


def test_sort_direction_button_updates_accessible_text_and_bar_widths() -> None:
    _app()

    button = SortDirectionButton("asc")

    assert button.text() == ""
    assert button.accessibleName() == "오름차순 정렬"
    assert button.toolTip() == "오름차순 정렬"
    assert button.bar_widths() == (4, 8, 12, 16)

    button.direction = "desc"

    assert button.accessibleName() == "내림차순 정렬"
    assert button.toolTip() == "내림차순 정렬"
    assert button.bar_widths() == (16, 12, 8, 4)


def test_tag_assignment_dialog_creates_renames_assigns_removes_and_deletes_tags(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(QuickNote("태그 대상 메모", datetime(2026, 6, 14, 8, 5)))
    task = repository.save_task(Task("태그 대상 할 일", 25))
    event = repository.save_event(
        Event(
            "태그 대상 일정",
            datetime(2026, 6, 14, 9, 0),
            datetime(2026, 6, 14, 10, 0),
        )
    )

    dialog = TagAssignmentDialog(repository, "quick_note", int(note.id))
    dialog.show()
    app.processEvents()
    dialog.new_tag_edit.setText("집중")

    dialog.create_tag()

    created_item = dialog.tag_list.findItems("집중", Qt.MatchFlag.MatchExactly)[0]
    assert repository.list_tags()[0].name == "집중"

    created_item.setCheckState(Qt.CheckState.Checked)
    dialog.accept()
    assert [tag.name for tag in repository.list_tags_for_target("quick_note", int(note.id))] == ["집중"]

    rename_dialog = TagAssignmentDialog(repository, "quick_note", int(note.id))
    renamed_item = rename_dialog.tag_list.findItems("집중", Qt.MatchFlag.MatchExactly)[0]
    rename_dialog.tag_list.setCurrentItem(renamed_item)
    monkeypatch.setattr(
        "app.ui.metadata_widgets.QInputDialog.getText",
        lambda *_args, **_kwargs: ("중요", True),
    )

    rename_dialog.rename_selected_tag()

    assert repository.list_tags()[0].name == "중요"

    remove_dialog = TagAssignmentDialog(repository, "quick_note", int(note.id))
    checked_item = remove_dialog.tag_list.findItems("중요", Qt.MatchFlag.MatchExactly)[0]
    assert checked_item.checkState() == Qt.CheckState.Checked
    checked_item.setCheckState(Qt.CheckState.Unchecked)
    remove_dialog.accept()
    assert repository.list_tags_for_target("quick_note", int(note.id)) == []

    delete_tag = repository.create_tag("삭제할 태그")
    repository.set_tags_for_target("quick_note", int(note.id), [int(delete_tag.id)])
    repository.set_tags_for_target("task", int(task.id), [int(delete_tag.id)])
    repository.set_tags_for_target("event", int(event.id), [int(delete_tag.id)])
    delete_dialog = TagAssignmentDialog(repository, "quick_note", int(note.id))
    delete_item = delete_dialog.tag_list.findItems("삭제할 태그", Qt.MatchFlag.MatchExactly)[0]
    delete_dialog.tag_list.setCurrentItem(delete_item)
    monkeypatch.setattr(
        "app.ui.metadata_widgets.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    delete_dialog.delete_selected_tag()

    assert "삭제할 태그" not in {tag.name for tag in repository.list_tags()}
    assert repository.list_tags_for_target("quick_note", int(note.id)) == []
    assert repository.list_tags_for_target("task", int(task.id)) == []
    assert repository.list_tags_for_target("event", int(event.id)) == []
    assert repository.get_quick_note(int(note.id)) is not None
    assert repository.get_task(int(task.id)) is not None
    assert repository.get_event(int(event.id)) is not None

    dialog.close()
    rename_dialog.close()
    remove_dialog.close()
    delete_dialog.close()


def test_note_folder_window_copy_and_refreshes_main_folder_combo(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    dialog = QuickNoteFolderNotesDialog(repository, window, on_changed=window.refresh_quick_note_views)
    dialog.show()
    app.processEvents()

    monkeypatch.setattr(
        "app.ui.main_window.QInputDialog.getText",
        lambda *_args, **_kwargs: ("새 폴더", True),
    )
    dialog.add_folder()
    app.processEvents()

    assert window.quick_note_folder_combo.findText("새 폴더") >= 0

    folder_id = dialog.current_folder_id()
    note = repository.save_quick_note(
        QuickNote(
            body="폴더 보기에서 복사할 메모",
            created_at=datetime(2026, 6, 14, 9, 0),
            folder_id=folder_id,
        )
    )
    dialog.refresh()
    dialog.notes_list.setCurrentRow(0)
    dialog.copy_notes([int(note.id)])

    assert QApplication.clipboard().text() == "폴더 보기에서 복사할 메모"
    dialog.close()
    window.close()


def test_note_trash_soft_delete_restore_and_permanent_delete(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(QuickNote(body="버릴 메모", created_at=datetime(2026, 6, 14, 9, 0)))
    repository.delete_quick_note(note.id)

    window = MainWindow(repository)
    dialog = QuickNoteTrashDialog(repository, window, on_changed=window.refresh_quick_note_views)
    dialog.show()
    app.processEvents()

    assert dialog.trash_list.count() == 1
    assert repository.list_quick_notes() == []

    dialog.trash_list.setCurrentRow(0)
    dialog.restore_selected_notes()
    app.processEvents()
    assert repository.get_quick_note(note.id) is not None

    repository.delete_quick_note(note.id)
    dialog.refresh()
    dialog.trash_list.setCurrentRow(0)
    monkeypatch.setattr(
        "app.ui.main_window.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog.delete_selected_notes_permanently()
    app.processEvents()

    assert repository.get_quick_note_any(note.id) is None
    dialog.close()
    window.close()


def test_note_folder_window_trash_button_opens_main_trash(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    dialog = QuickNoteFolderNotesDialog(repository, window, on_changed=window.refresh_quick_note_views)
    dialog.show()
    app.processEvents()

    trash_button = dialog.findChild(QPushButton, "quickNoteFolderTrashButton")
    assert trash_button is not None
    assert trash_button.text() == "쓰레기통"

    assert window.quick_note_trash_window is None
    trash_button.click()
    app.processEvents()

    trash_window = window.quick_note_trash_window
    assert isinstance(trash_window, QuickNoteTrashDialog)

    trash_button.click()
    app.processEvents()
    assert window.quick_note_trash_window is trash_window

    trash_window.close()
    dialog.close()
    window.close()


def test_quick_memo_editor_ports_compact_header_actions(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    assert window.memo_editor_header.objectName() == "memoEditorHeader"
    assert window.quick_note_folder_combo.parentWidget() is window.memo_editor_header
    assert window.quick_note_folder_combo.objectName() == "quickNoteFolderCombo"
    assert window.memo_save_button.parentWidget() is window.memo_editor_header
    assert window.memo_attach_button.parentWidget() is window.memo_editor_header
    assert window.memo_folder_view_button.parentWidget() is window.memo_history_card
    assert window.memo_folder_settings_button.parentWidget() is None
    assert window.memo_save_button.maximumWidth() == 76
    assert window.memo_attach_button.maximumWidth() == 76
    assert window.memo_folder_view_button.maximumWidth() <= 86
    assert window.memo_history_filter_row.indexOf(window.note_filter_combo) == window.memo_history_filter_row.count() - 1
    assert window.memo_history_filter_row.indexOf(window.memo_folder_view_button) < window.memo_history_filter_row.indexOf(window.note_filter_combo)
    assert window.memo_panel.findChild(QWidget, "memoFolderStrip") is None
    assert 40 <= window.quick_note_editor.minimumHeight() <= 64
    splitter_sizes = window.memo_splitter.sizes()
    assert splitter_sizes[0] < splitter_sizes[1]
    assert len(window.findChildren(QPushButton, "memoSaveButton")) == 1
    assert len(window.findChildren(QPushButton, "memoAttachButton")) == 1
    assert window.findChild(QLabel, "memoHintLabel") is None
    assert "Ctrl+Enter" in window.quick_note_editor.placeholderText()
    window.close()


def test_quick_memo_ctrl_enter_shortcuts_save_through_repository(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    return_shortcut = window.quick_note_ctrl_return_shortcut
    enter_shortcut = window.quick_note_ctrl_enter_shortcut
    assert return_shortcut.objectName() == "quickNoteCtrlReturnShortcut"
    assert enter_shortcut.objectName() == "quickNoteCtrlEnterShortcut"
    assert return_shortcut.key() == QKeySequence("Ctrl+Return")
    assert enter_shortcut.key() == QKeySequence("Ctrl+Enter")
    assert return_shortcut.parent() is window.quick_note_editor
    assert enter_shortcut.parent() is window.quick_note_editor

    assert repository.list_quick_notes() == []

    window.quick_note_editor.setPlainText("엔터로 저장")
    enter_shortcut.activated.emit()
    app.processEvents()
    notes_after_enter = repository.list_quick_notes()
    assert len(notes_after_enter) == 1
    assert notes_after_enter[0].body == "엔터로 저장"
    assert window.quick_note_editor.toPlainText() == ""

    window.quick_note_editor.setPlainText("리턴으로 저장")
    return_shortcut.activated.emit()
    app.processEvents()
    notes_after_return = repository.list_quick_notes()
    assert len(notes_after_return) == 2
    assert notes_after_return[0].body == "리턴으로 저장"
    assert window.quick_note_editor.toPlainText() == ""

    window.quick_note_editor.setPlainText("   ")
    enter_shortcut.activated.emit()
    app.processEvents()
    assert len(repository.list_quick_notes()) == 2

    window.close()


def test_quick_note_detail_edits_inside_same_window(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(QuickNote("처음 메모", datetime(2026, 6, 14, 8, 5)))
    assert note.id is not None

    dialog = QuickNoteDetailDialog(repository, note.id)
    dialog.show()
    app.processEvents()

    assert dialog.body_view.isVisible()
    assert dialog.body_editor.isHidden()
    dialog.edit_note()
    app.processEvents()
    assert dialog.body_view.isHidden()
    assert dialog.body_editor.isVisible()
    assert dialog.save_button.isVisible()
    assert dialog.cancel_button.isVisible()
    assert dialog.edit_button.isHidden()

    dialog.body_editor.text_edit.setPlainText("수정된 메모")
    dialog.save_edit()
    app.processEvents()

    reloaded = repository.get_quick_note(note.id)
    assert reloaded is not None
    assert reloaded.body == "수정된 메모"
    assert dialog.body_view.isVisible()
    assert dialog.body_editor.isHidden()
    dialog.close()


def test_quick_memo_prioritizes_editor_when_tiny(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_quick_note(QuickNote("작은 패널에서도 목록은 다시 돌아와야 함", datetime(2026, 6, 14, 8, 5)))
    window = MainWindow(repository)
    window.resize(900, 720)
    window.show()
    window.refresh_notes()
    app.processEvents()

    window.memo_content_panel.setFixedSize(260, 280)
    window.update_memo_panel_responsive_layout()

    assert window.memo_history_card.isHidden()
    assert window.findChild(QLabel, "memoHintLabel") is None
    assert window.memo_folder_view_button.isHidden()
    assert window.memo_folder_settings_button.isHidden()
    assert window.quick_note_editor.isVisible()
    assert window.quick_note_editor.minimumHeight() == 40
    assert window.memo_save_button.isVisible()
    assert window.memo_attach_button.isVisible()

    window.memo_content_panel.setMinimumSize(0, 0)
    window.memo_content_panel.setMaximumSize(16777215, 16777215)
    window.memo_content_panel.resize(560, 520)
    window.update_memo_panel_responsive_layout()
    assert window.memo_history_card.isVisible()
    assert window.quick_note_editor.minimumHeight() in {48, 56}
    window.close()


def test_link_favorites_port_cards_show_target_context(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_link_favorite(LinkFavorite(title="유튜브", target="https://www.youtube.com/watch?v=test"))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.refresh_link_favorites()
    app.processEvents()

    favorite_buttons = [button for button in window.link_favorites_panel.findChildren(QPushButton) if button.objectName() == "favoriteButton"]
    assert favorite_buttons
    assert favorite_buttons[0].text() == "유튜브\nyoutube.com"
    assert favorite_buttons[0].minimumHeight() >= 56
    window.close()


def test_link_favorites_reflows_with_panel_width(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    for index in range(4):
        repository.save_link_favorite(LinkFavorite(title=f"링크 {index + 1}", target=f"https://example.com/{index + 1}"))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.link_favorites_content_panel.setFixedSize(680, 360)
    window.update_link_favorites_responsive_layout()
    window.refresh_link_favorites()
    app.processEvents()

    buttons = [
        button
        for button in window.link_favorites_panel.findChildren(QPushButton)
        if button.objectName() == "favoriteButton"
    ]
    assert len(buttons) == 4
    assert window.link_favorites_columns == 3
    wide_positions = [
        window.link_favorites_layout.getItemPosition(window.link_favorites_layout.indexOf(button))[:2]
        for button in buttons
    ]
    assert wide_positions == [(0, 0), (0, 1), (0, 2), (1, 0)]

    window.link_favorites_content_panel.setFixedSize(320, 360)
    window.update_link_favorites_responsive_layout()
    window.refresh_link_favorites()
    app.processEvents()

    buttons = [
        button
        for button in window.link_favorites_panel.findChildren(QPushButton)
        if button.objectName() == "favoriteButton"
    ]
    assert window.link_favorites_columns == 1
    narrow_positions = [
        window.link_favorites_layout.getItemPosition(window.link_favorites_layout.indexOf(button))[:2]
        for button in buttons
    ]
    assert narrow_positions == [(0, 0), (1, 0), (2, 0), (3, 0)]
    window.close()


def test_link_favorites_can_reorder_inside_panel(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    first = repository.save_link_favorite(LinkFavorite(title="First", target="https://example.com/1"))
    second = repository.save_link_favorite(LinkFavorite(title="Second", target="https://example.com/2"))
    third = repository.save_link_favorite(LinkFavorite(title="Third", target="https://example.com/3"))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.link_favorites_content_panel.setFixedSize(680, 360)
    window.refresh_link_favorites()
    app.processEvents()

    first_button = window.link_favorite_buttons_by_id[int(first.id)]
    drop_position = first_button.mapToGlobal(QPoint(3, 3))
    window.handle_link_favorite_reorder_drop(int(third.id), drop_position)
    app.processEvents()

    assert [favorite.title for favorite in repository.list_link_favorites()] == ["Third", "First", "Second"]
    window.close()


def test_favorites_settings_dialog_ports_card_editor(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_link_favorite(LinkFavorite(title="유튜브", target="https://youtube.com", icon_text="YT"))
    repository.save_link_favorite(LinkFavorite(title="문서", target="C:/work/doc.txt"))

    dialog = FavoritesSettingsDialog(repository, repository.get_preferences())
    dialog.show()
    app.processEvents()

    assert dialog.findChild(QWidget, "favoritesSettingsHeader") is not None
    assert dialog.findChild(QWidget, "favoritesSettingsListCard") is not None
    assert dialog.findChild(QWidget, "favoritesSettingsEditorCard") is not None
    assert dialog.findChild(QWidget, "favoritesDisplayPanel") is not None
    favorites_list = dialog.findChild(QListWidget, "favoritesSettingsList")
    assert favorites_list is dialog.favorites_list
    assert dialog.favorites_count_label.text() == "2개"
    assert dialog.favorite_icon_preview.objectName() == "favoriteIconPreview"
    youtube_items = dialog.favorites_list.findItems("유튜브", Qt.MatchFlag.MatchExactly)
    assert youtube_items
    dialog.favorites_list.setCurrentItem(youtube_items[0])
    app.processEvents()
    assert dialog.favorite_icon_preview.text() == "YT"

    dialog.favorite_icon_text_edit.setText("D")
    app.processEvents()
    assert dialog.favorite_icon_preview.text() == "D"
    dialog.close()


def test_today_checklist_ports_progress_bar(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    first = repository.save_task(Task("첫 번째", 0))
    repository.save_task(Task("두 번째", 0))
    repository.save_task(Task("세 번째", 0))
    repository.mark_task_completed(first.id, True)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.today_checklist_widget.refresh_checklist()
    app.processEvents()

    assert window.today_checklist_widget.summary_label.text() == "진행 중 2개 · 완료 1개 · 33%"
    assert window.today_checklist_widget.summary_label.minimumHeight() == PANEL_CONTROL_HEIGHT
    assert window.today_checklist_widget.checklist_progress.value() == 333
    assert "min-height: 10px;" in window.styleSheet()
    window.close()


def test_today_checklist_rows_use_compact_task_row_port(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_item_type(ItemType("작업", "task"))
    today = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
    task = repository.save_task(Task("보고서 정리", 15, due_at=today, created_at=today))

    window = MainWindow(repository)
    window.resize(760, 620)
    window.show()
    window.today_checklist_widget.refresh_checklist()
    app.processEvents()

    row = window.today_checklist_widget.findChild(QWidget, "checklistRow")
    checkboxes = window.today_checklist_widget.findChildren(QCheckBox, "checklistItemCheck")
    checkbox_slot = window.today_checklist_widget.findChild(QWidget, "checklistCheckboxSlot")
    meta_label = window.today_checklist_widget.findChild(QLabel, "checklistItemMeta")
    add_panel = window.today_checklist_widget.findChild(QWidget, "checklistAddPanel")
    checklist_input = window.today_checklist_widget.findChild(QWidget, "checklistInput")
    folder_combo = window.today_checklist_widget.findChild(QComboBox, "checklistFolderCombo")

    assert row is not None
    assert row.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert _margins_tuple(row.layout()) == (8, 12, 8, 12)
    assert "QLabel#noteBodyLabel" in window.styleSheet()
    assert "QLabel#noteBodyLabel {\n                color: #111315;\n                font-size: 13px;\n                font-weight: 500;" in window.styleSheet()
    assert "QLabel#checklistItemTitle {\n                color: #111315;\n                font-size: 13px;\n                font-weight: 500;" in window.styleSheet()
    assert "QLabel#checklistItemMeta, QLabel#checklistItemMetaDone" in window.styleSheet()
    assert "font-size: 11px;" in window.styleSheet()
    assert "subcontrol-position: center;" in window.styleSheet()
    assert "QWidget#checklistCheckboxSlot" in window.styleSheet()
    assert any(checkbox.width() == 19 and checkbox.maximumWidth() == 19 for checkbox in checkboxes)
    assert checkbox_slot is not None
    assert checkbox_slot.maximumWidth() == 19
    assert _margins_tuple(checkbox_slot.layout()) == (0, 1, 0, 0)
    assert meta_label is not None
    assert "10:30" in meta_label.text()
    assert "15분" in meta_label.text()
    assert add_panel is not None
    assert checklist_input is not None
    assert folder_combo is not None
    assert folder_combo.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert folder_combo.view().cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert folder_combo.view().objectName() == "checklistFolderComboView"
    folder_index = folder_combo.findData(folder.id)
    window.today_checklist_widget.select_checklist_folder_from_index(folder_combo.model().index(folder_index, 0))
    assert folder_combo.currentData() == folder.id

    window.today_checklist_widget.show_item_context_menu(row, QPoint(8, 8), "task", int(task.id), task.title)
    app.processEvents()
    popup = getattr(app, "_active_light_action_popup", None)
    assert popup is not None
    assert popup.isVisible()
    assert popup.palette().color(popup.backgroundRole()).name().lower() == "#ffffff"
    assert "background-color: #ffffff" in popup.styleSheet()
    popup_buttons = {button.text() for button in popup.findChildren(QPushButton)}
    assert "수정" in popup_buttons
    assert "삭제" in popup_buttons
    popup.close()
    window.close()


def test_task_folders_are_managed_outside_settings(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_item_type(ItemType("업무", "task"))
    repository.save_task(Task("보고서", 30, item_type_id=folder.id))
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    main_buttons = {button.text() for button in window.findChildren(QPushButton)}
    assert "할 일 폴더" in main_buttons

    settings = SettingsDialog(repository.get_preferences(), window)
    settings_labels = {label.text() for label in settings.findChildren(QLabel)}
    assert "할 일 분류" not in settings_labels
    settings.close()

    dialog = ItemTypeSettingsDialog(repository, window)
    dialog.show()
    app.processEvents()
    assert dialog.windowTitle() == "할 일 폴더 관리"
    dialog_labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert "할 일 폴더" in dialog_labels
    assert "폴더 목록" in dialog_labels
    assert dialog.findChild(QWidget, "itemTypeSettingsHeader") is not None
    assert dialog.findChild(QWidget, "itemTypeSettingsListCard") is not None
    assert dialog.findChild(QWidget, "itemTypeSettingsEditorCard") is not None
    assert dialog.findChild(QListWidget, "itemTypeSettingsList") is dialog.type_list
    assert dialog.type_total_badge.text() == "2개"
    assert dialog.type_count_badge.text() == "2개"
    assert dialog.type_list.findItems("업무 · 1개", Qt.MatchFlag.MatchStartsWith)
    work_items = dialog.type_list.findItems("업무 · 1개", Qt.MatchFlag.MatchStartsWith)
    dialog.type_list.setCurrentItem(work_items[0])
    app.processEvents()
    assert dialog.type_preview_badge.text() == "업무"
    assert dialog.selected_type_summary.text().startswith("업무 · 할 일 1개")
    dialog.close()
    window.close()


def test_task_folder_dialog_moves_checked_tasks(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    source = repository.save_item_type(ItemType("Source", "task"))
    target = repository.save_item_type(ItemType("Target", "task"))
    first = repository.save_task(Task("First", 0, item_type_id=source.id))
    second = repository.save_task(Task("Second", 0, item_type_id=source.id))

    dialog = ItemTypeSettingsDialog(repository)
    dialog.refresh_types(source.id)
    dialog.show()
    app.processEvents()

    assert dialog.type_task_list.count() == 2
    for row in range(dialog.type_task_list.count()):
        dialog.type_task_list.item(row).setCheckState(Qt.CheckState.Checked)
    target_index = dialog.target_type_combo.findData(target.id)
    assert target_index >= 0
    dialog.target_type_combo.setCurrentIndex(target_index)

    dialog.move_selected_tasks()
    app.processEvents()

    assert repository.get_task(first.id).item_type_id == target.id
    assert repository.get_task(second.id).item_type_id == target.id
    dialog.close()


def _task_folder_view_titles(dialog: TaskFolderTasksDialog) -> list[str]:
    return [dialog.tasks_list.item(row).text() for row in range(dialog.tasks_list.count())]


def test_today_checklist_exposes_folder_view_button(tmp_path) -> None:
    # Given a checklist panel with a task folder and a task
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_item_type(ItemType("업무", "task"))
    repository.save_task(Task("보고서 정리", 0, item_type_id=folder.id))
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    # Then the checklist exposes a visible "폴더 보기" control styled as a ghost button
    button = window.today_checklist_widget.folder_view_button
    assert button.text() == "폴더 보기"
    assert button.objectName() == "ghostButton"
    assert button.isVisible()

    # When the control is used it opens a task-folder view window tracked by MainWindow
    window.today_checklist_widget.open_folder_view()
    app.processEvents()
    dialog = window.task_folder_notes_window
    assert isinstance(dialog, TaskFolderTasksDialog)
    assert dialog.isVisible()
    assert dialog.windowTitle() == "할 일 폴더 보기"
    dialog.close()
    window.close()


def test_today_checklist_narrow_width_keeps_title_unclipped_and_drops_summary(tmp_path) -> None:
    # Given a standalone checklist panel holding a task
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_task(Task("보고서 정리", 0))
    widget = TodayChecklistWidget(repository)

    # The summary badge starts hidden so a static capture that never fires a resize
    # event cannot render the wide badge and crowd the title at a narrow width.
    assert widget.summary_label.isHidden()

    widget.resize(293, 600)
    widget.show()
    app.processEvents()

    # When the panel is laid out at the narrow default dashboard width
    widget.update_panel_rhythm()

    # Then the title stays visible with room for its full text (no clipping) and the
    # folder control stays usable, while the redundant summary badge yields its room.
    assert widget.title_label is not None
    assert not widget.title_label.isHidden()
    assert not widget.folder_view_button.isHidden()
    assert widget.summary_label.isHidden()
    assert widget.title_label.width() >= widget.title_label.sizeHint().width()

    # When the panel widens back to a roomy width the summary badge returns
    widget.resize(640, 600)
    widget.update_panel_rhythm()
    assert not widget.title_label.isHidden()
    assert not widget.summary_label.isHidden()

    # When the panel is squeezed to a genuinely cramped width the redundant internal
    # title hides so it cannot clip, while the folder control stays reachable; the
    # outer feature title still names the panel.
    widget.resize(240, 600)
    widget.update_panel_rhythm()
    assert widget.title_label.isHidden()
    assert not widget.folder_view_button.isHidden()
    assert widget.summary_label.isHidden()
    widget.close()


def test_today_checklist_repeated_refresh_has_no_stale_rows(tmp_path) -> None:
    # Given a checklist panel with two active tasks
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_task(Task("청소", 0))
    repository.save_task(Task("보고서 정리", 0))
    widget = TodayChecklistWidget(repository)
    widget.show()
    app.processEvents()

    # When the checklist is refreshed repeatedly without flushing the event loop
    for _ in range(5):
        widget.refresh_checklist()

    # Then cleared rows detach immediately and do not pile up behind the live ones
    rows = widget.findChildren(QWidget, "checklistRow")
    empty_labels = widget.findChildren(QLabel, "mutedLabel")
    assert len(rows) == 2
    assert len(empty_labels) == 1
    widget.close()


def test_today_checklist_sort_direction_persists_and_reorders_items(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.checklist_sort_direction = "asc"
    repository.save_preferences(preferences)
    today = datetime.now().replace(second=0, microsecond=0)
    repository.save_task(Task("아침 정리", 0, created_at=today.replace(hour=8, minute=0)))
    repository.save_task(Task("저녁 정리", 0, created_at=today.replace(hour=18, minute=0)))

    widget = TodayChecklistWidget(repository)
    widget.show()
    app.processEvents()

    assert widget.checklist_sort_button.direction == "asc"
    assert _checklist_section_titles(widget.active_items_layout, "checklistItemTitle") == ["아침 정리", "저녁 정리"]

    widget.checklist_sort_button.click()
    app.processEvents()

    assert repository.get_preferences().checklist_sort_direction == "desc"
    assert widget.checklist_sort_button.direction == "desc"
    assert _checklist_section_titles(widget.active_items_layout, "checklistItemTitle") == ["저녁 정리", "아침 정리"]
    widget.close()


def test_today_checklist_pinned_items_stay_first_in_active_and_completed_sections(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    today = datetime.now().replace(second=0, microsecond=0)
    repository.save_task(Task("일찍 만든 할 일", 0, created_at=today.replace(hour=8, minute=0)))
    repository.save_event(
        Event(
            "늦은 고정 일정",
            today.replace(hour=18, minute=0),
            today.replace(hour=19, minute=0),
            pinned=True,
        )
    )
    repository.save_task(
        Task(
            "늦게 완료한 할 일",
            0,
            completed=True,
            completed_at=today.replace(hour=20, minute=0),
            created_at=today.replace(hour=7, minute=0),
        )
    )
    repository.save_event(
        Event(
            "이른 완료 고정 일정",
            today.replace(hour=9, minute=0),
            today.replace(hour=10, minute=0),
            completed=True,
            completed_at=today.replace(hour=9, minute=30),
            pinned=True,
        )
    )

    widget = TodayChecklistWidget(repository)
    widget.show()
    app.processEvents()

    assert _checklist_section_titles(widget.active_items_layout, "checklistItemTitle")[0] == "늦은 고정 일정"
    assert _checklist_section_titles(widget.completed_items_layout, "checklistItemTitleDone")[0] == "이른 완료 고정 일정"
    assert [badge.text() for badge in widget.findChildren(QLabel, "pinBadge")] == ["PIN", "PIN"]
    widget.close()


def test_today_checklist_renders_tag_badges(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("태그 있는 할 일", 0))
    tag = repository.create_tag("집중")
    repository.set_tags_for_target("task", int(task.id), [int(tag.id)])

    widget = TodayChecklistWidget(repository)
    widget.show()
    app.processEvents()

    assert [badge.text() for badge in widget.findChildren(QLabel, "tagBadge")] == ["집중"]
    widget.close()


def test_today_checklist_context_menu_toggles_pin_and_assigns_tags(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("메뉴 대상", 0))
    tag = repository.create_tag("중요")
    widget = TodayChecklistWidget(repository)
    widget.show()
    app.processEvents()

    row = widget.findChild(QWidget, "checklistRow")
    assert row is not None
    widget.show_item_context_menu(row, QPoint(8, 8), "task", int(task.id), task.title)
    app.processEvents()
    popup_buttons = {button.text() for button in getattr(app, "_active_light_action_popup").findChildren(QPushButton)}
    assert {"고정", "태그 관리", "수정", "삭제"} <= popup_buttons

    _click_light_popup_button(app, "고정")

    assert repository.get_task(int(task.id)).pinned is True
    assert widget.findChild(QLabel, "pinBadge") is not None

    row = widget.findChild(QWidget, "checklistRow")
    assert row is not None
    widget.show_item_context_menu(row, QPoint(8, 8), "task", int(task.id), task.title)
    app.processEvents()

    _click_light_popup_button(app, "고정 해제")

    assert repository.get_task(int(task.id)).pinned is False

    opened: dict[str, object] = {}

    class FakeTagAssignmentDialog:
        def __init__(self, repository_arg, target_type: str, target_id: int, parent=None) -> None:
            opened["repository"] = repository_arg
            opened["target_type"] = target_type
            opened["target_id"] = target_id
            opened["parent"] = parent

        def exec(self):
            opened["exec"] = True
            repository.set_tags_for_target("task", int(task.id), [int(tag.id)])
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "TagAssignmentDialog", FakeTagAssignmentDialog)
    row = widget.findChild(QWidget, "checklistRow")
    assert row is not None
    widget.show_item_context_menu(row, QPoint(8, 8), "task", int(task.id), task.title)
    app.processEvents()

    _click_light_popup_button(app, "태그 관리")

    assert opened == {
        "repository": repository,
        "target_type": "task",
        "target_id": int(task.id),
        "parent": widget,
        "exec": True,
    }
    assert [tag.name for tag in repository.list_tags_for_target("task", int(task.id))] == ["중요"]
    assert [badge.text() for badge in widget.findChildren(QLabel, "tagBadge")] == ["중요"]
    widget.close()


def test_today_checklist_workspace_filters_hide_completed_and_restrict_metadata(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    work = repository.save_item_type(ItemType("업무", "task"))
    personal = repository.save_item_type(ItemType("개인", "task"))
    focus_tag = repository.create_tag("집중")
    other_tag = repository.create_tag("기타")
    visible = repository.save_task(Task("보이는 업무", 0, item_type_id=work.id))
    repository.set_tags_for_target("task", int(visible.id), [int(focus_tag.id)])
    untagged = repository.save_task(Task("태그 없는 업무", 0, item_type_id=work.id))
    hidden_personal = repository.save_task(Task("개인 업무", 0, item_type_id=personal.id))
    repository.set_tags_for_target("task", int(hidden_personal.id), [int(focus_tag.id)])
    hidden_other_tag = repository.save_task(Task("다른 태그 업무", 0, item_type_id=work.id))
    repository.set_tags_for_target("task", int(hidden_other_tag.id), [int(other_tag.id)])
    completed = repository.save_task(
        Task(
            "완료된 업무",
            0,
            item_type_id=work.id,
            completed=True,
            completed_at=datetime.now().replace(second=0, microsecond=0),
        )
    )
    repository.set_tags_for_target("task", int(completed.id), [int(focus_tag.id)])

    window = MainWindow(repository)
    window.show()
    state = window.current_layout_state()
    state["filters"] = {
        "memo.folder_id": None,
        "memo.tag_ids": [],
        "checklist.item_type_ids": [int(work.id)],
        "checklist.tag_ids": [int(focus_tag.id)],
        "checklist.show_completed": False,
    }
    window.apply_layout_state(state)
    window.today_checklist_widget.refresh_checklist()
    app.processEvents()

    assert _checklist_section_titles(window.today_checklist_widget.active_items_layout, "checklistItemTitle") == ["보이는 업무"]
    assert _checklist_section_titles(window.today_checklist_widget.completed_items_layout, "checklistItemTitleDone") == []
    assert repository.get_task(int(untagged.id)) is not None
    assert repository.get_task(int(hidden_personal.id)) is not None
    assert repository.get_task(int(hidden_other_tag.id)) is not None
    assert repository.get_task(int(completed.id)).completed is True
    window.close()


def test_today_flow_focus_selected_task_still_loads_task(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("집중할 업무", 35))
    repository.save_event(Event("선택하면 무시할 일정", datetime.now(), datetime.now() + timedelta(minutes=30)))
    window = MainWindow(repository)
    today_panel = window._build_today_panel()
    window.show()
    today_panel.show()
    window.refresh_today()
    app.processEvents()

    for row in range(window.today_list.count()):
        item = window.today_list.item(row)
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "task" and data.get("id") == task.id:
            window.today_list.setCurrentItem(item)
            break

    window.focus_selected_task()

    assert window.selected_task_id == task.id
    assert window.focus_title_edit.text() == "집중할 업무"
    assert window.planned_minutes_spin.value() == 35
    today_panel.close()
    window.close()


def test_task_folder_view_lists_tasks_by_folder(tmp_path) -> None:
    # Given two task folders each holding a task
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    work = repository.save_item_type(ItemType("업무", "task"))
    personal = repository.save_item_type(ItemType("개인", "task"))
    repository.save_task(Task("보고서 작성", 0, item_type_id=work.id))
    repository.save_task(Task("장보기", 0, item_type_id=personal.id))

    # When the folder view opens on the work folder
    dialog = TaskFolderTasksDialog(repository, initial_type_id=work.id)
    dialog.show()
    app.processEvents()

    # Then only the work folder's tasks are listed
    assert dialog.current_type_id() == work.id
    work_titles = _task_folder_view_titles(dialog)
    assert any("보고서 작성" in title for title in work_titles)
    assert all("장보기" not in title for title in work_titles)

    # When another folder is selected its own tasks are shown
    dialog.select_type(personal.id)
    app.processEvents()
    assert dialog.current_type_id() == personal.id
    personal_titles = _task_folder_view_titles(dialog)
    assert any("장보기" in title for title in personal_titles)
    assert all("보고서 작성" not in title for title in personal_titles)
    dialog.close()


def test_task_folder_view_moves_checked_tasks_and_refreshes(tmp_path) -> None:
    # Given two tasks in a source folder and a target folder
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    source = repository.save_item_type(ItemType("출발", "task"))
    target = repository.save_item_type(ItemType("도착", "task"))
    first = repository.save_task(Task("먼저", 0, item_type_id=source.id))
    second = repository.save_task(Task("다음", 0, item_type_id=source.id))
    changed = {"count": 0}

    dialog = TaskFolderTasksDialog(
        repository,
        initial_type_id=source.id,
        on_changed=lambda: changed.__setitem__("count", changed["count"] + 1),
    )
    dialog.show()
    app.processEvents()
    assert dialog.tasks_list.count() == 2

    # When both tasks are checked and moved to the target folder
    for row in range(dialog.tasks_list.count()):
        dialog.tasks_list.item(row).setCheckState(Qt.CheckState.Checked)
    target_index = dialog.target_type_combo.findData(target.id)
    assert target_index >= 0
    dialog.target_type_combo.setCurrentIndex(target_index)
    dialog.move_selected_tasks()
    app.processEvents()

    # Then both tasks belong to the target folder and on_changed fired
    assert repository.get_task(first.id).item_type_id == target.id
    assert repository.get_task(second.id).item_type_id == target.id
    assert changed["count"] >= 1
    dialog.close()


def test_task_folder_view_adds_task_to_selected_folder(tmp_path) -> None:
    # Given an empty task folder open in the folder view
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_item_type(ItemType("새폴더", "task"))
    changed = {"count": 0}
    dialog = TaskFolderTasksDialog(
        repository,
        initial_type_id=folder.id,
        on_changed=lambda: changed.__setitem__("count", changed["count"] + 1),
    )
    dialog.show()
    app.processEvents()

    # When a task is added through the folder view input
    dialog.new_task_edit.setText("새 할 일")
    dialog.add_task()
    app.processEvents()

    # Then the task is created in the selected folder, input clears, on_changed fires
    matches = [
        task
        for task in repository.list_tasks(include_completed=True)
        if task.title == "새 할 일" and task.item_type_id == folder.id
    ]
    assert matches
    assert dialog.new_task_edit.text() == ""
    assert changed["count"] >= 1
    dialog.close()


def test_task_folder_view_completes_and_deletes_task(tmp_path, monkeypatch) -> None:
    # Given a task in a folder open in the folder view
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_item_type(ItemType("정리", "task"))
    task = repository.save_task(Task("끝낼 일", 0, item_type_id=folder.id))
    changed = {"count": 0}
    dialog = TaskFolderTasksDialog(
        repository,
        initial_type_id=folder.id,
        on_changed=lambda: changed.__setitem__("count", changed["count"] + 1),
    )
    dialog.show()
    app.processEvents()

    # When the task is completed from the folder view
    dialog.set_task_completed(int(task.id), True)
    app.processEvents()

    # Then the task is marked completed and on_changed fires
    assert repository.get_task(task.id).completed is True
    assert changed["count"] >= 1

    # When the task is checked and deleted (confirmation accepted)
    monkeypatch.setattr(
        "app.ui.main_window.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    for row in range(dialog.tasks_list.count()):
        item = dialog.tasks_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == task.id:
            item.setCheckState(Qt.CheckState.Checked)
    dialog.delete_selected_tasks()
    app.processEvents()

    # Then the task is removed
    assert repository.get_task(task.id) is None
    dialog.close()


def test_task_folder_view_manage_button_opens_folder_management(tmp_path, monkeypatch) -> None:
    # Given the folder view open on a folder
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_item_type(ItemType("관리대상", "task"))
    changed = {"count": 0}
    dialog = TaskFolderTasksDialog(
        repository,
        initial_type_id=folder.id,
        on_changed=lambda: changed.__setitem__("count", changed["count"] + 1),
    )
    dialog.show()
    app.processEvents()

    # Then a clear "관리" path exists that routes to ItemTypeSettingsDialog
    manage_buttons = [button for button in dialog.findChildren(QPushButton) if button.text() == "관리"]
    assert manage_buttons

    captured: dict[str, object] = {}

    def fake_exec(self) -> int:
        captured["dialog"] = self
        return 0

    monkeypatch.setattr(main_window_module.ItemTypeSettingsDialog, "exec", fake_exec)
    dialog.open_folder_management()
    app.processEvents()

    assert isinstance(captured.get("dialog"), main_window_module.ItemTypeSettingsDialog)
    assert changed["count"] >= 1
    dialog.close()


def test_feature_context_windows_use_new_window_label_and_always_on_top(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    expected_titles = {
        "focus": "집중 새창",
        "pomodoro": "뽀모도로 새창",
        "quick_memo": "메모 새창",
        "today_checklist": "오늘 체크리스트 새창",
        "today_timeline": "시간표 새창",
        "link_favorites": "즐겨찾기 새창",
        "media_panel": "이미지 새창",
    }
    for feature_key, title in expected_titles.items():
        window.open_feature_widget(feature_key)
        app.processEvents()
        dialog = window.feature_widget_windows[feature_key]
        assert dialog.windowTitle() == title
        checks = [checkbox for checkbox in dialog.findChildren(QCheckBox) if checkbox.text() == "항상 위"]
        assert checks
        checks[0].setChecked(True)
        app.processEvents()
        assert bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        dialog.close()
        app.processEvents()

    window.close()


def test_media_panel_loads_saved_image_in_main_and_window(tmp_path) -> None:
    app = _app()
    image_path = tmp_path / "sample.png"
    pixmap = QPixmap(16, 10)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(image_path))

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.media_panel_file_path = str(image_path)
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert window.media_preview_label.pixmap() is not None
    assert not window.media_preview_label.pixmap().isNull()
    media_buttons = {button.text() for button in window.media_panel.findChildren(QPushButton)}
    assert "선택" not in media_buttons
    assert "비우기" not in media_buttons
    window.show_media_panel_context_menu(window.media_preview_label, QPoint(4, 4))
    app.processEvents()
    media_popup = getattr(app, "_active_light_action_popup", None)
    assert media_popup is not None
    assert media_popup.isVisible()
    media_popup_buttons = {button.text() for button in media_popup.findChildren(QPushButton)}
    assert "패널 고정" in media_popup_buttons
    assert "새창으로 열기" in media_popup_buttons
    assert "메인창에서 숨기기" in media_popup_buttons
    assert "이미지 변경" in media_popup_buttons
    assert "비우기" in media_popup_buttons
    assert "이미지 보기 조정" in media_popup_buttons
    assert "이미지 보기 초기화" in media_popup_buttons
    assert media_popup.minimumWidth() >= 164
    media_popup.close()

    window.open_feature_widget("media_panel")
    app.processEvents()
    dialog = window.feature_widget_windows["media_panel"]
    assert dialog.preview_label.pixmap() is not None
    assert not dialog.preview_label.pixmap().isNull()

    dialog.close()
    window.close()


def test_media_panel_preview_shares_card_content_baseline(tmp_path) -> None:
    app = _app()
    image_path = tmp_path / "panel.png"
    pixmap = QPixmap(24, 16)
    pixmap.fill(Qt.GlobalColor.magenta)
    assert pixmap.save(str(image_path))

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.media_panel_file_path = str(image_path)
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = False
    window.preferences.show_focus_panel = False
    window.preferences.show_header_banner = False
    window.preferences.show_quick_memo_panel = False
    window.preferences.show_media_panel = True
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = True
    window.preferences.show_today_timeline_inline = False
    window.preferences.show_today_checklist_inline = False
    window.preferences.show_link_favorites_panel = False

    window.feature_dashboard_items = [
        {"key": "media_panel", "x": 0, "y": 0, "w": 3, "h": 5},
        {"key": "pomodoro", "x": 3, "y": 0, "w": 3, "h": 5},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    media_box = window.feature_boxes["media_panel"]
    preview = window.media_preview_label
    media_content = media_box.findChild(QWidget, "mediaPanel")
    pomodoro_box = window.feature_boxes["pomodoro"]
    pomodoro_content = pomodoro_box.findChild(QWidget, "pomodoroPanel")
    assert preview is not None
    assert media_content is not None
    assert pomodoro_content is not None

    # The media panel now shows the same visible handle as titled panels, while its
    # image body stays directly draggable.
    titled_offset = PANEL_HEADER_HEIGHT + PANEL_HANDLE_CONTENT_GAP
    assert media_box.header_band is not None
    assert media_box.header_band.maximumHeight() == PANEL_HEADER_HEIGHT
    assert media_box.move_bar is not None
    assert media_box.move_bar.minimumHeight() == PANEL_MOVE_BAR_HEIGHT
    assert media_box.move_bar.maximumHeight() == PANEL_MOVE_BAR_HEIGHT
    assert media_box.title_label is None
    assert media_box.content_drag_enabled is True
    assert media_content.layout().contentsMargins().top() == 0

    # Its preview now starts below the visible handle, matching titled panels.
    assert media_content.mapTo(media_box, QPoint(0, 0)).y() == titled_offset
    assert preview.mapTo(media_box, QPoint(0, 0)).y() == titled_offset

    # A normal titled panel reserves the same visible handle-to-card gap.
    assert pomodoro_content.mapTo(pomodoro_box, QPoint(0, 0)).y() == titled_offset

    media_box_top = media_box.mapTo(window, QPoint(0, 0)).y()
    pomodoro_box_top = pomodoro_box.mapTo(window, QPoint(0, 0)).y()
    assert media_box_top == pomodoro_box_top
    assert media_box_top + media_box.height() == pomodoro_box_top + pomodoro_box.height()

    # The preview owns the card below the handle, down to the bottom edge.
    preview_top = preview.mapTo(window, QPoint(0, 0)).y()
    assert preview_top == media_box_top + titled_offset
    assert preview.height() == media_box.height() - titled_offset
    assert preview_top + preview.height() == media_box_top + media_box.height()

    assert preview.pixmap() is not None
    assert not preview.pixmap().isNull()

    window.close()


def test_handle_panels_share_card_content_baseline(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = True
    window.preferences.show_focus_panel = True
    window.preferences.show_header_banner = True
    window.preferences.show_quick_memo_panel = False
    window.preferences.show_media_panel = False
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = True
    window.preferences.show_today_timeline_inline = False
    window.preferences.show_today_checklist_inline = False
    window.preferences.show_link_favorites_panel = False

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 3, "h": 5},
        {"key": "header_banner", "x": 3, "y": 0, "w": 3, "h": 5},
        {"key": "pomodoro", "x": 6, "y": 0, "w": 3, "h": 5},
        {"key": "datetime", "x": 0, "y": 0, "w": 3, "h": 2},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    header_box = window.feature_boxes["header_banner"]
    header_content = window.header_banner_widget
    datetime_box = window.feature_boxes["datetime"]
    datetime_content = window.datetime_content_panel
    focus_box = window.feature_boxes["focus"]
    focus_content = window.focus_content_panel
    pomodoro_box = window.feature_boxes["pomodoro"]
    pomodoro_content = pomodoro_box.findChild(QWidget, "pomodoroPanel")
    assert pomodoro_content is not None

    # The media/header/datetime panels now expose the same visible handle as titled
    # panels, while their body stays directly draggable.
    titled_offset = PANEL_HEADER_HEIGHT + PANEL_HANDLE_CONTENT_GAP
    for handle_box in (datetime_box, header_box):
        assert handle_box.title_label is None
        assert handle_box.header_band is not None
        assert handle_box.header_band.maximumHeight() == PANEL_HEADER_HEIGHT
        assert handle_box.move_bar is not None
        assert handle_box.move_bar.minimumHeight() == PANEL_MOVE_BAR_HEIGHT
        assert handle_box.move_bar.maximumHeight() == PANEL_MOVE_BAR_HEIGHT
        assert handle_box.content_drag_enabled is True

    # The new handles react to hover exactly like other FeatureMoveBar controls.
    for handle_box in (datetime_box, header_box):
        move_bar = handle_box.move_bar
        QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Enter))
        assert move_bar.property("hovering") is True
        QApplication.sendEvent(move_bar, QEvent(QEvent.Type.Leave))
        assert move_bar.property("hovering") is False

    # Handle content now starts below the visible gap, matching titled panels.
    assert header_content.mapTo(header_box, QPoint(0, 0)).y() == titled_offset
    assert datetime_content.mapTo(datetime_box, QPoint(0, 0)).y() == titled_offset

    # Normal titled panels keep the same visible handle-to-card gap.
    assert focus_content.mapTo(focus_box, QPoint(0, 0)).y() == titled_offset
    assert pomodoro_content.mapTo(pomodoro_box, QPoint(0, 0)).y() == titled_offset

    # All four boxes share the same row-0 top (datetime overlays focus at (0, 0)).
    box_tops = {
        focus_box.mapTo(window, QPoint(0, 0)).y(),
        header_box.mapTo(window, QPoint(0, 0)).y(),
        pomodoro_box.mapTo(window, QPoint(0, 0)).y(),
        datetime_box.mapTo(window, QPoint(0, 0)).y(),
    }
    assert len(box_tops) == 1
    shared_box_top = box_tops.pop()

    # Every panel now shares the same handle-to-content baseline.
    assert header_content.mapTo(window, QPoint(0, 0)).y() == shared_box_top + titled_offset
    assert datetime_content.mapTo(window, QPoint(0, 0)).y() == shared_box_top + titled_offset
    assert focus_content.mapTo(window, QPoint(0, 0)).y() == shared_box_top + titled_offset
    assert pomodoro_content.mapTo(window, QPoint(0, 0)).y() == shared_box_top + titled_offset

    # The datetime overlay floats above the grid rather than occupying a grid slot,
    # yet still lands on the same container origin as focus.
    datetime_cell = window.feature_cells["datetime"]
    focus_cell = window.feature_cells["focus"]
    assert datetime_cell.parent() is window.feature_grid_container
    assert window.feature_dashboard_layout.indexOf(datetime_cell) == -1
    focus_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(focus_cell)
    )
    assert focus_position[:2] == (0, 0)
    assert datetime_cell.geometry().topLeft() == focus_cell.geometry().topLeft()

    window.close()


def test_handle_panel_content_press_starts_reposition(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = True
    window.preferences.show_header_banner = True
    window.preferences.show_focus_panel = True
    window.preferences.show_media_panel = True
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_quick_memo_panel = False
    window.preferences.show_pomodoro_controls = False
    window.preferences.show_today_timeline_inline = False
    window.preferences.show_today_checklist_inline = False
    window.preferences.show_link_favorites_panel = False

    window.feature_dashboard_items = [
        {"key": "header_banner", "x": 0, "y": 0, "w": 4, "h": 5},
        {"key": "media_panel", "x": 4, "y": 0, "w": 3, "h": 5},
        {"key": "focus", "x": 7, "y": 0, "w": 4, "h": 5},
        {"key": "datetime", "x": 0, "y": 6, "w": 3, "h": 2},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    overlay = window.dashboard_guide_overlay
    layout_before = [dict(item) for item in window._current_feature_dashboard_layout()]
    stored_before = [dict(item) for item in getattr(window, "feature_dashboard_items", [])]
    slots_before = {str(item.get("key", "")): _dashboard_slot(item) for item in layout_before}
    stored_slots_before = {str(item.get("key", "")): _dashboard_slot(item) for item in stored_before}
    assert not overlay.isVisible()

    def press_at(widget, local_point):
        return QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(local_point),
            QPointF(widget.mapToGlobal(local_point)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def move_at(widget, local_point):
        return QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(local_point),
            QPointF(widget.mapToGlobal(local_point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    handle_panel_contents = (
        ("header_banner", window.header_banner_widget),
        ("media_panel", window.media_preview_label),
        ("datetime", window.datetime_content_panel),
    )
    drag_threshold = QApplication.startDragDistance()
    for key, content in handle_panel_contents:
        box = window.feature_boxes[key]
        assert box.content_drag_enabled is True
        center = QPoint(max(1, content.width() // 2), max(1, content.height() // 2))
        # The box installs itself as the content event filter at runtime; body drag stays
        # a move affordance for image/banner/clock panels even though they now show a handle.
        consumed_press = box.eventFilter(content, press_at(content, center))
        assert consumed_press is False
        assert box.panel_drag_start is not None
        assert box.panel_drag_active is False
        moved = QPoint(center.x() + drag_threshold * 3, center.y())
        box.eventFilter(content, move_at(content, moved))
        assert box.panel_drag_start is not None
        assert box.panel_drag_active is True
        assert overlay.isVisible()
        current_slots = {
            str(item.get("key", "")): _dashboard_slot(item)
            for item in window._current_feature_dashboard_layout()
        }
        current_stored_slots = {
            str(item.get("key", "")): _dashboard_slot(item)
            for item in getattr(window, "feature_dashboard_items", [])
        }
        assert current_slots == slots_before
        assert current_stored_slots == stored_slots_before
        box.finish_feature_reposition_gesture(content.mapToGlobal(center), content)
        window._hide_dashboard_drag_guides()
        assert box.panel_drag_start is None
        assert box.panel_drag_active is False

    # Previewing handle-panel body drags does not mutate the live layout until a drop happens.
    current_slots = {
        str(item.get("key", "")): _dashboard_slot(item)
        for item in window._current_feature_dashboard_layout()
    }
    current_stored_slots = {
        str(item.get("key", "")): _dashboard_slot(item)
        for item in getattr(window, "feature_dashboard_items", [])
    }
    assert current_slots == slots_before
    assert current_stored_slots == stored_slots_before

    # A normal titled panel still arms a reposition gesture from its visible handle.
    focus_box = window.feature_boxes["focus"]
    move_bar = focus_box.move_bar
    assert move_bar is not None
    bar_center = QPoint(max(1, move_bar.width() // 2), max(1, move_bar.height() // 2))
    move_bar.mousePressEvent(press_at(move_bar, bar_center))
    assert focus_box.panel_drag_start is not None
    focus_box.finish_feature_reposition_gesture(move_bar.mapToGlobal(bar_center), move_bar)
    window._hide_dashboard_drag_guides()
    assert not overlay.isVisible()

    window.close()


def test_extra_media_panels_copy_assets_and_keep_hidden_images(tmp_path) -> None:
    app = _app()
    image_path = tmp_path / "extra.png"
    pixmap = QPixmap(18, 12)
    pixmap.fill(Qt.GlobalColor.blue)
    assert pixmap.save(str(image_path))

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_media_panel_2 = True
    preferences.media_panel_2_file_path = str(image_path)
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    stored_path = Path(window.preferences.media_panel_2_file_path)
    assert stored_path.parent == tmp_path / "media"
    assert stored_path.exists()
    assert window.media_panel_2.isVisible()
    preview = window.media_preview_labels["media_panel_2"]
    assert preview.pixmap() is not None
    assert not preview.pixmap().isNull()

    window.hide_feature_from_main("media_panel_2")
    app.processEvents()
    reloaded = repository.get_preferences()
    assert not reloaded.show_media_panel_2
    assert reloaded.media_panel_2_file_path == str(stored_path)

    window.close()


def test_header_banner_loads_gif_and_uses_image_context_popup(tmp_path) -> None:
    app = _app()
    gif_path = tmp_path / "banner.gif"
    gif_path.write_bytes(
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
        b"!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
        b"\x00\x02\x02D\x01\x00;"
    )

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = True
    preferences.header_banner_image_path = str(gif_path)
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert window.header_banner_widget.movie is not None
    assert window.header_banner_widget.movie.isValid()
    window.show_header_banner_context_menu(window.header_banner_widget, QPoint(4, 4))
    app.processEvents()

    popup = getattr(app, "_active_light_action_popup", None)
    assert popup is not None
    assert popup.isVisible()
    popup_buttons = {button.text() for button in popup.findChildren(QPushButton)}
    assert "패널 고정" in popup_buttons
    assert "메인창에서 숨기기" in popup_buttons
    assert "이미지 변경" in popup_buttons
    assert "비우기" in popup_buttons
    assert "이미지 보기 조정" in popup_buttons
    assert "이미지 보기 초기화" in popup_buttons
    assert popup.minimumWidth() >= 164
    popup.close()
    window.close()


def test_header_banner_uses_label_pixmap_loader_like_media_panel(tmp_path) -> None:
    app = _app()
    image_path = tmp_path / "banner.png"
    pixmap = QPixmap(28, 12)
    pixmap.fill(Qt.GlobalColor.green)
    assert pixmap.save(str(image_path))

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = True
    preferences.header_banner_image_path = str(image_path)
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    stored_path = Path(window.preferences.header_banner_image_path)
    assert stored_path.parent == tmp_path / "media"
    assert stored_path.exists()
    assert window.header_banner_widget.pixmap() is not None
    assert not window.header_banner_widget.pixmap().isNull()
    assert f"border-radius: {PANEL_CORNER_RADIUS}px;" in window.header_banner_widget.styleSheet()
    assert "border-radius: 18px;" not in window.header_banner_widget.styleSheet()

    window.set_header_banner_image_position("right")
    assert repository.get_preferences().header_banner_image_position == "right"
    assert bool(window.header_banner_widget.alignment() & Qt.AlignmentFlag.AlignRight)
    assert repository.get_preferences().header_banner_image_view

    window.close()


def test_media_panel_image_position_persists_from_context_action(tmp_path) -> None:
    app = _app()
    image_path = tmp_path / "position.png"
    pixmap = QPixmap(20, 12)
    pixmap.fill(Qt.GlobalColor.yellow)
    assert pixmap.save(str(image_path))

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.media_panel_file_path = str(image_path)
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.set_media_panel_image_position("media_panel", "left")
    assert repository.get_preferences().media_panel_image_position == "left"
    assert bool(window.media_preview_label.alignment() & Qt.AlignmentFlag.AlignLeft)
    window.set_media_panel_image_view("media_panel", {"zoom": 50, "x": 20, "y": 70})
    reloaded = repository.get_preferences()
    assert reloaded.media_panel_image_view == '{"zoom":50,"x":20,"y":70}'
    assert window.media_preview_label.image_view == {"zoom": 50, "x": 20, "y": 70}

    window.close()


def test_media_corner_clip_survives_image_viewport_clip() -> None:
    _app()
    widget = QWidget()
    widget.resize(80, 80)

    source = QPixmap(80, 80)
    source.fill(Qt.GlobalColor.red)
    target = QPixmap(80, 80)
    target.fill(Qt.GlobalColor.transparent)

    painter = QPainter(target)
    try:
        _clip_media_corners(widget, painter, True)
        _draw_image_viewport(widget, painter, source, {"zoom": 100, "x": 50, "y": 50})
    finally:
        painter.end()

    image = target.toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(40, 40).red() > 200
    assert image.pixelColor(40, 40).alpha() > 200


def test_media_corner_clip_uses_panel_radius() -> None:
    _app()
    widget = QWidget()
    widget.resize(80, 80)

    source = QPixmap(80, 80)
    source.fill(Qt.GlobalColor.red)
    target = QPixmap(80, 80)
    target.fill(Qt.GlobalColor.transparent)

    painter = QPainter(target)
    try:
        _clip_media_corners(widget, painter, True)
        _draw_image_viewport(widget, painter, source, {"zoom": 100, "x": 50, "y": 50})
    finally:
        painter.end()

    image = target.toImage()
    # The very corner is always clipped away.
    assert image.pixelColor(0, 0).alpha() == 0
    # A 16px panel-matching radius leaves these edge samples fully opaque (255);
    # the old 18px radius clipped them to ~219 alpha, leaving a visible step
    # against the neighbouring cards. Threshold sits between the two regimes.
    assert image.pixelColor(16, 0).alpha() >= 240
    assert image.pixelColor(0, 16).alpha() >= 240


def test_media_image_viewport_allows_zooming_out() -> None:
    _app()
    widget = QWidget()
    widget.resize(100, 100)

    source = QPixmap(100, 100)
    source.fill(Qt.GlobalColor.red)
    target = QPixmap(100, 100)
    target.fill(Qt.GlobalColor.transparent)

    painter = QPainter(target)
    try:
        _draw_image_viewport(widget, painter, source, {"zoom": 50, "x": 0, "y": 0})
    finally:
        painter.end()

    image = target.toImage()
    assert image.pixelColor(10, 10).red() > 200
    assert image.pixelColor(10, 10).alpha() > 200
    assert image.pixelColor(90, 90).alpha() == 0


def test_main_window_restores_last_closed_size(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.last_window_width = 1180
    preferences.last_window_height = 760
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()
    assert window.width() == 1180
    assert window.height() == 760

    window.resize(1234, 678)
    app.processEvents()
    window.close()

    saved = repository.get_preferences()
    assert saved.last_window_width == 1234
    assert saved.last_window_height == 678

    restored = MainWindow(repository)
    restored.show()
    app.processEvents()
    assert restored.width() == 1234
    assert restored.height() == 678
    restored.close()


def test_main_window_persists_normal_size_when_closing_maximized(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.last_window_width = 1180
    preferences.last_window_height = 760
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.resize(1234, 678)
    app.processEvents()

    window.showMaximized()
    app.processEvents()
    assert window.isMaximized()

    window.close()
    app.processEvents()

    saved = repository.get_preferences()
    # Closing while maximized must persist the tracked normal size, not the
    # maximized geometry.
    assert saved.last_window_width == 1234
    assert saved.last_window_height == 678


def test_main_window_restores_last_feature_sizes(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.resize_feature_grid_span("focus", 2)
    window.resize_feature_panel_height("quick_memo", window._dashboard_item_pixel_height(7))
    window.swap_feature_panels("quick_memo", "today_checklist", "before")
    app.processEvents()
    expected_dashboard = window.current_layout_state()["layout"]["dashboard"]
    window.close()
    app.processEvents()

    saved_state = json.loads(repository.get_preferences().last_layout_state)
    assert saved_state["layout"]["dashboard"] == expected_dashboard
    assert "window" not in saved_state

    restored = MainWindow(repository)
    restored.resize(1280, 820)
    restored.show()
    app.processEvents()
    app.processEvents()

    restored_dashboard = restored.current_layout_state()["layout"]["dashboard"]
    assert restored_dashboard == expected_dashboard
    restored.close()


def test_workspace_filter_round_trips_through_layout_state(tmp_path) -> None:
    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)

    state = window.current_layout_state()
    filters = state["filters"]
    expected_default_filters = {
        "memo.folder_id": None,
        "memo.tag_ids": [],
        "checklist.item_type_ids": [],
        "checklist.tag_ids": [],
        "checklist.show_completed": True,
    }
    assert filters == expected_default_filters
    assert set(filters) == set(expected_default_filters)

    updated_filters = {
        "memo.folder_id": 3,
        "memo.tag_ids": [11, 13],
        "checklist.item_type_ids": [2, 5],
        "checklist.tag_ids": [7, 17],
        "checklist.show_completed": False,
    }
    state["filters"] = updated_filters
    window.apply_layout_state(state)

    assert window._active_workspace_filters == updated_filters
    window.close()


def test_workspace_switch_applies_memo_folder_filter(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    project_folder = repository.save_quick_note_folder(QuickNoteFolder("프로젝트"))
    archive_folder = repository.save_quick_note_folder(QuickNoteFolder("보관"))
    assert project_folder.id is not None
    assert archive_folder.id is not None
    repository.save_quick_note(
        QuickNote("프로젝트 메모", datetime(2026, 6, 14, 9, 0), folder_id=project_folder.id)
    )
    repository.save_quick_note(
        QuickNote("보관 메모", datetime(2026, 6, 14, 10, 0), folder_id=archive_folder.id)
    )

    window = MainWindow(repository)
    window.show()
    app.processEvents()
    state = window.current_layout_state()
    state["filters"] = {
        **_workspace_filters(),
        "memo.folder_id": int(project_folder.id),
    }
    profile = repository.save_layout_profile(LayoutProfile(name="프로젝트", data=json.dumps(state, ensure_ascii=False)))
    assert profile.id is not None

    window.switch_workspace(profile.id)
    app.processEvents()

    assert _note_row_bodies(window) == ["프로젝트 메모"]
    window.close()


def test_workspace_switch_applies_memo_tag_filter(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    focus_tag = repository.create_tag("집중")
    other_tag = repository.create_tag("기타")
    visible = repository.save_quick_note(QuickNote("태그 메모", datetime(2026, 6, 14, 9, 0)))
    hidden = repository.save_quick_note(QuickNote("다른 태그 메모", datetime(2026, 6, 14, 10, 0)))
    assert focus_tag.id is not None
    assert other_tag.id is not None
    assert visible.id is not None
    assert hidden.id is not None
    repository.set_tags_for_target("quick_note", int(visible.id), [int(focus_tag.id)])
    repository.set_tags_for_target("quick_note", int(hidden.id), [int(other_tag.id)])

    window = MainWindow(repository)
    window.show()
    app.processEvents()
    state = window.current_layout_state()
    state["filters"] = {
        **_workspace_filters(),
        "memo.tag_ids": [int(focus_tag.id)],
    }
    profile = repository.save_layout_profile(LayoutProfile(name="메모 태그", data=json.dumps(state, ensure_ascii=False)))
    assert profile.id is not None

    window.switch_workspace(profile.id)
    app.processEvents()

    assert _note_row_bodies(window) == ["태그 메모"]
    window.close()


def test_workspace_switch_applies_checklist_tag_filter(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    focus_tag = repository.create_tag("집중")
    other_tag = repository.create_tag("기타")
    visible = repository.save_task(Task("보이는 할 일", 0))
    hidden = repository.save_task(Task("숨겨질 할 일", 0))
    assert focus_tag.id is not None
    assert other_tag.id is not None
    assert visible.id is not None
    assert hidden.id is not None
    repository.set_tags_for_target("task", int(visible.id), [int(focus_tag.id)])
    repository.set_tags_for_target("task", int(hidden.id), [int(other_tag.id)])

    window = MainWindow(repository)
    window.show()
    app.processEvents()
    state = window.current_layout_state()
    state["filters"] = {
        **_workspace_filters(),
        "checklist.tag_ids": [int(focus_tag.id)],
    }
    profile = repository.save_layout_profile(LayoutProfile(name="집중", data=json.dumps(state, ensure_ascii=False)))
    assert profile.id is not None

    window.switch_workspace(profile.id)
    app.processEvents()

    assert _checklist_section_titles(window.today_checklist_widget.active_items_layout, "checklistItemTitle") == [
        "보이는 할 일"
    ]
    window.close()


def test_manual_folder_combo_change_does_not_overwrite_workspace_filters(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    workspace_folder = repository.save_quick_note_folder(QuickNoteFolder("작업공간"))
    manual_folder = repository.save_quick_note_folder(QuickNoteFolder("수동"))
    assert workspace_folder.id is not None
    assert manual_folder.id is not None
    repository.save_quick_note(
        QuickNote("작업공간 메모", datetime(2026, 6, 14, 9, 0), folder_id=workspace_folder.id)
    )
    repository.save_quick_note(
        QuickNote("수동 메모", datetime(2026, 6, 14, 10, 0), folder_id=manual_folder.id)
    )

    window = MainWindow(repository)
    window.show()
    app.processEvents()
    state = window.current_layout_state()
    state["filters"] = {
        **_workspace_filters(),
        "memo.folder_id": int(workspace_folder.id),
    }
    window.apply_layout_state(state)
    original_filters = dict(window._active_workspace_filters)

    manual_index = window.note_filter_combo.findData(manual_folder.id)
    assert manual_index >= 0
    window.note_filter_combo.setCurrentIndex(manual_index)
    app.processEvents()

    assert window._active_workspace_filters == original_filters
    assert _note_row_bodies(window) == ["수동 메모"]
    window.close()


def test_future_panel_keys_do_not_create_visible_panels(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    future_keys = {
        WRITING_EDITOR_KEY,
        WRITING_LIBRARY_KEY,
        COMMISSION_SUMMARY_KEY,
        WEEKLY_PLAN_KEY,
    }
    default_column_items = {
        key
        for column_items in window.default_feature_layout().values()
        for key in column_items
    }
    default_dashboard_items = {str(item["key"]) for item in window.default_feature_grid_layout()}

    assert not future_keys.intersection(window.feature_boxes)
    assert not future_keys.intersection(default_column_items)
    assert not future_keys.intersection(default_dashboard_items)
    settings = SettingsDialog(repository.get_preferences(), window)
    settings.show()
    app.processEvents()
    settings_values = {settings.windowTitle(), settings.objectName()}
    settings_values.update(widget.objectName() for widget in settings.findChildren(QWidget) if widget.objectName())
    settings_values.update(label.text() for label in settings.findChildren(QLabel))
    settings_values.update(button.text() for button in settings.findChildren(QPushButton))
    settings_values.update(check.text() for check in settings.findChildren(QCheckBox))
    for combo in settings.findChildren(QComboBox):
        for index in range(combo.count()):
            settings_values.add(combo.itemText(index))
            settings_values.add(str(combo.itemData(index)))

    assert not future_keys.intersection(settings_values)
    settings.close()
    window.close()


def test_workspace_switch_refreshes_existing_feature_widget_windows_safely(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    class RefreshingDialog(QDialog):
        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)
            self.refresh_count = 0

        def refresh(self) -> None:
            self.refresh_count += 1

    dialog = RefreshingDialog(window)
    window.feature_widget_windows["focus"] = dialog
    state = window.current_layout_state()
    state["filters"] = {
        **_workspace_filters(),
        "checklist.show_completed": False,
    }
    profile = repository.save_layout_profile(LayoutProfile(name="열린 위젯", data=json.dumps(state, ensure_ascii=False)))
    assert profile.id is not None

    window.switch_workspace(profile.id)
    app.processEvents()

    assert dialog.refresh_count == 1
    dialog.close()
    window.close()


def test_switch_skips_refresh_when_unchanged(tmp_path, monkeypatch) -> None:
    # Given: a window whose current layout state is saved verbatim as a profile,
    # so switching to it carries identical filters/visibility/layout slices.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    state = window.current_layout_state()
    state["filters"] = _workspace_filters()
    profile = repository.save_layout_profile(LayoutProfile(name="동일", data=json.dumps(state, ensure_ascii=False)))
    assert profile.id is not None

    refresh_notes_calls = 0
    refresh_checklist_calls = 0
    refresh_widget_calls = 0

    def spy_refresh_notes() -> None:
        nonlocal refresh_notes_calls
        refresh_notes_calls += 1

    def spy_refresh_today_checklist() -> None:
        nonlocal refresh_checklist_calls
        refresh_checklist_calls += 1

    def spy_refresh_feature_widget(_key: str | None = None) -> None:
        nonlocal refresh_widget_calls
        refresh_widget_calls += 1

    monkeypatch.setattr(window, "refresh_notes", spy_refresh_notes)
    monkeypatch.setattr(window, "refresh_today_checklist", spy_refresh_today_checklist)
    monkeypatch.setattr(window, "refresh_feature_widget", spy_refresh_feature_widget)

    window.switch_workspace(profile.id)
    app.processEvents()

    # refresh_notes has no indirect call path from apply_layout_state, so the
    # diff-based skip must keep it at 0 when filters are unchanged.
    assert refresh_notes_calls == 0
    # refresh_today_checklist / refresh_feature_widget are triggered indirectly
    # by apply_layout_state (via today_checklist_widget.refresh_checklist ->
    # refresh_today callback chain). The diff-based skip must not add a DIRECT
    # call on top, so the count stays at the indirect-only baseline of 1.
    assert refresh_checklist_calls == 1
    assert refresh_widget_calls == 1
    assert window.preferences.active_workspace_id == profile.id
    window.close()


def test_switch_refreshes_when_filters_change(tmp_path, monkeypatch) -> None:
    # Given: a window and a workspace profile whose checklist filter differs
    # from the current state. Switching must trigger the content refreshes.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    state = window.current_layout_state()
    state["filters"] = {
        **_workspace_filters(),
        "checklist.show_completed": False,
    }
    profile = repository.save_layout_profile(LayoutProfile(name="필터 변경", data=json.dumps(state, ensure_ascii=False)))
    assert profile.id is not None

    refresh_notes_calls = 0
    refresh_checklist_calls = 0
    refresh_widget_calls = 0

    def spy_refresh_notes() -> None:
        nonlocal refresh_notes_calls
        refresh_notes_calls += 1

    def spy_refresh_today_checklist() -> None:
        nonlocal refresh_checklist_calls
        refresh_checklist_calls += 1

    def spy_refresh_feature_widget(_key: str | None = None) -> None:
        nonlocal refresh_widget_calls
        refresh_widget_calls += 1

    monkeypatch.setattr(window, "refresh_notes", spy_refresh_notes)
    monkeypatch.setattr(window, "refresh_today_checklist", spy_refresh_today_checklist)
    monkeypatch.setattr(window, "refresh_feature_widget", spy_refresh_feature_widget)

    window.switch_workspace(profile.id)
    app.processEvents()

    # refresh_notes: one direct call from the diff-based refresh (no indirect path).
    assert refresh_notes_calls == 1
    # refresh_today_checklist / refresh_feature_widget: one indirect call from
    # apply_layout_state plus one direct call from the diff-based refresh.
    assert refresh_checklist_calls == 2
    assert refresh_widget_calls == 2
    assert window._active_workspace_filters["checklist.show_completed"] is False
    window.close()


def test_workspace_switch_preserves_current_window_geometry(tmp_path) -> None:
    # Given: a shown window sized/positioned by the user, and a workspace profile
    # whose saved window geometry deliberately differs from the current window.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    window.resize(1180, 760)
    app.processEvents()
    before_size = (window.width(), window.height())
    before_pos = window.pos()

    state = _workspace_state(window, show_focus=False, show_quick_memo=True)
    state["window"] = {"width": before_size[0] + 320, "height": before_size[1] + 240}
    profile = repository.save_layout_profile(
        LayoutProfile(name="다른 크기", data=json.dumps(state, ensure_ascii=False))
    )
    assert profile.id is not None

    # When: the user selects that workspace.
    window.switch_workspace(profile.id)
    app.processEvents()

    # Then: the window neither resizes nor moves, while the workspace still applies.
    assert (window.width(), window.height()) == before_size
    assert window.pos() == before_pos
    assert window.preferences.active_workspace_id == profile.id
    assert window._active_workspace_filters["checklist.show_completed"] is True
    window.close()


def test_workspace_menu_selection_applies_state_without_mutating_previous_profile(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    work_state = _workspace_state(window, show_focus=False, show_quick_memo=True, show_completed=False)
    review_state = _workspace_state(window, show_focus=True, show_quick_memo=False, show_completed=True)
    work_profile = repository.save_layout_profile(
        LayoutProfile(name="업무", data=json.dumps(work_state, ensure_ascii=False))
    )
    review_profile = repository.save_layout_profile(
        LayoutProfile(name="리뷰", data=json.dumps(review_state, ensure_ascii=False))
    )
    assert work_profile.id is not None
    assert review_profile.id is not None
    original_work_data = _profile_data(repository, "업무")

    menu = window._build_workspace_menu()
    work_action = next(action for action in menu.actions() if action.text() == "업무")
    work_action.trigger()
    app.processEvents()

    assert window.preferences.active_workspace_id == work_profile.id
    assert not window.preferences.show_focus_panel
    assert window.preferences.show_quick_memo_panel
    assert window._active_workspace_filters["checklist.show_completed"] is False

    window.preferences.show_focus_panel = True
    window.preferences.show_quick_memo_panel = False
    window.apply_preferences(refresh_content=False)
    review_action = next(action for action in window._build_workspace_menu().actions() if action.text() == "리뷰")
    review_action.trigger()
    app.processEvents()

    assert window.preferences.active_workspace_id == review_profile.id
    assert window.preferences.show_focus_panel
    assert not window.preferences.show_quick_memo_panel
    assert _profile_data(repository, "업무") == original_work_data
    window.close()


def test_active_workspace_restores_on_reload_and_ignores_malformed_json(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seed_window = MainWindow(repository)
    workspace_state = _workspace_state(seed_window, show_focus=False, show_quick_memo=True, show_completed=False)
    profile = repository.save_layout_profile(
        LayoutProfile(name="저장된 작업공간", data=json.dumps(workspace_state, ensure_ascii=False))
    )
    assert profile.id is not None
    seed_window.switch_workspace(profile.id)
    seed_window.close()

    restored = MainWindow(repository)
    restored.show()
    app.processEvents()

    assert restored.preferences.active_workspace_id == profile.id
    assert not restored.preferences.show_focus_panel
    assert restored._active_workspace_filters["checklist.show_completed"] is False
    restored.close()

    broken = repository.save_layout_profile(LayoutProfile(name="깨진 작업공간", data="{"))
    assert broken.id is not None
    repository.set_active_workspace(broken.id)
    broken_restored = MainWindow(repository)
    broken_restored.show()
    app.processEvents()

    assert "작업공간" in broken_restored.statusBar().currentMessage()
    assert broken_restored.preferences.active_workspace_id == broken.id
    broken_restored.close()


def test_legacy_layout_state_without_filters_applies_safely(tmp_path) -> None:
    _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)

    legacy_state = window.current_layout_state()
    legacy_state.pop("filters")
    window.apply_layout_state(legacy_state)

    assert window._active_workspace_filters == {
        "memo.folder_id": None,
        "memo.tag_ids": [],
        "checklist.item_type_ids": [],
        "checklist.tag_ids": [],
        "checklist.show_completed": True,
    }
    window.close()


def test_workspace_manager_create_update_rename_and_delete(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()
    window.apply_layout_state(_workspace_state(window, show_focus=False, show_quick_memo=True, show_completed=False))

    names = iter(["새 작업공간", "이름 바꿈"])
    monkeypatch.setattr(
        main_window_module.QInputDialog,
        "getText",
        lambda *args: (next(names), True),
    )
    dialog = WorkspaceManagerDialog(repository, window)
    dialog.show()
    app.processEvents()

    dialog.create_workspace()
    created = repository.get_layout_profile("새 작업공간")
    assert created is not None
    assert json.loads(created.data)["filters"]["checklist.show_completed"] is False
    created_data = created.data

    window.apply_layout_state(_workspace_state(window, show_focus=True, show_quick_memo=False, show_completed=True))
    dialog.rename_selected_workspace()
    renamed = repository.get_layout_profile("이름 바꿈")
    assert renamed is not None
    assert renamed.id == created.id
    assert renamed.data == created_data

    repository.set_active_workspace(renamed.id)
    window.preferences.active_workspace_id = renamed.id
    window.apply_layout_state(_workspace_state(window, show_focus=True, show_quick_memo=False, show_completed=True))
    # Applying a state does NOT autosave (that would drift the layout on every
    # switch). A genuine layout edit (move/resize -> save_last_layout_state) is
    # what persists the active workspace's current arrangement.
    window.save_last_layout_state()
    window._flush_workspace_autosave()
    updated = repository.get_layout_profile("이름 바꿈")
    assert updated is not None
    assert updated.id == created.id
    assert json.loads(updated.data)["filters"]["checklist.show_completed"] is True
    assert json.loads(updated.data)["visible"]["quick_memo"] is False
    assert repository.get_preferences().active_workspace_id == renamed.id

    dialog.delete_selected_workspace(confirm=False)
    assert repository.get_layout_profile("이름 바꿈") is None
    assert repository.get_preferences().active_workspace_id is None
    dialog.close()
    window.close()


def test_switching_back_and_forth_does_not_drift_stored_layout(tmp_path) -> None:
    # Regression: switching between workspaces applies each profile's layout,
    # which rearranges the live dashboard. The pending autosave timer must NOT
    # persist that applied arrangement back onto the profile, or repeated
    # switching would slowly mutate ("drift") the saved layouts.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    state_a = _workspace_state(window, show_focus=True, show_quick_memo=True)
    state_b = _workspace_state(window, show_focus=False, show_quick_memo=False)
    profile_a = repository.save_layout_profile(
        LayoutProfile(name="A", data=json.dumps(state_a, ensure_ascii=False))
    )
    profile_b = repository.save_layout_profile(
        LayoutProfile(name="B", data=json.dumps(state_b, ensure_ascii=False))
    )
    assert profile_a.id is not None
    assert profile_b.id is not None
    saved_a = _profile_data(repository, "A")
    saved_b = _profile_data(repository, "B")

    # Simulate real usage: flip back and forth, letting the autosave timer fire
    # after each switch (which is what previously corrupted the profiles).
    for index in range(6):
        window.switch_workspace(int(profile_a.id if index % 2 == 0 else profile_b.id))
        app.processEvents()
        window._flush_workspace_autosave()
        app.processEvents()

    assert _profile_data(repository, "A") == saved_a
    assert _profile_data(repository, "B") == saved_b
    window.close()


def _asymmetric_workspaces(window: MainWindow) -> tuple[dict[str, object], dict[str, object]]:
    """Two workspaces whose VISIBLE panel sets differ, with explicit positions.

    The hidden panels of one are the visible panels of the other, so switching
    between them exercises the newly-visible-panel placement path.
    """
    base = window.current_layout_state()

    def make(visible_keys: set[str], positions: dict[str, tuple[int, int]]) -> dict[str, object]:
        state = json.loads(json.dumps(base))
        for key in list(state["visible"].keys()):
            state["visible"][key] = key in visible_keys
        for item in state["layout"]["dashboard"]:
            if item["key"] in positions:
                item["x"], item["y"] = positions[item["key"]]
        return state

    work = make(
        {"focus", "today_timeline", "today_checklist", "header_banner"},
        {"focus": (0, 3), "today_timeline": (9, 3), "today_checklist": (6, 3)},
    )
    memo = make(
        {"quick_memo", "link_favorites", "media_panel", "header_banner"},
        {"quick_memo": (0, 3), "link_favorites": (4, 3), "media_panel": (8, 3)},
    )
    return work, memo


def test_switching_between_differently_visible_workspaces_keeps_dashboard_stable(tmp_path) -> None:
    # Regression: when two workspaces expose different visible panels, the panels
    # that become visible on a switch must keep the incoming profile's stored x/y
    # instead of being re-flowed as if the user had just manually re-added them.
    # Otherwise the rendered dashboard drifts (panels creep left) on every switch.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    work, memo = _asymmetric_workspaces(window)
    id_work = int(repository.save_layout_profile(LayoutProfile(name="Work", data=json.dumps(work, ensure_ascii=False))).id)
    id_memo = int(repository.save_layout_profile(LayoutProfile(name="Memo", data=json.dumps(memo, ensure_ascii=False))).id)

    def dashboard() -> dict[str, tuple[int, int, int, int]]:
        return {
            str(item["key"]): (item["x"], item["y"], item["w"], item["h"])
            for item in window.current_layout_state()["layout"]["dashboard"]
        }

    window.switch_workspace(id_work)
    app.processEvents()
    first = dashboard()
    for _ in range(4):
        window.switch_workspace(id_memo)
        app.processEvents()
        window.switch_workspace(id_work)
        app.processEvents()
    second = dashboard()

    for key in ("focus", "today_timeline", "today_checklist"):
        assert first[key] == second[key], f"{key} drifted {first[key]} -> {second[key]}"
    window.close()


def test_applying_workspace_layout_round_trips_losslessly(tmp_path) -> None:
    # Regression: apply(state) then current_layout_state() must reproduce the
    # applied splitters/dashboard. If reading back differs, the first edit after a
    # switch persists the re-read approximation and the saved workspace drifts.
    # (Detached dashboard-mode splitters previously failed this round-trip.)
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    state = _workspace_state(window, show_focus=True, show_quick_memo=True)
    window.apply_layout_state(json.loads(json.dumps(state)), include_window=False)
    app.processEvents()

    read_back = window.current_layout_state()
    read_back.pop("window", None)
    expected = json.loads(json.dumps(state))
    expected.pop("window", None)
    assert read_back["splitters"] == expected["splitters"]
    assert read_back["layout"]["dashboard"] == expected["layout"]["dashboard"]
    window.close()


def test_workspace_order_persists_and_reflects_in_menu(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    first = repository.save_layout_profile(LayoutProfile(name="첫째", data=json.dumps(window.current_layout_state(), ensure_ascii=False)))
    second = repository.save_layout_profile(LayoutProfile(name="둘째", data=json.dumps(window.current_layout_state(), ensure_ascii=False)))
    assert first.id is not None
    assert second.id is not None

    dialog = WorkspaceManagerDialog(repository, window)
    dialog.show()
    app.processEvents()

    # Given: the dialog lists profiles in repository display_order (first then second).
    assert [dialog.profile_list.item(row).text() for row in range(dialog.profile_list.count())] == ["첫째", "둘째"]

    # When: the user moves the selected "첫째" workspace down.
    dialog.profile_list.setCurrentRow(0)
    dialog.move_selected_workspace_down()
    app.processEvents()

    # Then: repository order persisted as [second, first]...
    assert [profile.name for profile in repository.list_user_workspace_profiles()] == ["둘째", "첫째"]
    # ...and the dialog list reflects the new order with the moved row still selected.
    assert [dialog.profile_list.item(row).text() for row in range(dialog.profile_list.count())] == ["둘째", "첫째"]
    assert dialog.profile_list.currentRow() == 1

    # And: _build_workspace_menu lists workspace actions (excluding separator/manage/quick-config) in the same order.
    menu = window._build_workspace_menu()
    workspace_action_texts = [
        action.text()
        for action in menu.actions()
        if not action.isSeparator() and action.text() != "워크스페이스 관리..." and action.text() != "빠른 전환 버튼 설정..."
    ]
    assert workspace_action_texts == ["둘째", "첫째"]

    dialog.close()
    window.close()


def test_workspace_panel_changes_autosave(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    profile = repository.save_layout_profile(
        LayoutProfile(name="자동저장", data=json.dumps(window.current_layout_state(), ensure_ascii=False))
    )
    assert profile.id is not None
    window.switch_workspace(profile.id)
    assert window.preferences.active_workspace_id == profile.id

    original_data = repository.get_layout_profile("자동저장").data
    window.preferences.show_focus_panel = not window.preferences.show_focus_panel
    window.apply_preferences()
    window.save_last_layout_state()

    app.processEvents()
    QTest.qWait(500)
    app.processEvents()

    autosaved = repository.get_layout_profile("자동저장")
    assert autosaved is not None
    assert autosaved.data != original_data
    assert json.loads(autosaved.data)["visible"]["focus"] is window.preferences.show_focus_panel
    window.close()


def test_datetime_panel_visibility_persists_across_workspace_switch(tmp_path) -> None:
    # Regression for BUG 3: toggling the datetime panel via the settings dialog
    # while in a workspace must persist to that workspace, so switching away and
    # back restores the datetime panel visibility.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # Start with datetime panel hidden.
    assert not window.preferences.show_datetime_panel

    # Create a workspace from the current state (datetime off).
    profile = repository.save_layout_profile(
        LayoutProfile(name="날짜꺼짐", data=json.dumps(window.current_layout_state(), ensure_ascii=False))
    )
    assert profile.id is not None
    window.switch_workspace(int(profile.id))
    app.processEvents()
    assert window.preferences.active_workspace_id == int(profile.id)
    assert not window.preferences.show_datetime_panel

    # Toggle datetime panel ON via the settings dialog and accept.
    window.show_settings_window()
    app.processEvents()
    dialog = window._settings_dialog
    assert isinstance(dialog, SettingsDialog)
    dialog.show_datetime_panel_check.setChecked(True)
    dialog.accept()
    app.processEvents()

    assert window.preferences.show_datetime_panel
    # The workspace profile must now reflect datetime=True.
    saved = repository.get_layout_profile("날짜꺼짐")
    assert saved is not None
    assert json.loads(saved.data)["visible"]["datetime"] is True

    # Switch to a second workspace (datetime off by default), then back.
    other_profile = repository.save_layout_profile(
        LayoutProfile(name="다른화면", data=json.dumps(window.default_layout_state(), ensure_ascii=False))
    )
    assert other_profile.id is not None
    window.switch_workspace(int(other_profile.id))
    app.processEvents()
    assert not window.preferences.show_datetime_panel

    window.switch_workspace(int(profile.id))
    app.processEvents()
    # The datetime panel must be visible again after switching back.
    assert window.preferences.show_datetime_panel
    window.close()


def test_no_active_workspace_falls_back_to_last_layout_state(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    assert window.preferences.active_workspace_id is None
    original_last_state = window.preferences.last_layout_state

    window.preferences.show_focus_panel = not window.preferences.show_focus_panel
    window.apply_preferences()
    window.save_last_layout_state()
    app.processEvents()

    assert window.preferences.active_workspace_id is None
    assert window.preferences.last_layout_state != original_last_state
    window.close()


def test_autosave_debounces_rapid_changes(tmp_path, monkeypatch) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    profile = repository.save_layout_profile(
        LayoutProfile(name="디바운스", data=json.dumps(window.current_layout_state(), ensure_ascii=False))
    )
    assert profile.id is not None
    window.switch_workspace(profile.id)

    write_count = 0
    original_update = repository.update_layout_profile_data

    def counting_update(profile_id: int, data: str) -> LayoutProfile | None:
        nonlocal write_count
        write_count += 1
        return original_update(profile_id, data)

    monkeypatch.setattr(repository, "update_layout_profile_data", counting_update)

    for _ in range(5):
        window.preferences.show_focus_panel = not window.preferences.show_focus_panel
        window.apply_preferences()
        window.save_last_layout_state()
        app.processEvents()

    QTest.qWait(500)
    app.processEvents()

    assert write_count <= 1
    window.close()


def test_workspace_manager_delete_active_workspace_falls_back_safely(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    profile = repository.save_layout_profile(
        LayoutProfile(name="활성", data=json.dumps(window.current_layout_state(), ensure_ascii=False))
    )
    assert profile.id is not None
    window.switch_workspace(profile.id)

    dialog = WorkspaceManagerDialog(repository, window)
    dialog.show()
    app.processEvents()

    dialog.delete_selected_workspace(confirm=False)
    app.processEvents()

    assert repository.get_preferences().active_workspace_id is None
    assert window.preferences.active_workspace_id is None
    assert dialog.profile_list.count() == 0
    dialog.close()
    window.close()


def test_legacy_layout_profiles_are_visible_as_workspaces_with_default_filters(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    legacy_profile = repository.save_layout_profile(LayoutProfile(name="예전 화면", data='{"layout":{}}'))
    assert legacy_profile.id is not None
    # Legacy profiles predate the is_workspace flag; mark this one as a non-workspace
    # profile so it should be excluded from the workspace menu while remaining
    # switchable directly.
    with repository.connect() as connection:
        connection.execute(
            "UPDATE layout_profiles SET is_workspace = 0 WHERE id = ?",
            (legacy_profile.id,),
        )
    window = MainWindow(repository)

    # The workspace menu lists only user-created workspaces (is_workspace = 1).
    menu = window._build_workspace_menu()
    menu_action_texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert "예전 화면" not in menu_action_texts
    assert menu_action_texts[-1] == "워크스페이스 관리..."

    window.switch_workspace(legacy_profile.id)
    app.processEvents()

    assert window._active_workspace_filters == _workspace_filters()
    window.close()


def test_workspace_menu_lists_only_user_created_workspaces(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    user1 = repository.save_layout_profile(
        LayoutProfile(
            name="업무",
            data=json.dumps(_workspace_state(window, show_focus=True, show_quick_memo=True), ensure_ascii=False),
        )
    )
    user2 = repository.save_layout_profile(
        LayoutProfile(
            name="리뷰",
            data=json.dumps(_workspace_state(window, show_focus=False, show_quick_memo=True), ensure_ascii=False),
        )
    )
    assert user1.id is not None
    assert user2.id is not None
    legacy = repository.save_layout_profile(LayoutProfile(name="예전 화면", data='{"layout":{}}'))
    assert legacy.id is not None
    with repository.connect() as connection:
        connection.execute(
            "UPDATE layout_profiles SET is_workspace = 0 WHERE id = ?",
            (legacy.id,),
        )

    menu = window._build_workspace_menu()
    actions = menu.actions()
    action_texts = [action.text() for action in actions if not action.isSeparator()]
    separators = [action for action in actions if action.isSeparator()]
    assert action_texts == ["업무", "리뷰", "빠른 전환 버튼 설정...", "워크스페이스 관리..."]
    assert "예전 화면" not in action_texts
    assert len(separators) == 1
    assert separators[0] is actions[-3]
    assert actions[-1].text() == "워크스페이스 관리..."
    window.close()


def test_feature_width_resize_keeps_neighbors_packed(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1680, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "w": 4, "h": 4},
        {"key": "quick_memo", "w": 4, "h": 4},
        {"key": "link_favorites", "w": 3, "h": 4},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    window.resize_feature_panel_width("focus", window._dashboard_item_pixel_width(2))
    app.processEvents()

    current = window._current_feature_dashboard_layout()
    widths = {str(item["key"]): int(item["w"]) for item in current}
    assert widths["focus"] == window._minimum_feature_dashboard_width("focus")
    assert widths["quick_memo"] == 4
    assert widths["link_favorites"] == 3
    occupied: set[tuple[int, int]] = set()
    for item in current:
        if str(item["key"]) in FLOATING_OVERLAY_FEATURE_KEYS:
            continue
        cells = {
            (column, row)
            for column in range(int(item["x"]), int(item["x"]) + int(item["w"]))
            for row in range(int(item["y"]), int(item["y"]) + int(item["h"]))
        }
        assert occupied.isdisjoint(cells)
        occupied.update(cells)
    window.close()


def test_default_dashboard_layout_is_cleanly_packed(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    layout = window._normalized_feature_dashboard_layout(
        {
            "dashboard": window.default_feature_dashboard_layout(),
            "dashboard_columns": DASHBOARD_GRID_COLUMNS,
            "dashboard_row_height": DASHBOARD_GRID_ROW_HEIGHT,
        }
    )
    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in layout
    }
    occupied: set[tuple[int, int]] = set()
    for item in layout:
        cells = {
            (column, row)
            for column in range(int(item["x"]), int(item["x"]) + int(item["w"]))
            for row in range(int(item["y"]), int(item["y"]) + int(item["h"]))
        }
        assert occupied.isdisjoint(cells)
        occupied.update(cells)

    assert positions["header_banner"] == (0, 0, 12, 3)
    assert positions["focus"] == (0, 3, 3, 16)
    assert positions["quick_memo"] == (3, 3, 3, 16)
    assert positions["today_checklist"] == (6, 3, 3, 16)
    assert positions["today_timeline"] == (9, 3, 3, 16)
    assert positions["pomodoro"] == (0, 19, 3, 6)
    assert positions["link_favorites"] == (3, 19, 3, 6)
    assert positions["media_panel"] == (6, 19, 3, 6)
    assert positions["media_panel_2"] == (9, 19, 3, 6)
    assert positions["datetime"] == (0, 25, 3, 1)
    assert positions["media_panel_3"] == (6, 41, 4, 6)
    assert positions["media_panel_4"] == (2, 41, 4, 6)
    window.close()


def test_reset_main_layout_applies_captured_default_for_existing_users(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = False
    preferences.show_today_checklist_inline = False
    preferences.show_media_panel_2 = False
    preferences.show_datetime_panel = True
    preferences.last_layout_state = ""
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    assert not window.preferences.show_header_banner
    assert not window.preferences.show_today_checklist_inline
    assert not window.preferences.show_media_panel_2

    window.reset_main_layout()
    app.processEvents()

    assert window.preferences.show_header_banner
    assert window.preferences.show_today_checklist_inline
    assert window.preferences.show_media_panel_2
    assert not window.preferences.show_datetime_panel

    reloaded = repository.get_preferences()
    assert reloaded.show_header_banner
    assert reloaded.show_today_checklist_inline
    assert reloaded.show_media_panel_2

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions["focus"] == (0, 3, 3, 16)
    assert positions["today_timeline"] == (9, 3, 3, 16)
    assert positions["media_panel"] == (6, 19, 3, 6)
    assert positions["media_panel_2"] == (9, 19, 3, 6)
    assert positions["datetime"] == (0, 25, 3, 1)

    assert reloaded.last_layout_state
    saved_state = json.loads(reloaded.last_layout_state)
    saved_focus = next(
        item for item in saved_state["layout"]["dashboard"] if item.get("key") == "focus"
    )
    assert (int(saved_focus["x"]), int(saved_focus["y"])) == (0, 3)
    assert saved_state["visible"]["header_banner"] is True
    assert saved_state["visible"]["today_checklist"] is True
    assert saved_state["visible"]["media_panel_2"] is True
    assert saved_state["visible"]["datetime"] is False

    window.close()


def test_restore_last_layout_state_preserves_user_visibility(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = False
    preferences.show_media_panel_2 = False
    preferences.last_layout_state = json.dumps(
        {
            "version": 1,
            "visible": {"header_banner": True, "media_panel_2": True},
        }
    )
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert not window.preferences.show_header_banner
    assert not window.preferences.show_media_panel_2
    assert not repository.get_preferences().show_header_banner
    assert not repository.get_preferences().show_media_panel_2

    window.close()


def test_hidden_header_banner_does_not_block_dashboard_top_space(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = False
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    focus_cell = window.feature_cells["focus"]
    focus_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(focus_cell)
    )
    assert focus_position[:2] == (0, 0)

    window.close()


def test_pinning_panel_preserves_visible_slot_when_header_banner_is_hidden(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = False
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    focus_cell = window.feature_cells["focus"]
    before_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(focus_cell)
    )
    assert before_position[:2] == (0, 0)

    window.set_feature_panel_pinned("focus", True)
    app.processEvents()

    pinned_cell = window.feature_cells["focus"]
    after_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(pinned_cell)
    )
    assert after_position[:2] == before_position[:2]
    assert window.feature_panel_pinned("focus")
    saved_focus = next(
        item
        for item in window.current_layout_state()["layout"]["dashboard"]
        if item.get("key") == "focus"
    )
    assert (int(saved_focus["x"]), int(saved_focus["y"])) == (0, 0)
    assert saved_focus.get("pinned") is True

    window.close()


def test_datetime_panel_overlays_other_dashboard_items(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_datetime_panel = True
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    datetime_box = window.feature_boxes["datetime"]
    assert datetime_box.title_label is None
    assert datetime_box.header_band is not None
    assert datetime_box.move_bar is not None
    assert datetime_box.move_bar.maximumHeight() == PANEL_MOVE_BAR_HEIGHT
    assert datetime_box.content_drag_enabled is True

    window.feature_dashboard_items = [
        {"key": "datetime", "x": 0, "y": 0, "w": 4, "h": 2},
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    datetime_cell = window.feature_cells["datetime"]
    focus_cell = window.feature_cells["focus"]
    # datetime renders as a floating overlay child (direct child positioned by geometry),
    # not a grid item, so it never consumes a grid slot.
    assert datetime_cell.parent() is window.feature_grid_container
    assert window.feature_dashboard_layout.indexOf(datetime_cell) == -1
    focus_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(focus_cell)
    )
    assert focus_position[:2] == (0, 0)
    # The overlay still sits on top of focus at the same container origin.
    assert datetime_cell.geometry().topLeft() == focus_cell.geometry().topLeft()

    window.close()


def test_datetime_overlay_moves_and_resizes_without_repacking_neighbors(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_datetime_panel = True
    preferences.show_focus_panel = True
    preferences.show_quick_memo_panel = True
    preferences.show_pomodoro_controls = True
    preferences.show_today_checklist_inline = True
    preferences.show_header_banner = False
    preferences.show_today_timeline_inline = False
    preferences.show_link_favorites_panel = False
    preferences.show_media_panel = False
    preferences.show_media_panel_2 = False
    preferences.show_media_panel_3 = False
    preferences.show_media_panel_4 = False
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # datetime overlaps row 0 where focus/quick_memo/pomodoro live; today_checklist
    # sits below at row 4. Moving or resizing the floating datetime overlay must only
    # change datetime's own geometry, never nudge these neighbors.
    window.feature_dashboard_items = [
        {"key": "datetime", "x": 0, "y": 0, "w": 3, "h": 2},
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 4, "y": 0, "w": 4, "h": 4},
        {"key": "pomodoro", "x": 8, "y": 0, "w": 4, "h": 4},
        {"key": "today_checklist", "x": 0, "y": 4, "w": 4, "h": 4},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    neighbor_keys = ("focus", "quick_memo", "pomodoro", "today_checklist")

    def neighbor_geometries() -> dict[str, tuple[int, int, int, int]]:
        geometries: dict[str, tuple[int, int, int, int]] = {}
        for key in neighbor_keys:
            rect = window.feature_cells[key].geometry()
            geometries[key] = (rect.x(), rect.y(), rect.width(), rect.height())
        return geometries

    before_geometries = neighbor_geometries()

    # The floating datetime overlay is a direct child positioned by geometry, not a
    # grid item that consumes row space.
    datetime_cell = window.feature_cells["datetime"]
    assert datetime_cell.parent() is window.feature_grid_container
    assert window.feature_dashboard_layout.indexOf(datetime_cell) == -1

    row_step = int(DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP)
    target = window.feature_grid_container.mapToGlobal(QPoint(0, row_step))
    assert window._move_feature_to_dashboard_position("datetime", target, QPoint(0, 0))
    app.processEvents()

    moved = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert moved["datetime"][:2] == (0, 1)
    assert moved["focus"][:2] == (0, 0)
    assert moved["quick_memo"][:2] == (4, 0)
    assert moved["pomodoro"][:2] == (8, 0)
    assert moved["today_checklist"][:2] == (0, 4)
    # The regression: neighbor widget geometry must stay pixel-identical because their
    # slots did not change.
    assert neighbor_geometries() == before_geometries

    window._resize_feature_dashboard_item("datetime", width=window._dashboard_item_pixel_width(2))
    app.processEvents()
    resized = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert resized["focus"][:2] == (0, 0)
    assert resized["datetime"][2] == 2
    assert neighbor_geometries() == before_geometries

    window._resize_feature_dashboard_item("datetime", height=window._dashboard_item_pixel_height(3))
    app.processEvents()
    resized_height = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert resized_height["focus"][:2] == (0, 0)
    assert resized_height["datetime"][3] == 3
    assert neighbor_geometries() == before_geometries

    window.close()


def test_header_banner_position_setting_updates_dashboard_slot(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.show_header_banner = True
    preferences.header_banner_position = "right"
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "header_banner", "x": 0, "y": 5, "w": 4, "h": 3},
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
    ]
    window.move_header_banner_to_preferred_column()
    header = next(item for item in window._current_feature_dashboard_layout() if item["key"] == "header_banner")
    assert (int(header["x"]), int(header["y"]), int(header["w"])) == (8, 0, 4)

    window.close()


def test_feature_move_preserves_panel_size_and_repacks_neighbors_cleanly(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 6, "h": 7},
        {"key": "link_favorites", "x": 6, "y": 0, "w": 1, "h": 2},
        {"key": "quick_memo", "x": 7, "y": 0, "w": 5, "h": 7},
        {"key": "pomodoro", "x": 6, "y": 7, "w": 2, "h": 2},
    ]
    window._render_feature_dashboard()
    app.processEvents()
    before = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }

    window.swap_feature_panels("focus", "link_favorites", "after")
    app.processEvents()

    after = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert after["focus"][:2] == (6, 0)
    assert after["focus"][2:] == before["focus"][2:]
    assert after["link_favorites"][:2] == (0, 0)
    assert after["link_favorites"][2:] == before["link_favorites"][2:]
    assert after["quick_memo"][:2] == (1, 0)

    occupied: set[tuple[int, int]] = set()
    for key, (x, y, width, height) in after.items():
        if key in FLOATING_OVERLAY_FEATURE_KEYS:
            continue
        cells = {
            (column, row)
            for column in range(x, x + width)
            for row in range(y, y + height)
        }
        assert occupied.isdisjoint(cells)
        occupied.update(cells)
    window.close()


def test_dashboard_feature_can_move_to_empty_grid_position(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 2, "h": 3},
        {"key": "quick_memo", "x": 3, "y": 0, "w": 2, "h": 3},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    drop_point = QPoint(
        int(round((window._dashboard_column_width() + DASHBOARD_GRID_GAP) * 4)),
        int(round((DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP) * 4)),
    )
    assert window._move_feature_to_dashboard_position("focus", window.feature_grid_container.mapToGlobal(drop_point))
    app.processEvents()

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    expected_focus_x = window._normalized_dashboard_x(4, window._minimum_feature_dashboard_width("focus"))
    assert positions["focus"] == (expected_focus_x, 4)
    assert positions["quick_memo"] == (3, 0)
    window.close()


def test_dashboard_move_pushes_neighbors_sideways_when_space_remains(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 4, "y": 0, "w": 4, "h": 4},
        *_dashboard_support_items(6, {"focus", "quick_memo"}),
    ]
    window._render_feature_dashboard()
    app.processEvents()

    column_step = window._dashboard_column_width() + DASHBOARD_GRID_GAP
    drop_global = window.feature_grid_container.mapToGlobal(QPoint(int(round(column_step * 4)), 0))
    assert window._move_feature_to_dashboard_position("focus", drop_global)
    app.processEvents()

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions["focus"] == (4, 0)
    assert positions["quick_memo"] == (8, 0)
    window.close()


def _dashboard_layout_has_no_overlap(items: list[dict[str, object]]) -> bool:
    """True when no two non-floating panels share a grid cell."""
    occupied: set[tuple[int, int]] = set()
    for item in items:
        if str(item.get("key", "")) == "datetime":
            continue
        x, y = int(item["x"]), int(item["y"])
        w, h = int(item["w"]), int(item["h"])
        for cx in range(x, x + w):
            for cy in range(y, y + h):
                if (cx, cy) in occupied:
                    return False
                occupied.add((cx, cy))
    return True


def test_dashboard_move_pushes_neighbor_sideways_then_down_when_row_is_full(tmp_path) -> None:
    # When a panel is dropped onto a full row, the move is never blocked: the
    # dragged panel takes the target slot and displaced neighbors slide sideways
    # if the row still has room, otherwise drop to the next row. Nothing floats up.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 4, "y": 0, "w": 4, "h": 4},
        {"key": "link_favorites", "x": 8, "y": 0, "w": 4, "h": 4},
        *_dashboard_support_items(6, {"focus", "quick_memo", "link_favorites"}),
    ]
    window._render_feature_dashboard()
    app.processEvents()

    column_step = window._dashboard_column_width() + DASHBOARD_GRID_GAP
    drop_global = window.feature_grid_container.mapToGlobal(QPoint(int(round(column_step * 4)), 0))
    assert window._move_feature_to_dashboard_position("focus", drop_global)
    app.processEvents()

    items = [dict(item) for item in window._current_feature_dashboard_layout()]
    positions = {str(item["key"]): (int(item["x"]), int(item["y"])) for item in items}
    # Dragged panel lands exactly at the target slot.
    assert positions["focus"] == (4, 0)
    # quick_memo had room to its right, so it slides sideways within row 0.
    assert positions["quick_memo"] == (8, 0)
    # link_favorites had no lateral room left, so it drops straight down.
    assert positions["link_favorites"] == (8, 4)
    # No panel floated above its row and nothing overlaps.
    assert _dashboard_layout_has_no_overlap(items)
    window.close()


def test_dashboard_media_drag_pushes_neighbors_down_instead_of_blocking(tmp_path) -> None:
    # Dragging media onto a full row pushes the overlapped neighbors down rather
    # than blocking, and the drag preview matches the committed drop exactly.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 5, "h": 4},
        {"key": "quick_memo", "x": 5, "y": 0, "w": 4, "h": 4},
        {"key": "media_panel", "x": 9, "y": 0, "w": 3, "h": 4},
        *_dashboard_support_items(6, {"focus", "quick_memo", "media_panel"}),
    ]
    window._render_feature_dashboard()
    app.processEvents()

    column_step = window._dashboard_column_width() + DASHBOARD_GRID_GAP
    drag_offset = QPoint(10, 10)
    drop_global = window.feature_grid_container.mapToGlobal(QPoint(int(round(column_step * 2)) + 10, 10))

    preview = window._dashboard_preview_item("media_panel", drop_global, drag_offset)
    assert preview is not None
    # Preview shows the dragged panel at the target slot...
    assert (int(preview["x"]), int(preview["y"])) == (2, 0)

    window.finish_feature_reposition("media_panel", drop_global, drag_offset)
    app.processEvents()

    items = [dict(item) for item in window._current_feature_dashboard_layout()]
    positions = {str(item["key"]): (int(item["x"]), int(item["y"])) for item in items}
    # ...and the commit matches the preview, with the overlapped panel pushed down.
    assert positions["media_panel"] == (2, 0)
    assert positions["focus"] == (0, 4)
    assert positions["quick_memo"] == (5, 0)
    assert _dashboard_layout_has_no_overlap(items)
    window.close()


def test_dashboard_banner_drag_prefers_grid_position_and_pushes_neighbors_down(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "header_banner", "x": 0, "y": 0, "w": 12, "h": 3},
        {"key": "focus", "x": 0, "y": 3, "w": 5, "h": 4},
        {"key": "quick_memo", "x": 5, "y": 3, "w": 4, "h": 4},
        {"key": "media_panel", "x": 9, "y": 3, "w": 3, "h": 4},
        *_dashboard_support_items(9, {"header_banner", "focus", "quick_memo", "media_panel"}),
    ]
    window._render_feature_dashboard()
    app.processEvents()

    row_step = DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP
    drag_offset = QPoint(10, 10)
    drop_global = window.feature_grid_container.mapToGlobal(QPoint(10, int(round(row_step * 3)) + 10))

    preview = window._dashboard_preview_item("header_banner", drop_global, drag_offset)
    assert preview is not None
    assert (int(preview["x"]), int(preview["y"])) == (0, 3)

    window.finish_feature_reposition("header_banner", drop_global, drag_offset)
    app.processEvents()

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions["header_banner"] == (0, 3)
    assert positions["focus"] != (0, 0)
    assert positions["focus"][1] >= 6
    assert positions["quick_memo"][1] >= 6
    assert positions["media_panel"][1] >= 6
    window.close()


def test_dashboard_width_resize_pushes_neighbors_in_growth_direction(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 4, "y": 0, "w": 4, "h": 4},
        {"key": "link_favorites", "x": 8, "y": 0, "w": 4, "h": 4},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    window.resize_feature_panel_width("focus", window._dashboard_item_pixel_width(6))
    app.processEvents()

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions["focus"] == (0, 0, 6)
    assert positions["quick_memo"] == (6, 0, 4)
    assert positions["link_favorites"][1] >= 4
    window.close()


def test_dashboard_height_resize_pushes_neighbors_down(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 0, "y": 4, "w": 4, "h": 4},
        {"key": "link_favorites", "x": 4, "y": 4, "w": 4, "h": 4},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    window.resize_feature_panel_height("focus", window._dashboard_item_pixel_height(6))
    app.processEvents()

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions["focus"] == (0, 0, 6)
    assert positions["quick_memo"] == (0, 6, 4)
    assert positions["link_favorites"] == (4, 4, 4)
    window.close()


def test_dashboard_feature_pin_blocks_move_and_resize(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    focus_cell = window.feature_cells["focus"]
    before_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(focus_cell)
    )
    window.set_feature_panel_pinned("focus", True)
    assert window.feature_panel_pinned("focus")

    window._move_feature_in_dashboard("focus", "quick_memo")
    window.resize_feature_panel_width("focus", window._dashboard_item_pixel_width(12))
    window.resize_feature_panel_height("focus", window._dashboard_item_pixel_height(12))
    app.processEvents()

    pinned_cell = window.feature_cells["focus"]
    after_position = window.feature_dashboard_layout.getItemPosition(
        window.feature_dashboard_layout.indexOf(pinned_cell)
    )
    assert after_position == before_position
    focus_item = next(item for item in window._current_feature_dashboard_layout() if item.get("key") == "focus")
    assert (
        int(focus_item["x"]),
        int(focus_item["y"]),
        int(focus_item["w"]),
        int(focus_item["h"]),
        bool(focus_item.get("pinned", False)),
    ) == (before_position[1], before_position[0], before_position[3], before_position[2], True)
    assert any(item.get("key") == "focus" and item.get("pinned") for item in window.current_layout_state()["layout"]["dashboard"])
    window.close()


def test_dashboard_drag_uses_grab_offset_for_empty_grid_preview(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 8, "y": 0, "w": 3, "h": 3},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    focus_box = window.feature_boxes["focus"]
    grab_global = focus_box.mapToGlobal(QPoint(focus_box.width() // 2, 14))
    focus_box.begin_feature_reposition_gesture(grab_global, focus_box)
    drag_offset = QPoint(focus_box.panel_drag_offset)
    column_step = window._dashboard_column_width() + DASHBOARD_GRID_GAP
    row_step = DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP
    target_top_left = QPoint(int(round(column_step * 4)), int(round(row_step * 5)))
    cursor_local = QPoint(target_top_left.x() + drag_offset.x(), target_top_left.y() + drag_offset.y())
    cursor_global = window.feature_grid_container.mapToGlobal(cursor_local)

    preview = window._dashboard_preview_item("focus", cursor_global, drag_offset)
    assert preview is not None
    assert (int(preview["x"]), int(preview["y"])) == (4, 5)

    assert window._move_feature_to_dashboard_position("focus", cursor_global, drag_offset)
    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions["focus"] == (4, 5)
    window.close()


def test_dashboard_move_preserves_scroll_position(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(980, 420)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": key, "x": 0, "y": index * 5, "w": 4, "h": 4}
        for index, key in enumerate(window.feature_boxes)
    ]
    window._render_feature_dashboard()
    app.processEvents()

    scroll_bar = window.full_scroll_area.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    scroll_bar.setValue(min(260, scroll_bar.maximum()))
    before = scroll_bar.value()

    window._move_feature_in_dashboard("focus", "quick_memo")
    app.processEvents()

    assert scroll_bar.value() == before
    window.close()


def test_dashboard_drag_auto_scrolls_near_viewport_edges(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(980, 420)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": key, "x": 0, "y": index * 5, "w": 4, "h": 4}
        for index, key in enumerate(window.feature_boxes)
    ]
    window._render_feature_dashboard()
    app.processEvents()

    scroll_bar = window.full_scroll_area.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    scroll_bar.setValue(0)
    viewport = window.full_scroll_area.viewport()
    bottom_global = viewport.mapToGlobal(QPoint(viewport.width() // 2, viewport.height() - 3))
    window.auto_scroll_feature_drag(bottom_global)
    app.processEvents()

    assert scroll_bar.value() > 0
    window.close()


def test_dashboard_width_resize_from_left_keeps_right_edge(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 4, "y": 0, "w": 4, "h": 4},
        {"key": "quick_memo", "x": 0, "y": 6, "w": 4, "h": 3},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    window.resize_feature_panel_width_from_edge("focus", window._dashboard_item_pixel_width(6), "left")
    expanded = next(item for item in window._current_feature_dashboard_layout() if item["key"] == "focus")
    assert (int(expanded["x"]), int(expanded["w"])) == (2, 6)
    assert int(expanded["x"]) + int(expanded["w"]) == 8

    window.resize_feature_panel_width_from_edge("focus", window._dashboard_item_pixel_width(3), "left")
    shrunk = next(item for item in window._current_feature_dashboard_layout() if item["key"] == "focus")
    assert (int(shrunk["x"]), int(shrunk["w"])) == (5, 3)
    assert int(shrunk["x"]) + int(shrunk["w"]) == 8
    window.close()


def test_all_dashboard_features_can_resize_to_min_and_max_width(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    feature_keys = list(window.feature_boxes)
    for feature_key in feature_keys:
        window.resize_feature_panel_width(feature_key, window._dashboard_item_pixel_width(1))
        app.processEvents()
        widths = {
            str(item["key"]): int(item["w"])
            for item in window._current_feature_dashboard_layout()
        }
        assert widths[feature_key] == window._minimum_feature_dashboard_width(feature_key)

        window.resize_feature_panel_width(feature_key, window._dashboard_item_pixel_width(12))
        app.processEvents()
        widths = {
            str(item["key"]): int(item["w"])
            for item in window._current_feature_dashboard_layout()
        }
        assert widths[feature_key] == 12
    window.close()


def test_dashboard_migrates_legacy_six_column_layout_to_finer_grid(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    migrated = window._normalized_feature_dashboard_layout(
        {
            "dashboard": [
                {"key": "focus", "x": 3, "y": 2, "w": 3, "h": 5},
            ]
        }
    )
    focus = next(item for item in migrated if item["key"] == "focus")

    assert focus["x"] == 6
    assert focus["w"] == 6
    assert focus["y"] == 3
    assert focus["h"] == 7
    window.close()


def test_feature_resize_edges_work_without_visible_corner_grip(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    focus_box = window.feature_boxes["focus"]
    focus_box.resize(320, 240)
    app.processEvents()

    assert focus_box.resize_grip.objectName() == "featureResizeGrip"
    assert not focus_box.resize_grip.isVisible()
    assert focus_box._is_resize_edge(QPoint(20, focus_box.height() // 2))
    assert focus_box._is_resize_edge(QPoint(focus_box.width() - 20, focus_box.height() // 2))
    assert focus_box._is_height_resize_edge(QPoint(focus_box.width() // 2, focus_box.height() - 22))
    pomodoro_box = window.feature_boxes["pomodoro"]
    assert focus_box._minimum_resize_pixel_height() == 200
    assert pomodoro_box._minimum_resize_pixel_height() == 160
    window.close()


def test_feature_box_resize_band_ignores_interactive_children(tmp_path) -> None:
    app = _app()

    combo = QComboBox()
    combo.addItem("항목")
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    box = DraggableFeatureBox("today_checklist", "체크리스트", combo, lambda *_args: None)
    box.height_callback = lambda *_args: None
    box.resize_edge_callback = lambda *_args: None
    box.resize_callback = lambda *_args: None
    box.resize(320, 240)
    app.processEvents()

    # Given: an interactive child whose mapped position sits in the box resize bands.
    assert box._is_interactive_child(combo)
    height_band = QPoint(box.width() // 2, box.height() - 4)
    width_band = QPoint(box.width() - 4, box.height() // 2)
    assert box._is_height_resize_edge(height_band)
    assert box._resize_edge_at(width_band) == "right"

    def _mouse_event(event_type, box_point, button):
        return QMouseEvent(
            event_type,
            QPointF(combo.mapFrom(box, box_point)),
            QPointF(box.mapToGlobal(box_point)),
            button,
            button,
            Qt.KeyboardModifier.NoModifier,
        )

    # When: hovering the child inside the height/width bands.
    # Then: the resize cursors never overwrite the child's own cursor.
    box._handle_filtered_mouse_move(
        combo, _mouse_event(QEvent.Type.MouseMove, height_band, Qt.MouseButton.NoButton)
    )
    assert combo.cursor().shape() == Qt.CursorShape.PointingHandCursor
    box._handle_filtered_mouse_move(
        combo, _mouse_event(QEvent.Type.MouseMove, width_band, Qt.MouseButton.NoButton)
    )
    assert combo.cursor().shape() == Qt.CursorShape.PointingHandCursor

    # When: pressing the child inside the height/width bands.
    # Then: panel resizing must not begin.
    height_press = box._handle_filtered_mouse_press(
        combo, _mouse_event(QEvent.Type.MouseButtonPress, height_band, Qt.MouseButton.LeftButton)
    )
    assert height_press is False
    assert box.resizing_height is False
    assert box.resizing_span is False

    width_press = box._handle_filtered_mouse_press(
        combo, _mouse_event(QEvent.Type.MouseButtonPress, width_band, Qt.MouseButton.LeftButton)
    )
    assert width_press is False
    assert box.resizing_height is False
    assert box.resizing_span is False

    box.deleteLater()
    app.processEvents()


def test_panel_inputs_and_dropdowns_use_intent_cursors(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    ibeam = Qt.CursorShape.IBeamCursor
    pointer = Qt.CursorShape.PointingHandCursor
    timeline = window.inline_timeline_widget
    checklist = window.today_checklist_widget

    text_inputs = {
        "focus_title_edit": window.focus_title_edit,
        "quick_note_editor": window.quick_note_editor,
        "new_task_edit": checklist.new_task_edit,
        "timeline_event_edit": timeline.timeline_event_edit,
    }
    for name, widget in text_inputs.items():
        assert widget.cursor().shape() == ibeam, name

    dropdowns = {
        "quick_note_folder_combo": window.quick_note_folder_combo,
        "note_filter_combo": window.note_filter_combo,
        "target_combo": window.target_combo,
        "new_task_type_combo": checklist.new_task_type_combo,
        "timeline_filter_combo": timeline.timeline_filter_combo,
        "timeline_event_type_combo": timeline.timeline_event_type_combo,
    }
    for name, combo in dropdowns.items():
        assert combo.cursor().shape() == pointer, name
        assert combo.view().cursor().shape() == pointer, f"{name} view"

    assert timeline.block_table.cursor().shape() == pointer
    assert timeline.block_table.viewport().cursor().shape() == pointer

    window.close()


def test_dashboard_drag_guides_show_preview(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    target_cell = window.feature_cells["today_timeline"]
    window._show_dashboard_drag_guides("focus", target_cell.mapToGlobal(target_cell.rect().center()))
    app.processEvents()

    overlay = window.dashboard_guide_overlay
    assert overlay.isVisible()
    assert overlay.preview_rect.isValid()
    assert overlay.preview_rect.width() > 0
    assert overlay.preview_rect.height() > 0
    assert overlay.preview_rect.right() <= window.feature_grid_container.width() + 1
    assert overlay.impact_rects
    assert all(rect.isValid() and not rect.isNull() for rect in overlay.impact_rects)
    preview_item = window._dashboard_preview_item("focus", target_cell.mapToGlobal(target_cell.rect().center()))
    assert preview_item is not None
    focus_item = next(item for item in window._current_feature_dashboard_layout() if item["key"] == "focus")
    assert int(preview_item["w"]) == int(focus_item["w"])
    assert int(preview_item["h"]) == int(focus_item["h"])

    window._hide_dashboard_drag_guides()
    assert not overlay.isVisible()
    window.close()


def _dashboard_slot(item: dict[str, object]) -> tuple[int, int, int, int]:
    return (
        int(item.get("x", 0)),
        int(item.get("y", 0)),
        int(item.get("w", 1)),
        int(item.get("h", 1)),
    )


def test_show_dashboard_drag_guides_preserves_layout_and_matches_preview(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    target_cell = window.feature_cells["today_timeline"]
    target_global = target_cell.mapToGlobal(target_cell.rect().center())

    layout_before = [dict(item) for item in window._current_feature_dashboard_layout()]
    stored_before = [dict(item) for item in getattr(window, "feature_dashboard_items", [])]

    window._show_dashboard_drag_guides("focus", target_global)
    app.processEvents()

    # Showing guides must not mutate the live dashboard layout (preview is non-destructive).
    assert [dict(item) for item in window._current_feature_dashboard_layout()] == layout_before
    assert [dict(item) for item in getattr(window, "feature_dashboard_items", [])] == stored_before

    overlay = window.dashboard_guide_overlay
    assert overlay.isVisible()

    # preview_rect now follows the grabbed source panel (its own size plus the
    # pointer/grab offset), instead of snapping onto the previewed target grid slot.
    source_cell = window.feature_cells["focus"]
    assert overlay.preview_rect.width() == float(source_cell.width())
    assert overlay.preview_rect.height() == float(source_cell.height())
    assert overlay.preview_rect == window._dashboard_drag_preview_rect("focus", target_global)

    # impact_rects correspond exactly to the non-source panels whose slots change.
    preview_layout = window._dashboard_preview_layout("focus", target_global)
    current_slots = {
        str(item.get("key", "")): _dashboard_slot(item)
        for item in window._current_feature_dashboard_layout()
    }
    changed_keys = []
    for item in preview_layout:
        key = str(item.get("key", ""))
        if not key or key == "focus":
            continue
        if current_slots.get(key) != _dashboard_slot(item):
            changed_keys.append(key)
    assert changed_keys
    assert overlay.impact_rects == window._dashboard_preview_impact_rects("focus", preview_layout)
    assert len(overlay.impact_rects) == len(changed_keys)

    window._hide_dashboard_drag_guides()
    window.close()


def test_hide_dashboard_drag_guides_clears_state_and_preserves_layout(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    target_cell = window.feature_cells["today_timeline"]
    target_global = target_cell.mapToGlobal(target_cell.rect().center())

    layout_before = [dict(item) for item in window._current_feature_dashboard_layout()]
    stored_before = [dict(item) for item in getattr(window, "feature_dashboard_items", [])]

    window._show_dashboard_drag_guides("focus", target_global)
    app.processEvents()
    overlay = window.dashboard_guide_overlay
    assert overlay.preview_rect.isValid()
    assert overlay.impact_rects

    window._hide_dashboard_drag_guides()

    # Cancelling clears the preview/impact state...
    assert not overlay.isVisible()
    assert not overlay.preview_rect.isValid()
    assert overlay.preview_rect.isNull()
    assert overlay.impact_rects == []
    # ...and the abandoned drag preserves the prior layout untouched.
    assert [dict(item) for item in window._current_feature_dashboard_layout()] == layout_before
    assert [dict(item) for item in getattr(window, "feature_dashboard_items", [])] == stored_before

    window.close()


def test_dashboard_drag_preview_follows_grab_not_snapped_slot(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 5},
        {"key": "quick_memo", "x": 8, "y": 0, "w": 3, "h": 3},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    container = window.feature_grid_container
    source_cell = window.feature_cells["focus"]
    column_step = window._dashboard_column_width() + DASHBOARD_GRID_GAP
    row_step = DASHBOARD_GRID_ROW_HEIGHT + DASHBOARD_GRID_GAP

    # Grab the panel near its top-left corner and drag toward a far grid slot.
    drag_offset = QPoint(30, 18)
    # Followed top-left sits a little past slot (4, 5) yet still snaps onto it.
    followed = QPoint(int(round(column_step * 4)) + 20, int(round(row_step * 5)) + 12)
    cursor_local = QPoint(followed.x() + drag_offset.x(), followed.y() + drag_offset.y())
    cursor_global = container.mapToGlobal(cursor_local)

    window._show_dashboard_drag_guides("focus", cursor_global, drag_offset)
    app.processEvents()

    overlay = window.dashboard_guide_overlay
    assert overlay.isVisible()

    # Preview size mirrors the grabbed source cell, not a stand-in grid slot.
    assert overlay.preview_rect.width() == float(source_cell.width())
    assert overlay.preview_rect.height() == float(source_cell.height())

    # Preview top-left tracks the pointer minus the grab offset.
    assert abs(overlay.preview_rect.left() - followed.x()) <= 1.0
    assert abs(overlay.preview_rect.top() - followed.y()) <= 1.0

    # The preview does NOT collapse onto the snapped target grid slot rectangle.
    preview_item = window._dashboard_preview_item("focus", cursor_global, drag_offset)
    assert preview_item is not None
    assert (int(preview_item["x"]), int(preview_item["y"])) == (4, 5)
    snapped_rect = window._dashboard_item_rect(preview_item)
    assert overlay.preview_rect != snapped_rect
    assert overlay.preview_rect.topLeft() != snapped_rect.topLeft()

    window._hide_dashboard_drag_guides()
    window.close()


def test_show_dashboard_drag_guides_repeated_same_values_no_flicker(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    target_cell = window.feature_cells["today_timeline"]
    target_global = target_cell.mapToGlobal(target_cell.rect().center())

    window._show_dashboard_drag_guides("focus", target_global)
    app.processEvents()
    overlay = window.dashboard_guide_overlay
    assert overlay.isVisible()

    first_preview = QRectF(overlay.preview_rect)
    first_impacts = [QRectF(rect) for rect in overlay.impact_rects]
    layout_after_first = [dict(item) for item in window._current_feature_dashboard_layout()]

    hide_calls = {"count": 0}
    update_calls = {"count": 0}
    original_hide = overlay.hide
    original_update = overlay.update

    def counting_hide(*args, **kwargs):
        hide_calls["count"] += 1
        return original_hide(*args, **kwargs)

    def counting_update(*args, **kwargs):
        update_calls["count"] += 1
        return original_update(*args, **kwargs)

    overlay.hide = counting_hide
    overlay.update = counting_update
    try:
        # Re-show with byte-identical inputs: the overlay is already visible.
        window._show_dashboard_drag_guides("focus", target_global)
        app.processEvents()
    finally:
        overlay.hide = original_hide
        overlay.update = original_update

    # An identical re-show must not hide the visible overlay (no hide/show flicker)...
    assert hide_calls["count"] == 0
    assert overlay.isVisible()
    # ...nor schedule a repaint for unchanged preview/impact state...
    assert update_calls["count"] == 0
    # ...and the preview/impact geometry stays identical.
    assert overlay.preview_rect == first_preview
    assert overlay.impact_rects == first_impacts
    # The repeated non-destructive preview must not mutate the live layout.
    assert [dict(item) for item in window._current_feature_dashboard_layout()] == layout_after_first

    window._hide_dashboard_drag_guides()
    window.close()


def test_reposition_gesture_keeps_closed_hand_over_resize_edges(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 4, "h": 5},
        {"key": "quick_memo", "x": 8, "y": 0, "w": 3, "h": 3},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    box = window.feature_boxes["focus"]
    box.content_drag_enabled = True
    width = box.width()
    height = box.height()
    # The panel must be large enough to expose both resize edges.
    assert width >= box._minimum_resize_pixel_width()
    assert height >= 80
    assert box.resize_callback is not None or box.resize_edge_callback is not None
    assert box.height_callback is not None

    def move_event(local_point, buttons):
        return QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(local_point),
            box.mapToGlobal(local_point),
            Qt.MouseButton.NoButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    right_edge = QPoint(width - 2, height // 2)
    bottom_edge = QPoint(width // 2, height - 2)

    # Baseline: hovering the right edge without holding shows the width-resize cursor.
    box.mouseMoveEvent(move_event(right_edge, Qt.MouseButton.NoButton))
    assert box.cursor().shape() == Qt.CursorShape.SizeHorCursor

    # Begin holding a reposition gesture right on the width-resize edge.
    box.begin_feature_reposition_gesture(box.mapToGlobal(right_edge), box)
    assert box.cursor().shape() == Qt.CursorShape.ClosedHandCursor

    # A nudge below the drag threshold must NOT revert to the resize cursor.
    nudge_px = max(1, QApplication.startDragDistance() // 2)
    box.mouseMoveEvent(move_event(QPoint(width - 2 - nudge_px, height // 2), Qt.MouseButton.LeftButton))
    assert box.panel_drag_active is False
    assert box.cursor().shape() == Qt.CursorShape.ClosedHandCursor

    # Crossing the threshold over the bottom (height) resize edge stays grabbing.
    box.mouseMoveEvent(move_event(bottom_edge, Qt.MouseButton.LeftButton))
    assert box.panel_drag_active is True
    assert box.cursor().shape() == Qt.CursorShape.ClosedHandCursor

    # Releasing ends the gesture; resize cursors work again when not holding.
    box.finish_feature_reposition_gesture(box.mapToGlobal(right_edge), box)
    box.mouseMoveEvent(move_event(right_edge, Qt.MouseButton.NoButton))
    assert box.cursor().shape() == Qt.CursorShape.SizeHorCursor

    window._hide_dashboard_drag_guides()
    window.close()


def test_download_site_icon_uses_declared_favicon(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, data: bytes, content_type: str) -> None:
            self.data = data
            self.headers = {"Content-Type": content_type}

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return self.data

    calls: list[str] = []

    def fake_urlopen(request, timeout: int):
        assert timeout == 8
        url = request.full_url
        calls.append(url)
        if url == "https://youtube.com":
            return FakeResponse(
                b'<html><head><link rel="icon" href="/favicon-32.png"></head></html>',
                "text/html; charset=utf-8",
            )
        if url == "https://youtube.com/favicon-32.png":
            return FakeResponse(b"png-data", "image/png")
        raise AssertionError(url)

    monkeypatch.setattr("app.ui.main_window.urlopen", fake_urlopen)

    file_name, data = _download_site_icon("youtube.com")

    assert file_name == "favicon-32.png"
    assert data == b"png-data"
    assert calls == ["https://youtube.com", "https://youtube.com/favicon-32.png"]


def test_download_site_icon_falls_back_when_home_page_is_too_large(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, data: bytes, content_type: str) -> None:
            self.data = data
            self.headers = {"Content-Type": content_type}

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            return None

        def read(self, limit: int) -> bytes:
            if self.headers["Content-Type"].startswith("text/html"):
                return b"x" * limit
            return self.data

    calls: list[str] = []

    def fake_urlopen(request, timeout: int):
        assert timeout == 8
        url = request.full_url
        calls.append(url)
        if url == "https://large.example.com":
            return FakeResponse(b"", "text/html")
        if url == "https://large.example.com/favicon.ico":
            return FakeResponse(b"ico-data", "image/x-icon")
        raise AssertionError(url)

    monkeypatch.setattr("app.ui.main_window.urlopen", fake_urlopen)

    file_name, data = _download_site_icon("large.example.com")

    assert file_name == "favicon.ico"
    assert data == b"ico-data"
    assert calls == ["https://large.example.com", "https://large.example.com/favicon.ico"]


def _vertical_wheel_event(widget: QWidget, steps: int) -> QWheelEvent:
    center = widget.rect().center()
    return QWheelEvent(
        QPointF(center),
        QPointF(widget.mapToGlobal(center)),
        QPoint(0, 0),
        QPoint(0, 120 * steps),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_settings_font_size_spin_ignores_wheel_until_focused(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    spin = dialog.findChild(QSpinBox, "mainFontSizeSpin")
    assert isinstance(spin, NoScrollSpinBox)

    spin.clearFocus()
    app.processEvents()
    assert not spin.hasFocus()

    # Wheeling over an unfocused spin box must not silently change its value.
    unfocused_start = spin.value()
    QApplication.sendEvent(spin, _vertical_wheel_event(spin, 1))
    assert spin.value() == unfocused_start

    # Programmatic setValue still works while the spin box is unfocused.
    spin.setValue(unfocused_start + 1)
    assert spin.value() == unfocused_start + 1

    # Once the spin box owns focus the wheel adjusts the value again.
    dialog.activateWindow()
    spin.setFocus()
    app.processEvents()
    assert spin.hasFocus()
    focused_start = spin.value()
    QApplication.sendEvent(spin, _vertical_wheel_event(spin, 1))
    assert spin.value() > focused_start

    dialog.close()


def test_settings_font_combos_ignore_wheel_until_focused(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    # The font combos are disabled while the "use default font" switches are on,
    # so uncheck both to enable them before exercising the wheel guard.
    dialog.use_default_datetime_font_check.setChecked(False)
    dialog.use_default_main_font_check.setChecked(False)
    app.processEvents()

    for object_name in ("datetimeFontCombo", "mainFontCombo"):
        combo = dialog.findChild(NoScrollFontComboBox, object_name)
        assert isinstance(combo, NoScrollFontComboBox), object_name
        assert combo.focusPolicy() == Qt.FocusPolicy.StrongFocus, object_name
        assert combo.isEnabled(), object_name

        combo.clearFocus()
        app.processEvents()
        assert not combo.hasFocus(), object_name

        # Wheeling over an unfocused font combo must not silently change the font.
        unfocused_index = combo.currentIndex()
        unfocused_text = combo.currentText()
        QApplication.sendEvent(combo, _vertical_wheel_event(combo, 1))
        assert combo.currentIndex() == unfocused_index, object_name
        assert combo.currentText() == unfocused_text, object_name

        # Once the combo owns focus the wheel selects another font as usual.
        if combo.count() > 1:
            dialog.activateWindow()
            combo.setFocus()
            app.processEvents()
            assert combo.hasFocus(), object_name

            combo.setCurrentIndex(min(2, combo.count() - 1))
            app.processEvents()
            focused_start_index = combo.currentIndex()
            QApplication.sendEvent(combo, _vertical_wheel_event(combo, 1))
            assert combo.currentIndex() != focused_start_index, object_name

    dialog.close()


def test_settings_display_form_spins_are_no_scroll(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    dialog = SettingsDialog(repository.get_preferences())
    dialog.show()
    app.processEvents()

    for object_name in (
        "mainFontSizeSpin",
        "labelFontSizeSpin",
        "contentFontSizeSpin",
        "datetimeFontSizeSpin",
        "datetimeTextOutlineThicknessSpin",
    ):
        spin = dialog.findChild(QSpinBox, object_name)
        assert isinstance(spin, NoScrollSpinBox), object_name
        assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus, object_name

    dialog.close()


def test_dashboard_preview_rect_follows_narrow_grid_width(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(560, 780)
    window.show()
    app.processEvents()

    container_width = window.feature_grid_container.width()
    # Precondition: the grid is narrower than the old hard-coded 720px floor.
    assert 0 < container_width < 720

    window.feature_dashboard_items = [{"key": "focus", "x": 0, "y": 0, "w": 12, "h": 4}]
    window._render_feature_dashboard()
    app.processEvents()

    # A full-width span now tracks the real container, not the old 720px floor.
    assert abs(window._dashboard_item_pixel_width(DASHBOARD_GRID_COLUMNS) - container_width) <= 2

    focus_item = next(
        item for item in window._current_feature_dashboard_layout() if item["key"] == "focus"
    )
    rect = window._dashboard_item_rect(focus_item)
    cell = window.feature_cells["focus"]
    assert abs(rect.width() - cell.width()) <= 2
    assert rect.right() <= container_width + 1

    # The drag preview overlay stays inside the narrowed grid too.
    window._show_dashboard_resize_guides("focus")
    app.processEvents()
    overlay = window.dashboard_guide_overlay
    assert overlay.preview_rect.right() <= container_width + 1
    window._hide_dashboard_drag_guides()
    window.close()


def test_quick_memo_narrow_tall_keeps_history_scrollable(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    now = datetime(2026, 6, 20, 10, 0)
    for index in range(20):
        repository.save_quick_note(
            QuickNote(
                f"좁은 창 메모 {index + 1} - 마지막까지 스크롤 확인",
                now - timedelta(minutes=index),
            )
        )
    window = MainWindow(repository)
    window.resize(1200, 820)
    window.show()
    app.processEvents()

    panel = window.memo_content_panel

    # A short panel may still collapse to an editor-only view.
    panel.resize(280, 280)
    window.update_memo_panel_responsive_layout()
    assert window.memo_history_card.isHidden()
    assert window.memo_splitter.sizes()[1] == 0

    # Narrow but tall must keep the saved-note history visible and scrollable
    # instead of hiding it and stretching only the editor.
    panel.resize(280, 600)
    window.update_memo_panel_responsive_layout()
    assert not window.memo_history_card.isHidden()
    assert not window.notes_list.isHidden()
    sizes = window.memo_splitter.sizes()
    assert len(sizes) == 2
    assert sizes[0] > 0
    assert sizes[1] > 0
    window.refresh_notes()
    app.processEvents()
    assert window.notes_list.count() == 20
    scroll_bar = window.notes_list.verticalScrollBar()
    scroll_bar.setValue(scroll_bar.maximum())
    app.processEvents()
    last_item_rect = window.notes_list.visualItemRect(window.notes_list.item(window.notes_list.count() - 1))
    assert window.notes_list.viewport().rect().intersects(last_item_rect)

    window.close()


def test_main_window_resize_hides_stale_dashboard_guides(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    target_cell = window.feature_cells["today_timeline"]
    window._show_dashboard_drag_guides("focus", target_cell.mapToGlobal(target_cell.rect().center()))
    app.processEvents()
    overlay = window.dashboard_guide_overlay
    assert overlay.isVisible()
    assert overlay.preview_rect.isValid()

    # Resizing the main window must clear any stale guide so no transient flash remains.
    window.resize(900, 760)
    app.processEvents()

    assert not overlay.isVisible()
    assert not overlay.preview_rect.isValid()
    assert overlay.preview_rect.isNull()
    assert overlay.impact_rects == []

    window.close()


def test_readd_panel_restores_original_slot(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = False
    window.preferences.show_focus_panel = True
    window.preferences.show_header_banner = False
    window.preferences.show_quick_memo_panel = True
    window.preferences.show_media_panel = False
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = True
    window.preferences.show_today_timeline_inline = True
    window.preferences.show_today_checklist_inline = True
    window.preferences.show_link_favorites_panel = True

    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 3, "h": 7},
        {"key": "quick_memo", "x": 3, "y": 0, "w": 3, "h": 5},
        {"key": "today_checklist", "x": 6, "y": 0, "w": 3, "h": 6},
        {"key": "pomodoro", "x": 9, "y": 0, "w": 3, "h": 4},
        {"key": "link_favorites", "x": 0, "y": 7, "w": 3, "h": 4},
        {"key": "today_timeline", "x": 3, "y": 7, "w": 3, "h": 8},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    # Record the saved slot, then hide the panel.
    saved_slot = next(
        dict(item) for item in window._current_feature_dashboard_layout() if item["key"] == "quick_memo"
    )
    window.hide_feature_from_main("quick_memo")
    app.processEvents()
    assert not window.preferences.show_quick_memo_panel
    assert "quick_memo" in window.hidden_panel_positions
    assert window.hidden_panel_positions["quick_memo"]["x"] == saved_slot["x"]
    assert window.hidden_panel_positions["quick_memo"]["y"] == saved_slot["y"]

    # Re-show the panel; the saved slot is empty so it should restore.
    window.preferences.show_quick_memo_panel = True
    window.apply_preferences()
    app.processEvents()

    restored = next(
        item for item in window._current_feature_dashboard_layout() if item["key"] == "quick_memo"
    )
    assert restored["x"] == saved_slot["x"]
    assert restored["y"] == saved_slot["y"]
    assert "quick_memo" not in window.hidden_panel_positions
    window.close()


def test_readd_panel_fills_bottom_left_when_no_slot(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = False
    window.preferences.show_focus_panel = True
    window.preferences.show_header_banner = False
    window.preferences.show_quick_memo_panel = True
    window.preferences.show_media_panel = False
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = False
    window.preferences.show_today_timeline_inline = False
    window.preferences.show_today_checklist_inline = False
    window.preferences.show_link_favorites_panel = False

    # Two panels share a row; quick_memo is at (6,0). After hiding it, we move
    # focus into quick_memo's saved slot so restore cannot land there.
    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 6, "h": 7},
        {"key": "quick_memo", "x": 6, "y": 0, "w": 6, "h": 5},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    saved_slot = next(
        dict(item) for item in window._current_feature_dashboard_layout() if item["key"] == "quick_memo"
    )
    window.hide_feature_from_main("quick_memo")
    app.processEvents()

    # Move focus into the saved slot so it is occupied, and make it fill the row.
    window.feature_dashboard_items = [
        {"key": "focus", "x": 0, "y": 0, "w": 12, "h": 7},
    ]
    window._render_feature_dashboard()
    app.processEvents()

    # The saved slot is now occupied; re-showing must not restore it.
    window.preferences.show_quick_memo_panel = True
    window.apply_preferences()
    app.processEvents()

    restored = next(
        item for item in window._current_feature_dashboard_layout() if item["key"] == "quick_memo"
    )
    assert restored["x"] == 0
    # The panel lands on a new row below the existing one, not at the saved y.
    assert restored["y"] > saved_slot["y"]
    visible_rows = [
        int(item.get("y", 0))
        for item in window._current_feature_dashboard_layout()
        if window._feature_should_be_visible(str(item.get("key", "")))
    ]
    assert restored["y"] == max(visible_rows)
    window.close()


def test_readd_panel_auto_scrolls_to_panel(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(800, 600)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = False
    window.preferences.show_focus_panel = True
    window.preferences.show_header_banner = False
    window.preferences.show_quick_memo_panel = True
    window.preferences.show_media_panel = False
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = True
    window.preferences.show_today_timeline_inline = True
    window.preferences.show_today_checklist_inline = True
    window.preferences.show_link_favorites_panel = True

    # Stack many tall panels so the dashboard scrolls well past the viewport.
    items: list[dict[str, object]] = [
        {"key": "focus", "x": 0, "y": 0, "w": 6, "h": 8},
        {"key": "today_timeline", "x": 6, "y": 0, "w": 6, "h": 8},
        {"key": "quick_memo", "x": 0, "y": 8, "w": 6, "h": 8},
        {"key": "today_checklist", "x": 6, "y": 8, "w": 6, "h": 8},
        {"key": "pomodoro", "x": 0, "y": 16, "w": 6, "h": 8},
        {"key": "link_favorites", "x": 6, "y": 16, "w": 6, "h": 8},
    ]
    window.feature_dashboard_items = items
    window._render_feature_dashboard()
    app.processEvents()

    window.hide_feature_from_main("link_favorites")
    app.processEvents()

    # Scroll to the top so the re-added panel is well outside the viewport.
    scroll = window.full_scroll_area
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().minimum())
    app.processEvents()

    window.preferences.show_link_favorites_panel = True
    window.apply_preferences()
    app.processEvents()

    cell = window.feature_cells.get("link_favorites")
    assert cell is not None
    content = scroll.widget()
    cell_top = cell.mapTo(content, QPoint(0, 0)).y()
    viewport_top = scroll.verticalScrollBar().value()
    viewport_bottom = viewport_top + scroll.viewport().height()
    assert viewport_top <= cell_top <= viewport_bottom
    window.close()


def test_readd_panel_auto_scrolls_to_bottom_row_panel(tmp_path) -> None:
    # Regression for BUG 4: a panel re-added on a NEW bottom row (dashboard full)
    # must scroll so the panel's bottom edge is visible, not just its top.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(800, 600)
    window.show()
    app.processEvents()

    window.preferences.show_datetime_panel = False
    window.preferences.show_focus_panel = True
    window.preferences.show_header_banner = False
    window.preferences.show_quick_memo_panel = True
    window.preferences.show_media_panel = False
    window.preferences.show_media_panel_2 = False
    window.preferences.show_media_panel_3 = False
    window.preferences.show_media_panel_4 = False
    window.preferences.show_pomodoro_controls = True
    window.preferences.show_today_timeline_inline = True
    window.preferences.show_today_checklist_inline = True
    window.preferences.show_link_favorites_panel = True

    # Fill the dashboard so the re-added panel lands on a new bottom row.
    items: list[dict[str, object]] = [
        {"key": "focus", "x": 0, "y": 0, "w": 6, "h": 8},
        {"key": "today_timeline", "x": 6, "y": 0, "w": 6, "h": 8},
        {"key": "quick_memo", "x": 0, "y": 8, "w": 6, "h": 8},
        {"key": "today_checklist", "x": 6, "y": 8, "w": 6, "h": 8},
        {"key": "pomodoro", "x": 0, "y": 16, "w": 6, "h": 8},
        {"key": "link_favorites", "x": 6, "y": 16, "w": 6, "h": 8},
    ]
    window.feature_dashboard_items = items
    window._render_feature_dashboard()
    app.processEvents()

    window.hide_feature_from_main("link_favorites")
    app.processEvents()

    # Scroll to the top so the re-added bottom-row panel is far outside the viewport.
    scroll = window.full_scroll_area
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().minimum())
    app.processEvents()

    window.preferences.show_link_favorites_panel = True
    window.apply_preferences()
    app.processEvents()

    cell = window.feature_cells.get("link_favorites")
    assert cell is not None
    content = scroll.widget()
    cell_bottom = cell.mapTo(content, QPoint(0, cell.height())).y()
    viewport_top = scroll.verticalScrollBar().value()
    viewport_bottom = viewport_top + scroll.viewport().height()
    # The entire cell (including its bottom edge) must be within the viewport.
    assert cell_bottom <= viewport_bottom
    window.close()


def _press_key(window, key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    window.keyPressEvent(event)


def test_f11_toggles_fullscreen_hides_title_bar(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    chrome_bar = window.app_chrome_bar
    assert chrome_bar.isVisible()

    _press_key(window, Qt.Key.Key_F11)
    app.processEvents()
    assert window.isFullScreen()
    assert not chrome_bar.isVisible()

    _press_key(window, Qt.Key.Key_F11)
    app.processEvents()
    assert not window.isFullScreen()
    assert chrome_bar.isVisible()

    window.close()


def test_f11_or_esc_restores_pre_fullscreen_size(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    window.resize(1100, 700)
    app.processEvents()

    # F11 -> F11 restores the pre-fullscreen size.
    _press_key(window, Qt.Key.Key_F11)
    app.processEvents()
    assert window.isFullScreen()
    _press_key(window, Qt.Key.Key_F11)
    app.processEvents()
    assert not window.isFullScreen()
    assert (window.width(), window.height()) == (1100, 700)

    # F11 -> Esc restores the pre-fullscreen size.
    _press_key(window, Qt.Key.Key_F11)
    app.processEvents()
    assert window.isFullScreen()
    _press_key(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert not window.isFullScreen()
    assert (window.width(), window.height()) == (1100, 700)

    window.close()


def test_esc_does_not_close_app_when_not_fullscreen(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert window.isVisible()
    _press_key(window, Qt.Key.Key_Escape)
    app.processEvents()
    # Esc must not close the app when not fullscreen.
    assert window.isVisible()
    assert not window.closing

    window.close()


def _seed_quick_switch_profiles(repository: ScheduleRepository) -> list[LayoutProfile]:
    profiles = [
        repository.save_layout_profile(LayoutProfile(name=f"작업공간 {i}", data='{"layout":{}}'))
        for i in range(1, 7)
    ]
    for profile in profiles:
        assert profile.id is not None
    return profiles


def _set_quick_config(repository: ScheduleRepository, entries: list[dict[str, object]]) -> None:
    repository.set_quick_button_config(entries)


def test_quick_switch_buttons_switch_workspace(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "dot", "color": "#68a8f5", "visible": True},
        {"workspace_id": int(profiles[1].id), "shape": "heart", "color": "#ef8f8f", "visible": True},
        {"workspace_id": int(profiles[2].id), "shape": "star", "color": "#f5c869", "visible": True},
    ])

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    buttons = window._quick_switch_buttons
    assert len(buttons) == 3
    # Click the 2nd button -> active workspace switches to profiles[1].
    buttons[1]._on_click(buttons[1].workspace_id)
    app.processEvents()
    assert window.preferences.active_workspace_id == int(profiles[1].id)
    window.close()


def test_quick_switch_button_real_click_switches_workspace(tmp_path) -> None:
    # Given quick-switch buttons rendered as real push buttons.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "dot", "color": "#68a8f5", "visible": True},
        {"workspace_id": int(profiles[1].id), "shape": "heart", "color": "#ef8f8f", "visible": True},
        {"workspace_id": int(profiles[2].id), "shape": "star", "color": "#f5c869", "visible": True},
    ])

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    buttons = window._quick_switch_buttons
    assert len(buttons) == 3
    assert isinstance(buttons[2], QPushButton)
    # When the 3rd button is clicked via the real QPushButton click signal.
    buttons[2].click()
    app.processEvents()
    # Then the active workspace switches to that button's workspace.
    assert window.preferences.active_workspace_id == int(profiles[2].id)
    window.close()


def test_quick_switch_button_single_mouse_release_switches(tmp_path) -> None:
    # A real press+release on the chip (no drag) must switch in ONE click, not
    # be swallowed as a no-op reorder.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "dot", "color": "#68a8f5", "visible": True},
        {"workspace_id": int(profiles[1].id), "shape": "star", "color": "#ef8f8f", "visible": True},
        {"workspace_id": int(profiles[2].id), "shape": "moon", "color": "#7a5af5", "visible": True},
    ])

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()
    window.switch_workspace(int(profiles[0].id))
    app.processEvents()

    buttons = window._quick_switch_buttons
    assert len(buttons) == 3
    # When a single real mouse press+release lands on the 2nd chip center.
    target = buttons[1]
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target.rect().center())
    app.processEvents()
    # Then it switches on that one click.
    assert window.preferences.active_workspace_id == int(profiles[1].id)
    window.close()


def test_quick_switch_buttons_max_five(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    # Configure 6 entries; the 6th must be rejected by normalize_quick_config.
    config: list[dict[str, object]] = []
    for index, profile in enumerate(profiles[:6]):
        config.append({
            "workspace_id": int(profile.id),
            "shape": "dot",
            "color": "#68a8f5",
            "visible": True,
        })
    _set_quick_config(repository, config)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    buttons = window._quick_switch_buttons
    assert len(buttons) == 5
    # The 6th workspace must not appear in the row.
    sixth_id = int(profiles[5].id)
    assert all(button.workspace_id != sixth_id for button in buttons)
    window.close()


def test_quick_switch_active_button_highlighted(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "dot", "color": "#68a8f5", "visible": True},
        {"workspace_id": int(profiles[1].id), "shape": "heart", "color": "#ef8f8f", "visible": True},
        {"workspace_id": int(profiles[2].id), "shape": "star", "color": "#f5c869", "visible": True},
    ])

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # Switch to the 2nd workspace.
    window.switch_workspace(int(profiles[1].id))
    app.processEvents()

    buttons = window._quick_switch_buttons
    assert len(buttons) == 3
    # The 2nd button (index 1) should be active, others not.
    assert buttons[1]._active is True
    assert buttons[0]._active is False
    assert buttons[2]._active is False
    window.close()


def test_quick_switch_drag_reorder(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "dot", "color": "#68a8f5", "visible": True},
        {"workspace_id": int(profiles[1].id), "shape": "heart", "color": "#ef8f8f", "visible": True},
        {"workspace_id": int(profiles[2].id), "shape": "star", "color": "#f5c869", "visible": True},
    ])

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    # Programmatically reorder slot 0 -> slot 2.
    window._reorder_quick_switch(0, 2)
    app.processEvents()

    reloaded = repository.get_quick_button_config()
    assert [entry["workspace_id"] for entry in reloaded] == [
        int(profiles[1].id),
        int(profiles[2].id),
        int(profiles[0].id),
    ]

    buttons = window._quick_switch_buttons
    assert [button.workspace_id for button in buttons] == [
        int(profiles[1].id),
        int(profiles[2].id),
        int(profiles[0].id),
    ]
    window.close()


def test_quick_switch_config_dialog_preserves_saved_color(tmp_path) -> None:
    # Given a saved quick-switch config with a real hex color per slot.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    saved_color = "#ef8f8f"
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "heart", "color": saved_color, "visible": True},
    ])

    # When the config dialog is opened and accepted without re-picking the color,
    # the color must round-trip as the saved hex, not the button label "색".
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    dialog = QuickSwitchConfigDialog(repository, repository.get_quick_button_config(), window)
    app.processEvents()
    accepted_config = dialog.config()

    assert len(accepted_config) == 1
    assert accepted_config[0]["color"] == saved_color
    assert accepted_config[0]["color"] != "색"
    dialog.close()
    window.close()


def test_quick_switch_config_dialog_default_color_when_slot_empty(tmp_path) -> None:
    # A slot with no saved color falls back to the default hex, never the label text.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    dialog = QuickSwitchConfigDialog(repository, [], window)
    app.processEvents()
    # Pick a workspace in slot 0 but never touch the color button.
    dialog._rows[0].workspace_combo.setCurrentIndex(1)
    accepted_config = dialog.config()

    assert len(accepted_config) == 1
    assert accepted_config[0]["color"] != "색"
    dialog.close()
    window.close()


def test_quick_switch_config_dialog_applies_picked_color(tmp_path) -> None:
    # Given a config dialog with a workspace chosen in slot 0 and a saved color.
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profiles = _seed_quick_switch_profiles(repository)
    _set_quick_config(repository, [
        {"workspace_id": int(profiles[0].id), "shape": "dot", "color": "#ef8f8f", "visible": True},
    ])
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    dialog = QuickSwitchConfigDialog(repository, repository.get_quick_button_config(), window)
    app.processEvents()

    # When a new color is applied to slot 0 (as the palette popover's set_color does).
    dialog._rows[0].color = "#00ff00"
    picked_config = dialog.config()

    # Then config() reflects the live row color, not the previously saved snapshot.
    assert len(picked_config) == 1
    assert picked_config[0]["color"] == "#00ff00"
    dialog.close()
    window.close()
