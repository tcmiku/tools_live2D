import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError

from plugins.plastic_memories.pm_client import PlasticMemoriesClient
from plugins.plastic_memories.pm_policy import MemoryPolicy


class _DummyResponse:
    def __init__(self, status=200, body="{}") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_422_error(url: str) -> HTTPError:
    return HTTPError(url, 422, "Unprocessable Entity", hdrs=None, fp=io.BytesIO(b"{}"))


class PlasticMemoriesAppendTests(unittest.TestCase):
    def test_append_fallback_to_single(self) -> None:
        client = PlasticMemoriesClient(
            base_url="http://127.0.0.1:8007",
            user_id="local",
            persona_id="persona_1",
            template_path="personas/persona_1",
            source_app="tools_live2D",
        )
        messages = [
            {"role": "user", "content": "hi", "created_at": "2026-01-29T10:00:00Z"},
            {"role": "assistant", "content": "ok", "created_at": "2026-01-29T10:00:01Z"},
        ]
        calls = []

        def _side_effect(request, timeout=10):
            calls.append(request)
            if len(calls) == 1:
                raise _make_422_error("http://127.0.0.1:8007/messages/append")
            return _DummyResponse(200, "{}")

        with mock.patch("plugins.plastic_memories.pm_client.urlopen", side_effect=_side_effect):
            ok = client.append_messages("session-1", messages)

        self.assertTrue(ok)
        self.assertGreaterEqual(len(calls), 2)
        payload = json.loads(calls[1].data.decode("utf-8"))
        self.assertIn("role", payload)
        self.assertIn("content", payload)
        self.assertIn("created_at", payload)


class PlasticMemoriesWriteTests(unittest.TestCase):
    def test_write_memory_item_payload(self) -> None:
        client = PlasticMemoriesClient(
            base_url="http://127.0.0.1:8007",
            user_id="local",
            persona_id="persona_1",
            template_path="personas/persona_1",
            source_app="tools_live2D",
        )
        captured = {}

        def _side_effect(request, timeout=10):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _DummyResponse(200, "{}")

        with mock.patch("plugins.plastic_memories.pm_client.urlopen", side_effect=_side_effect):
            ok = client.write_memory_item("preferences", "user_name", "小明")

        self.assertTrue(ok)
        self.assertIn("type", captured)
        self.assertIn("key", captured)
        self.assertIn("content", captured)


class PlasticMemoriesPolicyTests(unittest.TestCase):
    def test_policy_extract_and_dedup(self) -> None:
        policy = MemoryPolicy()
        user_text = "叫我小明，以后用中文，输出步骤列表MVP，叫我小明"
        items = policy.extract(user_text, "")
        items_map = {item.key: item.content for item in items}
        self.assertEqual(len(items_map), 3)
        self.assertEqual(items_map.get("user_name"), "小明")
        self.assertEqual(items_map.get("language"), "zh-CN")
        self.assertEqual(items_map.get("response_style"), "步骤列表/最小可运行/MVP")


if __name__ == "__main__":
    unittest.main()
