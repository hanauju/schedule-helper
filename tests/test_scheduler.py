from __future__ import annotations

from datetime import datetime, time, timedelta

from app.models import AvailabilityRule, Event, Preference, Task
from app.services.scheduler import Scheduler


def test_scheduler_places_tasks_without_overlapping_fixed_events() -> None:
    scheduler = Scheduler()
    monday = datetime(2026, 6, 1)
    tasks = [
        Task("Important", 60, monday + timedelta(days=1, hours=17), 5, id=1),
        Task("Later", 60, monday + timedelta(days=2, hours=17), 3, id=2),
    ]
    fixed_events = [
        Event(
            "Meeting",
            monday.replace(hour=9),
            monday.replace(hour=10),
            fixed=True,
        )
    ]
    rules = [AvailabilityRule(0, time(9), time(12))]

    result = scheduler.schedule(
        tasks,
        fixed_events,
        rules,
        Preference(break_minutes=0),
        monday,
        monday + timedelta(days=7),
    )

    assert len(result.events) == 2
    assert result.failures == []
    assert result.events[0].start_at == monday.replace(hour=10)
    assert result.events[0].end_at == monday.replace(hour=11)
    assert result.events[1].start_at == monday.replace(hour=11)
    assert result.events[1].end_at == monday.replace(hour=12)


def test_scheduler_reports_tasks_that_cannot_fit() -> None:
    scheduler = Scheduler()
    monday = datetime(2026, 6, 1)
    tasks = [Task("Too long", 180, monday + timedelta(days=1), 3, id=1)]
    rules = [AvailabilityRule(0, time(9), time(10))]

    result = scheduler.schedule(
        tasks,
        [],
        rules,
        Preference(),
        monday,
        monday + timedelta(days=7),
    )

    assert result.events == []
    assert len(result.failures) == 1
    assert "빈 슬롯" in result.failures[0].reason


def test_scheduler_respects_due_dates() -> None:
    scheduler = Scheduler()
    monday = datetime(2026, 6, 1)
    tasks = [Task("Due early", 60, monday.replace(hour=9, minute=30), 5, id=1)]
    rules = [AvailabilityRule(0, time(9), time(12))]

    result = scheduler.schedule(
        tasks,
        [],
        rules,
        Preference(),
        monday,
        monday + timedelta(days=7),
    )

    assert result.events == []
    assert len(result.failures) == 1

