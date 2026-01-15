from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Dict, Any


@dataclass
class PomodoroState:
    mode: str  # idle | focus | break | paused
    remaining_sec: int
    focus_min: int
    break_min: int
    count_today: int


class PomodoroEngine:
    def __init__(self, data_path: str, focus_min: int = 25, break_min: int = 5) -> None:
        self._data_path = data_path
        self.focus_min = max(1, int(focus_min))
        self.break_min = max(1, int(break_min))
        self._mode = "idle"
        self._remaining_sec = 0
        self._last_tick = None
        self._count_data: Dict[str, Any] = {}
        self._load_counts()

    def _load_counts(self) -> None:
        try:
            if os.path.exists(self._data_path):
                with open(self._data_path, "r", encoding="utf-8") as f:
                    self._count_data = json.load(f)
        except Exception as exc:
            logging.exception("pomodoro load failed: %s", exc)
            self._count_data = {}

    def _save_counts(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._data_path), exist_ok=True)
            with open(self._data_path, "w", encoding="utf-8") as f:
                json.dump(self._count_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.exception("pomodoro save failed: %s", exc)

    def _today_key(self) -> str:
        return date.today().isoformat()

    def _inc_today(self) -> None:
        key = self._today_key()
        current = int(self._count_data.get(key, 0))
        self._count_data[key] = current + 1
        self._save_counts()

    def get_count_today(self) -> int:
        return int(self._count_data.get(self._today_key(), 0))

    def set_durations(self, focus_min: int, break_min: int) -> None:
        self.focus_min = max(1, int(focus_min))
        self.break_min = max(1, int(break_min))
        if self._mode in ("focus", "break", "paused"):
            # Keep remaining seconds within new duration.
            limit = self.focus_min * 60 if self._mode == "focus" else self.break_min * 60
            self._remaining_sec = min(self._remaining_sec, limit)

    def start(self) -> None:
        if self._mode in ("focus", "break"):
            return
        if self._mode == "paused":
            self._mode = "focus"
        else:
            self._mode = "focus"
            self._remaining_sec = self.focus_min * 60
        self._last_tick = time.time()

    def pause(self) -> None:
        if self._mode in ("focus", "break"):
            self._mode = "paused"

    def stop(self) -> None:
        self._mode = "idle"
        self._remaining_sec = 0
        self._last_tick = None

    def toggle(self) -> None:
        if self._mode in ("focus", "break"):
            self.pause()
        else:
            self.start()

    @property
    def mode(self) -> str:
        return self._mode

    def update(self) -> PomodoroState:
        now = time.time()
        if self._last_tick is None:
            self._last_tick = now
        delta = int(now - self._last_tick)
        if delta > 0:
            self._last_tick = now
            if self._mode in ("focus", "break") and self._remaining_sec > 0:
                self._remaining_sec = max(0, self._remaining_sec - delta)
            if self._mode == "focus" and self._remaining_sec == 0:
                self._inc_today()
                self._mode = "break"
                self._remaining_sec = self.break_min * 60
            elif self._mode == "break" and self._remaining_sec == 0:
                self._mode = "focus"
                self._remaining_sec = self.focus_min * 60
        return PomodoroState(
            mode=self._mode,
            remaining_sec=int(self._remaining_sec),
            focus_min=self.focus_min,
            break_min=self.break_min,
            count_today=self.get_count_today(),
        )


def reward_for_focus_minutes(minutes: int) -> int:
    return 1
