import os
import tempfile
import unittest
from unittest import mock

from backend.launchers import LauncherManager


class LauncherManagerTests(unittest.TestCase):
    def test_save_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "launchers.json")
            manager = LauncherManager(path)
            manager.save_launcher({"name": "GitHub", "type": "web", "url": "https://github.com", "tags": ["开发"]})
            manager.save_launcher({"name": "VS Code", "type": "app", "path": "code.exe", "tags": ["开发", "编辑器"]})
            results = manager.search("git")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "GitHub")
            results = manager.search("开发")
            self.assertEqual(len(results), 2)

    def test_execute_web_and_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "launchers.json")
            manager = LauncherManager(path)
            web = manager.save_launcher({"name": "GitHub", "type": "web", "url": "https://github.com"})
            app = manager.save_launcher({"name": "App", "type": "app", "path": "app.exe", "args": ["--x"]})
            with mock.patch("backend.launchers.webbrowser.open") as open_mock:
                result = manager.execute(web["id"])
            self.assertTrue(result.ok)
            open_mock.assert_called_once()
            with mock.patch("backend.launchers.subprocess.Popen") as popen_mock:
                result = manager.execute(app["id"])
            self.assertTrue(result.ok)
            popen_mock.assert_called_once()

    def test_group_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "launchers.json")
            manager = LauncherManager(path)
            web = manager.save_launcher({"name": "GitHub", "type": "web", "url": "https://github.com"})
            group = manager.save_launcher(
                {
                    "name": "Suite",
                    "type": "group",
                    "items": [{"launcher_id": web["id"]}],
                }
            )
            with mock.patch("backend.launchers.webbrowser.open") as open_mock:
                result = manager.execute(group["id"])
            self.assertTrue(result.ok)
            open_mock.assert_called_once()

    def test_recent_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "launchers.json")
            manager = LauncherManager(path)
            a = manager.save_launcher({"name": "A", "type": "web", "url": "https://a.com"})
            b = manager.save_launcher({"name": "B", "type": "web", "url": "https://b.com"})
            with mock.patch("backend.launchers.webbrowser.open"):
                manager.execute(a["id"])
                manager.execute(b["id"])
                manager.execute(a["id"])
            recent = manager.get_recent_ids()
            self.assertEqual(recent[0], a["id"])


if __name__ == "__main__":
    unittest.main()
