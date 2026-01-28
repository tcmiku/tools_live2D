import unittest

from backend.hotkey_hints import build_hotkey_hint


class HotkeyHintTests(unittest.TestCase):
    def test_build_hotkey_hint(self):
        settings = {
            "hotkey_toggle_pet": "Ctrl+Shift+L",
            "hotkey_note": "Ctrl+Shift+P",
            "hotkey_pomodoro": "Ctrl+Shift+T",
        }
        text = build_hotkey_hint(settings)
        self.assertIn("Ctrl+Shift+L", text)
        self.assertIn("显示/隐藏宠物", text)
        self.assertIn("Ctrl+Shift+P", text)
        self.assertIn("快速便签", text)
        self.assertIn("Ctrl+Shift+T", text)
        self.assertIn("番茄钟开关", text)


if __name__ == "__main__":
    unittest.main()
