import os
import tempfile
import unittest

from backend.ai_client import AIClient
from backend.settings import AppSettings


class AILocalContextTests(unittest.TestCase):
    def test_time_context_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            client = AIClient(settings)
            hint = client._extra_context("现在几点", now=0)
            self.assertIn("本地时间", hint)

    def test_location_context_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings({"local_city": "上海", "local_location": "浦东"})
            client = AIClient(settings)
            hint = client._extra_context("你在哪里", now=0)
            self.assertIn("上海", hint)
            self.assertIn("浦东", hint)


if __name__ == "__main__":
    unittest.main()
