from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time
from pathlib import Path

import pytest

from app.models import (
    AppUsageSession,
    AvailabilityRule,
    Event,
    FocusEvent,
    FocusSession,
    ItemType,
    LinkFavorite,
    LayoutProfile,
    Preference,
    QuickNote,
    QuickNoteFolder,
    Tag,
    TagLink,
    Task,
    TrackedProgram,
)
from app.storage.database import ScheduleRepository


def test_default_app_title_is_orot(tmp_path) -> None:
    assert Preference().app_title == "오롯"

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    assert repository.get_preferences().app_title == "오롯"

    preferences = repository.get_preferences()
    preferences.app_title = "   "
    repository.save_preferences(preferences)
    assert repository.get_preferences().app_title == "오롯"

    preferences.app_title = "Focus Desk"
    repository.save_preferences(preferences)
    assert repository.get_preferences().app_title == "오롯"

    legacy_repository = ScheduleRepository(tmp_path / "legacy.sqlite3")
    with legacy_repository.connect() as connection:
        connection.execute("UPDATE preferences SET app_title = 'Focus Desk' WHERE id = 1")
    assert legacy_repository.get_preferences().app_title == "오롯"


def test_default_preference_dataclass_uses_first_run_palette() -> None:
    preferences = Preference()

    assert preferences.background_color == "#d9e7f5"
    assert preferences.accent_color == "#68a8f5"
    assert preferences.button_color == "#d9e7f5"
    assert preferences.text_color == "#111315"
    assert preferences.inner_background_color == "#d9e7f5"
    assert preferences.panel_color == "#fafafa"
    assert preferences.table_color == "#fafafa"


def test_seed_defaults_apply_first_run_palette(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    preferences = repository.get_preferences()

    assert preferences.background_color == "#d9e7f5"
    assert preferences.accent_color == "#68a8f5"
    assert preferences.button_color == "#d9e7f5"
    assert preferences.text_color == "#111315"
    assert preferences.inner_background_color == "#d9e7f5"
    assert preferences.panel_color == "#fafafa"
    assert preferences.table_color == "#fafafa"


def test_legacy_preferences_migration_applies_first_run_palette(tmp_path) -> None:
    db_path = tmp_path / "legacy_palette.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                day_max_minutes INTEGER NOT NULL,
                break_minutes INTEGER NOT NULL,
                strategy TEXT NOT NULL
            );
            INSERT INTO preferences (id, day_max_minutes, break_minutes, strategy)
            VALUES (1, 480, 10, 'deadline_priority');
            """
        )
        connection.commit()
    finally:
        connection.close()

    repository = ScheduleRepository(db_path)
    preferences = repository.get_preferences()

    assert preferences.background_color == "#d9e7f5"
    assert preferences.accent_color == "#68a8f5"
    assert preferences.button_color == "#d9e7f5"
    assert preferences.text_color == "#111315"
    assert preferences.inner_background_color == "#d9e7f5"
    assert preferences.panel_color == "#fafafa"
    assert preferences.table_color == "#fafafa"


def test_default_preferences_show_captured_dashboard_panels(tmp_path) -> None:
    defaults = Preference()

    assert defaults.show_today_checklist_inline
    assert defaults.show_media_panel_2
    assert defaults.show_header_banner
    assert defaults.show_focus_panel
    assert defaults.show_quick_memo_panel
    assert defaults.show_today_timeline_inline
    assert defaults.show_pomodoro_controls
    assert defaults.show_link_favorites_panel
    assert defaults.show_media_panel
    assert not defaults.show_datetime_panel

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()

    assert seeded.show_today_checklist_inline
    assert seeded.show_media_panel_2
    assert seeded.show_header_banner
    assert seeded.show_focus_panel
    assert seeded.show_quick_memo_panel
    assert seeded.show_today_timeline_inline
    assert seeded.show_pomodoro_controls
    assert seeded.show_link_favorites_panel
    assert seeded.show_media_panel
    assert not seeded.show_datetime_panel


def test_auto_collapse_focus_form_preference_round_trips(tmp_path) -> None:
    assert Preference().auto_collapse_focus_form is False

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()
    assert seeded.auto_collapse_focus_form is False

    seeded.auto_collapse_focus_form = True
    repository.save_preferences(seeded)

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
    assert reloaded.auto_collapse_focus_form is True


def test_keep_focus_form_expanded_preference_round_trips(tmp_path) -> None:
    assert Preference().keep_focus_form_expanded is False

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()
    assert seeded.keep_focus_form_expanded is False

    seeded.keep_focus_form_expanded = True
    repository.save_preferences(seeded)

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
    assert reloaded.keep_focus_form_expanded is True


def test_focus_status_grid_and_color_preferences_round_trip(tmp_path) -> None:
    defaults = Preference()
    assert defaults.show_focus_status_grid is True
    assert defaults.focus_display_color == "#b9a7e8"

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()
    assert seeded.show_focus_status_grid is True
    assert seeded.focus_display_color == "#b9a7e8"

    seeded.show_focus_status_grid = False
    seeded.focus_display_color = "#ff8800"
    repository.save_preferences(seeded)

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
    assert reloaded.show_focus_status_grid is False
    assert reloaded.focus_display_color == "#ff8800"


def test_focus_fade_threshold_preferences_round_trip(tmp_path) -> None:
    defaults = Preference()
    assert defaults.focus_fade_half_minutes == 3
    assert defaults.focus_fade_white_minutes == 6

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()
    assert seeded.focus_fade_half_minutes == 3
    assert seeded.focus_fade_white_minutes == 6

    seeded.focus_fade_half_minutes = 2
    seeded.focus_fade_white_minutes = 8
    repository.save_preferences(seeded)

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
    assert reloaded.focus_fade_half_minutes == 2
    assert reloaded.focus_fade_white_minutes == 8


def test_focus_status_cell_shape_preference_round_trip(tmp_path) -> None:
    defaults = Preference()
    assert defaults.focus_status_cell_shape == "dot"

    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()
    assert seeded.focus_status_cell_shape == "dot"

    seeded.focus_status_cell_shape = "heart"
    repository.save_preferences(seeded)

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
    assert reloaded.focus_status_cell_shape == "heart"


def test_focus_status_cell_shape_preference_supports_all_shapes(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    for shape in ("dot", "heart", "wave", "line"):
        seeded = repository.get_preferences()
        seeded.focus_status_cell_shape = shape
        repository.save_preferences(seeded)
        reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
        assert reloaded.focus_status_cell_shape == shape


def test_focus_status_cell_shape_preference_normalizes_unknown(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    seeded = repository.get_preferences()
    seeded.focus_status_cell_shape = "triangle"
    repository.save_preferences(seeded)

    reloaded = ScheduleRepository(tmp_path / "schedule.sqlite3").get_preferences()
    assert reloaded.focus_status_cell_shape == "dot"


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


def test_repository_migrates_metadata_schema_without_data_loss(tmp_path) -> None:
    db_path = tmp_path / "legacy_metadata.sqlite3"
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
            CREATE TABLE quick_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                content_html TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                focus_session_id INTEGER,
                task_id INTEGER,
                process_name TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                day_max_minutes INTEGER NOT NULL,
                break_minutes INTEGER NOT NULL,
                strategy TEXT NOT NULL
            );
            INSERT INTO tasks (title, duration_minutes, priority, created_at)
            VALUES ('legacy task', 20, 3, '2026-06-08T09:00:00');
            INSERT INTO events (title, start_at, end_at)
            VALUES ('legacy event', '2026-06-08T10:00:00', '2026-06-08T10:30:00');
            INSERT INTO quick_notes (body, content_html, created_at, process_name)
            VALUES ('legacy note', '', '2026-06-08T12:00:00', '');
            INSERT INTO preferences (id, day_max_minutes, break_minutes, strategy)
            VALUES (1, 480, 10, 'deadline_priority');
            """
        )
        connection.commit()
    finally:
        connection.close()

    repository = ScheduleRepository(db_path)

    task = repository.list_tasks()[0]
    event = repository.list_events(include_completed=True)[0]
    note = repository.list_quick_notes()[0]
    preferences = repository.get_preferences()
    assert task.title == "legacy task"
    assert event.title == "legacy event"
    assert note.body == "legacy note"
    assert task.pinned is False
    assert event.pinned is False
    assert note.pinned is False
    assert preferences.quick_note_sort_direction == "desc"
    assert preferences.checklist_sort_direction == "desc"
    assert preferences.active_workspace_id is None

    with repository.connect() as migrated:
        task_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(tasks)")}
        event_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(events)")}
        note_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(quick_notes)")}
        preference_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(preferences)")}
        tag_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(tags)")}
        tag_link_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(tag_links)")}

    assert "pinned" in task_columns
    assert "pinned" in event_columns
    assert "pinned" in note_columns
    assert {"quick_note_sort_direction", "checklist_sort_direction", "active_workspace_id"} <= preference_columns
    assert {"id", "name", "created_at"} <= tag_columns
    assert {"id", "target_type", "target_id", "tag_id"} <= tag_link_columns


