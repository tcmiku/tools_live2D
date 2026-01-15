import datetime
import unittest

from backend.achievements import (
    build_daily_summary,
    build_weekly_summary,
    format_duration,
    weekly_percentile,
    week_range,
)


class AchievementTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(45), "45 秒")
        self.assertEqual(format_duration(75), "1 分钟 15 秒")
        self.assertEqual(format_duration(3660), "1 小时 1 分钟")

    def test_week_range(self):
        day = datetime.date(2026, 1, 15)
        rng = week_range(day)
        self.assertEqual(rng.start.isoformat(), "2026-01-12")
        self.assertEqual(rng.end.isoformat(), "2026-01-18")

    def test_weekly_percentile(self):
        self.assertEqual(weekly_percentile(0), 50)
        self.assertEqual(weekly_percentile(2 * 3600), 65)
        self.assertEqual(weekly_percentile(5 * 3600), 75)
        self.assertEqual(weekly_percentile(8 * 3600), 85)
        self.assertEqual(weekly_percentile(12 * 3600), 90)
        self.assertEqual(weekly_percentile(20 * 3600), 95)

    def test_build_summaries(self):
        daily = build_daily_summary(3 * 3600 + 15 * 60, 4)
        weekly = build_weekly_summary(18 * 3600)
        self.assertIn("3 小时 15 分钟", daily)
        self.assertIn("4 个番茄钟", daily)
        self.assertIn("18 小时", weekly)
        self.assertIn("%", weekly)


if __name__ == "__main__":
    unittest.main()
