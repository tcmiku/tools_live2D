import unittest
from pathlib import Path


class MoreInfoUITests(unittest.TestCase):
    def test_more_info_panel_and_gift_button(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertIn("more-info-panel", html)
        self.assertIn("gift-button", html)
        self.assertIn("info-ai-status", html)
        self.assertIn("info-ai-model", html)
        self.assertIn("info-cpu", html)
        self.assertIn("info-mem", html)
        self.assertIn("info-net", html)
        self.assertIn("info-battery", html)


if __name__ == "__main__":
    unittest.main()
