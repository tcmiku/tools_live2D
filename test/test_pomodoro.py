import os
import tempfile
import unittest
from unittest import mock

from backend.pomodoro import PomodoroEngine


class PomodoroEngineTests(unittest.TestCase):
    def test_start_and_update_reduces_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "pomodoro.json")
            engine = PomodoroEngine(data_path, focus_min=25, break_min=5)
            with mock.patch("backend.pomodoro.time.time", side_effect=[1000.0, 1010.0]):
                engine.start()
                state = engine.update()
            self.assertEqual(state.mode, "focus")
            self.assertEqual(state.remaining_sec, 25 * 60 - 10)

    def test_set_durations_clamps_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "pomodoro.json")
            engine = PomodoroEngine(data_path, focus_min=25, break_min=5)
            with mock.patch("backend.pomodoro.time.time", return_value=1000.0):
                engine.start()
            engine._remaining_sec = 900
            engine.set_durations(10, 2)
            state = engine.update()
            self.assertEqual(state.remaining_sec, 600)

    def test_focus_to_break_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "pomodoro.json")
            engine = PomodoroEngine(data_path, focus_min=1, break_min=2)
            with mock.patch("backend.pomodoro.time.time", side_effect=[1000.0, 1060.0]):
                engine.start()
                state = engine.update()
            self.assertEqual(state.mode, "break")
            self.assertEqual(state.remaining_sec, 2 * 60)
            self.assertEqual(state.count_today, 1)


if __name__ == "__main__":
    unittest.main()
