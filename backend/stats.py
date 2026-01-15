from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Dict, Any


def _safe_read_json(path: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logging.exception("stats read failed: %s", exc)
        return {}


def _safe_write_json(path: str, data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logging.exception("stats write failed: %s", exc)


class FocusStats:
    def __init__(self, stats_path: str | None = None) -> None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.stats_path = stats_path or os.path.join(base_dir, "data", "stats.json")
        self._data = _safe_read_json(self.stats_path)

    def _today_key(self) -> str:
        return date.today().isoformat()

    def add_focus_second(self, seconds: int = 1) -> None:
        if seconds <= 0:
            return

        today = self._today_key()
        day_info = self._data.get(today, {"focus_seconds": 0})
        day_info["focus_seconds"] = int(day_info.get("focus_seconds", 0)) + int(seconds)
        self._data[today] = day_info
        _safe_write_json(self.stats_path, self._data)

    def get_today_focus_seconds(self) -> int:
        today = self._today_key()
        day_info = self._data.get(today, {})
        return int(day_info.get("focus_seconds", 0))

    def get_focus_seconds_by_date(self, date_str: str) -> int:
        day_info = self._data.get(date_str, {})
        return int(day_info.get("focus_seconds", 0))

    def get_range_focus_seconds(self, start: date, end: date) -> int:
        total = 0
        current = start
        while current <= end:
            total += self.get_focus_seconds_by_date(current.isoformat())
            current += timedelta(days=1)
        return total

    def get_week_focus_seconds(self, now: date | None = None) -> int:
        if now is None:
            now = date.today()
        start = now - timedelta(days=now.weekday())
        end = start + timedelta(days=6)
        return self.get_range_focus_seconds(start, end)

    def format_today_focus(self) -> str:
        seconds = self.get_today_focus_seconds()
        if seconds < 60:
            return f"{seconds} 秒"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} 分钟 {sec} 秒"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分钟"
