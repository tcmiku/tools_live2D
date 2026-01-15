from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ReminderConfig:
    rest_enabled: bool = True
    rest_interval_min: int = 90
    water_enabled: bool = True
    water_interval_min: int = 60
    eye_enabled: bool = True
    eye_interval_min: int = 45

    @classmethod
    def from_settings(cls, settings: Dict[str, Any]) -> "ReminderConfig":
        return cls(
            rest_enabled=bool(settings.get("rest_enabled", True)),
            rest_interval_min=int(settings.get("rest_interval_min", 90)),
            water_enabled=bool(settings.get("water_enabled", True)),
            water_interval_min=int(settings.get("water_interval_min", 60)),
            eye_enabled=bool(settings.get("eye_enabled", True)),
            eye_interval_min=int(settings.get("eye_interval_min", 45)),
        )


class ReminderEngine:
    def __init__(self, config: ReminderConfig | None = None) -> None:
        self._config = config or ReminderConfig()
        self._active_seconds = 0.0
        self._last_tick: float | None = None
        self._last_water: float | None = None
        self._last_eye: float | None = None

    def set_config(self, config: ReminderConfig) -> None:
        self._config = config

    def update_focus(self, state, now: float | None = None) -> List[str]:
        if now is None:
            now = time.time()
        if self._last_tick is None:
            self._last_tick = now
        delta = max(0.0, now - self._last_tick)
        self._last_tick = now
        events: List[str] = []

        if state.status == "active":
            self._active_seconds += delta
            if self._config.rest_enabled and self._config.rest_interval_min > 0:
                if self._active_seconds >= self._config.rest_interval_min * 60:
                    self._active_seconds = 0.0
                    events.append("rest")
        else:
            self._active_seconds = 0.0

        return events

    def update_timers(self, now: float | None = None) -> List[str]:
        if now is None:
            now = time.time()
        events: List[str] = []

        if self._config.water_enabled and self._config.water_interval_min > 0:
            if self._last_water is None:
                self._last_water = now
            elif now - self._last_water >= self._config.water_interval_min * 60:
                self._last_water = now
                events.append("water")

        if self._config.eye_enabled and self._config.eye_interval_min > 0:
            if self._last_eye is None:
                self._last_eye = now
            elif now - self._last_eye >= self._config.eye_interval_min * 60:
                self._last_eye = now
                events.append("eye")

        return events


class ReminderStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._data: Dict[str, Any] = {"todos": []}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception as exc:
            logging.exception("reminder store load failed: %s", exc)
            self._data = {"todos": []}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.exception("reminder store save failed: %s", exc)

    def list_todos(self) -> List[Dict[str, Any]]:
        todos = self._data.get("todos", [])
        if not isinstance(todos, list):
            return []
        return list(todos)

    def add_todo(self, title: str, due_ts: float) -> Dict[str, Any]:
        todos = self._data.get("todos", [])
        if not isinstance(todos, list):
            todos = []
        next_id = max((int(t.get("id", 0)) for t in todos), default=0) + 1
        item = {
            "id": next_id,
            "title": title,
            "due_ts": float(due_ts),
            "triggered": False,
        }
        todos.append(item)
        self._data["todos"] = todos
        self._save()
        return item

    def remove_todo(self, todo_id: int) -> None:
        todos = self._data.get("todos", [])
        if not isinstance(todos, list):
            return
        self._data["todos"] = [t for t in todos if int(t.get("id", 0)) != todo_id]
        self._save()

    def mark_triggered(self, todo_id: int) -> None:
        todos = self._data.get("todos", [])
        if not isinstance(todos, list):
            return
        changed = False
        for item in todos:
            if int(item.get("id", 0)) == todo_id:
                item["triggered"] = True
                changed = True
                break
        if changed:
            self._save()

    def due_items(self, now: float | None = None) -> List[Dict[str, Any]]:
        if now is None:
            now = time.time()
        due: List[Dict[str, Any]] = []
        for item in self.list_todos():
            if item.get("triggered"):
                continue
            try:
                if float(item.get("due_ts", 0)) <= now:
                    due.append(item)
            except (TypeError, ValueError):
                continue
        return due
