import unittest

from backend.hotkeys import parse_hotkey, MOD_CONTROL, MOD_SHIFT


class HotkeyParseTests(unittest.TestCase):
    def test_parse_space(self):
        parsed = parse_hotkey("Ctrl+Shift+Space")
        self.assertIsNotNone(parsed)
        mods, key = parsed
        self.assertEqual(mods, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(key, 0x20)


if __name__ == "__main__":
    unittest.main()
