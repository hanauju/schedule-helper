from __future__ import annotations

from datetime import datetime, timedelta

from app.models import FocusEvent, FocusSession
from app.services.app_usage import ActiveWindowProvider
from app.storage.database import ScheduleRepository, normalize_process_name


class FocusTimerService:
    def __init__(
        self,
        repository: ScheduleRepository,
        window_provider: ActiveWindowProvider | None = None,
        idle_cutoff_seconds: int = 60,
    ) -> None:
        self.repository = repository
        self.window_provider = window_provider
        self.idle_cutoff_seconds = idle_cutoff_seconds
        self.session: FocusSession | None = None
        self.last_tick_at: datetime | None = None
        self.segment_type: str | None = None
        self.segment_started_at: datetime | None = None
        self.current_process_name = ""
        self.current_window_title = ""

    def start(
        self,
        title: str,
        planned_seconds: int,
        target_process_name: str = "",
        target_window_title: str = "",
        task_id: int | None = None,
        now: datetime | None = None,
    ) -> FocusSession:
        now = now or datetime.now()
        if self.session is not None and self.session.status not in {"completed", "interrupted", "cancelled"}:
            self.stop(now, status="interrupted")
        self.session = None
        self.session = self.repository.save_focus_session(
            FocusSession(
                title=title.strip() or "집중 세션",
                task_id=task_id,
                target_process_name=normalize_process_name(target_process_name) if target_process_name else "",
                target_window_title=target_window_title,
                planned_seconds=max(60, planned_seconds),
                started_at=now,
                status="running",
            )
        )
        self.last_tick_at = now
        self.segment_type = None
        self.segment_started_at = None
        return self.session

    def pause(self, now: datetime | None = None) -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None or self.session.status != "running":
            return self.session
        self.tick(now)
        self.session.status = "paused"
        self.last_tick_at = now
        self._switch_segment("paused", now)
        return self.repository.save_focus_session(self.session)

    def resume(self, now: datetime | None = None) -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None or self.session.status != "paused":
            return self.session
        self.tick(now)
        self.session.status = "running"
        self.last_tick_at = now
        self._switch_segment(None, now)
        return self.repository.save_focus_session(self.session)

    def start_break(self, now: datetime | None = None) -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None or self.session.status != "running":
            return self.session
        self.tick(now)
        self.session.status = "break"
        self.last_tick_at = now
        self._switch_segment("break", now)
        return self.repository.save_focus_session(self.session)

    def end_break(self, now: datetime | None = None) -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None or self.session.status != "break":
            return self.session
        self.tick(now)
        self.session.status = "running"
        self.last_tick_at = now
        self._switch_segment(None, now)
        return self.repository.save_focus_session(self.session)

    def complete(self, now: datetime | None = None) -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None:
            return None
        self.tick(now)
        return self._finish(now, "completed")

    def stop(self, now: datetime | None = None, status: str = "interrupted") -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None:
            return None
        return self._finish(now, status)

    def tick(self, now: datetime | None = None) -> FocusSession | None:
        now = now or datetime.now()
        if self.session is None or self.session.status in {"completed", "interrupted", "cancelled"}:
            return self.session
        if self.last_tick_at is None:
            self.last_tick_at = now
            return self.session

        delta = int((now - self.last_tick_at).total_seconds())
        if delta <= 0:
            return self.session

        if self.session.status in {"paused", "break"}:
            self.session.paused_seconds += delta
            self._switch_segment(self.session.status, self.last_tick_at)
        else:
            segment_type = self._current_segment_type()
            if segment_type == "focused":
                remaining = self.session.remaining_seconds
                added = min(delta, remaining)
                self.session.focused_seconds += added
                if added < delta:
                    now = self.last_tick_at + timedelta(seconds=added)
                    self._switch_segment("focused", self.last_tick_at)
                    self.last_tick_at = now
                    self.repository.save_focus_session(self.session)
                    return self._finish(now, "completed")
            else:
                self.session.away_seconds += delta
            self._switch_segment(segment_type, self.last_tick_at)

        self.last_tick_at = now
        if self.session.focused_seconds >= self.session.planned_seconds:
            return self._finish(now, "completed")
        return self.repository.save_focus_session(self.session)

    def focus_ratio(self) -> float:
        if self.session is None:
            return 0.0
        total = self.session.focused_seconds + self.session.away_seconds
        if total <= 0:
            return 1.0
        return self.session.focused_seconds / total

    def _current_segment_type(self) -> str:
        if self.session is None:
            return "away"

        snapshot = self.window_provider.current_window() if self.window_provider else None
        if snapshot is not None:
            self.current_process_name = snapshot.process_name
            self.current_window_title = snapshot.window_title
            if snapshot.idle_seconds > self.idle_cutoff_seconds:
                return "away"

        target = self.session.target_process_name
        if not target:
            return "focused"
        if snapshot is None:
            return "away"
        return "focused" if normalize_process_name(snapshot.process_name) == normalize_process_name(target) else "away"

    def _switch_segment(self, next_type: str | None, now: datetime) -> None:
        if self.session is None:
            return
        if self.segment_type == next_type:
            return

        self._close_segment(now)
        self.segment_type = next_type
        self.segment_started_at = now if next_type else None

    def _close_segment(self, ended_at: datetime) -> None:
        if self.session is None or self.session.id is None:
            return
        if self.segment_type is None or self.segment_started_at is None:
            return
        duration = int((ended_at - self.segment_started_at).total_seconds())
        if duration <= 0:
            return
        self.repository.save_focus_event(
            FocusEvent(
                focus_session_id=self.session.id,
                event_type=self.segment_type,
                started_at=self.segment_started_at,
                ended_at=ended_at,
                duration_seconds=duration,
                metadata=self.current_process_name,
            )
        )

    def _finish(self, now: datetime, status: str) -> FocusSession:
        if self.session is None:
            raise RuntimeError("No active focus session")
        self._close_segment(now)
        self.segment_type = None
        self.segment_started_at = None
        self.session.status = status
        self.session.ended_at = now
        self.last_tick_at = now
        self.repository.save_focus_session(self.session)
        return self.session
