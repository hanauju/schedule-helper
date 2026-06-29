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
    item_type_id: int | None = None
    pinned: bool = False


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
    item_type_id: int | None = None
    pinned: bool = False

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
    app_title: str = "오롯"
    main_always_on_top: bool = False
    show_focus_panel: bool = True
    auto_collapse_focus_form: bool = False
    keep_focus_form_expanded: bool = False
    show_focus_status_grid: bool = True
    show_datetime_panel: bool = False
    show_current_date: bool = True
    show_current_time: bool = True
    show_current_seconds: bool = False
    datetime_panel_border_enabled: bool = False
    datetime_panel_transparent_background: bool = True
    datetime_panel_text_color: str = ""
    datetime_panel_text_outline_color: str = ""
    datetime_panel_text_outline_thickness: int = 0
    datetime_panel_font_family: str = ""
    datetime_panel_font_size: int = 24
    datetime_panel_background_image_path: str = ""
    datetime_panel_background_image_view: str = ""
    show_pomodoro_controls: bool = True
    show_today_timeline_inline: bool = True
    show_today_timeline_waiting_panel: bool = True
    show_today_timeline_waiting_pinned: bool = True
    show_today_checklist_inline: bool = True
    show_today_flow_panel: bool = False
    show_quick_memo_panel: bool = True
    show_link_favorites_panel: bool = True
    show_media_panel: bool = False
    media_panel_file_path: str = ""
    media_panel_image_position: str = "center"
    media_panel_image_view: str = ""
    show_media_panel_2: bool = False
    media_panel_2_file_path: str = ""
    media_panel_2_image_position: str = "center"
    media_panel_2_image_view: str = ""
    show_media_panel_3: bool = False
    media_panel_3_file_path: str = ""
    media_panel_3_image_position: str = "center"
    media_panel_3_image_view: str = ""
    show_media_panel_4: bool = False
    media_panel_4_file_path: str = ""
    media_panel_4_image_position: str = "center"
    media_panel_4_image_view: str = ""
    media_rounded_corners: bool = True
    legacy_media_panels_migrated: bool = False
    show_compact_favorites_panel: bool = False
    favorite_display_mode: str = "text"
    time_format: str = "24h"
    appearance_theme: str = "light"
    accent_color: str = "#68a8f5"
    button_color: str = "#d9e7f5"
    background_color: str = "#d9e7f5"
    inner_background_color: str = "#d9e7f5"
    panel_color: str = "#fafafa"
    table_color: str = "#fafafa"
    text_color: str = "#111315"
    focus_display_color: str = "#b9a7e8"
    focus_fade_half_minutes: int = 3
    focus_fade_white_minutes: int = 6
    focus_status_cell_shape: str = "dot"
    main_font_family: str = ""
    main_font_size: int = 13
    label_font_size: int = 13
    content_font_size: int = 13
    show_header_banner: bool = True
    header_banner_image_path: str = ""
    header_banner_image_position: str = "center"
    header_banner_image_view: str = ""
    header_banner_height: int = 132
    header_banner_position: str = "center"
    header_banner_span: int = 1
    focus_rate_display: str = "ring"
    last_window_width: int = 1280
    last_window_height: int = 820
    last_layout_state: str = ""
    quick_note_sort_direction: str = "desc"
    checklist_sort_direction: str = "desc"
    active_workspace_id: int | None = None
    id: int = 1


@dataclass(slots=True)
class LayoutProfile:
    name: str
    data: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
    is_workspace: bool = True
    display_order: int | None = None
    quick_buttons: str | None = None


@dataclass(slots=True)
class Tag:
    name: str
    id: int | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class TagLink:
    target_type: str
    target_id: int
    tag_id: int
    id: int | None = None


@dataclass(slots=True)
class ItemType:
    name: str
    base_kind: str = "task"
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
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
    color: str = ""
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
    folder_id: int | None = None
    pinned: bool = False
    process_name: str = ""
    window_title: str = ""
    deleted_at: datetime | None = None
    id: int | None = None


@dataclass(slots=True)
class QuickNoteFolder:
    name: str
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
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
    sort_order: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass(slots=True)
class ImagePanel:
    title: str = "이미지 패널"
    file_path: str = ""
    image_position: str = "center"
    image_view: str = ""
    visible: bool = True
    sort_order: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
