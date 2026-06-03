from __future__ import annotations

from datetime import datetime, time

from app.models import AvailabilityRule, Event, Task
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


def test_repository_manages_availability_and_preferences(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.reset_default_availability()
    repository.save_availability_rule(AvailabilityRule(5, time(10), time(12)))

    rules = repository.list_availability_rules()
    assert any(rule.weekday == 5 and rule.start_time == time(10) for rule in rules)

    preferences = repository.get_preferences()
    preferences.break_minutes = 20
    repository.save_preferences(preferences)

    assert repository.get_preferences().break_minutes == 20

