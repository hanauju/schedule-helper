from __future__ import annotations

from datetime import datetime, time

from app.models import AppUsageSession, AvailabilityRule, Event, FocusEvent, FocusSession, QuickNote, Task, TrackedProgram
from app.storage.database import ScheduleRepository


def test_repository_persists_tasks_and_events(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("Write", 45, datetime(2026, 6, 4, 18, 0), 4, "work"))
    event = repository.save_event(
        Event(
            "Focus",
            datetime(2026, 6, 4, 9, 0),
            datetime(2026, 6, 4, 9, 45),
            fixed=False,
            task_id=task.id,
            category="work",
        )
    )

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3")
    tasks = reloaded.list_tasks()
    events = reloaded.list_events()

    assert len(tasks) == 1
    assert tasks[0].title == "Write"
    assert tasks[0].priority == 4
    assert len(events) == 1
    assert events[0].id == event.id
    assert events[0].task_id == task.id


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
    repository.save_preferences(preferences)

    reloaded_preferences = repository.get_preferences()
    assert reloaded_preferences.break_minutes == 20
    assert reloaded_preferences.week_start_day == 6


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