def test_repository_round_trips_pinned_items(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)

    task = repository.save_task(Task("Default pin task", 15))
    event = repository.save_event(Event("Default pin event", datetime(2026, 6, 9, 9, 0), datetime(2026, 6, 9, 9, 30)))
    note = repository.save_quick_note(QuickNote(body="default pin note", created_at=datetime(2026, 6, 9, 10, 0)))

    reloaded = ScheduleRepository(db_path)
    assert reloaded.get_task(task.id).pinned is False
    assert reloaded.get_event(event.id).pinned is False
    assert reloaded.get_quick_note(note.id).pinned is False

    task.pinned = True
    event.pinned = True
    note.pinned = True
    repository.save_task(task)
    repository.save_event(event)
    repository.save_quick_note(note)

    reloaded = ScheduleRepository(db_path)
    assert reloaded.get_task(task.id).pinned is True
    assert reloaded.get_event(event.id).pinned is True
    assert reloaded.get_quick_note(note.id).pinned is True


def test_repository_persists_sort_directions_and_active_workspace(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    profile = repository.save_layout_profile(LayoutProfile(name="Project", data='{"layout": "focus"}'))

    preferences = repository.get_preferences()
    preferences.quick_note_sort_direction = "asc"
    preferences.checklist_sort_direction = "asc"
    preferences.active_workspace_id = profile.id
    repository.save_preferences(preferences)

    reloaded = ScheduleRepository(db_path)
    saved_preferences = reloaded.get_preferences()
    assert saved_preferences.quick_note_sort_direction == "asc"
    assert saved_preferences.checklist_sort_direction == "asc"
    assert saved_preferences.active_workspace_id == profile.id

    saved_preferences.active_workspace_id = None
    reloaded.save_preferences(saved_preferences)
    assert ScheduleRepository(db_path).get_preferences().active_workspace_id is None

    missing_profile_preferences = ScheduleRepository(db_path).get_preferences()
    missing_profile_preferences.active_workspace_id = 999_999
    ScheduleRepository(db_path).save_preferences(missing_profile_preferences)
    assert ScheduleRepository(db_path).get_preferences().active_workspace_id == 999_999


def test_tags_are_case_insensitively_unique_and_trimmed(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    tag = Tag(" Focus ")

    with repository.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO tags (name, created_at) VALUES (?, ?)",
            (tag.name.strip(), tag.created_at.isoformat()),
        )
        tag.id = int(cursor.lastrowid)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO tags (name, created_at) VALUES (?, ?)",
                ("focus", datetime(2026, 6, 9, 11, 0).isoformat()),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO tags (name, created_at) VALUES (?, ?)",
                (" spaced ", datetime(2026, 6, 9, 11, 5).isoformat()),
            )

    assert tag.id is not None
    with repository.connect() as connection:
        row = connection.execute("SELECT name FROM tags WHERE id = ?", (tag.id,)).fetchone()
    assert row["name"] == "Focus"


