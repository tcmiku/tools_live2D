from __future__ import annotations

import time
from typing import Tuple

from settings import AppSettings


def calculate_reward(streak: int) -> int:
    if streak >= 30:
        return 20
    if streak >= 7:
        return 10
    if streak >= 3:
        return 5
    if streak >= 1:
        return 2
    return 0


def apply_daily_login(settings: AppSettings, now_ts: float | None = None) -> Tuple[int, int, bool]:
    if now_ts is None:
        now_ts = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now_ts))
    yesterday = time.strftime("%Y-%m-%d", time.localtime(now_ts - 86400))
    data = settings.get_settings()
    last_login = str(data.get("last_login_date", ""))
    streak = int(data.get("login_streak", 0))
    is_new_day = last_login != today
    if is_new_day:
        if last_login == yesterday:
            streak += 1
        else:
            streak = 1
        settings.set_settings({"last_login_date": today, "login_streak": streak})
    reward = calculate_reward(streak) if is_new_day else 0
    return reward, streak, is_new_day
