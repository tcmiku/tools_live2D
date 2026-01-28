import unittest
from unittest import mock

from backend.focus import FocusEngine


class DummyStats:
    def __init__(self) -> None:
        self.value = 0

    def add_focus_second(self, seconds: int = 1) -> None:
        self.value += seconds

    def get_today_focus_seconds(self) -> int:
        return self.value


class InteractionEventTests(unittest.TestCase):
    def test_typing_event(self):
        engine = FocusEngine(stats=DummyStats())
        with mock.patch("backend.focus.get_idle_milliseconds", return_value=1000), \
            mock.patch("backend.focus.get_cursor_pos", return_value=(10, 10)), \
            mock.patch("backend.focus.get_foreground_window_title", return_value=(1, "Editor")), \
            mock.patch("backend.focus.time.time", return_value=100):
            state = engine.update()
            events = engine.get_interaction_events(state)
        self.assertIn("typing", events)

    def test_idle_event(self):
        engine = FocusEngine(stats=DummyStats())
        with mock.patch("backend.focus.get_idle_milliseconds", return_value=200000), \
            mock.patch("backend.focus.get_cursor_pos", return_value=(10, 10)), \
            mock.patch("backend.focus.get_foreground_window_title", return_value=(1, "Editor")), \
            mock.patch("backend.focus.time.time", return_value=100):
            state = engine.update()
            events = engine.get_interaction_events(state)
        self.assertIn("idle", events)

    def test_switch_event(self):
        engine = FocusEngine(stats=DummyStats())
        with mock.patch("backend.focus.get_idle_milliseconds", return_value=0), \
            mock.patch("backend.focus.get_cursor_pos", return_value=(10, 10)):
            for t, handle in [(200, 1), (205, 2), (210, 3)]:
                with mock.patch("backend.focus.get_foreground_window_title", return_value=(handle, "Editor")), \
                    mock.patch("backend.focus.time.time", return_value=t):
                    engine.update()
            with mock.patch("backend.focus.time.time", return_value=215):
                state = engine.update()
                events = engine.get_interaction_events(state)
        self.assertIn("switch", events)

    def test_browser_event(self):
        engine = FocusEngine(stats=DummyStats())
        with mock.patch("backend.focus.get_idle_milliseconds", return_value=0), \
            mock.patch("backend.focus.get_cursor_pos", return_value=(10, 10)), \
            mock.patch("backend.focus.get_foreground_window_title", return_value=(1, "Chrome - Test")), \
            mock.patch("backend.focus.time.time", return_value=400):
            state = engine.update()
            events = engine.get_interaction_events(state)
        self.assertIn("browser", events)


if __name__ == "__main__":
    unittest.main()
