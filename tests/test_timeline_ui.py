import json
import os
from datetime import datetime, time, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QBoxLayout, QCheckBox, QFrame, QLabel, QPushButton, QSizePolicy, QWidget

from app.models import FocusSession, ItemType, LinkFavorite, QuickNote, Task
from app.storage.database import ScheduleRepository
from app.ui.main_window import (
    ItemTypeSettingsDialog,
    MainWindow,
    SettingsDialog,
    TodayTimelineWidget,
    _download_site_icon,
    _format_time,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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
        repeated_titles = [
            label.text()
            for label in feature_box.findChildren(QLabel)
            if label.objectName() == "sectionTitle" and label.text() == title
        ]
        assert repeated_titles == []
    assert window.feature_boxes["media_panel"].title_label is None

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
    assert window.header_focus_card.isVisible()
    assert window.header_focus_status_label.text() == "대기 중"
    assert window.header_focus_time_label.text() == "25:00"
    assert "집중할 일을 고른 뒤 시작하세요" in window.header_focus_card.toolTip()
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
    assert window.remove_target_button.isVisible()

    window.close()


def test_focus_panel_reflows_controls_when_narrow(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1280, 820)
    window.show()
    app.processEvents()

    window.focus_content_panel.resize(340, window.focus_content_panel.height())
    window.update_focus_panel_responsive_layout()

    assert window.focus_meter_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window.focus_metrics_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert window.focus_button_row.direction() == QBoxLayout.Direction.TopToBottom
    assert "font-size" in window.remaining_time_label.styleSheet()

    window.focus_content_panel.resize(720, window.focus_content_panel.height())
    window.update_focus_panel_responsive_layout()

    assert window.focus_meter_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window.focus_button_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window.remaining_time_label.styleSheet() == ""
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


def test_timeline_time_blocks_shrink_inside_narrow_width(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    widget = TodayTimelineWidget(repository)
    widget.resize(360, 520)
    widget.show()
    app.processEvents()

    widget.block_table.resize(230, 390)
    widget._resize_time_columns()

    assert widget.block_table.columnWidth(0) <= 50
    assert widget.block_table.columnWidth(1) < 42
    total_width = sum(widget.block_table.columnWidth(column) for column in range(7))
    assert total_width <= widget.block_table.viewport().width() + 8
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


def test_quick_memo_editor_ports_compact_header_actions(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(900, 720)
    window.show()
    app.processEvents()

    assert window.memo_editor_header.objectName() == "memoEditorHeader"
    assert window.memo_save_button.parentWidget() is window.memo_editor_header
    assert window.memo_attach_button.parentWidget() is window.memo_editor_header
    assert window.memo_save_button.maximumWidth() == 76
    assert window.memo_attach_button.maximumWidth() == 76
    assert 72 <= window.quick_note_editor.minimumHeight() <= 96
    assert len(window.findChildren(QPushButton, "memoSaveButton")) == 1
    assert len(window.findChildren(QPushButton, "memoAttachButton")) == 1
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
    assert window.today_checklist_widget.checklist_progress.value() == 333
    window.close()


def test_today_checklist_rows_use_compact_task_row_port(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    today = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
    repository.save_task(Task("보고서 정리", 15, due_at=today, created_at=today))

    window = MainWindow(repository)
    window.resize(760, 620)
    window.show()
    window.today_checklist_widget.refresh_checklist()
    app.processEvents()

    row = window.today_checklist_widget.findChild(QWidget, "checklistRow")
    checkboxes = window.today_checklist_widget.findChildren(QCheckBox, "checklistItemCheck")
    time_badge = window.today_checklist_widget.findChild(QLabel, "checklistTimeBadge")
    detail_badge = window.today_checklist_widget.findChild(QLabel, "checklistDetailBadge")

    assert row is not None
    assert row.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert any(checkbox.width() == 22 and checkbox.maximumWidth() == 22 for checkbox in checkboxes)
    assert time_badge is not None
    assert time_badge.maximumWidth() == 170
    assert detail_badge is not None
    assert detail_badge.maximumWidth() == 170
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
    assert dialog.type_list.findItems("업무 · 1개", Qt.MatchFlag.MatchStartsWith)
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

    window.open_feature_widget("media_panel")
    app.processEvents()
    dialog = window.feature_widget_windows["media_panel"]
    assert dialog.preview_label.pixmap() is not None
    assert not dialog.preview_label.pixmap().isNull()

    dialog.close()
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


def test_feature_move_adopts_target_slot_size(tmp_path) -> None:
    app = _app()
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window = MainWindow(repository)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    window.feature_dashboard_items = [
        {"key": "focus", "w": 2, "h": 4},
        {"key": "quick_memo", "w": 4, "h": 4},
        {"key": "link_favorites", "w": 3, "h": 4},
    ]
    window._render_feature_dashboard()
    app.processEvents()
    before = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }

    window.swap_feature_panels("focus", "quick_memo", "after")
    app.processEvents()

    after = {
        str(item["key"]): (int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"]))
        for item in window._current_feature_dashboard_layout()
    }
    assert after["focus"] == before["quick_memo"]
    assert after["quick_memo"] == before["focus"]
    assert after["link_favorites"][2] == 3
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
        int(round((window._dashboard_column_width() + 16) * 4)),
        int(round((58 + 16) * 4)),
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

        window.resize_feature_panel_width(feature_key, window._dashboard_item_pixel_width(6))
        app.processEvents()
        widths = {
            str(item["key"]): int(item["w"])
            for item in window._current_feature_dashboard_layout()
        }
        assert widths[feature_key] == 6
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
    preview_item = window._dashboard_preview_item("focus", target_cell.mapToGlobal(target_cell.rect().center()))
    assert preview_item is not None
    assert int(preview_item["w"]) == int(next(item["w"] for item in window._current_feature_dashboard_layout() if item["key"] == "today_timeline"))
    assert int(preview_item["h"]) == int(next(item["h"] for item in window._current_feature_dashboard_layout() if item["key"] == "today_timeline"))

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
