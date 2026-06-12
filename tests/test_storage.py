from __future__ import annotations

import sqlite3
from datetime import datetime, time

from app.models import (
    AppUsageSession,
    AvailabilityRule,
    Event,
    FocusEvent,
    FocusSession,
    ItemType,
    LinkFavorite,
    LayoutProfile,
    QuickNote,
    QuickNoteFolder,
    Task,
    TrackedProgram,
)
from app.storage.database import ScheduleRepository


def test_repository_persists_tasks_and_events(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    custom_task_type = repository.save_item_type(ItemType("업무", "task"))
    custom_event_type = repository.save_item_type(ItemType("회의", "event"))
    task = repository.save_task(
        Task("Write", 45, datetime(2026, 6, 4, 18, 0), 4, "work", item_type_id=custom_task_type.id)
    )
    event = repository.save_event(
        Event(
            "Focus",
            datetime(2026, 6, 4, 9, 0),
            datetime(2026, 6, 4, 9, 45),
            fixed=False,
            task_id=task.id,
            category="work",
            item_type_id=custom_event_type.id,
        )
    )

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3")
    tasks = reloaded.list_tasks()
    events = reloaded.list_events()

    assert len(tasks) == 1
    assert tasks[0].title == "Write"
    assert tasks[0].priority == 4
    assert tasks[0].item_type_id == custom_task_type.id
    assert len(events) == 1
    assert events[0].id == event.id
    assert events[0].task_id == task.id
    assert events[0].item_type_id == custom_event_type.id


def test_repository_manages_item_types(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    default_task_type = repository.default_item_type("task")
    default_event_type = repository.default_item_type("event")

    assert default_task_type.name == "할 일"
    assert default_task_type.is_default
    assert default_event_type.name == "일정"
    assert default_event_type.is_default

    custom_type = repository.save_item_type(ItemType("개인 업무", "task"))
    task = repository.save_task(Task("Read", 0, item_type_id=custom_type.id))

    custom_type.name = "개인"
    custom_type.is_default = True
    repository.save_item_type(custom_type)

    assert repository.default_item_type("task").id == custom_type.id
    assert repository.get_item_type(custom_type.id).name == "개인"
    assert repository.get_task(task.id).item_type_id == custom_type.id
    assert not repository.delete_item_type(custom_type.id)

    default_task_type = repository.get_item_type(default_task_type.id)
    assert default_task_type is not None
    assert repository.set_default_item_type(default_task_type.id).is_default
    assert repository.delete_item_type(custom_type.id)
    assert repository.get_task(task.id).item_type_id == default_task_type.id


def test_repository_migrates_legacy_items_without_item_type(tmp_path) -> None:
    db_path = tmp_path / "legacy_items.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                due_at TEXT,
                priority INTEGER NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                fixed INTEGER NOT NULL DEFAULT 1,
                task_id INTEGER,
                category TEXT NOT NULL DEFAULT '',
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT
            );
            INSERT INTO tasks (title, duration_minutes, priority, created_at)
            VALUES ('legacy task', 20, 3, '2026-06-08T09:00:00');
            INSERT INTO events (title, start_at, end_at)
            VALUES ('legacy event', '2026-06-08T10:00:00', '2026-06-08T10:30:00');
            """
        )
        connection.commit()
    finally:
        connection.close()

    repository = ScheduleRepository(db_path)

    assert repository.list_tasks()[0].item_type_id == repository.default_item_type("task").id
    assert repository.list_events(include_completed=True)[0].item_type_id == repository.default_item_type("event").id


def test_repository_tracks_completed_tasks(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("Review", 25))

    repository.mark_task_completed(task.id, True)
    completed_tasks = repository.list_completed_tasks()

    assert len(completed_tasks) == 1
    assert completed_tasks[0].title == "Review"
    assert completed_tasks[0].completed
    assert completed_tasks[0].completed_at is not None

    repository.mark_task_completed(task.id, False)

    assert repository.list_completed_tasks() == []
    assert repository.get_task(task.id).completed_at is None


def test_repository_tracks_completed_events(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    event = repository.save_event(
        Event(
            "Planning",
            datetime(2026, 6, 4, 10, 0),
            datetime(2026, 6, 4, 10, 30),
        )
    )

    repository.mark_event_completed(event.id, True)
    completed_events = repository.list_completed_events()

    assert repository.list_events() == []
    assert len(completed_events) == 1
    assert completed_events[0].title == "Planning"
    assert completed_events[0].completed
    assert completed_events[0].completed_at is not None

    repository.mark_event_completed(event.id, False)

    assert repository.list_completed_events() == []
    assert len(repository.list_events()) == 1
    assert repository.get_event(event.id).completed_at is None


def test_repository_manages_availability_and_preferences(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.reset_default_availability()
    repository.save_availability_rule(AvailabilityRule(5, time(10), time(12)))

    rules = repository.list_availability_rules()
    assert any(rule.weekday == 5 and rule.start_time == time(10) for rule in rules)

    preferences = repository.get_preferences()
    preferences.break_minutes = 20
    preferences.week_start_day = 6
    preferences.show_focus_panel = False
    preferences.show_pomodoro_controls = False
    preferences.show_today_timeline_inline = True
    preferences.show_today_timeline_waiting_panel = False
    preferences.show_today_timeline_waiting_pinned = False
    preferences.show_today_checklist_inline = True
    preferences.show_today_flow_panel = False
    preferences.show_quick_memo_panel = False
    preferences.show_link_favorites_panel = False
    preferences.show_compact_favorites_panel = True
    preferences.favorite_display_mode = "icon_only"
    preferences.time_format = "12h"
    repository.save_preferences(preferences)

    reloaded_preferences = repository.get_preferences()
    assert reloaded_preferences.break_minutes == 20
    assert reloaded_preferences.week_start_day == 6
    assert not reloaded_preferences.show_focus_panel
    assert not reloaded_preferences.show_pomodoro_controls
    assert reloaded_preferences.show_today_timeline_inline
    assert not reloaded_preferences.show_today_timeline_waiting_panel
    assert not reloaded_preferences.show_today_timeline_waiting_pinned
    assert reloaded_preferences.show_today_checklist_inline
    assert not reloaded_preferences.show_today_flow_panel
    assert not reloaded_preferences.show_quick_memo_panel
    assert not reloaded_preferences.show_link_favorites_panel
    assert reloaded_preferences.show_compact_favorites_panel
    assert reloaded_preferences.favorite_display_mode == "icon_only"
    assert reloaded_preferences.time_format == "12h"


def test_repository_saves_named_layout_profiles(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profile = repository.save_layout_profile(LayoutProfile(name="작업 배치", data='{"body":[700,300]}'))

    assert profile.id is not None
    assert repository.get_layout_profile("작업 배치").data == '{"body":[700,300]}'

    repository.save_layout_profile(LayoutProfile(name="작업 배치", data='{"body":[600,400]}'))
    profiles = repository.list_layout_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "작업 배치"
    assert profiles[0].data == '{"body":[600,400]}'


def test_repository_persists_app_usage_and_summaries(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    program = repository.save_tracked_program(TrackedProgram("Chrome", "chrome"))
    repository.save_app_usage_session(
        AppUsageSession(
            target_id=program.id,
            process_name="chrome.exe",
            window_title="Docs",
            started_at=datetime(2026, 6, 4, 23, 50),
            ended_at=datetime(2026, 6, 5, 0, 10),
            duration_seconds=20 * 60,
        )
    )

    summaries = repository.list_app_usage_summaries(
        datetime(2026, 6, 5, 0, 0),
        datetime(2026, 6, 6, 0, 0),
    )

    assert summaries[0].display_name == "Chrome"
    assert summaries[0].process_name == "chrome.exe"
    assert summaries[0].total_seconds == 10 * 60


def test_repository_deletes_focus_session_with_events_and_keeps_notes(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    session = repository.save_focus_session(
        FocusSession(
            title="Deep Work",
            planned_seconds=1500,
            focused_seconds=300,
            started_at=datetime(2026, 6, 8, 9, 0),
            status="completed",
        )
    )
    repository.save_focus_event(
        FocusEvent(
            focus_session_id=session.id,
            event_type="focused",
            started_at=datetime(2026, 6, 8, 9, 0),
            ended_at=datetime(2026, 6, 8, 9, 5),
            duration_seconds=300,
        )
    )
    repository.save_quick_note(
        QuickNote(
            body="done",
            created_at=datetime(2026, 6, 8, 9, 5),
            focus_session_id=session.id,
        )
    )

    repository.delete_focus_session(session.id)

    assert repository.get_focus_session(session.id) is None
    assert repository.list_focus_events(session.id) == []
    assert repository.list_quick_notes()[0].focus_session_id is None


def test_repository_deletes_quick_note(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(
        QuickNote(
            body="지울 메모",
            created_at=datetime(2026, 6, 8, 12, 0),
        )
    )

    repository.delete_quick_note(note.id)

    assert repository.list_quick_notes() == []


def test_repository_updates_quick_note_body(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    note = repository.save_quick_note(
        QuickNote(
            body="before",
            created_at=datetime(2026, 6, 8, 12, 0),
        )
    )

    note.body = "after"
    note.content_html = "<p><u>after</u></p>"
    repository.save_quick_note(note)

    reloaded = repository.get_quick_note(note.id)
    assert reloaded is not None
    assert reloaded.body == "after"
    assert reloaded.content_html == "<p><u>after</u></p>"
    assert reloaded.created_at == datetime(2026, 6, 8, 12, 0)


def test_repository_migrates_legacy_quick_notes_without_folder_column(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE quick_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                content_html TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                focus_session_id INTEGER,
                task_id INTEGER,
                process_name TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO quick_notes (body, content_html, created_at, process_name)
            VALUES ('legacy note', '', '2026-06-08T12:00:00', '');
            """
        )
        connection.commit()
    finally:
        connection.close()

    repository = ScheduleRepository(db_path)

    note = repository.list_quick_notes()[0]
    default_folder = repository.default_quick_note_folder()
    assert note.body == "legacy note"
    assert note.folder_id == default_folder.id
    assert note.window_title == ""
    with repository.connect() as migrated:
        indexes = {row["name"] for row in migrated.execute("PRAGMA index_list(quick_notes)")}
    assert "idx_quick_notes_folder" in indexes


