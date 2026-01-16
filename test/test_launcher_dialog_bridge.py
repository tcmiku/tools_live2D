import unittest

from backend.ai_client import AIClient
from backend.bridge import BackendBridge
from backend.settings import AppSettings


class LauncherDialogBridgeTests(unittest.TestCase):
    def test_open_launcher_dialog_calls_handler(self):
        called = {"ok": False}

        def handler():
            called["ok"] = True

        settings = AppSettings()
        bridge = BackendBridge(AIClient(settings), settings=settings)
        bridge.set_open_launcher_dialog(handler)
        bridge.openLauncherDialog()
        self.assertTrue(called["ok"])


if __name__ == "__main__":
    unittest.main()
