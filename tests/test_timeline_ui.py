import json
import os
from datetime import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

from app.models import ItemType, Task
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

    window.body_splitter.setSizes([430, 850])
    window.left_splitter.setSizes([40, 210, 90, 160, 300])
    window.right_splitter.setSizes([540, 180])
    window.memo_splitter.setSizes([140, 300])
    app.processEvents()
    expected_splitters = window.current_layout_state()["splitters"]
    window.close()
    app.processEvents()

    saved_state = json.loads(repository.get_preferences().last_layout_state)
    assert saved_state["splitters"] == expected_splitters
    assert "window" not in saved_state

    restored = MainWindow(repository)
    restored.resize(1280, 820)
    restored.show()
    app.processEvents()
    app.processEvents()

    restored_splitters = restored.current_layout_state()["splitters"]
    assert restored_splitters == expected_splitters
    restored.close()


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
