import os
import tempfile
import time
import unittest

from backend.login_rewards import apply_daily_login, calculate_reward
from backend.settings import AppSettings


def _ts(date_str: str) -> float:
    return time.mktime(time.strptime(date_str, "%Y-%m-%d"))


class DailyLoginTests(unittest.TestCase):
    def test_streak_increases_on_consecutive_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(os.path.join(tmp, "settings.json"))
            settings.set_settings({"last_login_date": "2026-01-01", "login_streak": 2})
            reward, streak, is_new_day = apply_daily_login(settings, _ts("2026-01-02"))

            self.assertTrue(is_new_day)
            self.assertEqual(streak, 3)
            self.assertEqual(reward, 5)
            self.assertEqual(settings.get_settings()["login_streak"], 3)

    def test_streak_resets_after_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(os.path.join(tmp, "settings.json"))
            settings.set_settings({"last_login_date": "2026-01-01", "login_streak": 5})
            reward, streak, is_new_day = apply_daily_login(settings, _ts("2026-01-03"))

            self.assertTrue(is_new_day)
            self.assertEqual(streak, 1)
            self.assertEqual(reward, 2)

    def test_no_reward_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(os.path.join(tmp, "settings.json"))
            settings.set_settings({"last_login_date": "2026-01-02", "login_streak": 7})
            reward, streak, is_new_day = apply_daily_login(settings, _ts("2026-01-02"))

            self.assertFalse(is_new_day)
            self.assertEqual(streak, 7)
            self.assertEqual(reward, 0)

    def test_calculate_reward_thresholds(self):
        self.assertEqual(calculate_reward(0), 0)
        self.assertEqual(calculate_reward(1), 2)
        self.assertEqual(calculate_reward(3), 5)
        self.assertEqual(calculate_reward(7), 10)
        self.assertEqual(calculate_reward(30), 20)


if __name__ == "__main__":
    unittest.main()