def test_tag_links_survive_reload_and_reject_duplicates(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    task = repository.save_task(Task("Tagged task", 25))

    with repository.connect() as connection:
        tag_id = int(
            connection.execute(
                "INSERT INTO tags (name, created_at) VALUES (?, ?)",
                ("Planning", datetime(2026, 6, 9, 11, 0).isoformat()),
            ).lastrowid
        )
        tag_link = TagLink("task", int(task.id), tag_id)
        tag_link.id = int(
            connection.execute(
                "INSERT INTO tag_links (target_type, target_id, tag_id) VALUES (?, ?, ?)",
                (tag_link.target_type, tag_link.target_id, tag_link.tag_id),
            ).lastrowid
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO tag_links (target_type, target_id, tag_id) VALUES (?, ?, ?)",
                (tag_link.target_type, tag_link.target_id, tag_link.tag_id),
            )

    with ScheduleRepository(db_path).connect() as connection:
        row = connection.execute("SELECT * FROM tag_links WHERE id = ?", (tag_link.id,)).fetchone()
    assert row["target_type"] == "task"
    assert row["target_id"] == task.id
    assert row["tag_id"] == tag_id


def test_deleting_tag_unlinks_assignments_and_preserves_targets(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("Keep target", 25))

    with repository.connect() as connection:
        tag_id = int(
            connection.execute(
                "INSERT INTO tags (name, created_at) VALUES (?, ?)",
                ("Archive", datetime(2026, 6, 9, 11, 0).isoformat()),
            ).lastrowid
        )
        connection.execute(
            "INSERT INTO tag_links (target_type, target_id, tag_id) VALUES (?, ?, ?)",
            ("task", task.id, tag_id),
        )
        connection.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    assert repository.get_task(task.id).title == "Keep target"
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tag_links").fetchone()[0] == 0


def test_workspace_filter_payload_round_trips_in_layout_profile_data(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    filters = {
        "memo.folder_id": 7,
        "memo.tag_ids": [1, 3, 5],
        "checklist.item_type_ids": [2, 4],
        "checklist.tag_ids": [6, 8],
        "checklist.show_completed": False,
    }
    profile_data = json.dumps({"workspace_filters": filters}, ensure_ascii=False, sort_keys=True)

    saved = repository.save_layout_profile(LayoutProfile(name="Filtered workspace", data=profile_data))

    reloaded = ScheduleRepository(db_path).get_layout_profile("Filtered workspace")
    assert saved.id is not None
    assert reloaded is not None
    assert json.loads(reloaded.data)["workspace_filters"] == filters


def test_repository_workspace_profile_apis_and_filter_normalization(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    first = repository.save_layout_profile(LayoutProfile(name="First", data='{"layout":"first"}'))
    second = repository.save_layout_profile(LayoutProfile(name="Second", data='{"layout":"second"}'))
    with repository.connect() as connection:
        connection.execute(
            "UPDATE layout_profiles SET updated_at = ? WHERE id = ?",
            (datetime(2026, 6, 8, 12, 0).isoformat(), first.id),
        )
        connection.execute(
            "UPDATE layout_profiles SET updated_at = ? WHERE id = ?",
            (datetime(2026, 6, 8, 12, 1).isoformat(), second.id),
        )

    assert [profile.id for profile in repository.list_workspace_profiles()] == [second.id, first.id]
    assert repository.get_active_workspace() is None

    repository.set_active_workspace(first.id)
    active = repository.get_active_workspace()

    assert active is not None
    assert active.id == first.id

    repository.clear_active_workspace()
    assert repository.get_active_workspace() is None

    repository.set_active_workspace(999_999)
    assert repository.get_preferences().active_workspace_id == 999_999
    assert repository.get_active_workspace() is None

    filters = repository.normalize_workspace_filters(
        {
            "workspace_filters": {
                "memo.folder_id": 7,
                "memo.tag_ids": [1, 3, 5],
                "checklist.item_type_ids": [2, 4],
                "checklist.tag_ids": [6, 8],
                "checklist.show_completed": False,
                "ignored": True,
            }
        }
    )

    assert filters == {
        "memo.folder_id": 7,
        "memo.tag_ids": [1, 3, 5],
        "checklist.item_type_ids": [2, 4],
        "checklist.tag_ids": [6, 8],
        "checklist.show_completed": False,
    }
    assert repository.normalize_workspace_filters({}) == {
        "memo.folder_id": None,
        "memo.tag_ids": [],
        "checklist.item_type_ids": [],
        "checklist.tag_ids": [],
        "checklist.show_completed": True,
    }


def test_repository_tag_apis_manage_names_links_and_deletion(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("Tagged task", 25))
    event = repository.save_event(Event("Tagged event", datetime(2026, 6, 8, 9, 0), datetime(2026, 6, 8, 9, 30)))
    note = repository.save_quick_note(QuickNote(body="tagged note", created_at=datetime(2026, 6, 8, 10, 0)))

    focus = repository.create_tag(" Focus ")
    planning = repository.create_tag("Planning")

    assert isinstance(focus, Tag)
    assert focus.name == "Focus"
    assert [tag.name for tag in repository.list_tags()] == ["Focus", "Planning"]
    assert repository.get_tag(focus.id).name == "Focus"
    with pytest.raises(ValueError):
        repository.create_tag("focus")
    with pytest.raises(ValueError):
        repository.create_tag("   ")

    renamed = repository.rename_tag(planning.id, " Plan ")

    assert renamed is not None
    assert renamed.name == "Plan"
    with pytest.raises(ValueError):
        repository.rename_tag(renamed.id, "FOCUS")

    repository.add_tag_to_target("task", task.id, focus.id)
    repository.add_tag_to_target("task", task.id, focus.id)
    repository.set_tags_for_target("event", event.id, [focus.id, renamed.id, focus.id])
    repository.add_tag_to_target("quick_note", note.id, renamed.id)

    assert [tag.name for tag in repository.list_tags_for_target("task", task.id)] == ["Focus"]
    assert [tag.name for tag in repository.list_tags_for_target("event", event.id)] == ["Focus", "Plan"]
    assert [tag.name for tag in repository.list_tags_for_target("quick_note", note.id)] == ["Plan"]

    repository.remove_tag_from_target("quick_note", note.id, renamed.id)
    repository.remove_tag_from_target("quick_note", note.id, renamed.id)

    assert repository.list_tags_for_target("quick_note", note.id) == []

    repository.delete_tag(focus.id)

    assert repository.get_tag(focus.id) is None
    assert repository.get_task(task.id).title == "Tagged task"
    assert repository.get_event(event.id).title == "Tagged event"
    assert repository.get_quick_note(note.id).body == "tagged note"
    assert [tag.name for tag in repository.list_tags_for_target("event", event.id)] == ["Plan"]


def test_repository_tag_target_validation_rejects_without_mutation(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    task = repository.save_task(Task("Stable tag target", 25))
    tag = repository.create_tag("Stable")
    repository.add_tag_to_target("task", task.id, tag.id)

    with pytest.raises(ValueError):
        repository.list_tags_for_target("unknown", task.id)
    with pytest.raises(ValueError):
        repository.set_tags_for_target("unknown", task.id, [tag.id])
    with pytest.raises(ValueError):
        repository.set_tags_for_target("task", 999_999, [tag.id])
    with pytest.raises(ValueError):
        repository.set_tags_for_target("task", task.id, [999_999])
    with pytest.raises(ValueError):
        repository.add_tag_to_target("event", 999_999, tag.id)
    with pytest.raises(ValueError):
        repository.remove_tag_from_target("quick_note", 999_999, tag.id)

    assert [tag.id for tag in repository.list_tags_for_target("task", task.id)] == [tag.id]


def test_repository_lists_tasks_sorted_with_pins_and_completed_times(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    due = repository.save_task(
        Task("due", 15, due_at=datetime(2026, 6, 8, 8, 0), created_at=datetime(2026, 6, 8, 12, 0))
    )
    created = repository.save_task(Task("created", 15, created_at=datetime(2026, 6, 8, 9, 0)))
    pinned_early = repository.save_task(
        Task("pinned early", 15, due_at=datetime(2026, 6, 8, 10, 0), created_at=datetime(2026, 6, 8, 10, 0))
    )
    pinned_late = repository.save_task(
        Task("pinned late", 15, due_at=datetime(2026, 6, 8, 11, 0), created_at=datetime(2026, 6, 8, 11, 0))
    )
    repository.save_task(
        Task(
            "completed",
            15,
            due_at=datetime(2026, 6, 8, 7, 0),
            completed=True,
            completed_at=datetime(2026, 6, 8, 13, 0),
            created_at=datetime(2026, 6, 8, 7, 0),
        )
    )

    assert repository.set_pinned_task(pinned_early.id, True)
    assert repository.set_pinned_task(pinned_late.id, True)
    assert not repository.set_pinned_task(999_999, True)

    assert [task.title for task in repository.list_tasks_sorted("asc", include_completed=False)] == [
        "pinned early",
        "pinned late",
        "due",
        "created",
    ]
    assert [task.title for task in repository.list_tasks_sorted("desc", include_completed=True)] == [
        "pinned late",
        "pinned early",
        "completed",
        "created",
        "due",
    ]
    assert repository.get_task(pinned_early.id).pinned is True
    assert repository.get_task(due.id).pinned is False


def test_repository_lists_events_sorted_with_pins_range_and_completed_times(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    window_start = datetime(2026, 6, 8, 8, 0)
    window_end = datetime(2026, 6, 8, 14, 0)
    open_event = repository.save_event(
        Event("open", datetime(2026, 6, 8, 9, 0), datetime(2026, 6, 8, 9, 30))
    )
    pinned_early = repository.save_event(
        Event("pinned early", datetime(2026, 6, 8, 10, 0), datetime(2026, 6, 8, 10, 30))
    )
    pinned_late = repository.save_event(
        Event("pinned late", datetime(2026, 6, 8, 11, 0), datetime(2026, 6, 8, 11, 30))
    )
    repository.save_event(
        Event(
            "completed",
            datetime(2026, 6, 8, 8, 30),
            datetime(2026, 6, 8, 8, 45),
            completed=True,
            completed_at=datetime(2026, 6, 8, 13, 0),
        )
    )
    repository.save_event(Event("outside", datetime(2026, 6, 9, 9, 0), datetime(2026, 6, 9, 9, 30)))

    assert repository.set_pinned_event(pinned_early.id, True)
    assert repository.set_pinned_event(pinned_late.id, True)
    assert not repository.set_pinned_event(999_999, True)

    assert [event.title for event in repository.list_events_sorted("asc", window_start, window_end, False)] == [
        "pinned early",
        "pinned late",
        "open",
    ]
    assert [event.title for event in repository.list_events_sorted("desc", window_start, window_end, True)] == [
        "pinned late",
        "pinned early",
        "completed",
        "open",
    ]
    assert repository.get_event(pinned_early.id).pinned is True
    assert repository.get_event(open_event.id).pinned is False


def test_repository_lists_quick_notes_sorted_with_pins_before_limit(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    folder = repository.save_quick_note_folder(QuickNoteFolder(name="Sorted notes"))
    repository.save_quick_note(
        QuickNote(body="unpinned old", created_at=datetime(2026, 6, 8, 12, 0), folder_id=folder.id)
    )
    pinned_old = repository.save_quick_note(
        QuickNote(body="pinned old", created_at=datetime(2026, 6, 8, 12, 1), folder_id=folder.id)
    )
    pinned_new = repository.save_quick_note(
        QuickNote(body="pinned new", created_at=datetime(2026, 6, 8, 12, 2), folder_id=folder.id)
    )
    repository.save_quick_note(
        QuickNote(body="unpinned new", created_at=datetime(2026, 6, 8, 12, 3), folder_id=folder.id)
    )
    deleted = repository.save_quick_note(
        QuickNote(
            body="deleted pinned",
            created_at=datetime(2026, 6, 8, 12, 4),
            folder_id=folder.id,
            deleted_at=datetime(2026, 6, 8, 13, 0),
        )
    )
    repository.save_quick_note(QuickNote(body="other folder pinned", created_at=datetime(2026, 6, 8, 12, 5)))

    assert repository.set_pinned_note(pinned_old.id, True)
    assert repository.set_pinned_note(pinned_new.id, True)
    assert repository.set_pinned_note(deleted.id, True)
    assert not repository.set_pinned_note(999_999, True)

    assert [note.body for note in repository.list_quick_notes_sorted("asc", 2, folder.id, None, False)] == [
        "pinned old",
        "pinned new",
    ]
    assert [note.body for note in repository.list_quick_notes_sorted("desc", 2, folder.id, None, False)] == [
        "pinned new",
        "pinned old",
    ]
    assert [note.body for note in repository.list_quick_notes_sorted("desc", 1, folder.id, None, True)] == ["deleted pinned"]
    assert repository.get_quick_note(pinned_old.id).pinned is True


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


def test_repository_moves_tasks_between_item_types(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    source_type = repository.save_item_type(ItemType("Source", "task"))
    target_type = repository.save_item_type(ItemType("Target", "task"))
    first = repository.save_task(Task("First", 0, item_type_id=source_type.id))
    second = repository.save_task(Task("Second", 0, item_type_id=source_type.id))

    moved = repository.move_tasks_to_type([first.id, second.id], target_type.id)

    assert moved == 2
    assert repository.get_task(first.id).item_type_id == target_type.id
    assert repository.get_task(second.id).item_type_id == target_type.id


def test_repository_reuses_focus_session_color_by_title(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    first = repository.save_focus_session(
        FocusSession("Deep work", 1500, started_at=datetime(2026, 6, 8, 9, 0))
    )

    assert first.color.startswith("#")
    assert repository.set_focus_session_color(first.id, "#123456")

    second = repository.save_focus_session(
        FocusSession("Deep work", 1500, started_at=datetime(2026, 6, 8, 10, 0))
    )

    assert second.color == "#123456"


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

    completed_at = datetime(2026, 6, 10, 8, 45)
    repository.update_task_completed_at(task.id, completed_at)
    updated = repository.get_task(task.id)
    assert updated.completed
    assert updated.completed_at == completed_at


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

    completed_at = datetime(2026, 6, 11, 19, 30)
    repository.update_event_completed_at(event.id, completed_at)
    updated = repository.get_event(event.id)
    assert updated.completed
    assert updated.completed_at == completed_at


def test_repository_marks_today_checklist_items_completed_with_timestamps(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    open_task = repository.save_task(Task("Open task", 15, created_at=datetime(2026, 6, 8, 8, 0)))
    completed_task = repository.save_task(Task("Done task", 25, created_at=datetime(2026, 6, 8, 9, 0)))
    open_event = repository.save_event(
        Event(
            "Open event",
            datetime(2026, 6, 8, 10, 0),
            datetime(2026, 6, 8, 10, 30),
        )
    )
    completed_event = repository.save_event(
        Event(
            "Done event",
            datetime(2026, 6, 8, 11, 0),
            datetime(2026, 6, 8, 11, 30),
        )
    )

    repository.mark_task_completed(completed_task.id, True)
    repository.mark_event_completed(completed_event.id, True)

    reloaded = ScheduleRepository(db_path)
    completed_tasks = reloaded.list_completed_tasks()
    completed_events = reloaded.list_completed_events()

    assert [task.id for task in completed_tasks] == [completed_task.id]
    assert completed_tasks[0].completed
    assert completed_tasks[0].completed_at is not None
    assert reloaded.get_task(completed_task.id).completed_at == completed_tasks[0].completed_at
    assert reloaded.get_task(open_task.id).completed_at is None
    assert [event.id for event in completed_events] == [completed_event.id]
    assert completed_events[0].completed
    assert completed_events[0].completed_at is not None
    assert reloaded.get_event(completed_event.id).completed_at == completed_events[0].completed_at
    assert reloaded.get_event(open_event.id).completed_at is None


def test_repository_manages_availability_and_preferences(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    repository.reset_default_availability()
    repository.save_availability_rule(AvailabilityRule(5, time(10), time(12)))

    rules = repository.list_availability_rules()
    assert any(rule.weekday == 5 and rule.start_time == time(10) for rule in rules)

    preferences = repository.get_preferences()
    preferences.break_minutes = 20
    preferences.week_start_day = 6
    preferences.app_title = "My Desk"
    preferences.main_always_on_top = True
    preferences.show_focus_panel = False
    preferences.show_datetime_panel = False
    preferences.show_current_date = False
    preferences.show_current_time = True
    preferences.show_current_seconds = True
    preferences.datetime_panel_border_enabled = True
    preferences.datetime_panel_transparent_background = False
    preferences.datetime_panel_text_color = "#abcdef"
    preferences.datetime_panel_text_outline_color = "#00ff00"
    preferences.datetime_panel_text_outline_thickness = 4
    preferences.datetime_panel_font_family = "Arial"
    preferences.datetime_panel_font_size = 36
    preferences.datetime_panel_background_image_path = "C:/Images/time.png"
    preferences.datetime_panel_background_image_view = '{"zoom":75,"x":20,"y":80}'
    preferences.show_pomodoro_controls = False
    preferences.show_today_timeline_inline = True
    preferences.show_today_timeline_waiting_panel = False
    preferences.show_today_timeline_waiting_pinned = False
    preferences.show_today_checklist_inline = True
    preferences.show_today_flow_panel = False
    preferences.show_quick_memo_panel = False
    preferences.show_link_favorites_panel = False
    preferences.show_media_panel = False
    preferences.media_panel_file_path = "C:/Images/reference.gif"
    preferences.media_panel_image_position = "right"
    preferences.media_panel_image_view = '{"zoom":50,"x":80,"y":40}'
    preferences.show_media_panel_2 = True
    preferences.media_panel_2_file_path = "C:/Images/reference-2.gif"
    preferences.media_panel_2_image_position = "left"
    preferences.media_panel_2_image_view = '{"zoom":120,"x":15,"y":50}'
    preferences.show_media_panel_3 = True
    preferences.media_panel_3_file_path = "C:/Images/reference-3.gif"
    preferences.media_panel_3_image_position = "top"
    preferences.media_panel_3_image_view = '{"zoom":200,"x":50,"y":0}'
    preferences.show_media_panel_4 = False
    preferences.media_panel_4_file_path = "C:/Images/reference-4.gif"
    preferences.media_panel_4_image_position = "bottom"
    preferences.media_panel_4_image_view = '{"zoom":220,"x":50,"y":100}'
    preferences.media_rounded_corners = False
    preferences.show_compact_favorites_panel = True
    preferences.favorite_display_mode = "icon_only"
    preferences.time_format = "12h"
    preferences.appearance_theme = "dark"
    preferences.accent_color = "#ff3366"
    preferences.button_color = "#33aa77"
    preferences.background_color = "#112233"
    preferences.inner_background_color = "#223344"
    preferences.panel_color = "#334455"
    preferences.table_color = "#445566"
    preferences.text_color = "#f8f9fa"
    preferences.main_font_family = "Arial"
    preferences.main_font_size = 16
    preferences.label_font_size = 15
    preferences.content_font_size = 18
    preferences.show_header_banner = True
    preferences.header_banner_image_path = "C:/Images/banner.png"
    preferences.header_banner_image_position = "left"
    preferences.header_banner_image_view = '{"zoom":170,"x":0,"y":45}'
    preferences.header_banner_height = 220
    preferences.header_banner_position = "right"
    preferences.header_banner_span = 3
    preferences.focus_rate_display = "bar"
    preferences.last_window_width = 1440
    preferences.last_window_height = 900
    preferences.last_layout_state = '{"splitters":{"body":[300,700]}}'
    repository.save_preferences(preferences)

    reloaded_preferences = repository.get_preferences()
    assert reloaded_preferences.break_minutes == 20
    assert reloaded_preferences.week_start_day == 6
    assert reloaded_preferences.app_title == "My Desk"
    assert reloaded_preferences.main_always_on_top
    assert not reloaded_preferences.show_focus_panel
    assert not reloaded_preferences.show_datetime_panel
    assert not reloaded_preferences.show_current_date
    assert reloaded_preferences.show_current_time
    assert reloaded_preferences.show_current_seconds
    assert reloaded_preferences.datetime_panel_border_enabled
    assert not reloaded_preferences.datetime_panel_transparent_background
    assert reloaded_preferences.datetime_panel_text_color == "#abcdef"
    assert reloaded_preferences.datetime_panel_text_outline_color == "#00ff00"
    assert reloaded_preferences.datetime_panel_text_outline_thickness == 4
    assert reloaded_preferences.datetime_panel_font_family == "Arial"
    assert reloaded_preferences.datetime_panel_font_size == 36
    assert reloaded_preferences.datetime_panel_background_image_path == "C:/Images/time.png"
    assert reloaded_preferences.datetime_panel_background_image_view == '{"zoom":75,"x":20,"y":80}'
    assert not reloaded_preferences.show_pomodoro_controls
    assert reloaded_preferences.show_today_timeline_inline
    assert not reloaded_preferences.show_today_timeline_waiting_panel
    assert not reloaded_preferences.show_today_timeline_waiting_pinned
    assert reloaded_preferences.show_today_checklist_inline
    assert not reloaded_preferences.show_today_flow_panel
    assert not reloaded_preferences.show_quick_memo_panel
    assert not reloaded_preferences.show_link_favorites_panel
    assert not reloaded_preferences.show_media_panel
    assert reloaded_preferences.media_panel_file_path == "C:/Images/reference.gif"
    assert reloaded_preferences.media_panel_image_position == "right"
    assert reloaded_preferences.media_panel_image_view == '{"zoom":50,"x":80,"y":40}'
    assert reloaded_preferences.show_media_panel_2
    assert reloaded_preferences.media_panel_2_file_path == "C:/Images/reference-2.gif"
    assert reloaded_preferences.media_panel_2_image_position == "left"
    assert reloaded_preferences.media_panel_2_image_view == '{"zoom":120,"x":15,"y":50}'
    assert reloaded_preferences.show_media_panel_3
    assert reloaded_preferences.media_panel_3_file_path == "C:/Images/reference-3.gif"
    assert reloaded_preferences.media_panel_3_image_position == "top"
    assert reloaded_preferences.media_panel_3_image_view == '{"zoom":200,"x":50,"y":0}'
    assert not reloaded_preferences.show_media_panel_4
    assert reloaded_preferences.media_panel_4_file_path == "C:/Images/reference-4.gif"
    assert reloaded_preferences.media_panel_4_image_position == "bottom"
    assert reloaded_preferences.media_panel_4_image_view == '{"zoom":220,"x":50,"y":100}'
    assert not reloaded_preferences.media_rounded_corners
    assert reloaded_preferences.show_compact_favorites_panel
    assert reloaded_preferences.favorite_display_mode == "icon_only"
    assert reloaded_preferences.time_format == "12h"
    assert reloaded_preferences.appearance_theme == "dark"
    assert reloaded_preferences.accent_color == "#ff3366"
    assert reloaded_preferences.button_color == "#33aa77"
    assert reloaded_preferences.background_color == "#112233"
    assert reloaded_preferences.inner_background_color == "#223344"
    assert reloaded_preferences.panel_color == "#334455"
    assert reloaded_preferences.table_color == "#445566"
    assert reloaded_preferences.text_color == "#f8f9fa"
    assert reloaded_preferences.main_font_family == "Arial"
    assert reloaded_preferences.main_font_size == 16
    assert reloaded_preferences.label_font_size == 15
    assert reloaded_preferences.content_font_size == 18
    assert reloaded_preferences.show_header_banner
    assert reloaded_preferences.header_banner_image_path == "C:/Images/banner.png"
    assert reloaded_preferences.header_banner_image_position == "left"
    assert reloaded_preferences.header_banner_image_view == '{"zoom":170,"x":0,"y":45}'
    assert reloaded_preferences.header_banner_height == 220
    assert reloaded_preferences.header_banner_position == "right"
    assert reloaded_preferences.header_banner_span == 3
    assert reloaded_preferences.focus_rate_display == "bar"
    assert reloaded_preferences.last_window_width == 1440
    assert reloaded_preferences.last_window_height == 900
    assert reloaded_preferences.last_layout_state == '{"splitters":{"body":[300,700]}}'


def test_repository_round_trips_last_layout_state_across_reloads(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    preferences = repository.get_preferences()
    preferences.last_layout_state = '{"splitters":{"main":[240,560],"side":[120,320]},"panels":["today","memo"]}'

    repository.save_preferences(preferences)

    assert ScheduleRepository(db_path).get_preferences().last_layout_state == preferences.last_layout_state


def test_repository_normalizes_datetime_text_outline(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")

    defaults = repository.get_preferences()
    assert defaults.datetime_panel_text_outline_color == ""
    assert defaults.datetime_panel_text_outline_thickness == 0

    invalid = repository.get_preferences()
    invalid.datetime_panel_text_outline_color = "not-a-color"
    invalid.datetime_panel_text_outline_thickness = 99
    repository.save_preferences(invalid)
    reloaded_invalid = repository.get_preferences()
    assert reloaded_invalid.datetime_panel_text_outline_color == ""
    assert reloaded_invalid.datetime_panel_text_outline_thickness == 12

    edge = repository.get_preferences()
    edge.datetime_panel_text_outline_color = "#ABCDEF"
    edge.datetime_panel_text_outline_thickness = -5
    repository.save_preferences(edge)
    reloaded_edge = repository.get_preferences()
    assert reloaded_edge.datetime_panel_text_outline_color == "#abcdef"
    assert reloaded_edge.datetime_panel_text_outline_thickness == 0


def test_repository_copies_media_assets_next_to_database(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    source = tmp_path / "source image.png"
    source.write_bytes(b"image-bytes")

    stored_path = Path(repository.copy_media_asset(source))

    assert stored_path.parent == tmp_path / "media"
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"image-bytes"
    assert repository.copy_media_asset(stored_path) == str(stored_path)


def test_repository_saves_named_layout_profiles(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    profile = repository.save_layout_profile(LayoutProfile(name="작업 배치", data='{"body":[700,300]}'))
    secondary_profile = repository.save_layout_profile(LayoutProfile(name="보조 배치", data='{"body":[300,700]}'))

    assert profile.id is not None
    assert repository.get_layout_profile("작업 배치").data == '{"body":[700,300]}'

    repository.save_layout_profile(LayoutProfile(name="작업 배치", data='{"body":[600,400]}'))
    with repository.connect() as connection:
        connection.execute(
            "UPDATE layout_profiles SET updated_at = ? WHERE id = ?",
            (datetime(2026, 6, 8, 12, 1).isoformat(), profile.id),
        )
        connection.execute(
            "UPDATE layout_profiles SET updated_at = ? WHERE id = ?",
            (datetime(2026, 6, 8, 12, 0).isoformat(), secondary_profile.id),
        )
    profiles = repository.list_layout_profiles()

    assert len(profiles) == 2
    assert profiles[0].name == "작업 배치"
    assert profiles[0].data == '{"body":[600,400]}'
    assert profiles[1].name == "보조 배치"
    assert profiles[1].id == secondary_profile.id

    original_timestamp = datetime(2026, 6, 8, 12, 1)
    with repository.connect() as connection:
        connection.execute(
            "UPDATE layout_profiles SET updated_at = ? WHERE id = ?",
            (original_timestamp.isoformat(), profile.id),
        )

    updated_profile = repository.update_layout_profile_data(profile.id, '{"body":[500,500]}')

    assert updated_profile is not None
    assert updated_profile.id == profile.id
    assert updated_profile.name == "작업 배치"
    assert updated_profile.data == '{"body":[500,500]}'
    assert updated_profile.updated_at >= original_timestamp

    renamed_profile = repository.rename_layout_profile(profile.id, "  집중 배치  ")

    assert renamed_profile is not None
    assert renamed_profile.id == profile.id
    assert renamed_profile.name == "집중 배치"
    assert renamed_profile.data == '{"body":[500,500]}'
    assert renamed_profile.updated_at >= updated_profile.updated_at
    assert repository.update_layout_profile_data(999_999, "{}") is None
    assert repository.rename_layout_profile(999_999, "없는 배치") is None
    with pytest.raises(ValueError):
        repository.rename_layout_profile(profile.id, "   ")

    saved_profile = repository.get_layout_profile("집중 배치")
    assert saved_profile is not None
    repository.delete_layout_profile(saved_profile.id)

    assert repository.get_layout_profile("집중 배치") is None
    assert [item.name for item in repository.list_layout_profiles()] == ["보조 배치"]


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
    assert repository.list_deleted_quick_notes()[0].id == note.id

    repository.restore_quick_note(note.id)

    assert repository.list_quick_notes()[0].id == note.id
    assert repository.list_deleted_quick_notes() == []


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


def test_repository_lists_all_quick_notes_newest_first_unless_limited(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    for index in range(6):
        repository.save_quick_note(
            QuickNote(
                body=f"note-{index}",
                created_at=datetime(2026, 6, 8, 12, index),
            )
        )
    repository.save_quick_note(QuickNote(body="tie-first", created_at=datetime(2026, 6, 8, 12, 6)))
    repository.save_quick_note(QuickNote(body="tie-second", created_at=datetime(2026, 6, 8, 12, 6)))

    all_notes = repository.list_quick_notes()

    assert [note.body for note in all_notes] == [
        "tie-second",
        "tie-first",
        "note-5",
        "note-4",
        "note-3",
        "note-2",
        "note-1",
        "note-0",
    ]
    assert [note.body for note in repository.list_quick_notes(limit=3)] == ["tie-second", "tie-first", "note-5"]


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
    assert note.deleted_at is None
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

    assert repository.list_quick_note_attachments(note.id)[0].id == attachment.id
    assert any(copied_path.glob("*"))

    repository.delete_quick_note_permanently(note.id)

    assert repository.list_quick_note_attachments(note.id) == []
    assert not any(copied_path.glob("*"))


def test_repository_purges_expired_deleted_quick_notes(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    old_note = repository.save_quick_note(QuickNote(body="old", created_at=datetime(2026, 6, 1, 12, 0)))
    fresh_note = repository.save_quick_note(QuickNote(body="fresh", created_at=datetime(2026, 6, 8, 12, 0)))
    old_note.deleted_at = datetime(2026, 6, 1, 12, 0)
    fresh_note.deleted_at = datetime(2026, 6, 7, 12, 0)
    repository.save_quick_note(old_note)
    repository.save_quick_note(fresh_note)

    purged = repository.purge_expired_quick_notes(datetime(2026, 6, 9, 12, 0))

    assert purged == 1
    assert repository.get_quick_note_any(old_note.id) is None
    assert repository.get_quick_note_any(fresh_note.id).id == fresh_note.id


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

    second = repository.save_link_favorite(LinkFavorite(title="Second", target="https://second.example"))
    third = repository.save_link_favorite(LinkFavorite(title="Third", target="https://third.example"))
    assert [item.title for item in repository.list_link_favorites()] == ["Reference", "Second", "Third"]
    repository.reorder_link_favorites([int(third.id), int(favorite.id), int(second.id)])
    assert [item.title for item in repository.list_link_favorites()] == ["Third", "Reference", "Second"]

    favorite.icon_path = repository.save_link_favorite_icon_bytes(favorite.id, "site-icon.png", b"site icon")
    repository.save_link_favorite(favorite)
    site_icon_path = tmp_path / "favorite_icons" / str(favorite.id)
    assert Path(favorite.icon_path).read_bytes() == b"site icon"
    assert any(path.name.endswith("_site-icon.png") for path in site_icon_path.iterdir())

    repository.delete_link_favorite(favorite.id)
    repository.delete_link_favorite(second.id)
    repository.delete_link_favorite(third.id)

    assert repository.list_link_favorites() == []


def test_list_user_workspace_profiles_filters_and_orders(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    first = repository.save_layout_profile(LayoutProfile(name="First", data='{"layout":"first"}'))
    second = repository.save_layout_profile(LayoutProfile(name="Second", data='{"layout":"second"}'))
    third = repository.save_layout_profile(LayoutProfile(name="Third", data='{"layout":"third"}'))

    with repository.connect() as connection:
        connection.execute(
            "UPDATE layout_profiles SET is_workspace = 0 WHERE id = ?",
            (second.id,),
        )

    listed = repository.list_user_workspace_profiles()
    assert [profile.id for profile in listed] == [first.id, third.id]
    assert all(profile.is_workspace for profile in listed)
    assert [profile.display_order for profile in listed] == [1, 3]

    repository.set_workspace_order([third.id, first.id])
    reordered = repository.list_user_workspace_profiles()
    assert [profile.id for profile in reordered] == [third.id, first.id]
    assert [profile.display_order for profile in reordered] == [1, 2]


def test_set_workspace_order_persists_and_reorders(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    alpha = repository.save_layout_profile(LayoutProfile(name="Alpha", data='{"layout":"alpha"}'))
    beta = repository.save_layout_profile(LayoutProfile(name="Beta", data='{"layout":"beta"}'))
    gamma = repository.save_layout_profile(LayoutProfile(name="Gamma", data='{"layout":"gamma"}'))

    repository.set_workspace_order([gamma.id, alpha.id, beta.id])

    reloaded = ScheduleRepository(db_path).list_user_workspace_profiles()
    assert [profile.id for profile in reloaded] == [gamma.id, alpha.id, beta.id]
    assert [profile.display_order for profile in reloaded] == [1, 2, 3]

    repository.set_workspace_order([beta.id, gamma.id])
    reloaded_after = ScheduleRepository(db_path).list_user_workspace_profiles()
    assert [profile.id for profile in reloaded_after] == [beta.id, gamma.id, alpha.id]


def test_quick_button_config_round_trips(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    repository = ScheduleRepository(db_path)
    assert repository.get_quick_button_config() == []

    config = [
        {"workspace_id": 1, "shape": "circle", "color": "#68a8f5", "visible": True},
        {"workspace_id": 2, "shape": "heart", "color": "#ef8f8f", "visible": False},
    ]
    repository.set_quick_button_config(config)

    reloaded = ScheduleRepository(db_path).get_quick_button_config()
    assert reloaded == config

    repository.set_quick_button_config([])
    assert ScheduleRepository(db_path).get_quick_button_config() == []


def test_legacy_layout_profile_db_upgrades_without_data_loss(tmp_path) -> None:
    db_path = tmp_path / "schedule.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE preferences (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            day_max_minutes INTEGER NOT NULL,
            break_minutes INTEGER NOT NULL,
            strategy TEXT NOT NULL
        );
        INSERT INTO preferences (id, day_max_minutes, break_minutes, strategy)
        VALUES (1, 480, 10, 'deadline_priority');

        CREATE TABLE layout_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO layout_profiles (name, data, created_at, updated_at)
        VALUES
            ('Legacy A', '{"body":[700,300]}', '2026-06-01T09:00:00', '2026-06-01T09:00:00'),
            ('Legacy B', '{"body":[300,700]}', '2026-06-02T10:00:00', '2026-06-02T10:00:00');
        """
    )
    connection.commit()
    connection.close()

    repository = ScheduleRepository(db_path)

    profiles = repository.list_layout_profiles()
    assert {profile.name for profile in profiles} == {"Legacy A", "Legacy B"}
    assert all(profile.is_workspace for profile in profiles)
    assert all(profile.data for profile in profiles)
    assert all(profile.quick_buttons is None for profile in profiles)

    user_profiles = repository.list_user_workspace_profiles()
    assert [profile.name for profile in user_profiles] == ["Legacy A", "Legacy B"]
    assert [profile.display_order for profile in user_profiles] == [1, 2]
    assert repository.get_quick_button_config() == []
