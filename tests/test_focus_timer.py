from __future__ import annotations

from datetime import datetime, timedelta

from app.models import QuickNote
from app.services.app_usage import ActiveWindowSnapshot
from app.services.focus_timer import FocusTimerService
from app.storage.database import ScheduleRepository


class FakeProvider:
    def __init__(self) -> None:
        self.snapshot: ActiveWindowSnapshot | None = None

    def current_window(self) -> ActiveWindowSnapshot | None:
        return self.snapshot


def test_focus_timer_tracks_focused_away_and_paused_time(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    provider = FakeProvider()
    service = FocusTimerService(repository, provider)
    start = datetime(2026, 6, 8, 9, 0, 0)

    provider.snapshot = ActiveWindowSnapshot("code.exe", "main.py")
    session = service.start("Build", 25 * 60, "code.exe", now=start)
    service.tick(start + timedelta(seconds=10))

    provider.snapshot = ActiveWindowSnapshot("chrome.exe", "Search")
    service.tick(start + timedelta(seconds=25))

    service.pause(start + timedelta(seconds=25))
    service.tick(start + timedelta(seconds=40))

    service.resume(start + timedelta(seconds=40))
    provider.snapshot = ActiveWindowSnapshot("code.exe", "main.py")
    service.tick(start + timedelta(seconds=50))
    service.complete(start + timedelta(seconds=50))

    saved = repository.get_focus_session(session.id)
    assert saved is not None
    assert saved.focused_seconds == 20
    assert saved.away_seconds == 15
    assert saved.paused_seconds == 15
    assert saved.status == "completed"


def test_focus_timer_accepts_multiple_target_windows(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    provider = FakeProvider()
    service = FocusTimerService(repository, provider)
    start = datetime(2026, 6, 8, 9, 0, 0)

    provider.snapshot = ActiveWindowSnapshot("code.exe", "main.py")
    session = service.start(
        "Build",
        25 * 60,
        target_windows=[
            {"process_name": "code.exe", "window_title": "main.py"},
            {"process_name": "chrome.exe", "window_title": "Docs"},
        ],
        now=start,
    )
    service.tick(start + timedelta(seconds=10))

    provider.snapshot = ActiveWindowSnapshot("chrome.exe", "Docs")
    service.tick(start + timedelta(seconds=25))

    provider.snapshot = ActiveWindowSnapshot("chrome.exe", "Search")
    service.tick(start + timedelta(seconds=35))

    saved = repository.get_focus_session(session.id)
    assert saved is not None
    assert saved.focused_seconds == 25
    assert saved.away_seconds == 10


def test_quick_notes_keep_created_time_and_session_link(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    service = FocusTimerService(repository)
    created_at = datetime(2026, 6, 8, 10, 0, 0)
    session = service.start("Read", 1500, now=created_at)

    note = repository.save_quick_note(
        QuickNote(
            body="핵심 아이디어 정리",
            created_at=created_at + timedelta(minutes=3),
            focus_session_id=session.id,
            process_name="notion.exe",
        )
    )

    notes = repository.list_quick_notes(limit=5)
    assert notes[0].id == note.id
    assert notes[0].created_at == created_at + timedelta(minutes=3)
    assert notes[0].focus_session_id == session.id


def test_focus_timer_tracks_break_time_as_break_event(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    service = FocusTimerService(repository)
    start = datetime(2026, 6, 8, 11, 0, 0)
    session = service.start("Pomodoro", 1500, now=start)

    service.tick(start + timedelta(seconds=10))
    service.start_break(start + timedelta(seconds=10))
    service.tick(start + timedelta(seconds=40))
    service.end_break(start + timedelta(seconds=40))

    saved = repository.get_focus_session(session.id)
    events = repository.list_focus_events(session.id)

    assert saved is not None
    assert saved.focused_seconds == 10
    assert saved.paused_seconds == 30
    assert any(event.event_type == "break" and event.duration_seconds == 30 for event in events)
