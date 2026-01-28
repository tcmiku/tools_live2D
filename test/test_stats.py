import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from stats import FocusStats  # noqa: E402


class FocusStatsTests(unittest.TestCase):
    def test_add_focus_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stats.json")
            stats = FocusStats(stats_path=path)
            stats.add_focus_second(3)
            self.assertEqual(stats.get_today_focus_seconds(), 3)

    def test_format_today_focus_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stats.json")
            stats = FocusStats(stats_path=path)
            stats.add_focus_second(5)
            self.assertEqual(stats.format_today_focus(), "5 sec")


if __name__ == "__main__":
    unittest.main()
