from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time


@dataclass(slots=True)
class Task:
    title: str
    duration_minutes: int
    due_at: datetime | None = None
    priority: int = 3
    category: str = ""
    completed: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass(slots=True)
class Event:
    title: str
    start_at: datetime
    end_at: datetime
    fixed: bool = True
    task_id: int | None = None
    category: str = ""
    id: int | None = None

    @property
    def duration_minutes(self) -> int:
        return int((self.end_at - self.start_at).total_seconds() // 60)


@dataclass(slots=True)
class AvailabilityRule:
    weekday: int
    start_time: time
    end_time: time
    id: int | None = None


@dataclass(slots=True)
class Preference:
    day_max_minutes: int = 480
    break_minutes: int = 10
    strategy: str = "deadline_priority"
    id: int = 1

