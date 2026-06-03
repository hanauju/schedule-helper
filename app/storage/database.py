from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from typing import Iterator

from app.models import AvailabilityRule, Event, Preference, Task


def default_database_path() -> Path:
    override = os.environ.get("SCHEDULE_HELPER_DB")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ScheduleHelper" / "schedule_helper.sqlite3"
    return Path.cwd() / "data" / "schedule_helper.sqlite3"


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(second=0, microsecond=0).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _time(value: time) -> str:
    return value.strftime("%H:%M")


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


class ScheduleRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()
        self.seed_defaults()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    due_at TEXT,
                    priority INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    fixed INTEGER NOT NULL DEFAULT 1,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    category TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS availability_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    weekday INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    day_max_minutes INTEGER NOT NULL,
                    break_minutes INTEGER NOT NULL,
                    strategy TEXT NOT NULL
                );
                """
            )

    def seed_defaults(self) -> None:
        with self.connect() as connection:
            has_rules = connection.execute("SELECT COUNT(*) FROM availability_rules").fetchone()[0]
            if has_rules == 0:
                connection.executemany(
                    """
                    INSERT INTO availability_rules (weekday, start_time, end_time)
                    VALUES (?, ?, ?)
                    """,
                    [(weekday, "09:00", "17:00") for weekday in range(5)],
                )

            has_preferences = connection.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
            if has_preferences == 0:
                connection.execute(
                    """
                    INSERT INTO preferences (id, day_max_minutes, break_minutes, strategy)
                    VALUES (1, 480, 10, 'deadline_priority')
                    """
                )

    def save_task(self, task: Task) -> Task:
        with self.connect() as connection:
            if task.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tasks
                      (title, duration_minutes, due_at, priority, category, completed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.title,
                        task.duration_minutes,
                        _dt(task.due_at),
                        task.priority,
                        task.category,
                        int(task.completed),
                        _dt(task.created_at),
                    ),
                )
                task.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = ?,
                        duration_minutes = ?,
                        due_at = ?,
                        priority = ?,
                        category = ?,
                        completed = ?,
                        created_at = ?
                    WHERE id = ?
                    """,
                    (
                        task.title,
                        task.duration_minutes,
                        _dt(task.due_at),
                        task.priority,
                        task.category,
                        int(task.completed),
                        _dt(task.created_at),
                        task.id,
                    ),
                )
        return task

    def list_tasks(self, include_completed: bool = True) -> list[Task]:
        query = "SELECT * FROM tasks"
        params: tuple[object, ...] = ()
        if not include_completed:
            query += " WHERE completed = 0"
        query += " ORDER BY completed ASC, due_at IS NULL ASC, due_at ASC, priority DESC, created_at ASC"

        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: int) -> Task | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def delete_task(self, task_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def mark_task_completed(self, task_id: int, completed: bool) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE tasks SET completed = ? WHERE id = ?", (int(completed), task_id))

    def save_event(self, event: Event) -> Event:
        with self.connect() as connection:
            if event.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO events (title, start_at, end_at, fixed, task_id, category)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.title,
                        _dt(event.start_at),
                        _dt(event.end_at),
                        int(event.fixed),
                        event.task_id,
                        event.category,
                    ),
                )
                event.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE events
                    SET title = ?,
                        start_at = ?,
                        end_at = ?,
                        fixed = ?,
                        task_id = ?,
                        category = ?
                    WHERE id = ?
                    """,
                    (
                        event.title,
                        _dt(event.start_at),
                        _dt(event.end_at),
                        int(event.fixed),
                        event.task_id,
                        event.category,
                        event.id,
                    ),
                )
        return event

    def get_event(self, event_id: int) -> Event | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._event_from_row(row) if row else None

    def list_events(self, start_at: datetime | None = None, end_at: datetime | None = None) -> list[Event]:
        query = "SELECT * FROM events"
        params: list[object] = []
        if start_at and end_at:
            query += " WHERE start_at < ? AND end_at > ?"
            params.extend([_dt(end_at), _dt(start_at)])
        query += " ORDER BY start_at ASC, end_at ASC"

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._event_from_row(row) for row in rows]

    def delete_event(self, event_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def delete_generated_events_between(self, start_at: datetime, end_at: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM events WHERE fixed = 0 AND start_at < ? AND end_at > ?",
                (_dt(end_at), _dt(start_at)),
            )

    def list_availability_rules(self) -> list[AvailabilityRule]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM availability_rules ORDER BY weekday ASC, start_time ASC"
            ).fetchall()
        return [self._availability_from_row(row) for row in rows]

    def save_availability_rule(self, rule: AvailabilityRule) -> AvailabilityRule:
        with self.connect() as connection:
            if rule.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO availability_rules (weekday, start_time, end_time)
                    VALUES (?, ?, ?)
                    """,
                    (rule.weekday, _time(rule.start_time), _time(rule.end_time)),
                )
                rule.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE availability_rules
                    SET weekday = ?, start_time = ?, end_time = ?
                    WHERE id = ?
                    """,
                    (rule.weekday, _time(rule.start_time), _time(rule.end_time), rule.id),
                )
        return rule

    def delete_availability_rule(self, rule_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM availability_rules WHERE id = ?", (rule_id,))

    def reset_default_availability(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM availability_rules")
            connection.executemany(
                """
                INSERT INTO availability_rules (weekday, start_time, end_time)
                VALUES (?, ?, ?)
                """,
                [(weekday, "09:00", "17:00") for weekday in range(5)],
            )

    def get_preferences(self) -> Preference:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM preferences WHERE id = 1").fetchone()
        if not row:
            return Preference()
        return Preference(
            id=int(row["id"]),
            day_max_minutes=int(row["day_max_minutes"]),
            break_minutes=int(row["break_minutes"]),
            strategy=str(row["strategy"]),
        )

    def save_preferences(self, preferences: Preference) -> Preference:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences (id, day_max_minutes, break_minutes, strategy)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day_max_minutes = excluded.day_max_minutes,
                    break_minutes = excluded.break_minutes,
                    strategy = excluded.strategy
                """,
                (preferences.day_max_minutes, preferences.break_minutes, preferences.strategy),
            )
        return preferences

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        return Task(
            id=int(row["id"]),
            title=str(row["title"]),
            duration_minutes=int(row["duration_minutes"]),
            due_at=_parse_dt(row["due_at"]),
            priority=int(row["priority"]),
            category=str(row["category"]),
            completed=bool(row["completed"]),
            created_at=_parse_dt(row["created_at"]) or datetime.now(),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> Event:
        start_at = _parse_dt(row["start_at"])
        end_at = _parse_dt(row["end_at"])
        if start_at is None or end_at is None:
            raise ValueError("Stored event is missing a valid time range")
        return Event(
            id=int(row["id"]),
            title=str(row["title"]),
            start_at=start_at,
            end_at=end_at,
            fixed=bool(row["fixed"]),
            task_id=row["task_id"],
            category=str(row["category"]),
        )

    @staticmethod
    def _availability_from_row(row: sqlite3.Row) -> AvailabilityRule:
        return AvailabilityRule(
            id=int(row["id"]),
            weekday=int(row["weekday"]),
            start_time=_parse_time(str(row["start_time"])),
            end_time=_parse_time(str(row["end_time"])),
        )
