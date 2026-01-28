import unittest

from backend.passive_chat import PassiveChatEngine, PassiveChatConfig


class DummyState:
    def __init__(self, status="active", window_title="") -> None:
        self.status = status
        self.window_title = window_title
        self.focus_seconds_today = 0


class PassiveChatContextTests(unittest.TestCase):
    def test_context_ide(self):
        engine = PassiveChatEngine(PassiveChatConfig())
        state = DummyState(window_title="Visual Studio Code")
        msg = engine.get_contextual_message(state, state.window_title, now=0)
        self.assertIn("代码", msg)

    def test_context_browser(self):
        engine = PassiveChatEngine(PassiveChatConfig())
        state = DummyState(window_title="Chrome - Docs")
        msg = engine.get_contextual_message(state, state.window_title, now=0)
        self.assertIn("查资料", msg)

    def test_context_design(self):
        engine = PassiveChatEngine(PassiveChatConfig())
        state = DummyState(window_title="Figma")
        msg = engine.get_contextual_message(state, state.window_title, now=0)
        self.assertIn("设计", msg)

    def test_context_sleep(self):
        engine = PassiveChatEngine(PassiveChatConfig())
        state = DummyState(status="sleep", window_title="")
        msg = engine.get_contextual_message(state, state.window_title, now=0)
        self.assertIn("休息", msg)


if __name__ == "__main__":
    unittest.main()
