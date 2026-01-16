from __future__ import annotations

import logging
import os
import time
import threading
from typing import TYPE_CHECKING

import requests

try:
    from .settings import AppSettings
except ImportError:
    from settings import AppSettings


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分钟 {sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分钟"


class AIClient:
    def __init__(self, settings: "AppSettings | None" = None, max_history: int = 6) -> None:
        self._settings = settings
        self._env_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._env_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self._env_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._history: list[dict] = []
        self._max_history = max(0, int(max_history))
        self._lock = threading.Lock()

    def _load_providers(self) -> list[dict]:
        if not self._settings:
            if self._env_api_key:
                return [
                    {
                        "name": "env",
                        "base_url": self._env_base_url,
                        "model": self._env_model,
                        "api_key": self._env_api_key,
                        "enabled": True,
                    }
                ]
            return []
        data = self._settings.get_settings()
        providers = data.get("ai_providers", [])
        normalized = []
        if isinstance(providers, list):
            for item in providers:
                if not isinstance(item, dict):
                    continue
                enabled = bool(item.get("enabled", True))
                api_key = str(item.get("api_key", "")).strip()
                base_url = str(item.get("base_url", "")).strip().rstrip("/")
                model = str(item.get("model", "")).strip()
                if not enabled:
                    continue
                if not api_key:
                    continue
                normalized.append(
                    {
                        "name": str(item.get("name", "OpenAI兼容")),
                        "base_url": base_url or self._env_base_url,
                        "model": model or self._env_model,
                        "api_key": api_key,
                    }
                )
        if not normalized and self._env_api_key:
            normalized.append(
                {
                    "name": "env",
                    "base_url": self._env_base_url,
                    "model": self._env_model,
                    "api_key": self._env_api_key,
                }
            )
        return normalized

    def call(self, user_text: str, focus_seconds_today: int, plugin_context: list[str] | None = None) -> str:
        providers = self._load_providers()
        if not providers:
            return "AI 未配置，请先在 AI 设置中填写 API Key。"

        focus_hint = _format_duration(focus_seconds_today)
        extra_hint = self._extra_context(user_text)
        favor_hint = self._favor_hint()
        mood_hint = self._mood_hint()
        plugin_hint = ""
        if plugin_context:
            context_text = "\n".join([text for text in plugin_context if text])
            if context_text:
                plugin_hint = f"插件上下文：\n{context_text}\n"
        system_prompt = (
            "你是一只友好的 Live2D 桌面宠物。"
            "语气轻松、鼓励用户专注、回答简洁。"
            "可以参考今日专注时间作为上下文，但不要每句话都提到。"
            f"今日专注时间：{focus_hint}。"
            f"{favor_hint}"
            f"{mood_hint}"
            f"{extra_hint}"
            f"{plugin_hint}"
        )

        with self._lock:
            history = list(self._history)
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.7,
        }

        last_error = None
        for provider in providers:
            base_url = provider["base_url"]
            api_key = provider["api_key"]
            model = provider["model"]
            payload["model"] = model
            try:
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                with self._lock:
                    self._history.append({"role": "user", "content": user_text})
                    self._history.append({"role": "assistant", "content": reply})
                    if self._max_history > 0 and len(self._history) > self._max_history * 2:
                        self._history = self._history[-self._max_history * 2 :]
                return reply
            except Exception as exc:
                last_error = exc
                logging.exception("ai request failed: provider=%s error=%s", provider.get("name"), exc)
                continue
        logging.exception("ai request failed all providers: %s", last_error)
        return "抱歉，暂时无法连接 AI 服务，请稍后再试。"

    def _favor_hint(self) -> str:
        if not self._settings:
            return ""
        data = self._settings.get_settings()
        try:
            favor = int(data.get("favor", 50))
        except (TypeError, ValueError):
            favor = 50
        favor = max(0, min(100, favor))
        if favor >= 75:
            return "好感度偏高，语气更亲近一些。"
        if favor <= 25:
            return "好感度偏低，语气保持礼貌克制。"
        return "好感度中等，语气自然友好。"

    def _mood_hint(self) -> str:
        if not self._settings:
            return ""
        data = self._settings.get_settings()
        try:
            mood = int(data.get("mood", 60))
        except (TypeError, ValueError):
            mood = 60
        mood = max(0, min(100, mood))
        if mood >= 80:
            return "心情很好，语气更轻快活泼。"
        if mood >= 60:
            return "心情不错，语气温柔友好。"
        if mood >= 40:
            return "心情平静，语气平和自然。"
        if mood >= 20:
            return "心情有点低落，语气多些鼓励。"
        return "心情有些孤独，语气更关心陪伴。"

    def _extra_context(self, user_text: str, now: float | None = None) -> str:
        text = user_text.lower()
        wants_time = any(key in text for key in ["时间", "几点", "日期", "today", "date", "time"])
        wants_location = any(key in text for key in ["位置", "在哪里", "location", "city", "地点"])
        if not wants_time and not wants_location:
            return ""
        if now is None:
            now = time.time()
        parts = []
        if wants_time:
            parts.append(f"本地时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}。")
        if wants_location:
            location = self._get_location_hint()
            parts.append(f"地理位置：{location}。")
        return "".join(parts)

    def _get_location_hint(self) -> str:
        if not self._settings:
            return "未配置"
        data = self._settings.get_settings()
        city = str(data.get("local_city", "")).strip()
        detail = str(data.get("local_location", "")).strip()
        if city and detail:
            return f"{city} {detail}"
        if city:
            return city
        if detail:
            return detail
        return "未配置"

    def test_connection(self) -> tuple[bool, str]:
        providers = self._load_providers()
        if not providers:
            return False, "未配置可用的 API Key。"
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "ping"},
            ],
            "temperature": 0.0,
            "max_tokens": 1,
        }
        last_error = None
        for provider in providers:
            base_url = provider["base_url"]
            api_key = provider["api_key"]
            model = provider["model"]
            payload["model"] = model
            try:
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=10,
                )
                resp.raise_for_status()
                return True, f"连接成功：{provider.get('name', 'provider')}"
            except Exception as exc:
                last_error = exc
                logging.exception("ai test failed: provider=%s error=%s", provider.get("name"), exc)
                continue
        return False, f"连接失败：{last_error}"
