import unittest

from backend.pomodoro import PomodoroEngine


class PomodoroUpdateTests(unittest.TestCase):
    def test_update_exists(self):
        engine = PomodoroEngine("/tmp/pomodoro.json", focus_min=1, break_min=1)
        state = engine.update()
        self.assertIsNotNone(state)


if __name__ == "__main__":
    unittest.main()
