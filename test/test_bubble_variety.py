import unittest

from backend.passive_chat import PassiveChatEngine, PassiveChatConfig


class PassiveChatVarietyTests(unittest.TestCase):
    def test_random_samples_multiple(self):
        engine = PassiveChatEngine(PassiveChatConfig())
        samples = engine._maybe_random(0)
        self.assertTrue(samples)

    def test_contextual_variants(self):
        engine = PassiveChatEngine(PassiveChatConfig())
        class DummyState:
            status = "active"
        msg = engine.get_contextual_message(DummyState(), "vscode", now=0)
        self.assertTrue(msg)


if __name__ == "__main__":
    unittest.main()
