import os
import tempfile
import unittest

from backend.settings import AppSettings


class FavorSettingsTests(unittest.TestCase):
    def test_favor_clamped_upper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings({"favor": 999})
            data = settings.get_settings()
            self.assertEqual(data.get("favor"), 100)

    def test_favor_clamped_lower(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings({"favor": -10})
            data = settings.get_settings()
            self.assertEqual(data.get("favor"), 0)


if __name__ == "__main__":
    unittest.main()
