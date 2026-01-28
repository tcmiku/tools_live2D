import os
import tempfile
import unittest
from unittest import mock

from backend.bridge import BackendBridge
from backend.ai_client import AIClient
from backend.settings import AppSettings


class BackupRestoreTests(unittest.TestCase):
    def test_backup_creates_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            for name in ["settings.json", "stats.json", "pomodoro.json", "clipboard.json", "note.txt"]:
                with open(os.path.join(data_dir, name), "w", encoding="utf-8") as f:
                    f.write("test")
            settings = AppSettings(os.path.join(data_dir, "settings.json"))
            bridge = BackendBridge(AIClient(settings), settings=settings)
            target_zip = os.path.join(tmp, "backup.zip")
            with mock.patch("backend.bridge.os.path.abspath", return_value=tmp), \
                mock.patch("backend.bridge.os.path.dirname", return_value=tmp):
                bridge.createBackup(target_zip)
            self.assertTrue(os.path.exists(target_zip))


if __name__ == "__main__":
    unittest.main()
