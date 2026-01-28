import unittest
from pathlib import Path


class QuickToolbarUITests(unittest.TestCase):
    def test_quick_toolbar_buttons(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertIn("quick-toolbar", html)
        self.assertIn("quick-toggle", html)
        self.assertIn("quick-note", html)
        self.assertIn("quick-pomodoro", html)
        self.assertIn("quick-settings", html)


if __name__ == "__main__":
    unittest.main()
