from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from typing import Iterator

from app.models import (
    AppUsageSession,
    AppUsageSummary,
    AvailabilityRule,
    Event,
    FocusEvent,
    FocusSession,
    Preference,
    QuickNote,
    Task,
    TrackedProgram,
)


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


def _dt_exact(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _time(value: time) -> str:
    return value.strftime("%H:%M")


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def normalize_process_name(value: str) -> str:
    process_name = value.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
    if process_name and "." not in process_name:
        process_name = f"{process_name}.exe"
    return process_name


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
                    completed_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    fixed INTEGER NOT NULL DEFAULT 1,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    category TEXT NOT NULL DEFAULT '',
                    completed INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT
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
                    strategy TEXT NOT NULL,
                    week_start_day INTEGER NOT NULL DEFAULT 0,
                    show_pomodoro_controls INTEGER NOT NULL DEFAULT 1,
                    show_today_timeline_inline INTEGER NOT NULL DEFAULT 0,
                    show_today_checklist_inline INTEGER NOT NULL DEFAULT 0,
                    show_today_flow_panel INTEGER NOT NULL DEFAULT 1,
                    show_quick_memo_panel INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS app_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    process_name TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_usage_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER REFERENCES app_targets(id) ON DELETE SET NULL,
                    process_name TEXT NOT NULL,
                    window_title TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_app_usage_sessions_range
                    ON app_usage_sessions (started_at, ended_at);

                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    target_process_name TEXT NOT NULL DEFAULT '',
                    target_window_title TEXT NOT NULL DEFAULT '',
                    planned_seconds INTEGER NOT NULL,
                    focused_seconds INTEGER NOT NULL DEFAULT 0,
                    paused_seconds INTEGER NOT NULL DEFAULT 0,
                    away_seconds INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    ended_at TEXT,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS focus_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    focus_session_id INTEGER NOT NULL REFERENCES focus_sessions(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    metadata TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS quick_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    focus_session_id INTEGER REFERENCES focus_sessions(id) ON DELETE SET NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    process_name TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_focus_sessions_started
                    ON focus_sessions (started_at, ended_at);

                CREATE INDEX IF NOT EXISTS idx_quick_notes_created
                    ON quick_notes (created_at);
                """
            )
            task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "completed_at" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
            event_columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
            if "completed" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN completed INTEGER NOT NULL DEFAULT 0")
            if "completed_at" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN completed_at TEXT")
            preference_columns = {row["name"] for row in connection.execute("PRAGMA table_info(preferences)")}
            if "week_start_day" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN week_start_day INTEGER NOT NULL DEFAULT 0")
            if "show_pomodoro_controls" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_pomodoro_controls INTEGER NOT NULL DEFAULT 1"
                )
            if "show_today_timeline_inline" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_timeline_inline INTEGER NOT NULL DEFAULT 0"
                )
            if "show_today_checklist_inline" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_checklist_inline INTEGER NOT NULL DEFAULT 0"
                )
            if "show_today_flow_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_flow_panel INTEGER NOT NULL DEFAULT 1"
                )
            if "show_quick_memo_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_quick_memo_panel INTEGER NOT NULL DEFAULT 1"
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
                    INSERT INTO preferences
                      (id, day_max_minutes, break_minutes, strategy, week_start_day,
                       show_pomodoro_controls, show_today_timeline_inline, show_today_checklist_inline,
                       show_today_flow_panel, show_quick_memo_panel)
                    VALUES (1, 480, 10, 'deadline_priority', 0, 1, 0, 0, 1, 1)
                    """
                )

    def save_task(self, task: Task) -> Task:
        if task.completed and task.completed_at is None:
            task.completed_at = datetime.now()
        elif not task.completed:
            task.completed_at = None

        with self.connect() as connection:
            if task.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tasks
                      (title, duration_minutes, due_at, priority, category, completed, completed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.title,
                        task.duration_minutes,
                        _dt(task.due_at),
                        task.priority,
                        task.category,
                        int(task.completed),
                        _dt_exact(task.completed_at),
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
                        completed_at = ?,
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
                        _dt_exact(task.completed_at),
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
        query += (
            " ORDER BY completed ASC, completed_at IS NULL ASC, completed_at DESC, "
            "due_at IS NULL ASC, due_at ASC, priority DESC, created_at ASC"
        )

        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def list_completed_tasks(self, limit: int | None = None) -> list[Task]:
        query = """
            SELECT * FROM tasks
            WHERE completed = 1
            ORDER BY completed_at IS NULL ASC, completed_at DESC, created_at DESC, id DESC
        """
        params: list[object] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: int) -> Task | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def delete_task(self, task_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def mark_task_completed(self, task_id: int, completed: bool) -> None:
        completed_at = _dt_exact(datetime.now()) if completed else None
        with self.connect() as connection:
            connection.execute(
                "UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?",
                (int(completed), completed_at, task_id),
            )

    def save_event(self, event: Event) -> Event:
        if event.completed and event.completed_at is None:
            event.completed_at = datetime.now()
        elif not event.completed:
            event.completed_at = None

        with self.connect() as connection:
            if event.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO events
                      (title, start_at, end_at, fixed, task_id, category, completed, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.title,
                        _dt(event.start_at),
                        _dt(event.end_at),
                        int(event.fixed),
                        event.task_id,
                        event.category,
                        int(event.completed),
                        _dt_exact(event.completed_at),
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
                        category = ?,
                        completed = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (
                        event.title,
                        _dt(event.start_at),
                        _dt(event.end_at),
                        int(event.fixed),
                        event.task_id,
                        event.category,
                        int(event.completed),
                        _dt_exact(event.completed_at),
                        event.id,
                    ),
                )
        return event

    def get_event(self, event_id: int) -> Event | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._event_from_row(row) if row else None

    def list_events(
        self,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        include_completed: bool = False,
    ) -> list[Event]:
        query = "SELECT * FROM events"
        params: list[object] = []
        conditions: list[str] = []
        if not include_completed:
            conditions.append("completed = 0")
        if start_at and end_at:
            conditions.append("start_at < ? AND end_at > ?")
            params.extend([_dt(end_at), _dt(start_at)])
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY start_at ASC, end_at ASC"

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_completed_events(self, limit: int | None = None) -> list[Event]:
        query = """
            SELECT * FROM events
            WHERE completed = 1
            ORDER BY completed_at IS NULL ASC, completed_at DESC, start_at DESC, id DESC
        """
        params: list[object] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._event_from_row(row) for row in rows]

    def delete_event(self, event_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def mark_event_completed(self, event_id: int, completed: bool) -> None:
        completed_at = _dt_exact(datetime.now()) if completed else None
        with self.connect() as connection:
            connection.execute(
                "UPDATE events SET completed = ?, completed_at = ? WHERE id = ?",
                (int(completed), completed_at, event_id),
            )

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
            week_start_day=int(row["week_start_day"]),
            show_pomodoro_controls=bool(row["show_pomodoro_controls"]),
            show_today_timeline_inline=bool(row["show_today_timeline_inline"]),
            show_today_checklist_inline=bool(row["show_today_checklist_inline"]),
            show_today_flow_panel=bool(row["show_today_flow_panel"]),
            show_quick_memo_panel=bool(row["show_quick_memo_panel"]),
        )

    def save_preferences(self, preferences: Preference) -> Preference:
        preferences.week_start_day = 6 if preferences.week_start_day == 6 else 0
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences
                  (id, day_max_minutes, break_minutes, strategy, week_start_day,
                   show_pomodoro_controls, show_today_timeline_inline, show_today_checklist_inline,
                   show_today_flow_panel, show_quick_memo_panel)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day_max_minutes = excluded.day_max_minutes,
                    break_minutes = excluded.break_minutes,
                    strategy = excluded.strategy,
                    week_start_day = excluded.week_start_day,
                    show_pomodoro_controls = excluded.show_pomodoro_controls,
                    show_today_timeline_inline = excluded.show_today_timeline_inline,
                    show_today_checklist_inline = excluded.show_today_checklist_inline,
                    show_today_flow_panel = excluded.show_today_flow_panel,
                    show_quick_memo_panel = excluded.show_quick_memo_panel
                """,
                (
                    preferences.day_max_minutes,
                    preferences.break_minutes,
                    preferences.strategy,
                    preferences.week_start_day,
                    int(preferences.show_pomodoro_controls),
                    int(preferences.show_today_timeline_inline),
                    int(preferences.show_today_checklist_inline),
                    int(preferences.show_today_flow_panel),
                    int(preferences.show_quick_memo_panel),
                ),
            )
        return preferences

    def save_tracked_program(self, program: TrackedProgram) -> TrackedProgram:
        program.process_name = normalize_process_name(program.process_name)
        if not program.display_name.strip():
            program.display_name = program.process_name

        with self.connect() as connection:
            if program.id is None:
                connection.execute(
                    """
                    INSERT INTO app_targets (display_name, process_name, enabled, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(process_name) DO UPDATE SET
                        display_name = excluded.display_name,
                        enabled = excluded.enabled
                    """,
                    (
                        program.display_name.strip(),
                        program.process_name,
                        int(program.enabled),
                        _dt_exact(program.created_at),
                    ),
                )
                program.id = self._program_id_for(connection, program.process_name)
            else:
                connection.execute(
                    """
                    UPDATE app_targets
                    SET display_name = ?,
                        process_name = ?,
                        enabled = ?
                    WHERE id = ?
                    """,
                    (program.display_name.strip(), program.process_name, int(program.enabled), program.id),
                )
        return program

    def list_tracked_programs(self, include_disabled: bool = True) -> list[TrackedProgram]:
        query = "SELECT * FROM app_targets"
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY enabled DESC, display_name COLLATE NOCASE ASC"
        with self.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._tracked_program_from_row(row) for row in rows]

    def get_tracked_program(self, program_id: int) -> TrackedProgram | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM app_targets WHERE id = ?", (program_id,)).fetchone()
        return self._tracked_program_from_row(row) if row else None

    def find_tracked_program_by_process(self, process_name: str) -> TrackedProgram | None:
        normalized = normalize_process_name(process_name)
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM app_targets WHERE process_name = ?", (normalized,)).fetchone()
        return self._tracked_program_from_row(row) if row else None

    def delete_tracked_program(self, program_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM app_targets WHERE id = ?", (program_id,))

    def save_app_usage_session(self, session: AppUsageSession) -> AppUsageSession:
        if session.ended_at <= session.started_at or session.duration_seconds <= 0:
            return session

        with self.connect() as connection:
            if session.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO app_usage_sessions
                      (target_id, process_name, window_title, started_at, ended_at, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.target_id,
                        normalize_process_name(session.process_name),
                        session.window_title,
                        _dt_exact(session.started_at),
                        _dt_exact(session.ended_at),
                        session.duration_seconds,
                    ),
                )
                session.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE app_usage_sessions
                    SET target_id = ?,
                        process_name = ?,
                        window_title = ?,
                        started_at = ?,
                        ended_at = ?,
                        duration_seconds = ?
                    WHERE id = ?
                    """,
                    (
                        session.target_id,
                        normalize_process_name(session.process_name),
                        session.window_title,
                        _dt_exact(session.started_at),
                        _dt_exact(session.ended_at),
                        session.duration_seconds,
                        session.id,
                    ),
                )
        return session

    def list_app_usage_sessions(
        self,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        target_id: int | None = None,
    ) -> list[AppUsageSession]:
        query = "SELECT * FROM app_usage_sessions"
        clauses: list[str] = []
        params: list[object] = []
        if start_at and end_at:
            clauses.append("started_at < ? AND ended_at > ?")
            params.extend([_dt_exact(end_at), _dt_exact(start_at)])
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC"

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._usage_session_from_row(row) for row in rows]

    def list_app_usage_summaries(self, start_at: datetime, end_at: datetime) -> list[AppUsageSummary]:
        programs = self.list_tracked_programs(include_disabled=True)
        sessions = self.list_app_usage_sessions(start_at, end_at)
        by_target: dict[int | None, list[AppUsageSession]] = {}
        for session in sessions:
            by_target.setdefault(session.target_id, []).append(session)

        summaries: list[AppUsageSummary] = []
        for program in programs:
            program_sessions = by_target.get(program.id, [])
            total_seconds = sum(_clipped_seconds(session, start_at, end_at) for session in program_sessions)
            last_used_at = max((session.ended_at for session in program_sessions), default=None)
            summaries.append(
                AppUsageSummary(
                    target_id=program.id,
                    display_name=program.display_name,
                    process_name=program.process_name,
                    total_seconds=total_seconds,
                    last_used_at=last_used_at,
                )
            )

        return sorted(summaries, key=lambda item: (-item.total_seconds, item.display_name.casefold()))

    def save_focus_session(self, session: FocusSession) -> FocusSession:
        with self.connect() as connection:
            if session.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO focus_sessions
                      (title, task_id, target_process_name, target_window_title, planned_seconds,
                       focused_seconds, paused_seconds, away_seconds, started_at, ended_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.title,
                        session.task_id,
                        normalize_process_name(session.target_process_name) if session.target_process_name else "",
                        session.target_window_title,
                        session.planned_seconds,
                        session.focused_seconds,
                        session.paused_seconds,
                        session.away_seconds,
                        _dt_exact(session.started_at),
                        _dt_exact(session.ended_at),
                        session.status,
                    ),
                )
                session.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE focus_sessions
                    SET title = ?,
                        task_id = ?,
                        target_process_name = ?,
                        target_window_title = ?,
                        planned_seconds = ?,
                        focused_seconds = ?,
                        paused_seconds = ?,
                        away_seconds = ?,
                        started_at = ?,
                        ended_at = ?,
                        status = ?
                    WHERE id = ?
                    """,
                    (
                        session.title,
                        session.task_id,
                        normalize_process_name(session.target_process_name) if session.target_process_name else "",
                        session.target_window_title,
                        session.planned_seconds,
                        session.focused_seconds,
                        session.paused_seconds,
                        session.away_seconds,
                        _dt_exact(session.started_at),
                        _dt_exact(session.ended_at),
                        session.status,
                        session.id,
                    ),
                )
        return session

    def get_focus_session(self, session_id: int) -> FocusSession | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._focus_session_from_row(row) if row else None

    def delete_focus_session(self, session_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM focus_sessions WHERE id = ?", (session_id,))

    def list_focus_sessions(
        self,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int | None = None,
    ) -> list[FocusSession]:
        query = "SELECT * FROM focus_sessions"
        params: list[object] = []
        if start_at and end_at:
            query += " WHERE COALESCE(started_at, ended_at) < ? AND COALESCE(ended_at, started_at) > ?"
            params.extend([_dt_exact(end_at), _dt_exact(start_at)])
        query += " ORDER BY COALESCE(started_at, ended_at) DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._focus_session_from_row(row) for row in rows]

    def save_focus_event(self, event: FocusEvent) -> FocusEvent:
        if event.ended_at <= event.started_at or event.duration_seconds <= 0:
            return event

        with self.connect() as connection:
            if event.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO focus_events
                      (focus_session_id, event_type, started_at, ended_at, duration_seconds, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.focus_session_id,
                        event.event_type,
                        _dt_exact(event.started_at),
                        _dt_exact(event.ended_at),
                        event.duration_seconds,
                        event.metadata,
                    ),
                )
                event.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE focus_events
                    SET focus_session_id = ?,
                        event_type = ?,
                        started_at = ?,
                        ended_at = ?,
                        duration_seconds = ?,
                        metadata = ?
                    WHERE id = ?
                    """,
                    (
                        event.focus_session_id,
                        event.event_type,
                        _dt_exact(event.started_at),
                        _dt_exact(event.ended_at),
                        event.duration_seconds,
                        event.metadata,
                        event.id,
                    ),
                )
        return event

    def list_focus_events(self, focus_session_id: int) -> list[FocusEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM focus_events WHERE focus_session_id = ? ORDER BY started_at ASC",
                (focus_session_id,),
            ).fetchall()
        return [self._focus_event_from_row(row) for row in rows]

    def save_quick_note(self, note: QuickNote) -> QuickNote:
        with self.connect() as connection:
            if note.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO quick_notes (body, created_at, focus_session_id, task_id, process_name)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        note.body.strip(),
                        _dt_exact(note.created_at),
                        note.focus_session_id,
                        note.task_id,
                        normalize_process_name(note.process_name) if note.process_name else "",
                    ),
                )
                note.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE quick_notes
                    SET body = ?,
                        created_at = ?,
                        focus_session_id = ?,
                        task_id = ?,
                        process_name = ?
                    WHERE id = ?
                    """,
                    (
                        note.body.strip(),
                        _dt_exact(note.created_at),
                        note.focus_session_id,
                        note.task_id,
                        normalize_process_name(note.process_name) if note.process_name else "",
                        note.id,
                    ),
                )
        return note

    def list_quick_notes(
        self,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int | None = None,
    ) -> list[QuickNote]:
        query = "SELECT * FROM quick_notes"
        params: list[object] = []
        if start_at and end_at:
            query += " WHERE created_at >= ? AND created_at < ?"
            params.extend([_dt_exact(start_at), _dt_exact(end_at)])
        query += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._quick_note_from_row(row) for row in rows]

    def get_quick_note(self, note_id: int) -> QuickNote | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM quick_notes WHERE id = ?", (note_id,)).fetchone()
        return self._quick_note_from_row(row) if row else None

    def delete_quick_note(self, note_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM quick_notes WHERE id = ?", (note_id,))

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
            completed_at=_parse_dt(row["completed_at"]),
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
            completed=bool(row["completed"]),
            completed_at=_parse_dt(row["completed_at"]),
        )

    @staticmethod
    def _availability_from_row(row: sqlite3.Row) -> AvailabilityRule:
        return AvailabilityRule(
            id=int(row["id"]),
            weekday=int(row["weekday"]),
            start_time=_parse_time(str(row["start_time"])),
            end_time=_parse_time(str(row["end_time"])),
        )

    @staticmethod
    def _tracked_program_from_row(row: sqlite3.Row) -> TrackedProgram:
        return TrackedProgram(
            id=int(row["id"]),
            display_name=str(row["display_name"]),
            process_name=str(row["process_name"]),
            enabled=bool(row["enabled"]),
            created_at=_parse_dt(row["created_at"]) or datetime.now(),
        )

    @staticmethod
    def _usage_session_from_row(row: sqlite3.Row) -> AppUsageSession:
        started_at = _parse_dt(row["started_at"])
        ended_at = _parse_dt(row["ended_at"])
        if started_at is None or ended_at is None:
            raise ValueError("Stored app usage session is missing a valid time range")
        return AppUsageSession(
            id=int(row["id"]),
            target_id=row["target_id"],
            process_name=str(row["process_name"]),
            window_title=str(row["window_title"]),
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=int(row["duration_seconds"]),
        )

    @staticmethod
    def _program_id_for(connection: sqlite3.Connection, process_name: str) -> int | None:
        row = connection.execute("SELECT id FROM app_targets WHERE process_name = ?", (process_name,)).fetchone()
        return int(row["id"]) if row else None

    @staticmethod
    def _focus_session_from_row(row: sqlite3.Row) -> FocusSession:
        return FocusSession(
            id=int(row["id"]),
            title=str(row["title"]),
            task_id=row["task_id"],
            target_process_name=str(row["target_process_name"]),
            target_window_title=str(row["target_window_title"]),
            planned_seconds=int(row["planned_seconds"]),
            focused_seconds=int(row["focused_seconds"]),
            paused_seconds=int(row["paused_seconds"]),
            away_seconds=int(row["away_seconds"]),
            started_at=_parse_dt(row["started_at"]),
            ended_at=_parse_dt(row["ended_at"]),
            status=str(row["status"]),
        )

    @staticmethod
    def _focus_event_from_row(row: sqlite3.Row) -> FocusEvent:
        started_at = _parse_dt(row["started_at"])
        ended_at = _parse_dt(row["ended_at"])
        if started_at is None or ended_at is None:
            raise ValueError("Stored focus event is missing a valid time range")
        return FocusEvent(
            id=int(row["id"]),
            focus_session_id=int(row["focus_session_id"]),
            event_type=str(row["event_type"]),
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=int(row["duration_seconds"]),
            metadata=str(row["metadata"]),
        )

    @staticmethod
    def _quick_note_from_row(row: sqlite3.Row) -> QuickNote:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise ValueError("Stored quick note is missing a valid created_at")
        return QuickNote(
            id=int(row["id"]),
            body=str(row["body"]),
            created_at=created_at,
            focus_session_id=row["focus_session_id"],
            task_id=row["task_id"],
            process_name=str(row["process_name"]),
        )


def _clipped_seconds(session: AppUsageSession, start_at: datetime, end_at: datetime) -> int:
    clipped_start = max(session.started_at, start_at)
    clipped_end = min(session.ended_at, end_at)
    if clipped_end <= clipped_start:
        return 0
    return int((clipped_end - clipped_start).total_seconds())
