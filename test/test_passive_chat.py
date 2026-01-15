import unittest

from backend.passive_chat import PassiveChatEngine, PassiveChatConfig


class DummyState:
    def __init__(self, focus_seconds_today: int = 0) -> None:
        self.focus_seconds_today = focus_seconds_today


class PassiveChatTests(unittest.TestCase):
    def test_focus_message_interval(self):
        config = PassiveChatConfig(enabled=True, focus_enabled=True, focus_interval_min=1)
        engine = PassiveChatEngine(config)
        state = DummyState(focus_seconds_today=120)
        self.assertEqual(engine.tick(state, now=0, hour=9), [])
        self.assertEqual(engine.tick(state, now=60, hour=9), [])
        messages = engine.tick(state, now=120, hour=9)
        self.assertTrue(any("רע" in msg for msg in messages))

    def test_blessing_once_per_day(self):
        config = PassiveChatConfig(enabled=True, blessing_enabled=True, random_enabled=False, focus_enabled=False)
        engine = PassiveChatEngine(config)
        state = DummyState()
        messages = engine.tick(state, now=0, hour=8)
        self.assertTrue(any("�簲" in msg for msg in messages))
        messages_again = engine.tick(state, now=10, hour=8)
        self.assertFalse(any("�簲" in msg for msg in messages_again))

    def test_random_interval(self):
        config = PassiveChatConfig(enabled=True, random_enabled=True, interval_min=1, focus_enabled=False, blessing_enabled=False)
        engine = PassiveChatEngine(config)
        state = DummyState()
        self.assertEqual(engine.tick(state, now=0, hour=12), [])
        messages = engine.tick(state, now=60, hour=12)
        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()
