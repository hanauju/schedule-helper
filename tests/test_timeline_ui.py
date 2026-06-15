import json
import os
from datetime import datetime, time, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, QTime
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QWidget,
)

from app.models import FocusSession, ItemType, LinkFavorite, QuickNote, Task
from app.services.app_usage import ActiveWindowSnapshot
from app.storage.database import ScheduleRepository
from app.ui.main_window import (
    DASHBOARD_GRID_GAP,
    DASHBOARD_GRID_COLUMNS,
    DASHBOARD_GRID_ROW_HEIGHT,
    PANEL_CONTROL_HEIGHT,
    PANEL_HEADER_HEIGHT,
    PANEL_MOVE_BAR_HEIGHT,
    PANEL_TITLE_HEIGHT,
    ChecklistItemEditDialog,
    CompletedAtEditDialog,
    FavoritesSettingsDialog,
    FocusWidgetDialog,
    ItemTypeSettingsDialog,
    MainWindow,
    QuickNoteDetailDialog,
    SettingsDialog,
    TodayChecklistWidget,
    TodayTimelineWidget,
    _download_site_icon,
    _eyedropper_cursor,
    _format_time,
    _record_items_for_date,
    _today_timeline_blocks,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _margins_tuple(layout) -> tuple[int, int, int, int]:
    margins = layout.contentsMargins()
    return margins.left(), margins.top(), margins.right(), margins.bottom()


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


def test_main_feature_titles_are_not_repeated_inside_panels(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    for feature_key, title in (
        ("pomodoro", "뽀모도로"),
        ("today_checklist", "오늘 체크리스트"),
        ("today_timeline", "오늘 시간표"),
        ("quick_memo", "빠른 메모"),
        ("link_favorites", "즐겨찾기"),
    ):
        feature_box = window.feature_boxes[feature_key]
        assert feature_box.title_label.text() == title
        assert not feature_box.title_label.isHidden()
        assert feature_box.title_label.isVisibleTo(feature_box)
        assert feature_box.title_label.minimumWidth() == 0
        assert feature_box.title_label.minimumHeight() == PANEL_TITLE_HEIGHT
        assert feature_box.title_label.maximumHeight() == PANEL_TITLE_HEIGHT
        assert feature_box.header_band is not None
        assert feature_box.header_band.minimumHeight() == PANEL_HEADER_HEIGHT
        assert feature_box.header_band.maximumHeight() == PANEL_HEADER_HEIGHT
        assert feature_box.move_bar is not None
        assert feature_box.move_bar.minimumHeight() == PANEL_MOVE_BAR_HEIGHT
        assert feature_box.move_bar.maximumHeight() == PANEL_MOVE_BAR_HEIGHT
        assert feature_box.move_bar.toolTip() == title
        repeated_titles = [
            label.text()
            for label in feature_box.findChildren(QLabel)
            if label.objectName() == "sectionTitle" and label.text() == title
        ]
        assert repeated_titles == []
    assert window.feature_boxes["media_panel"].title_label is None
    favorites_inner_labels = [
        label.text()
        for label in window.link_favorites_panel.findChildren(QLabel)
        if label.text() == "바로가기"
    ]
    assert favorites_inner_labels == []

    window.close()


def test_side_by_side_feature_titles_share_same_baseline(tmp_path) -> None:
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

    title_tops = {
        key: window.feature_boxes[key].title_label.mapTo(window, QPoint(0, 0)).y()
        for key in ("today_timeline", "quick_memo", "link_favorites")
    }
    assert len(set(title_tops.values())) == 1

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
    assert "rgba(79, 140, 107, 0.18)" in window.styleSheet()
    assert "QWidget#featureMoveBar[dragging=\"true\"]" in window.styleSheet()
    assert "background: #4f8c6b" in window.styleSheet()

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


def test_feature_panel_controls_share_consistent_alignment_metrics(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1600, 900)
    window.show()
    app.processEvents()

    title_heights = [
        window.feature_boxes[key].title_label.maximumHeight()
        for key in ("focus", "today_checklist", "pomodoro", "quick_memo", "link_favorites")
    ]
    assert set(title_heights) == {PANEL_TITLE_HEIGHT}

    controls = [
        window.focus_title_edit,
        window.planned_minutes_spin,
        window.idle_cutoff_spin,
        window.pomodoro_minutes_spin,
        window.break_minutes_spin,
        window.start_pomodoro_button,
        window.pause_pomodoro_button,
        window.reset_pomodoro_button,
        window.today_checklist_widget.new_task_type_combo,
        window.today_checklist_widget.new_task_edit,
        window.today_checklist_widget.findChild(QPushButton, "checklistAddButton"),
        window.quick_note_folder_combo,
        window.note_filter_combo,
    ]
    assert all(control is not None for control in controls)
    assert {control.minimumHeight() for control in controls} == {PANEL_CONTROL_HEIGHT}
    assert {control.maximumHeight() for control in controls} == {PANEL_CONTROL_HEIGHT}
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
    assert window.header_focus_card.isHidden()
    assert window.header_focus_status_label.text() == "대기 중"
    assert window.header_focus_time_label.text() == "25:00"
    assert "집중할 일을 고른 뒤 시작하세요" in window.header_focus_card.toolTip()
    assert not window.findChildren(QWidget, "themeSegment")
    assert not hasattr(window, "light_theme_button")
    assert not hasattr(window, "dark_theme_button")
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

    assert default_check is not None
    assert font_combo is not None
    assert size_spin is not None
    assert default_check.isChecked()
    assert not font_combo.isEnabled()
    assert size_spin.value() == 13

    default_check.setChecked(False)
    size_spin.setValue(17)
    app.processEvents()

    preferences = dialog.preferences()
    assert preferences.main_font_family
    assert preferences.main_font_size == 17
    dialog.close()


def test_main_window_applies_configured_font_and_scales_text(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    preferences = repository.get_preferences()
    preferences.main_font_family = "Arial"
    preferences.main_font_size = 15
    repository.save_preferences(preferences)

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    style = window.styleSheet()
    assert 'font-family: "Arial", "Pretendard", "Segoe UI", "Malgun Gothic", sans-serif;' in style
    assert "QWidget {\n                color: #18201b;\n                font-family:" in style
    assert "font-size: 15px;" in style
    assert "QLabel#noteBodyLabel" in style
    window.close()


def test_focus_panel_target_controls_start_collapsed_and_splitter_is_slim(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    assert not window.target_combo.isVisible()
    assert not window.focus_targets_list.isVisible()
    assert not window.remove_target_button.isVisible()
    assert "width: 4px;" in window.styleSheet()
    assert "height: 4px;" in window.styleSheet()

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
    assert combo_position[:4] == (3, 0, 1, 4)
    assert actions_position[:4] == (4, 0, 1, 4)
    assert list_position[:4] == (6, 0, 1, 4)
    assert window.focus_detail_label.isHidden()
    assert window.focus_ratio_card.isVisible()
    assert window.focus_ratio_card.maximumHeight() <= 86
    assert window.focus_ratio_stack.currentIndex() == 1
    assert window.focus_status_label.maximumHeight() <= 34
    assert not window.focus_status_label.wordWrap()
    assert all(card.isHidden() for card in window.focus_metric_cards)
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
    assert window.focus_ratio_card.maximumHeight() <= 86
    assert window.focus_ratio_stack.currentIndex() == 1
    assert window.focus_status_label.height() <= 34
    assert all(card.isHidden() for card in window.focus_metric_cards)
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
    assert "font-size: 26px" in window.remaining_time_label.styleSheet()

    window.focus_content_panel.setFixedSize(720, 620)
    window.update_focus_panel_responsive_layout()
    assert window.focus_form_panel.isVisible()
    assert window.focus_ratio_card.isVisible()
    assert all(card.isVisible() for card in window.focus_metric_cards)
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
    assert window.pomodoro_detail_label.text() == "집중 25분 · 휴식 5분"

    window.pomodoro_mode = "focus"
    window.pomodoro_total_seconds = 1500
    window.pomodoro_remaining_seconds = 900
    window.pomodoro_paused = False
    window.update_pomodoro_display()

    assert window.pomodoro_status_label.text() == "집중 중"
    assert window.pomodoro_time_label.text() == "15:00"
    assert window.pomodoro_progress.value() == 400
    assert window.pomodoro_detail_label.text() == "집중 · 남은 15:00 / 전체 25:00"
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
    window.pomodoro_panel.setFixedSize(560, 220)
    window.update_pomodoro_panel_responsive_layout()
    window.memo_content_panel.setFixedSize(560, 420)
    window.update_memo_panel_responsive_layout()
    window.link_favorites_content_panel.setFixedSize(560, 260)
    window.update_link_favorites_responsive_layout()
    window.today_checklist_widget.resize(560, 420)
    window.inline_timeline_widget.resize(700, 520)
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

    window.pomodoro_panel.setFixedSize(240, 220)
    window.update_pomodoro_panel_responsive_layout()
    assert window.pomodoro_input_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window.pomodoro_button_row.direction() == QBoxLayout.Direction.TopToBottom
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
    assert "__SPIN_UP_ARROW__" not in style
    assert "__SPIN_DOWN_ARROW__" not in style
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

    assert widget.timeline_item_stat_label.text() == "항목 1개"
    assert widget.timeline_completed_stat_label.text() == "완료 1개"
    assert widget.timeline_focus_stat_label.text() == "집중 기록 1개"
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
    assert {"폴더 보기", "폴더 관리"}.issubset(memo_buttons)
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


def test_quick_memo_context_copy_copies_note_body(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.save_quick_note(QuickNote("복사할 빠른 메모", datetime(2026, 6, 14, 8, 5)))

    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    window.refresh_notes()
    app.processEvents()

    window.notes_list.setCurrentRow(0)
    window.copy_selected_quick_note()

    assert QApplication.clipboard().text() == "복사할 빠른 메모"
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
    assert window.memo_folder_settings_button.parentWidget() is window.memo_history_card
    assert window.memo_save_button.maximumWidth() == 76
    assert window.memo_attach_button.maximumWidth() == 76
    assert window.memo_folder_view_button.maximumWidth() <= 86
    assert window.memo_folder_settings_button.maximumWidth() <= 86
    assert window.memo_history_filter_row.indexOf(window.note_filter_combo) == window.memo_history_filter_row.count() - 1
    assert window.memo_history_filter_row.indexOf(window.memo_folder_view_button) < window.memo_history_filter_row.indexOf(window.note_filter_combo)
    assert window.memo_history_filter_row.indexOf(window.memo_folder_settings_button) < window.memo_history_filter_row.indexOf(window.note_filter_combo)
    assert window.memo_panel.findChild(QWidget, "memoFolderStrip") is None
    assert 40 <= window.quick_note_editor.minimumHeight() <= 64
    splitter_sizes = window.memo_splitter.sizes()
    assert splitter_sizes[0] < splitter_sizes[1]
    assert len(window.findChildren(QPushButton, "memoSaveButton")) == 1
    assert len(window.findChildren(QPushButton, "memoAttachButton")) == 1
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
    assert window.memo_shortcut_label.isHidden()
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
    meta_label = window.today_checklist_widget.findChild(QLabel, "checklistItemMeta")
    add_panel = window.today_checklist_widget.findChild(QWidget, "checklistAddPanel")
    checklist_input = window.today_checklist_widget.findChild(QWidget, "checklistInput")
    folder_combo = window.today_checklist_widget.findChild(QComboBox, "checklistFolderCombo")

    assert row is not None
    assert row.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert _margins_tuple(row.layout()) == (8, 12, 8, 12)
    assert "QLabel#noteBodyLabel" in window.styleSheet()
    assert "QLabel#checklistItemTitle {\n                color: #18201b;\n                font-size: 13px;\n                font-weight: 600;" in window.styleSheet()
    assert "QLabel#checklistItemMeta, QLabel#checklistItemMetaDone" in window.styleSheet()
    assert "font-size: 11px;" in window.styleSheet()
    assert any(checkbox.width() == 19 and checkbox.maximumWidth() == 19 for checkbox in checkboxes)
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


def test_feature_context_windows_use_new_window_label_and_always_on_top(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.show()
    app.processEvents()

    expected_titles = {
        "focus": "집중 새창",
        "pomodoro": "뽀모도로 새창",
        "quick_memo": "빠른 메모 새창",
        "today_checklist": "오늘 체크리스트 새창",
        "today_timeline": "오늘 시간표 새창",
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
    assert media_popup.minimumWidth() >= 164
    media_popup.close()

    window.open_feature_widget("media_panel")
    app.processEvents()
    dialog = window.feature_widget_windows["media_panel"]
    assert dialog.preview_label.pixmap() is not None
    assert not dialog.preview_label.pixmap().isNull()

    dialog.close()
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
    assert popup.minimumWidth() >= 164
    popup.close()
    window.close()


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
    assert positions["focus"] == (0, 3, 5, 7)
    assert positions["today_timeline"] == (0, 10, 5, 11)
    assert positions["today_checklist"] == (5, 3, 4, 6)
    assert positions["quick_memo"] == (5, 9, 4, 12)
    assert positions["pomodoro"] == (9, 3, 3, 4)
    assert positions["media_panel"] == (9, 7, 3, 8)
    assert positions["link_favorites"] == (9, 15, 3, 6)
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
    for x, y, width, height in after.values():
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


def test_dashboard_move_does_not_wrap_neighbors_when_side_space_is_full(tmp_path) -> None:
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
    before = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert not window._move_feature_to_dashboard_position("focus", drop_global)
    app.processEvents()

    after = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert after == before
    window.close()


def test_dashboard_media_drag_blocks_instead_of_wrapping_full_row(tmp_path) -> None:
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
    before = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }

    preview = window._dashboard_preview_item("media_panel", drop_global, drag_offset)
    assert preview is not None
    assert (int(preview["x"]), int(preview["y"])) == before["media_panel"]

    window.finish_feature_reposition("media_panel", drop_global, drag_offset)
    app.processEvents()

    positions = {
        str(item["key"]): (int(item["x"]), int(item["y"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert positions == before
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

    before = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    window.set_feature_panel_pinned("focus", True)
    assert window.feature_panel_pinned("focus")

    window._move_feature_in_dashboard("focus", "quick_memo")
    window.resize_feature_panel_width("focus", window._dashboard_item_pixel_width(12))
    window.resize_feature_panel_height("focus", window._dashboard_item_pixel_height(12))
    app.processEvents()

    after = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]), bool(item.get("pinned", False)))
        for item in window._current_feature_dashboard_layout()
    }
    assert after["focus"] == (*before["focus"], True)
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
