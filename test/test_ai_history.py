import os
import tempfile
import unittest
from unittest import mock

from backend.ai_client import AIClient
from backend.settings import AppSettings


class AIHistoryTests(unittest.TestCase):
    def test_history_is_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = AppSettings(path)
            settings.set_settings({"ai_api_key": "key", "ai_base_url": "https://example.com/v1", "ai_model": "m"})
            client = AIClient(settings, max_history=2)

            def fake_post(url, headers=None, json=None, timeout=None):
                self.assertEqual(url, "https://example.com/v1/chat/completions")
                messages = json.get("messages", [])
                self.assertTrue(len(messages) >= 2)
                class Resp:
                    def raise_for_status(self_inner):
                        return None
                    def json(self_inner):
                        return {"choices": [{"message": {"content": "ok"}}]}
                return Resp()

            with mock.patch("backend.ai_client.requests.post", side_effect=fake_post):
                client.call("hi", 0)
                client.call("again", 0)

            with mock.patch("backend.ai_client.requests.post", side_effect=fake_post) as patched:
                client.call("third", 0)
                last_payload = patched.call_args.kwargs["json"]
                roles = [m["role"] for m in last_payload["messages"]]
                self.assertIn("assistant", roles)


if __name__ == "__main__":
    unittest.main()
