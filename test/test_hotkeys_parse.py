import unittest

from backend.hotkeys import parse_hotkey, MOD_CONTROL, MOD_SHIFT


class HotkeyParseTests(unittest.TestCase):
    def test_parse_ctrl_shift_letter(self):
        result = parse_hotkey("Ctrl+Shift+L")
        self.assertIsNotNone(result)
        modifiers, key = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(key, ord("L"))

    def test_invalid_hotkey(self):
        self.assertIsNone(parse_hotkey(""))
        self.assertIsNone(parse_hotkey("Ctrl"))
        self.assertIsNone(parse_hotkey("Ctrl+???"))


if __name__ == "__main__":
    unittest.main()
