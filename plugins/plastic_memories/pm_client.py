from __future__ import annotations

import json
import time
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class PlasticMemoriesClient:
    def __init__(
        self,
        base_url: str,
        user_id: str,
        persona_id: str,
        template_path: str,
        source_app: str,
        timeout: float = 10.0,
        log=None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.user_id = str(user_id or "")
        self.persona_id = str(persona_id or "")
        self.template_path = str(template_path or "")
        self.source_app = str(source_app or "")
        self.timeout = float(timeout or 10.0)
        self._log = log
        self._batch_supported = True

    def _emit(self, level: str, message: str) -> None:
        if not self._log:
            return
        try:
            self._log(level, message)
        except Exception:
            return

    def _post_json(self, path: str, payload: dict, allow_status: set[int] | None = None) -> tuple[int, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8") if resp else ""
                return status, json.loads(body) if body else {}
        except HTTPError as exc:
            status = exc.code
            body = ""
            try:
                if exc.fp:
                    body = exc.fp.read().decode("utf-8")
            except Exception:
                body = ""
            if allow_status and status in allow_status:
                return status, json.loads(body) if body else {}
            raise

    def _get(self, path: str, allow_status: set[int] | None = None) -> tuple[int, str]:
        url = f"{self.base_url}{path}"
        req = Request(url, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8") if resp else ""
                return status, body
        except HTTPError as exc:
            status = exc.code
            body = ""
            try:
                if exc.fp:
                    body = exc.fp.read().decode("utf-8")
            except Exception:
                body = ""
            if allow_status and status in allow_status:
                return status, body
            raise

    def _now_iso(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def ensure_persona(self) -> bool:
        payload = {
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "template_path": self.template_path,
            "allow_overwrite": False,
        }
        try:
            self._post_json("/persona/create_from_template", payload)
            return True
        except Exception as exc:
            self._emit("warn", f"创建人格失败: {exc}")
            return False

    def recall(self, query: str) -> dict:
        payload = {
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "query": str(query or ""),
            "top_k": 8,
            "include_profile": True,
            "include_snippets": True,
            "snippets_days": 30,
            "top_k_snippets": 5,
        }
        status, data = self._post_json("/memory/recall", payload)
        if status >= 400:
            self._emit("warn", f"Recall 请求失败: status={status}")
        if isinstance(data, dict):
            return data
        return {}

    def append_messages(self, session_id: str, messages: list[dict]) -> bool:
        if not self._batch_supported:
            return self._append_single_fallback(session_id, messages)
        payload = {
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "source_app": self.source_app,
            "session_id": session_id,
            "messages": messages,
        }
        try:
            status, _data = self._post_json("/messages/append", payload, allow_status={422})
            if status == 422:
                self._batch_supported = False
                self._emit("warn", "messages/append 批量不被支持，已切换为单条追加")
                return self._append_single_fallback(session_id, messages)
            return status < 400
        except Exception as exc:
            self._emit("warn", f"批量追加失败: {exc}")
            return False

    def _append_single_fallback(self, session_id: str, messages: Iterable[dict]) -> bool:
        for item in messages:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            created_at = str(item.get("created_at", "")).strip() or self._now_iso()
            if not role or not content:
                continue
            ok = self.append_message(session_id, role, content, created_at)
            if not ok:
                return False
        return True

    def append_message(self, session_id: str, role: str, content: str, created_at: str) -> bool:
        payload = {
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "source_app": self.source_app,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": created_at or self._now_iso(),
        }
        try:
            status, _data = self._post_json("/messages/append", payload)
            if status >= 400:
                self._emit("warn", f"单条追加失败: status={status}")
                return False
            return True
        except Exception as exc:
            self._emit("warn", f"单条追加异常: {exc}")
            return False

    def write_memory_item(self, memory_type: str, key: str, content: str) -> bool:
        payload = {
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "type": memory_type,
            "key": key,
            "content": content,
        }
        if not payload.get("type") or not payload.get("key") or not payload.get("content"):
            self._emit("warn", "memory/write 参数缺失")
            return False
        try:
            status, _data = self._post_json("/memory/write", payload)
            if status >= 400:
                self._emit("warn", f"memory/write 失败: status={status}")
                return False
            return True
        except Exception as exc:
            self._emit("warn", f"memory/write 异常: {exc}")
            return False

    def health_check(self) -> tuple[bool, str]:
        try:
            status, body = self._get("/health", allow_status={404})
            if status >= 400:
                return False, f"health status={status}"
            return True, body or "ok"
        except Exception as exc:
            return False, str(exc)
