from __future__ import annotations

import ctypes
import logging
import time
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass, replace

try:
    from .stats import FocusStats
except ImportError:
    from stats import FocusStats


@dataclass
class FocusState:
    status: str  # active | idle | sleep | paused
    idle_ms: int
    focus_seconds_today: int
    input_type: str  # keyboard | mouse | idle | sleep | paused
    window_title: str


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def get_idle_milliseconds() -> int:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)

    if not user32.GetLastInputInfo(ctypes.byref(info)):
        logging.warning("GetLastInputInfo failed")
        return 0

    tick = kernel32.GetTickCount()
    return max(0, int(tick - info.dwTime))


def get_cursor_pos() -> tuple[int, int] | None:
    user32 = ctypes.windll.user32
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def get_foreground_window_title() -> tuple[int, str]:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return int(hwnd), ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return int(hwnd), buffer.value


class FocusEngine:
    def __init__(
        self,
        stats: FocusStats,
        active_threshold_ms: int = 60000,
        sleep_threshold_ms: int = 120000,
    ) -> None:
        self.stats = stats
        self.active_threshold_ms = active_threshold_ms
        self.sleep_threshold_ms = sleep_threshold_ms
        self.paused = False
        self._last_cursor: tuple[int, int] | None = None
        self._last_window_handle: int | None = None
        self._last_window_title: str = ""
        self._switch_times: deque[float] = deque(maxlen=10)
        self._last_typing_hint = 0.0
        self._last_idle_hint: float | None = None
        self._last_switch_hint = 0.0
        self._last_browser_hint = 0.0

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_thresholds(self, active_ms: int, sleep_ms: int) -> None:
        if active_ms <= 0 or sleep_ms <= 0:
            return
        self.active_threshold_ms = active_ms
        self.sleep_threshold_ms = max(sleep_ms, active_ms + 1000)

    def update(self) -> FocusState:
        now = time.time()
        idle_ms = get_idle_milliseconds()
        cursor = get_cursor_pos()
        window_handle, window_title = get_foreground_window_title()
        if window_handle and window_handle != self._last_window_handle:
            self._last_window_handle = window_handle
            self._last_window_title = window_title or ""
            self._switch_times.append(now)
        elif window_title:
            self._last_window_title = window_title

        input_type = "idle"

        if self.paused:
            return FocusState(
                status="paused",
                idle_ms=idle_ms,
                focus_seconds_today=self.stats.get_today_focus_seconds(),
                input_type="paused",
                window_title=self._last_window_title,
            )

        if idle_ms < self.active_threshold_ms:
            self.stats.add_focus_second(1)
            status = "active"
            if cursor and self._last_cursor and cursor != self._last_cursor:
                input_type = "mouse"
            else:
                input_type = "keyboard"
        elif idle_ms < self.sleep_threshold_ms:
            status = "idle"
            input_type = "idle"
        else:
            status = "sleep"
            input_type = "sleep"

        if cursor:
            self._last_cursor = cursor

        return FocusState(
            status=status,
            idle_ms=idle_ms,
            focus_seconds_today=self.stats.get_today_focus_seconds(),
            input_type=input_type,
            window_title=self._last_window_title,
        )

    def get_interaction_events(self, state: FocusState) -> list[str]:
        now = time.time()
        events: list[str] = []

        if state.input_type == "keyboard" and now - self._last_typing_hint > 60:
            self._last_typing_hint = now
            events.append("typing")

        if state.status == "sleep":
            if self._last_idle_hint is None or now - self._last_idle_hint > 300:
                self._last_idle_hint = now
                events.append("idle")

        while self._switch_times and now - self._switch_times[0] > 20:
            self._switch_times.popleft()
        if len(self._switch_times) >= 3 and now - self._last_switch_hint > 120:
            self._last_switch_hint = now
            events.append("switch")

        if state.window_title and now - self._last_browser_hint > 300:
            title = state.window_title.lower()
            browsers = ("chrome", "edge", "firefox", "brave", "opera")
            if any(name in title for name in browsers):
                self._last_browser_hint = now
                events.append("browser")

        return events


def adjust_state_for_pomodoro(state: FocusState, pomodoro_mode: str) -> FocusState:
    if pomodoro_mode == "focus" and state.status == "sleep":
        return replace(state, status="idle")
    return state
