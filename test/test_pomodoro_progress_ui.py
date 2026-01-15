import unittest
from pathlib import Path


class PomodoroUIProgressTests(unittest.TestCase):
    def test_progress_bar_exists(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertIn("pomodoro-progress", html)


if __name__ == "__main__":
    unittest.main()
