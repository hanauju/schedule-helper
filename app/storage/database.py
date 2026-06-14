from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
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
    ItemType,
    LinkFavorite,
    LayoutProfile,
    Preference,
    QuickNote,
    QuickNoteAttachment,
    QuickNoteFolder,
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


def _safe_file_stem(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "._- " else "_" for character in value)
    safe = safe.strip(" ._")[:80]
    return safe or "attachment"


def _favorite_display_mode(value: str) -> str:
    return value if value in {"text", "icon_with_label", "icon_only"} else "text"


def _time_format(value: str) -> str:
    return value if value in {"24h", "12h"} else "24h"


def _appearance_theme(value: str) -> str:
    return value if value in {"light", "dark"} else "light"


def _focus_rate_display(value: str) -> str:
    return value if value in {"ring", "bar"} else "ring"


def _header_banner_position(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"left", "center", "right"}:
        return normalized
    if normalized in {"top", "bottom"}:
        return "center"
    return "center"


def _accent_color(value: object) -> str:
    color = str(value or "").strip()
    if len(color) == 7 and color.startswith("#") and all(
        character in "0123456789abcdefABCDEF" for character in color[1:]
    ):
        return color.lower()
    return "#4f8c6b"


def _optional_color(value: object) -> str:
    color = str(value or "").strip()
    if len(color) == 7 and color.startswith("#") and all(
        character in "0123456789abcdefABCDEF" for character in color[1:]
    ):
        return color.lower()
    return ""


def _window_dimension(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        dimension = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, dimension))


def _header_banner_height(value: object) -> int:
    return _window_dimension(value, 132, 72, 360)


def _header_banner_span(value: object) -> int:
    return _window_dimension(value, 1, 1, 3)


DEFAULT_TASK_ITEM_TYPE_NAME = "할 일"
DEFAULT_EVENT_ITEM_TYPE_NAME = "일정"


def _item_base_kind(value: str) -> str:
    return value if value in {"task", "event"} else "task"


