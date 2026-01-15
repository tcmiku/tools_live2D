import unittest

from backend.pomodoro import PomodoroEngine


class PomodoroToggleTests(unittest.TestCase):
    def test_toggle_starts_and_pauses(self):
        engine = PomodoroEngine("/tmp/pomodoro.json", focus_min=1, break_min=1)
        engine.toggle()
        self.assertIn(engine.mode, ("focus", "break"))
        engine.toggle()
        self.assertEqual(engine.mode, "paused")


if __name__ == "__main__":
    unittest.main()
