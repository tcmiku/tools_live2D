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
    def __init__(self, config: PassiveChatConfig | None = None, rng: random.Random | None = None) -> None:
        self._config = config or PassiveChatConfig()
        self._rng = rng or random.Random()
        self._last_random_ts: float | None = None
        self._last_focus_ts: float | None = None
        self._last_context_ts: float | None = None
        self._last_morning_day: int | None = None
        self._last_evening_day: int | None = None

    def set_config(self, config: PassiveChatConfig) -> None:
        self._config = config

    def tick(self, state, now: float | None = None, hour: int | None = None) -> List[str]:
        if not self._config.enabled:
            return []
        if now is None:
            now = time.time()
        if hour is None:
            hour = time.localtime(now).tm_hour
        day = time.localtime(now).tm_yday

        messages: List[str] = []
        messages.extend(self._maybe_blessing(day, hour))
        context = self.get_contextual_message(state, getattr(state, "window_title", ""), now=now)
        if context:
            messages.append(context)
        messages.extend(self._maybe_focus(state, now))
        messages.extend(self._maybe_random(now))
        return messages

    def _maybe_blessing(self, day: int, hour: int) -> Iterable[str]:
        if not self._config.blessing_enabled:
            return []
        messages: List[str] = []
        if 5 <= hour <= 10 and self._last_morning_day != day:
            self._last_morning_day = day
            messages.append("早安！今天也一起加油吧～")
        if 20 <= hour <= 23 and self._last_evening_day != day:
            self._last_evening_day = day
            messages.append("晚安，记得早点休息哦。")
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
        if now - self._last_focus_ts >= interval:
            self._last_focus_ts = now
            return [f"你今天已经专注了 {_format_duration(focus_seconds)}，很棒！"]
        return []

    def _maybe_random(self, now: float) -> Iterable[str]:
        if not self._config.random_enabled:
            return []
        interval = max(1, int(self._config.interval_min)) * 60
        if self._last_random_ts is None:
            self._last_random_ts = now
            return []
        if now - self._last_random_ts < interval:
            return []
        self._last_random_ts = now
        samples = [
            "要不要伸个懒腰？",
            "专注一会儿再休息也可以哦。",
            "我会一直在这里陪着你。",
            "记得补充水分，保持好状态。",
            "小目标完成了吗？我在呢。",
            "呼吸一下，继续冲。",
            "你专注的时候很帅气！",
            "给自己一个小奖励吧。",
            "我在看着时间，别太累。",
            "调整一下坐姿，背挺直～",
            "如果卡住了，先拆小步骤。",
            "进度一点点也很棒。",
            "滴答滴答，时间是你的朋友。",
            "缓一缓，再出发。",
            "记得眨眨眼，放松肩膀。",
        ]
        return [self._rng.choice(samples)]

    def get_contextual_message(self, state, window_title: str, now: float | None = None) -> str | None:
        if not self._config.enabled:
            return None
        if now is None:
            now = time.time()
        if self._last_context_ts is not None and now - self._last_context_ts < 300:
            return None
        title = (window_title or "").lower()
        if "vscode" in title or "pycharm" in title:
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "代码写得不错，继续保持！",
                    "这个函数挺顺手的，再推进一点～",
                    "调试顺利吗？需要我给你打打气？",
                ]
            )
        if any(b in title for b in ["chrome", "edge", "firefox"]):
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "查资料吗？需要我帮你记点什么吗？",
                    "在找灵感吗？要不要记个要点？",
                    "浏览别太久，记住重点就好～",
                ]
            )
        if any(d in title for d in ["photoshop", "figma", "design"]):
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "设计得真棒！记得休息一下眼睛哦～",
                    "配色挺舒服的，继续加油！",
                    "细节很赞，别忘了保存版本。",
                ]
            )
        if getattr(state, "status", "") == "sleep":
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "我有点困了，你也休息一下吧？",
                    "休息片刻再回来，会更清醒哦。",
                    "闭眼一分钟，脑袋会更轻松。",
                ]
            )
        return None
