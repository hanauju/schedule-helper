from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.models import AvailabilityRule, Event, Preference, Task


@dataclass(slots=True)
class TimeSlot:
    start_at: datetime
    end_at: datetime

    @property
    def duration_minutes(self) -> int:
        return int((self.end_at - self.start_at).total_seconds() // 60)


@dataclass(slots=True)
class SchedulingFailure:
    task: Task
    reason: str


@dataclass(slots=True)
class SchedulingResult:
    events: list[Event]
    failures: list[SchedulingFailure]


class Scheduler:
    def schedule(
        self,
        tasks: list[Task],
        fixed_events: list[Event],
        availability_rules: list[AvailabilityRule],
        preferences: Preference,
        window_start: datetime,
        window_end: datetime,
    ) -> SchedulingResult:
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")

        slots = self._build_available_slots(availability_rules, window_start, window_end)
        slots = self._apply_day_limits(slots, preferences.day_max_minutes)
        for event in sorted(fixed_events, key=lambda item: item.start_at):
            slots = self._subtract_event(slots, event)

        scheduled: list[Event] = []
        failures: list[SchedulingFailure] = []
        candidates = [task for task in tasks if not task.completed and task.duration_minutes > 0]
        candidates.sort(
            key=lambda task: (
                task.due_at or datetime.max,
                -task.priority,
                task.created_at,
                task.title.casefold(),
            )
        )

        for task in candidates:
            if task.due_at and task.due_at <= window_start:
                failures.append(SchedulingFailure(task, "마감일이 현재 주간 범위보다 빠릅니다."))
                continue

            placement = self._find_slot(slots, task, window_end)
            if placement is None:
                failures.append(SchedulingFailure(task, "사용 가능한 시간대에 들어갈 빈 슬롯이 없습니다."))
                continue

            slot_index, start_at = placement
            end_at = start_at + timedelta(minutes=task.duration_minutes)
            event = Event(
                title=task.title,
                start_at=start_at,
                end_at=end_at,
                fixed=False,
                task_id=task.id,
                category=task.category,
            )
            scheduled.append(event)
            slots = self._consume_slot(slots, slot_index, end_at, preferences.break_minutes)

        return SchedulingResult(events=scheduled, failures=failures)

    def _build_available_slots(
        self,
        rules: list[AvailabilityRule],
        window_start: datetime,
        window_end: datetime,
    ) -> list[TimeSlot]:
        by_weekday: dict[int, list[AvailabilityRule]] = {}
        for rule in rules:
            if rule.end_time > rule.start_time:
                by_weekday.setdefault(rule.weekday, []).append(rule)

        slots: list[TimeSlot] = []
        current = window_start.date()
        last = window_end.date()
        while current <= last:
            for rule in by_weekday.get(current.weekday(), []):
                start_at = datetime.combine(current, rule.start_time)
                end_at = datetime.combine(current, rule.end_time)
                start_at = max(start_at, window_start)
                end_at = min(end_at, window_end)
                if end_at > start_at:
                    slots.append(TimeSlot(start_at, end_at))
            current += timedelta(days=1)

        return sorted(slots, key=lambda slot: slot.start_at)

    def _apply_day_limits(self, slots: list[TimeSlot], max_minutes: int) -> list[TimeSlot]:
        if max_minutes <= 0:
            return []

        limited: list[TimeSlot] = []
        used_by_day: dict[date, int] = {}
        for slot in slots:
            day = slot.start_at.date()
            used = used_by_day.get(day, 0)
            remaining = max_minutes - used
            if remaining <= 0:
                continue
            duration = min(slot.duration_minutes, remaining)
            limited.append(TimeSlot(slot.start_at, slot.start_at + timedelta(minutes=duration)))
            used_by_day[day] = used + duration
        return limited

    def _subtract_event(self, slots: list[TimeSlot], event: Event) -> list[TimeSlot]:
        result: list[TimeSlot] = []
        for slot in slots:
            if event.end_at <= slot.start_at or event.start_at >= slot.end_at:
                result.append(slot)
                continue

            if event.start_at > slot.start_at:
                result.append(TimeSlot(slot.start_at, min(event.start_at, slot.end_at)))
            if event.end_at < slot.end_at:
                result.append(TimeSlot(max(event.end_at, slot.start_at), slot.end_at))

        return sorted(result, key=lambda item: item.start_at)

    def _find_slot(
        self,
        slots: list[TimeSlot],
        task: Task,
        window_end: datetime,
    ) -> tuple[int, datetime] | None:
        latest_end = min(task.due_at or window_end, window_end)
        duration = timedelta(minutes=task.duration_minutes)
        for index, slot in enumerate(slots):
            start_at = slot.start_at
            end_at = start_at + duration
            if end_at <= slot.end_at and end_at <= latest_end:
                return index, start_at
        return None

    def _consume_slot(
        self,
        slots: list[TimeSlot],
        slot_index: int,
        consumed_until: datetime,
        break_minutes: int,
    ) -> list[TimeSlot]:
        remaining = list(slots)
        slot = remaining.pop(slot_index)
        next_start = consumed_until + timedelta(minutes=max(0, break_minutes))
        if next_start < slot.end_at:
            remaining.append(TimeSlot(next_start, slot.end_at))
        return sorted(remaining, key=lambda item: item.start_at)


def week_start_for(value: date) -> date:
    return value - timedelta(days=value.weekday())


def at_start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min)


def at_end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max).replace(microsecond=0)