DEFAULT_QUICK_NOTE_FOLDER_NAME = "메모함"


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

                CREATE TABLE IF NOT EXISTS item_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    base_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    due_at TEXT,
                    priority INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    item_type_id INTEGER REFERENCES item_types(id) ON DELETE SET NULL,
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
                    item_type_id INTEGER REFERENCES item_types(id) ON DELETE SET NULL,
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
                    app_title TEXT NOT NULL DEFAULT 'Focus Desk',
                    main_always_on_top INTEGER NOT NULL DEFAULT 0,
                    show_focus_panel INTEGER NOT NULL DEFAULT 1,
                    show_datetime_panel INTEGER NOT NULL DEFAULT 1,
                    show_current_date INTEGER NOT NULL DEFAULT 1,
                    show_current_time INTEGER NOT NULL DEFAULT 1,
                    show_current_seconds INTEGER NOT NULL DEFAULT 0,
                    show_pomodoro_controls INTEGER NOT NULL DEFAULT 1,
                    show_today_timeline_inline INTEGER NOT NULL DEFAULT 1,
                    show_today_timeline_waiting_panel INTEGER NOT NULL DEFAULT 1,
                    show_today_timeline_waiting_pinned INTEGER NOT NULL DEFAULT 1,
                    show_today_checklist_inline INTEGER NOT NULL DEFAULT 0,
                    show_today_flow_panel INTEGER NOT NULL DEFAULT 0,
                    show_quick_memo_panel INTEGER NOT NULL DEFAULT 1,
                    show_link_favorites_panel INTEGER NOT NULL DEFAULT 1,
                    show_media_panel INTEGER NOT NULL DEFAULT 1,
                    media_panel_file_path TEXT NOT NULL DEFAULT '',
                    show_compact_favorites_panel INTEGER NOT NULL DEFAULT 0,
                    favorite_display_mode TEXT NOT NULL DEFAULT 'text',
                    time_format TEXT NOT NULL DEFAULT '24h',
                    appearance_theme TEXT NOT NULL DEFAULT 'light',
                    accent_color TEXT NOT NULL DEFAULT '#4f8c6b',
                    button_color TEXT NOT NULL DEFAULT '#4f8c6b',
                    background_color TEXT NOT NULL DEFAULT '',
                    inner_background_color TEXT NOT NULL DEFAULT '',
                    panel_color TEXT NOT NULL DEFAULT '',
                    table_color TEXT NOT NULL DEFAULT '',
                    text_color TEXT NOT NULL DEFAULT '',
                    show_header_banner INTEGER NOT NULL DEFAULT 0,
                    header_banner_image_path TEXT NOT NULL DEFAULT '',
                    header_banner_height INTEGER NOT NULL DEFAULT 132,
                    header_banner_position TEXT NOT NULL DEFAULT 'center',
                    header_banner_span INTEGER NOT NULL DEFAULT 1,
                    focus_rate_display TEXT NOT NULL DEFAULT 'ring',
                    last_window_width INTEGER NOT NULL DEFAULT 1280,
                    last_window_height INTEGER NOT NULL DEFAULT 820,
                    last_layout_state TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS layout_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS quick_note_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS quick_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL,
                    content_html TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    focus_session_id INTEGER REFERENCES focus_sessions(id) ON DELETE SET NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    folder_id INTEGER REFERENCES quick_note_folders(id) ON DELETE SET NULL,
                    process_name TEXT NOT NULL DEFAULT '',
                    window_title TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS quick_note_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quick_note_id INTEGER NOT NULL REFERENCES quick_notes(id) ON DELETE CASCADE,
                    file_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS link_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    target TEXT NOT NULL,
                    icon_text TEXT NOT NULL DEFAULT '',
                    icon_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_focus_sessions_started
                    ON focus_sessions (started_at, ended_at);

                CREATE INDEX IF NOT EXISTS idx_quick_notes_created
                    ON quick_notes (created_at);

                CREATE INDEX IF NOT EXISTS idx_quick_note_attachments_note
                    ON quick_note_attachments (quick_note_id);
                """
            )
            item_type_columns = {row["name"] for row in connection.execute("PRAGMA table_info(item_types)")}
            if "is_default" not in item_type_columns:
                connection.execute("ALTER TABLE item_types ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")
            task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "item_type_id" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN item_type_id INTEGER REFERENCES item_types(id) ON DELETE SET NULL")
            if "completed_at" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
            event_columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
            if "item_type_id" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN item_type_id INTEGER REFERENCES item_types(id) ON DELETE SET NULL")
            if "completed" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN completed INTEGER NOT NULL DEFAULT 0")
            if "completed_at" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN completed_at TEXT")
            default_task_type_id = self._ensure_default_item_type(connection, "task")
            default_event_type_id = self._ensure_default_item_type(connection, "event")
            connection.execute(
                "UPDATE tasks SET item_type_id = ? WHERE item_type_id IS NULL",
                (default_task_type_id,),
            )
            connection.execute(
                "UPDATE events SET item_type_id = ? WHERE item_type_id IS NULL",
                (default_event_type_id,),
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_item_types_default
                    ON item_types (base_kind, is_default)
                    WHERE is_default = 1
                """
            )
            preference_columns = {row["name"] for row in connection.execute("PRAGMA table_info(preferences)")}
            if "week_start_day" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN week_start_day INTEGER NOT NULL DEFAULT 0")
            if "app_title" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN app_title TEXT NOT NULL DEFAULT 'Focus Desk'")
            if "main_always_on_top" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN main_always_on_top INTEGER NOT NULL DEFAULT 0")
            if "show_focus_panel" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_focus_panel INTEGER NOT NULL DEFAULT 1")
            if "show_datetime_panel" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_datetime_panel INTEGER NOT NULL DEFAULT 1")
            if "show_current_date" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_current_date INTEGER NOT NULL DEFAULT 1")
            if "show_current_time" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_current_time INTEGER NOT NULL DEFAULT 1")
            if "show_current_seconds" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_current_seconds INTEGER NOT NULL DEFAULT 0")
            if "show_pomodoro_controls" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_pomodoro_controls INTEGER NOT NULL DEFAULT 1"
                )
            if "show_today_timeline_inline" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_timeline_inline INTEGER NOT NULL DEFAULT 1"
                )
            if "show_today_timeline_waiting_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_timeline_waiting_panel INTEGER NOT NULL DEFAULT 1"
                )
            if "show_today_timeline_waiting_pinned" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_timeline_waiting_pinned INTEGER NOT NULL DEFAULT 1"
                )
            if "show_today_checklist_inline" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_checklist_inline INTEGER NOT NULL DEFAULT 0"
                )
            if "show_today_flow_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_today_flow_panel INTEGER NOT NULL DEFAULT 0"
                )
            if "show_quick_memo_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_quick_memo_panel INTEGER NOT NULL DEFAULT 1"
                )
            if "show_link_favorites_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_link_favorites_panel INTEGER NOT NULL DEFAULT 1"
                )
            if "show_media_panel" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_media_panel INTEGER NOT NULL DEFAULT 1")
            if "media_panel_file_path" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN media_panel_file_path TEXT NOT NULL DEFAULT ''")
            if "show_compact_favorites_panel" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN show_compact_favorites_panel INTEGER NOT NULL DEFAULT 0"
                )
            if "favorite_display_mode" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN favorite_display_mode TEXT NOT NULL DEFAULT 'text'"
                )
            if "time_format" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN time_format TEXT NOT NULL DEFAULT '24h'")
            needs_palette_migration = "appearance_theme" not in preference_columns
            if needs_palette_migration:
                connection.execute("ALTER TABLE preferences ADD COLUMN appearance_theme TEXT NOT NULL DEFAULT 'light'")
            if "accent_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN accent_color TEXT NOT NULL DEFAULT '#4f8c6b'")
            elif needs_palette_migration:
                connection.execute(
                    "UPDATE preferences SET accent_color = '#4f8c6b' WHERE lower(accent_color) = '#5a5ad6'"
                )
            if "button_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN button_color TEXT NOT NULL DEFAULT '#4f8c6b'")
                connection.execute("UPDATE preferences SET button_color = accent_color")
            if "focus_rate_display" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN focus_rate_display TEXT NOT NULL DEFAULT 'ring'")
            if "background_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN background_color TEXT NOT NULL DEFAULT ''")
            if "inner_background_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN inner_background_color TEXT NOT NULL DEFAULT ''")
            if "panel_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN panel_color TEXT NOT NULL DEFAULT ''")
            if "table_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN table_color TEXT NOT NULL DEFAULT ''")
            if "text_color" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN text_color TEXT NOT NULL DEFAULT ''")
            if "show_header_banner" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN show_header_banner INTEGER NOT NULL DEFAULT 0")
            if "header_banner_image_path" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN header_banner_image_path TEXT NOT NULL DEFAULT ''")
            if "header_banner_height" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN header_banner_height INTEGER NOT NULL DEFAULT 132")
            if "header_banner_position" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN header_banner_position TEXT NOT NULL DEFAULT 'center'")
            if "header_banner_span" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN header_banner_span INTEGER NOT NULL DEFAULT 1")
            if "last_window_width" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN last_window_width INTEGER NOT NULL DEFAULT 1280"
                )
            if "last_window_height" not in preference_columns:
                connection.execute(
                    "ALTER TABLE preferences ADD COLUMN last_window_height INTEGER NOT NULL DEFAULT 820"
                )
            if "last_layout_state" not in preference_columns:
                connection.execute("ALTER TABLE preferences ADD COLUMN last_layout_state TEXT NOT NULL DEFAULT ''")

            favorite_columns = {row["name"] for row in connection.execute("PRAGMA table_info(link_favorites)")}
            if "icon_text" not in favorite_columns:
                connection.execute("ALTER TABLE link_favorites ADD COLUMN icon_text TEXT NOT NULL DEFAULT ''")
            if "icon_path" not in favorite_columns:
                connection.execute("ALTER TABLE link_favorites ADD COLUMN icon_path TEXT NOT NULL DEFAULT ''")

            quick_note_columns = {row["name"] for row in connection.execute("PRAGMA table_info(quick_notes)")}
            if "content_html" not in quick_note_columns:
                connection.execute("ALTER TABLE quick_notes ADD COLUMN content_html TEXT NOT NULL DEFAULT ''")
            if "folder_id" not in quick_note_columns:
                connection.execute("ALTER TABLE quick_notes ADD COLUMN folder_id INTEGER REFERENCES quick_note_folders(id) ON DELETE SET NULL")
            if "window_title" not in quick_note_columns:
                connection.execute("ALTER TABLE quick_notes ADD COLUMN window_title TEXT NOT NULL DEFAULT ''")

            quick_note_folder_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(quick_note_folders)")
            }
            if "is_default" not in quick_note_folder_columns:
                connection.execute("ALTER TABLE quick_note_folders ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")

            default_folder_id = self._ensure_default_quick_note_folder(connection)
            connection.execute("UPDATE quick_notes SET folder_id = ? WHERE folder_id IS NULL", (default_folder_id,))
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quick_notes_folder
                    ON quick_notes (folder_id, created_at)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_quick_note_folders_default
                    ON quick_note_folders (is_default)
                    WHERE is_default = 1
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
                    INSERT INTO preferences
                      (id, day_max_minutes, break_minutes, strategy, week_start_day,
                       app_title, main_always_on_top,
                       show_focus_panel,
                       show_datetime_panel, show_current_date, show_current_time, show_current_seconds,
                       show_pomodoro_controls, show_today_timeline_inline, show_today_timeline_waiting_panel,
                       show_today_timeline_waiting_pinned,
                       show_today_checklist_inline,
                       show_today_flow_panel, show_quick_memo_panel, show_link_favorites_panel,
                       show_media_panel, media_panel_file_path,
                       show_compact_favorites_panel, favorite_display_mode, time_format, appearance_theme, accent_color, button_color,
                       background_color, inner_background_color, panel_color, table_color, text_color,
                       show_header_banner, header_banner_image_path,
                       header_banner_height, header_banner_position, header_banner_span,
                       focus_rate_display)
                    VALUES (1, 480, 10, 'deadline_priority', 0, 'Focus Desk', 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 0, 1, 1, 1, '', 0, 'text', '24h', 'light', '#4f8c6b', '#4f8c6b', '', '', '', '', '', 0, '', 132, 'center', 1, 'ring')
                    """
                )

            self._ensure_default_quick_note_folder(connection)
            self._ensure_default_item_type(connection, "task")
            self._ensure_default_item_type(connection, "event")

    def default_item_type(self, base_kind: str) -> ItemType:
        kind = _item_base_kind(base_kind)
        with self.connect() as connection:
            type_id = self._ensure_default_item_type(connection, kind)
            row = connection.execute("SELECT * FROM item_types WHERE id = ?", (type_id,)).fetchone()
        if row is None:
            raise ValueError("Default item type could not be created")
        return self._item_type_from_row(row)

    def list_item_types(self, base_kind: str | None = None) -> list[ItemType]:
        query = "SELECT * FROM item_types"
        params: tuple[object, ...] = ()
        if base_kind is not None:
            query += " WHERE base_kind = ?"
            params = (_item_base_kind(base_kind),)
        query += (
            " ORDER BY CASE base_kind WHEN 'task' THEN 0 ELSE 1 END, "
            "is_default DESC, name COLLATE NOCASE ASC, id ASC"
        )

        with self.connect() as connection:
            self._ensure_default_item_type(connection, "task")
            self._ensure_default_item_type(connection, "event")
            rows = connection.execute(query, params).fetchall()
        return [self._item_type_from_row(row) for row in rows]

    def get_item_type(self, item_type_id: int | None) -> ItemType | None:
        if item_type_id is None:
            return None
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM item_types WHERE id = ?", (item_type_id,)).fetchone()
        return self._item_type_from_row(row) if row else None

    def save_item_type(self, item_type: ItemType) -> ItemType:
        item_type.name = item_type.name.strip()
        if not item_type.name:
            raise ValueError("Item type name is required")
        item_type.base_kind = _item_base_kind(item_type.base_kind)

        with self.connect() as connection:
            if item_type.is_default:
                connection.execute(
                    "UPDATE item_types SET is_default = 0 WHERE base_kind = ?",
                    (item_type.base_kind,),
                )

            if item_type.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO item_types (name, base_kind, created_at, is_default)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        item_type.name,
                        item_type.base_kind,
                        _dt_exact(item_type.created_at),
                        int(item_type.is_default),
                    ),
                )
                item_type.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE item_types
                    SET name = ?,
                        base_kind = ?,
                        is_default = ?
                    WHERE id = ?
                    """,
                    (
                        item_type.name,
                        item_type.base_kind,
                        int(item_type.is_default),
                        item_type.id,
                    ),
                )

            self._ensure_default_item_type(connection, item_type.base_kind)
        return item_type

    def set_default_item_type(self, item_type_id: int) -> ItemType | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM item_types WHERE id = ?", (item_type_id,)).fetchone()
            if row is None:
                return None
            item_type = self._item_type_from_row(row)
            connection.execute(
                "UPDATE item_types SET is_default = 0 WHERE base_kind = ?",
                (item_type.base_kind,),
            )
            connection.execute("UPDATE item_types SET is_default = 1 WHERE id = ?", (item_type.id,))
            updated = connection.execute("SELECT * FROM item_types WHERE id = ?", (item_type.id,)).fetchone()
        return self._item_type_from_row(updated) if updated else None

    def delete_item_type(self, item_type_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM item_types WHERE id = ?", (item_type_id,)).fetchone()
            if row is None:
                return False
            item_type = self._item_type_from_row(row)
            if item_type.is_default:
                return False
            default_type_id = self._ensure_default_item_type(connection, item_type.base_kind)
            table = "tasks" if item_type.base_kind == "task" else "events"
            connection.execute(
                f"UPDATE {table} SET item_type_id = ? WHERE item_type_id = ?",
                (default_type_id, item_type_id),
            )
            connection.execute("DELETE FROM item_types WHERE id = ?", (item_type_id,))
        return True

    def _default_item_type_id(self, connection: sqlite3.Connection, base_kind: str) -> int:
        return self._ensure_default_item_type(connection, _item_base_kind(base_kind))

    def save_task(self, task: Task) -> Task:
        if task.completed and task.completed_at is None:
            task.completed_at = datetime.now()
        elif not task.completed:
            task.completed_at = None

        with self.connect() as connection:
            task.item_type_id = task.item_type_id or self._default_item_type_id(connection, "task")
            if task.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tasks
                      (title, duration_minutes, due_at, priority, category, item_type_id, completed, completed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.title,
                        task.duration_minutes,
                        _dt(task.due_at),
                        task.priority,
                        task.category,
                        task.item_type_id,
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
                        item_type_id = ?,
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
                        task.item_type_id,
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
            event.item_type_id = event.item_type_id or self._default_item_type_id(connection, "event")
            if event.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO events
                      (title, start_at, end_at, fixed, task_id, category, item_type_id, completed, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.title,
                        _dt(event.start_at),
                        _dt(event.end_at),
                        int(event.fixed),
                        event.task_id,
                        event.category,
                        event.item_type_id,
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
                        item_type_id = ?,
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
                        event.item_type_id,
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
            app_title=str(row["app_title"]).strip() or "Focus Desk",
            main_always_on_top=bool(row["main_always_on_top"]),
            show_focus_panel=bool(row["show_focus_panel"]),
            show_datetime_panel=bool(row["show_datetime_panel"]),
            show_current_date=bool(row["show_current_date"]),
            show_current_time=bool(row["show_current_time"]),
            show_current_seconds=bool(row["show_current_seconds"]),
            show_pomodoro_controls=bool(row["show_pomodoro_controls"]),
            show_today_timeline_inline=bool(row["show_today_timeline_inline"]),
            show_today_timeline_waiting_panel=bool(row["show_today_timeline_waiting_panel"]),
            show_today_timeline_waiting_pinned=bool(row["show_today_timeline_waiting_pinned"]),
            show_today_checklist_inline=bool(row["show_today_checklist_inline"]),
            show_today_flow_panel=bool(row["show_today_flow_panel"]),
            show_quick_memo_panel=bool(row["show_quick_memo_panel"]),
            show_link_favorites_panel=bool(row["show_link_favorites_panel"]),
            show_media_panel=bool(row["show_media_panel"]),
            media_panel_file_path=str(row["media_panel_file_path"] or "").strip(),
            show_compact_favorites_panel=bool(row["show_compact_favorites_panel"]),
            favorite_display_mode=_favorite_display_mode(str(row["favorite_display_mode"])),
            time_format=_time_format(str(row["time_format"])),
            appearance_theme=_appearance_theme(str(row["appearance_theme"])),
            accent_color=_accent_color(row["accent_color"]),
            button_color=_accent_color(row["button_color"]),
            background_color=_optional_color(row["background_color"]),
            inner_background_color=_optional_color(row["inner_background_color"]),
            panel_color=_optional_color(row["panel_color"]),
            table_color=_optional_color(row["table_color"]),
            text_color=_optional_color(row["text_color"]),
            show_header_banner=bool(row["show_header_banner"]),
            header_banner_image_path=str(row["header_banner_image_path"] or "").strip(),
            header_banner_height=_header_banner_height(row["header_banner_height"]),
            header_banner_position=_header_banner_position(str(row["header_banner_position"])),
            header_banner_span=_header_banner_span(row["header_banner_span"]),
            focus_rate_display=_focus_rate_display(str(row["focus_rate_display"])),
            last_window_width=_window_dimension(row["last_window_width"], 1280, 430, 4000),
            last_window_height=_window_dimension(row["last_window_height"], 820, 320, 3000),
            last_layout_state=str(row["last_layout_state"]),
        )

    def save_preferences(self, preferences: Preference) -> Preference:
        preferences.week_start_day = 6 if preferences.week_start_day == 6 else 0
        preferences.time_format = _time_format(preferences.time_format)
        preferences.appearance_theme = _appearance_theme(preferences.appearance_theme)
        preferences.accent_color = _accent_color(preferences.accent_color)
        preferences.button_color = _accent_color(preferences.button_color)
        preferences.background_color = _optional_color(preferences.background_color)
        preferences.inner_background_color = _optional_color(preferences.inner_background_color)
        preferences.panel_color = _optional_color(preferences.panel_color)
        preferences.table_color = _optional_color(preferences.table_color)
        preferences.text_color = _optional_color(preferences.text_color)
        preferences.media_panel_file_path = preferences.media_panel_file_path.strip()
        preferences.header_banner_image_path = preferences.header_banner_image_path.strip()
        preferences.header_banner_height = _header_banner_height(preferences.header_banner_height)
        preferences.header_banner_position = _header_banner_position(preferences.header_banner_position)
        preferences.header_banner_span = _header_banner_span(preferences.header_banner_span)
        preferences.focus_rate_display = _focus_rate_display(preferences.focus_rate_display)
        preferences.app_title = preferences.app_title.strip() or "Focus Desk"
        preferences.last_window_width = _window_dimension(preferences.last_window_width, 1280, 430, 4000)
        preferences.last_window_height = _window_dimension(preferences.last_window_height, 820, 320, 3000)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences
                  (id, day_max_minutes, break_minutes, strategy, week_start_day,
                   app_title, main_always_on_top,
                   show_focus_panel, show_datetime_panel, show_current_date, show_current_time, show_current_seconds,
                   show_pomodoro_controls, show_today_timeline_inline, show_today_timeline_waiting_panel,
                   show_today_timeline_waiting_pinned, show_today_checklist_inline,
                   show_today_flow_panel, show_quick_memo_panel, show_link_favorites_panel,
                   show_media_panel, media_panel_file_path,
                   show_compact_favorites_panel, favorite_display_mode, time_format, appearance_theme, accent_color,
                   button_color, background_color, inner_background_color, panel_color, table_color, text_color,
                   show_header_banner, header_banner_image_path, header_banner_height, header_banner_position, header_banner_span,
                   focus_rate_display,
                   last_window_width, last_window_height, last_layout_state)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day_max_minutes = excluded.day_max_minutes,
                    break_minutes = excluded.break_minutes,
                    strategy = excluded.strategy,
                    week_start_day = excluded.week_start_day,
                    app_title = excluded.app_title,
                    main_always_on_top = excluded.main_always_on_top,
                    show_focus_panel = excluded.show_focus_panel,
                    show_datetime_panel = excluded.show_datetime_panel,
                    show_current_date = excluded.show_current_date,
                    show_current_time = excluded.show_current_time,
                    show_current_seconds = excluded.show_current_seconds,
                    show_pomodoro_controls = excluded.show_pomodoro_controls,
                    show_today_timeline_inline = excluded.show_today_timeline_inline,
                    show_today_timeline_waiting_panel = excluded.show_today_timeline_waiting_panel,
                    show_today_timeline_waiting_pinned = excluded.show_today_timeline_waiting_pinned,
                    show_today_checklist_inline = excluded.show_today_checklist_inline,
                    show_today_flow_panel = excluded.show_today_flow_panel,
                    show_quick_memo_panel = excluded.show_quick_memo_panel,
                    show_link_favorites_panel = excluded.show_link_favorites_panel,
                    show_media_panel = excluded.show_media_panel,
                    media_panel_file_path = excluded.media_panel_file_path,
                    show_compact_favorites_panel = excluded.show_compact_favorites_panel,
                    favorite_display_mode = excluded.favorite_display_mode,
                    time_format = excluded.time_format,
                    appearance_theme = excluded.appearance_theme,
                    accent_color = excluded.accent_color,
                    button_color = excluded.button_color,
                    background_color = excluded.background_color,
                    inner_background_color = excluded.inner_background_color,
                    panel_color = excluded.panel_color,
                    table_color = excluded.table_color,
                    text_color = excluded.text_color,
                    show_header_banner = excluded.show_header_banner,
                    header_banner_image_path = excluded.header_banner_image_path,
                    header_banner_height = excluded.header_banner_height,
                    header_banner_position = excluded.header_banner_position,
                    header_banner_span = excluded.header_banner_span,
                    focus_rate_display = excluded.focus_rate_display,
                    last_window_width = excluded.last_window_width,
                    last_window_height = excluded.last_window_height,
                    last_layout_state = excluded.last_layout_state
                """,
                (
                    preferences.day_max_minutes,
                    preferences.break_minutes,
                    preferences.strategy,
                    preferences.week_start_day,
                    preferences.app_title,
                    int(preferences.main_always_on_top),
                    int(preferences.show_focus_panel),
                    int(preferences.show_datetime_panel),
                    int(preferences.show_current_date),
                    int(preferences.show_current_time),
                    int(preferences.show_current_seconds),
                    int(preferences.show_pomodoro_controls),
                    int(preferences.show_today_timeline_inline),
                    int(preferences.show_today_timeline_waiting_panel),
                    int(preferences.show_today_timeline_waiting_pinned),
                    int(preferences.show_today_checklist_inline),
                    int(preferences.show_today_flow_panel),
                    int(preferences.show_quick_memo_panel),
                    int(preferences.show_link_favorites_panel),
                    int(preferences.show_media_panel),
                    preferences.media_panel_file_path,
                    int(preferences.show_compact_favorites_panel),
                    _favorite_display_mode(preferences.favorite_display_mode),
                    _time_format(preferences.time_format),
                    _appearance_theme(preferences.appearance_theme),
                    preferences.accent_color,
                    preferences.button_color,
                    preferences.background_color,
                    preferences.inner_background_color,
                    preferences.panel_color,
                    preferences.table_color,
                    preferences.text_color,
                    int(preferences.show_header_banner),
                    preferences.header_banner_image_path,
                    preferences.header_banner_height,
                    _header_banner_position(preferences.header_banner_position),
                    preferences.header_banner_span,
                    _focus_rate_display(preferences.focus_rate_display),
                    preferences.last_window_width,
                    preferences.last_window_height,
                    preferences.last_layout_state,
                ),
            )
        return preferences

    def save_layout_profile(self, profile: LayoutProfile) -> LayoutProfile:
        now = datetime.now()
        name = profile.name.strip()
        if not name:
            raise ValueError("Layout profile name is required")

        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM layout_profiles WHERE name = ?",
                (name,),
            ).fetchone()
            if existing:
                profile.id = int(existing["id"])
                profile.created_at = _parse_dt(existing["created_at"]) or profile.created_at
                profile.updated_at = now
                connection.execute(
                    """
                    UPDATE layout_profiles
                    SET data = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (profile.data, _dt_exact(profile.updated_at), profile.id),
                )
            else:
                profile.name = name
                profile.created_at = now
                profile.updated_at = now
                cursor = connection.execute(
                    """
                    INSERT INTO layout_profiles (name, data, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        profile.name,
                        profile.data,
                        _dt_exact(profile.created_at),
                        _dt_exact(profile.updated_at),
                    ),
                )
                profile.id = int(cursor.lastrowid)
        return profile

    def list_layout_profiles(self) -> list[LayoutProfile]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM layout_profiles
                ORDER BY updated_at DESC, name ASC
                """
            ).fetchall()
        return [self._layout_profile_from_row(row) for row in rows]

    def get_layout_profile(self, name: str) -> LayoutProfile | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM layout_profiles WHERE name = ?",
                (name.strip(),),
            ).fetchone()
        return self._layout_profile_from_row(row) if row else None

    def delete_layout_profile(self, profile_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM layout_profiles WHERE id = ?", (profile_id,))

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

    def default_quick_note_folder(self) -> QuickNoteFolder:
        with self.connect() as connection:
            folder_id = self._ensure_default_quick_note_folder(connection)
            row = connection.execute("SELECT * FROM quick_note_folders WHERE id = ?", (folder_id,)).fetchone()
        if row is None:
            raise ValueError("Default quick note folder could not be created")
        return self._quick_note_folder_from_row(row)

    def list_quick_note_folders(self) -> list[QuickNoteFolder]:
        with self.connect() as connection:
            self._ensure_default_quick_note_folder(connection)
            rows = connection.execute(
                """
                SELECT * FROM quick_note_folders
                ORDER BY is_default DESC, name COLLATE NOCASE ASC, id ASC
                """
            ).fetchall()
        return [self._quick_note_folder_from_row(row) for row in rows]

    def get_quick_note_folder(self, folder_id: int) -> QuickNoteFolder | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM quick_note_folders WHERE id = ?", (folder_id,)).fetchone()
        return self._quick_note_folder_from_row(row) if row else None

    def save_quick_note_folder(self, folder: QuickNoteFolder) -> QuickNoteFolder:
        name = folder.name.strip() or DEFAULT_QUICK_NOTE_FOLDER_NAME
        with self.connect() as connection:
            if folder.is_default:
                connection.execute("UPDATE quick_note_folders SET is_default = 0 WHERE is_default = 1")
            if folder.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO quick_note_folders (name, created_at, is_default)
                    VALUES (?, ?, ?)
                    """,
                    (name, _dt_exact(folder.created_at), int(folder.is_default)),
                )
                folder.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE quick_note_folders
                    SET name = ?,
                        is_default = ?
                    WHERE id = ?
                    """,
                    (name, int(folder.is_default), folder.id),
                )
            if not folder.is_default:
                self._ensure_default_quick_note_folder(connection)
        folder.name = name
        return folder

    def set_default_quick_note_folder(self, folder_id: int) -> QuickNoteFolder | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM quick_note_folders WHERE id = ?", (folder_id,)).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE quick_note_folders SET is_default = 0 WHERE is_default = 1")
            connection.execute("UPDATE quick_note_folders SET is_default = 1 WHERE id = ?", (folder_id,))
            updated = connection.execute("SELECT * FROM quick_note_folders WHERE id = ?", (folder_id,)).fetchone()
        return self._quick_note_folder_from_row(updated) if updated else None

    def delete_quick_note_folder(self, folder_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM quick_note_folders WHERE id = ?", (folder_id,)).fetchone()
            if row is None:
                return False
            folder = self._quick_note_folder_from_row(row)
            if folder.is_default:
                return False
            default_folder_id = self._ensure_default_quick_note_folder(connection)
            connection.execute(
                "UPDATE quick_notes SET folder_id = ? WHERE folder_id = ?",
                (default_folder_id, folder_id),
            )
            connection.execute("DELETE FROM quick_note_folders WHERE id = ?", (folder_id,))
        return True

    def move_quick_notes_to_folder(self, note_ids: list[int] | tuple[int, ...] | set[int], folder_id: int) -> int:
        unique_note_ids = sorted({int(note_id) for note_id in note_ids if int(note_id) > 0})
        if not unique_note_ids:
            return 0

        with self.connect() as connection:
            folder = connection.execute("SELECT id FROM quick_note_folders WHERE id = ?", (folder_id,)).fetchone()
            if folder is None:
                return 0
            placeholders = ", ".join("?" for _ in unique_note_ids)
            cursor = connection.execute(
                f"UPDATE quick_notes SET folder_id = ? WHERE id IN ({placeholders})",
                (folder_id, *unique_note_ids),
            )
        return int(cursor.rowcount)

    def save_quick_note(self, note: QuickNote) -> QuickNote:
        with self.connect() as connection:
            folder_id = note.folder_id or self._ensure_default_quick_note_folder(connection)
            if note.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO quick_notes
                      (body, content_html, created_at, focus_session_id, task_id, folder_id, process_name, window_title)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note.body.strip(),
                        note.content_html,
                        _dt_exact(note.created_at),
                        note.focus_session_id,
                        note.task_id,
                        folder_id,
                        normalize_process_name(note.process_name) if note.process_name else "",
                        note.window_title.strip(),
                    ),
                )
                note.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE quick_notes
                    SET body = ?,
                        content_html = ?,
                        created_at = ?,
                        focus_session_id = ?,
                        task_id = ?,
                        folder_id = ?,
                        process_name = ?,
                        window_title = ?
                    WHERE id = ?
                    """,
                    (
                        note.body.strip(),
                        note.content_html,
                        _dt_exact(note.created_at),
                        note.focus_session_id,
                        note.task_id,
                        folder_id,
                        normalize_process_name(note.process_name) if note.process_name else "",
                        note.window_title.strip(),
                        note.id,
                    ),
                )
        note.folder_id = folder_id
        return note

    def list_quick_notes(
        self,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int | None = None,
        folder_id: int | None = None,
    ) -> list[QuickNote]:
        query = "SELECT * FROM quick_notes"
        params: list[object] = []
        conditions: list[str] = []
        if start_at and end_at:
            conditions.append("created_at >= ? AND created_at < ?")
            params.extend([_dt_exact(start_at), _dt_exact(end_at)])
        if folder_id is not None:
            conditions.append("folder_id = ?")
            params.append(folder_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
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
        attachments = self.list_quick_note_attachments(note_id)
        with self.connect() as connection:
            connection.execute("DELETE FROM quick_notes WHERE id = ?", (note_id,))
        for attachment in attachments:
            self._delete_attachment_file(attachment)

    def add_quick_note_attachment(self, note_id: int, source_path: Path | str) -> QuickNoteAttachment:
        if self.get_quick_note(note_id) is None:
            raise ValueError("Quick note does not exist")

        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))

        target = self._attachment_storage_path(note_id, source)
        shutil.copy2(source, target)

        attachment = QuickNoteAttachment(
            quick_note_id=note_id,
            file_name=source.name,
            stored_path=str(target),
            created_at=datetime.now(),
        )
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO quick_note_attachments (quick_note_id, file_name, stored_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    attachment.quick_note_id,
                    attachment.file_name,
                    attachment.stored_path,
                    _dt_exact(attachment.created_at),
                ),
            )
            attachment.id = int(cursor.lastrowid)
        return attachment

    def list_quick_note_attachments(self, note_id: int) -> list[QuickNoteAttachment]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM quick_note_attachments
                WHERE quick_note_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (note_id,),
            ).fetchall()
        return [self._quick_note_attachment_from_row(row) for row in rows]

    def get_quick_note_attachment(self, attachment_id: int) -> QuickNoteAttachment | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM quick_note_attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
        return self._quick_note_attachment_from_row(row) if row else None

    def delete_quick_note_attachment(self, attachment_id: int) -> None:
        attachment = self.get_quick_note_attachment(attachment_id)
        with self.connect() as connection:
            connection.execute("DELETE FROM quick_note_attachments WHERE id = ?", (attachment_id,))
        if attachment is not None:
            self._delete_attachment_file(attachment)

    def _attachment_storage_path(self, note_id: int, source: Path) -> Path:
        directory = self.db_path.parent / "attachments" / str(note_id)
        directory.mkdir(parents=True, exist_ok=True)
        safe_stem = _safe_file_stem(source.stem)
        suffix = source.suffix[:20]
        return directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"

    def copy_inline_note_image(self, source_path: Path | str) -> str:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))

        directory = self.db_path.parent / "inline_images"
        directory.mkdir(parents=True, exist_ok=True)
        safe_stem = _safe_file_stem(source.stem)
        suffix = source.suffix[:20]
        target = directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
        shutil.copy2(source, target)
        return str(target)

    def _delete_attachment_file(self, attachment: QuickNoteAttachment) -> None:
        try:
            Path(attachment.stored_path).unlink(missing_ok=True)
        except OSError:
            pass

    def save_link_favorite(self, favorite: LinkFavorite) -> LinkFavorite:
        title = favorite.title.strip()
        target = favorite.target.strip()
        icon_text = favorite.icon_text.strip()[:12]
        icon_path = favorite.icon_path.strip()
        if not title:
            title = target
        if not title or not target:
            raise ValueError("Link favorite title and target are required")

        with self.connect() as connection:
            if favorite.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO link_favorites (title, target, icon_text, icon_path, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (title, target, icon_text, icon_path, _dt_exact(favorite.created_at)),
                )
                favorite.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE link_favorites
                    SET title = ?,
                        target = ?,
                        icon_text = ?,
                        icon_path = ?
                    WHERE id = ?
                    """,
                    (title, target, icon_text, icon_path, favorite.id),
                )
        favorite.title = title
        favorite.target = target
        favorite.icon_text = icon_text
        favorite.icon_path = icon_path
        return favorite

    def copy_link_favorite_icon(self, favorite_id: int, source_path: Path | str) -> str:
        if self.get_link_favorite(favorite_id) is None:
            raise ValueError("Link favorite does not exist")

        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))

        directory = self.db_path.parent / "favorite_icons" / str(favorite_id)
        directory.mkdir(parents=True, exist_ok=True)
        safe_stem = _safe_file_stem(source.stem)
        suffix = source.suffix[:20]
        target = directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
        shutil.copy2(source, target)
        return str(target)

    def save_link_favorite_icon_bytes(self, favorite_id: int, file_name: str, data: bytes) -> str:
        if self.get_link_favorite(favorite_id) is None:
            raise ValueError("Link favorite does not exist")
        if not data:
            raise ValueError("Icon data is empty")

        directory = self.db_path.parent / "favorite_icons" / str(favorite_id)
        directory.mkdir(parents=True, exist_ok=True)
        source_name = Path(file_name or "site-icon.ico")
        safe_stem = _safe_file_stem(source_name.stem)
        suffix = source_name.suffix[:20] or ".ico"
        target = directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
        target.write_bytes(data)
        return str(target)

    def list_link_favorites(self) -> list[LinkFavorite]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM link_favorites
                ORDER BY title COLLATE NOCASE ASC, id ASC
                """
            ).fetchall()
        return [self._link_favorite_from_row(row) for row in rows]

    def get_link_favorite(self, favorite_id: int) -> LinkFavorite | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM link_favorites WHERE id = ?", (favorite_id,)).fetchone()
        return self._link_favorite_from_row(row) if row else None

    def delete_link_favorite(self, favorite_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM link_favorites WHERE id = ?", (favorite_id,))

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        keys = set(row.keys())
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
            item_type_id=row["item_type_id"] if "item_type_id" in keys else None,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> Event:
        start_at = _parse_dt(row["start_at"])
        end_at = _parse_dt(row["end_at"])
        if start_at is None or end_at is None:
            raise ValueError("Stored event is missing a valid time range")
        keys = set(row.keys())
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
            item_type_id=row["item_type_id"] if "item_type_id" in keys else None,
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
    def _ensure_default_item_type(connection: sqlite3.Connection, base_kind: str) -> int:
        kind = _item_base_kind(base_kind)
        row = connection.execute(
            """
            SELECT id FROM item_types
            WHERE base_kind = ? AND is_default = 1
            ORDER BY id ASC
            LIMIT 1
            """,
            (kind,),
        ).fetchone()
        if row is not None:
            return int(row["id"])

        first_row = connection.execute(
            """
            SELECT id FROM item_types
            WHERE base_kind = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (kind,),
        ).fetchone()
        if first_row is not None:
            item_type_id = int(first_row["id"])
            connection.execute("UPDATE item_types SET is_default = 1 WHERE id = ?", (item_type_id,))
            return item_type_id

        name = DEFAULT_EVENT_ITEM_TYPE_NAME if kind == "event" else DEFAULT_TASK_ITEM_TYPE_NAME
        cursor = connection.execute(
            """
            INSERT INTO item_types (name, base_kind, created_at, is_default)
            VALUES (?, ?, ?, 1)
            """,
            (name, kind, _dt_exact(datetime.now())),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _item_type_from_row(row: sqlite3.Row) -> ItemType:
        created_at = _parse_dt(row["created_at"]) or datetime.now()
        return ItemType(
            id=int(row["id"]),
            name=str(row["name"]),
            base_kind=_item_base_kind(str(row["base_kind"])),
            created_at=created_at,
            is_default=bool(row["is_default"]),
        )

    @staticmethod
    def _ensure_default_quick_note_folder(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT id FROM quick_note_folders WHERE is_default = 1 ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is not None:
            return int(row["id"])

        named_row = connection.execute(
            """
            SELECT id FROM quick_note_folders
            WHERE name = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (DEFAULT_QUICK_NOTE_FOLDER_NAME,),
        ).fetchone()
        if named_row is not None:
            folder_id = int(named_row["id"])
            connection.execute("UPDATE quick_note_folders SET is_default = 1 WHERE id = ?", (folder_id,))
            return folder_id

        cursor = connection.execute(
            """
            INSERT INTO quick_note_folders (name, created_at, is_default)
            VALUES (?, ?, 1)
            """,
            (DEFAULT_QUICK_NOTE_FOLDER_NAME, _dt_exact(datetime.now())),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _quick_note_folder_from_row(row: sqlite3.Row) -> QuickNoteFolder:
        created_at = _parse_dt(row["created_at"]) or datetime.now()
        return QuickNoteFolder(
            id=int(row["id"]),
            name=str(row["name"]),
            created_at=created_at,
            is_default=bool(row["is_default"]),
        )

    @staticmethod
    def _quick_note_from_row(row: sqlite3.Row) -> QuickNote:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise ValueError("Stored quick note is missing a valid created_at")
        keys = set(row.keys())
        return QuickNote(
            id=int(row["id"]),
            body=str(row["body"]),
            content_html=str(row["content_html"]),
            created_at=created_at,
            focus_session_id=row["focus_session_id"],
            task_id=row["task_id"],
            folder_id=row["folder_id"] if "folder_id" in keys else None,
            process_name=str(row["process_name"]),
            window_title=str(row["window_title"]) if "window_title" in keys else "",
        )

    @staticmethod
    def _quick_note_attachment_from_row(row: sqlite3.Row) -> QuickNoteAttachment:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise ValueError("Stored quick note attachment is missing a valid created_at")
        return QuickNoteAttachment(
            id=int(row["id"]),
            quick_note_id=int(row["quick_note_id"]),
            file_name=str(row["file_name"]),
            stored_path=str(row["stored_path"]),
            created_at=created_at,
        )

    @staticmethod
    def _link_favorite_from_row(row: sqlite3.Row) -> LinkFavorite:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise ValueError("Stored link favorite is missing a valid created_at")
        return LinkFavorite(
            id=int(row["id"]),
            title=str(row["title"]),
            target=str(row["target"]),
            icon_text=str(row["icon_text"]),
            icon_path=str(row["icon_path"]),
            created_at=created_at,
        )

    @staticmethod
    def _layout_profile_from_row(row: sqlite3.Row) -> LayoutProfile:
        created_at = _parse_dt(row["created_at"]) or datetime.now()
        updated_at = _parse_dt(row["updated_at"]) or created_at
        return LayoutProfile(
            id=int(row["id"]),
            name=str(row["name"]),
            data=str(row["data"]),
            created_at=created_at,
            updated_at=updated_at,
        )


def _clipped_seconds(session: AppUsageSession, start_at: datetime, end_at: datetime) -> int:
    clipped_start = max(session.started_at, start_at)
    clipped_end = min(session.ended_at, end_at)
    if clipped_end <= clipped_start:
        return 0
    return int((clipped_end - clipped_start).total_seconds())