def test_repository_manages_quick_note_folders_and_window_context(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    default_folder = repository.default_quick_note_folder()
    assert default_folder.name == "메모함"
    assert default_folder.is_default

    folder = repository.save_quick_note_folder(QuickNoteFolder(name="프로젝트 A"))
    note = repository.save_quick_note(
        QuickNote(
            body="window note",
            created_at=datetime(2026, 6, 8, 12, 0),
            folder_id=folder.id,
            process_name="notepad",
            window_title="Plan.txt",
        )
    )

    reloaded = repository.get_quick_note(note.id)
    assert reloaded is not None
    assert reloaded.folder_id == folder.id
    assert reloaded.process_name == "notepad.exe"
    assert reloaded.window_title == "Plan.txt"
    assert [item.id for item in repository.list_quick_notes(folder_id=folder.id)] == [note.id]

    assert repository.set_default_quick_note_folder(folder.id).is_default
    assert repository.default_quick_note_folder().id == folder.id
    default_note = repository.save_quick_note(
        QuickNote(
            body="default folder note",
            created_at=datetime(2026, 6, 8, 13, 0),
        )
    )
    assert default_note.folder_id == folder.id

    folder.name = "프로젝트 B"
    repository.save_quick_note_folder(folder)
    assert repository.get_quick_note_folder(folder.id).name == "프로젝트 B"

    repository.set_default_quick_note_folder(default_folder.id)
    assert repository.delete_quick_note_folder(folder.id)
    moved = repository.get_quick_note(note.id)
    assert moved is not None
    assert moved.folder_id == default_folder.id
    assert not repository.delete_quick_note_folder(default_folder.id)


def test_repository_moves_multiple_quick_notes_to_folder(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    default_folder = repository.default_quick_note_folder()
    target_folder = repository.save_quick_note_folder(QuickNoteFolder(name="옮길 폴더"))
    first = repository.save_quick_note(QuickNote(body="first", created_at=datetime(2026, 6, 8, 12, 0)))
    second = repository.save_quick_note(QuickNote(body="second", created_at=datetime(2026, 6, 8, 12, 10)))
    third = repository.save_quick_note(QuickNote(body="third", created_at=datetime(2026, 6, 8, 12, 20)))

    moved_count = repository.move_quick_notes_to_folder({first.id, second.id}, target_folder.id)

    assert moved_count == 2
    assert repository.get_quick_note(first.id).folder_id == target_folder.id
    assert repository.get_quick_note(second.id).folder_id == target_folder.id
    assert repository.get_quick_note(third.id).folder_id == default_folder.id
    assert repository.move_quick_notes_to_folder([third.id], -1) == 0


def test_repository_manages_quick_note_attachments(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    source = tmp_path / "source image.png"
    source.write_text("image-bytes", encoding="utf-8")
    note = repository.save_quick_note(
        QuickNote(
            body="with attachment",
            created_at=datetime(2026, 6, 8, 12, 0),
        )
    )

    attachment = repository.add_quick_note_attachment(note.id, source)

    assert attachment.id is not None
    assert attachment.file_name == "source image.png"
    assert repository.list_quick_note_attachments(note.id)[0].id == attachment.id
    assert repository.get_quick_note_attachment(attachment.id).stored_path == attachment.stored_path

    copied_path = tmp_path / "attachments" / str(note.id)
    assert copied_path.exists()

    repository.delete_quick_note(note.id)

    assert repository.list_quick_note_attachments(note.id) == []
    assert not any(copied_path.glob("*"))


def test_repository_manages_link_favorites(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    icon_source = tmp_path / "icon.png"
    icon_source.write_text("icon", encoding="utf-8")
    favorite = repository.save_link_favorite(LinkFavorite(title="Docs", target="example.com", icon_text="D"))

    assert favorite.id is not None
    assert repository.list_link_favorites()[0].title == "Docs"
    assert repository.list_link_favorites()[0].icon_text == "D"

    favorite.title = "Reference"
    favorite.target = "C:\\Tools\\editor.exe"
    favorite.icon_path = repository.copy_link_favorite_icon(favorite.id, icon_source)
    repository.save_link_favorite(favorite)

    reloaded = repository.get_link_favorite(favorite.id)
    assert reloaded is not None
    assert reloaded.title == "Reference"
    assert reloaded.target == "C:\\Tools\\editor.exe"
    assert reloaded.icon_path
    assert (tmp_path / "favorite_icons" / str(favorite.id)).exists()

    repository.delete_link_favorite(favorite.id)

    assert repository.list_link_favorites() == []
