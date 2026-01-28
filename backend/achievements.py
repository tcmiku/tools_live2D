from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass
class WeekRange:
    start: datetime.date
    end: datetime.date


def week_range(day: datetime.date | None = None) -> WeekRange:
    if day is None:
        day = datetime.date.today()
    start = day - datetime.timedelta(days=day.weekday())
    end = start + datetime.timedelta(days=6)
    return WeekRange(start=start, end=end)


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分钟 {sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分钟"


def weekly_percentile(focus_seconds: int) -> int:
    hours = focus_seconds / 3600.0
    if hours >= 20:
        return 95
    if hours >= 12:
        return 90
    if hours >= 8:
        return 85
    if hours >= 5:
        return 75
    if hours >= 2:
        return 65
    return 50


def build_daily_summary(focus_seconds: int, pomodoro_count: int) -> str:
    return f"今天你专注了 {format_duration(focus_seconds)}，完成了 {pomodoro_count} 个番茄钟！"


def build_weekly_summary(focus_seconds: int) -> str:
    percentile = weekly_percentile(focus_seconds)
    return f"本周累计专注 {format_duration(focus_seconds)}，超过 {percentile}% 的用户 🎉"
