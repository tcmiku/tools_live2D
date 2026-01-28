import os
import tempfile
import unittest
from unittest import mock

from backend.ai_client import AIClient
from backend.settings import AppSettings


class AIClientConfigTests(unittest.TestCase):
    def test_missing_api_key_returns_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings({"ai_api_key": ""})
            client = AIClient(settings)
            msg = client.call("hi", 0)
            self.assertIn("API Key", msg)

    def test_uses_settings_base_url_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings({
                "ai_api_key": "test-key",
                "ai_base_url": "https://example.com/v1",
                "ai_model": "test-model",
            })
            client = AIClient(settings)

            def fake_post(url, headers=None, json=None, timeout=None):
                self.assertEqual(url, "https://example.com/v1/chat/completions")
                self.assertEqual(json.get("model"), "test-model")

                class FakeResp:
                    def raise_for_status(self_inner):
                        return None

                    def json(self_inner):
                        return {"choices": [{"message": {"content": "ok"}}]}

                return FakeResp()

            with mock.patch("backend.ai_client.requests.post", side_effect=fake_post):
                reply = client.call("hello", 0)
            self.assertEqual(reply, "ok")

    def test_fallback_to_next_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings(
                {
                    "ai_providers": [
                        {
                            "name": "bad",
                            "base_url": "https://bad.example.com/v1",
                            "model": "bad-model",
                            "api_key": "bad-key",
                            "enabled": True,
                        },
                        {
                            "name": "good",
                            "base_url": "https://good.example.com/v1",
                            "model": "good-model",
                            "api_key": "good-key",
                            "enabled": True,
                        },
                    ]
                }
            )
            client = AIClient(settings)

            def fake_post(url, headers=None, json=None, timeout=None):
                if "bad.example.com" in url:
                    raise RuntimeError("fail")
                self.assertEqual(url, "https://good.example.com/v1/chat/completions")

                class FakeResp:
                    def raise_for_status(self_inner):
                        return None

                    def json(self_inner):
                        return {"choices": [{"message": {"content": "ok2"}}]}

                return FakeResp()

            with mock.patch("backend.ai_client.requests.post", side_effect=fake_post):
                reply = client.call("hello", 0)
            self.assertEqual(reply, "ok2")

    def test_test_connection_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings(
                {
                    "ai_providers": [
                        {
                            "name": "good",
                            "base_url": "https://good.example.com/v1",
                            "model": "good-model",
                            "api_key": "good-key",
                            "enabled": True,
                        }
                    ]
                }
            )
            client = AIClient(settings)

            def fake_post(url, headers=None, json=None, timeout=None):
                self.assertEqual(url, "https://good.example.com/v1/chat/completions")

                class FakeResp:
                    def raise_for_status(self_inner):
                        return None

                    def json(self_inner):
                        return {"choices": [{"message": {"content": "pong"}}]}

                return FakeResp()

            with mock.patch("backend.ai_client.requests.post", side_effect=fake_post):
                ok, message = client.test_connection()
            self.assertTrue(ok)
            self.assertIn("连接成功", message)

    def test_test_connection_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings(
                {
                    "ai_providers": [
                        {
                            "name": "bad",
                            "base_url": "https://bad.example.com/v1",
                            "model": "bad-model",
                            "api_key": "bad-key",
                            "enabled": True,
                        }
                    ]
                }
            )
            client = AIClient(settings)

            with mock.patch("backend.ai_client.requests.post", side_effect=RuntimeError("fail")):
                ok, message = client.test_connection()
            self.assertFalse(ok)
            self.assertIn("连接失败", message)


if __name__ == "__main__":
    unittest.main()
