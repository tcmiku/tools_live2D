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
        if now - self._last_focus_ts > interval:
            self._last_focus_ts = now
            return [f"你今天已经专注了 {_format_duration(focus_seconds)}，很棒！"]
        return []

    def _maybe_random(self, now: float) -> Iterable[str]:
        if not self._config.random_enabled:
            return []
        interval = max(1, int(self._config.interval_min)) * 60
        if self._last_random_ts is None:
            self._last_random_ts = now
            samples = [
                "要不要伸个懒腰？",
                "专注一会儿再休息也可以哦～",
                "我会一直在这里陪着你。",
                "记得补充水分，保持好状态～",
                "小目标完成了吗？我在呢。",
                "深呼吸一下，继续冲～",
                "你专注的时候很帅气！",
                "给自己一个小奖励吧～",
                "别太累了，我帮你看着时间。",
                "调整一下坐姿，背挺直～",
                "卡住了就拆小步走。",
                "进度一点点也很棒。",
                "滴答滴答，时间是你的朋友。",
                "缓一缓，再出发～",
                "眨眨眼，放松肩膀～",
                "手边有水吗？喝一口吧。",
                "先把最重要的那件事搞定～",
                "今天状态不错，继续保持！",
                "小休息一下，效率会更高。",
                "给自己打个勾? 很有成就感！",
                "遇到难题先记下来，等会儿再攻。",
                "我在这里，陪你一起稳稳推进。",
                "别急，慢慢做也能做得漂亮。",
                "先清空杂念，聚焦一件事。",
                "进度条正在缓慢上涨～",
                "写完这一段就奖励自己一下？",
                "别忘了伸展一下手腕。",
                "我给你加个油：加油！",
                "目标就在前面，冲～",
                "保持呼吸节奏，心态放轻松。",
                "今天也要元气满满！",
            ]
            return [self._rng.choice(samples)]
        if now - self._last_random_ts < interval:
            return []
        self._last_random_ts = now
        samples = [
            "要不要伸个懒腰？",
            "专注一会儿再休息也可以哦～",
            "我会一直在这里陪着你。",
            "记得补充水分，保持好状态～",
            "小目标完成了吗？我在呢。",
            "深呼吸一下，继续冲～",
            "你专注的时候很帅气！",
            "给自己一个小奖励吧～",
            "别太累了，我帮你看着时间。",
            "调整一下坐姿，背挺直～",
            "卡住了就拆小步走。",
            "进度一点点也很棒。",
            "滴答滴答，时间是你的朋友。",
            "缓一缓，再出发～",
            "眨眨眼，放松肩膀～",
            "手边有水吗？喝一口吧。",
            "先把最重要的那件事搞定～",
            "今天状态不错，继续保持！",
            "小休息一下，效率会更高。",
            "给自己打个勾✓ 很有成就感！",
            "遇到难题先记下来，等会儿再攻。",
            "我在这里，陪你一起稳稳推进。",
            "别急，慢慢做也能做得漂亮。",
            "先清空杂念，聚焦一件事。",
            "进度条正在缓慢上涨～",
            "写完这一段就奖励自己一下？",
            "别忘了伸展一下手腕。",
            "我给你加个油：加油！",
            "目标就在前面，冲～",
            "保持呼吸节奏，心态放轻松。",
            "今天也要元气满满！",
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
        if "vscode" in title or "pycharm" in title or "visual studio code" in title:
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "代码写得不错，继续保持！",
                    "这段代码很顺手，再推进一点～",
                    "写代码别太赶，稳一点更好。",
                    "代码结构清晰！你在变强。",
                    "代码调试顺利吗？需要我打打气吗？",
                ]
            )
        if any(b in title for b in ["chrome", "edge", "firefox"]):
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "查资料吗？需要我帮你记点什么吗？",
                    "查资料别太久，记住重点就好～",
                    "查资料时顺手记下关键词吧。",
                    "查资料要不要我帮你整理要点？",
                    "查资料看到好内容就收藏一下吧。",
                ]
            )
        if any(d in title for d in ["photoshop", "figma", "design"]):
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "设计得真棒！记得休息一下眼睛哦～",
                    "设计配色挺舒服的，继续加油！",
                    "设计细节很赞，别忘了保存版本。",
                    "这个设计版式很有感觉～",
                    "设计再微调一点点就更完美了。",
                ]
            )
        if getattr(state, "status", "") == "sleep":
            self._last_context_ts = now
            return self._rng.choice(
                [
                    "我有点困了，你也休息一下吧？",
                    "休息片刻再回来，会更清醒哦。",
                    "闭眼一分钟，休息一下会更轻松～",
                    "起来活动下吧，休息一下肩颈也需要关照。",
                ]
            )
        return None
