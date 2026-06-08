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
    completed_at: datetime | None = None
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
    completed: bool = False
    completed_at: datetime | None = None
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
    week_start_day: int = 0
    show_pomodoro_controls: bool = True
    show_today_timeline_inline: bool = True
    show_today_checklist_inline: bool = False
    show_today_flow_panel: bool = False
    show_quick_memo_panel: bool = True
    show_link_favorites_panel: bool = True
    show_compact_favorites_panel: bool = False
    favorite_display_mode: str = "text"
    time_format: str = "24h"
    id: int = 1


@dataclass(slots=True)
class LayoutProfile:
    name: str
    data: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass(slots=True)
class TrackedProgram:
    display_name: str
    process_name: str
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None

    @property
    def normalized_process_name(self) -> str:
        return self.process_name.strip().lower()


@dataclass(slots=True)
class AppUsageSession:
    target_id: int | None
    process_name: str
    window_title: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    id: int | None = None


@dataclass(slots=True)
class AppUsageSummary:
    target_id: int | None
    display_name: str
    process_name: str
    total_seconds: int
    last_used_at: datetime | None = None


@dataclass(slots=True)
class FocusSession:
    title: str
    planned_seconds: int
    focused_seconds: int = 0
    paused_seconds: int = 0
    away_seconds: int = 0
    status: str = "ready"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    task_id: int | None = None
    target_process_name: str = ""
    target_window_title: str = ""
    id: int | None = None

    @property
    def elapsed_seconds(self) -> int:
        return self.focused_seconds + self.away_seconds

    @property
    def remaining_seconds(self) -> int:
        return max(0, self.planned_seconds - self.focused_seconds)


@dataclass(slots=True)
class FocusEvent:
    focus_session_id: int
    event_type: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    metadata: str = ""
    id: int | None = None


@dataclass(slots=True)
class QuickNote:
    body: str
    content_html: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    focus_session_id: int | None = None
    task_id: int | None = None
    process_name: str = ""
    id: int | None = None


@dataclass(slots=True)
class QuickNoteAttachment:
    quick_note_id: int
    file_name: str
    stored_path: str
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass(slots=True)
class LinkFavorite:
    title: str
    target: str
    icon_text: str = ""
    icon_path: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
