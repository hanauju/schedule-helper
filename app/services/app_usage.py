from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.models import AppUsageSession, TrackedProgram
from app.storage.database import ScheduleRepository, normalize_process_name


@dataclass(slots=True)
class ActiveWindowSnapshot:
    process_name: str
    window_title: str
    executable_path: str = ""
    idle_seconds: int = 0


class ActiveWindowProvider(Protocol):
    def current_window(self) -> ActiveWindowSnapshot | None:
        ...


class WindowsActiveWindowProvider:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsActiveWindowProvider is only available on Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._enum_windows_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self._enum_windows_proc_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong

    def current_window(self) -> ActiveWindowSnapshot | None:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None

        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        executable_path = self._process_path(process_id.value)
        if not executable_path:
            return None

        process_name = normalize_process_name(Path(executable_path).name)
        return ActiveWindowSnapshot(
            process_name=process_name,
            window_title=self._window_title(hwnd),
            executable_path=executable_path,
            idle_seconds=self._idle_seconds(),
        )

    def list_open_windows(self) -> list[ActiveWindowSnapshot]:
        windows: list[ActiveWindowSnapshot] = []
        seen: set[tuple[str, str]] = set()

        def callback(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True

            title = self._window_title(hwnd).strip()
            if not title:
                return True

            process_id = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            executable_path = self._process_path(process_id.value)
            if not executable_path:
                return True

            process_name = normalize_process_name(Path(executable_path).name)
            key = (process_name, title)
            if key in seen:
                return True

            seen.add(key)
            windows.append(
                ActiveWindowSnapshot(
                    process_name=process_name,
                    window_title=title,
                    executable_path=executable_path,
                )
            )
            return True

        enum_proc = self._enum_windows_proc_type(callback)
        self.user32.EnumWindows(enum_proc, 0)
        return sorted(windows, key=lambda item: (item.process_name.casefold(), item.window_title.casefold()))

    def _process_path(self, process_id: int) -> str:
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return buffer.value
        finally:
            self.kernel32.CloseHandle(handle)

    def _window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _idle_seconds(self) -> int:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        elapsed_ms = self.kernel32.GetTickCount64() - info.dwTime
        return max(0, int(elapsed_ms // 1000))


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


@dataclass(slots=True)
class _ActiveUsage:
    program: TrackedProgram
    process_name: str
    window_title: str
    started_at: datetime


class AppUsageRecorder:
    def __init__(
        self,
        repository: ScheduleRepository,
        provider: ActiveWindowProvider,
        idle_cutoff_seconds: int = 60,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.idle_cutoff_seconds = idle_cutoff_seconds
        self.active: _ActiveUsage | None = None
        self.last_snapshot: ActiveWindowSnapshot | None = None
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self, now: datetime | None = None) -> None:
        self._finish(now or datetime.now())
        self.running = False

    def tick(self, now: datetime | None = None) -> TrackedProgram | None:
        if not self.running:
            return None

        now = now or datetime.now()
        snapshot = self.provider.current_window()
        self.last_snapshot = snapshot
        if snapshot is None:
            self._finish(now)
            return None

        if snapshot.idle_seconds > self.idle_cutoff_seconds:
            self._finish(now - timedelta(seconds=snapshot.idle_seconds))
            return None

        program = self.repository.find_tracked_program_by_process(snapshot.process_name)
        if program is None or not program.enabled:
            self._finish(now)
            return None

        if self._is_same_active(program, snapshot):
            return program

        self._finish(now)
        self.active = _ActiveUsage(
            program=program,
            process_name=snapshot.process_name,
            window_title=snapshot.window_title,
            started_at=now,
        )
        return program

    def _is_same_active(self, program: TrackedProgram, snapshot: ActiveWindowSnapshot) -> bool:
        return (
            self.active is not None
            and self.active.program.id == program.id
            and self.active.process_name == snapshot.process_name
            and self.active.window_title == snapshot.window_title
        )

    def _finish(self, ended_at: datetime) -> None:
        if self.active is None:
            return

        if ended_at <= self.active.started_at:
            self.active = None
            return

        duration_seconds = int((ended_at - self.active.started_at).total_seconds())
        if duration_seconds > 0:
            self.repository.save_app_usage_session(
                AppUsageSession(
                    target_id=self.active.program.id,
                    process_name=self.active.process_name,
                    window_title=self.active.window_title,
                    started_at=self.active.started_at,
                    ended_at=ended_at,
                    duration_seconds=duration_seconds,
                )
            )
        self.active = None
