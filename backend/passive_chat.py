from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Iterable, List


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分钟 {sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分钟"


@dataclass
class PassiveChatConfig:
    enabled: bool = True
    interval_min: int = 30
    random_enabled: bool = True
    blessing_enabled: bool = True
    focus_enabled: bool = True
    focus_interval_min: int = 60


class PassiveChatEngine:
    def __init__(
        self,
        config: PassiveChatConfig | None = None,
        rng: random.Random | None = None,
        texts=None,
    ) -> None:
        self._config = config or PassiveChatConfig()
        self._rng = rng or random.Random()
        self._texts = texts
        self._last_random_ts: float | None = None
        self._last_focus_ts: float | None = None
        self._last_context_ts: float | None = None
        self._last_morning_day: int | None = None
        self._last_evening_day: int | None = None

    def set_config(self, config: PassiveChatConfig) -> None:
        self._config = config

    def _text_list(self, path: str, fallback: list[str]) -> list[str]:
        if not self._texts:
            return fallback
        return self._texts.get_list(path, fallback)

    def _text_value(self, path: str, fallback: str) -> str:
        if not self._texts:
            return fallback
        return self._texts.get_text(path, fallback)

    def tick(self, state, now: float | None = None, hour: int | None = None) -> List[str]:
        if not self._config.enabled:
            return []
        if now is None:
            now = time.time()
        if hour is None:
            hour = time.localtime(now).tm_hour
        day = time.localtime(now).tm_yday

        messages: List[str] = []
        focus_seconds = int(getattr(state, "focus_seconds_today", 0))
        if focus_seconds <= 0:
            messages.extend(self._maybe_blessing(day, hour))
        context = self.get_contextual_message(state, getattr(state, "window_title", ""), now=now)
        if context:
            messages.append(context)
        messages.extend(self._maybe_focus(state, now))
        if self._last_random_ts is None:
            self._last_random_ts = now
        else:
            messages.extend(self._maybe_random(now))
        return messages

    def _maybe_blessing(self, day: int, hour: int) -> Iterable[str]:
        if not self._config.blessing_enabled:
            return []
        messages: List[str] = []
        if 5 <= hour <= 10 and self._last_morning_day != day:
            self._last_morning_day = day
            morning = self._text_list("passive.blessing.morning", [])
            if morning:
                messages.append(self._rng.choice(morning))
        if 20 <= hour <= 23 and self._last_evening_day != day:
            self._last_evening_day = day
            evening = self._text_list("passive.blessing.evening", [])
            if evening:
                messages.append(self._rng.choice(evening))
        return messages

    def _maybe_focus(self, state, now: float) -> Iterable[str]:
        if not self._config.focus_enabled:
            return []
        focus_seconds = int(getattr(state, "focus_seconds_today", 0))
        if focus_seconds <= 0:
            return []
        interval = max(1, int(self._config.focus_interval_min)) * 60
        if self._last_focus_ts is None:
            self._last_focus_ts = now
            return []
        if now - self._last_focus_ts > interval:
            self._last_focus_ts = now
            template = self._text_value("passive.focus_template", "")
            if template:
                return [template.format(duration=_format_duration(focus_seconds))]
            return []
        return []

    def _maybe_random(self, now: float) -> Iterable[str]:
        if not self._config.random_enabled:
            return []
        interval = max(1, int(self._config.interval_min)) * 60
        if self._last_random_ts is None:
            self._last_random_ts = now
            samples = self._text_list("passive.random", [])
            if samples:
                return [self._rng.choice(samples)]
            return []
        if now - self._last_random_ts < interval:
            return []
        self._last_random_ts = now
        samples = self._text_list("passive.random", [])
        if samples:
            return [self._rng.choice(samples)]
        return []

    def get_contextual_message(self, state, window_title: str, now: float | None = None) -> str | None:
        if not self._config.enabled:
            return None
        if now is None:
            now = time.time()
        if self._last_context_ts is not None and now - self._last_context_ts < 300:
            return None
        title = (window_title or "").lower()
        if "vscode" in title or "pycharm" in title or "visual studio code" in title:
            self._last_context_ts = now
            choices = self._text_list("passive.context.vscode", [])
            return self._rng.choice(choices) if choices else None
        if any(b in title for b in ["chrome", "edge", "firefox"]):
            self._last_context_ts = now
            choices = self._text_list("passive.context.browser", [])
            return self._rng.choice(choices) if choices else None
        if any(d in title for d in ["photoshop", "figma", "design"]):
            self._last_context_ts = now
            choices = self._text_list("passive.context.design", [])
            return self._rng.choice(choices) if choices else None
        if getattr(state, "status", "") == "sleep":
            self._last_context_ts = now
            choices = self._text_list("passive.context.sleep", [])
            return self._rng.choice(choices) if choices else None
        return None
