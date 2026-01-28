import unittest

from backend.focus import FocusState, adjust_state_for_pomodoro
from backend.pomodoro import reward_for_focus_minutes


class PomodoroLinkTests(unittest.TestCase):
    def test_adjust_state_blocks_sleep_during_focus(self):
        state = FocusState(
            status="sleep",
            idle_ms=200000,
            focus_seconds_today=0,
            input_type="sleep",
            window_title="",
        )
        adjusted = adjust_state_for_pomodoro(state, "focus")
        self.assertEqual(adjusted.status, "idle")

    def test_adjust_state_no_change_on_break(self):
        state = FocusState(
            status="sleep",
            idle_ms=200000,
            focus_seconds_today=0,
            input_type="sleep",
            window_title="",
        )
        adjusted = adjust_state_for_pomodoro(state, "break")
        self.assertEqual(adjusted.status, "sleep")

    def test_reward_scaling(self):
        self.assertEqual(reward_for_focus_minutes(25), 1)
        self.assertEqual(reward_for_focus_minutes(60), 1)
        self.assertEqual(reward_for_focus_minutes(5), 1)


if __name__ == "__main__":
    unittest.main()
