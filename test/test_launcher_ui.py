import unittest
from pathlib import Path


class LauncherUiTests(unittest.TestCase):
    def test_launcher_panel_present(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertIn('id="launcher-panel"', html)
        self.assertIn('id="tool-launcher"', html)
        self.assertIn("启动器", html)

    def test_launcher_panel_ids_present(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertIn('id="launcher-search"', html)
        self.assertIn('id="launcher-add"', html)
        self.assertIn('id="launcher-import"', html)
        self.assertIn('id="launcher-export"', html)
        self.assertIn('id="launcher-desktop"', html)
        self.assertIn('id="launcher-recent"', html)
        self.assertIn('id="launcher-list"', html)


if __name__ == "__main__":
    unittest.main()
