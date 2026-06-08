from __future__ import annotations

from datetime import datetime, timedelta

from app.models import TrackedProgram
from app.services.app_usage import ActiveWindowSnapshot, AppUsageRecorder
from app.storage.database import ScheduleRepository


class FakeProvider:
    def __init__(self) -> None:
        self.snapshot: ActiveWindowSnapshot | None = None

    def current_window(self) -> ActiveWindowSnapshot | None:
        return self.snapshot


def test_app_usage_recorder_saves_sessions_when_foreground_app_changes(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    chrome = repository.save_tracked_program(TrackedProgram("Chrome", "chrome.exe"))
    code = repository.save_tracked_program(TrackedProgram("Code", "Code.exe"))
    provider = FakeProvider()
    recorder = AppUsageRecorder(repository, provider, idle_cutoff_seconds=60)
    recorder.start()

    start = datetime(2026, 6, 4, 9, 0, 0)
    provider.snapshot = ActiveWindowSnapshot("chrome.exe", "Search")
    recorder.tick(start)

    provider.snapshot = ActiveWindowSnapshot("code.exe", "main_window.py")
    recorder.tick(start + timedelta(seconds=10))
    recorder.stop(start + timedelta(seconds=25))

    sessions = repository.list_app_usage_sessions(start, start + timedelta(hours=1))
    assert len(sessions) == 2
    assert sessions[1].target_id == chrome.id
    assert sessions[1].duration_seconds == 10
    assert sessions[0].target_id == code.id
    assert sessions[0].duration_seconds == 15


def test_app_usage_recorder_stops_counting_after_idle_cutoff(tmp_path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.sqlite3")
    program = repository.save_tracked_program(TrackedProgram("Chrome", "chrome.exe"))
    provider = FakeProvider()
    recorder = AppUsageRecorder(repository, provider, idle_cutoff_seconds=60)
    recorder.start()

    start = datetime(2026, 6, 4, 9, 0, 0)
    provider.snapshot = ActiveWindowSnapshot("chrome.exe", "Search", idle_seconds=0)
    recorder.tick(start)
    recorder.tick(start + timedelta(seconds=30))

    provider.snapshot = ActiveWindowSnapshot("chrome.exe", "Search", idle_seconds=70)
    recorder.tick(start + timedelta(seconds=120))

    sessions = repository.list_app_usage_sessions(start, start + timedelta(hours=1))
    assert len(sessions) == 1
    assert sessions[0].target_id == program.id
    assert sessions[0].duration_seconds == 50
